"""Retained P0 completion protocol. No bootstrap, cleanup or hardware authority.

Import captures clock/wait without invoking them. Only the already rooted native
publication may be observed; all resources remain retained even on success.
Trusted CPython, admitted modules and exclusive same-thread ownership are required.
"""
from dataclasses import dataclass
import sys
import threading
import time

import native_packet_publication as P
import post_execution_images as PE

C, A, N = P.C, P.A, P.N
_CLOCK, _WAIT = time.monotonic_ns, time.sleep
_VERIFY = PE.verify
_MODULE = sys.modules[__name__]
_TIMEOUT_NS, _MAX_POLLS, _WAIT_SECONDS = 1_000_000_000, 1024, 0.001
_POST_TIMEOUT_NS = 10_000_000_000


@dataclass(frozen=True)
class CompletionEvent:
    component: str
    sequence: int
    operation: str
    stage: str
    attempt: int
    returned: bool


@dataclass(frozen=True)
class CompletionEvidence:
    control: bytes
    data: tuple
    get: int
    put: int
    signal: int
    events: tuple
    clock_values: tuple


@dataclass(frozen=True)
class CompletionResult:
    prefix: int
    signal: int
    polls: int
    operations: tuple
    image_policy: PE.ModelResult
    evidence: CompletionEvidence
    status: str = 'CPU_NATIVE_COMPLETION_PROTOCOL_MODEL_VERIFIED'
    signal_returned: bool = True
    acquire_returned: bool = True
    retained: bool = True
    native_execution_proven: bool = False
    flight_retirement_authorized: bool = False
    health_verified: bool = False
    evidence_persisted: bool = False


