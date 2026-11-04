"""Owning channel preparation from the reviewed header-based requirements.

Own code; imports team Arena primitives and our identity/image/resource layers.
No old helpers or driver implementation template. C361 size/offset used for
C461 remains a declared cross-class profile. No upload, schedule or publication
is exposed. read_memory is an injected, trusted exact byte reader; its native
implementation and completion protocol require separate integration.
"""
from dataclasses import dataclass, replace
from channel_images import Instances
from channel_resources import ArenaSession
from replacement_inputs import arena as A
from mapping_protocol import Backing, MapSpec


@dataclass(frozen=True)
class ChannelConfig:
    usermode_base: int
    region_base: int
    ring_offset: int
    userd_offset: int

    def validate(self, session):
        A.require(all(type(x) is int for x in vars(self).values()), 'OBJECT_CONFIG_TYPE')
        length = session._tree.abi.const('NVC361_NV_USERMODE__SIZE')
        A.require(self.usermode_base > 0 and self.usermode_base % A.PAGE == 0
                  and self.usermode_base + length <= 1 << 47, 'OBJECT_USERMODE_SPAN')
        A.require(0 <= self.region_base < 1 << 40 and self.region_base % A.PAGE == 0,
                  'OBJECT_REGION_BASE')
        base, size = session.config.base, session.config.size
        A.require(disjoint(base, size, self.usermode_base, length), 'OBJECT_MAP_ALIAS')
        plan = session._tree.plan
        client = 1
        while client in vars(plan).values():
            client += 1
        session._tree.images.channel(replace(plan, client=client), Instances(session._tree.card.gpu_id, 0, 0),
                                     base, size, self.ring_offset, self.userd_offset)


def disjoint(a, n, b, m):
    return a + n <= b or b + m <= a


@dataclass(frozen=True)
class PreparedBinding:
    channel: int
    compute: int
    usermode: int
    usermode_base: int
    doorbell_address: int
    userd_address: int
    ring_address: int
    token: int
    region_base: int
    region_length: int


