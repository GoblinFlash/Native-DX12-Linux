"""One completed/disabled flight -> durable evidence -> original teardown.

This is a resource-lifecycle claim, not GPU qualification. The host/bootstrap
must separately admit actual native execution. No retry, remap or recovery.
"""
from dataclasses import dataclass
import sys
import threading

import native_execution as X
import native_execution_evidence as V
import native_execution_health as H
import data_resources as D

A, C = X.A, X.C
_MODULE = sys.modules[__name__]


@dataclass(frozen=True)
class ClosedResult:
    manifest_sha256: str
    kernel_last_sequence: int
    teardown_sha256: str
    status: str = 'RESOURCES_CLOSED'
    retained: bool = False
    native_execution_proven: bool = False
    device_qualified: bool = False


class NativeRetirement:
    def __init__(self, execution, store):
        A.require(type(self) is NativeRetirement and type(execution) is X.NativeExecution,
                  'RETIRE_TYPE')
        A.require(type(store) is V.EvidenceStore and store.phase == 'NEW', 'RETIRE_STORE')
        X.NativeExecution._check_disabled(execution)
        q, c, tree, backend, owners, flight = execution._originals
        A.require(getattr(q, '_retirement', None) is None, 'RETIRE_EXISTS')
        self.execution, self.store = execution, store
        self.completion, self.publication = q, c
        self.data, self.objects, self.session = q.data, c.objects, c.session
        self.tree, self.backend, self.words, self.owners, self.flight = tree, backend, q.words, owners, flight
        self._registry, self._root = q._registry, q._root
        self.health = self._registry.anchors['health']
        A.require(type(self.health) is H.KernelHealth and self.health.phase == 'ACTIVE'
                  and self.health._registry is self._registry and self.health._root is self._root,
                  'RETIRE_HEALTH')
        H.KernelHealth._same(self.health)
        self._teardown = D.DataResources.teardown
        self._modules = (X, V, H, D, _MODULE)
        self.thread = threading.get_ident()
        self.phase, self.attempted, self._removed = 'NEW', False, False
        self.failure = self.result = self._closed_result = self._closed_image = None
        self._persisted = self._persisted_image = self._health_evidence = None
        self._post_health = self._post_receipt = self._post_image = None
        self.teardown_error = self.health_error = self.persistence_error = None
        self._anchors = tuple((name, getattr(self, name)) for name in (
            'execution','store','completion','publication','data','objects','session',
            'tree','backend','words','owners','flight','_registry','_root','health',
            '_teardown','_modules'))
        self._registry._register_closure(self)
        q._retirement = self

    def _same(self):
        A.require(type(self) is NativeRetirement and threading.get_ident() == self.thread,
                  'RETIRE_THREAD')
        A.require(all(getattr(self, name) is value for name, value in self._anchors),
                  'RETIRE_REFERENCE_CHANGED')
        A.require(all(sys.modules.get(name) is module for name, module in zip(
            ('native_execution','native_execution_evidence','native_execution_health',
             'data_resources',__name__),self._modules)), 'RETIRE_MODULE_CHANGED')
        A.require(self._registry.root is self._root and self.completion._retirement is self
                  and self._registry.anchors['health'] is self.health, 'RETIRE_BINDING')

    def _before(self):
        self._same()
        A.require(D.DataResources.teardown is self._teardown
                  and C.method_is(self.data.teardown,self.data,self._teardown), 'RETIRE_TEARDOWN_CHANGED')
        X.NativeExecution._check_disabled(self.execution)
        H.KernelHealth._same(self.health)

    def _closed(self, result):
        # Deliberately no publication/completion custody after flight removal.
        self._same()
        A.require(self.phase == 'CLOSED' and self._removed and self.attempted
                  and type(result) is ClosedResult and result is self.result is self._closed_result
                  and C.image_value(result) == self._closed_image, 'RETIRE_CLOSURE_RESULT')
        A.require(self.data.objects is self.objects and self.data.session is self.session
                  and self.data.tree is self.tree and self.data.backend is self.backend
                  and self.objects._session is self.session and self.objects._tree is self.tree
                  and self.session._tree is self.tree and self.tree.backend is self.backend
                  and all(obj.owners is self.owners for obj in
                          (self.data,self.objects,self.tree,self.backend)), 'RETIRE_CLOSURE_BINDING')
        A.require(all(allocator.phase == A.TORN for allocator in self.publication._original_allocators),
                  'RETIRE_CLOSURE_ALLOCATORS')
        A.require(type(self.owners) is list and not self.owners
                  and all(obj.phase == 'CLOSED' for obj in
                          (self.data,self.objects,self.session,self.tree,self.backend))
                  and self.data.busy is False and not self.backend.pending
                  and not self.backend.fds and not self.backend.ranges,
                  'RETIRE_CLOSURE_RESOURCES')
        A.require(self.words.phase == 'READY' and self.words.pending is False
                  and self.words._file_fd is None and self.words._library is self.publication._native_custody.library
                  and self.health.phase == 'CLOSED' and self.health.fd is None
                  and self.health.uncertain_close_fd is None, 'RETIRE_CLOSURE_NATIVE')
        A.require(self.flight.state == 'RETIRED' and self.flight.undo is None
                  and self.completion.phase == self.publication.phase == 'RETIRED'
                  and self.execution.phase == 'CLOSED', 'RETIRE_CLOSURE_FLIGHT')
        A.require(self.store.phase == 'COMMITTED' and not self.store.fds
                  and self.store.result is self._persisted
                  and C.image_value(self.store.result) == self._persisted_image,
                  'RETIRE_CLOSURE_EVIDENCE')
        V.EvidenceStore._identity_check(self.store)
        A.require(self.store.post_result is self._post_receipt
                  and type(self._post_receipt) is V.TeardownPersistenceResult
                  and C.image_value(self._post_receipt) == self._post_image
                  and result.teardown_sha256 == self._post_receipt.sha256
                  and result.kernel_last_sequence == self._post_health.last_sequence
                  and self.teardown_error is self.health_error is self.persistence_error is None,
                  'RETIRE_CLOSURE_POST_EVIDENCE')

    def retire(self):
        A.require(type(self) is NativeRetirement and self.phase == 'NEW' and not self.attempted
                  and threading.get_ident() == self.thread, 'RETIRE_CLOSED')
        self.phase, self.attempted = 'RETIRING', True
        try:
            self._before()
            observed = H.KernelHealth.snapshot(self.health)
            H.KernelHealth.verify(self.health, observed)
            self._health_evidence = observed
            self._persisted = V.EvidenceStore.persist(self.store, self.execution, health_evidence=observed)
            self._persisted_image = C.image_value(self._persisted)
            # A new tail was not in the durable manifest: hold rather than
            # silently broaden the observation window or retry publication.
            latest = H.KernelHealth.snapshot(self.health)
            A.require(latest.baseline_sequence == observed.baseline_sequence
                      and latest.last_sequence == observed.last_sequence
                      and latest.records == observed.records, 'RETIRE_UNRECORDED_HEALTH')
            H.KernelHealth.verify(self.health, latest)
            self._before()
            A.require(self.store.phase == 'COMMITTED' and not self.store.fds
                      and self.store.result is self._persisted
                      and self.store.health_evidence is observed
                      and C.image_value(self.store.result) == self._persisted_image,
                      'RETIRE_EVIDENCE_CHANGED')
            # Last custody check above; no recorder/I/O/callback in this
            # in-memory transition. The original flight never gains an undo.
            A.require(self.owners and self.owners[-1] is self.flight, 'RETIRE_FLIGHT_TOP')
            self.flight.state = 'RETIRED'
            self.owners.pop()
            self._removed = True
            self.completion.phase = self.publication.phase = 'RETIRED'
            try:
                self._teardown(self.data, True)
            except BaseException as exc:
                self.teardown_error = exc
            # Observe the RM free/unmap window even if teardown stopped early.
            # No publication custody or retry is legal after the flight pop.
            try:
                self._post_health = H.KernelHealth.snapshot(self.health)
                H.KernelHealth.verify(self.health, self._post_health)
            except BaseException as exc:
                self.health_error = exc
            try:
                self._post_receipt = V.EvidenceStore.persist_teardown(self.store, self)
                self._post_image = C.image_value(self._post_receipt)
            except BaseException as exc:
                self.persistence_error = exc
            for error in (self.teardown_error, self.health_error, self.persistence_error):
                if error is not None:
                    raise error
            H.KernelHealth.close(self.health)
            self.execution.phase = 'CLOSED'
            self.result = ClosedResult(self._persisted.manifest_sha256,
                self._post_health.last_sequence, self._post_receipt.sha256)
            self._closed_result = self.result
            self._closed_image = C.image_value(self.result)
            self.phase = 'CLOSED'
            NativeRetirement._closed(self,self.result)
            return self.result
        except BaseException as exc:
            self.phase, self.failure, self.result = 'FAILED_HELD', exc, None
            # If interrupted immediately around pop, actual membership decides
            # whether the flight is still owned. Never reconstruct freed owners.
            removed = not any(owner is self.flight for owner in self.owners)
            if removed:
                self._removed = True
                self.flight.state = 'RETIRED'
                self.execution.phase, self.execution.failure = 'FAILED_HELD', exc
            else:
                X.NativeExecution._fail(self.execution, exc)
            raise
