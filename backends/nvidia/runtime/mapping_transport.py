"""Original mapping-bound word operations; no native publication entry.

NativeTransport permits initial reads only. Native arming awaits the separate
packet/controller/process contract. ModelTransport's explicit test seam covers
the same ordered operations with a synthetic flight owner and injected words.
Neither variant opens, releases or owns RM resources; all references stay live.
"""
from copy import deepcopy
import threading
import types

import native_words_binding as N
from preparation_schedule import InitialSchedule
from replacement_inputs import arena as A


def method_identity(method):
    A.require(type(method) is types.MethodType, 'TRANSPORT_METHOD_TYPE')
    return method.__self__, method.__func__


class _Transport:
    def __init__(self, schedule, words, *, record=None, packet_check=None):
        A.require(type(schedule) is InitialSchedule and schedule.phase == 'ACKNOWLEDGED',
                  'TRANSPORT_SCHEDULE')
        A.require(record is None or callable(record), 'TRANSPORT_RECORDER')
        A.require(packet_check is None or type(packet_check) is types.MethodType,
                  'TRANSPORT_PACKET_CHECK')
        o, s, t = schedule.objects, schedule.session, schedule.tree
        A.require(getattr(o, '_mapping_transport', None) is None, 'TRANSPORT_EXISTS')
        self.schedule, self.objects, self.session, self.tree = schedule, o, s, t
        self.backend, self.owners, self.mappings = t.backend, t.owners, s._mappings
        self.arena, self.config, self.resource_config = s._arena, o.config, s.config
        self.upload, self.binding = schedule.upload, schedule.binding
        self.arena_binding, self.handles, self.instances = s._binding, t._handles, t._instances
        self.sysmem, self.usermode = s._cpu_mapping, o._usermode_mapping
        self.mapping_rows = tuple((b, self.mappings.records[b.mapping_id],
                                   self.mappings.records[b.mapping_id].spec,
                                   self.mappings.records[b.mapping_id].backing,
                                   self.mappings.records[b.mapping_id].fingerprint)
                                  for b in (self.sysmem, self.usermode))
        self.parents = tuple(self.owners)
        self.parent_undo = tuple(x.undo for x in self.parents)
        self.parent_values = deepcopy([(x.label, x.requested, x.returned) for x in self.parents])
        self.words, self._words = words, words
        self.thread = threading.get_ident()
        self.functions = {k: getattr(words, k) for k in ('read32', 'write32', 'release')}
        self.function_ids = {k: method_identity(v) for k, v in self.functions.items()}
        self.record = record
        self.packet_check = self._checker = packet_check
        self.checker_id = None if packet_check is None else method_identity(packet_check)
        self.failure_handler_error = None
        self.phase, self.busy, self.flight, self.controller = 'BOUND', False, None, None
        self.failure, self.result, self.events = None, None, []
        self.targets = self._targets()
        o._mapping_transport = self

    def _targets(self):
        b = self.binding
        A.require(self.sysmem.profile == 'sysmem' and self.usermode.profile == 'usermode'
                  and (self.arena_binding.cpu_base, self.arena_binding.size)
                      == (self.sysmem.cpu_base, self.sysmem.length)
                  and b.usermode_base == self.usermode.cpu_base
                  and b.userd_address == self.sysmem.cpu_base + self.config.userd_offset,
                  'TRANSPORT_ADDRESS_BINDING')
        c = self.tree.abi.struct('Nvc56fControl')
        A.require(c.size == 512 and c.fields['GPGet'][0] == 0x88
                  and c.fields['GPPut'][0] == 0x8c
                  and type(self.config.userd_offset) is int
                  and 0 <= self.config.userd_offset <= self.sysmem.length - 512,
                  'TRANSPORT_USERD')
        A.require(b.doorbell_address == self.usermode.cpu_base
                  + self.tree.abi.const('NVC361_NOTIFY_CHANNEL_PENDING')
                  and type(b.token) is int and 0 <= b.token < 1 << 32,
                  'TRANSPORT_DOORBELL')
        get, put, door = b.userd_address + 0x88, b.userd_address + 0x8c, b.doorbell_address
        for m, a in ((self.sysmem, get), (self.sysmem, put), (self.usermode, door)):
            N.span(m.cpu_base, m.length, a)
        return get, put, door, b.token

    def _dependencies(self):
        o, s, t, m = self.objects, self.session, self.tree, self.mappings
        A.require(o._mapping_transport is self and o._initial_schedule is self.schedule
                  and o._initial_upload is self.upload and o._session is s
                  and s._tree is t and t.backend is self.backend
                  and s._mappings is m and s._arena is self.arena
                  and self.schedule.objects is o and self.schedule.session is s
                  and self.schedule.tree is t and self.schedule.upload is self.upload
                  and self.schedule.owners is self.owners, 'TRANSPORT_ASSOCIATION')
        o._owned()
        A.require(self.owners is t.owners and self.owners is self.backend.owners,
                  'TRANSPORT_LEDGER')
        expected = self.parents + ((self.flight,) if self.flight is not None else ())
        A.require(len(self.owners) == len(expected)
                  and all(x is y for x, y in zip(self.owners, expected)), 'TRANSPORT_LEDGER')
        A.require(all(x.state == A.CERTAIN and x.undo is undo
                      for x, undo in zip(self.parents, self.parent_undo))
                  and [(x.label, x.requested, x.returned) for x in self.parents] == self.parent_values,
                  'TRANSPORT_PARENT_CHANGED')
        if self.flight is not None:
            A.require(self.flight.state == A.UNCERTAIN and self.flight.undo is None
                      and self.controller.transport is self
                      and self.controller.schedule is self.schedule
                      and self.controller.owner is self.flight
                      and self.controller.phase == 'ARMED'
                      and self.flight.requested == self.flight_identity,
                      'TRANSPORT_FLIGHT')
        A.require(o.phase == 'PREPARED' and s.phase == 'ARENA_READY'
                  and t.phase == 'IDENTIFIED' and self.backend.phase == 'ACTIVE'
                  and not self.backend.pending and self.arena.phase == A.OPEN
                  and m.phase == 'ACTIVE' and self.schedule.phase == 'ACKNOWLEDGED'
                  and self.upload.phase == 'DONE', 'TRANSPORT_PHASE')
        A.require(o._binding is self.binding and self.schedule.binding is self.binding
                  and s._binding is self.arena_binding and o.config is self.config
                  and s.config is self.resource_config and t._handles is self.handles
                  and t._instances is self.instances and s._cpu_mapping is self.sysmem
                  and o._usermode_mapping is self.usermode, 'TRANSPORT_BINDING')
        for binding, rec, spec, backing, fingerprint in self.mapping_rows:
            A.require(m.records.get(binding.mapping_id) is rec and rec.spec is spec
                      and rec.backing is backing and rec.fingerprint == fingerprint,
                      'TRANSPORT_MAPPING_IDENTITY')
            A.require(m.validate_binding(binding) is binding
                      and (rec.fd, rec.rm_address) == (binding.fd, binding.rm_address)
                      and m._range(rec)['state'] == 'M1_MATERIALIZED', 'TRANSPORT_MAPPING')
            m._fd(rec)
            rows = self.backend._snapshot(binding.cpu_base, binding.length)
            A.require(len(rows) == 1 and rows[0].start == binding.cpu_base
                      and rows[0].end == binding.cpu_base + binding.length
                      and rows[0].perms == 'rw-s' and rows[0].path == fingerprint[4],
                      'TRANSPORT_VMA')
        A.require(self._targets() == self.targets, 'TRANSPORT_TARGET_CHANGED')
        A.require(self.words is self._words and self.words.phase == 'READY'
                  and not self.words.pending and self.words.thread == self.thread
                  and threading.get_ident() == self.thread, 'TRANSPORT_WORDS')
        for name, method in self.functions.items():
            old_self, old_func = self.function_ids[name]
            now_self, now_func = method_identity(getattr(self.words, name))
            A.require(now_self is old_self and now_func is old_func
                      and method_identity(method) == (old_self, old_func),
                      'TRANSPORT_METHOD_CHANGED')

    def _packet_check(self):
        checker = self._checker
        if checker is None:
            A.require(self.packet_check is None and self.checker_id is None,
                      'TRANSPORT_PACKET_CHECK_CHANGED')
            return

        def same():
            A.require(type(self.packet_check) is types.MethodType
                      and type(checker) is types.MethodType
                      and method_identity(self.packet_check) == self.checker_id
                      and method_identity(checker) == self.checker_id,
                      'TRANSPORT_PACKET_CHECK_CHANGED')

        same()
        result = checker()
        same()
        A.require(result is None, 'TRANSPORT_PACKET_CHECK_RESULT')

    def _preserve_failure(self, exc):
        try:
            self._fail(exc)
        except BaseException as secondary:
            # The composition's outer failure path still reaches its captured
            # resources. A lower diagnostic failure must not replace the cause.
            self.failure_handler_error = secondary

    def _fail(self, exc):
        self.phase = 'FAILED_HELD' if self.flight is not None else 'FAILED'
        if self.flight is not None:
            self.flight.state = A.UNCERTAIN
        self.failure = {'type': type(exc).__name__, 'message': str(exc)}
        for layer in (self.objects, self.session, self.mappings, self.backend):
            if layer.phase in ('CLOSING', 'CLEANUP'):
                layer.phase = 'TERMINAL'
            elif layer.phase not in ('TERMINAL', 'CLOSED', 'TORN'):
                layer.phase = 'FAILED'
        if self.tree.phase not in ('TERMINAL', 'CLOSED'):
            self.tree._failed(exc)
        self.arena._fail('TRANSPORT_FAILED', self.failure)

    def _operation(self, name, before, after, effect, *, read=False):
        A.require(not self.busy and threading.get_ident() == self.thread, 'TRANSPORT_BUSY')
        A.require(self.phase == before, 'TRANSPORT_ORDER')
        self.busy = True
        self.phase = 'CALLING'
        event = {'operation': name, 'attempted': False}
        self.events.append(event)
        try:
            A.require(read or self.flight is not None, 'TRANSPORT_NOT_ARMED')
            self._dependencies()
            self._packet_check()
            if self.record is not None:
                self.record(dict(event))
            self._dependencies()
            self._packet_check()
            event['attempted'] = True
            value = effect()
            event['returned'], event['call_returned'] = value, True
            if read:
                A.require(type(value) is int and value == 0, 'TRANSPORT_INITIAL_NOT_EMPTY')
            else:
                A.require(value is None, 'TRANSPORT_EFFECT_RESULT')
            self._dependencies()
            self._packet_check()
            if self.record is not None:
                self.record(dict(event))
            self._dependencies()
            self._packet_check()
            self.phase = after
            return value
        except BaseException as exc:
            event['error'] = {'type': type(exc).__name__, 'message': str(exc)}
            self._preserve_failure(exc)
            raise
        finally:
            self.busy = False

    def read_initial_get(self):
        m = self.sysmem
        return self._operation('initial_get', 'BOUND', 'GET_ZERO',
            lambda: self.functions['read32'](m.cpu_base, m.length, self.targets[0]), read=True)

    def read_initial_put(self):
        m = self.sysmem
        return self._operation('initial_put', 'GET_ZERO', 'INITIAL_EMPTY',
            lambda: self.functions['read32'](m.cpu_base, m.length, self.targets[1]), read=True)

    def release_before_put(self):
        return self._operation('release_before_put', 'ARMED', 'PUT_READY', self.functions['release'])

    def put(self):
        m = self.sysmem
        return self._operation('put', 'PUT_READY', 'PUT_WRITTEN',
            lambda: self.functions['write32'](m.cpu_base, m.length, self.targets[1], 1))

    def release_before_doorbell(self):
        return self._operation('release_before_doorbell', 'PUT_WRITTEN', 'DOORBELL_READY',
                               self.functions['release'])

    def doorbell(self):
        m = self.usermode
        return self._operation('doorbell', 'DOORBELL_READY', 'DOORBELL_WRITTEN',
            lambda: self.functions['write32'](m.cpu_base, m.length, self.targets[2], self.targets[3]))

    def release_after_doorbell(self):
        self._operation('release_after_doorbell', 'DOORBELL_WRITTEN', 'PUBLISHED_UNCONFIRMED',
                        self.functions['release'])
        try:
            self.result = {'status': 'MODEL_BOUND_PUBLICATION_SEQUENCE_RECORDED',
                           'completion_verified': False, 'retained': True, 'mode': 'CPU_MODEL',
                           'publication_effects': 5}
            return dict(self.result)
        except BaseException as exc:
            self._preserve_failure(exc)
            raise


