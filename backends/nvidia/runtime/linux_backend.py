"""Own Linux syscall transport derived from REQUIREMENTS_BACKEND and pinned ABI.

Codex author, owner solo reassignment 2026-10-30. No vendor implementation or
old allocation helper used as a template. Not a clean-room claim.

No device is opened on import/construction. LinuxOps is real syscall code; CPU
tests inject a separate model. This is not a GPU launcher or hardware approval.
The caller supplies a shared Owner list and explicitly enters cleanup only with
known safe completion. Channel/RM identity binding remains the channel layer.
Single-thread/private-address-space profile: no other thread/library may mutate
the selected VA ranges or descriptor table during the protocol. A maps snapshot
detects existing drift; it does not eliminate a concurrent MAP_FIXED TOCTOU.
Unknown u0/u1/u2/u3/u4 remain baseline assumptions, never automatic fallbacks.
"""
import ctypes
from dataclasses import dataclass
import hashlib
import mmap
import os
from pathlib import Path
import platform
import stat
import sys
import time

from replacement_inputs import arena as A

# Linux x86_64 UAPI, asm-generic/mman{,-common}.h; documented mmap(2) choices.
MAP_FIXED = 0x10
MAP_NORESERVE = 0x4000
MAP_FIXED_NOREPLACE = 0x100000
PAGE = 4096


