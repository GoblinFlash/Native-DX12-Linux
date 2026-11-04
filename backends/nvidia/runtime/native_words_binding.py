"""Original typed binding to exactly the reviewed native word library.

No construction at import, no device discovery, no runtime integration.
The caller owns each mapping and excludes changes for the entire call. Integer
checks are not mapping proof. A trusted single-threaded bootstrap must pin this
module; hostile loader state, interposition, and concurrent file/VA mutation
are outside this contract. No retry, dlclose or signal recovery is provided.
"""
import ctypes
import hashlib
import os
from pathlib import Path
import stat
import sys
import threading

LIBRARY_SHA256 = 'a60ddcb47edffda54986de9aebe3b2a16c2630a186aac43798ea4fa653d21ff4'
LIBRARY_SIZE = 13848
LIBRARY_MODE = 0o775
ABI = 0x4e44585700000001
U64 = (1 << 64) - 1
_KEEPALIVE = []


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def integer(value, maximum, reason):
    require(type(value) is int and 0 <= value <= maximum, reason)


def span(base, size, address):
    for value in (base, size, address):
        integer(value, U64, 'NATIVE_WORD_TYPE')
    require(base > 0 and size >= 4 and size <= U64 - base
            and address > 0 and address % 4 == 0 and address >= base
            and address - base <= size - 4, 'NATIVE_WORD_RANGE')


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def regular(path):
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'NATIVE_LIBRARY_SYMLINK')
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == LIBRARY_MODE
            and info.st_uid == os.geteuid() and info.st_size == LIBRARY_SIZE,
            'NATIVE_LIBRARY_METADATA')
    return info


def mapped(path, info):
    # Reject an existing loader object, including an old inode at this path.
    # Trusted /proc and exclusive loader/FD table are process prerequisites.
    device = f'{os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}'
    for line in Path('/proc/self/maps').read_text().splitlines():
        row = line.split(None, 5)
        require(len(row) >= 5, 'NATIVE_MAPS_FORMAT')
        location = row[5] if len(row) == 6 else ''
        if location.removesuffix(' (deleted)') == str(path):
            return True
        if row[3] == device and int(row[4]) == info.st_ino:
            return True
    return False


def loaded_image(path, info):
    """The loaded pathname must have the same backing inode, with an RX span."""
    device = f'{os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}'
    rows = []
    for line in Path('/proc/self/maps').read_text().splitlines():
        row = line.split(None, 5)
        require(len(row) >= 5, 'NATIVE_MAPS_FORMAT')
        if len(row) == 6 and row[5].removesuffix(' (deleted)') == str(path):
            rows.append(row)
    return bool(rows) and all(row[5] == str(path) and row[3] == device
                              and int(row[4]) == info.st_ino for row in rows) \
        and any(row[1] == 'r-xp' for row in rows)


