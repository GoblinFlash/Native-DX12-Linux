"""Own M1 mapping lifecycle; CPU candidate, not integrated or GPU qualified.

Derived from the reviewed M1 application protocol and pinned header ABI.
No vendor implementation is copied/adapted. The private fd-table/VA exclusion
precondition is mandatory: snapshots cannot prove absence of concurrent change.
One mapping per backing object; fresh open per mapping, never dup or fallback.
"""
from dataclasses import dataclass, field
import mmap
import os

from replacement_inputs import arena as A
from rm_channel import IdentityTree
import mapping_flags
from linux_backend import MAP_FIXED


@dataclass(frozen=True)
class Backing:
    owner: object
    memory: int
    memory_class: int
    size: int
    location: object = None


@dataclass(frozen=True)
class MapSpec:
    mapping_id: str
    profile: str
    base: int
    length: int


@dataclass(frozen=True)
class Binding:
    mapping_id: str
    cpu_base: int
    length: int
    rm_address: int
    fd: int
    profile: str


@dataclass
class _Record:
    spec: MapSpec
    backing: Backing
    owners: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    fd: object = None
    fingerprint: object = None
    rm_address: object = None
    binding: object = None
    rm_live: bool = False
    vma_live: bool = False
    vma_removed: bool = False
    fd_closed: bool = False


