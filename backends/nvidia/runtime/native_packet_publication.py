"""Retained native publication composition; no bootstrap, completion or retirement.

Import is effect-free. Trusted source/loader, exclusive process/thread/fd/address
ownership and a correctly rooted bootstrap remain prerequisites. Returning from
the native wrappers is not proof of GPU acceptance or execution.
"""
import ctypes
from dataclasses import dataclass
import sys
import threading

import packet_publication as C
import process_retention as R
import preparation_upload as U

A, M, N = C.A, C.M, C.M.N
_REGISTRY = R.REGISTRY
_READ, _WRITE = U.native_read, U.native_write
_SIGNATURES = (
    ('ndx_word_abi', (), ctypes.c_uint64),
    ('ndx_word_read32', (ctypes.c_uint64,) * 3, ctypes.c_uint64),
    ('ndx_word_write32', (ctypes.c_uint64,) * 4, ctypes.c_uint32),
    ('ndx_word_release', (), None),
    ('ndx_word_acquire', (), None),
)


@dataclass(frozen=True)
class NativePublicationResult:
    preparation: C.PP.PreparationResult
    schedule: C.S.ScheduleResult
    reads: int
    effects: int
    native_calls_returned: bool = True
    native_execution_proven: bool = False
    completion_verified: bool = False
    flight_retirement_authorized: bool = False
    retained: bool = True


@dataclass(frozen=True)
class _Custody:
    registry: object
    root: object
    anchors: tuple
    bridge: object
    words: object
    library: object
    functions: dict
    symbols: tuple
    methods: tuple


def _receipt():
    return {'status': 'NATIVE_BOUND_PUBLICATION_CALLS_RETURNED', 'mode': 'NATIVE',
            'publication_effects': 5, 'completion_verified': False, 'retained': True}


class _NativePacketTransport(M.NativeTransport):
    """Private exact-controller arming; public NativeTransport stays read-only."""
    def __init__(self, controller):
        A.require(type(controller) is PacketPublicationNative and controller.phase == 'NEW',
                  'NATIVE_TRANSPORT_CONTROLLER')
        self._native_controller = controller
        self._native_custody = controller._native_custody
        super().__init__(controller.schedule, controller.words,
            record=controller._record if controller.record is not None else None,
            packet_check=controller._check)

    def attach_native(self, controller):
        A.require(not self.busy and threading.get_ident() == self.thread, 'TRANSPORT_BUSY')
        A.require(self.phase == 'INITIAL_EMPTY', 'TRANSPORT_ORDER')
        self.busy = True
        try:
            A.require(type(controller) is PacketPublicationNative
                      and controller is self._native_controller
                      and controller.transport is self and controller.schedule is self.schedule
                      and controller.phase == 'ARMED'
                      and controller._native_custody is self._native_custody,
                      'NATIVE_TRANSPORT_CONTROLLER')
            controller._native_check(controller)
            owner = controller.owner
            A.require(type(owner) is A.Owner and owner is controller._owner
                      and owner.state == A.UNCERTAIN and owner.undo is None
                      and owner.returned is controller.attempts
                      and len(self.owners) == len(self.parents) + 1
                      and all(a is b for a, b in zip(self.owners[:-1], self.parents))
                      and self.owners[-1] is owner, 'NATIVE_TRANSPORT_OWNER')
            identity = {'channel': self.binding.channel, 'upload_sha256': self.schedule.digest,
                        'put_address': self.targets[1], 'put': 1,
                        'doorbell_address': self.targets[2], 'token': self.targets[3]}
            A.require(C.PP.value_image(owner.requested) == C.PP.value_image(identity),
                      'NATIVE_TRANSPORT_IDENTITY')
            self.controller, self.flight, self.flight_identity = controller, owner, identity
            self._dependencies()
            self._packet_check()
            self.phase = 'ARMED'
        except BaseException as exc:
            self._preserve_failure(exc)
            raise
        finally:
            self.busy = False

    def release_after_doorbell(self):
        self._operation('release_after_doorbell', 'DOORBELL_WRITTEN', 'PUBLISHED_UNCONFIRMED',
                        self.functions['release'])
        try:
            self.result = _receipt()
            return dict(self.result)
        except BaseException as exc:
            self._preserve_failure(exc)
            raise


