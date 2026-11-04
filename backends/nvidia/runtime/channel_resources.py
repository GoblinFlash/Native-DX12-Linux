"""Own composition of IdentityTree and the reviewed team's arena allocator.

Sources: REQUIREMENTS_A/BACKEND/CHANNEL and the imported replacement modules.
No old allocation helper or vendor implementation is used. This component has
no uploader, TSG, channel, scheduling or publication path. Native acceptance of
the mapping profile remains unqualified; tests use injected syscall primitives.
"""
from dataclasses import dataclass
from replacement_inputs import arena as A
from rm_channel import IdentityTree
from mapping_protocol import Backing, MapSpec, Mappings


@dataclass(frozen=True)
class ArenaConfig:
    base: int
    size: int
    budget: int
    memory_class: int
    layout_bytes: int

    def validate(self, abi):
        A.require(all(type(x) is int for x in vars(self).values()), 'RESOURCE_CONFIG_TYPE')
        A.require(self.base > 0 and self.base % A.PAGE == 0 and self.size > 0
                  and self.size % A.PAGE == 0 and self.base + self.size <= 1 << 40,
                  'RESOURCE_CONFIG_SPAN')
        A.require(self.size <= self.budget <= 64 * A.MIB and 0 <= self.layout_bytes <= self.size,
                  'RESOURCE_CONFIG_BUDGET')
        A.require(self.memory_class in (abi.const('NV01_MEMORY_SYSTEM'), abi.const('NV01_MEMORY_LOCAL_USER')),
                  'RESOURCE_CONFIG_CLASS')


@dataclass(frozen=True)
class ArenaBinding:
    client: int
    device: int
    subdevice: int
    vaspace: int
    memory: int
    gpu_uuid: bytes
    cpu_base: int
    gpu_base: int
    size: int


