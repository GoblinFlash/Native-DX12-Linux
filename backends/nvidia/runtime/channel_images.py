"""Pure channel request images, from reviewed contract C0–C3 and pinned ABI.

No fd, syscall, MMIO, scheduling execution or publication. Codex original code;
no old create_channel or vendor implementation used. Parent/identity/ordering
inputs still have to come from a future owning runtime, not caller assertions.
"""
from dataclasses import dataclass, fields
from replacement_inputs import arena as A


def u32(x, name, nonzero=False):
    A.require(type(x) is int and (1 if nonzero else 0) <= x <= 0xffffffff,
              'CHANNEL_U32', field=name)
    return x


@dataclass(frozen=True)
class Handles:
    client: int
    device: int
    subdevice: int
    vas: int
    memory: int
    usermode: int
    tsg: int
    context: int
    channel: int
    compute: int

    def validate(self):
        values = [u32(getattr(self, f.name), f.name, True) for f in fields(self)]
        A.require(len(values) == len(set(values)), 'CHANNEL_HANDLE_ALIAS')


@dataclass(frozen=True)
class Instances:
    gpu_id: int
    device_instance: int
    subdevice_instance: int

    def validate(self):
        for f in fields(self):
            u32(getattr(self, f.name), f.name)
        A.require(self.subdevice_instance == 0, 'SUBDEVICE_INSTANCE_UNSUPPORTED')


@dataclass(frozen=True)
class Allocation:
    label: str
    envelope: bytes
    parameter_type: str | None
    parameters: bytes


@dataclass(frozen=True)
class Control:
    command: int
    object_handle: int
    envelope: bytes
    parameter_type: str
    parameters: bytes


