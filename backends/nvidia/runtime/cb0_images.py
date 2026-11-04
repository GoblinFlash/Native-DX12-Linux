"""Original MODEL_ONLY CB images; no live ownership or publication authority.

Widths/units are the explicit profile in CB0-IMAGE-BOUNDARY, not inferred
from metadata offsets. No foreign host encoder or reviewer oracle is used.
"""
from dataclasses import dataclass
import struct

import shader_info_check as S
import sort_workload as W


@dataclass(frozen=True)
class ModelPlacement:
    role: str
    gpu_base: int
    allocation_size: int
    logical_size: int
    payload_offset: int = 256


def _metadata(kind, views):
    inventory = S.parse(S.pinned((S.HERE.parent / 'data' / 'parallel_sort_programs.json'), S.INVENTORY_SHA))
    entries = inventory['programs'][kind]['artifacts']
    images = {name: S.pinned(e['path'], e['sha256'], e['size'], e['mode'])
              for name, e in entries.items()}
    meta = S.parse(images['json'])
    S.compare(kind, images['bin'], images['info.bin'], meta)
    cb = meta.get('cb0')
    wanted = dict(layout='ndx12.nvidia.shared.cb0.v1', bytes=80, qmd_bytes=128,
                  params_offset=48, param_mask=W.PARAM_MASKS[W.STAGES.index(kind)])
    S.require(type(cb) is dict and set(cb) == set(wanted)
              and all(type(cb[k]) is type(v) and cb[k] == v for k, v in wanted.items()),
              'CB_METADATA_PROFILE')
    rows = meta.get('bindings')
    S.require(type(rows) is list and len(rows) == len(views), 'CB_BINDING_COUNT')
    fields = {'binding', 'reads', 'writes', 'base_offset', 'size_offset'}
    for i, (row, view) in enumerate(zip(rows, views)):
        S.require(type(row) is dict and set(row) == fields
                  and all(type(row[k]) is int and row[k] >= 0 for k in fields), 'CB_BINDING_SHAPE')
        S.require(row['binding'] == i and row['base_offset'] == 16*i
                  and row['size_offset'] == 16*i+8, 'CB_BINDING_OFFSETS')
        S.require((view.access == 'R' and row['reads'] > 0 and row['writes'] == 0)
                  or (view.access == 'W' and row['reads'] == 0 and row['writes'] > 0),
                  'CB_BINDING_DIRECTION')
    return wanted['param_mask']


def _request(workload, index, placements):
    S.require(type(workload) is W.Workload, 'CB_WORKLOAD_TYPE')
    workload.validate()
    S.require(type(index) is int and 0 <= index < 40, 'CB_STAGE_INDEX')
    stage = workload.stages[index]
    S.require(type(placements) is tuple and len(placements) == 4
              and all(type(p) is ModelPlacement for p in placements), 'CB_PLACEMENTS_TYPE')
    S.require(all(type(p.role) is str for p in placements)
              and tuple(p.role for p in placements) == W.ROLES, 'CB_PLACEMENT_ROLES')
    spans = []
    for p in placements:
        S.require(all(type(x) is int for x in
                      (p.gpu_base, p.allocation_size, p.logical_size, p.payload_offset)),
                  'CB_PLACEMENT_TYPE')
        S.require(0 < p.gpu_base < 1 << 40 and p.gpu_base % 4096 == 0
                  and 0 < p.allocation_size <= (1 << 40)-p.gpu_base
                  and p.allocation_size % 4096 == 0, 'CB_PLACEMENT_SPAN')
        S.require(p.logical_size == workload.layout.logical_bytes
                  and p.allocation_size >= p.logical_size and p.payload_offset == 256,
                  'CB_PLACEMENT_LAYOUT')
        S.require(all(p.gpu_base+p.allocation_size <= base or base+size <= p.gpu_base
                      for base, size in spans), 'CB_PLACEMENT_ALIAS')
        spans.append((p.gpu_base, p.allocation_size))
    S.require(sum(p.allocation_size for p in placements) <= 64*1024*1024, 'CB_PLACEMENT_BUDGET')
    mask = _metadata(stage.kind, stage.views)
    S.require(all(value == 0 for i, value in enumerate(stage.params) if not mask & (1 << i)),
              'CB_UNUSED_PARAMETER')
    descriptors = []
    for view in stage.views:
        p = placements[W.ROLES.index(view.role)]
        length = 4 * view.words
        S.require(0 < length < 1 << 32 and p.payload_offset % 4 == 0
                  and p.payload_offset <= p.logical_size-256
                  and length <= p.logical_size-256-p.payload_offset
                  and length <= p.allocation_size-p.payload_offset, 'CB_VIEW_SPAN')
        descriptors.append((p.gpu_base+p.payload_offset, length))
    return stage.params, tuple(descriptors)


def _encode(params, descriptors):
    result = bytearray(128)
    for i, (address, length) in enumerate(descriptors):
        struct.pack_into('<QI', result, 16*i, address, length)
    struct.pack_into('<8I', result, 48, *params)
    return bytes(result)


def image(workload, index, placements):
    """Return bytes only. ModelPlacement is never evidence of live ownership."""
    params, descriptors = _request(workload, index, placements)
    return _encode(params, descriptors)


def verify(raw, workload, index, placements):
    S.require(type(raw) is bytes and len(raw) == 128, 'CB_IMAGE_SIZE')
    params, descriptors = _request(workload, index, placements)
    for i in range(3):
        wanted = descriptors[i] if i < len(descriptors) else (0, 0)
        S.require(struct.unpack_from('<QI', raw, 16*i) == wanted, 'CB_DESCRIPTOR_MISMATCH')
        S.require(raw[16*i+12:16*i+16] == bytes(4), 'CB_DESCRIPTOR_PADDING')
    S.require(struct.unpack_from('<8I', raw, 48) == params, 'CB_PARAMETER_MISMATCH')
    S.require(raw[80:] == bytes(48), 'CB_FINAL_PADDING')
    S.require(raw == _encode(params, descriptors), 'CB_IMAGE_MISMATCH')
    return raw
