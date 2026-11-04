"""Bounded /dev/kmsg observation, rooted before device effects.

Linux v6.18 Documentation/ABI/testing/dev-kmsg defines record sequences/EPIPE.
A contiguous observed log window is not a universal hardware-health proof.
No source fallback, retry after loss, log clearing, device writes or recovery.
"""
from dataclasses import dataclass
import errno
import os
import stat
import sys
import threading
import time

import process_retention as R

_REGISTRY, _MODULE = R.REGISTRY, sys.modules[__name__]
_RECORD_BYTES, _BASELINE_RECORDS, _WINDOW_RECORDS = 65536, 65536, 8192
_WINDOW_BYTES, _DRAIN_NS = 4 * 1024 * 1024, 5_000_000_000


class HealthError(RuntimeError):
    pass


def require(ok, reason):
    if not ok:
        raise HealthError(reason)


def fingerprint(info):
    return info.st_dev, info.st_ino, info.st_rdev, info.st_mode


def parse(raw):
    require(type(raw) is bytes and 0 < len(raw) <= _RECORD_BYTES
            and raw.endswith(b'\n') and b';' in raw, 'HEALTH_RECORD')
    header, message = raw.split(b';', 1)
    parts = header.split(b',')
    require(len(parts) >= 4 and all(p and p.isdigit() for p in parts[:3]), 'HEALTH_RECORD')
    priority, sequence, stamp = map(int, parts[:3])
    require(0 <= priority < 2048 and 0 <= sequence < 1 << 64
            and 0 <= stamp < 1 << 64, 'HEALTH_RECORD')
    return priority, sequence, stamp, parts[3], message


@dataclass(frozen=True)
class HealthEvidence:
    baseline_sequence: int
    last_sequence: int
    baseline_record: bytes
    records: tuple
    started_ns: int
    observed_ns: int
    nonce: str
    status: str = 'KERNEL_LOG_WINDOW_OBSERVED'
    retirement_authorized: bool = False
    native_execution_proven: bool = False


