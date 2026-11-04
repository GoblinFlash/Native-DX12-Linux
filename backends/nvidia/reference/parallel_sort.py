"""Scope-B oracle for the FidelityFX Parallel Sort workload: expected buffer contents per prefix, derived from
CONTRACT_B.md and SOURCE_LEDGER.md (L-B1, L-B2-DOC: the AMD "FidelityFX - Parallel Sort" v1.1 slides, and the
header #define constants). Written from those documents and from the sorting-problem definition.

Not a clean-room artefact: the author has seen earlier implementations. No FFX function body, no 012/015
oracle and no archived GPU bytes were used as a template or as a source of expected values. Scope: cases whose
block count divides evenly over the thread groups (515/1, 1025/800). A case that needs the additional-block rule
(U1 in CONTRACT_B) is refused, not guessed.

Conventions used (ledger citations):
  block         = 128 threads * 4 elements = 512 keys                 (slide 11; header #define constants)
  pass          = 4-bit digit, 8 passes over u32, LSD, stable           (L-B1 problem definition)
  SumTable      = count[bin][group] stored bin-major: index bin*G+g     (slide 12)
  ReduceTable   = per-bin totals sum over groups                        (slide 13)
  scan          = exclusive prefix, first element 0                     (slide 14)
  scanadd       = per bin: exclusive prefix over groups + bin offset    (slide 15)
  scatter       = stable placement of this group's keys at the offsets  (slide 16)
Everything about where buffers live (offsets in the BO, poison tails) is an input to this module, not an FFX
rule: callers supply a BufferLayout (CONTRACT_B L2, our own contract).
"""
from dataclasses import dataclass
import struct

THREADS = 128
ELEMENTS_PER_THREAD = 4
BLOCK = THREADS * ELEMENTS_PER_THREAD  # 512
BINS = 16
DIGIT_BITS = 4
PASSES = 32 // DIGIT_BITS  # 8
STAGES = ('count', 'reduce', 'scan', 'scanadd', 'scatter')
U32 = 0xffffffff


class Refused(ValueError):
    """The requested case needs a convention this oracle does not define (CONTRACT_B U1/U2)."""


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


# ----------------------------------------------------------------------------- dispatch geometry

@dataclass(frozen=True)
class Geometry:
    """Work split for one pass. Derived from: blocks = ceil(keys/BLOCK); groups = min(max_groups, blocks)
    (slide 11: "Each threadgroup will sort 1 or more blocks"); the remainder rule is U1 and refused."""
    keys: int
    groups: int
    blocks: int
    blocks_per_group: int

    @property
    def scan_values(self):
        # One reduced count per bin when every bin fits one reduce group (U2 excluded below).
        return BINS

    def group_key_ranges(self):
        """[start, end) key index per group: contiguous, block-aligned, in group order."""
        out, start = [], 0
        for _ in range(self.groups):
            end = min(start + self.blocks_per_group * BLOCK, self.keys)
            out.append((start, end))
            start = end
        require(start == self.keys, 'GEOMETRY_PARTITION')
        return out


