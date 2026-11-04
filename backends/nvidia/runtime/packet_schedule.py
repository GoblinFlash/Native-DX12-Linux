"""Original PS0..PS5 bridge; initial scheduling with no command publication.

Trusted exclusive thread/VA/fd/source ownership and ordinary-memory callbacks.
No native default, flight, completion, cleanup or authority token.
"""
from dataclasses import dataclass
import hashlib
import threading

import packet_preparation as PP
from preparation_schedule import InitialSchedule

A = PP.A


@dataclass(frozen=True)
class ScheduleResult:
    preparation: PP.PreparationResult
    prefix: int
    signal: int
    control_sha256: str
    data_sha256: tuple
    reads: int
    controls: int
    status: str = 'CPU_PACKET_SCHEDULE_VERIFIED'
    work_published: bool = False
    gpu_executed: bool = False
    native_completion_verified: bool = False
    flight_retirement_authorized: bool = False


def method_is(value, obj, function):
    return getattr(value, '__self__', None) is obj and getattr(value, '__func__', None) is function


class PacketSchedule:
    def __init__(self, packet, *, bind_group=False):
        A.require(type(packet) is PP.PacketPreparation and packet.phase == 'READY'
                  and not packet.busy and not packet.copying
                  and packet.thread == threading.get_ident(), 'PS_PACKET')
        A.require(type(bind_group) is bool, 'PS_PROFILE')
        A.require(getattr(packet.objects, '_packet_schedule', None) is None, 'PS_EXISTS')
        packet._check(False)
        result = packet.result
        A.require(type(result) is PP.PreparationResult, 'PS_PREPARATION_RESULT')
        expected = PP.PreparationResult(packet.prefix, packet.signal,
            hashlib.sha256(packet.control_image.raw).hexdigest(),
            tuple(hashlib.sha256(b).hexdigest() for b in packet.expected_data), packet.cursor)
        A.require(PP.value_image(vars(result)) == PP.value_image(vars(expected))
                  and packet.cursor == len(packet.queue), 'PS_PREPARATION_RESULT')
        PP.CI.verify(packet.control_image, packet.inputs, packet.prefix,
                     packet.signal, packet.expected_userd)
        A.require(packet._derive(packet.prefix) == packet.inputs, 'PS_INPUT_BINDING')
        self.packet, self.preparation = packet, result
        # Copy the original anchors, never recover them through a drifted packet.
        names = ('data', 'objects', 'session', 'tree', 'backend', 'mappings', 'owners',
                 'control', 'layout', 'abi', 'bindings', 'arena', 'channel', 'config',
                 'resource_config', 'allocators', 'mapping_rows', 'parents', 'parent_undo',
                 'refs', 'values', 'parent_values', 'inputs', 'control_image', 'expected_data',
                 'expected_userd', 'queue', 'expectations', 'completed_uploads',
                 'data_upload', 'control_upload', 'callbacks')
        self.anchors = tuple((name, getattr(packet, name)) for name in names)
        for name, value in self.anchors:
            setattr(self, name, value)
        self.packet_values = PP.value_image((vars(result), packet.parameters, packet.cursor))
        self.prefix, self.signal = packet.prefix, packet.signal
        self.read_bytes = packet.read_bytes
        self.thread, self.bind_group = packet.thread, bind_group
        self.profile = bind_group
        self.data_refs = (self.data.slots, self.data._slots, self.data.ledger,
                          self.data.owner_images, self.data.records, self.data.record_images)
        self.record_values = PP.value_image([(vars(spec), {k: v for k, v in vars(back).items()
                                                         if k != 'owner'}, fp, fd, addr)
                                            for spec, back, fp, fd, addr in self.data.record_images])
        self.binding_refs = tuple((b.owner, b.allocator, b.mapping) for b in self.bindings)
        self.phase, self.busy, self.copying, self.mode = 'NEW', False, False, None
        self.scheduler, self.schedule_owner = None, None
        self.ack_result, self.ack_image = None, None
        self.failure, self.result, self.copy_failure = None, None, None
        self.events, self.cursor = [], 0
        self.targets = ((self.arena.cpu_base, self.arena.size, self.control_image.raw),
                        *((b.cpu_base, b.allocation_size, raw)
                          for b, raw in zip(self.bindings, self.expected_data)))
        self._targets = self.targets
        self.objects._packet_schedule = self

    def _check(self):
        p, d, o, s, t = self.packet, self.data, self.objects, self.session, self.tree
        A.require(self.busy and self.phase == 'SCHEDULING' and d.busy
                  and threading.get_ident() == self.thread, 'PS_BUSY')
        A.require(o._packet_schedule is self and o._packet_preparation is p
                  and type(self.bind_group) is bool and self.bind_group is self.profile,
                  'PS_ASSOCIATION')
        A.require(all(getattr(p, name) is value for name, value in self.anchors), 'PS_PACKET_REFERENCE')
        A.require(p.phase == 'READY' and not p.busy and not p.copying
                  and p.result is self.preparation
                  and PP.value_image((vars(p.result), p.parameters, p.cursor)) == self.packet_values
                  and type(p.prefix) is int and type(p.signal) is int
                  and (p.prefix, p.signal) == (self.prefix, self.signal), 'PS_PACKET_STATE')
        A.require(p.read_bytes is self.read_bytes is self.callbacks[0]
                  and p.write_bytes is self.callbacks[1], 'PS_CALLBACK_CHANGED')
        A.require(self.targets is self._targets and self.targets ==
                  ((self.arena.cpu_base, self.arena.size, self.control_image.raw),
                   *((b.cpu_base, b.allocation_size, raw)
                     for b, raw in zip(self.bindings, self.expected_data))), 'PS_TARGET_CHANGED')
        refs = PP.PacketPreparation._references(self)
        A.require(len(refs) == len(self.refs) and all(a is b for a, b in zip(refs, self.refs)),
                  'PS_REFERENCE_CHANGED')
        d._owned()
        A.require(d.phase == 'READY' and o.phase == 'PREPARED' and s.phase == 'ARENA_READY'
                  and t.phase == 'IDENTIFIED' and self.backend.phase == 'ACTIVE'
                  and not self.backend.pending and self.mappings.phase == 'ACTIVE', 'PS_PHASE')
        A.require(getattr(o, '_mapping_transport', None) is None
                  and getattr(o, '_initial_publication', None) is None, 'PS_TOO_LATE')
        A.require(d.handles is t._handles and d.instances is t._instances and d.uuid == t.uuid
                  and d.channel is self.channel and d.arena_binding is self.arena
                  and d.memory_class == self.resource_config.memory_class
                  and d.va == (self.control.observed['va_base'], self.control.observed['va_size']),
                  'PS_DATA_CONTEXT')
        A.require(all(a is b for a, b in zip((d.slots, d._slots, d.ledger, d.owner_images,
                                              d.records, d.record_images), self.data_refs))
                  and len(d.records) == len(d.record_images) == len(self.bindings) == 4,
                  'PS_DATA_RECORDS')
        A.require(PP.value_image([(vars(spec), {k: v for k, v in vars(back).items() if k != 'owner'},
                                  fp, fd, addr) for spec, back, fp, fd, addr in d.record_images])
                  == self.record_values, 'PS_DATA_RECORD_VALUES')
        for index, (b, original) in enumerate(zip(self.bindings, self.binding_refs)):
            A.require(all(a is c for a, c in zip((b.owner, b.allocator, b.mapping), original))
                      and d.records[index] is self.mapping_rows[index + 2][1], 'PS_DATA_BINDING')
        A.require(getattr(d, '_initial_data_upload', None) is self.data_upload
                  and getattr(o, '_initial_upload', None) is self.control_upload,
                  'PS_UPLOADER_CHANGED')
        for uploader, result, snapshot in self.completed_uploads:
            A.require(uploader.phase == 'DONE' and uploader.result is result
                      and PP.value_image(result) == snapshot, 'PS_UPLOAD_RESULT')
            A.require(method_is(uploader.read_bytes, p, PP.PacketPreparation._read)
                      and method_is(uploader.write_bytes, p, PP.PacketPreparation._write),
                      'PS_UPLOAD_ADAPTER')
        for parent, undo in zip(self.parents, self.parent_undo):
            A.require(parent.state == A.CERTAIN, 'PS_PARENT_STATE')
            if parent.undo is not undo:
                parent.state = A.UNCERTAIN
                raise A.Stop('PS_PARENT_CHANGED')
        if PP.value_image([(x.label, x.requested, x.returned) for x in self.parents]) != self.parent_values:
            for parent in self.parents:
                parent.state = A.UNCERTAIN
            raise A.Stop('PS_PARENT_CHANGED')
        schedule = self.scheduler
        expected_owners = self.parents
        if schedule is None:
            A.require(self.mode == 'PRE' and getattr(o, '_initial_schedule', None) is None,
                      'PS_SCHEDULE_PHASE')
        else:
            A.require(type(schedule) is InitialSchedule and o._initial_schedule is schedule
                      and schedule.upload is self.control_upload and schedule.objects is o
                      and schedule.session is s and schedule.tree is t and schedule.owners is self.owners
                      and schedule.binding is self.channel and schedule.mapped is self.mapping_rows[0][0]
                      and schedule.digest == self.preparation.control_sha256
                      and schedule.bind_group is self.profile
                      and method_is(schedule.read_bytes, self, PacketSchedule._read)
                      and schedule.read_bytes is schedule._reader, 'PS_SCHEDULE_BINDING')
            A.require((self.mode == 'SCHEDULE' and schedule.phase == 'SCHEDULING')
                      or (self.mode == 'POST' and schedule.phase == 'ACKNOWLEDGED'), 'PS_SCHEDULE_PHASE')
            owner = schedule.owner
            A.require(owner is schedule._owner, 'PS_SCHEDULE_OWNER')
            if owner is None:
                A.require(self.mode == 'SCHEDULE' and self.schedule_owner is None
                          and not schedule.attempts, 'PS_SCHEDULE_OWNER')
            else:
                if self.schedule_owner is None:
                    self.schedule_owner = owner
                A.require(owner is self.schedule_owner and type(owner) is A.Owner
                          and owner.state == A.CERTAIN and owner.label == 'control:initial_schedule'
                          and PP.value_image(owner.requested) == PP.value_image({
                              'channel': self.channel.channel, 'bind_group': self.profile,
                              'upload_sha256': self.preparation.control_sha256})
                          and owner.returned is schedule.attempts, 'PS_SCHEDULE_OWNER')
                A.require((self.mode == 'SCHEDULE' and owner.undo is None) or
                          (self.mode == 'POST' and method_is(owner.undo, schedule, InitialSchedule._retire)),
                          'PS_SCHEDULE_UNDO')
                expected_owners += (owner,)
            if self.mode == 'POST':
                A.require(schedule.result is self.ack_result and PP.value_image(
                    (schedule.result, schedule.attempts)) == self.ack_image, 'PS_ACK_CHANGED')
        A.require(len(self.owners) == len(expected_owners)
                  and all(a is b for a, b in zip(self.owners, expected_owners)), 'PS_LEDGER')
        A.require(o.binding() is self.channel and s.binding() is self.arena, 'PS_BINDING')
        for b, rec, spec, backing in self.mapping_rows:
            A.require(self.mappings.records.get(b.mapping_id) is rec and rec.spec is spec
                      and rec.backing is backing and rec.binding is b, 'PS_MAPPING_CHANGED')
            A.require(self.mappings.validate_binding(b) is b
                      and self.mappings._range(rec)['state'] == 'M1_MATERIALIZED', 'PS_MAPPING_STATE')
            self.mappings._fd(rec)
            rows = self.backend._snapshot(b.cpu_base, b.length)
            A.require(len(rows) == 1 and rows[0].start == b.cpu_base
                      and rows[0].end == b.cpu_base + b.length and rows[0].perms == 'rw-s'
                      and rows[0].path == rec.fingerprint[4], 'PS_MAPPING_VMA')
        A.require(PP.PacketPreparation._values(self) == self.values, 'PS_VALUE_CHANGED')
        for index, (allocator, mapped) in enumerate(((self.control, self.mapping_rows[0][0]),
                                  *((b.allocator, b.mapping) for b in self.bindings))):
            backing = self.mappings.records[mapped.mapping_id].backing
            request = allocator.req
            A.validate_request(request, self.abi)
            A.require(allocator.phase == A.OPEN and allocator.backend is self.backend
                      and allocator.owners is self.owners and allocator.abi is self.abi
                      and (index == 0 or request is d.requests[index - 1]),
                      'PS_ALLOCATOR_BINDING')
            h = t._handles
            A.require((request.h_client, request.h_device, request.h_subdevice, request.h_vas,
                       request.gpu_uuid, request.rm_ctrl_fd) ==
                      (h.client, h.device, h.subdevice, h.vas, t.uuid, self.backend.fds['ctl'])
                      and request.h_memory == backing.memory
                      and request.memory_class == backing.memory_class, 'PS_ALLOCATOR_TARGET')
            location = A.field_value(allocator.observed['attr'], self.abi.const('NVOS32_ATTR_LOCATION_SHIFT'),
                                     self.abi.const('NVOS32_ATTR_LOCATION_MASK'))
            A.require(location == backing.location == self.abi.const('NVOS32_ATTR_LOCATION_PCI')
                      and allocator.observed['format'] == self.abi.const('NV_MMU_PTE_KIND_GENERIC_MEMORY'),
                      'PS_ALLOCATION_PROFILE')
        for b in self.bindings:
            a, back = b.allocator, self.mappings.records[b.mapping.mapping_id].backing
            A.require(a.req.base == b.gpu_base == a.observed['gpu_base'] == b.cpu_base
                      and a.observed['arena_size'] == b.allocation_size == back.size
                      and b.memory == back.memory == b.owner.returned and back.owner is b.owner,
                      'PS_DATA_ALLOCATION')
        PP.input_pins()

    def _copy(self, label, target):
        A.require(self.busy and not self.copying and self.phase == 'SCHEDULING'
                  and threading.get_ident() == self.thread, 'PS_READ_BUSY')
        A.require((self.mode == 'SCHEDULE' and label == 'schedule-control' and target is self.targets[0])
                  or (self.mode in ('PRE', 'POST') and 0 <= self.cursor < 5
                      and label == self.mode + ':' + str(self.cursor)
                      and target is self.targets[self.cursor]), 'PS_READ_TARGET')
        address, size, expected = target
        event = {'index': len(self.events), 'label': label, 'address': address,
                 'length': size, 'attempted': False}
        self.events.append(event)
        self.copying = True
        try:
            self._check()
            event['attempted'] = True
            raw = self.read_bytes(address, size)
            event['call_returned'] = True
            A.require(type(raw) is bytes and len(raw) == size, 'PS_READ_RESULT')
            self._check()
            A.require(raw == expected, 'PS_READBACK', region=label)
            event['verified'] = True
            return raw
        except BaseException as exc:
            event['error'] = {'type': type(exc).__name__, 'reason': str(exc)}
            if self.copy_failure is None:
                self.copy_failure = exc
            raise
        finally:
            self.copying = False

    def _read(self, address, size):
        A.require(self.mode == 'SCHEDULE' and self.scheduler is not None
                  and self.scheduler.phase == 'SCHEDULING', 'PS_READ_PHASE')
        A.require(type(address) is int and type(size) is int
                  and (address, size) == self.targets[0][:2], 'PS_READ_TARGET')
        return self._copy('schedule-control', self.targets[0])

    def _images(self):
        self.cursor = 0
        for index, target in enumerate(self.targets):
            self._copy(self.mode + ':' + str(index), target)
            self.cursor += 1

    def _fail(self, exc):
        self.phase, self.result = 'FAILED', None
        self.failure = {'type': type(exc).__name__, 'message': str(exc)}
        self.packet.phase, self.packet.result = 'FAILED', None
        self.packet.failure = self.failure.copy()
        self.data.failure = self.failure.copy()
        for layer in (self.data, self.objects, self.session, self.mappings, self.backend):
            if layer.phase in ('CLOSING', 'CLEANUP'):
                layer.phase = 'TERMINAL'
            elif layer.phase not in ('CLOSED', 'TERMINAL'):
                layer.phase = 'FAILED'
        if self.tree.phase not in ('CLOSED', 'TERMINAL'):
            self.tree.phase = 'FAILED'
            self.tree.failure = {'type': type(exc).__name__, 'reason': str(exc)}
        for allocator in (self.control, *self.allocators):
            if allocator.phase == A.OPEN:
                allocator.phase = A.FAILED
                allocator.failure = ('DATA_FAILED', self.failure.copy())
        for owner in self.parents:
            if owner.state == A.PENDING:
                owner.state = A.UNCERTAIN
        if self.schedule_owner is not None:
            self.schedule_owner.state = A.UNCERTAIN
        elif self.scheduler is not None and self.scheduler._owner is not None:
            # A first query may fail before the bridge's first post-query read.
            # The schedule itself retains and marks its original owner on failure.
            for owner in self.owners[len(self.parents):]:
                if owner.state == A.PENDING:
                    owner.state = A.UNCERTAIN

    def schedule(self):
        A.require(self.phase == 'NEW', 'PS_CLOSED')
        A.require(not self.busy and not self.data.busy and threading.get_ident() == self.thread,
                  'PS_BUSY')
        self.phase, self.busy, self.data.busy, self.mode = 'SCHEDULING', True, True, 'PRE'
        try:
            self._images()
            self.scheduler = InitialSchedule(self.control_upload, bind_group=self.profile,
                                             read_bytes=self._read)
            self.mode = 'SCHEDULE'
            self.scheduler.schedule()
            self.ack_result = self.scheduler.result
            self.ack_image = PP.value_image((self.ack_result, self.scheduler.attempts))
            self.mode = 'POST'
            self._images()
            self._check()
            calls = len(self.scheduler.attempts)
            A.require(len(self.events) == 10 + 1 + 2 * calls
                      and all(e.get('verified') for e in self.events), 'PS_READ_COUNT')
            self.result = ScheduleResult(self.preparation, self.prefix, self.signal,
                self.preparation.control_sha256, self.preparation.data_sha256, len(self.events), calls)
            self.phase = 'ACKNOWLEDGED'
            return self.result
        except BaseException as exc:
            original = self.copy_failure if self.copy_failure is not None else exc
            self._fail(original)
            if original is not exc:
                raise original from exc
            raise
        finally:
            self.busy, self.data.busy, self.mode = False, False, None