class KernelHealth:
    def __init__(self):
        require(type(self) is KernelHealth, 'HEALTH_TYPE')
        self.phase, self.fd = 'NEW', None
        self._fd = None
        self.failure = self.uncertain_close_fd = None
        self._root = self._registry = self._fingerprint = None
        self.thread = threading.get_ident()
        self.records, self.total_bytes = [], 0
        self.last_sequence = self.last_stamp = None
        self.baseline_record = self.baseline_sequence = self.started_ns = None
        self._evidence = self._evidence_value = None

    def _same(self):
        require(type(self) is KernelHealth and threading.get_ident() == self.thread,
                'HEALTH_THREAD')
        require(sys.modules.get('process_retention') is R and R.REGISTRY is _REGISTRY
                and sys.modules.get(__name__) is _MODULE and self._registry is _REGISTRY,
                'HEALTH_REGISTRY')
        require((_RECORD_BYTES, _BASELINE_RECORDS, _WINDOW_RECORDS, _WINDOW_BYTES, _DRAIN_NS)
                == (65536, 65536, 8192, 4 * 1024 * 1024, 5_000_000_000), 'HEALTH_POLICY')
        self._registry.checkpoint()
        require(self._registry.root is self._root and self._root.health is self
                and self._registry.anchors['health'] is self,
                'HEALTH_ROOT')
        require(type(self.fd) is int and self.fd == self._fd
                and fingerprint(os.fstat(self._fd)) == self._fingerprint
                and fingerprint(os.lstat('/dev/kmsg')) == self._fingerprint, 'HEALTH_FD_CHANGED')

    def _drain(self, baseline):
        limit = _BASELINE_RECORDS if baseline else _WINDOW_RECORDS
        began = time.monotonic_ns()
        for _ in range(limit + 1):
            self._same()
            require(time.monotonic_ns() - began < _DRAIN_NS, 'HEALTH_DRAIN_TIMEOUT')
            try:
                raw = os.read(self.fd, _RECORD_BYTES)
            except BlockingIOError as exc:
                require(exc.errno == errno.EAGAIN, 'HEALTH_READ')
                return
            except OSError as exc:
                # EPIPE is a lost window, never resume at the next record.
                raise HealthError('HEALTH_READ') from exc
            if not baseline:
                self.records.append(raw)
                self.total_bytes += len(raw)
                require(len(self.records) <= _WINDOW_RECORDS and self.total_bytes <= _WINDOW_BYTES,
                        'HEALTH_WINDOW_BUDGET')
            priority, sequence, stamp, flags, message = parse(raw)
            require(self.last_sequence is None or sequence == self.last_sequence + 1, 'HEALTH_SEQUENCE')
            # Kernel sequence is the loss/ordering signal; timestamps can regress.
            self.last_sequence, self.last_stamp = sequence, stamp
            if baseline:
                self.baseline_record = raw
            else:
                require(flags == b'-', 'HEALTH_FRAGMENT')
                lower = message.lower()
                require(priority % 8 > 4 and not any(token in lower for token in (
                    b'nvrm', b'nvidia', b'xid', b'gpu reset', b'fallen off', b'suppressed',
                    b'ratelimit', b'messages lost', b'watchdog', b'lockup', b'oom-kill')),
                    'HEALTH_KERNEL_EVENT')
        raise HealthError('HEALTH_DRAIN_BUDGET')

    def start(self):
        require(self.phase == 'NEW' and threading.get_ident() == self.thread, 'HEALTH_STATE')
        _REGISTRY.checkpoint()
        root, anchors = _REGISTRY.root, _REGISTRY.anchors
        backend, words = anchors['backend'], anchors['words']
        require(not anchors['owners'] and anchors['preparation'] is None
                and anchors['schedule'] is None and anchors['publication'] is None
                and (backend is None or (backend.phase == 'NEW' and backend.sequence == 0))
                and (words is None or words.phase == 'NEW'), 'HEALTH_TOO_LATE')
        require(anchors['health'] is None, 'HEALTH_EXISTS')
        self._registry, self._root = _REGISTRY, root
        _REGISTRY.attach('health', self)
        self.phase = 'STARTING'
        try:
            self.fd = os.open('/dev/kmsg', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
            self._fd = self.fd
            info = os.fstat(self._fd)
            require(stat.S_ISCHR(info.st_mode), 'HEALTH_SOURCE')
            self._fingerprint = fingerprint(info)
            self._drain(True)
            require(self.baseline_record is not None, 'HEALTH_EMPTY_BASELINE')
            self.baseline_sequence = self.last_sequence
            self.started_ns = time.monotonic_ns()
            self._same()
            self.phase = 'ACTIVE'
        except BaseException as exc:
            self.phase, self.failure = 'FAILED', exc
            raise

    def snapshot(self):
        require(self.phase == 'ACTIVE', 'HEALTH_STATE')
        try:
            self._drain(False)
            self._same()
            now = time.monotonic_ns()
            require(now >= self.started_ns, 'HEALTH_CLOCK')
            self._evidence = HealthEvidence(self.baseline_sequence, self.last_sequence,
                self.baseline_record, tuple(self.records), self.started_ns, now,
                self._registry.anchors['nonce'])
            self._evidence_value = tuple(vars(self._evidence).items())
            return self._evidence
        except BaseException as exc:
            self.phase, self.failure = 'FAILED', exc
            raise

    def verify(self, evidence):
        require(self.phase == 'ACTIVE', 'HEALTH_STATE')
        self._same()
        require(type(evidence) is HealthEvidence and evidence is self._evidence
                and tuple(vars(evidence).items()) == self._evidence_value
                and evidence.records == tuple(self.records)
                and evidence.last_sequence == self.last_sequence, 'HEALTH_EVIDENCE_CHANGED')

    def close(self):
        require(self.phase == 'ACTIVE', 'HEALTH_STATE')
        self._same()
        require(not self._registry.anchors['owners']
                and self._registry.anchors['backend'] is not None
                and self._registry.anchors['backend'].phase == 'CLOSED', 'HEALTH_CLOSE_UNSAFE')
        fd, self.fd, self.phase = self.fd, None, 'CLOSING'
        try:
            os.close(fd)
            self.phase = 'CLOSED'
        except BaseException as exc:
            self.uncertain_close_fd, self.failure, self.phase = fd, exc, 'FAILED'
            raise