class ChannelObjects:
    """Exclusive preparation, with one shared ledger and no automatic cleanup."""
    def __init__(self, session, config, read_memory, *, region_profile='REQUIRED_BUFFER_INFO',
                 region_alignment=None, region_factor=None, region_budget=None):
        A.require(type(session) is ArenaSession and session.phase == 'NEW', 'OBJECT_SESSION_FRESH')
        A.require(type(config) is ChannelConfig and callable(read_memory), 'OBJECT_CONFIG')
        A.require(type(region_profile) is str and region_profile in
                  ('REQUIRED_BUFFER_INFO', 'ZERO_REGION', 'SIZE_QUERY_PROBE', 'REPORTED_TOTAL_SIZE'), 'OBJECT_REGION_PROFILE')
        if region_profile == 'REPORTED_TOTAL_SIZE':
            A.require(type(region_alignment) is int and region_alignment == 2 * 1024 * 1024
                      and type(region_factor) is int and region_factor in (1, 2)
                      and type(region_budget) is int and region_alignment <= region_budget <= 256 * 1024 * 1024
                      and region_budget % 4096 == 0 and config.region_base % region_alignment == 0,
                      'OBJECT_REGION_PROFILE')
        else:
            A.require(region_alignment is None and region_factor is None and region_budget is None,
                      'OBJECT_REGION_PROFILE')
        self._region_policy = (region_alignment, region_factor, region_budget)
        self._region_profile = region_profile
        config.validate(session)
        A.require(getattr(session, '_channel_session', None) is None, 'OBJECT_OWNER_EXISTS')
        self._session, self.config, self._read = session, config, read_memory
        self._tree, self.abi = session._tree, session._tree.abi
        self.backend, self.owners = self._tree.backend, self._tree.owners
        self.phase, self.failure, self.observed = 'NEW', None, {}
        self._binding = None
        self._usermode_mapping = None
        session._channel_session = self

    def _owned(self):
        A.require(self._session._channel_session is self and self.owners is self._tree.owners,
                  'OBJECT_OWNER_BINDING')
        self._session._owned()

    def _acquire(self, label, requested, effect, validate, undo):
        self._owned()
        owner = A.Owner(label, requested)
        self.owners.append(owner)
        try:
            returned = effect()
        except A.Rejected as exc:
            self.owners.pop()
            raise A.Stop('OBJECT_REJECTED', step=label) from exc
        except BaseException:
            owner.state = A.UNCERTAIN
            raise
        owner.returned = returned
        try:
            validate(returned)
        except BaseException:
            owner.state = A.UNCERTAIN
            raise
        owner.undo, owner.state = undo, A.CERTAIN
        return returned

    def _ioctl(self, name, struct, values):
        codec = self.abi.struct(struct)
        data = codec.pack(values)
        rc = self.backend.ioctl('ctl', self.abi.const(name), data)
        return rc, codec.unpack(data)

    def _usermode_map(self, handles):
        c, cfg = self.abi.const, self.config
        base, length = cfg.usermode_base, c('NVC361_NV_USERMODE__SIZE')
        owner = self.owners[-1]
        A.require(owner.label == 'rm:usermode' and owner.state == A.CERTAIN, 'OBJECT_USERMODE_OWNER')
        mapping = self._session._mappings
        backing = Backing(owner, handles.usermode, c('TURING_USERMODE_A'), length)
        self._usermode_mapping = mapping.create(MapSpec('usermode', 'usermode', base, length), backing)
        binding = mapping.validate_binding(self._usermode_mapping)
        A.require((binding.cpu_base, binding.length) == (base, length), 'OBJECT_MAPPING_BINDING')

    def _object(self, image, stable_fields=()):
        self._owned()
        self._tree._allocate(image)
        if image.parameter_type:
            codec = self.abi.struct(image.parameter_type)
            sent = codec.unpack(image.parameters)
            raw = bytes.fromhex(self._tree.observed[-1]['parameters_output'])
            out = codec.unpack(raw)
            self.observed[image.label] = out
            A.require(all((self._tree.images.channel_flags_match(sent[k], out[k])
                           if image.label == 'channel' and k == 'flags' else out[k] == sent[k])
                          for k in stable_fields), 'OBJECT_RETURNED_BINDING', label=image.label)

    def _context_size(self, h):
        tree = self._tree
        i = tree.images
        image = i.control(h.client, h.subdevice, 'NV2080_CTRL_CMD_GR_GET_CTX_BUFFER_SIZE',
                          'NV2080_CTRL_GR_GET_CTX_BUFFER_SIZE_PARAMS', {'hChannel': h.channel})
        rc, envelope, parameters = tree._call('NVOS54_PARAMETERS', 'IOCTL_RM_CONTROL',
                                             image.envelope, image.parameters)
        out = self.abi.struct('NVOS54_PARAMETERS').unpack(envelope)
        info = self.abi.struct(image.parameter_type).unpack(parameters)
        receipt = {'operation': 'context_size_probe', 'rc': rc, 'status': out['status'],
                   'hChannel': info['hChannel'], 'totalBufferSize': info['totalBufferSize'],
                   'input': image.envelope.hex(), 'output': bytes(envelope).hex(),
                   'parameters_input': image.parameters.hex(),
                   'parameters_output': bytes(parameters).hex()}
        self.observed['context_size_probe'] = receipt
        self.backend._emit(receipt)
        A.require(type(rc) is int and rc == 0 and out['status'] == self.abi.const('NV_OK'),
                  'OBJECT_CTX_SIZE_STATUS', rc=rc, status=out['status'])
        sent = self.abi.struct('NVOS54_PARAMETERS').unpack(image.envelope)
        A.require(info['hChannel'] == h.channel and all(out[k] == sent[k] for k in
                  ('hClient','hObject','cmd','flags','paramsSize')), 'OBJECT_CTX_SIZE_IDENTITY')
        return info['totalBufferSize']

    def _register_reported_region(self, handles, total):
        # Depends on the pinned private arena lifecycle/reservation/UVM API.
        arena = self._session._arena
        alignment, factor, budget = self._region_policy
        A.require(type(total) is int and 0 < total <= (1 << 64) - 1, 'OBJECT_REGION_TOTAL')
        length = ((factor * total + alignment - 1) // alignment) * alignment
        base = self.config.region_base
        A.require(length <= budget and length <= (1 << 64) - 1, 'OBJECT_REGION_BUDGET', length=length, budget=budget)
        A.contains(base, length, arena.observed['va_base'], arena.observed['va_size'])
        A.require(base + length <= 1 << 40 and disjoint(base, length, self.config.usermode_base,
                  self.abi.const('NVC361_NV_USERMODE__SIZE')) and disjoint(base, length,
                  self._session.config.base, self._session.config.size), 'OBJECT_REGION_ALIAS')
        receipt = {'operation': 'channel_region_profile', 'profile': self._region_profile,
                   'reported_total': total, 'alignment': alignment, 'factor': factor,
                   'budget': budget, 'base': base, 'length': length}
        self.observed['region_profile'] = receipt
        self.backend._emit(receipt)
        def register():
            r = arena.req
            arena._reserve('channel_region:%d' % handles.channel, base, length)
            arena._uvm_acquire('uvm_channel:%d' % handles.channel, handles.channel,
                'UVM_REGISTER_CHANNEL', 'UVM_REGISTER_CHANNEL_PARAMS',
                {'gpuUuid': r.gpu_uuid, 'rmCtrlFd': r.rm_ctrl_fd, 'hClient': r.h_client,
                 'hChannel': handles.channel, 'base': base, 'length': length},
                undo=lambda: arena._uvm('UVM_UNREGISTER_CHANNEL', 'UVM_UNREGISTER_CHANNEL_PARAMS',
                                       {'hClient': r.h_client, 'hChannel': handles.channel}))
            arena.observed['channel_region:%d' % handles.channel] = (base, length, alignment)
            return base, length
        return arena._run('register_channel:%r' % handles.channel, register)

    def prepare(self):
        A.require(self.phase == 'NEW', 'OBJECT_CLOSED')
        self.phase = 'PREPARING'
        try:
            self._owned()
            arena_binding = self._session.open_arena()
            tree, cfg, i = self._tree, self.config, self._tree.images
            h, inst = tree.identity()
            length = self.abi.const('NVC361_NV_USERMODE__SIZE')
            A.require(disjoint(arena_binding.cpu_base, arena_binding.size, cfg.usermode_base, length),
                      'OBJECT_MAP_ALIAS')
            channel_image = i.channel(h, inst, arena_binding.gpu_base, arena_binding.size,
                                       cfg.ring_offset, cfg.userd_offset)
            self._object(i.usermode(h))
            self._usermode_map(h)
            self._object(i.group(h), ('hVASpace', 'engineType'))
            self._object(i.context(h), ('hVASpace', 'flags', 'subctxId'))
            self._object(channel_image, ('gpFifoOffset', 'gpFifoEntries', 'flags', 'hContextShare',
                                         'hVASpace', 'hUserdMemory', 'userdOffset', 'engineType', 'subDeviceId'))
            self._object(i.compute(h), ('version', 'size'))
            userd_address = arena_binding.cpu_base + cfg.userd_offset
            userd = self._read(userd_address, self.abi.struct('Nvc56fControl').size)
            A.require(type(userd) is bytes, 'OBJECT_READ_TYPE')
            i.check_initial_userd(userd)
            self.observed['initial_userd'] = userd
            arena = self._session._arena
            if self._region_profile == 'SIZE_QUERY_PROBE':
                raise A.Stop('OBJECT_CTX_SIZE_PROBE', totalBufferSize=self._context_size(h))
            if self._region_profile == 'REPORTED_TOTAL_SIZE':
                region_base, region_length = self._register_reported_region(h, self._context_size(h))
            else:
                # Explicit separately admitted profile, never a fallback after query failure.
                records = () if self._region_profile == 'ZERO_REGION' else arena.ctx_buffer_records(h.channel)
                region_length, _ = A.channel_region_length(records)
                if region_length:
                    A.require(cfg.region_base + region_length <= 1 << 40, 'OBJECT_REGION_SPAN')
                    A.require(disjoint(cfg.region_base, region_length, cfg.usermode_base, length), 'OBJECT_REGION_ALIAS')
                region_base, region_length = arena.register_channel(h.channel, cfg.region_base, records)
            token = i.read_token(tree._query(i.token(h)))
            mmio = self._session._mappings.validate_binding(self._usermode_mapping)
            self._binding = PreparedBinding(h.channel, h.compute, h.usermode, mmio.cpu_base,
                                           mmio.cpu_base + self.abi.const('NVC361_NOTIFY_CHANNEL_PENDING'),
                                           userd_address, arena_binding.gpu_base + cfg.ring_offset,
                                           token, region_base, region_length)
            self.phase = 'PREPARED'
            return self.binding()
        except BaseException as exc:
            self.phase, self.failure = 'FAILED', {'type': type(exc).__name__, 'reason': str(exc)}
            self._session.phase = 'FAILED'
            tree = self._tree
            tree._failed(exc)
            if self._session._arena is not None:
                self._session._arena._fail('OBJECT_FAILED', self.failure)
            raise

    def binding(self):
        A.require(self.phase == 'PREPARED', 'OBJECT_NOT_PREPARED')
        self._owned()
        self._session.binding()
        self._session._mappings.validate_binding(self._usermode_mapping)
        return self._binding

    def teardown(self, safe_state):
        A.require(safe_state is True, 'OBJECT_TEARDOWN_UNSAFE')
        A.require(self.phase in ('PREPARED', 'FAILED'), 'OBJECT_CLOSED')
        self.phase = 'CLOSING'
        try:
            self._owned()
            self._session.teardown(True)
            self.phase = 'CLOSED'
        except BaseException:
            self.phase = 'TERMINAL'
            raise
