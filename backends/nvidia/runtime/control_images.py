"""Original CI model composer. Bytes only, never authority for native publication.

Expected USERD is a separate caller-retained input. This initial-image verifier
is deliberately unsuitable for post-publication readback or owner retirement.
"""
from dataclasses import dataclass
import struct

import push_images as P
import gp_entry as G
from replacement_inputs import arena as A

S = P.S


@dataclass(frozen=True)
class ImageSpan:
    offset: int
    data: bytes


@dataclass(frozen=True)
class ModelControlImage:
    raw: bytes
    spans: tuple


def _userd(raw):
    S.require(type(raw) is bytes and len(raw) == 512, 'CONTROL_IMAGE_USERD')
    spec = A.Abi().struct('Nvc56fControl')
    S.require(spec.size == 512 and spec.fields['GPGet'] == (0x88, 4, 'u32')
              and spec.fields['GPPut'] == (0x8c, 4, 'u32'), 'CONTROL_IMAGE_USERD_ABI')
    S.require(struct.unpack_from('<II', raw, 0x88) == (0, 0), 'CONTROL_IMAGE_NOT_EMPTY')
    return raw


def _spans(raw, userd):
    # Canonical USERD extent is already admitted, never caller-selected masking.
    rows = []
    if userd.offset > 0:
        rows.append(ImageSpan(0, raw[:userd.offset]))
    end = userd.offset + userd.reserved
    if end < len(raw):
        rows.append(ImageSpan(end, raw[end:]))
    return tuple(rows)


def _assemble(inputs, push, userd):
    """Internal pure operation; public entrypoints admit all inputs first."""
    layout = inputs.layout
    slots = {s.label: s for s in layout.slots}
    raw = bytearray(b'\xa7') * layout.arena.allocation_size

    def put(slot, data, zero_pad=True):
        S.require(type(data) is bytes and len(data) == slot.used
                  and 0 <= slot.offset <= len(raw)
                  and slot.used <= slot.reserved <= len(raw)-slot.offset,
                  'CONTROL_IMAGE_WRITE_SPAN')
        # Memoryview assignment cannot resize the destination.
        memoryview(raw)[slot.offset:slot.offset+slot.used] = data
        if zero_pad:
            start = slot.offset + slot.used
            memoryview(raw)[start:slot.offset+slot.reserved] = bytes(slot.reserved-slot.used)

    kinds = ('affine-u32',) if type(inputs.workload) is P.AI.D.AffineLayout else P.W.STAGES
    count = 1 if type(inputs.workload) is P.AI.D.AffineLayout else 40
    for kind, data in zip(kinds, inputs.code_images):
        put(slots['code:'+kind], data)
    for i in range(count):
        put(slots['cb:'+str(i)], inputs.cb_images[i])
        put(slots['qmd:'+str(i)], inputs.qmd_images[i])
    put(slots['push'], push)
    entry = G.image(slots['push'].gpu_address, len(push))
    put(slots['ring'], entry + bytes(56))
    put(slots['completion'], bytes(4), zero_pad=False)
    put(slots['userd'], userd)
    result = bytes(raw)
    return ModelControlImage(result, _spans(result, slots['userd']))


def compose(inputs, prefix, signal, expected_userd):
    userd = _userd(expected_userd)
    push = P.image(inputs, prefix, signal)
    return _assemble(inputs, push, userd)


def verify(candidate, inputs, prefix, signal, expected_userd):
    userd = _userd(expected_userd)
    S.require(type(candidate) is ModelControlImage and type(candidate.raw) is bytes
              and type(candidate.spans) is tuple, 'CONTROL_IMAGE_TYPE')
    S.require(all(type(s) is ImageSpan and type(s.offset) is int
                  and type(s.data) is bytes for s in candidate.spans), 'CONTROL_IMAGE_SPANS_TYPE')
    S.require(type(inputs) is P.Inputs and type(inputs.layout) is P.L.ControlLayout,
              'CONTROL_IMAGE_INPUT_TYPE')
    layout = inputs.layout
    P.L.references(layout, inputs.workload, layout.arena)
    S.require(len(candidate.raw) == layout.arena.allocation_size, 'CONTROL_IMAGE_SIZE')
    slots = {s.label: s for s in layout.slots}
    p = slots['push']; r = slots['ring']
    push = candidate.raw[p.offset:p.offset+p.used]
    P.verify(push, inputs, prefix, signal)
    G.verify(candidate.raw[r.offset:r.offset+8], p.gpu_address, len(push))
    expected = _assemble(inputs, push, userd)
    S.require(candidate.raw == expected.raw, 'CONTROL_IMAGE_BYTES')
    S.require(candidate.spans == expected.spans, 'CONTROL_IMAGE_SPANS')
    return candidate
