"""Original CPU packet publication controller; no native arming or retirement.

Exclusive trusted thread, source, fd and address ownership is required. Initial
byte comparisons are observations, not an atomic snapshot against external writers.
"""
from dataclasses import dataclass, fields, is_dataclass
import hashlib
import threading

import mapping_transport as M
import packet_schedule as S

PP, A = S.PP, S.A
method_is = S.method_is


def image_value(value):
    """Snapshot the known image dataclasses without traversing resource owners."""
    if is_dataclass(value) and not isinstance(value, type):
        return type(value), tuple((f.name, image_value(getattr(value, f.name))) for f in fields(value))
    if type(value) in (tuple, list):
        return type(value), tuple(image_value(v) for v in value)
    return PP.value_image(value)


@dataclass(frozen=True)
class PublicationResult:
    preparation: PP.PreparationResult
    schedule: S.ScheduleResult
    reads: int
    effects: int
    model_publication_recorded: bool = True
    native_execution_proven: bool = False
    completion_verified: bool = False
    flight_retirement_authorized: bool = False
    retained: bool = True


class _PacketPublicationCore:
    # Fixed implementation methods, never caller-supplied policy objects.
    _MODE_METHODS = ('_admit_words', '_make_transport', '_words_bound', '_transport_type',
                     '_attach_transport', '_expected_receipt', '_make_result', '_owner_label')

    def __init__(self, bridge, words, *, record=None):
        A.require(type(self) is not _PacketPublicationCore, 'PC_IMPLEMENTATION')
        self._implementation = type(self)
        self._mode_functions = tuple((name, getattr(type(self), name))
                                     for name in _PacketPublicationCore._MODE_METHODS)
        self._policy()
        A.require(type(bridge) is S.PacketSchedule and bridge.phase == 'ACKNOWLEDGED'
                  and not bridge.busy and not bridge.copying
                  and bridge.thread == threading.get_ident(), 'PC_BRIDGE')
        self._admit_words(words)
        A.require(record is None or callable(record), 'PC_RECORDER')
        A.require(type(bridge.packet) is PP.PacketPreparation
                  and type(bridge.scheduler) is S.InitialSchedule
                  and type(bridge.schedule_owner) is A.Owner
                  and type(bridge.result) is S.ScheduleResult
                  and type(bridge.preparation) is PP.PreparationResult, 'PC_EVIDENCE_TYPE')
        o = bridge.objects
        A.require(all(getattr(o, name, None) is None for name in
                      ('_mapping_transport', '_initial_publication', '_packet_publication')), 'PC_EXISTS')
        self.bridge, self.packet, self.schedule = bridge, bridge.packet, bridge.scheduler
        self.preparation, self.scheduled = bridge.preparation, bridge.result
        self.packet_anchors = bridge.anchors
        for name, value in self.packet_anchors:
            setattr(self, name, value)
        self.schedule_owner = bridge.schedule_owner
        self.parents = bridge.parents + (self.schedule_owner,)
        self.parent_undo = tuple(owner.undo for owner in self.parents)
        self.parent_values = PP.value_image([(x.label, x.requested, x.returned) for x in self.parents])
        self.prefix, self.signal = bridge.prefix, bridge.signal
        self.thread, self.profile = bridge.thread, bridge.profile
        self.packet_values = bridge.packet_values
        self.data_refs, self.record_values, self.binding_refs = (
            bridge.data_refs, bridge.record_values, bridge.binding_refs)
        self.read_bytes = bridge.read_bytes
        self.targets = bridge.targets
        self.image_values = image_value((self.inputs, self.control_image,
                                        self.expected_data, self.expected_userd))
        self.ack_result, self.ack_image = bridge.ack_result, bridge.ack_image
        self.schedule_values = PP.value_image({k: v for k, v in vars(self.scheduled).items()
                                               if k != 'preparation'})
        self.words = self._words = words
        self.record = self._observer = record
        self.phase, self.busy, self.copying = 'NEW', False, False
        self.owner = self._owner = None
        self._flight_installed, self._associated = False, False
        self.transport = self._transport = None
        self.events = []
        self.attempts = self._attempts = {'reads': self.events, 'transport': None}
        self.failure, self.failure_handler_error, self.result = None, None, None
        self._originals = (self.data, self.objects, self.session, self.mappings,
                           self.backend, self.tree, self.packet, self.bridge, self.schedule)
        self._original_allocators = (self.control, *self.allocators)
        self._original_owners = self.owners
        self._original_parents = self.parents
        self._anchors = tuple((name, getattr(self, name)) for name in (
            'bridge', 'packet', 'schedule', 'preparation', 'scheduled', 'packet_anchors',
            'data', 'objects', 'session', 'tree', 'backend', 'mappings', 'owners', 'control',
            'layout', 'abi', 'bindings', 'arena', 'channel', 'config', 'resource_config',
            'allocators', 'mapping_rows', 'parents', 'parent_undo', 'refs', 'values',
            'parent_values', 'inputs', 'control_image', 'expected_data', 'expected_userd',
            'queue', 'expectations', 'completed_uploads', 'data_upload', 'control_upload',
            'callbacks', 'read_bytes', 'targets', 'schedule_owner', 'ack_result', 'ack_image',
            '_implementation', '_mode_functions'))
        self._check()
        self._admit_images()
        self._policy()
        self.transport = self._make_transport()
        self._transport = self.transport
        self.attempts['transport'] = self.transport.events
        o._packet_publication = o._initial_publication = self
        self._associated = True

    def _policy(self):
        A.require(type(self) is self._implementation
                  and type(self._mode_functions) is tuple
                  and tuple(name for name, _ in self._mode_functions)
                      == _PacketPublicationCore._MODE_METHODS
                  and all(method_is(getattr(self, name, None), self, function)
                          for name, function in self._mode_functions),
                  'PC_IMPLEMENTATION_CHANGED')

    def _admit_images(self):
        p = self.packet
        expected = PP.PreparationResult(self.prefix, self.signal,
            hashlib.sha256(self.control_image.raw).hexdigest(),
            tuple(hashlib.sha256(raw).hexdigest() for raw in self.expected_data), p.cursor)
        A.require(PP.value_image(vars(self.preparation)) == PP.value_image(vars(expected))
                  and p.cursor == len(self.queue), 'PC_PREPARATION_RESULT')
        expected_schedule = S.ScheduleResult(self.preparation, self.prefix, self.signal,
            self.preparation.control_sha256, self.preparation.data_sha256,
            11 + 2 * (2 if self.profile else 1), 2 if self.profile else 1)
        A.require(self.scheduled.preparation is self.preparation
                  and PP.value_image({k: v for k, v in vars(expected_schedule).items()
                                     if k != 'preparation'}) == self.schedule_values,
                  'PC_SCHEDULE_RESULT')
        PP.CI.verify(self.control_image, self.inputs, self.prefix, self.signal, self.expected_userd)
        A.require(PP.PacketPreparation._derive(self, self.prefix) == self.inputs, 'PC_INPUT_BINDING')

    def _check(self):
        A.require(threading.get_ident() == self.thread and self.phase in ('NEW', 'PREFLIGHT', 'ARMED')
                  and self.busy is (self.phase != 'NEW')
                  and self._originals[0].busy is self.busy, 'PC_BUSY')
        _PacketPublicationCore._check_custody(self)

    def _check_published(self, companion):
        A.require(companion is not None
                  and getattr(self, '_completion', None) is companion
                  and getattr(self, '_completion_original', None) is companion
                  and getattr(companion, 'publication', None) is self
                  and getattr(companion, '_publication', None) is self,
                  'PC_COMPLETION_ASSOCIATION')
        A.require(threading.get_ident() == self.thread
                  and self.phase == 'PUBLISHED_UNCONFIRMED' and self.busy is False
                  and companion.busy is True
                  and companion.phase in ('WAITING', 'ACQUIRING', 'READING')
                  and self._originals[0].busy is True, 'PC_COMPLETION_BUSY')
        A.require(self._associated and self._flight_installed
                  and self.transport.phase == 'PUBLISHED_UNCONFIRMED'
                  and self.transport.busy is False, 'PC_COMPLETION_PHASE')
        A.require(self.result is self._published_result
                  and image_value(self.result) == self._published_image
                  and self.result == self._make_result()
                  and self.transport.result is self._published_receipt
                  and PP.value_image(self.transport.result) == self._published_receipt_image
                  and self.transport.result == self._expected_receipt(),
                  'PC_COMPLETION_RESULT')
        _PacketPublicationCore._check_custody(self)

    def _check_custody(self):
        # Internal invariant body: fixed entry wrappers own phase and busy rules.
        self._policy()
        A.require(all(getattr(self, name) is value for name, value in self._anchors), 'PC_REFERENCE_CHANGED')
        b, p, d, o, s = self.bridge, self.packet, self.data, self.objects, self.schedule
        A.require(b.phase == 'ACKNOWLEDGED' and not b.busy and not b.copying
                  and b.packet is p and b.scheduler is s and b.result is self.scheduled
                  and b.preparation is self.preparation and b.schedule_owner is self.schedule_owner
                  and b.profile is self.profile and b.bind_group is self.profile,
                  'PC_BRIDGE_CHANGED')
        A.require(o._packet_schedule is b and o._packet_preparation is p
                  and o._initial_schedule is s, 'PC_ASSOCIATION')
        A.require(all(getattr(p, name) is value and getattr(b, name) is value
                      for name, value in self.packet_anchors), 'PC_PACKET_REFERENCE')
        A.require(p.phase == 'READY' and not p.busy and not p.copying
                  and p.result is self.preparation
                  and PP.value_image((vars(p.result), p.parameters, p.cursor)) == self.packet_values
                  and type(p.prefix) is int and type(p.signal) is int
                  and (p.prefix, p.signal) == (self.prefix, self.signal), 'PC_PACKET_STATE')
        A.require(p.read_bytes is b.read_bytes is self.read_bytes is self.callbacks[0]
                  and p.write_bytes is self.callbacks[1], 'PC_CALLBACK_CHANGED')
        A.require(self.targets == ((self.arena.cpu_base, self.arena.size, self.control_image.raw),
                  *((x.cpu_base, x.allocation_size, raw)
                    for x, raw in zip(self.bindings, self.expected_data))), 'PC_TARGET_CHANGED')
        A.require(image_value((self.inputs, self.control_image, self.expected_data, self.expected_userd))
                  == self.image_values, 'PC_IMAGE_CHANGED')
        A.require(self.scheduled.preparation is self.preparation and PP.value_image(
                  {k: v for k, v in vars(self.scheduled).items() if k != 'preparation'})
                  == self.schedule_values, 'PC_SCHEDULE_RESULT')
        A.require(s.phase == 'ACKNOWLEDGED' and s.objects is o and s.session is self.session
                  and s.tree is self.tree and s.owners is self.owners
                  and s.upload is self.control_upload and s.binding is self.channel
                  and s.mapped is self.mapping_rows[0][0] and s.bind_group is self.profile
                  and s.digest == self.preparation.control_sha256
                  and method_is(s.read_bytes, b, S.PacketSchedule._read)
                  and s.read_bytes is s._reader, 'PC_SCHEDULE_BINDING')
        owner = self.schedule_owner
        A.require(type(owner) is A.Owner and s.owner is s._owner is owner
                  and owner.state == A.CERTAIN and owner.returned is s.attempts is s._attempts
                  and method_is(owner.undo, s, S.InitialSchedule._retire)
                  and s.result is b.ack_result is self.ack_result
                  and PP.value_image((s.result, s.attempts)) == b.ack_image == self.ack_image,
                  'PC_ACK_BINDING')
        for parent, undo in zip(self.parents, self.parent_undo):
            A.require(parent.state == A.CERTAIN, 'PC_PARENT_STATE')
            if parent.undo is not undo:
                parent.state = A.UNCERTAIN
                raise A.Stop('PC_PARENT_CHANGED')
        if PP.value_image([(x.label, x.requested, x.returned) for x in self.parents]) != self.parent_values:
            for parent in self.parents:
                parent.state = A.UNCERTAIN
            raise A.Stop('PC_PARENT_CHANGED')
        expected = self.parents + ((self._owner,) if self._flight_installed else ())
        A.require(len(self.owners) == len(expected) and all(x is y for x, y in zip(self.owners, expected)),
                  'PC_LEDGER')
        A.require(self.attempts is self._attempts and self.attempts['reads'] is self.events,
                  'PC_ATTEMPTS_CHANGED')
        if self.phase in ('ARMED', 'PUBLISHED_UNCONFIRMED'):
            A.require(self._flight_installed and self.owner is self._owner
                      and type(self.owner) is A.Owner and self.owner.state == A.UNCERTAIN
                      and self.owner.undo is None and self.owner.returned is self.attempts
                      and PP.value_image(self.owner.requested) == self.flight_values,
                      'PC_FLIGHT_CHANGED')
        else:
            A.require(not self._flight_installed and self.owner is self._owner is None, 'PC_FLIGHT_EARLY')
        A.require(self._words_bound() and self.record is self._observer, 'PC_OBSERVER_CHANGED')
        if self._associated:
            t = self.transport
            A.require(t is self._transport and o._mapping_transport is t
                      and o._packet_publication is self and o._initial_publication is self
                      and type(t) is self._transport_type() and t.schedule is s and t.words is self.words
                      and method_is(t.packet_check, self, _PacketPublicationCore._check)
                      and (t.record is None if self._observer is None else
                           method_is(t.record, self, _PacketPublicationCore._record))
                      and self.attempts['transport'] is t.events, 'PC_TRANSPORT_BINDING')
        else:
            A.require(all(getattr(o, name, None) is None for name in
                          ('_mapping_transport', '_initial_publication', '_packet_publication')),
                      'PC_EXISTS')
        self._resources()

    def _record(self, event):
        A.require(self.busy and self.phase in ('PREFLIGHT', 'ARMED')
                  and self.record is self._observer and self._observer is not None,
                  'PC_RECORD_PHASE')
        self._observer(event)

    def _read_initial(self, index):
        A.require(self.phase == 'PREFLIGHT' and self.busy and not self.copying
                  and index == len(self.events) and 0 <= index < 5, 'PC_READ_PHASE')
        address, size, expected = self.targets[index]
        event = {'region': 'initial:' + str(index), 'address': address,
                 'length': size, 'attempted': False}
        self.events.append(event)
        self.copying = True
        try:
            self._check()
            event['attempted'] = True
            raw = self.read_bytes(address, size)
            event['call_returned'] = True
            A.require(type(raw) is bytes and len(raw) == size, 'PC_READ_RESULT')
            self._check()
            A.require(raw == expected, 'PC_READBACK', region=event['region'])
            event['verified'] = True
        except BaseException as exc:
            event['error'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            self.copying = False

    def _mark_failed(self, exc):
        self.phase, self.result = ('FAILED_HELD' if self._flight_installed else 'FAILED'), None
        self.failure = {'type': type(exc).__name__, 'message': str(exc)}
        for layer in self._originals:
            if layer.phase in ('CLOSING', 'CLEANUP'):
                layer.phase = 'TERMINAL'
            elif layer.phase not in ('TERMINAL', 'CLOSED', 'TORN'):
                layer.phase = 'FAILED'
        for allocator in self._original_allocators:
            if allocator.phase not in (A.TORN, A.FAILED, 'CLOSED', 'TERMINAL'):
                allocator.phase = A.FAILED
                allocator.failure = ('DATA_FAILED', self.failure.copy())
        for owner in self._original_parents:
            if owner.state == A.PENDING:
                owner.state = A.UNCERTAIN
        if self._flight_installed:
            self._owner.state, self._owner.undo = A.UNCERTAIN, None

    def _fail(self, exc):
        self._mark_failed(exc)

    def publish(self):
        A.require(self.phase == 'NEW', 'PC_CLOSED')
        data = self._originals[0]
        A.require(not self.busy and not data.busy and threading.get_ident() == self.thread, 'PC_BUSY')
        self.phase, self.busy, data.busy = 'PREFLIGHT', True, True
        try:
            self._check()
            for index in range(5):
                self._read_initial(index)
            self.transport.read_initial_get()
            self.transport.read_initial_put()
            self._check()
            self._admit_images()
            t = self.transport
            requested = {'channel': self.channel.channel, 'upload_sha256': self.preparation.control_sha256,
                         'put_address': t.targets[1], 'put': 1,
                         'doorbell_address': t.targets[2], 'token': t.targets[3]}
            self.flight_values = PP.value_image(requested)
            self.owner = self._owner = A.Owner(self._owner_label(), requested, state=A.UNCERTAIN)
            self.owner.returned = self.attempts
            try:
                self._original_owners.append(self.owner)
            finally:
                self._flight_installed = any(x is self._owner for x in self._original_owners)
            self.phase = 'ARMED'
            self._check()
            self._attach_transport()
            t.release_before_put()
            t.put()
            t.release_before_doorbell()
            t.doorbell()
            receipt = t.release_after_doorbell()
            self._check()
            A.require(t.phase == 'PUBLISHED_UNCONFIRMED' and receipt == self._expected_receipt()
                and len(self.events) == 5 and all(e.get('verified') for e in self.events)
                and len(t.events) == 7 and all(e.get('call_returned') for e in t.events), 'PC_RESULT')
            self.result = self._make_result()
            self._published_result = self.result
            self._published_image = image_value(self.result)
            self._published_receipt = t.result
            self._published_receipt_image = PP.value_image(t.result)
            self.phase = 'PUBLISHED_UNCONFIRMED'
            return self.result
        except BaseException as exc:
            try:
                self._fail(exc)
            except BaseException as secondary:
                self.failure_handler_error = secondary
                _PacketPublicationCore._mark_failed(self, exc)
            raise
        finally:
            self.busy, data.busy = False, False

    def _resources(self):
        # Phase-independent custody from the author's existing bridge checks.
        # Do not call public binding(), _pure or _context with a flight owner.
        p, d, o, s, t = self.packet, self.data, self.objects, self.session, self.tree
        refs = PP.PacketPreparation._references(self)
        A.require(len(refs) == len(self.refs) and all(a is b for a, b in zip(refs, self.refs)),
                  'PC_REFERENCE_CHANGED')
        d._owned()
        A.require(d.phase == 'READY' and o.phase == 'PREPARED' and s.phase == 'ARENA_READY'
                  and t.phase == 'IDENTIFIED' and self.backend.phase == 'ACTIVE'
                  and not self.backend.pending and self.mappings.phase == 'ACTIVE', 'PC_PHASE')
        A.require(d.handles is t._handles and d.instances is t._instances and d.uuid == t.uuid
                  and d.channel is self.channel and d.arena_binding is self.arena
                  and d.memory_class == self.resource_config.memory_class
                  and d.va == (self.control.observed['va_base'], self.control.observed['va_size']),
                  'PC_DATA_CONTEXT')
        A.require(all(a is b for a, b in zip((d.slots, d._slots, d.ledger, d.owner_images,
                                              d.records, d.record_images), self.data_refs))
                  and len(d.records) == len(d.record_images) == len(self.bindings) == 4,
                  'PC_DATA_RECORDS')
        A.require(PP.value_image([(vars(spec), {k: v for k, v in vars(back).items() if k != 'owner'},
                                  fp, fd, addr) for spec, back, fp, fd, addr in d.record_images])
                  == self.record_values, 'PC_DATA_RECORD_VALUES')
        for index, (b, original) in enumerate(zip(self.bindings, self.binding_refs)):
            A.require(all(a is c for a, c in zip((b.owner, b.allocator, b.mapping), original))
                      and d.records[index] is self.mapping_rows[index + 2][1], 'PC_DATA_BINDING')
        A.require(getattr(d, '_initial_data_upload', None) is self.data_upload
                  and getattr(o, '_initial_upload', None) is self.control_upload,
                  'PC_UPLOADER_CHANGED')
        for uploader, result, snapshot in self.completed_uploads:
            A.require(uploader.phase == 'DONE' and uploader.result is result
                      and PP.value_image(result) == snapshot, 'PC_UPLOAD_RESULT')
            A.require(method_is(uploader.read_bytes, p, PP.PacketPreparation._read)
                      and method_is(uploader.write_bytes, p, PP.PacketPreparation._write),
                      'PC_UPLOAD_ADAPTER')
        for b, rec, spec, backing in self.mapping_rows:
            A.require(self.mappings.records.get(b.mapping_id) is rec and rec.spec is spec
                      and rec.backing is backing and rec.binding is b, 'PC_MAPPING_CHANGED')
            A.require(self.mappings.validate_binding(b) is b
                      and self.mappings._range(rec)['state'] == 'M1_MATERIALIZED', 'PC_MAPPING_STATE')
            self.mappings._fd(rec)
            rows = self.backend._snapshot(b.cpu_base, b.length)
            A.require(len(rows) == 1 and rows[0].start == b.cpu_base
                      and rows[0].end == b.cpu_base + b.length and rows[0].perms == 'rw-s'
                      and rows[0].path == rec.fingerprint[4], 'PC_MAPPING_VMA')
        A.require(PP.PacketPreparation._values(self) == self.values, 'PC_VALUE_CHANGED')
        for index, (allocator, mapped) in enumerate(((self.control, self.mapping_rows[0][0]),
                                  *((b.allocator, b.mapping) for b in self.bindings))):
            backing = self.mappings.records[mapped.mapping_id].backing
            request = allocator.req
            A.validate_request(request, self.abi)
            A.require(allocator.phase == A.OPEN and allocator.backend is self.backend
                      and allocator.owners is self.owners and allocator.abi is self.abi
                      and (index == 0 or request is d.requests[index - 1]),
                      'PC_ALLOCATOR_BINDING')
            h = t._handles
            A.require((request.h_client, request.h_device, request.h_subdevice, request.h_vas,
                       request.gpu_uuid, request.rm_ctrl_fd) ==
                      (h.client, h.device, h.subdevice, h.vas, t.uuid, self.backend.fds['ctl'])
                      and request.h_memory == backing.memory
                      and request.memory_class == backing.memory_class, 'PC_ALLOCATOR_TARGET')
            location = A.field_value(allocator.observed['attr'], self.abi.const('NVOS32_ATTR_LOCATION_SHIFT'),
                                     self.abi.const('NVOS32_ATTR_LOCATION_MASK'))
            A.require(location == backing.location == self.abi.const('NVOS32_ATTR_LOCATION_PCI')
                      and allocator.observed['format'] == self.abi.const('NV_MMU_PTE_KIND_GENERIC_MEMORY'),
                      'PC_ALLOCATION_PROFILE')
        for b in self.bindings:
            a, back = b.allocator, self.mappings.records[b.mapping.mapping_id].backing
            A.require(a.req.base == b.gpu_base == a.observed['gpu_base'] == b.cpu_base
                      and a.observed['arena_size'] == b.allocation_size == back.size
                      and b.memory == back.memory == b.owner.returned and back.owner is b.owner,
                      'PC_DATA_ALLOCATION')
        PP.input_pins()


class PacketPublicationModel(_PacketPublicationCore):
    """Fixed CPU-only implementation; no native policy or arbitrary subclasses."""
    def __init__(self, bridge, words, *, record=None):
        A.require(type(self) is PacketPublicationModel, 'PC_IMPLEMENTATION')
        super().__init__(bridge, words, record=record)

    def _admit_words(self, words):
        A.require(not isinstance(words, M.N.NativeWords) and getattr(words, 'mode', None) == 'CPU_MODEL',
                  'PC_MODEL_ONLY')

    def _make_transport(self):
        return M.ModelTransport(self.schedule, self.words,
            record=self._record if self.record is not None else None, packet_check=self._check)

    def _words_bound(self):
        return self.words is self._words and self.words.mode == 'CPU_MODEL'

    def _transport_type(self):
        return M.ModelTransport

    def _attach_transport(self):
        self.transport.attach_model(self)

    def _expected_receipt(self):
        return {'status': 'MODEL_BOUND_PUBLICATION_SEQUENCE_RECORDED',
                'completion_verified': False, 'retained': True,
                'mode': 'CPU_MODEL', 'publication_effects': 5}

    def _make_result(self):
        return PublicationResult(self.preparation, self.scheduled, 5, 5)

    def _owner_label(self):
        return 'work:packet_publication_model'
