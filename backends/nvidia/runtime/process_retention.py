"""One process-owned root and main-thread retention boundary (CPU candidate).

Trusted Python, one imported module instance and exclusive ownership are required.
This does not validate native resources, grant arming/retirement, or survive forced
process termination. Import installs no handlers. serve() is an explicit process
entry: an attempted root may return only through validated full closure.
Synthetic children exercise retention; hardware execution remains separate.
"""
import os
import signal
import sys
import threading
import time
from types import MappingProxyType


class RetentionError(RuntimeError):
    pass


def require(ok, reason):
    if not ok:
        raise RetentionError(reason)


class _Retention:
    NAMES = ('nonce', 'owners', 'backend', 'tree', 'recorder', 'events', 'words',
             'preparation', 'schedule', 'publication', 'health', 'identity')

    def __init__(self):
        self.phase = 'EMPTY'
        self._root, self._anchors = None, {}
        self._pid = os.getpid()
        self._attempted = False
        self.stop_requested = False
        self.primary = self.secondary = self.result = None
        self.error_count = 0
        self._reporters = []
        self._closure_binding = None

    @property
    def root(self):
        return self._root

    @property
    def anchors(self):
        return MappingProxyType(self._anchors)

    def _thread(self):
        require(threading.get_ident() == threading.main_thread().ident, 'RETENTION_THREAD')
        require(os.getpid() == self._pid, 'RETENTION_PROCESS')

    def reserve(self, root):
        self._thread()
        require(self.phase == 'EMPTY' and self._root is None, 'RETENTION_RESERVED')
        require(root is not None, 'RETENTION_ROOT')
        # Capture before inspecting configuration: even a bad property cannot
        # make the original root disappear from the outer process boundary.
        self._root, self.phase = root, 'ROOTED'
        for name in self.NAMES:
            self._anchors[name] = getattr(root, name, None)
        require(type(self._anchors['owners']) is list
                and type(self._anchors['events']) is list, 'RETENTION_LEDGER')
        require(type(self._anchors['nonce']) is str and bool(self._anchors['nonce']),
                'RETENTION_NONCE')
        self._same()

    def _same(self):
        require(self._root is not None, 'RETENTION_ROOT')
        for name, original in self._anchors.items():
            require(getattr(self._root, name, None) is original,
                    'RETENTION_ANCHOR_CHANGED:' + name)
        owners = self._anchors['owners']
        backend, tree = self._anchors['backend'], self._anchors['tree']
        if backend is not None:
            require(backend.owners is owners, 'RETENTION_BACKEND_LEDGER')
        if tree is not None:
            require(tree.owners is owners and tree.backend is backend,
                    'RETENTION_TREE_BINDING')

    def attach(self, name, value):
        self._thread()
        require(self.phase in ('ROOTED', 'ACTIVE'), 'RETENTION_CLOSED')
        require(name in self.NAMES and name not in ('nonce', 'owners', 'events'),
                'RETENTION_ANCHOR_NAME')
        require(value is not None and self._anchors.get(name) is None,
                'RETENTION_ANCHOR_EXISTS')
        self._same()
        # Retain first, then expose the reference; never accept a returned
        # resource factory as the registration operation.
        self._anchors[name] = value
        setattr(self._root, name, value)
        self._same()

    def request_stop(self, signum=None, frame=None):
        # Also the signal callback: flags only, no checks, reporting or cleanup.
        self.stop_requested = True

    def checkpoint(self):
        self._thread()
        require(self.phase == 'ACTIVE', 'RETENTION_NOT_ACTIVE')
        self._same()
        require(not self.stop_requested, 'RETENTION_STOP')

    def _register_closure(self, owner):
        self.checkpoint()
        require(self._closure_binding is None, 'RETENTION_CLOSURE_EXISTS')
        module = sys.modules.get('native_retirement')
        require(module is not None and type(owner) is module.NativeRetirement
                and owner.phase == 'NEW' and owner._registry is self
                and owner._root is self._root, 'RETENTION_CLOSURE_OWNER')
        self._closure_binding = (owner, module, module.NativeRetirement,
                                 module.NativeRetirement._closed)

    def _validate_closed(self, result):
        require(self._closure_binding is not None, 'RETENTION_CLOSURE_MISSING')
        owner, module, cls, check = self._closure_binding
        require(sys.modules.get('native_retirement') is module
                and module.NativeRetirement is cls and type(owner) is cls
                and cls._closed is check and owner._registry is self
                and owner._root is self._root, 'RETENTION_CLOSURE_CHANGED')
        require(result is owner.result, 'RETENTION_CLOSURE_RESULT')
        require(check(owner, result) is None, 'RETENTION_CLOSURE_CHECK')

    def exit_permitted(self):
        try:
            self._thread()
            if self.phase == 'EMPTY':
                return self._root is None and not self._attempted
            if self.phase == 'CLOSED':
                self._same()
                self._validate_closed(self.result)
                return True
            if self.phase != 'ROOTED' or self._attempted:
                return False
            self._same()
            a = self._anchors
            return (a['identity'] is None and a['health'] is None and not a['owners'] and a['backend'] is not None
                    and a['tree'] is not None and a['words'] is not None
                    and a['recorder'] is not None and a['events'] is not None
                    and a['backend'].phase == 'NEW' and a['words'].phase == 'NEW'
                    and a['backend'].sequence == 0)
        except BaseException:
            return False

    def _hold(self, exc=None):
        self.phase = 'HELD'
        if exc is not None:
            self.error_count += 1
            if self.primary is None:
                self.primary = exc
            elif self.secondary is None:
                self.secondary = exc
        # At most two exceptions, never an unbounded traceback list. Original
        # anchors/result remain strongly reachable even if public links drift.

    def diagnose(self, index):
        self._thread()
        require(type(index) is int and 0 <= index < len(self._reporters),
                'RETENTION_REPORTER_INDEX')
        callback = self._reporters[index]
        if callback is not None:
            try:
                callback(self)
                self._same()
            except BaseException as exc:
                self._reporters[index] = None
                self._hold(exc)

    def attempt(self, factory, *, reporters=()):
        self._thread()
        require(self.phase == 'ROOTED' and not self._attempted, 'RETENTION_ATTEMPT')
        require(callable(factory) and type(reporters) is tuple
                and len(reporters) <= 8 and all(callable(x) for x in reporters),
                'RETENTION_CALLBACKS')
        if self.stop_requested:
            return
        self._reporters = list(reporters)
        self._attempted, self.phase = True, 'ACTIVE'
        try:
            self.checkpoint()
            self.result = factory(self._root)
            self.checkpoint()
            if self._closure_binding is not None:
                self._validate_closed(self.result)
                self.phase = 'CLOSED'
        except BaseException as exc:
            self._hold(exc)
        if not self.exit_permitted():
            self._hold()
        for index in range(len(self._reporters)):
            self.diagnose(index)

    def _loop(self, observer, wait):
        while True:
            try:
                if observer is not None:
                    try:
                        observer(self)
                    except BaseException as exc:
                        observer = None
                        self._hold(exc)
                try:
                    wait(0.05)
                except BaseException as exc:
                    wait = time.sleep
                    self._hold(exc)
            except BaseException as exc:
                # Protect the body itself, not only callbacks in the attempt.
                self._hold(exc)

    def serve(self, root, factory, *, reporters=(), observer=None, wait=time.sleep):
        """Explicit main-thread process boundary; never returns from HELD.

        A caller may use a returned code only for an effect-free or verified CLOSED exit. No timeout,
        release flag, model result or stop command can break the retention loop.
        """
        self._thread()
        try:
            if self.stop_requested and self.exit_permitted():
                return 0
            for name in ('SIGINT', 'SIGTERM', 'SIGHUP'):
                signal.signal(getattr(signal, name), self.request_stop)
            self.reserve(root)
            self.attempt(factory, reporters=reporters)
        except BaseException as exc:
            if self.exit_permitted():
                return 1
            self._hold(exc)
        if self.exit_permitted():
            return 0
        self._hold()
        self._loop(observer, wait)


# Normal import supplies one registry. Private construction/reloading or hostile
# mutation is not a supported way to retry; the eventual verified loader must
# preserve this unique module identity just as it does other stateful components.
REGISTRY = _Retention()