def reject(ok, reason):
    if not ok:
        raise A.Rejected(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Node:
    path: str
    major: int
    minor: int


@dataclass(frozen=True)
class Card:
    domain: int
    bus: int
    slot: int
    function: int
    vendor: int
    device: int
    gpu_id: int
    minor: int


@dataclass(frozen=True)
class Mapping:
    start: int
    end: int
    perms: str
    offset: int
    dev: str
    inode: int
    path: str
    line: str


def parse_maps(text):
    """Parse the complete maps snapshot; never ignore malformed/overlapping rows."""
    rows = []
    for line in text.splitlines():
        fields = line.split(None, 5)
        try:
            if len(fields) < 5:
                raise ValueError()
            lo, hi = (int(x, 16) for x in fields[0].split('-'))
            perms, offset, dev, inode = fields[1:5]
            major, minor = (int(x, 16) for x in dev.split(':'))
            offset, inode = int(offset, 16), int(inode)
            valid_perms = (len(perms) == 4 and perms[0] in 'r-'
                           and perms[1] in 'w-' and perms[2] in 'x-' and perms[3] in 'sp')
            if not (0 <= lo < hi <= 1 << 64 and valid_perms and min(offset, inode, major, minor) >= 0):
                raise ValueError()
            if rows and rows[-1].end > lo:
                raise ValueError()
        except (ValueError, TypeError):
            raise A.Stop('MAPS_FORMAT', line=line) from None
        rows.append(Mapping(lo, hi, perms, offset, dev, inode,
                            fields[5] if len(fields) == 6 else '', line))
    return rows


class LinuxOps:
    """Thin syscall ABI, no retry, hidden fallback or NVIDIA policy.

    ctypes libc ioctl avoids fcntl's small-buffer handling and implicit retry.
    Python os.open/read may restart EINTR; acquisition/teardown below use libc
    open/close/mmap/munmap/ioctl once. Read-only proc metadata uses Python APIs.
    """
    def __init__(self):
        A.require(sys.platform == 'linux' and platform.machine() == 'x86_64'
                  and sys.byteorder == 'little' and ctypes.sizeof(ctypes.c_void_p) == 8
                  and os.sysconf('SC_PAGE_SIZE') == PAGE, 'LINUX_HOST_ABI')
        self.lib = ctypes.CDLL(None, use_errno=True)
        signatures = {
            'open': (ctypes.c_int, [ctypes.c_char_p, ctypes.c_int]),
            'close': (ctypes.c_int, [ctypes.c_int]),
            'ioctl': (ctypes.c_int, [ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p]),
            'mmap': (ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_long]),
            'munmap': (ctypes.c_int, [ctypes.c_void_p, ctypes.c_size_t]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(self.lib, name)
            fn.restype, fn.argtypes = result, args

    @staticmethod
    def result(rc, failure=-1):
        if rc == failure:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
        return rc

    def open(self, path, flags):
        return self.result(self.lib.open(os.fsencode(path), flags))

    def close(self, fd):
        self.result(self.lib.close(fd))

    def ioctl(self, fd, request, data):
        buf = (ctypes.c_ubyte * len(data)).from_buffer(data)
        return self.result(self.lib.ioctl(fd, request, ctypes.addressof(buf)))

    def mmap(self, base, length, prot, flags, fd, offset):
        addr = self.lib.mmap(base, length, prot, flags, fd, offset)
        return self.result(addr, ctypes.c_void_p(-1).value)

    def munmap(self, base, length):
        self.result(self.lib.munmap(base, length))

    def fstat(self, fd):
        return os.fstat(fd)

    def fd_path(self, fd):
        return os.readlink('/proc/self/fd/' + str(fd))

    def resolve(self, path):
        return str(Path(path).resolve(strict=True))

    def maps(self):
        return Path('/proc/self/maps').read_text()


# Request schemas are header names, not implementation-derived request bytes.
RM_REQUESTS = {
    'IOCTL_CARD_INFO': ('ctl', 'nv_ioctl_card_info_t', None),
    'IOCTL_REGISTER_FD': ('dev', 'nv_ioctl_register_fd_t', None),
    'IOCTL_RM_ALLOC_NVOS21': ('ctl', 'NVOS21_PARAMETERS', 'status'),
    'IOCTL_RM_CONTROL': ('ctl', 'NVOS54_PARAMETERS', 'status'),
    'IOCTL_RM_FREE': ('ctl', 'NVOS00_PARAMETERS', 'status'),
    'IOCTL_RM_MAP_MEMORY_FD': ('ctl', 'nv_ioctl_nvos33_parameters_with_fd', 'params.status'),
    'IOCTL_RM_UNMAP_MEMORY': ('ctl', 'NVOS34_PARAMETERS', 'status'),
}
UVM_REQUESTS = ('INITIALIZE', 'MM_INITIALIZE', 'REGISTER_GPU', 'UNREGISTER_GPU',
                'REGISTER_GPU_VASPACE', 'UNREGISTER_GPU_VASPACE', 'CREATE_EXTERNAL_RANGE',
                'FREE', 'MAP_EXTERNAL_ALLOCATION', 'REGISTER_CHANNEL', 'UNREGISTER_CHANNEL')
CLEANUP_REQUESTS = frozenset({'IOCTL_RM_FREE', 'IOCTL_RM_UNMAP_MEMORY', 'UVM_FREE',
                              'UVM_UNREGISTER_GPU', 'UVM_UNREGISTER_GPU_VASPACE',
                              'UVM_UNREGISTER_CHANNEL'})


class LinuxBackend(A.Backend):
    def __init__(self, abi, nodes, ops, owners, record, *, mapping_node='dev'):
        # Pure configuration, including recorder: caller owns persistence/custody.
        reject(type(nodes) is dict and set(nodes) == {'ctl', 'dev', 'uvm'}, 'NODE_SET')
        for node in nodes.values():
            reject(type(node) is Node and type(node.path) is str and node.path.startswith('/dev/')
                   and '..' not in Path(node.path).parts and '\x00' not in node.path
                   and type(node.major) is int and type(node.minor) is int
                   and node.major >= 0 and node.minor >= 0, 'NODE_SPEC')
        reject(mapping_node in ('dev', 'ctl'), 'MAPPING_NODE')
        reject(type(owners) is list and not owners and callable(record), 'BACKEND_BINDING')
        self.abi, self.nodes, self.ops = abi, dict(nodes), ops
        self.owners, self.record, self.mapping_node = owners, record, mapping_node
        self.phase, self.fds, self.ranges = 'NEW', {}, {}
        self.fd_owners, self.fd_identity = {}, {}
        self.uvm_initialized, self.mm_initialized, self.card_verified = False, False, False
        self.pending, self.failure, self.last_event = False, None, None
        self.sequence = 0
        self.table = {}
        for name, (node, struct, status) in RM_REQUESTS.items():
            self.table[abi.const(name)] = (name, node, abi.struct(struct), status)
        for suffix in UVM_REQUESTS:
            name = 'UVM_' + suffix
            self.table[abi.const(name)] = (name, 'uvm_mm' if suffix == 'MM_INITIALIZE' else 'uvm',
                                          abi.struct(name + '_PARAMS'), 'rmStatus')

    def _emit(self, event):
        event = dict(event, sequence=self.sequence, monotonic_ns=time.monotonic_ns())
        self.sequence += 1
        self.last_event = event
        # A recorder failure after a syscall is not a certified refusal.
        self.record(event)

    def _effect(self, name, fn, *, fields=None, after=None):
        self.pending = True
        event = dict(fields or {}, operation=name)
        try:
            result = fn()
            event['return'] = result
            event['errno'] = 0
            if after is not None:
                event.update(after())
            self._emit(event)
            return result
        except BaseException as exc:
            self.failure = {'operation': name, 'error': type(exc).__name__, 'errno': getattr(exc, 'errno', None)}
            self.phase = 'TERMINAL' if self.phase == 'CLEANUP' else 'FAILED'
            # ioctl may have changed output bytes before returning an errno.
            if after is not None:
                try:
                    event.update(after())
                except BaseException as secondary:
                    event['output_inspection_error'] = type(secondary).__name__
            try:
                self._emit(dict(event, failure=self.failure))
            except BaseException:
                pass  # last_event retains the attempted diagnostic in memory.
            # An injected primitive must not certify a refusal after invocation.
            if isinstance(exc, A.Rejected):
                raise A.Stop('PRIMITIVE_CONTRACT', operation=name) from exc
            raise
        finally:
            self.pending = False

    def _active(self):
        reject(self.phase == 'ACTIVE', 'BACKEND_PHASE:' + self.phase)

    def _owner(self, label, requested):
        o = A.Owner(label, requested)
        self.owners.append(o)
        return o

    def _fingerprint(self, fd, node):
        s = self.ops.fstat(fd)
        path = self.ops.fd_path(fd)
        expected = self.nodes['uvm' if node == 'uvm_mm' else node]
        resolved = self.ops.resolve(expected.path)
        A.require(stat.S_ISCHR(s.st_mode) and os.major(s.st_rdev) == expected.major
                  and os.minor(s.st_rdev) == expected.minor and resolved.startswith('/dev/')
                  and path == resolved, 'FD_IDENTITY', node=node, target=path)
        return (s.st_dev, s.st_ino, s.st_rdev, s.st_mode, path)

    def _fd(self, node):
        reject(node in self.fds, 'NODE_CLOSED')
        fd = self.fds[node]
        try:
            A.require(self._fingerprint(fd, node) == self.fd_identity[node], 'FD_CHANGED', node=node)
        except BaseException:
            self.fd_owners[node].state = A.UNCERTAIN
            self.phase = 'TERMINAL' if self.phase == 'CLEANUP' else 'FAILED'
            raise
        return fd

    def _open(self, node):
        spec = self.nodes['uvm' if node == 'uvm_mm' else node]
        reject(node not in self.fds, 'DUPLICATE_FD')
        resolved = self.ops.resolve(spec.path)
        reject(resolved.startswith('/dev/'), 'NODE_OUTSIDE_DEV')
        o = self._owner('fd:' + node, spec.path)
        self.fd_owners[node] = o
        def acquire():
            fd = self.ops.open(spec.path, os.O_RDWR | os.O_CLOEXEC)
            o.returned = fd  # Retain known return even if the recorder subsequently fails.
            return fd
        try:
            fd = self._effect('open', acquire,
                              fields={'node': node, 'path': spec.path})
            o.returned = fd
            A.require(type(fd) is int and 0 <= fd <= 0x7fffffff and fd not in self.fds.values(), 'FD_RETURN')
            self.fds[node] = fd
            ident = self._fingerprint(fd, node)
            self.fd_identity[node] = ident
            self._emit({'operation': 'fd_identity', 'node': node, 'identity': ident})
            o.state, o.undo = A.CERTAIN, lambda: self._close(node, o)
        except BaseException:
            o.state = A.UNCERTAIN
            self.phase = 'FAILED'
            raise

    def open_nodes(self):
        reject(self.phase == 'NEW', 'BACKEND_PHASE:' + self.phase)
        try:
            # Validate all paths before opening the first descriptor.
            for spec in self.nodes.values():
                reject(self.ops.resolve(spec.path).startswith('/dev/'), 'NODE_OUTSIDE_DEV')
            self.phase = 'ACTIVE'
            for node in ('ctl', 'dev', 'uvm'):
                self._open(node)
        except BaseException:
            # Metadata can fail between acquisitions, outside _open's syscall
            # guard. Retain certain earlier owners; permit only safe cleanup.
            self.phase = 'FAILED'
            raise

    def _close(self, node, owner):
        A.require(self.phase == 'CLEANUP' and self.owners and self.owners[-1] is owner,
                  'FD_DEPENDENTS', node=node)
        A.require(not self.ranges, 'FD_LIVE_RANGES', node=node)
        fd = self._fd(node)
        try:
            self._effect('close', lambda: self.ops.close(fd), fields={'node': node, 'fd': fd})
        except BaseException:
            owner.state = A.UNCERTAIN
            raise
        del self.fds[node]

    def begin_teardown(self, safe_state):
        A.require(safe_state is True and not self.pending, 'BACKEND_TEARDOWN_UNSAFE')
        A.require(self.phase in ('ACTIVE', 'FAILED'), 'BACKEND_TEARDOWN_CLOSED')
        self.phase = 'CLEANUP'

    def close_fds(self):
        """Only after dependent owners have been removed by their own teardown."""
        A.require(self.phase == 'CLEANUP', 'BACKEND_TEARDOWN_CLOSED')
        try:
            while self.owners:
                o = self.owners[-1]
                A.require(any(o is x for x in self.fd_owners.values()), 'FD_DEPENDENTS')
                A.require(o.state == A.CERTAIN, 'FD_UNCERTAIN')
                o.undo()
                self.owners.pop()
            A.require(not self.fds, 'FD_LEDGER')
            self.phase = 'CLOSED'
        except BaseException:
            self.phase = 'TERMINAL'
            raise

    def device_fd(self):
        self._active()
        return self._fd(self.mapping_node)

    def _snapshot(self, base, length):
        return [x for x in parse_maps(self.ops.maps()) if x.start < base + length and base < x.end]

    @staticmethod
    def _span(base, length):
        reject(type(base) is int and type(length) is int and base > 0 and length > 0
               and base % PAGE == 0 and length % PAGE == 0
               and base + length <= 1 << 47, 'MAP_ARGUMENTS')

    def reserve(self, base, length):
        self._active()
        self._span(base, length)
        reject(all(base + length <= a or a + v['length'] <= base
                   for a, v in self.ranges.items()), 'MAP_OVERLAP')
        state = {'length': length, 'state': 'UNCERTAIN'}
        self.ranges[base] = state
        def check():
            rows = self._snapshot(base, length)
            A.require(len(rows) == 1 and rows[0].start <= base and rows[0].end >= base + length
                      and rows[0].perms == '---p' and rows[0].inode == 0 and not rows[0].path,
                      'RESERVATION_MAPS')
            return {'maps': [x.line for x in rows]}
        addr = self._effect('reserve', lambda: self.ops.mmap(base, length, 0,
                            mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS | MAP_FIXED_NOREPLACE | MAP_NORESERVE, -1, 0),
                            fields={'base': base, 'length': length}, after=check)
        if addr != base:
            self.phase = 'FAILED'
            raise A.Stop('RESERVE_ADDRESS', returned=addr)
        state['state'] = 'RESERVED'
        return addr

    def materialize(self, base, length):
        reject(getattr(self, '_m1_owner', None) is None, 'M1_LEGACY_MAPPING_DISABLED')
        self._active()
        self._span(base, length)
        state = self.ranges.get(base)
        reject(state is not None and state['length'] == length and state['state'] == 'RM_MAPPED', 'MATERIALIZE_ORDER')
        fd = self._fd(self.mapping_node)
        # SUPPORT-F1: validate before destructive MAP_FIXED, not just afterwards.
        # The selected baseline expects RM to leave our PROT_NONE reservation for
        # materialization. A driver that already materialized it needs a distinct
        # reviewed handshake; do not accept an anonymous or device-looking impostor.
        try:
            rows = self._snapshot(base, length)
            A.require(len(rows) == 1 and rows[0].start <= base and rows[0].end >= base + length
                      and rows[0].perms == '---p' and rows[0].inode == 0 and not rows[0].path,
                      'MATERIALIZE_PRECONDITION')
            self._emit({'operation': 'materialize_precheck', 'base': base, 'length': length,
                        'maps': [x.line for x in rows]})
        except BaseException:
            state['state'], self.phase = 'UNCERTAIN', 'FAILED'
            raise
        state['state'] = 'UNCERTAIN'
        def check():
            rows = self._snapshot(base, length)
            expected = self.fd_identity[self.mapping_node][4]
            A.require(len(rows) == 1 and rows[0].start == base and rows[0].end == base + length
                      and rows[0].path == expected and rows[0].perms == 'rw-s', 'MATERIALIZE_MAPS')
            return {'maps': [x.line for x in rows]}
        addr = self._effect('materialize', lambda: self.ops.mmap(base, length, mmap.PROT_READ | mmap.PROT_WRITE,
                            mmap.MAP_SHARED | MAP_FIXED, fd, 0), fields={'base': base, 'length': length}, after=check)
        if addr != base:
            self.phase = 'FAILED'
            raise A.Stop('MATERIALIZE_ADDRESS', returned=addr)
        state['state'] = 'MATERIALIZED'
        return addr

    def release(self, base, length):
        reject(self.phase == 'CLEANUP', 'BACKEND_PHASE:' + self.phase)
        state = self.ranges.get(base)
        reject(state is not None and state['length'] == length, 'RELEASE_RANGE')
        # M1 consumes its own reservations. Unmapped channel reservations still
        # use this path; a mapping ID must never enter the legacy RM release path.
        reject('mapping_id' not in state, 'M1_LEGACY_MAPPING_DISABLED')
        if state['state'] == 'RELEASED_BY_RM':
            # Do not inspect/reclaim a new mapping now occupying this address.
            self._emit({'operation': 'release_noop', 'base': base, 'length': length})
            del self.ranges[base]
            return
        reject(state['state'] == 'RESERVED', 'RELEASE_STATE')
        rows = self._snapshot(base, length)
        A.require(len(rows) == 1 and rows[0].start <= base and rows[0].end >= base + length
                  and rows[0].perms == '---p' and rows[0].inode == 0 and not rows[0].path, 'RELEASE_MAPS_CHANGED')
        state['state'] = 'UNCERTAIN'
        def check():
            A.require(not self._snapshot(base, length), 'RELEASE_NOT_EMPTY')
            return {}
        self._effect('munmap', lambda: self.ops.munmap(base, length), fields={'base': base, 'length': length}, after=check)
        del self.ranges[base]

    def ioctl(self, node, request, data, indirect=None):
        reject(type(request) is int and request in self.table, 'IOCTL_REQUEST')
        name, expected_node, codec, status_field = self.table[request]
        if name in ('IOCTL_RM_MAP_MEMORY_FD', 'IOCTL_RM_UNMAP_MEMORY'):
            reject(getattr(self, '_m1_owner', None) is None, 'M1_LEGACY_MAPPING_DISABLED')
        reject(node == expected_node and type(data) is bytearray and len(data) == codec.size, 'IOCTL_SCHEMA')
        reject(self.phase == ('CLEANUP' if name in CLEANUP_REQUESTS else 'ACTIVE'), 'IOCTL_PHASE')
        if name.startswith('IOCTL_'):
            reject(codec.size < 16384 and ((request >> 16) & 0x3fff) == codec.size, 'IOCTL_SIZE')
        fd = self._fd(node)
        values = codec.unpack(data)
        aux_ref = None
        if name in ('IOCTL_RM_ALLOC_NVOS21', 'IOCTL_RM_CONTROL'):
            pointer = 'pAllocParms' if name == 'IOCTL_RM_ALLOC_NVOS21' else 'params'
            off = codec.fields[pointer][0]
            size = values['paramsSize']
            if size:
                reject(type(indirect) is tuple and len(indirect) == 2 and indirect[0] == off
                       and type(indirect[1]) is bytearray and len(indirect[1]) == size and size < 16384,
                       'IOCTL_INDIRECT')
                aux_ref = (ctypes.c_ubyte * size).from_buffer(indirect[1])
            else:
                reject(indirect is None and values[pointer] == 0, 'IOCTL_INDIRECT')
        else:
            reject(indirect is None, 'IOCTL_INDIRECT')
        if 'rmCtrlFd' in values:
            reject(values['rmCtrlFd'] == self._fd('ctl'), 'IOCTL_FOREIGN_FD')
        if name == 'IOCTL_REGISTER_FD':
            reject(values['ctl_fd'] == self._fd('ctl'), 'IOCTL_FOREIGN_FD')
        if name.startswith('UVM_'):
            if name == 'UVM_INITIALIZE':
                reject(not self.uvm_initialized, 'UVM_INIT_DUPLICATE')
            elif name == 'UVM_MM_INITIALIZE':
                reject(self.uvm_initialized and not self.mm_initialized
                       and values['uvmFd'] == self._fd('uvm'), 'UVM_MM_ORDER')
            else:
                reject(self.mm_initialized, 'UVM_MM_REQUIRED')
        if name == 'IOCTL_RM_ALLOC_NVOS21':
            reject(self.card_verified, 'CARD_INFO_REQUIRED')
        state, address = None, None
        if name == 'IOCTL_RM_MAP_MEMORY_FD':
            inner = self.abi.struct('NVOS33_PARAMETERS').unpack(values['params'])
            address = inner['pLinearAddress']
            state = self.ranges.get(address)
            reject(values['fd'] == self._fd(self.mapping_node), 'IOCTL_FOREIGN_FD')
            reject(state is not None and state['state'] == 'RESERVED' and inner['length'] == state['length']
                   and inner['flags'] & (1 << self.abi.const('NVOS33_FLAGS_MAP_FIXED_SHIFT')), 'RM_MAP_RANGE')
        if name == 'IOCTL_RM_UNMAP_MEMORY':
            address = values['pLinearAddress']
            state = self.ranges.get(address)
            reject(state is not None and state['state'] in ('RM_MAPPED', 'MATERIALIZED')
                   and values['flags'] == 0, 'RM_UNMAP_RANGE')
            reject(tuple(values[k] for k in ('hClient', 'hDevice', 'hMemory')) == state['rm_identity'],
                   'RM_UNMAP_OBJECT')
        if aux_ref is not None:
            data[off:off + 8] = ctypes.addressof(aux_ref).to_bytes(8, 'little')
        sent = sha(data)
        sent_aux = sha(indirect[1]) if indirect else None
        if state is not None:
            state['state'] = 'UNCERTAIN'
        def observed():
            out = codec.unpack(data)
            status = None
            if status_field == 'params.status':
                status = self.abi.struct('NVOS33_PARAMETERS').unpack(out['params'])['status']
            elif status_field:
                status = out[status_field]
            return {'received_sha256': sha(data), 'aux_received_sha256': sha(indirect[1]) if indirect else None,
                    'status': status}
        rc = self._effect(name, lambda: self.ops.ioctl(fd, request, data),
                          fields={'node': node, 'request': request, 'sent_sha256': sent, 'aux_sent_sha256': sent_aux},
                          after=observed)
        out = codec.unpack(data)
        status = observed()['status']
        accepted = {self.abi.const('NV_OK')}
        if name == 'UVM_MM_INITIALIZE':
            accepted.add(self.abi.const('NV_WARN_NOTHING_TO_DO'))
        if rc != 0 or (status is not None and status not in accepted):
            self.phase = 'TERMINAL' if self.phase == 'CLEANUP' else 'FAILED'
            return rc  # Leave both result fields intact for the owner layer.
        try:
            if name == 'UVM_INITIALIZE':
                self.uvm_initialized = True
            if name == 'UVM_MM_INITIALIZE':
                self.mm_initialized = True
            if name == 'IOCTL_RM_MAP_MEMORY_FD':
                inner = self.abi.struct('NVOS33_PARAMETERS').unpack(out['params'])
                requested_inner = self.abi.struct('NVOS33_PARAMETERS').unpack(values['params'])
                A.require(out['fd'] == values['fd'] and all(inner[k] == requested_inner[k]
                          for k in ('hClient', 'hDevice', 'hMemory', 'offset', 'flags')), 'RM_MAP_IDENTITY')
                A.require((inner['pLinearAddress'], inner['length']) == (address, state['length']), 'RM_MAP_IDENTITY')
                state['rm_identity'] = tuple(inner[k] for k in ('hClient', 'hDevice', 'hMemory'))
                state['state'] = 'RM_MAPPED'
            if name == 'IOCTL_RM_UNMAP_MEMORY':
                A.require(out['pLinearAddress'] == address, 'RM_UNMAP_IDENTITY')
                rows = self._snapshot(address, state['length'])
                self._emit({'operation': 'rm_unmap_maps', 'base': address, 'maps': [x.line for x in rows]})
                A.require(not rows, 'RM_UNMAP_NOT_EMPTY')
                state['state'] = 'RELEASED_BY_RM'
        except BaseException:
            self.phase = 'TERMINAL' if self.phase == 'CLEANUP' else 'FAILED'
            raise
        return rc

    def verify_card(self, expected):
        self._active()
        reject(type(expected) is Card and not self.card_verified, 'CARD_PLAN')
        reject(expected.vendor == 0x10de and expected.device == 0x2684, 'CARD_GPU_PROFILE')
        codec = self.abi.struct('nv_ioctl_card_info_t')
        data = codec.pack({})
        rc = self.ioctl('ctl', self.abi.const('IOCTL_CARD_INFO'), data)
        out = codec.unpack(data)
        pci = self.abi.struct('nv_pci_info_t').unpack(out['pci_info'])
        actual = Card(pci['domain'], pci['bus'], pci['slot'], pci['function'], pci['vendor_id'],
                      pci['device_id'], out['gpu_id'], out['minor_number'])
        if rc != 0 or out['valid'] != 1 or actual != expected:
            self.phase = 'FAILED'
            raise A.Stop('IDENTITY_MISMATCH', expected=expected, actual=actual)
        self._fd('dev')
        if self.fd_identity['dev'][2] != os.makedev(195, actual.minor):
            self.phase = 'FAILED'
            raise A.Stop('CARD_DEVICE_BINDING')
        self.card_verified = True
        return actual

    def register_device(self):
        data = self.abi.struct('nv_ioctl_register_fd_t').pack({'ctl_fd': self._fd('ctl')})
        rc = self.ioctl('dev', self.abi.const('IOCTL_REGISTER_FD'), data)
        A.require(rc == 0, 'REGISTER_FD_RC', rc=rc)

    def initialize_mm(self):
        """After primary initialize and before any dependent UVM effect."""
        self._active()
        reject(self.uvm_initialized and not self.mm_initialized, 'UVM_MM_ORDER')
        self._open('uvm_mm')
        owner = self.fd_owners['uvm_mm']
        # MM_INITIALIZE can have unknown effects; retain both fds on any failure.
        owner.state = A.UNCERTAIN
        codec = self.abi.struct('UVM_MM_INITIALIZE_PARAMS')
        data = codec.pack({'uvmFd': self._fd('uvm')})
        rc = self.ioctl('uvm_mm', self.abi.const('UVM_MM_INITIALIZE'), data)
        status = codec.unpack(data)['rmStatus']
        A.require(rc == 0 and status in (self.abi.const('NV_OK'), self.abi.const('NV_WARN_NOTHING_TO_DO')),
                  'UVM_MM_STATUS', rc=rc, status=status)
        owner.state = A.CERTAIN
        if status == self.abi.const('NV_WARN_NOTHING_TO_DO'):
            # No MM context. Close only this top owner; this is not general cleanup.
            self.phase = 'CLEANUP'
            self._close('uvm_mm', owner)
            self.owners.pop()
            self.phase = 'ACTIVE'
        return status
