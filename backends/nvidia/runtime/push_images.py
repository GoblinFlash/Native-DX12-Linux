"""Original P1 CPU image admission; no live resource or completion certificate.

PUSH-PROFILE-BOUNDARY defines the sequence and its hardware UNKNOWNs. Only
declarations and reviewed team image builders are used, not vendor encoders.
decode() checks framing only; verify() checks the complete bound P1 sequence.
"""
from dataclasses import dataclass
import struct

import shader_info_check as S
import sort_workload as W
import control_layout as L
import cb0_images as C
import qmd_images as Q
import push_bits as B
import affine_images as AI


@dataclass(frozen=True)
class Inputs:
    workload: W.Workload
    layout: L.ControlLayout
    placements: tuple
    code_images: tuple
    cb_images: tuple
    qmd_images: tuple


# HW93: observed Ada profile, not a header-defined universal window size.
SHADER_WINDOWS = ((0xfe000000, 0x1000000), (0xff000000, 0x1000000))


def check_window_spans(spans):
    for base, size in spans:
        S.require(type(base) is int and type(size) is int and base >= 0 and size > 0,
                  'P1_WINDOW_SPAN')
        S.require(all(base + size <= start or start + length <= base
                      for start, length in SHADER_WINDOWS), 'P1_WINDOW_ALIAS')


def byte_length(prefix):
    S.require(type(prefix) is int and 1 <= prefix <= 40, 'P1_PREFIX')
    return 8 * (21 + 8 * prefix)


def _admit(inputs, prefix, signal):
    length = byte_length(prefix)
    S.require(type(signal) is int and 0 < signal < 1 << 32, 'P1_SIGNAL')
    S.require(type(inputs) is Inputs, 'P1_INPUT_TYPE')
    S.require(type(inputs.layout) is L.ControlLayout, 'P1_LAYOUT_TYPE')
    layout, work = inputs.layout, inputs.workload
    if type(work) is AI.D.AffineLayout:
        S.require(type(prefix) is int and prefix == 1, 'AFFINE_PREFIX')
        refs = L.references(layout, work, layout.arena)
        S.require(layout.arena.push_bytes == length, 'P1_PUSH_LENGTH')
        for images in (inputs.code_images, inputs.cb_images, inputs.qmd_images):
            S.require(type(images) is tuple and len(images) == 1
                      and type(images[0]) is bytes, 'P1_IMAGE_SET')
        code = AI.program()[0]
        S.require(inputs.code_images == (code,), 'P1_CODE_IMAGE')
        S.require(inputs.cb_images == (AI.cb_image(work, inputs.placements),), 'AFFINE_CB_IMAGE')
        _, _, c, cb, qmd = refs[0]
        S.require(inputs.qmd_images == (AI.qmd_image(work, c.gpu_address, cb.gpu_address),),
                  'AFFINE_QMD_IMAGE')
        S.require((c.used, cb.used, qmd.used) == (len(code), 128, 256), 'P1_SLOT_IMAGE_SIZE')
        base, size = layout.arena.gpu_base, layout.arena.allocation_size
        S.require(all(base + size <= p.gpu_base or p.gpu_base + p.allocation_size <= base
                      for p in inputs.placements), 'P1_CONTROL_DATA_ALIAS')
        check_window_spans(((base, size),) + tuple((p.gpu_base, p.allocation_size) for p in inputs.placements))
        end = next(s for s in layout.slots if s.label == 'completion')
        return refs, end.gpu_address
    refs = L.references(layout, work, layout.arena)
    S.require(layout.arena.push_bytes == length, 'P1_PUSH_LENGTH')
    for images, count in ((inputs.code_images, 5), (inputs.cb_images, 40),
                          (inputs.qmd_images, 40)):
        S.require(type(images) is tuple and len(images) == count
                  and all(type(raw) is bytes for raw in images), 'P1_IMAGE_SET')
    inventory = S.parse(S.pinned((S.HERE.parent / 'data' / 'parallel_sort_programs.json'), S.INVENTORY_SHA))
    for kind, raw in zip(W.STAGES, inputs.code_images):
        entry = inventory['programs'][kind]['artifacts']['bin']
        expected = S.pinned(entry['path'], entry['sha256'], entry['size'], entry['mode'])
        S.require(raw == expected, 'P1_CODE_IMAGE')
    for i, kind, code, cb, qmd in refs:
        C.verify(inputs.cb_images[i], work, i, inputs.placements)
        Q.verify(inputs.qmd_images[i], kind, work.stages[i].grid,
                 code.gpu_address, cb.gpu_address)
        S.require(code.used == len(inputs.code_images[W.STAGES.index(kind)])
                  and cb.used == 128 and qmd.used == 256, 'P1_SLOT_IMAGE_SIZE')
    # CB admission established placement types/ranges before this comparison.
    base, size = layout.arena.gpu_base, layout.arena.allocation_size
    S.require(all(base + size <= p.gpu_base or p.gpu_base + p.allocation_size <= base
                  for p in inputs.placements), 'P1_CONTROL_DATA_ALIAS')
    check_window_spans(((base, size),) + tuple((p.gpu_base, p.allocation_size) for p in inputs.placements))
    slots = {s.label: s for s in layout.slots}
    end = slots['completion']
    S.require(end.used == 4 and end.reserved == 256 and end.gpu_address % 256 == 0
              and 0 < end.gpu_address < 1 << 40
              and end.offset + 256 <= size, 'P1_COMPLETION_SPAN')
    return refs, end.gpu_address