class PacketCompletionNative:
    def __init__(self, publication):
        A.require(type(self) is PacketCompletionNative, 'CC_IMPLEMENTATION')
        A.require(type(publication) is P.PacketPublicationNative
                  and publication.phase == 'NEW', 'CC_PUBLICATION_TYPE')
        A.require(type(publication.transport) is P._NativePacketTransport,
                  'CC_TRANSPORT_TYPE')
        A.require(getattr(publication, '_completion', None) is None
                  and getattr(publication, '_completion_original', None) is None,
                  'CC_EXISTS')
        # Admission is deliberately before attach(publication): NEW expects None.
        C._PacketPublicationCore._check(publication)
        self.publication = self._publication = publication
        self.thread = threading.get_ident()
        self.data = publication._originals[0]
        self._retained = (publication, self.data)
        self.words = publication.words
        self.inputs, self.prefix, self.signal = publication.inputs, publication.prefix, publication.signal
        self.initial_userd = publication.expected_userd
        self.control_image, self.expected_data = publication.control_image, publication.expected_data
        self.bindings, self.arena = publication.bindings, publication.arena
        self.roles = (PE.CI.P.AI.D.ROLES if type(self.inputs.workload) is PE.CI.P.AI.D.AffineLayout
                      else PE.D.ROLES)
        self.targets = tuple((address, size) for address, size, _ in publication.targets)
        self._observer = publication._observer
        self._clock, self._wait, self._verify = _CLOCK, _WAIT, _VERIFY
        self._acquire_function = N.NativeWords.acquire
        self._acquire = self.words.acquire
        self._read_function = N.NativeWords.read32
        self._read32 = self.words.read32
        self._read_bytes = publication.read_bytes
        self._registry = publication._native_custody.registry
        self._root = publication._native_custody.root
        self._native_custody = publication._native_custody
        self._modules = (P, PE, C, N, _MODULE)
        self._sizes()
        slots = {s.label: s for s in self.inputs.layout.slots}
        base, size = self.targets[0]
        self.word_targets = (base + slots['completion'].offset,
                             base + slots['userd'].offset + 0x88,
                             base + slots['userd'].offset + 0x8c)
        for address in self.word_targets:
            N.span(base, size, address)
        completion_offset = self.word_targets[0] - base
        userd_offset = slots['userd'].offset
        A.require(self.control_image.raw[completion_offset:completion_offset + 4] == bytes(4)
                  and self.control_image.raw[userd_offset + 0x88:userd_offset + 0x90] == bytes(8),
                  'CC_INITIAL_STATE')
        self.phase, self.busy = 'NEW', False
        self.failure = self.failure_handler_error = self.result = None
        self.publication_history = self.receipt_history = None
        self._verified_result = self._verified_image = None
        self.events, self.observations, self.clock_values, self.operations = [], [], [], []
        self.polls, self.acquire_calls, self.sequence = 0, 0, 0
        self.start = self.deadline = self.post_deadline = self.last_clock = None
        self._anchors = tuple((name, getattr(self, name)) for name in (
            'publication', '_publication', 'data', 'words', 'inputs', 'initial_userd',
            'control_image', 'expected_data', 'bindings', 'arena', 'roles', 'targets',
            'word_targets', '_observer', '_clock', '_wait', '_verify', '_acquire_function',
            '_acquire', '_read_function', '_read32', '_read_bytes', '_registry', '_root',
            '_native_custody', '_modules', '_retained', 'events', 'observations', 'clock_values', 'operations'))
        self._image = C.image_value((self.inputs, self.prefix, self.signal, self.initial_userd,
                                    self.control_image, self.expected_data, self.targets,
                                    self.word_targets, self.roles))
        self._local_check()
        # Last: reserve the association only after all pure admission has passed.
        publication._completion = publication._completion_original = self

    def _sizes(self):
        if type(self.inputs.workload) is PE.CI.P.AI.D.AffineLayout:
            A.require(type(self.prefix) is int and self.prefix == 1, 'CC_INPUT_RANGE')
        A.require(type(self.prefix) is int and 1 <= self.prefix <= 40
                  and type(self.signal) is int and 0 < self.signal < 1 << 32, 'CC_INPUT_RANGE')
        A.require(len(self.bindings) == len(self.inputs.placements) == len(self.expected_data) == 4
                  and tuple(b.role for b in self.bindings) == self.roles, 'CC_DATA_ROLES')
        A.require(self.arena.size == self.inputs.layout.arena.allocation_size
                  == len(self.control_image.raw), 'CC_CONTROL_SIZE')
        A.require(all(b.allocation_size == p.allocation_size == len(raw)
                      for b, p, raw in zip(self.bindings, self.inputs.placements, self.expected_data)),
                  'CC_DATA_SIZE')
        A.require(self.targets == ((self.arena.cpu_base, self.arena.size),
                  *((b.cpu_base, b.allocation_size) for b in self.bindings)), 'CC_COPY_TARGETS')

    def _local_check(self):
        A.require(type(self) is PacketCompletionNative and threading.get_ident() == self.thread,
                  'CC_IMPLEMENTATION_CHANGED')
        A.require(all(getattr(self, name) is value for name, value in self._anchors),
                  'CC_REFERENCE_CHANGED')
        A.require(sys.modules.get('native_packet_publication') is self._modules[0]
                  and sys.modules.get('post_execution_images') is self._modules[1]
                  and sys.modules.get('packet_publication') is self._modules[2]
                  and sys.modules.get('native_words_binding') is self._modules[3]
                  and sys.modules.get(__name__) is self._modules[4], 'CC_MODULE_CHANGED')
        A.require(_CLOCK is self._clock and _WAIT is self._wait
                  and _VERIFY is self._verify and PE.verify is self._verify,
                  'CC_CALLBACK_CHANGED')
        A.require(N.NativeWords.acquire is self._acquire_function
                  and C.method_is(self.words.acquire, self.words, self._acquire_function)
                  and C.method_is(self._acquire, self.words, self._acquire_function),
                  'CC_ACQUIRE_CHANGED')
        A.require(N.NativeWords.read32 is self._read_function
                  and C.method_is(self.words.read32, self.words, self._read_function)
                  and C.method_is(self._read32, self.words, self._read_function), 'CC_READ_CHANGED')
        c = self._publication
        A.require(type(c) is P.PacketPublicationNative and c._native_custody is self._native_custody
                  and c.words is self.words and c.inputs is self.inputs
                  and c.read_bytes is self._read_bytes and c.record is c._observer is self._observer,
                  'CC_PUBLICATION_BINDING')
        A.require(self._native_custody.registry is self._registry
                  and self._registry.root is self._root, 'CC_ROOT_CHANGED')
        A.require(C.image_value((self.inputs, self.prefix, self.signal, self.initial_userd,
                                self.control_image, self.expected_data, self.targets,
                                self.word_targets, self.roles)) == self._image, 'CC_VALUE_CHANGED')
        self._sizes()
        A.require((_TIMEOUT_NS, _MAX_POLLS, _WAIT_SECONDS, _POST_TIMEOUT_NS) == (1_000_000_000, 1024, 0.001, 10_000_000_000),
                  'CC_BUDGET_CHANGED')

    def _check(self):
        self._local_check()
        A.require(self.busy is True and self.phase in ('WAITING', 'ACQUIRING', 'READING'),
                  'CC_PHASE')
        C._PacketPublicationCore._check_published(self._publication, self)

    def _verified_value(self):
        return (C.image_value((self.result, self.events, self.observations,
                              self.clock_values, self.operations, self.polls,
                              self.acquire_calls, self.sequence, self.start,
                              self.deadline, self.post_deadline, self.last_clock)),
                self.publication_history, self.receipt_history)

    def _check_verified(self):
        """Pure terminal custody; does not authorize release or change phase.

        Called while the original registry is ACTIVE, before any flight removal.
        Health, durable evidence and channel disable remain separate obligations.
        """
        self._local_check()
        c = self._publication
        A.require(self.phase == 'VERIFIED_HELD' and self.busy is False
                  and self.data.busy is False and c.busy is False
                  and c.phase == 'PUBLISHED_UNCONFIRMED', 'CC_VERIFIED_PHASE')
        A.require(c._completion is self and c._completion_original is self,
                  'CC_VERIFIED_ASSOCIATION')
        A.require(c._associated and c._flight_installed
                  and c.transport.phase == 'PUBLISHED_UNCONFIRMED'
                  and c.transport.busy is False
                  and c.result is c._published_result
                  and C.image_value(c.result) == c._published_image
                  and c.result == c._make_result()
                  and c.transport.result is c._published_receipt
                  and C.PP.value_image(c.transport.result) == c._published_receipt_image
                  and c.transport.result == c._expected_receipt(),
                  'CC_VERIFIED_PUBLICATION')
        A.require(type(self.result) is CompletionResult
                  and self.result is self._verified_result
                  and self._verified_value() == self._verified_image
                  and self.acquire_calls == 1
                  and self.result.evidence.signal == self.signal
                  and self.result.evidence.get == self.result.evidence.put == 1,
                  'CC_VERIFIED_RESULT')
        # Same invariant body as publication/completion, with a terminal wrapper
        # instead of pretending that another completion read is in progress.
        C._PacketPublicationCore._check_custody(c)

    def _time(self):
        now = self._clock()
        A.require(type(now) is int and now >= 0, 'CC_CLOCK_RESULT')
        A.require(self.last_clock is None or now >= self.last_clock, 'CC_CLOCK_BACKWARD')
        self.last_clock = now
        self.clock_values.append(now)
        if self.start is None:
            self.start, self.deadline = now, now + _TIMEOUT_NS
        limit = self.deadline if self.phase == 'WAITING' else self.post_deadline
        A.require(type(limit) is int and now < limit, 'CC_DEADLINE')
        return now

    def _boundary(self):
        self._check()
        now = self._time()
        # The captured clock is still a callback and may have changed custody.
        self._check()
        return now

    def _event(self, operation, stage, attempt):
        event = CompletionEvent('packet_completion', self.sequence, operation, stage,
                                attempt, stage == 'after')
        self.sequence += 1
        payload = dict(vars(event))
        if self._observer is not None:
            returned = self._observer(payload)
            A.require(returned is None, 'CC_OBSERVER_RESULT')
        A.require(C.PP.value_image(payload) == C.PP.value_image(vars(event)), 'CC_EVENT_CHANGED')
        self.events.append(event)

    def _operation(self, operation, effect):
        attempt = len(self.operations)
        self._boundary()
        self._event(operation, 'before', attempt)
        self._boundary()
        self.operations.append(operation)
        returned = effect()
        self._boundary()
        self._event(operation, 'after', attempt)
        self._boundary()
        return returned

    def _word(self, address):
        base, size = self.targets[0]
        N.span(base, size, address)
        value = self._read32(base, size, address)
        A.require(type(value) is int and 0 <= value < 1 << 32, 'CC_WORD_RESULT')
        return value

    def _poll(self):
        A.require(self.polls < _MAX_POLLS, 'CC_POLL_BUDGET')
        self.polls += 1
        return self._word(self.word_targets[0])

    def _fence(self):
        A.require(self.acquire_calls == 0, 'CC_ACQUIRE_ONCE')
        self.acquire_calls += 1
        returned = self._acquire()
        A.require(returned is None, 'CC_ACQUIRE_RESULT')

    def _copy(self, index):
        address, size = self.targets[index]
        raw = self._read_bytes(address, size)
        A.require(type(raw) is bytes and len(raw) == size, 'CC_COPY_RESULT:' + str(index))
        self.observations.append(raw)
        return raw

    def _wait_once(self):
        remaining = (self.deadline - self.last_clock) / 1_000_000_000
        A.require(remaining > 0, 'CC_DEADLINE')
        returned = self._wait(min(_WAIT_SECONDS, remaining))
        A.require(returned is None, 'CC_WAIT_RESULT')

    def _fail(self, exc):
        self.phase, self.result, self.failure = 'FAILED_HELD', None, exc
        c = self._retained[0]
        try:
            c._mark_failed(exc)
        except BaseException as secondary:
            self.failure_handler_error = secondary
            C._PacketPublicationCore._mark_failed(c, exc)

    def finish(self):
        A.require(type(self) is PacketCompletionNative, 'CC_IMPLEMENTATION')
        A.require(self.phase == 'NEW' and self.busy is False
                  and threading.get_ident() == self.thread, 'CC_CLOSED')
        c, data = self._retained
        A.require(c.phase == 'PUBLISHED_UNCONFIRMED' and c.busy is False
                  and data.busy is False, 'CC_PUBLICATION_STATE')
        self.phase, self.busy, data.busy = 'WAITING', True, True
        try:
            self.publication_history, self.receipt_history = c._published_image, c._published_receipt_image
            self._boundary()
            while True:
                signal = self._operation('poll', self._poll)
                A.require(signal in (0, self.signal), 'CC_FOREIGN_SIGNAL')
                if signal == self.signal:
                    break
                A.require(self.polls < _MAX_POLLS, 'CC_POLL_BUDGET')
                self._operation('wait', self._wait_once)
            # Signal matched under the GPU wait deadline. CPU verification has
            # its own finite budget; it does not extend GPU polling.
            A.require(type(self.last_clock) is int, 'CC_CLOCK_RESULT')
            self.post_deadline = self.last_clock + _POST_TIMEOUT_NS
            self.phase = 'ACQUIRING'
            self._operation('acquire', self._fence)
            self.phase = 'READING'
            control = self._operation('control', lambda: self._copy(0))
            raw_data = tuple(self._operation(role, lambda i=i: self._copy(i + 1))
                             for i, role in enumerate(self.roles))
            get = self._operation('get', lambda: self._word(self.word_targets[1]))
            A.require(get == 1, 'CC_GET')
            put = self._operation('put', lambda: self._word(self.word_targets[2]))
            A.require(put == 1, 'CC_PUT')
            policy = self._verify(self.inputs, self.prefix, self.signal, self.initial_userd,
                                  control, raw_data, get, put)
            self._boundary()
            final = self._operation('final_signal', lambda: self._word(self.word_targets[0]))
            A.require(final == self.signal, 'CC_FINAL_SIGNAL')
            self._boundary()
            evidence = CompletionEvidence(control, raw_data, get, put, final,
                                          tuple(self.events), tuple(self.clock_values))
            self.result = CompletionResult(self.prefix, self.signal, self.polls,
                                           tuple(self.operations), policy, evidence)
            self._verified_result = self.result
            self._verified_image = self._verified_value()
            self.phase = 'VERIFIED_HELD'
            return self.result
        except BaseException as exc:
            self._fail(exc)
            raise
        finally:
            self.busy, data.busy = False, False
