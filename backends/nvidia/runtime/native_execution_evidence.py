"""Durable packet observations. Persistence is not health or release authority.

The private new directory is never reused or cleaned up by this module. The
caller must retain this store through the original execution/root. Source/host
admission and the kernel health window are separate bootstrap obligations.
"""
from dataclasses import dataclass, fields, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import threading

import native_execution as X

A = X.A
_LIMIT = 16 * 1024 * 1024


def _json_value(value):
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is bytes:
        return {'bytes_hex': value.hex()}
    if type(value) in (tuple, list):
        return [_json_value(v) for v in value]
    if type(value) is dict and all(type(k) is str for k in value):
        return {k: _json_value(v) for k, v in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json_value(getattr(value, f.name)) for f in fields(value)}
    raise A.Stop('EVIDENCE_VALUE_TYPE', type=type(value).__name__)


def _json(value):
    return (json.dumps(_json_value(value), sort_keys=True, separators=(',', ':')) + '\n').encode()


@dataclass(frozen=True)
class PersistenceResult:
    directory: str
    manifest_sha256: str
    files: tuple
    evidence_persisted: bool = True
    health_verified: bool = False
    retirement_authorized: bool = False
    native_execution_proven: bool = False


@dataclass(frozen=True)
class TeardownPersistenceResult:
    sha256: str
    manifest_sha256: str
    size: int


def _error(exc):
    if exc is None:
        return None
    cause = exc.__cause__
    return {'type': type(exc).__name__, 'message': str(exc),
            'cause_type': None if cause is None else type(cause).__name__,
            'cause_errno': None if cause is None else getattr(cause, 'errno', None)}