def _value(table, name):
    row = table[name]
    S.require(row['kind'] == 'value', 'P1_DECLARATION_VALUE')
    return row['value']


def _field(table, name, value):
    row = table[name]
    S.require(row['kind'] == 'field', 'P1_DECLARATION_FIELD')
    S.require(type(value) is int and 0 <= value < 1 << row['width'], 'P1_FIELD_VALUE')
    return value << row['lo']


def _packet(table, method, value):
    S.require(type(method) is int and 0 <= method <= 0x3ffc and method % 4 == 0,
              'P1_METHOD')
    S.require(type(value) is int and 0 <= value < 1 << 32, 'P1_WORD')
    # HW92: compute methods use SC1; C56F host methods retain SC0.
    compute = ('NVC9C0_SET_OBJECT', 'NVC9C0_WAIT_FOR_IDLE', 'NVC9C0_INVALIDATE_SHADER_CACHES',
               'NVC9C0_INVALIDATE_SKED_CACHES', 'NVC9C0_SEND_PCAS_A', 'NVC9C0_SEND_SIGNALING_PCAS2_B',
               'NVC9C0_SET_SHADER_SHARED_MEMORY_WINDOW_A', 'NVC9C0_SET_SHADER_SHARED_MEMORY_WINDOW_B', 'NVC9C0_SET_SHADER_LOCAL_MEMORY_WINDOW_A', 'NVC9C0_SET_SHADER_LOCAL_MEMORY_WINDOW_B')
    host = tuple(_value(table, 'NVC56F_' + name) for name in
                 ('MEM_OP_A', 'MEM_OP_B', 'MEM_OP_C', 'MEM_OP_D', 'SEM_ADDR_LO',
                  'SEM_ADDR_HI', 'SEM_PAYLOAD_LO', 'SEM_PAYLOAD_HI', 'SEM_EXECUTE'))
    S.require(not set(host) & {_value(table, name) for name in compute}, 'P1_CLASS_ADDRESS_ALIAS')
    subchannel = 1 if method in tuple(_value(table, name) for name in compute) else 0
    header = (_field(table, 'NVC56F_DMA_INCR_ADDRESS', method // 4)
              | _field(table, 'NVC56F_DMA_INCR_COUNT', 1)
              | _field(table, 'NVC56F_DMA_INCR_SUBCHANNEL', subchannel)
              | _field(table, 'NVC56F_DMA_INCR_OPCODE',
                       _value(table, 'NVC56F_DMA_INCR_OPCODE_VALUE')))
    return struct.pack('<II', header, value)


def _sequence(table, refs, completion, prefix, signal):
    # All fields not selected here remain zero, including timestamp/64-bit SEM.
    def val(name): return _value(table, name)
    def put(name, value): return _field(table, name, value)
    def pair(name, value): return (val(name), value)
    def membar(operation):
        return (pair('NVC56F_MEM_OP_A', 0), pair('NVC56F_MEM_OP_B', 0),
                pair('NVC56F_MEM_OP_C', put('NVC56F_MEM_OP_C_MEMBAR_TYPE',
                                           val('NVC56F_MEM_OP_C_MEMBAR_TYPE_SYS_MEMBAR'))),
                pair('NVC56F_MEM_OP_D', put('NVC56F_MEM_OP_D_OPERATION', val(operation))))
    def shader(flags):
        word = 0
        for flag in flags:
            name = 'NVC9C0_INVALIDATE_SHADER_CACHES_' + flag
            word |= put(name, val(name + '_TRUE'))
        return pair('NVC9C0_INVALIDATE_SHADER_CACHES', word)
    idle = pair('NVC9C0_WAIT_FOR_IDLE', 0)
    barrier = membar('NVC56F_MEM_OP_D_OPERATION_MEMBAR')
    result = [pair('NVC9C0_SET_OBJECT', put('NVC9C0_SET_OBJECT_CLASS_ID', val('ADA_COMPUTE_A')))]
    for kind, (base, _) in zip(('SHARED', 'LOCAL'), SHADER_WINDOWS):
        name = 'NVC9C0_SET_SHADER_' + kind + '_MEMORY_WINDOW_'
        result.extend((pair(name + 'A', put(name + 'A_BASE_ADDRESS_UPPER', base >> 32)),
                       pair(name + 'B', put(name + 'B_BASE_ADDRESS', base & 0xffffffff))))
    result.append(idle)
    result.extend(barrier)
    result.extend(membar('NVC56F_MEM_OP_D_OPERATION_L2_SYSMEM_INVALIDATE'))
    result.extend((shader(('INSTRUCTION', 'DATA', 'CONSTANT')),
                   pair('NVC9C0_INVALIDATE_SKED_CACHES', 0)))
    for i in range(prefix):
        qmd = refs[i][4].gpu_address
        S.require(qmd % 256 == 0 and 0 < qmd < 1 << 40, 'P1_QMD_ADDRESS')
        result.append(pair('NVC9C0_SEND_PCAS_A', put('NVC9C0_SEND_PCAS_A_QMD_ADDRESS_SHIFTED8', qmd >> 8)))
        result.append(pair('NVC9C0_SEND_SIGNALING_PCAS2_B',
                           put('NVC9C0_SEND_SIGNALING_PCAS2_B_PCAS_ACTION',
                               val('NVC9C0_SEND_SIGNALING_PCAS2_B_PCAS_ACTION_INVALIDATE_COPY_SCHEDULE'))))
        result.extend((idle, shader(('DATA', 'CONSTANT', 'FLUSH_DATA'))))
        result.extend(barrier)
    sem = (put('NVC56F_SEM_EXECUTE_OPERATION', val('NVC56F_SEM_EXECUTE_OPERATION_RELEASE'))
           | put('NVC56F_SEM_EXECUTE_RELEASE_WFI', val('NVC56F_SEM_EXECUTE_RELEASE_WFI_EN'))
           | put('NVC56F_SEM_EXECUTE_PAYLOAD_SIZE', val('NVC56F_SEM_EXECUTE_PAYLOAD_SIZE_32BIT'))
           | put('NVC56F_SEM_EXECUTE_RELEASE_TIMESTAMP', val('NVC56F_SEM_EXECUTE_RELEASE_TIMESTAMP_DIS')))
    result.extend((pair('NVC56F_SEM_ADDR_LO', put('NVC56F_SEM_ADDR_LO_OFFSET', (completion & 0xffffffff) >> 2)),
                   pair('NVC56F_SEM_ADDR_HI', put('NVC56F_SEM_ADDR_HI_OFFSET', completion >> 32)),
                   pair('NVC56F_SEM_PAYLOAD_LO', signal), pair('NVC56F_SEM_PAYLOAD_HI', 0),
                   pair('NVC56F_SEM_EXECUTE', sem)))
    S.require(len(result) == 21 + 8 * prefix, 'P1_METHOD_COUNT')
    return tuple(result)


def image(inputs, prefix, signal):
    refs, completion = _admit(inputs, prefix, signal)
    if type(inputs.workload) is AI.D.AffineLayout:
        return AI.push_image(refs[0][4].gpu_address, completion, signal)
    table = B.declarations()
    return b''.join(_packet(table, *row) for row in _sequence(table, refs, completion, prefix, signal))


def decode(raw):
    """Framing only. Does NOT admit an executable command sequence."""
    S.require(type(raw) is bytes and 0 < len(raw) <= 2728 and len(raw) % 8 == 0, 'P1_IMAGE_SIZE')
    table = B.declarations()
    rows = []
    for header, value in struct.iter_unpack('<II', raw):
        field = table['NVC56F_DMA_INCR_ADDRESS']
        method = ((header >> field['lo']) & ((1 << field['width']) - 1)) * 4
        S.require(_packet(table, method, value) == struct.pack('<II', header, value), 'P1_PACKET_HEADER')
        rows.append((method, value))
    return tuple(rows)


def verify(raw, inputs, prefix, signal):
    # Reject framing/size first; no returned object grants hardware authority.
    rows = decode(raw)
    S.require(len(raw) == byte_length(prefix), 'P1_IMAGE_LENGTH')
    refs, completion = _admit(inputs, prefix, signal)
    table = B.declarations()
    expected = _sequence(table, refs, completion, prefix, signal)
    S.require(rows == expected, 'P1_SEQUENCE')
    S.require(raw == b''.join(_packet(table, *row) for row in expected), 'P1_FULL_IMAGE')
    return raw