class PacketPublicationNative(C._PacketPublicationCore):
    """One exact retained native publication attempt, without release authority."""
    def __init__(self, bridge, words, *, record=None):
        A.require(type(self) is PacketPublicationNative, 'PC_IMPLEMENTATION')
        self._native_bridge = bridge
        super().__init__(bridge, words, record=record)

    def _admit_words(self, words):
        A.require(sys.modules.get('process_retention') is R and R.REGISTRY is _REGISTRY,
                  'NC_REGISTRY_MODULE')
        _REGISTRY.checkpoint()
        A.require(type(words) is N.NativeWords and words.phase == 'READY'
                  and words.pending is False and words.thread == threading.get_ident(),
                  'NC_WORDS')
        A.require(words._library is not None and type(words._functions) is dict
                  and words._file_fd is None, 'NC_LIBRARY')
        A.require(set(words._functions) == {name for name, _, _ in _SIGNATURES},
                  'NC_SYMBOL_SET')
        anchors = _REGISTRY.anchors
        A.require(set(anchors) == set(R._Retention.NAMES), 'NC_ANCHOR_SET')
        self._native_custody = _Custody(_REGISTRY, _REGISTRY.root,
            tuple((name, anchors[name]) for name in R._Retention.NAMES if name != 'publication'),
            self._native_bridge, words, words._library, words._functions,
            tuple((name, words._functions[name]) for name, _, _ in _SIGNATURES),
            tuple((name, getattr(N.NativeWords, name)) for name in ('read32', 'write32', 'release')))
        self._native_check(None)

    def _native_check(self, publication):
        state = self._native_custody
        registry, b, words = state.registry, state.bridge, state.words
        A.require(sys.modules.get('process_retention') is R and R.REGISTRY is _REGISTRY
                  and registry is _REGISTRY, 'NC_REGISTRY_MODULE')
        registry.checkpoint()
        A.require(registry.root is state.root and state.root is not None, 'NC_ROOT')
        anchors = registry.anchors
        A.require(set(anchors) == set(R._Retention.NAMES)
                  and all(anchors.get(name) is original for name, original in state.anchors),
                  'NC_ANCHOR_CHANGED')
        A.require(anchors['publication'] is publication, 'NC_PUBLICATION_ANCHOR')
        A.require(self._native_bridge is b and anchors['owners'] is b.owners
                  and anchors['backend'] is b.backend and anchors['tree'] is b.tree
                  and anchors['words'] is words and anchors['preparation'] is b.packet
                  and anchors['schedule'] is b, 'NC_ROOT_BINDING')
        A.require(b.backend.record is anchors['recorder'] and callable(anchors['recorder'])
                  and type(anchors['events']) is list, 'NC_RECORDER_BINDING')
        A.require(U.native_read is _READ and U.native_write is _WRITE
                  and b.packet.read_bytes is b.read_bytes is _READ
                  and b.packet.write_bytes is _WRITE, 'NC_COPY_CALLBACK')
        A.require(type(words) is N.NativeWords and words.phase == 'READY'
                  and words.pending is False and words.thread == threading.get_ident(),
                  'NC_WORDS')
        A.require(words._library is state.library and state.library is not None
                  and words._functions is state.functions and words._file_fd is None,
                  'NC_LIBRARY_CHANGED')
        A.require(type(words._functions) is dict
                  and set(words._functions) == {name for name, _, _ in _SIGNATURES}
                  and all(words._functions[name] is function for name, function in state.symbols),
                  'NC_SYMBOL_CHANGED')
        for name, args, result in _SIGNATURES:
            function = words._functions[name]
            A.require(isinstance(function, ctypes._CFuncPtr)
                      and type(function.argtypes) is tuple and function.argtypes == args
                      and function.restype is result, 'NC_SYMBOL_SIGNATURE')
        for name, function in state.methods:
            A.require(getattr(N.NativeWords, name) is function
                      and C.method_is(getattr(words, name), words, function), 'NC_WORD_METHOD')

    def _words_bound(self):
        self._native_check(None if self.phase == 'NEW' else self)
        return self.words is self._words is self._native_custody.words

    def _make_transport(self):
        return _NativePacketTransport(self)

    def _transport_type(self):
        return _NativePacketTransport

    def _attach_transport(self):
        self.transport.attach_native(self)

    def _expected_receipt(self):
        return _receipt()

    def _make_result(self):
        return NativePublicationResult(self.preparation, self.scheduled, 5, 5)

    def _owner_label(self):
        return 'work:packet_publication_native'