def geometry(keys, max_groups):
    require(type(keys) is int and keys > 0 and type(max_groups) is int and max_groups > 0, 'GEOMETRY_ARGS')
    blocks = (keys + BLOCK - 1) // BLOCK
    groups = min(max_groups, blocks)
    if blocks % groups:
        raise Refused('U1_ADDITIONAL_BLOCK_ASSIGNMENT: blocks=%d groups=%d' % (blocks, groups))
    if groups > BLOCK:
        raise Refused('U2_MULTI_CHUNK_REDUCE: groups=%d' % groups)
    return Geometry(keys, groups, blocks, blocks // groups)


# ----------------------------------------------------------------------------- pass mathematics (L-B1/L-B2)

def digit(key, pass_index):
    return (key >> (DIGIT_BITS * pass_index)) & (BINS - 1)


def count_table(keys, geo, pass_index):
    """SumTable after Count: bin-major, index bin*G+g (slide 12)."""
    table = [0] * (BINS * geo.groups)
    for g, (a, b) in enumerate(geo.group_key_ranges()):
        for k in keys[a:b]:
            table[digit(k, pass_index) * geo.groups + g] += 1
    return table


def reduce_table(sum_table, geo):
    """ReduceTable after ReduceCount: one total per bin (slide 13)."""
    g = geo.groups
    return [sum(sum_table[b * g:(b + 1) * g]) for b in range(BINS)]


def exclusive_scan(values):
    """Slide 14: first element 0, then running sums."""
    out, acc = [], 0
    for v in values:
        out.append(acc)
        acc += v
    return out


def scan_add_table(sum_table, bin_offsets, geo):
    """SumTable after ScanAdd: per bin, exclusive prefix over groups plus that bin's global offset (slide 15)."""
    g = geo.groups
    out = []
    for b in range(BINS):
        out.extend(bin_offsets[b] + x for x in exclusive_scan(sum_table[b * g:(b + 1) * g]))
    return out


def scatter(keys, geo, pass_index, offsets):
    """Stable placement (slide 16; L-B1 stability). offsets = SumTable after ScanAdd.
    Every write must land inside [0, len(keys)) exactly once; any other offset table is refused."""
    require(len(offsets) == BINS * geo.groups and all(type(o) is int and 0 <= o <= len(keys) for o in offsets),
            'SCATTER_OFFSETS')
    dst = [None] * len(keys)
    cursor = list(offsets)
    for g, (a, b) in enumerate(geo.group_key_ranges()):
        for k in keys[a:b]:
            idx = digit(k, pass_index) * geo.groups + g
            pos = cursor[idx]
            require(0 <= pos < len(keys) and dst[pos] is None, 'SCATTER_COLLISION')
            dst[pos] = k
            cursor[idx] += 1
    require(all(x is not None for x in dst), 'SCATTER_COVERAGE')
    return dst


def sorted_by_low_bits(keys, bits):
    """L-B1 check value: stable sort by the low `bits` bits (bits=32 -> fully sorted)."""
    mask = U32 if bits >= 32 else (1 << bits) - 1
    return sorted(keys, key=lambda k: k & mask)


# ----------------------------------------------------------------------------- buffer layout (CONTRACT_B L2, ours)

@dataclass(frozen=True)
class BufferLayout:
    """Where each logical array lives inside its 32-bit-word buffer, and what the untouched words hold.
    This is our own contract (CONTRACT_B L2), supplied by the caller; the oracle never infers it."""
    buffer_words: int          # words per BO (all four BOs have the same size here)
    payload_offset_words: int  # first word of the live region in each BO
    poison_word: int           # value expected in every word outside the live region
    key_count: int
    sum_words: int             # live words of the sum/scanadd table (BINS*groups)
    reduce_words: int          # live words of the reduce/scan table (BINS)

    def image(self, name, live):
        """Full BO as words: poison everywhere, `live` written at payload_offset."""
        words = [self.poison_word] * self.buffer_words
        require(self.payload_offset_words + len(live) <= self.buffer_words, 'LAYOUT_OVERFLOW:' + name)
        words[self.payload_offset_words:self.payload_offset_words + len(live)] = live
        return words


def pack(words):
    return struct.pack('<%dI' % len(words), *words)


# ----------------------------------------------------------------------------- prefix state

def bind(keys, geo, layout, initial=None):
    """Central consistency check of the four inputs (B-F2). Returns validated starting images (words).
    The geometry must be reconstructible by geometry(): a hand-built Geometry cannot smuggle in the U1/U2 cases
    that geometry() refuses (residual B-F2)."""
    require(type(geo) is Geometry and all(type(x) is int for x in (geo.keys, geo.groups, geo.blocks, geo.blocks_per_group)),
            'BIND_GEOMETRY_TYPE')
    require(geo == geometry(geo.keys, geo.groups), 'BIND_GEOMETRY_UNRECONSTRUCTIBLE')
    require(type(keys) in (list, tuple) and len(keys) == geo.keys == layout.key_count, 'BIND_KEY_COUNT')
    require(all(type(k) is int and 0 <= k <= U32 for k in keys), 'BIND_KEY_U32')
    require(layout.sum_words == BINS * geo.groups and layout.reduce_words == geo.scan_values, 'BIND_TABLE_WORDS')
    require(type(layout.buffer_words) is int and type(layout.payload_offset_words) is int and
            layout.payload_offset_words >= 0 and layout.buffer_words > 0, 'BIND_LAYOUT_INTS')
    need_words = layout.payload_offset_words + max(layout.key_count, layout.sum_words, layout.reduce_words)
    require(need_words <= layout.buffer_words, 'BIND_LAYOUT_CAPACITY')
    if initial is None:
        return {'keys0': layout.image('keys0', list(keys)), 'keys1': layout.image('keys1', []),
                'sum': layout.image('sum', []), 'reduce': layout.image('reduce', [])}
    require(type(initial) is dict and set(initial) == {'keys0', 'keys1', 'sum', 'reduce'}, 'BIND_INITIAL_SET')
    state = {}
    for n, img in initial.items():
        require(len(img) == layout.buffer_words and all(type(w) is int and 0 <= w <= U32 for w in img),
                'BIND_INITIAL_IMAGE:' + n)
        state[n] = list(img)
    off = layout.payload_offset_words
    require(state['keys0'][off:off + layout.key_count] == list(keys), 'BIND_INITIAL_KEYS')
    return state


def expected_state(keys, geo, layout, prefix, initial=None):
    """Expected contents of keys0/keys1/sum/reduce after `prefix` kernel dispatches (prefix in 0..40).
    `initial` optionally supplies the four starting images (exactly layout.buffer_words words each) so untouched
    regions are compared against what was really there; otherwise poison per `layout`."""
    require(type(prefix) is int and 0 <= prefix <= PASSES * len(STAGES), 'PREFIX_RANGE')
    state = bind(keys, geo, layout, initial)
    off = layout.payload_offset_words

    def live(name, n):
        return state[name][off:off + n]

    def put(name, words):
        require(len(words) == {'keys0': layout.key_count, 'keys1': layout.key_count,
                               'sum': layout.sum_words, 'reduce': layout.reduce_words}[name], 'PUT_LENGTH:' + name)
        state[name][off:off + len(words)] = words
        require(len(state[name]) == layout.buffer_words, 'PUT_CAPACITY:' + name)

    for i in range(prefix):
        p, stage = divmod(i, len(STAGES))
        src, dst = ('keys0', 'keys1') if p % 2 == 0 else ('keys1', 'keys0')
        cur = live(src, layout.key_count)
        if stage == 0:
            put('sum', count_table(cur, geo, p))
        elif stage == 1:
            put('reduce', reduce_table(live('sum', layout.sum_words), geo))
        elif stage == 2:
            put('reduce', exclusive_scan(live('reduce', layout.reduce_words)))
        elif stage == 3:
            put('sum', scan_add_table(live('sum', layout.sum_words), live('reduce', layout.reduce_words), geo))
        else:
            put(dst, scatter(cur, geo, p, live('sum', layout.sum_words)))
    return state


def stage_of(prefix):
    """1-based prefix -> (pass_index, stage_name) of the kernel that completed it."""
    require(1 <= prefix <= PASSES * len(STAGES), 'PREFIX_RANGE')
    p, s = divmod(prefix - 1, len(STAGES))
    return p, STAGES[s]