class ArenaSession:
    """Exclusive one-attempt owner of a fresh IdentityTree and its backend.

No caller may use the tree/backend/allocator separately during this session.
The same-process claim detects accidental double wrappers, not hostile code.
Safe teardown must come from the enclosing process protocol; no destructor or
context manager silently releases resources. Unknown effects retain parents.
"""
    def __init__(self, tree, config):
        A.require(type(tree) is IdentityTree and tree.phase == 'NEW', 'RESOURCE_TREE_FRESH')
        A.require(type(config) is ArenaConfig, 'RESOURCE_CONFIG_TYPE')
        config.validate(tree.abi)
        A.require(getattr(tree, '_resource_session', None) is None, 'RESOURCE_OWNER_EXISTS')
        self._tree, self._arena, self.config = tree, None, config
        self._mappings, self._cpu_mapping = None, None
        self.phase, self.failure, self._binding = 'NEW', None, None
        tree._resource_session = self

    def _owned(self):
        tree = self._tree
        A.require(tree._resource_session is self and tree.owners is tree.backend.owners,
                  'RESOURCE_OWNER_BINDING')
        if self._arena is not None:
            A.require(self._arena.owners is tree.owners, 'RESOURCE_ARENA_LEDGER')
        if self._mappings is not None:
            self._mappings._owned()

    def _map_arena(self, handles):
        arena, cfg, tree = self._arena, self.config, self._tree
        size = arena.observed['arena_size']
        A.require(cfg.base + size <= 1 << 40, 'RESOURCE_RETURNED_SPAN')
        # Keep the containment check that used to be inside Arena.place().
        A.contains(cfg.base, size, arena.observed['va_base'], arena.observed['va_size'])
        owner = tree.owners[-1]
        A.require(owner.label == 'memory' and owner.state == A.CERTAIN
                  and owner.returned == handles.memory, 'RESOURCE_MEMORY_OWNER')
        location = A.field_value(arena.observed['attr'], tree.abi.const('NVOS32_ATTR_LOCATION_SHIFT'),
                                 tree.abi.const('NVOS32_ATTR_LOCATION_MASK'))
        self._mappings = Mappings(tree)
        backing = Backing(owner, owner.returned, cfg.memory_class, size, location)
        self._cpu_mapping = self._mappings.create(MapSpec('arena', 'sysmem', cfg.base, size), backing)
        binding = self._mappings.validate_binding(self._cpu_mapping)
        A.require((binding.cpu_base, binding.length) == (cfg.base, size), 'RESOURCE_MAPPING_BINDING')
        arena.observed['cpu_base'] = binding.cpu_base

    def open_arena(self):
        A.require(self.phase == 'NEW', 'RESOURCE_CLOSED')
        self.phase = 'ACQUIRING'
        try:
            self._owned()
            tree, cfg = self._tree, self.config
            handles, instances = tree.acquire()
            # IdentityTree has completed primary initialize and MM initialize.
            # Arena.build() would initialize UVM a second time, so use only the
            # remaining UVM/allocation steps; M1 explicitly replaces place/map_cpu.
            A.require(tree.identity() == (handles, instances), 'RESOURCE_IDENTITY')
            request = A.ArenaRequest(
                h_client=handles.client, h_device=handles.device, h_subdevice=handles.subdevice,
                gpu_uuid=tree.uuid, rm_ctrl_fd=tree.backend.fds['ctl'],
                memory_class=cfg.memory_class, size=cfg.size, base=cfg.base,
                h_vas=handles.vas, h_memory=handles.memory,
                budget=cfg.budget, layout_bytes=cfg.layout_bytes)
            arena = A.Arena(request, tree.backend, tree.abi)
            # Replace the allocator's default empty ledger before its first
            # effect. Do not concatenate lists after acquisition.
            arena.owners = tree.owners
            self._arena = arena
            self._owned()
            for operation in (arena.uvm_register_gpu, arena.create_vaspace, arena.uvm_register_vaspace,
                              arena.allocate):
                self._owned()
                operation()
                if operation == arena.allocate:
                    A.require(cfg.base + arena.observed['arena_size'] <= 1 << 40, 'RESOURCE_RETURNED_SPAN')
            self._map_arena(handles)
            for operation in (arena.external_range, arena.map_gpu):
                self._owned()
                operation()
            size = arena.observed['arena_size']
            # A larger returned allocation is the actual mapped range; the
            # channel's low-VA profile applies to its end as well as its base.
            A.require(cfg.base + size <= 1 << 40, 'RESOURCE_RETURNED_SPAN')
            self._binding = ArenaBinding(handles.client, handles.device, handles.subdevice,
                                         handles.vas, handles.memory, tree.uuid,
                                         arena.observed['cpu_base'], arena.observed['gpu_base'], size)
            self.phase = 'ARENA_READY'
            return self.binding()
        except BaseException as exc:
            self.phase = 'FAILED'
            self.failure = {'type': type(exc).__name__, 'reason': str(exc)}
            # Includes KeyboardInterrupt/SystemExit, beyond Arena._run's
            # Exception handler. Every pending acquisition becomes uncertain.
            self._tree._failed(exc)
            if self._arena is not None:
                self._arena._fail('RESOURCE_FAILED', self.failure)
            raise

    def binding(self):
        A.require(self.phase == 'ARENA_READY', 'RESOURCE_BINDING_UNAVAILABLE')
        self._owned()
        A.require(self._tree.backend.phase == 'ACTIVE' and self._arena.phase == A.OPEN
                  and all(o.state == A.CERTAIN for o in self._tree.owners), 'RESOURCE_NOT_READY')
        self._mappings.validate_binding(self._cpu_mapping)
        return self._binding

    def teardown(self, safe_state):
        A.require(safe_state is True, 'RESOURCE_TEARDOWN_UNSAFE')
        A.require(self.phase in ('FAILED', 'ARENA_READY'), 'RESOURCE_CLOSED')
        self.phase = 'CLOSING'
        try:
            self._owned()
            # One traversal covers UVM, M1 VMA/RM/dedicated fd and backing owners.
            # M1 consumes replaced reservations without a second munmap.
            self._tree.teardown(True)
            if self._arena is not None:
                self._arena.phase = A.TORN
            self.phase = 'CLOSED'
        except BaseException:
            self.phase = 'TERMINAL'
            if self._arena is not None:
                self._arena.phase = A.TERMINAL
            raise