class Mappings:
    def __init__(self, tree):
        A.require(type(tree) is IdentityTree, 'M1_TREE_TYPE')
        handles, _ = tree.identity()
        A.require(tree.backend.mm_initialized, 'M1_MM_REQUIRED')
        A.require(getattr(tree.backend, '_m1_owner', None) is None, 'M1_OWNER_EXISTS')
        A.require(all(r['state'] == 'RESERVED' and 'mapping_id' not in r
                      for r in tree.backend.ranges.values()), 'M1_LEGACY_RANGE_EXISTS')
        self.tree, self.backend, self.abi = tree, tree.backend, tree.abi
        self.owners, self.handles, self.card = tree.owners, handles, tree.card
        self.flags = mapping_flags.load()
        self.records, self.phase = {}, 'ACTIVE'
        self.backend._m1_owner = self

    def _owned(self):
        A.require(self.backend._m1_owner is self and self.owners is self.backend.owners
                  and self.owners is self.tree.owners, 'M1_OWNER_BINDING')

    def _guard(self, fn, *, cleanup=False):
        if cleanup:
            A.require(self.backend.phase == 'CLEANUP' and self.phase in ('ACTIVE', 'FAILED', 'CLEANUP'),
                      'M1_CLEANUP_PHASE')
            self.phase = 'CLEANUP'
        else:
            A.require(self.phase == 'ACTIVE' and self.backend.phase == 'ACTIVE', 'M1_CLOSED')
        try:
            self._owned()
            return fn()
        except BaseException:
            self.phase = 'TERMINAL' if cleanup else 'FAILED'
            self.backend.phase = 'TERMINAL' if cleanup else 'FAILED'
            for owner in self.owners:
                if owner.state == A.PENDING:
                    owner.state = A.UNCERTAIN
            raise

    def _contains_owner(self, owner):
        return any(x is owner for x in self.owners)

    def _validate(self, spec, backing):
        A.require(type(spec) is MapSpec and type(backing) is Backing, 'M1_SPEC_TYPE')
        ident = spec.mapping_id
        A.require(type(ident) is str and 0 < len(ident) <= 64 and
                  all(c.isascii() and (c.isalnum() or c in '-_') for c in ident), 'M1_ID')
        A.require(ident not in self.records, 'M1_ID_REUSED')
        A.require(spec.profile in ('sysmem', 'usermode'), 'M1_PROFILE')
        self.backend._span(spec.base, spec.length)
        A.require(type(backing.memory) is int and 0 < backing.memory <= 0xffffffff
                  and type(backing.memory_class) is int and type(backing.size) is int
                  and backing.size == spec.length, 'M1_BACKING_SPAN')
        o = backing.owner
        A.require(self._contains_owner(o) and o.state == A.CERTAIN and callable(o.undo), 'M1_BACKING_OWNER')
        A.require(not any(r.backing.owner is o for r in self.records.values()), 'M1_BACKING_REUSED')
        c = self.abi.const
        if spec.profile == 'sysmem':
            A.require(backing.memory_class in (c('NV01_MEMORY_SYSTEM'), c('NV01_MEMORY_LOCAL_USER'))
                      and type(backing.location) is int and backing.location == c('NVOS32_ATTR_LOCATION_PCI')
                      and o.label == 'memory' and o.returned == backing.memory, 'M1_SYSMEM_ADMISSION')
        else:
            A.require(backing.memory_class == c('TURING_USERMODE_A')
                      and backing.size == c('NVC361_NV_USERMODE__SIZE')
                      and backing.location is None and o.label == 'rm:usermode', 'M1_USERMODE_ADMISSION')
            reply = self.abi.struct('NVOS21_PARAMETERS').unpack(o.returned['envelope'])
            A.require(reply['hObjectNew'] == backing.memory and reply['hRoot'] == self.handles.client
                      and reply['hObjectParent'] == self.handles.subdevice
                      and reply['hClass'] == backing.memory_class, 'M1_USERMODE_BINDING')

    def _acquire(self, rec, role, effect, validate, undo):
        owner = A.Owner('m1:' + rec.spec.mapping_id + ':' + role, rec.spec)
        rec.owners[role] = owner
        self.owners.append(owner)
        try:
            result = effect(owner)
            validate(result)
            owner.undo = lambda: self._undo(rec, role, undo)
            owner.state = A.CERTAIN
            return result
        except A.Rejected:
            # Only a pre-effect certified refusal can remove a pending owner.
            A.require(self.owners[-1] is owner, 'M1_REJECTED_LEDGER')
            self.owners.pop()
            del rec.owners[role]
            raise
        except BaseException:
            owner.state = A.UNCERTAIN
            raise

    def _undo(self, rec, role, action):
        def run():
            owner = rec.owners[role]
            A.require(self.records.get(rec.spec.mapping_id) is rec and self.owners[-1] is owner
                      and owner.state == A.CERTAIN, 'M1_UNDO_BINDING')
            owner.state = A.UNCERTAIN
            action()
            # The shared ledger's caller pops only after this returns.
            owner.state = A.CERTAIN
        return self._guard(run, cleanup=True)

    def _fd(self, rec, *, admitting=False, closing=False):
        owner = rec.owners['fd']
        A.require(not rec.fd_closed and self._contains_owner(owner) and owner.returned == rec.fd,
                  'M1_FD_BINDING')
        A.require(owner.state == (A.UNCERTAIN if admitting or closing else A.CERTAIN), 'M1_FD_CERTAINTY')
        node = 'ctl' if rec.spec.profile == 'sysmem' else 'dev'
        try:
            A.require(self.backend._fingerprint(rec.fd, node) == rec.fingerprint, 'M1_FD_CHANGED')
        except BaseException:
            owner.state = A.UNCERTAIN
            raise
        return rec.fd

    def _ioctl(self, rec, fd, name, struct, values):
        codec = self.abi.struct(struct)
        data = codec.pack(values)
        event = {'mapping_id': rec.spec.mapping_id, 'request': name, 'fd': fd,
                 'input': bytes(data).hex()}
        rec.evidence.append(event)
        def call():
            try:
                rc = self.backend.ops.ioctl(fd, self.abi.const(name), data)
                event['rc'] = rc
                return rc
            finally:
                event['output'] = bytes(data).hex()
        rc = self.backend._effect('m1:' + name, call, fields=event,
                                  after=lambda: {'output': bytes(data).hex()})
        A.require(type(rc) is int and rc == 0, 'M1_IOCTL_RC')
        return codec.unpack(data)

    def _open_fd(self, rec):
        node = 'ctl' if rec.spec.profile == 'sysmem' else 'dev'
        spec = self.backend.nodes[node]
        A.require(self.backend.ops.resolve(spec.path).startswith('/dev/'), 'M1_NODE_PATH')
        def open_call(owner):
            def effect():
                fd = self.backend.ops.open(spec.path, os.O_RDWR | os.O_CLOEXEC)
                rec.fd = owner.returned = fd
                return fd
            return self.backend._effect('m1:open', effect, fields={'mapping_id': rec.spec.mapping_id, 'node': node})
        def validate(fd):
            others = list(self.backend.fds.values()) + [r.fd for r in self.records.values() if r is not rec and not r.fd_closed]
            A.require(type(fd) is int and 0 <= fd <= 0x7fffffff and fd not in others, 'M1_FD_RETURN')
            rec.fingerprint = self.backend._fingerprint(fd, node)
            self.backend._emit({'operation': 'm1:fd_identity', 'mapping_id': rec.spec.mapping_id,
                                'fd': fd, 'identity': rec.fingerprint})
        self._acquire(rec, 'fd', open_call, validate, lambda: self._close_fd(rec))
        if node == 'dev':
            owner = rec.owners['fd']
            owner.state = A.UNCERTAIN
            self._fd(rec, admitting=True)
            out = self._ioctl(rec, self.backend._fd('ctl'), 'IOCTL_CARD_INFO', 'nv_ioctl_card_info_t', {})
            pci = self.abi.struct('nv_pci_info_t').unpack(out['pci_info'])
            card = self.card
            expected = (card.domain, card.bus, card.slot, card.function, card.vendor,
                        card.device, card.gpu_id, card.minor)
            actual = tuple(pci[k] for k in ('domain', 'bus', 'slot', 'function', 'vendor_id', 'device_id')) + (out['gpu_id'], out['minor_number'])
            A.require(out['valid'] == 1 and actual == expected, 'M1_CARD_IDENTITY')
            A.require(rec.fingerprint[2] == os.makedev(195, card.minor)
                      == os.makedev(195, out['minor_number']), 'M1_CARD_FD_BINDING')
            ctl = self.backend._fd('ctl')
            registered = self._ioctl(rec, self._fd(rec, admitting=True), 'IOCTL_REGISTER_FD', 'nv_ioctl_register_fd_t', {'ctl_fd': ctl})
            A.require(registered['ctl_fd'] == ctl, 'M1_REGISTER_IDENTITY')
            owner.state = A.CERTAIN

    def _close_fd(self, rec):
        A.require(not rec.rm_live and not rec.vma_live and not self._contains_owner(rec.owners.get('rm'))
                  and not self._contains_owner(rec.owners.get('vma')), 'M1_FD_DEPENDENTS')
        fd = self._fd(rec, closing=True)
        self.backend._effect('m1:close', lambda: self.backend.ops.close(fd),
                             fields={'mapping_id': rec.spec.mapping_id, 'fd': fd})
        rec.fd_closed = True

    def _reservation(self, rec):
        s = rec.spec
        def reserve(owner):
            address = self.backend.reserve(s.base, s.length)
            owner.returned = address
            return address
        self._acquire(rec, 'reservation', reserve,
                      lambda a: A.require(a == s.base, 'M1_RESERVATION_ADDRESS'),
                      lambda: self._release_reservation(rec))
        self.backend.ranges[s.base]['mapping_id'] = s.mapping_id

    def _range(self, rec):
        state = self.backend.ranges.get(rec.spec.base)
        A.require(state is not None and state['length'] == rec.spec.length
                  and state.get('mapping_id') == rec.spec.mapping_id, 'M1_RANGE_BINDING')
        return state

    def _release_reservation(self, rec):
        s = rec.spec
        A.require(not rec.rm_live and not rec.vma_live and
                  ('fd' not in rec.owners or rec.fd_closed), 'M1_RESERVATION_DEPENDENTS')
        self._range(rec)
        if rec.vma_removed:
            A.require(not self.backend._snapshot(s.base, s.length), 'M1_RELEASE_NOT_EMPTY')
            self.backend._emit({'operation': 'm1:reservation_consumed', 'mapping_id': s.mapping_id})
            del self.backend.ranges[s.base]
        else:
            # A certified pre-map refusal may leave the original reservation.
            # Do not route M1 ownership through the disabled legacy release path.
            A.require(self._range(rec)['state'] == 'RESERVED', 'M1_RELEASE_STATE')
            rows = self.backend._snapshot(s.base, s.length)
            A.require(len(rows) == 1 and rows[0].start <= s.base and rows[0].end >= s.base + s.length
                      and rows[0].perms == '---p' and rows[0].inode == 0 and not rows[0].path,
                      'M1_RELEASE_RESERVATION_CHANGED')
            self.backend._effect('m1:release_reservation', lambda: self.backend.ops.munmap(s.base, s.length),
                                 fields={'mapping_id': s.mapping_id, 'base': s.base, 'length': s.length})
            A.require(not self.backend._snapshot(s.base, s.length), 'M1_RELEASE_NOT_EMPTY')
            del self.backend.ranges[s.base]

    def _map_rm(self, rec):
        s, h = rec.spec, self.handles
        fd = self._fd(rec)
        # M1 PROFILE/UNKNOWN: NVOS33/34 hDevice uses device for both profiles.
        # This is separate from USERMODE's allocation parent (subdevice).
        # Header "device or sub-device" does not qualify this live RM choice.
        params = dict(hClient=h.client, hDevice=h.device, hMemory=rec.backing.memory,
                      offset=0, length=s.length, pLinearAddress=s.base, flags=self.flags.request('map'))
        def effect(owner):
            evidence_start = len(rec.evidence)
            try:
                return self._ioctl(rec, self.backend._fd('ctl'), 'IOCTL_RM_MAP_MEMORY_FD',
                                   'nv_ioctl_nvos33_parameters_with_fd', {'params': params, 'fd': fd})
            finally:
                owner.returned = (rec.evidence[evidence_start].copy()
                                  if len(rec.evidence) > evidence_start else None)
        def validate(wrapper):
            out = self.abi.struct('NVOS33_PARAMETERS').unpack(wrapper['params'])
            A.require(out['status'] == self.abi.const('NV_OK'), 'M1_MAP_STATUS')
            A.require(wrapper['fd'] == fd and all(out[k] == params[k] for k in
                      ('hClient', 'hDevice', 'hMemory', 'offset', 'length')), 'M1_MAP_IDENTITY')
            self.flags.check_reply(s.profile, out['flags'])
            rec.rm_address, rec.rm_live = out['pLinearAddress'], True
        self._acquire(rec, 'rm', effect, validate, lambda: self._unmap_rm(rec))
        self._range(rec)['state'] = 'M1_RM_MAPPED'

    def _materialize(self, rec):
        s = rec.spec
        state = self._range(rec)
        A.require(state['state'] == 'M1_RM_MAPPED' and rec.rm_live, 'M1_MATERIALIZE_ORDER')
        def effect(owner):
            fd = self._fd(rec)
            rows = self.backend._snapshot(s.base, s.length)
            A.require(len(rows) == 1 and rows[0].start <= s.base and rows[0].end >= s.base + s.length
                      and rows[0].perms == '---p' and rows[0].inode == 0 and not rows[0].path,
                      'M1_MATERIALIZE_PRECONDITION')
            self.backend._emit({'operation': 'm1:precheck', 'mapping_id': s.mapping_id, 'maps': [r.line for r in rows]})
            def call():
                result = self.backend.ops.mmap(s.base, s.length, mmap.PROT_READ | mmap.PROT_WRITE,
                                               mmap.MAP_SHARED | MAP_FIXED, fd, 0)
                owner.returned = result
                return result
            return self.backend._effect('m1:mmap', call, fields={'mapping_id': s.mapping_id, 'fd': fd})
        def validate(addr):
            rows = self.backend._snapshot(s.base, s.length)
            A.require(addr == s.base and len(rows) == 1 and rows[0].start == s.base
                      and rows[0].end == s.base + s.length and rows[0].path == rec.fingerprint[4]
                      and rows[0].perms == 'rw-s', 'M1_VMA_IDENTITY')
            self.backend._emit({'operation': 'm1:vma_identity', 'mapping_id': s.mapping_id, 'maps': [r.line for r in rows]})
            rec.vma_live = True
        self._acquire(rec, 'vma', effect, validate, lambda: self._unmap_vma(rec))
        state['state'] = 'M1_MATERIALIZED'

    def _unmap_vma(self, rec):
        s = rec.spec
        self._fd(rec)
        A.require(rec.rm_live and rec.vma_live, 'M1_VMA_ORDER')
        rows = self.backend._snapshot(s.base, s.length)
        A.require(len(rows) == 1 and rows[0].start == s.base and rows[0].end == s.base + s.length
                  and rows[0].path == rec.fingerprint[4] and rows[0].perms == 'rw-s', 'M1_VMA_CHANGED')
        self.backend._effect('m1:munmap', lambda: self.backend.ops.munmap(s.base, s.length),
                             fields={'mapping_id': s.mapping_id, 'base': s.base, 'length': s.length})
        A.require(not self.backend._snapshot(s.base, s.length), 'M1_VMA_NOT_EMPTY')
        self.backend._emit({'operation': 'm1:vma_removed', 'mapping_id': s.mapping_id})
        rec.vma_live, rec.vma_removed = False, True

    def _unmap_rm(self, rec):
        self._fd(rec)
        s, h = rec.spec, self.handles
        A.require(rec.rm_live and not rec.vma_live and not self._contains_owner(rec.owners.get('vma')),
                  'M1_RM_DEPENDENTS')
        # If mmap never ran, its still-owned reservation is not a live driver VMA.
        values = dict(hClient=h.client, hDevice=h.device, hMemory=rec.backing.memory,
                      pLinearAddress=rec.rm_address, flags=self.flags.request('unmap'))
        out = self._ioctl(rec, self.backend._fd('ctl'), 'IOCTL_RM_UNMAP_MEMORY', 'NVOS34_PARAMETERS', values)
        A.require(out['status'] == self.abi.const('NV_OK') and all(out[k] == v for k, v in values.items()),
                  'M1_UNMAP_ACK')
        rows = self.backend._snapshot(s.base, s.length)
        if rec.vma_removed:
            A.require(not rows, 'M1_UNMAP_VMA_POST')
        else:
            A.require(len(rows) == 1 and rows[0].start <= s.base and rows[0].end >= s.base + s.length
                      and rows[0].perms == '---p' and rows[0].inode == 0 and not rows[0].path,
                      'M1_UNMAP_RESERVATION_POST')
        self.backend._emit({'operation': 'm1:rm_driver_acknowledged', 'mapping_id': s.mapping_id,
                            'maps': [r.line for r in rows]})
        rec.rm_live = False
        if not rec.vma_removed:
            self._range(rec)['state'] = 'RESERVED'

    def create(self, spec, backing):
        def run():
            self._validate(spec, backing)
            rec = _Record(spec, backing)
            self.records[spec.mapping_id] = rec
            self._reservation(rec)
            self._open_fd(rec)
            self._map_rm(rec)
            self._materialize(rec)
            rec.binding = Binding(spec.mapping_id, spec.base, spec.length, rec.rm_address, rec.fd, spec.profile)
            return rec.binding
        return self._guard(run)

    def validate_binding(self, binding):
        self._owned()
        A.require(self.phase == 'ACTIVE' and self.backend.phase == 'ACTIVE', 'M1_CLOSED')
        rec = self.records.get(getattr(binding, 'mapping_id', None))
        A.require(rec is not None and binding is rec.binding and rec.rm_live and rec.vma_live
                  and self._contains_owner(rec.backing.owner) and rec.backing.owner.state == A.CERTAIN
                  and all(self._contains_owner(o) and o.state == A.CERTAIN for o in rec.owners.values()),
                  'M1_BINDING')
        return binding
