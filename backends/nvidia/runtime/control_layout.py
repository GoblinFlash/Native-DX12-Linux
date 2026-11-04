"""Original CPU-only control placement. No upload, live ownership or publication.

See CONTROL-LAYOUT-BOUNDARY and CONTROL-LAYOUT-PROFILE (read-ahead UNKNOWN).
"""
from dataclasses import dataclass
import shader_info_check as S
import qmd_images as Q
import sort_workload as W
import affine_data as AD
import affine_images as AI


@dataclass(frozen=True)
class ModelArena:
    gpu_base: int
    allocation_size: int
    ring_offset: int
    userd_offset: int
    push_bytes: int


@dataclass(frozen=True)
class Slot:
    label: str
    offset: int
    used: int
    reserved: int
    gpu_address: int


@dataclass(frozen=True)
class ControlLayout:
    arena: ModelArena
    slots: tuple


def _geometry(arena):
    S.require(type(arena) is ModelArena
              and all(type(v) is int for v in vars(arena).values()), 'CONTROL_MODEL_TYPE')
    b, n = arena.gpu_base, arena.allocation_size
    S.require(0 < b < 1 << 40 and b % 4096 == 0
              and 0 < n <= 64*1024*1024 and n % 4096 == 0
              and n <= (1 << 40)-b, 'CONTROL_ARENA_SPAN')
    r, u = arena.ring_offset, arena.userd_offset
    S.require(0 <= r <= n-64 and (b+r) % 8 == 0, 'CONTROL_RING')
    S.require(0 <= u <= n-512 and u % 512 == 0, 'CONTROL_USERD')
    S.require(r+64 <= u or u+512 <= r, 'CONTROL_FIXED_ALIAS')
    S.require(0 < arena.push_bytes <= ((1 << 21)-1)*4
              and arena.push_bytes % 4 == 0, 'CONTROL_PUSH_LENGTH')


def _round256(n):
    return (n+255)//256*256


def _check_slots(arena, slots):
    S.require(type(slots) is tuple and len(slots) in (7, 89), 'CONTROL_SLOT_SET')
    spans, labels = [], set()
    for slot in slots:
        S.require(type(slot) is Slot and type(slot.label) is str
                  and all(type(v) is int for v in (slot.offset, slot.used, slot.reserved, slot.gpu_address)),
                  'CONTROL_SLOT_TYPE')
        S.require(slot.label not in labels, 'CONTROL_SLOT_DUPLICATE')
        labels.add(slot.label)
        S.require(0 <= slot.offset <= arena.allocation_size
                  and 0 < slot.used <= slot.reserved <= arena.allocation_size-slot.offset
                  and slot.gpu_address == arena.gpu_base+slot.offset, 'CONTROL_SLOT_SPAN')
        if slot.label not in ('ring', 'userd'):
            S.require(slot.gpu_address % 256 == 0 and slot.reserved % 256 == 0,
                      'CONTROL_SLOT_ALIGNMENT')
        S.require(all(slot.offset+slot.reserved <= a or e <= slot.offset for a,e in spans),
                  'CONTROL_SLOT_ALIAS')
        spans.append((slot.offset, slot.offset+slot.reserved))


def plan(workload, arena):
    if type(workload) is AD.AffineLayout:
        workload.validate()
        _geometry(arena)
        S.require(arena.push_bytes == AI.PUSH_BYTES, 'AFFINE_PUSH_LENGTH')
        spec = AI.ControlSpec(arena.gpu_base, arena.allocation_size,
                              arena.ring_offset, arena.userd_offset)
        slots = tuple(Slot(s.label, s.offset, s.used, s.reserved, s.gpu_address)
                      for s in AI.control_plan(spec))
        _check_slots(arena, slots)
        return ControlLayout(arena, slots)
    S.require(type(workload) is W.Workload, 'CONTROL_WORKLOAD_TYPE')
    workload.validate()
    _geometry(arena)
    # Q.seed checks all pinned code/info/JSON/QMD bytes before yielding length.
    sizes = tuple(Q.seed(kind)[1] for kind in W.STAGES)
    S.require(all(type(n) is int and n > 0 for n in sizes), 'CONTROL_CODE_LENGTH')
    specs = [('code:'+kind, n) for kind,n in zip(W.STAGES, sizes)]
    specs += [('cb:'+str(i), 128) for i in range(40)]
    specs += [('qmd:'+str(i), 256) for i in range(40)]
    specs += [('push', arena.push_bytes), ('completion', 4)]
    slots = [Slot('ring', arena.ring_offset, 64, 64, arena.gpu_base+arena.ring_offset),
             Slot('userd', arena.userd_offset, 512, 512, arena.gpu_base+arena.userd_offset)]
    obstacles = sorted((s.offset, s.offset+s.reserved) for s in slots)
    cursor = 0
    for label, used in specs:
        reserved = _round256(used)
        cursor = _round256(cursor)
        skips = 0
        while True:
            collision = next(((a,e) for a,e in obstacles if cursor < e and a < cursor+reserved), None)
            if collision is None:
                break
            # Each forward skip passes one of the two fixed reservations.
            # Refuse a broken predicate/advance instead of spinning forever.
            S.require(skips < len(obstacles), 'CONTROL_SKIP_LIMIT')
            skips += 1
            cursor = _round256(collision[1])
        S.require(cursor <= arena.allocation_size and reserved <= arena.allocation_size-cursor,
                  'CONTROL_NO_FIT')
        slots.append(Slot(label, cursor, used, reserved, arena.gpu_base+cursor))
        cursor += reserved
    result = ControlLayout(arena, tuple(slots))
    _check_slots(arena, result.slots)
    return result


def verify(layout, workload, arena):
    S.require(type(layout) is ControlLayout and type(layout.arena) is ModelArena, 'CONTROL_LAYOUT_TYPE')
    _geometry(layout.arena)
    _check_slots(layout.arena, layout.slots)
    expected = plan(workload, arena)
    S.require(layout == expected, 'CONTROL_LAYOUT_MISMATCH')
    return layout


def references(layout, workload, arena):
    """Canonical stage/code/CB/QMD records only, never an execution certificate."""
    verify(layout, workload, arena)
    by_label = {s.label:s for s in layout.slots}
    if type(workload) is AD.AffineLayout:
        return ((0, 'affine-u32', by_label['code:affine-u32'], by_label['cb:0'], by_label['qmd:0']),)
    return tuple((stage.index, stage.kind, by_label['code:'+stage.kind],
                  by_label['cb:'+str(stage.index)], by_label['qmd:'+str(stage.index)])
                 for stage in workload.stages)
