"""One-shot execution lifecycle, initially the retained channel-disable stage.

No bootstrap or release authority. A successful disable is not an idle proof:
original completion/acquire/full readback remain mandatory. All owners remain
retained until health, persistence and retirement are separately implemented.
Trusted admitted CPython/modules and exclusive same-thread ownership required.
"""
from dataclasses import dataclass
import sys
import threading

import native_packet_completion as E
import rm_channel as T
import linux_backend as L

C, A = E.C, E.A
_MODULE = sys.modules[__name__]


@dataclass(frozen=True)
class DisableResult:
    envelope: bytes
    parameters: bytes
    returned_envelope: bytes
    returned_parameters: bytes
    syscall_return: int
    rm_status: int
    status: str = 'CHANNEL_DISABLE_RETURNED_HELD'
    native_execution_proven: bool = False
    retirement_authorized: bool = False
    retained: bool = True


class NativeExecution:
    def __init__(self, completion):
        A.require(type(self) is NativeExecution
                  and type(completion) is E.PacketCompletionNative, 'EXEC_TYPE')
        A.require(getattr(completion, '_execution', None) is None
                  and getattr(completion, '_execution_original', None) is None, 'EXEC_EXISTS')
        E.PacketCompletionNative._check_verified(completion)
        self.completion = completion
        self.publication = completion._publication
        self.tree = self.publication.tree
        self.backend = self.tree.backend
        self.owners = self.tree.owners
        self.flight = self.publication._owner
        self._originals = (completion, self.publication, self.tree, self.backend,
                           self.owners, self.flight)
        A.require(type(self.tree) is T.IdentityTree and type(self.backend) is L.LinuxBackend,
                  'EXEC_BACKEND_TYPE')
        self._query = self.tree._query
        self._query_function = T.IdentityTree._query
        self._ioctl_function = L.LinuxBackend.ioctl
        self._record = self.backend.record
        self._observed = self.tree.observed
        self._modules = (E, T, L, _MODULE)
        self._registry = completion._registry
        self._root = completion._root
        self.thread = threading.get_ident()
        handles = self.tree._handles
        self.request = self.tree.images.control(
            handles.client, handles.channel, 'NVA06F_CTRL_CMD_GPFIFO_SCHEDULE',
            'NVA06F_CTRL_GPFIFO_SCHEDULE_PARAMS',
            {'bEnable': 0, 'bSkipSubmit': 0, 'bSkipEnable': 0})
        self._request_image = C.image_value(self.request)
        self.phase, self.busy, self.attempted = 'NEW', False, False
        self.result = self.failure = self.failure_handler_error = None
        self._disabled_result = self._disabled_image = None
        self.observations = []
        self._anchors = tuple((name, getattr(self, name)) for name in (
            'completion', 'publication', 'tree', 'backend', 'owners', 'flight',
            '_originals', '_query', '_query_function', '_ioctl_function', '_record',
            '_observed', '_modules', '_registry', '_root', 'request', 'observations'))
        self._check(associated=False)
        completion._execution = completion._execution_original = self

    def _check(self, *, associated=True):
        A.require(type(self) is NativeExecution and threading.get_ident() == self.thread,
                  'EXEC_THREAD')
        A.require(all(getattr(self, name) is value for name, value in self._anchors),
                  'EXEC_REFERENCE_CHANGED')
        A.require(sys.modules.get('native_packet_completion') is self._modules[0]
                  and sys.modules.get('rm_channel') is self._modules[1]
                  and sys.modules.get('linux_backend') is self._modules[2]
                  and sys.modules.get(__name__) is self._modules[3], 'EXEC_MODULE_CHANGED')
        q, c, tree, backend, owners, flight = self._originals
        if associated:
            A.require(q._execution is q._execution_original is self, 'EXEC_ASSOCIATION')
        A.require(T.IdentityTree._query is self._query_function
                  and C.method_is(tree._query, tree, self._query_function)
                  and C.method_is(self._query, tree, self._query_function)
                  and L.LinuxBackend.ioctl is self._ioctl_function
                  and C.method_is(backend.ioctl, backend, self._ioctl_function)
                  and backend.record is self._record and tree.observed is self._observed,
                  'EXEC_QUERY_CHANGED')
        A.require(C.image_value(self.request) == self._request_image, 'EXEC_REQUEST_CHANGED')
        A.require(q._registry is self._registry and q._root is self._root
                  and c.tree is tree and c.backend is backend and tree.backend is backend
                  and tree.owners is owners and c.owners is owners and c._owner is flight,
                  'EXEC_BINDING')
        E.PacketCompletionNative._check_verified(q)

    def _disabled_value(self):
        return C.image_value((self.result, self.observations))

    def _check_disabled(self):
        A.require(self.phase == 'DISABLED_HELD' and self.busy is False
                  and self.attempted is True, 'EXEC_DISABLED_PHASE')
        NativeExecution._check(self)
        A.require(type(self.result) is DisableResult
                  and self.result is self._disabled_result
                  and self._disabled_value() == self._disabled_image,
                  'EXEC_DISABLED_RESULT')

    def _fail(self, exc):
        self.phase, self.result, self.failure = 'FAILED_HELD', None, exc
        try:
            E.PacketCompletionNative._fail(self._originals[0], exc)
        except BaseException as secondary:
            self.failure_handler_error = secondary

    def disable(self):
        A.require(type(self) is NativeExecution and self.phase == 'NEW'
                  and self.busy is False and not self.attempted
                  and threading.get_ident() == self.thread, 'EXEC_CLOSED')
        self.attempted, self.busy, self.phase = True, True, 'DISABLING'
        q, c, tree, backend, owners, flight = self._originals
        try:
            self._check()
            first = len(self._observed)
            try:
                returned = self._query(self.request)
            finally:
                # The tree captures raw output in finally, including failures
                # after the syscall in the backend's recorder. Never retry.
                self.observations.extend(dict(event) for event in self._observed[first:])
            A.require(len(self.observations) == 1, 'EXEC_DISABLE_OBSERVATION')
            event = self.observations[0]
            A.require(type(returned) is bytes and returned == self.request.parameters
                      and event['parameters_input'] == self.request.parameters.hex()
                      and event['parameters_output'] == returned.hex(), 'EXEC_DISABLE_PARAMETERS')
            out = bytes.fromhex(event['output'])
            status = tree.abi.struct('NVOS54_PARAMETERS').unpack(out)['status']
            A.require(event['request'] == 'IOCTL_RM_CONTROL'
                      and event['input'] == self.request.envelope.hex()
                      and type(event['rc']) is int and event['rc'] == 0
                      and status == tree.abi.const('NV_OK'), 'EXEC_DISABLE_STATUS')
            self._check()
            self.result = DisableResult(self.request.envelope, self.request.parameters,
                                        out, returned, event['rc'], status)
            self._disabled_result = self.result
            self._disabled_image = self._disabled_value()
            self.phase = 'DISABLED_HELD'
            return self.result
        except BaseException as exc:
            NativeExecution._fail(self, exc)
            raise
        finally:
            self.busy = False