class NativeTransport(_Transport):
    """Initial live-bound reads; no native arming API in this increment."""
    def __init__(self, schedule, words, *, record=None, packet_check=None):
        A.require(type(words) is N.NativeWords and words.phase == 'READY', 'TRANSPORT_NATIVE_TYPE')
        super().__init__(schedule, words, record=record, packet_check=packet_check)


class ModelTransport(_Transport):
    """Explicit CPU-only seam, never selected by a native execution entry."""
    def __init__(self, schedule, words, *, record=None, packet_check=None):
        A.require(not isinstance(words, N.NativeWords)
                  and getattr(words, 'mode', None) == 'CPU_MODEL', 'TRANSPORT_MODEL_ONLY')
        super().__init__(schedule, words, record=record, packet_check=packet_check)

    def attach_model(self, controller):
        A.require(not self.busy and threading.get_ident() == self.thread, 'TRANSPORT_BUSY')
        A.require(self.phase == 'INITIAL_EMPTY', 'TRANSPORT_ORDER')
        self.busy = True
        try:
            A.require(controller.transport is self and controller.schedule is self.schedule
                      and controller.phase == 'ARMED', 'TRANSPORT_MODEL_CONTROLLER')
            owner = controller.owner
            A.require(type(owner) is A.Owner and owner.state == A.UNCERTAIN and owner.undo is None
                      and len(self.owners) == len(self.parents) + 1
                      and self.owners[-1] is owner, 'TRANSPORT_MODEL_OWNER')
            identity = {'channel': self.binding.channel, 'upload_sha256': self.schedule.digest,
                        'put_address': self.targets[1], 'put': 1,
                        'doorbell_address': self.targets[2], 'token': self.targets[3]}
            A.require(owner.requested == identity, 'TRANSPORT_MODEL_IDENTITY')
            self.controller, self.flight, self.flight_identity = controller, owner, identity
            self._dependencies()
            self._packet_check()
            self.phase = 'ARMED'
        except BaseException as exc:
            self._preserve_failure(exc)
            raise
        finally:
            self.busy = False