class EvidenceStore:
    def __init__(self, directory):
        A.require(type(self) is EvidenceStore, 'EVIDENCE_TYPE')
        self.directory = Path(directory)
        self.thread = threading.get_ident()
        self.phase = 'NEW'
        self.execution = self.result = self.failure = self.close_error = None
        self.fds = []
        self._directory_fd = self._parent_fd = None
        self._directory_identity = None
        self._health = self._health_module = self.health_evidence = None
        self._post_owner = self.post_result = self.post_failure = None
        self._identity_registry = sys.modules['process_retention'].REGISTRY
        self._identity_root = self._identity_registry.root
        self._identity = self._identity_registry.anchors.get('identity')
        self._identity_module = sys.modules.get('bootstrap_identity')
        self._identity_receipt = self._identity_image = None
        if self._identity is not None:
            require_module = self._identity_module
            A.require(require_module is not None and type(self._identity) is require_module.BootstrapIdentity,
                      'EVIDENCE_IDENTITY_TYPE')
            require_module.BootstrapIdentity.verify(self._identity)
            self._identity_receipt = self._identity.result
            self._identity_image = X.C.image_value(self._identity_receipt)
        self._identity_check()

    def _identity_check(self):
        registry = self._identity_registry
        A.require(sys.modules['process_retention'].REGISTRY is registry
                  and registry.root is self._identity_root
                  and registry.anchors.get('identity') is self._identity,
                  'EVIDENCE_IDENTITY_BINDING')
        if self.execution is not None:
            A.require(self.execution._registry is registry, 'EVIDENCE_IDENTITY_REGISTRY')
        if self._identity is not None:
            A.require(sys.modules.get('bootstrap_identity') is self._identity_module,
                      'EVIDENCE_IDENTITY_MODULE')
            self._identity_module.BootstrapIdentity.verify(self._identity)
            A.require(self._identity.result is self._identity_receipt
                      and X.C.image_value(self._identity_receipt) == self._identity_image,
                      'EVIDENCE_IDENTITY_RECEIPT')

    def _identity_record(self):
        self._identity_check()
        return self._identity_receipt

    def _check(self):
        A.require(type(self) is EvidenceStore and threading.get_ident() == self.thread,
                  'EVIDENCE_THREAD')
        x = self.execution
        A.require(type(x) is X.NativeExecution and x._evidence_store is self,
                  'EVIDENCE_ASSOCIATION')
        X.NativeExecution._check_disabled(x)
        self._identity_check()
        if self._health is not None:
            A.require(sys.modules.get('native_execution_health') is self._health_module,
                      'EVIDENCE_HEALTH_MODULE')
            self._health_module.KernelHealth.verify(self._health, self.health_evidence)
        self._directory_check()

    def _directory_check(self):
        if self._directory_fd is not None:
            current = os.fstat(self._directory_fd)
            linked = os.stat(self.directory.name, dir_fd=self._parent_fd, follow_symlinks=False)
            A.require(stat.S_ISDIR(current.st_mode) and
                      (current.st_dev, current.st_ino) == self._directory_identity ==
                      (linked.st_dev, linked.st_ino), 'EVIDENCE_DIRECTORY_CHANGED')

    def _open(self, name, flags, *, directory_fd=None):
        fd = os.open(name, flags | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        self.fds.append(fd)
        return fd

    def _close_all(self):
        first = None
        while self.fds:
            fd = self.fds.pop()
            try:
                os.close(fd)  # One attempt; never retry an ambiguous close.
            except BaseException as exc:
                if first is None:
                    first = exc
        self._directory_fd = self._parent_fd = None
        if first is not None:
            raise first

    def _write(self, name, raw):
        self._io_check()
        fd = self._open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL,
                        directory_fd=self._directory_fd)
        info = os.fstat(fd)
        A.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == 0,
                  'EVIDENCE_FILE')
        offset = 0
        while offset < len(raw):
            count = os.write(fd, raw[offset:])
            A.require(type(count) is int and 0 < count <= len(raw) - offset, 'EVIDENCE_WRITE')
            offset += count
            self._io_check()
        os.fsync(fd)
        self._io_check()
        copied = bytearray()
        while len(copied) < len(raw):
            part = os.pread(fd, len(raw) - len(copied), len(copied))
            A.require(type(part) is bytes and bool(part), 'EVIDENCE_READBACK')
            copied.extend(part)
        A.require(bytes(copied) == raw and os.fstat(fd).st_size == len(raw), 'EVIDENCE_READBACK')
        self._io_check()
        return {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

    def _io_check(self):
        if self._post_owner is None:
            self._check()
            return
        # The resource ledger is already retired. Validate the original
        # coordinator/store binding, never the pre-retirement publication.
        z = self._post_owner
        module = sys.modules.get('native_retirement')
        A.require(type(self) is EvidenceStore and threading.get_ident() == self.thread,
                  'EVIDENCE_THREAD')
        A.require(module is not None and type(z) is module.NativeRetirement
                  and z.store is self and z.execution is self.execution
                  and self.execution._evidence_store is self and z._removed
                  and z.phase == 'RETIRING' and self.phase == 'COMMITTED'
                  and self.result is z._persisted
                  and X.C.image_value(self.result) == z._persisted_image,
                  'EVIDENCE_POST_BINDING')
        module.NativeRetirement._same(z)
        self._identity_check()
        self._directory_check()

    def persist_teardown(self, retirement):
        A.require(self._post_owner is None and self.post_result is None
                  and not self.fds and self.phase == 'COMMITTED', 'EVIDENCE_POST_CLOSED')
        self._post_owner = retirement  # Retained before filesystem effects.
        try:
            self._io_check()
            z, h = retirement, retirement.health
            raw = _json({'schema': 'native-packet-teardown.v1',
                'manifest_sha256': self.result.manifest_sha256,
                'bootstrap_identity': self._identity_record(),
                'health_evidence': z._post_health,
                'health_error': _error(z.health_error), 'teardown_error': _error(z.teardown_error),
                'health_observation': {'baseline_sequence': h.baseline_sequence,
                    'last_sequence': h.last_sequence, 'baseline_record': h.baseline_record,
                    'records': tuple(h.records), 'phase': h.phase},
                'remaining_owners': [owner.state for owner in z.owners],
                'bootstrap_events': None if self._identity is None else tuple(self._identity_registry.anchors['events']),
                'resource_phases': {name: getattr(z, name).phase for name in
                    ('data', 'objects', 'session', 'tree', 'backend')},
                'nonce': z._registry.anchors['nonce'], 'native_execution_proven': False})
            A.require(len(raw) <= _LIMIT, 'EVIDENCE_BUDGET')
            for ancestor in (self.directory, *self.directory.parents):
                A.require(not ancestor.is_symlink(), 'EVIDENCE_SYMLINK')
            self._parent_fd = self._open(str(self.directory.parent), os.O_RDONLY | os.O_DIRECTORY)
            self._directory_fd = self._open(self.directory.name, os.O_RDONLY | os.O_DIRECTORY,
                                            directory_fd=self._parent_fd)
            self._io_check()  # Original directory identity retained by persist().
            A.require(not os.path.lexists(self.directory / 'teardown.json'), 'EVIDENCE_POST_EXISTS')
            row = self._write('.teardown.pending', raw)
            self._io_check()
            os.rename('.teardown.pending', 'teardown.json',
                      src_dir_fd=self._directory_fd, dst_dir_fd=self._directory_fd)
            os.fsync(self._directory_fd)
            os.fsync(self._parent_fd)
            self._io_check()
            fd = self._open('teardown.json', os.O_RDONLY, directory_fd=self._directory_fd)
            info = os.fstat(fd)
            A.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                      and info.st_size == len(raw), 'EVIDENCE_POST_READBACK')
            copied = bytearray()
            while len(copied) < len(raw):
                part = os.pread(fd, len(raw) - len(copied), len(copied))
                A.require(type(part) is bytes and bool(part), 'EVIDENCE_POST_READBACK')
                copied.extend(part)
            A.require(bytes(copied) == raw, 'EVIDENCE_POST_READBACK')
            self._io_check()
            self._close_all()
            self._io_check()
            self.post_result = TeardownPersistenceResult(row['sha256'], self.result.manifest_sha256, row['size'])
            return self.post_result
        except BaseException as exc:
            # Do not call execution._fail after the flight has been removed.
            self.post_failure = exc
            raise
        finally:
            if self.fds:
                try:
                    self._close_all()
                except BaseException as secondary:
                    self.close_error = secondary

    def persist(self, execution, *, health_evidence=None):
        A.require(self.phase == 'NEW' and threading.get_ident() == self.thread, 'EVIDENCE_CLOSED')
        A.require(type(execution) is X.NativeExecution and
                  getattr(execution, '_evidence_store', None) is None, 'EVIDENCE_EXECUTION')
        X.NativeExecution._check_disabled(execution)
        self.execution = execution
        execution._evidence_store = self  # Retain before the first filesystem effect.
        self.phase = 'WRITING'
        try:
            if health_evidence is not None:
                module = sys.modules.get('native_execution_health')
                health = execution._registry.anchors['health']
                A.require(module is not None and type(health) is module.KernelHealth,
                          'EVIDENCE_HEALTH_TYPE')
                module.KernelHealth.verify(health, health_evidence)
                self._health, self._health_module, self.health_evidence = health, module, health_evidence
            path = self.directory
            A.require(path.is_absolute() and '..' not in path.parts and path.name not in ('', '.', '..'),
                      'EVIDENCE_PATH')
            for ancestor in (path, *path.parents):
                A.require(not ancestor.is_symlink(), 'EVIDENCE_SYMLINK')
            q = execution.completion
            result = q.result
            affine = type(q.inputs.workload) is X.E.PE.CI.P.AI.D.AffineLayout
            roles = X.E.PE.CI.P.AI.D.ROLES if affine else X.E.PE.D.ROLES
            A.require(q.roles == roles, 'EVIDENCE_DATA_ROLES')
            filenames = ('control.bin',) + tuple(role + '.bin' for role in roles)
            payloads = dict(zip(filenames, (result.evidence.control, *result.evidence.data)))
            payloads['inputs.json'] = _json(q.inputs)
            if self._identity is not None:
                payloads['bootstrap-events.json'] = _json(tuple(self._identity_registry.anchors['events']))
            if health_evidence is not None:
                payloads['kernel-window.json'] = _json(health_evidence)
            payloads['protocol.json'] = _json({
                'completion': {f.name: getattr(result, f.name) for f in fields(result) if f.name != 'evidence'},
                'signal': result.evidence.signal, 'get': result.evidence.get, 'put': result.evidence.put,
                'events': result.evidence.events, 'clock_values': result.evidence.clock_values,
                'disable': execution.result, 'disable_observations': execution.observations,
                'nonce': execution._registry.anchors['nonce'],
                'bootstrap_identity': self._identity_record(),
                'health_verified': False, 'native_execution_proven': False,
                'flight_retirement_authorized': False})
            A.require(sum(len(raw) for raw in payloads.values()) <= _LIMIT, 'EVIDENCE_BUDGET')
            self._check()
            self._parent_fd = self._open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
            os.mkdir(path.name, mode=0o700, dir_fd=self._parent_fd)
            self._directory_fd = self._open(path.name, os.O_RDONLY | os.O_DIRECTORY,
                                            directory_fd=self._parent_fd)
            info = os.fstat(self._directory_fd)
            self._directory_identity = (info.st_dev, info.st_ino)
            self._check()
            rows = {name: self._write(name, raw) for name, raw in payloads.items()}
            manifest_value = {'schema':'native-packet-observations.v1', 'files': rows,
                              'bootstrap_identity': self._identity_record(),
                              'health_verified':False, 'retirement_authorized':False}
            if affine:
                manifest_value.update(workload_profile='affine-u32', roles=roles)
            manifest = _json(manifest_value)
            self._write('.manifest.pending', manifest)
            self._check()
            os.rename('.manifest.pending', 'manifest.json',
                      src_dir_fd=self._directory_fd, dst_dir_fd=self._directory_fd)
            os.fsync(self._directory_fd)
            os.fsync(self._parent_fd)
            self._check()
            # Reopen every published name: a retained fd alone cannot prove
            # that the directory still names the bytes recorded in the manifest.
            for name, expected in (*payloads.items(), ('manifest.json', manifest)):
                fd = self._open(name, os.O_RDONLY, directory_fd=self._directory_fd)
                info = os.fstat(fd)
                A.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                          and info.st_size == len(expected), 'EVIDENCE_PUBLISHED_READBACK')
                copied = bytearray()
                while len(copied) < len(expected):
                    part = os.pread(fd, len(expected) - len(copied), len(copied))
                    A.require(type(part) is bytes and bool(part), 'EVIDENCE_PUBLISHED_READBACK')
                    copied.extend(part)
                A.require(bytes(copied) == expected, 'EVIDENCE_PUBLISHED_READBACK')
                self._check()
            self._close_all()
            self._check()
            self.result = PersistenceResult(str(path), hashlib.sha256(manifest).hexdigest(),
                          tuple((name, row['size'], row['sha256']) for name, row in rows.items()))
            self.phase = 'COMMITTED'
            return self.result
        except BaseException as exc:
            self.failure, self.result, self.phase = exc, None, 'FAILED'
            X.NativeExecution._fail(execution, exc)
            raise
        finally:
            if self.fds:
                try:
                    self._close_all()
                except BaseException as secondary:
                    self.close_error = secondary
