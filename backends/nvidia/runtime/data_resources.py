"""Four original data-resource wrappers in the reviewed shared VA/M1 lifecycle.

No historical allocator template; no upload, shader descriptor, scheduling or
publication API. Live PROFILE acceptance is untested. No automatic cleanup.
"""
import copy
from dataclasses import dataclass
import threading

from channel_objects import ChannelObjects, disjoint
from mapping_protocol import Backing, MapSpec
from replacement_inputs import arena as A
from sort_data_layout import DataLayout, ROLES, TOTAL_LIMIT
import affine_data as AD


@dataclass(frozen=True)
class DataSlot:
    role: str
    memory: int
    base: int
    maximum_size: int


@dataclass(frozen=True)
class DataBinding:
    role: str
    memory: int
    owner: object
    allocator: object
    mapping: object
    cpu_base: int
    gpu_base: int
    allocation_size: int
    logical_size: int
    payload_offset: int


class DataResources:
    def __init__(self, objects, layout, slots):
        A.require(type(objects) is ChannelObjects and objects.phase == 'PREPARED', 'DATA_CHANNEL')
        A.require(type(layout) in (DataLayout, AD.AffineLayout), 'DATA_LAYOUT_TYPE')
        layout.validate()
        A.require(type(slots) is tuple and len(slots) == 4
                  and all(type(s) is DataSlot for s in slots), 'DATA_SLOTS')
        A.require(getattr(objects, '_data_resources', None) is None, 'DATA_OWNER_EXISTS')
        self.objects, self.session, self.tree = objects, objects._session, objects._tree
        self.backend, self.owners, self.abi = objects.backend, objects.owners, objects.abi
        self.mappings, self.control = self.session._mappings, self.session._arena
        self.layout, self.slots = layout, slots
        self._layout, self._slots = layout, slots
        self.thread, self.busy, self.phase, self.failure = threading.get_ident(), True, 'NEW', None
        self.allocators, self.requests, self.bindings, self.records = [], [], [], []
        self.record_images = []
        self._result = None
        self.handles, self.instances = self.tree._handles, self.tree._instances
        self.channel, self.arena_binding = objects._binding, self.session._binding
        self.va = (self.control.observed['va_base'], self.control.observed['va_size'])
        self.uuid, self.memory_class = self.tree.uuid, self.session.config.memory_class
        self.ledger, self.owner_images = (), []
        objects._data_resources = self
        try:
            self._capture(tuple(self.owners))
            self._context(acquiring=True)
            self._plan()
            self._context(acquiring=True)
        except BaseException as exc:
            self._fail(exc)
            raise
        finally:
            self.busy = False

    def _capture(self, owners):
        for o in owners:
            A.require(type(o) is A.Owner and o.state == A.CERTAIN and callable(o.undo), 'DATA_OWNER_STATE')
            self.owner_images.append((o, o.label, copy.deepcopy(o.requested), copy.deepcopy(o.returned), o.undo))
        self.ledger += owners

    def _owned(self):
        A.require(self.objects._data_resources is self and self.objects._session is self.session
                  and self.objects._tree is self.tree and self.objects.backend is self.backend
                  and self.session._tree is self.tree and self.session._arena is self.control
                  and self.session._mappings is self.mappings
                  and self.owners is self.objects.owners and self.owners is self.tree.owners
                  and self.owners is self.backend.owners, 'DATA_OWNER_BINDING')
        self.session._owned()
        A.require(self.layout is self._layout and self.slots is self._slots
                  and type(self.layout) in (DataLayout, AD.AffineLayout), 'DATA_PLAN_CHANGED')

    def _pure(self, *, acquiring=False):
        self._owned()
        A.require(self.objects.phase == 'PREPARED' and self.session.phase == 'ARENA_READY'
                  and self.tree.phase == 'IDENTIFIED' and self.backend.phase == 'ACTIVE'
                  and not self.backend.pending and self.control.phase == A.OPEN
                  and self.mappings.phase == 'ACTIVE', 'DATA_PHASE')
        A.require(self.tree._handles is self.handles and self.tree._instances is self.instances
                  and self.tree.uuid == self.uuid and self.objects._binding is self.channel
                  and self.session._binding is self.arena_binding
                  and self.session.config.memory_class == self.memory_class
                  and (self.control.observed['va_base'], self.control.observed['va_size']) == self.va,
                  'DATA_CONTEXT_CHANGED')
        expected = self.ledger
        schedule = getattr(self.objects, '_initial_schedule', None)
        if not acquiring and schedule is not None and schedule.owner is not None:
            A.require(schedule.phase == 'ACKNOWLEDGED' and schedule.objects is self.objects,
                      'DATA_DESCENDANT_PHASE')
            expected += (schedule.owner,)
        A.require(len(self.owners) == len(expected)
                  and all(a is b for a, b in zip(self.owners, expected)), 'DATA_LEDGER_CHANGED')
        A.require(all(o.state == A.CERTAIN for o in self.owners), 'DATA_OWNER_STATE')
        for o, label, requested, returned, undo in self.owner_images:
            if not (o.label == label and o.requested == requested and o.returned == returned and o.undo is undo):
                o.state = A.UNCERTAIN
                raise A.Stop('DATA_OWNER_CHANGED')
        if acquiring:
            A.require(getattr(self.objects, '_initial_upload', None) is None
                      and schedule is None and getattr(self.objects, '_mapping_transport', None) is None,
                      'DATA_TOO_LATE')
        A.require(len(self.allocators) == len(self.requests) <= 4
                  and len(self.bindings) == len(self.records) == len(self.record_images)
                  and len(self.bindings) <= len(self.allocators), 'DATA_COMPONENT_COUNT')
        for allocator, request in zip(self.allocators, self.requests):
            A.require(allocator.req is request and allocator.backend is self.backend
                      and allocator.owners is self.owners and allocator.abi is self.abi
                      and allocator.phase == A.OPEN, 'DATA_ALLOCATOR_CHANGED')

    def _context(self, *, acquiring=False):
        self._pure(acquiring=acquiring)
        A.require(self.objects.binding() is self.channel and self.session.binding() is self.arena_binding,
                  'DATA_BINDING_CHANGED')
        for binding, record, image in zip(self.bindings, self.records, self.record_images):
            m = binding.mapping
            spec, backing, fingerprint, fd, rm_address = image
            if not (record.spec is spec and record.backing is backing
                    and record.fingerprint == fingerprint and record.fd == fd
                    and record.rm_address == rm_address):
                for owner in record.owners.values():
                    owner.state = A.UNCERTAIN
                raise A.Stop('DATA_RECORD_CHANGED')
            A.require(self.mappings.records.get(m.mapping_id) is record
                      and record.backing.owner is binding.owner
                      and record.backing.memory == binding.memory
                      and record.backing.size == binding.allocation_size
                      and self.mappings.validate_binding(m) is m, 'DATA_MAPPING_CHANGED')
            A.require(m.profile == 'sysmem' and m.cpu_base == binding.cpu_base == binding.gpu_base
                      and m.length == binding.allocation_size
                      and self.mappings._range(record)['state'] == 'M1_MATERIALIZED', 'DATA_MAPPING_SPAN')
            self.mappings._fd(record)
            rows = self.backend._snapshot(m.cpu_base, m.length)
            A.require(len(rows) == 1 and rows[0].start == m.cpu_base and rows[0].end == m.cpu_base + m.length
                      and rows[0].perms == 'rw-s' and rows[0].path == record.fingerprint[4], 'DATA_VMA_CHANGED')
        self._pure(acquiring=acquiring)

    def _plan(self):
        A.require(all(type(s.role) is str for s in self.slots)
                  and tuple(s.role for s in self.slots) ==
                  (AD.ROLES if type(self.layout) is AD.AffineLayout else ROLES), 'DATA_ROLES')
        existing = set(vars(self.handles).values())
        seen, spans = set(), []
        a, c = self.arena_binding, self.channel
        occupied = [(a.cpu_base, a.size), (c.usermode_base, self.abi.const('NVC361_NV_USERMODE__SIZE'))]
        if c.region_length:
            occupied.append((c.region_base, c.region_length))
        for s in self.slots:
            A.require(type(s.memory) is int and 0 < s.memory <= 0xffffffff
                      and s.memory not in existing and s.memory not in seen, 'DATA_MEMORY_HANDLE')
            A.require(type(s.base) is int and s.base > 0 and s.base % A.PAGE == 0
                      and type(s.maximum_size) is int and s.maximum_size >= self.layout.logical_bytes
                      and s.maximum_size % A.PAGE == 0 and s.base + s.maximum_size <= 1 << 40, 'DATA_APERTURE')
            A.contains(s.base, s.maximum_size, *self.va)
            A.require(all(disjoint(s.base, s.maximum_size, b, n) for b, n in occupied + spans), 'DATA_ALIAS')
            seen.add(s.memory)
            spans.append((s.base, s.maximum_size))
        A.require(sum(s.maximum_size for s in self.slots) <= TOTAL_LIMIT, 'DATA_BUDGET')

    def _step(self, fn, labels):
        self._context(acquiring=True)
        prior = self.ledger
        result = fn()
        added = tuple(self.owners[len(prior):])
        A.require(len(self.owners) == len(prior) + len(labels)
                  and all(a is b for a, b in zip(self.owners, prior))
                  and tuple(o.label for o in added) == labels, 'DATA_STEP_LEDGER')
        self._capture(added)
        self._context(acquiring=True)
        return result

    def _fail(self, exc):
        self.failure = {'type': type(exc).__name__, 'message': str(exc)}
        if self.phase not in ('CLOSED', 'TERMINAL'):
            self.phase = 'FAILED'
        for layer in (self.objects, self.session, self.mappings, self.backend):
            if layer.phase in ('CLOSING', 'CLEANUP'):
                layer.phase = 'TERMINAL'
            elif layer.phase not in ('CLOSED', 'TERMINAL'):
                layer.phase = 'FAILED'
        if self.tree.phase not in ('CLOSED', 'TERMINAL'):
            self.tree._failed(exc)
        for allocator in (self.control, *self.allocators):
            allocator._fail('DATA_FAILED', self.failure)

    def acquire(self):
        A.require(not self.busy and threading.get_ident() == self.thread, 'DATA_BUSY')
        A.require(self.phase == 'NEW', 'DATA_CLOSED')
        self.phase, self.busy = 'ACQUIRING', True
        try:
            self._context(acquiring=True)
            self._plan()
            h = self.handles
            for slot in self.slots:
                request = A.ArenaRequest(h.client, h.device, h.subdevice, self.uuid,
                    self.backend.fds['ctl'], self.memory_class, self.layout.logical_bytes,
                    slot.base, h.vas, slot.memory, budget=slot.maximum_size,
                    layout_bytes=self.layout.logical_bytes, consumers={'bo': {'read', 'write'}})
                allocator = A.Arena(request, self.backend, self.abi)
                allocator.owners = self.owners
                self.allocators.append(allocator)
                self.requests.append(request)
                self._step(allocator.allocate, ('memory',))
                memory_owner = self.ledger[-1]
                A.require(memory_owner.returned == slot.memory, 'DATA_MEMORY_OWNER')
                size = allocator.observed['arena_size']
                A.require(self.layout.logical_bytes <= size <= slot.maximum_size
                          and size % A.PAGE == 0 and slot.base + size <= 1 << 40, 'DATA_RETURNED_SPAN')
                A.contains(slot.base, size, *self.va)
                self._plan()
                location = A.field_value(allocator.observed['attr'], self.abi.const('NVOS32_ATTR_LOCATION_SHIFT'),
                                         self.abi.const('NVOS32_ATTR_LOCATION_MASK'))
                backing = Backing(memory_owner, slot.memory, self.memory_class, size, location)
                spec = MapSpec('data-' + slot.role, 'sysmem', slot.base, size)
                mapped = self._step(lambda: self.mappings.create(spec, backing),
                    tuple('m1:' + spec.mapping_id + ':' + r for r in ('reservation', 'fd', 'rm', 'vma')))
                A.require(mapped.cpu_base == slot.base and mapped.length == size, 'DATA_MAPPING_RESULT')
                # Track the live CPU mapping before either dependent UVM call.
                # Public bindings still remain unavailable until all four finish.
                binding = DataBinding(slot.role, slot.memory, memory_owner, allocator, mapped,
                                      mapped.cpu_base, slot.base, size, self.layout.logical_bytes, 256)
                self.bindings.append(binding)
                record = self.mappings.records[mapped.mapping_id]
                self.records.append(record)
                self.record_images.append((spec, backing, record.fingerprint, record.fd, record.rm_address))
                self._step(allocator.external_range, ('uvm_external_range',))
                self._step(allocator.map_gpu, ('uvm_gpu_map',))
                A.require(allocator.observed['gpu_base'] == slot.base, 'DATA_GPU_BASE')
                self._context(acquiring=True)
            self._result = tuple(self.bindings)
            self.phase = 'READY'
            return self._result
        except BaseException as exc:
            self._fail(exc)
            raise
        finally:
            self.busy = False

    def binding(self):
        A.require(not self.busy and threading.get_ident() == self.thread, 'DATA_BUSY')
        A.require(self.phase == 'READY', 'DATA_CLOSED')
        self.busy = True
        try:
            A.require(type(self._result) is tuple and len(self._result) == 4
                      and len(self.bindings) == 4 and all(a is b for a, b in zip(self._result, self.bindings)),
                      'DATA_RESULT_CHANGED')
            self._context()
            return self._result
        except BaseException as exc:
            self._fail(exc)
            raise
        finally:
            self.busy = False

    def teardown(self, safe_state):
        A.require(not self.busy and threading.get_ident() == self.thread, 'DATA_BUSY')
        A.require(safe_state is True, 'DATA_TEARDOWN_UNSAFE')
        A.require(self.phase in ('NEW', 'READY', 'FAILED'), 'DATA_CLOSED')
        self.phase, self.busy = 'CLOSING', True
        try:
            self._owned()
            self.objects.teardown(True)
            for allocator in self.allocators:
                allocator.phase = A.TORN
            self.phase = 'CLOSED'
        except BaseException:
            self.phase = 'TERMINAL'
            for allocator in self.allocators:
                allocator.phase = A.TERMINAL
            raise
        finally:
            self.busy = False
