"""Original PE0..PE5 byte policy; a model result, never completion authority.

Uses original team image builders and the pinned team scope-B oracle. No
observed image supplies expected bytes, starting state, geometry or a mask.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
import struct

import control_images as CI
import sort_data_layout as D

S = CI.S
POLICY = 'P0_USERD_GET_PUT_1_OTHER_504_BYTES_EXCLUDED'


@dataclass(frozen=True)
class ModelResult:
    prefix: int
    signal: int
    roles: tuple
    data_bytes: tuple
    data_sha256: tuple
    control_bytes: int
    control_compared_bytes: int
    control_sha256: str
    userd_excluded_intervals: tuple
    userd_policy: str
    full_sort_checked: bool
    status: str = 'CPU_POST_EXECUTION_IMAGE_MODEL_VERIFIED'
    native_execution_proven: bool = False
    flight_retirement_authorized: bool = False


def _region(layout, offset):
    for slot in layout.slots:
        if slot.offset <= offset < slot.offset + slot.reserved:
            relative = offset - slot.offset
            if slot.label.startswith('qmd:') and 24 <= relative < 32:
                return slot.label + ':CTA_RASTER_RESUME[192:255]'
            return slot.label
    return 'hole-or-tail'


def _full_sort(raw, layout):
    start = 4 * layout.payload_offset_words
    keys = struct.unpack_from('<' + str(len(layout.keys)) + 'I', raw, start)
    S.require(all(a <= b for a, b in zip(keys, keys[1:])), 'PE_SORT_ORDER')
    S.require(Counter(keys) == Counter(layout.keys), 'PE_SORT_MULTISET')


def verify(inputs, prefix, signal, initial_userd, observed_control, observed_data,
           observed_get, observed_put):
    """Compare supplied immutable byte strings; no live read or owner transition."""
    if type(inputs) is CI.P.Inputs and type(inputs.workload) is CI.P.AI.D.AffineLayout:
        CI.P._admit(inputs, prefix, signal)
        a = inputs.layout.arena
        spec = CI.P.AI.ControlSpec(a.gpu_base, a.allocation_size, a.ring_offset, a.userd_offset)
        return CI.P.AI.verify_observed(inputs.workload, inputs.placements, spec, prefix, signal,
                                      initial_userd, observed_control, observed_data,
                                      observed_get, observed_put)
    S.require(type(prefix) is int and 1 <= prefix <= 40, 'PE_PREFIX')
    S.require(type(signal) is int and 0 < signal < 1 << 32, 'PE_SIGNAL')
    S.require(type(inputs) is CI.P.Inputs, 'PE_INPUT_TYPE')
    S.require(type(observed_control) is bytes, 'PE_CONTROL_TYPE')
    S.require(type(observed_data) is tuple and len(observed_data) == 4
              and all(type(raw) is bytes for raw in observed_data), 'PE_DATA_TYPE')
    S.require(all(type(value) is int and 0 <= value < 1 << 32
                  for value in (observed_get, observed_put)), 'PE_RING_TYPE')
    S.require(observed_get == observed_put == 1, 'PE_RING_POSITION')
    # compose admits all40 CB/QMD images, all pinned code, layout and initial
    # USERD ABI before any interpretation of observed bytes or geometry.
    initial = CI.compose(inputs, prefix, signal, initial_userd)
    layout = inputs.layout
    slots = {slot.label: slot for slot in layout.slots}
    S.require(len(observed_control) == layout.arena.allocation_size, 'PE_CONTROL_SIZE')
    sizes = tuple(p.allocation_size for p in inputs.placements)
    S.require(tuple(len(raw) for raw in observed_data) == sizes, 'PE_DATA_SIZE')

    u = slots['userd'].offset
    completion = slots['completion'].offset
    expected_control = bytearray(initial.raw)
    expected_control[completion:completion+4] = struct.pack('<I', signal)
    expected_control[u+0x88:u+0x90] = struct.pack('<II', 1, 1)
    embedded = struct.unpack_from('<II', observed_control, u+0x88)
    S.require(embedded == (observed_get, observed_put), 'PE_RING_OBSERVATION')
    excluded = ((u, u+0x88), (u+0x90, u+512))
    included = ((0, u), (u+0x88, u+0x90), (u+512, len(observed_control)))
    for start, end in included:
        if observed_control[start:end] != expected_control[start:end]:
            offset = next(i for i in range(start, end)
                          if observed_control[i] != expected_control[i])
            raise S.Refused('PE_CONTROL_BYTES:' + _region(layout, offset)
                            + ':offset=' + str(offset))

    data_layout = inputs.workload.layout
    geo, logical = data_layout.validate()
    # No optional initial argument: untouched logical words start from the
    # independently retained keys/poison, never from an observed candidate.
    words = D.B.expected_state(data_layout.keys, geo, logical, prefix)
    expected_data = tuple(D.B.pack(words[role]) + D.POISON.to_bytes(4, 'little') *
                          ((size - data_layout.logical_bytes) // 4)
                          for role, size in zip(D.ROLES, sizes))
    for role, raw, expected in zip(D.ROLES, observed_data, expected_data):
        S.require(raw == expected, 'PE_DATA_BYTES:' + role)
    if prefix == 40:
        _full_sort(observed_data[0], data_layout)
    return ModelResult(prefix, signal, D.ROLES, sizes,
                       tuple(hashlib.sha256(raw).hexdigest() for raw in observed_data),
                       len(observed_control), len(observed_control)-504,
                       hashlib.sha256(observed_control).hexdigest(), excluded, POLICY,
                       prefix == 40)
