"""Original pre-SCHEDULE packet preparation over the reviewed owned resources.

Trusted ordinary-memory callbacks only; no native default, arming or cleanup.
Input-byte pins are not a substitute for the future executable loader closure.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import threading

import control_images as CI
from channel_objects import ChannelObjects, disjoint
from channel_resources import ArenaSession
from data_resources import DataResources
from initial_data_upload import DataUploadResult, InitialDataUpload
from mapping_protocol import MapSpec
from preparation_upload import InitialUpload, Span
from replacement_inputs import arena as A

P = CI.P
HERE = Path(__file__).resolve().parent
INPUTS_SHA = '00f62a97026233e9c0da5c173f406a42e01efd4370dbfc733206334c213243bf'


def input_pins():
    raw = P.S.pinned((HERE.parent / 'data' / 'packet_inputs.json'), INPUTS_SHA)
    entries = P.S.parse(raw)['entries']
    A.require(type(entries) is list and len(entries) == 61, 'PACKET_INPUT_SET')
    for entry in entries:
        P.S.pinned(Path(entry['path']), entry['sha256'], entry['size'], entry['mode'])


def value_image(value):
    """Type-sensitive snapshot of value fields; never traverse resource objects."""
    t = type(value)
    if t in (type(None), bool, int, str, bytes, float):
        return t, value
    if t in (list, tuple):
        return t, tuple(value_image(v) for v in value)
    if t is dict:
        return t, tuple((value_image(k), value_image(v)) for k, v in value.items())
    if t in (set, frozenset):
        return t, frozenset(value_image(v) for v in value)
    if t in (MapSpec, DataUploadResult):
        return t, value_image(vars(value))
    A.require(False, 'PACKET_VALUE_TYPE', type=t.__name__)


@dataclass(frozen=True)
class PreparationResult:
    prefix: int
    signal: int
    control_sha256: str
    data_sha256: tuple
    copies: int
    status: str = 'CPU_PACKET_PREPARATION_VERIFIED'
    gpu_executed: bool = False


class PacketPreparation:
    def __init__(self, resources, read_bytes, write_bytes):
        A.require(type(resources) is DataResources and resources.phase == 'READY'
                  and not resources.busy and resources.thread == threading.get_ident(),
                  'PACKET_RESOURCES')
        A.require(callable(read_bytes) and callable(write_bytes), 'PACKET_CALLBACKS')
        o = resources.objects
        A.require(type(o) is ChannelObjects and type(o._session) is ArenaSession,
                  'PACKET_COMPONENT_TYPE')
        A.require(getattr(o, '_packet_preparation', None) is None, 'PACKET_EXISTS')
        A.require(all(getattr(o, name, None) is None for name in
                      ('_initial_schedule','_mapping_transport','_initial_publication')), 'PACKET_TOO_LATE')
        A.require(getattr(o, '_initial_upload', None) is None
                  and getattr(resources, '_initial_data_upload', None) is None, 'PACKET_UPLOADER_CHANGED')
        self.data, self.objects, self.session = resources, o, o._session
        self.tree, self.backend = resources.tree, resources.backend
        self.mappings, self.owners, self.control = resources.mappings, resources.owners, resources.control
        self.layout, self.abi = resources.layout, resources.abi
        self.bindings = resources.binding()
        self.arena, self.channel = self.session.binding(), self.objects.binding()
        self.config, self.resource_config = o.config, self.session.config
        self.allocators = tuple(resources.allocators)
        self.read_bytes, self.write_bytes = read_bytes, write_bytes
        self.callbacks = (read_bytes, write_bytes)
        self.thread, self.busy, self.copying = threading.get_ident(), False, False
        self.phase, self.failure, self.result = 'NEW', None, None
        self.data_upload, self.control_upload = None, None
        self.completed_uploads, self.copy_failure = (), None
        self.inputs, self.control_image, self.expected_data, self.expected_userd = None, None, None, None
        self.prefix, self.signal = None, None
        self.events, self.queue, self.cursor = [], (), 0
        self.expectations = None
        self.parents = tuple(self.owners)
        self.parent_undo = tuple(x.undo for x in self.parents)
        self.parent_values = value_image([(x.label, x.requested, x.returned) for x in self.parents])
        maps = (self.session._cpu_mapping, self.objects._usermode_mapping,
                *(b.mapping for b in self.bindings))
        self.mapping_rows = tuple((b, self.mappings.records[b.mapping_id],
                                  self.mappings.records[b.mapping_id].spec,
                                  self.mappings.records[b.mapping_id].backing)
                                 for b in maps)
        self.refs = self._references()
        self.values = self._values()
        o._packet_preparation = self
        try:
            self._check(False)
        except BaseException as exc:
            self._fail(exc)
            raise

    def _references(self):
        d, o, s, t = self.data, self.objects, self.session, self.tree
        return (d.objects, d.session, d.tree, d.backend, d.mappings, d.owners,
                d.control, d.layout, d.abi, d._result, o._session, o._tree,
                o.config, o.abi, o.backend, o.owners, o._binding,
                s._tree, s._arena, s._mappings, s.config, s._binding,
                t.backend, t.owners, t.card, t._handles, t._instances, t.abi,
                s._cpu_mapping, o._usermode_mapping, *d.allocators, *d.requests,
                *d.bindings)

    def _values(self):
        return value_image({
            'target': vars(self.tree.card), 'uuid': self.tree.uuid,
            'handles': vars(self.tree._handles), 'instances': vars(self.tree._instances),
            'config': vars(self.objects.config), 'resource_config': vars(self.session.config),
            'arena': vars(self.arena), 'channel': vars(self.channel),
            'layout': vars(self.layout), 'objects_observed': self.objects.observed,
            'allocators': [(vars(a.req), a.observed) for a in (self.control, *self.allocators)],
            'data': [(b.role, b.memory, b.cpu_base, b.gpu_base, b.allocation_size,
                      b.logical_size, b.payload_offset) for b in self.bindings],
            'mappings': [(vars(b), vars(spec), {k:v for k,v in vars(backing).items() if k != 'owner'},
                          rec.fingerprint, rec.fd, rec.rm_address)
                         for b, rec, spec, backing in self.mapping_rows]})

    def _check(self, data_busy):
        d, o, s, t = self.data, self.objects, self.session, self.tree
        A.require(threading.get_ident() == self.thread and d.busy is data_busy,
                  'PACKET_BUSY_BINDING')
        A.require(o._packet_preparation is self and self.read_bytes is self.callbacks[0]
                  and self.write_bytes is self.callbacks[1], 'PACKET_ASSOCIATION')
        refs = self._references()
        A.require(len(refs) == len(self.refs) and all(x is y for x,y in zip(refs, self.refs)),
                  'PACKET_REFERENCE_CHANGED')
        A.require(d.phase == 'READY' and o.phase == 'PREPARED' and s.phase == 'ARENA_READY'
                  and t.phase == 'IDENTIFIED' and self.backend.phase == 'ACTIVE'
                  and not self.backend.pending and self.mappings.phase == 'ACTIVE', 'PACKET_PHASE')
        A.require(all(getattr(o, name, None) is None for name in
                      ('_initial_schedule', '_mapping_transport', '_initial_publication')),
                  'PACKET_TOO_LATE')
        A.require(getattr(d, '_initial_data_upload', None) is self.data_upload
                  and getattr(o, '_initial_upload', None) is self.control_upload,
                  'PACKET_UPLOADER_CHANGED')
        if self.expectations is not None:
            actual = (self.inputs,self.control_image,self.expected_data,self.expected_userd,self.queue)
            A.require(all(x is y for x,y in zip(actual,self.expectations)), 'PACKET_EXPECTATION_CHANGED')
            A.require(type(self.prefix) is int and type(self.signal) is int
                      and (self.prefix,self.signal) == self.parameters, 'PACKET_PARAMETERS_CHANGED')
        for uploader in (self.data_upload,self.control_upload):
            if uploader is not None:
                for name, fn in (('read_bytes',PacketPreparation._read),('write_bytes',PacketPreparation._write)):
                    method = getattr(uploader,name)
                    A.require(getattr(method,'__self__',None) is self
                              and getattr(method,'__func__',None) is fn, 'PACKET_COPY_ADAPTER_CHANGED')
        for uploader, result, snapshot in self.completed_uploads:
            A.require(uploader.phase == 'DONE' and uploader.result is result
                      and value_image(result) == snapshot, 'PACKET_UPLOAD_RESULT')
        # This call deliberately preserves the lower layer's UNCERTAIN marking.
        d._context()
        A.require(len(self.owners) == len(self.parents)
                  and all(x is y for x,y in zip(self.owners, self.parents)), 'PACKET_LEDGER')
        A.require(all(x.state == A.CERTAIN and x.undo is u for x,u in zip(self.parents, self.parent_undo))
                  and value_image([(x.label,x.requested,x.returned) for x in self.parents]) == self.parent_values,
                  'PACKET_OWNER_CHANGED')
        for b, rec, spec, backing in self.mapping_rows:
            A.require(self.mappings.records.get(b.mapping_id) is rec and rec.spec is spec
                      and rec.backing is backing and rec.binding is b, 'PACKET_MAPPING_CHANGED')
            A.require(self.mappings.validate_binding(b) is b
                      and self.mappings._range(rec)['state'] == 'M1_MATERIALIZED', 'PACKET_MAPPING_STATE')
            self.mappings._fd(rec)
            rows = self.backend._snapshot(b.cpu_base, b.length)
            A.require(len(rows) == 1 and rows[0].start == b.cpu_base
                      and rows[0].end == b.cpu_base + b.length and rows[0].perms == 'rw-s'
                      and rows[0].path == rec.fingerprint[4], 'PACKET_MAPPING_VMA')
        A.require(self._values() == self.values, 'PACKET_VALUE_CHANGED')
        for allocator, mapped in ((self.control,self.session._cpu_mapping),
                                  *((b.allocator,b.mapping) for b in self.bindings)):
            backing = self.mappings.records[mapped.mapping_id].backing
            request = allocator.req
            A.validate_request(request,self.abi)
            A.require(allocator.phase == A.OPEN and allocator.backend is self.backend
                      and allocator.owners is self.owners and allocator.abi is self.abi,
                      'PACKET_ALLOCATOR_BINDING')
            h = self.tree._handles
            A.require((request.h_client,request.h_device,request.h_subdevice,request.h_vas,
                       request.gpu_uuid,request.rm_ctrl_fd) ==
                      (h.client,h.device,h.subdevice,h.vas,self.tree.uuid,self.backend.fds['ctl'])
                      and request.h_memory == backing.memory
                      and request.memory_class == backing.memory_class,
                      'PACKET_ALLOCATOR_TARGET')
            location = A.field_value(allocator.observed['attr'],self.abi.const('NVOS32_ATTR_LOCATION_SHIFT'),
                                     self.abi.const('NVOS32_ATTR_LOCATION_MASK'))
            A.require(location == backing.location == self.abi.const('NVOS32_ATTR_LOCATION_PCI')
                      and allocator.observed['format'] == self.abi.const('NV_MMU_PTE_KIND_GENERIC_MEMORY'),
                      'PACKET_ALLOCATION_PROFILE')
        for b in self.bindings:
            a, back = b.allocator, self.mappings.records[b.mapping.mapping_id].backing
            A.require(a.req.base == b.gpu_base == a.observed['gpu_base'] == b.cpu_base
                      and a.observed['arena_size'] == b.allocation_size == back.size
                      and b.memory == back.memory == b.owner.returned and back.owner is b.owner,
                      'PACKET_DATA_ALLOCATION')
        input_pins()

    def _derive(self, prefix):
        arena, channel = self.arena, self.channel
        affine = type(self.layout) is P.AI.D.AffineLayout
        if affine:
            A.require(type(prefix) is int and prefix == 1, 'AFFINE_PREFIX')
        work = self.layout if affine else P.W.plan(self.layout)
        placement_type = P.AI.Placement if affine else P.C.ModelPlacement
        placements = tuple(placement_type(b.role,b.gpu_base,b.allocation_size,
                                             b.logical_size,b.payload_offset) for b in self.bindings)
        spans = [(arena.gpu_base, arena.size)] + [(b.gpu_base,b.allocation_size) for b in self.bindings]
        extras = [(channel.usermode_base, self.objects._usermode_mapping.length)]
        if channel.region_length:
            extras.append((channel.region_base, channel.region_length))
        va = self.control.observed['va_base'], self.control.observed['va_size']
        for i,(base,size) in enumerate(spans):
            A.contains(base,size,*va)
            A.require(base > 0 and base + size <= 1 << 40, 'PACKET_VA_SPAN')
            A.require(all(disjoint(base,size,b,n) for b,n in spans[:i] + extras), 'PACKET_ALIAS')
        A.require(arena.cpu_base == arena.gpu_base
                  and channel.ring_address == arena.gpu_base + self.config.ring_offset
                  and channel.userd_address == arena.cpu_base + self.config.userd_offset,
                  'PACKET_CONTROL_BINDING')
        sent = self.tree.images.channel(self.tree._handles, self.tree._instances,
                    arena.gpu_base, arena.size, self.config.ring_offset, self.config.userd_offset)
        expected = self.abi.struct(sent.parameter_type).unpack(sent.parameters)
        observed = self.objects.observed['channel']
        fields = ('gpFifoOffset','gpFifoEntries','flags','hContextShare','hVASpace',
                  'hUserdMemory','userdOffset','engineType','subDeviceId')
        A.require(expected['gpFifoEntries'] == 8 and all((self.tree.images.channel_flags_match(expected[k], observed[k])
                       if k == 'flags' else value_image(observed[k]) == value_image(expected[k]))
                  for k in fields), 'PACKET_CHANNEL_BINDING')
        layout = P.L.plan(work, P.L.ModelArena(arena.gpu_base,arena.size,
                              self.config.ring_offset,self.config.userd_offset,P.byte_length(prefix)))
        refs = P.L.references(layout,work,layout.arena)
        if affine:
            A.require(type(prefix) is int and prefix == 1, 'AFFINE_PREFIX')
            _, _, code_slot, cb_slot, _ = refs[0]
            return P.Inputs(work, layout, placements, (P.AI.program()[0],),
                            (P.AI.cb_image(work, placements),),
                            (P.AI.qmd_image(work, code_slot.gpu_address, cb_slot.gpu_address),))
        inv = P.S.parse(P.S.pinned((HERE.parent / 'data' / 'parallel_sort_programs.json'), P.S.INVENTORY_SHA))
        code = []
        for kind in P.W.STAGES:
            e = inv['programs'][kind]['artifacts']['bin']
            code.append(P.S.pinned(Path(e['path']),e['sha256'],e['size'],e['mode']))
        cbs = tuple(P.C.image(work,i,placements) for i in range(40))
        qmds = tuple(P.Q.image(kind,work.stages[i].grid,c.gpu_address,cb.gpu_address)
                     for i,kind,c,cb,_ in refs)
        return P.Inputs(work,layout,placements,tuple(code),cbs,qmds)

    def _fail(self, exc):
        self.phase, self.result = 'FAILED', None
        self.failure = {'type':type(exc).__name__, 'message':str(exc)}
        # PPB-N1: includes failures propagated only partially by InitialUpload.
        d = self.data
        live = (d.objects,d.session,d.tree,d.backend,d.mappings,d.control,d.owners,*d.allocators)
        captured = (self.objects,self.session,self.tree,self.backend,self.mappings,
                    self.control,self.owners,*self.allocators)
        if len(live) == len(captured) and all(x is y for x,y in zip(live,captured)):
            self.data._fail(exc)
        else:
            # A detected reference drift must not redirect failure to a replacement.
            # Mark only retained original objects; never restore links or clean up.
            d.failure = self.failure.copy()
            if d.phase not in ('CLOSED','TERMINAL'):
                d.phase = 'FAILED'
            for layer in (self.objects,self.session,self.mappings,self.backend):
                if layer.phase in ('CLOSING','CLEANUP'):
                    layer.phase = 'TERMINAL'
                elif layer.phase not in ('CLOSED','TERMINAL'):
                    layer.phase = 'FAILED'
            if self.tree.phase not in ('CLOSED','TERMINAL'):
                self.tree.phase = 'FAILED'
                self.tree.failure = {'type':type(exc).__name__,'reason':str(exc)}
            for allocator in (self.control,*self.allocators):
                if allocator.phase == A.OPEN:
                    allocator.phase = A.FAILED
                    allocator.failure = ('DATA_FAILED',self.failure.copy())
            for owner in self.parents:
                if owner.state == A.PENDING:
                    owner.state = A.UNCERTAIN

    def _copy(self, kind, address, argument):
        A.require(self.busy and not self.copying and self.phase == 'PREPARING'
                  and threading.get_ident() == self.thread, 'PACKET_COPY_BUSY')
        A.require(self.cursor < len(self.queue), 'PACKET_COPY_EXTRA')
        operation = self.queue[self.cursor]
        label, expected_kind, base, size, raw, inherited_busy = operation
        A.require(kind == expected_kind and type(address) is int and address == base
                  and ((kind == 'read' and type(argument) is int and argument == size)
                       or (kind == 'write' and type(argument) is bytes and argument == raw)),
                  'PACKET_COPY_TARGET')
        self._check(inherited_busy)
        if not inherited_busy:
            self.data.busy = True
        self.copying = True
        event = {'index':self.cursor, 'operation':label, 'kind':kind,
                 'address':address, 'length':size, 'attempted':False}
        self.events.append(event)
        try:
            self._check(True)
            event['attempted'] = True
            value = (self.read_bytes(address,argument) if kind == 'read'
                     else self.write_bytes(address,argument))
            event['call_returned'] = True
            A.require((type(value) is bytes and len(value) == size) if kind == 'read'
                      else value is None, 'PACKET_COPY_RESULT')
            self._check(True)
            if label == 'control-before':
                off = self.config.userd_offset
                A.require(value[off:off+512] == self.expected_userd, 'PACKET_USERD_CHANGED')
            if label in ('control-after','control-final'):
                A.require(value == self.control_image.raw, 'PACKET_CONTROL_READBACK')
            self.cursor += 1
            event['verified'] = True
            return value
        except BaseException as exc:
            event['error'] = {'type':type(exc).__name__, 'message':str(exc)}
            self.copy_failure = exc
            raise
        finally:
            self.copying = False
            if not inherited_busy:
                self.data.busy = False

    def _read(self, address, size):
        return self._copy('read',address,size)

    def _write(self, address, raw):
        return self._copy('write',address,raw)

    def prepare(self, prefix, signal):
        A.require(not self.busy and threading.get_ident() == self.thread, 'PACKET_BUSY')
        A.require(self.phase == 'NEW', 'PACKET_CLOSED')
        self.phase, self.busy = 'PREPARING', True
        try:
            A.require(type(prefix) is int and 1 <= prefix <= 40 and type(signal) is int
                      and 0 < signal < 1 << 32, 'PACKET_PARAMETERS')
            self._check(False)
            self.prefix, self.signal = prefix, signal
            self.parameters = (prefix,signal)
            self.inputs = self._derive(prefix)
            self.expected_data = self.layout.initial_images(tuple(b.allocation_size for b in self.bindings))
            base, size = self.arena.cpu_base, self.arena.size
            self.queue = (('capture','read',base,size,None,False),)
            before = self._read(base,size)
            u = self.config.userd_offset
            self.expected_userd = CI._userd(before[u:u+512])
            self.control_image = CI.compose(self.inputs,prefix,signal,self.expected_userd)
            CI.verify(self.control_image,self.inputs,prefix,signal,self.expected_userd)
            spans = tuple(Span(s.offset,s.data) for s in self.control_image.spans)
            ops = list(self.queue)
            ops.extend(('data-write:'+b.role,'write',b.cpu_base,b.allocation_size,raw,True)
                       for b,raw in zip(self.bindings,self.expected_data))
            ops.extend(('data-read:'+b.role,'read',b.cpu_base,b.allocation_size,None,True) for b in self.bindings)
            ops.append(('control-before','read',base,size,None,False))
            ops.extend(('control-write','write',base+s.offset,len(s.data),s.data,False) for s in spans)
            ops += [('control-after','read',base,size,None,False),('control-final','read',base,size,None,False)]
            ops.extend(('data-final:'+b.role,'read',b.cpu_base,b.allocation_size,None,False) for b in self.bindings)
            self.queue = tuple(ops)
            self.expectations = (self.inputs,self.control_image,self.expected_data,self.expected_userd,self.queue)
            self.data_upload = InitialDataUpload(self.data,self._read,self._write)
            data_result = self.data_upload.upload(self.expected_data)
            self.completed_uploads = ((self.data_upload,data_result,value_image(data_result)),)
            self.control_upload = InitialUpload(self.objects,self._read,self._write)
            control_result = self.control_upload.upload(spans)
            self.completed_uploads += ((self.control_upload,control_result,value_image(control_result)),)
            self._check(False)
            # Rebuild from bound resources before accepting any completed preparation.
            A.require(self._derive(prefix) == self.inputs and self.layout.initial_images(
                tuple(b.allocation_size for b in self.bindings)) == self.expected_data, 'PACKET_EXPECTATION_CHANGED')
            final = self._read(base,size)
            CI.verify(CI.ModelControlImage(final,self.control_image.spans),self.inputs,prefix,signal,self.expected_userd)
            for b,raw in zip(self.bindings,self.expected_data):
                A.require(self._read(b.cpu_base,b.allocation_size) == raw, 'PACKET_DATA_READBACK', role=b.role)
            self._check(False)
            A.require(self.data_upload.phase == 'DONE' and self.data_upload.result is data_result
                      and self.control_upload.phase == 'DONE' and self.control_upload.result is control_result,
                      'PACKET_UPLOAD_RESULT')
            A.require(self.cursor == len(self.queue) == 16 + len(spans), 'PACKET_COPY_COUNT')
            self.result = PreparationResult(prefix,signal,hashlib.sha256(final).hexdigest(),
                tuple(hashlib.sha256(raw).hexdigest() for raw in self.expected_data),self.cursor)
            self.phase = 'READY'
            return self.result
        except BaseException as exc:
            original = self.copy_failure if self.copy_failure is not None else exc
            self._fail(original)
            if original is not exc:
                raise original from exc
            raise
        finally:
            self.busy = False