class Images:
    def __init__(self, abi):
        self.abi = abi
        self.c = abi.const

    def _alloc(self, label, root, parent, handle, cls, struct, values):
        for name, value in [('root', root), ('parent', parent), ('handle', handle)]:
            u32(value, name)
        aux = bytes(self.abi.struct(struct).pack(values)) if struct else b''
        data = self.abi.struct('NVOS21_PARAMETERS').pack({
            'hRoot': root, 'hObjectParent': parent, 'hObjectNew': handle,
            'hClass': self.c(cls), 'paramsSize': len(aux)})
        return Allocation(label, bytes(data), struct, aux)

    def client(self):
        # C0 baseline: RM-generated handle. Other client fields zero by profile.
        return self._alloc('client', 0, 0, 0, 'NV01_ROOT_CLIENT', 'NV0000_ALLOC_PARAMETERS', {})

    def device(self, handles, instances, *, multiple_vaspaces=False):
        handles.validate()
        instances.validate()
        A.require(type(multiple_vaspaces) is bool, 'VAMODE_PROFILE')
        mode = ('NV_DEVICE_ALLOCATION_VAMODE_MULTIPLE_VASPACES' if multiple_vaspaces
                else 'NV_DEVICE_ALLOCATION_VAMODE_OPTIONAL_MULTIPLE_VASPACES')
        return self._alloc('device', handles.client, handles.client, handles.device, 'NV01_DEVICE_0',
                           'NV0080_ALLOC_PARAMETERS', {'deviceId': instances.device_instance, 'vaMode': self.c(mode)})

    def subdevice(self, handles, instances):
        handles.validate()
        instances.validate()
        return self._alloc('subdevice', handles.client, handles.device, handles.subdevice, 'NV20_SUBDEVICE_0',
                           'NV2080_ALLOC_PARAMETERS', {'subDeviceId': instances.subdevice_instance})

    def usermode(self, handles):
        handles.validate()
        # C-C3 unknown acceptance: NULL params. No fabricated alternative.
        return self._alloc('usermode', handles.client, handles.subdevice, handles.usermode,
                           'TURING_USERMODE_A', None, {})

    def group(self, handles):
        handles.validate()
        return self._alloc('tsg', handles.client, handles.device, handles.tsg, 'KEPLER_CHANNEL_GROUP_A',
                           'NV_CHANNEL_GROUP_ALLOCATION_PARAMETERS',
                           {'hVASpace': handles.vas, 'engineType': self.c('NV2080_ENGINE_TYPE_GRAPHICS')})

    def context(self, handles):
        handles.validate()
        flags = A.field_set(self.c('NV_CTXSHARE_ALLOCATION_FLAGS_SUBCONTEXT_SYNC'),
                            self.c('NV_CTXSHARE_ALLOCATION_FLAGS_SUBCONTEXT_SHIFT'),
                            self.c('NV_CTXSHARE_ALLOCATION_FLAGS_SUBCONTEXT_MASK'))
        return self._alloc('context', handles.client, handles.tsg, handles.context, 'FERMI_CONTEXT_SHARE_A',
                           'NV_CTXSHARE_ALLOCATION_PARAMETERS', {'hVASpace': handles.vas, 'flags': flags})

    def channel(self, handles, instances, arena_base, arena_length, ring_offset, userd_offset):
        handles.validate()
        instances.validate()  # Same checked subdevice drives both mask and USERD slot.
        A.require(all(type(x) is int for x in (arena_base, arena_length, ring_offset, userd_offset))
                  and arena_base > 0 and arena_length > 0 and arena_base + arena_length <= 1 << 40,
                  'CHANNEL_ARENA')
        # Baseline C-C4 = eight entries; alternative geometry is a separate profile.
        entries, userd_length = 8, self.abi.struct('Nvc56fControl').size
        A.require(ring_offset >= 0 and (arena_base + ring_offset) % 8 == 0
                  and ring_offset + entries * 8 <= arena_length, 'CHANNEL_RING')
        A.require(userd_offset >= 0 and userd_offset % 512 == 0
                  and userd_offset + userd_length <= arena_length, 'CHANNEL_USERD')
        A.require(ring_offset + entries * 8 <= userd_offset or userd_offset + userd_length <= ring_offset,
                  'CHANNEL_RING_USERD_ALIAS')
        slot = instances.subdevice_instance
        memories, offsets = [0] * self.c('NV_MAX_SUBDEVICES'), [0] * self.c('NV_MAX_SUBDEVICES')
        memories[slot], offsets[slot] = handles.memory, userd_offset
        flags = ((self.c('NVOS04_FLAGS_DELAY_CHANNEL_SCHEDULING_TRUE') << self.c('NVOS04_FLAGS_DELAY_CHANNEL_SCHEDULING_SHIFT'))
                 | (self.c('NVOS04_FLAGS_CHANNEL_CLIENT_MAP_FIFO_TRUE') << self.c('NVOS04_FLAGS_CHANNEL_CLIENT_MAP_FIFO_SHIFT')))
        return self._alloc('channel', handles.client, handles.tsg, handles.channel, 'AMPERE_CHANNEL_GPFIFO_A',
                           'NV_CHANNEL_ALLOC_PARAMS', {'gpFifoOffset': arena_base + ring_offset,
                            'gpFifoEntries': entries, 'flags': flags, 'hContextShare': handles.context,
                            'hVASpace': 0, 'hHandleVASpace': 0, 'hUserdMemory': memories, 'userdOffset': offsets,
                            'engineType': self.c('NV2080_ENGINE_TYPE_GRAPHICS'), 'subDeviceId': 1 << slot})

    def channel_flags_match(self, sent, returned):
        # alloc_channel.h bit5: PRIVILEGED_CHANNEL, effective only for GSP-vGPU
        # plugin clients. Observed RM615 output normalization; never request it.
        return (type(sent) is int and type(returned) is int and sent & 0x20 == 0
                and returned in (sent, sent | 0x20))

    def compute(self, handles):
        handles.validate()
        name = 'NV_GR_ALLOCATION_PARAMETERS'
        return self._alloc('compute', handles.client, handles.channel, handles.compute, 'ADA_COMPUTE_A',
                           name, {'version': 2, 'size': self.abi.struct(name).size})

    def control(self, client, obj, command, struct, values):
        u32(client, 'client', True)
        u32(obj, 'object', True)
        aux = bytes(self.abi.struct(struct).pack(values))
        cmd = self.c(command)
        data = self.abi.struct('NVOS54_PARAMETERS').pack({
            'hClient': client, 'hObject': obj, 'cmd': cmd, 'paramsSize': len(aux)})
        return Control(cmd, obj, bytes(data), struct, aux)

    def id_info(self, client, gpu_id):
        u32(gpu_id, 'gpu_id')
        return self.control(client, client, 'NV0000_CTRL_CMD_GPU_GET_ID_INFO_V2',
                            'NV0000_CTRL_GPU_GET_ID_INFO_V2_PARAMS', {'gpuId': gpu_id})

    def subdevice_identity(self, handles):
        handles.validate()
        get_id = self.control(handles.client, handles.subdevice, 'NV2080_CTRL_CMD_GPU_GET_ID',
                              'NV2080_CTRL_GPU_GET_ID_PARAMS', {})
        flags = (self.c('NV2080_GPU_CMD_GPU_GET_GID_FLAGS_FORMAT_BINARY_SHIFTED')
                 | self.c('NV2080_GPU_CMD_GPU_GET_GID_FLAGS_TYPE_SHA1_SHIFTED')
                 | self.c('NV2080_GPU_CMD_GPU_GET_GID_FLAGS_MODE_GPU_SHIFTED'))
        get_uuid = self.control(handles.client, handles.subdevice, 'NV2080_CTRL_CMD_GPU_GET_GID_INFO',
                                'NV2080_CTRL_GPU_GET_GID_INFO_PARAMS', {'flags': flags, 'length': 16})
        return get_id, get_uuid

    def token(self, handles):
        handles.validate()
        return self.control(handles.client, handles.channel, 'NVC36F_CTRL_CMD_GPFIFO_GET_WORK_SUBMIT_TOKEN',
                            'NVC36F_CTRL_CMD_GPFIFO_GET_WORK_SUBMIT_TOKEN_PARAMS', {})

    def scheduling(self, handles, *, bind_group=False):
        handles.validate()
        A.require(type(bind_group) is bool, 'SCHEDULE_PROFILE')
        calls = []
        if bind_group:
            calls.append(self.control(handles.client, handles.tsg, 'NVA06C_CTRL_CMD_BIND',
                         'NVA06F_CTRL_BIND_PARAMS', {'engineType': self.c('NV2080_ENGINE_TYPE_GRAPHICS')}))
        calls.append(self.control(handles.client, handles.channel, 'NVA06F_CTRL_CMD_GPFIFO_SCHEDULE',
                                  'NVA06F_CTRL_GPFIFO_SCHEDULE_PARAMS', {'bEnable': 1}))
        return tuple(calls)

    def validate_schedule_images(self, handles, calls):
        # Equality includes complete envelopes/params, not merely command names.
        # This is a plan check, never evidence that scheduling actually succeeded.
        A.require(type(calls) is tuple and calls in (self.scheduling(handles),
                  self.scheduling(handles, bind_group=True)), 'CHANNEL_SCHEDULE_PLAN')

    def decode_instances(self, raw, expected_gpu_id):
        u32(expected_gpu_id, 'gpu_id')
        out = self.abi.struct('NV0000_CTRL_GPU_GET_ID_INFO_V2_PARAMS').unpack(raw)
        A.require(out['gpuId'] == expected_gpu_id, 'CHANNEL_GPU_ID')
        result = Instances(out['gpuId'], out['deviceInstance'], out['subDeviceInstance'])
        result.validate()
        return result

    def client_result(self, rc, envelope, parameters):
        out = self.abi.struct('NVOS21_PARAMETERS').unpack(envelope)
        aux = self.abi.struct('NV0000_ALLOC_PARAMETERS').unpack(parameters)
        x, y = out['hObjectNew'], aux['hClient']
        evidence = {'rc': rc, 'status': out['status'], 'hObjectNew': x, 'hClient': y}
        A.require(type(rc) is int and rc == 0 and out['status'] == self.c('NV_OK')
                  and (x or y) and (not x or not y or x == y),
                  'CLIENT_IDENTITY_UNCERTAIN', observed=evidence)
        return (x or y), ('both' if x and y else 'envelope' if x else 'parameters'), evidence

    def check_subdevice_identity(self, gpu_id, uuid, raw_id, raw_uuid):
        u32(gpu_id, 'gpu_id')
        A.require(type(uuid) is bytes and len(uuid) == 16, 'CHANNEL_UUID_PLAN')
        ident = self.abi.struct('NV2080_CTRL_GPU_GET_ID_PARAMS').unpack(raw_id)
        gid = self.abi.struct('NV2080_CTRL_GPU_GET_GID_INFO_PARAMS').unpack(raw_uuid)
        A.require(ident['gpuId'] == gpu_id and gid['length'] == 16 and gid['data'][:16] == uuid,
                  'CHANNEL_SUBDEVICE_IDENTITY')

    def check_initial_userd(self, raw):
        # Read only. Never synthesize a zeroed USERD for upload.
        out = self.abi.struct('Nvc56fControl').unpack(raw)
        A.require(out['GPGet'] == 0 and out['GPPut'] == 0, 'CHANNEL_USERD_NOT_EMPTY')

    def read_token(self, raw):
        return self.abi.struct('NVC36F_CTRL_CMD_GPFIFO_GET_WORK_SUBMIT_TOKEN_PARAMS').unpack(raw)['workSubmitToken']
