"""Root-owned durable bootstrap identity, not host or GPU authorization.

The trusted entry supplies already admitted plan bytes. Their hash identifies
that plan; it does not authenticate the caller or grant execution authority.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import threading

import process_retention as R

_REGISTRY, _MODULE = R.REGISTRY, sys.modules[__name__]
_LIMIT = 256 * 1024


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def fingerprint(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@dataclass(frozen=True)
class IdentityReceipt:
    path: str
    sha256: str
    size: int
    nonce: str
    plan_sha256: str


class BootstrapIdentity:
    def __init__(self, directory, plan_bytes, plan_sha256):
        require(type(self) is BootstrapIdentity, 'IDENTITY_TYPE')
        _REGISTRY.checkpoint()
        a = _REGISTRY.anchors
        require(a['identity'] is None, 'IDENTITY_EXISTS')
        require(not a['owners'] and a['preparation'] is None and a['publication'] is None
                and a['schedule'] is None
                and (a['backend'] is None or (a['backend'].phase == 'NEW' and a['backend'].sequence == 0))
                and (a['words'] is None or a['words'].phase == 'NEW'), 'IDENTITY_TOO_LATE')
        require(type(plan_bytes) is bytes and 0 < len(plan_bytes) <= _LIMIT
                and type(plan_sha256) is str
                and hashlib.sha256(plan_bytes).hexdigest() == plan_sha256, 'IDENTITY_PLAN_PIN')
        self.directory = Path(directory)
        require(self.directory.is_absolute() and '..' not in self.directory.parts,
                'IDENTITY_PATH')
        self._registry, self._root = _REGISTRY, _REGISTRY.root
        self.nonce = a['nonce']
        self.thread = threading.get_ident()
        self.raw = (json.dumps({'schema': 'native-bootstrap-identity.v1',
            'nonce': self.nonce, 'plan_sha256': plan_sha256,
            'plan_bytes_hex': plan_bytes.hex()}, sort_keys=True, separators=(',', ':')) + '\n').encode()
        self._raw, self._directory = self.raw, self.directory
        self.plan_sha256 = plan_sha256
        self.phase = 'NEW'
        self.result = self._result = self.failure = self.close_error = None
        self._receipt_image = self._fingerprint = None
        self.fds = []
        self._registry.attach('identity', self)

    def _same(self):
        require(type(self) is BootstrapIdentity and threading.get_ident() == self.thread,
                'IDENTITY_THREAD')
        require(sys.modules.get(__name__) is _MODULE and sys.modules.get('process_retention') is R
                and R.REGISTRY is _REGISTRY is self._registry, 'IDENTITY_MODULE')
        self._registry._same()
        require(self._registry.root is self._root and self._registry.anchors['identity'] is self
                and self._registry.anchors['nonce'] is self.nonce
                and self.raw is self._raw and self.directory is self._directory, 'IDENTITY_BINDING')

    def _before(self):
        self._same()
        self._registry.checkpoint()
        a = self._registry.anchors
        require(not a['owners'] and (a['backend'] is None or
                (a['backend'].phase == 'NEW' and a['backend'].sequence == 0))
                and (a['words'] is None or a['words'].phase == 'NEW'), 'IDENTITY_TOO_LATE')

    def _open(self, path, flags, *, dir_fd=None):
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
        self.fds.append(fd)
        return fd

    def _close(self):
        first = None
        while self.fds:
            fd = self.fds.pop()
            try:
                os.close(fd)
            except BaseException as exc:
                if first is None:
                    first = exc
        if first is not None:
            self.close_error = first
            raise first

    def commit(self):
        require(self.phase == 'NEW', 'IDENTITY_CLOSED')
        self.phase = 'WRITING'
        try:
            self._before()
            for path in (self.directory, *self.directory.parents):
                require(not path.is_symlink(), 'IDENTITY_SYMLINK')
            parent = self._open(str(self.directory.parent), os.O_RDONLY | os.O_DIRECTORY)
            os.mkdir(self.directory.name, 0o700, dir_fd=parent)
            directory = self._open(self.directory.name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=parent)
            fd = self._open('.identity.pending', os.O_RDWR | os.O_CREAT | os.O_EXCL, dir_fd=directory)
            offset = 0
            while offset < len(self.raw):
                count = os.write(fd, self.raw[offset:])
                require(type(count) is int and 0 < count <= len(self.raw) - offset, 'IDENTITY_WRITE')
                offset += count
                self._before()
            os.fsync(fd)
            self._before()
            os.rename('.identity.pending', 'identity.json', src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
            os.fsync(parent)
            self._before()
            named = self.directory / 'identity.json'
            info = named.lstat()
            require(fingerprint(info) == fingerprint(os.fstat(fd)) and stat.S_ISREG(info.st_mode)
                    and info.st_nlink == 1 and named.read_bytes() == self.raw, 'IDENTITY_READBACK')
            self._fingerprint = fingerprint(info)
            self._close()
            self.result = IdentityReceipt(str(named), hashlib.sha256(self.raw).hexdigest(),
                len(self.raw), self.nonce, self.plan_sha256)
            self._result = self.result
            self._receipt_image = tuple(vars(self.result).items())
            self.phase = 'COMMITTED'
            self.verify()
            return self.result
        except BaseException as exc:
            self.failure, self.phase = exc, 'FAILED'
            raise
        finally:
            if self.fds:
                try:
                    self._close()
                except BaseException as exc:
                    self.close_error = exc

    def verify(self):
        self._same()
        require(self.phase == 'COMMITTED' and not self.fds and self.close_error is None
                and type(self.result) is IdentityReceipt and self.result is self._result
                and tuple(vars(self.result).items()) == self._receipt_image
                and self.result.nonce == self.nonce
                and self.result.sha256 == hashlib.sha256(self.raw).hexdigest(), 'IDENTITY_RECEIPT')
        path = self.directory / 'identity.json'
        require(fingerprint(path.lstat()) == self._fingerprint
                and path.read_bytes() == self.raw
                and fingerprint(path.lstat()) == self._fingerprint, 'IDENTITY_FILE_CHANGED')