class NativeWords:
    def __init__(self):
        self.phase = 'NEW'
        self.thread = threading.get_ident()
        self.pending = False
        self._library = None
        self._file_fd = None
        self.failure = None

    def load(self, path):
        require(self.phase == 'NEW' and threading.get_ident() == self.thread,
                'NATIVE_LOAD_CLOSED')
        self.phase = 'LOADING'
        close_attempted = False
        try:
            require(sys.platform == 'linux' and os.uname().machine == 'x86_64'
                    and sys.byteorder == 'little' and ctypes.sizeof(ctypes.c_void_p) == 8
                    and sys.implementation.name == 'cpython'
                    and sys._is_gil_enabled(), 'NATIVE_HOST')
            require(type(path) is str and path.startswith('/')
                    and all(ord(c) >= 32 and c != '\\' for c in path), 'NATIVE_LIBRARY_PATH')
            path = Path(path)
            require('..' not in path.parts and path.resolve() == path, 'NATIVE_LIBRARY_PATH')
            initial = regular(path)
            require(not mapped(path, initial), 'NATIVE_LIBRARY_PRELOAD')
            self._file_fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
            require(fingerprint(os.fstat(self._file_fd)) == fingerprint(initial), 'NATIVE_LIBRARY_IDENTITY')
            pieces, total = [], 0
            while total <= LIBRARY_SIZE:
                piece = os.read(self._file_fd, LIBRARY_SIZE + 1 - total)
                if not piece:
                    break
                pieces.append(piece)
                total += len(piece)
            raw = b''.join(pieces)
            require(total == LIBRARY_SIZE and hashlib.sha256(raw).hexdigest() == LIBRARY_SHA256,
                    'NATIVE_LIBRARY_PIN')
            require(fingerprint(os.fstat(self._file_fd)) == fingerprint(initial)
                    and fingerprint(regular(path)) == fingerprint(initial), 'NATIVE_LIBRARY_IDENTITY')
            # Absolute path and exclusive file/loader state, not a TOCTOU proof.
            # PyDLL keeps the GIL during calls; it does not replace VA exclusion.
            self._library = ctypes.PyDLL(str(path), mode=os.RTLD_LOCAL | os.RTLD_NOW)
            _KEEPALIVE.append(self._library)
            require(fingerprint(regular(path)) == fingerprint(initial), 'NATIVE_LIBRARY_IDENTITY')
            require(loaded_image(path, initial), 'NATIVE_LOADED_IMAGE')
            signatures = {
                'ndx_word_abi': ((), ctypes.c_uint64),
                'ndx_word_read32': ((ctypes.c_uint64,) * 3, ctypes.c_uint64),
                'ndx_word_write32': ((ctypes.c_uint64,) * 4, ctypes.c_uint32),
                'ndx_word_release': ((), None),
                'ndx_word_acquire': ((), None),
            }
            self._functions = {}
            for name, (args, result) in signatures.items():
                function = getattr(self._library, name)
                function.argtypes, function.restype = args, result
                self._functions[name] = function
            require(self._functions['ndx_word_abi']() == ABI, 'NATIVE_ABI')
            close_attempted = True
            os.close(self._file_fd)
            self._file_fd = None
            self.phase = 'READY'
            return self
        except BaseException as exc:
            self.phase = 'FAILED'
            self.failure = {'type': type(exc).__name__, 'message': str(exc)}
            # One close attempt for a pre-load failure. A close failure itself
            # must not cause a second close of a possibly recycled descriptor.
            if self._file_fd is not None and not close_attempted:
                fd, self._file_fd = self._file_fd, None
                try:
                    os.close(fd)
                except BaseException as close_error:
                    self._file_fd = fd
                    self.failure['close_error'] = type(close_error).__name__
            raise

    def _ready(self):
        require(self.phase == 'READY' and not self.pending
                and threading.get_ident() == self.thread, 'NATIVE_NOT_READY')

    def _call(self, name, args, result_kind):
        self._ready()
        self.pending = True
        try:
            result = self._functions[name](*args)
            if result_kind == 'word':
                require(type(result) is int and 0 <= result <= U64, 'NATIVE_READ_RESULT')
                require(result >> 32 == 0, 'NATIVE_READ_STATUS:' + str(result >> 32))
                return result
            if result_kind == 'status':
                require(type(result) is int and result == 0, 'NATIVE_WRITE_STATUS')
            else:
                require(result is None, 'NATIVE_FENCE_RESULT')
            return None
        except BaseException as exc:
            self.phase = 'FAILED'
            self.failure = {'operation': name, 'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            self.pending = False

    def read32(self, base, size, address):
        self._ready()
        span(base, size, address)
        return self._call('ndx_word_read32', (base, size, address), 'word')

    def write32(self, base, size, address, value):
        self._ready()
        span(base, size, address)
        integer(value, (1 << 32) - 1, 'NATIVE_VALUE_TYPE')
        return self._call('ndx_word_write32', (base, size, address, value), 'status')

    def release(self):
        return self._call('ndx_word_release', (), 'void')

    def acquire(self):
        return self._call('ndx_word_acquire', (), 'void')
