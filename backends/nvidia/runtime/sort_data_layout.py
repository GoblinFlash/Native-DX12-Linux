"""Original L2 layout policy over the reviewed team-authored scope-B oracle.

No old host planner or shader body is a source. This defines expected images,
not stage descriptor lengths, packet admission, or observed GPU correctness.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import stat
import sys
import types

from replacement_inputs import arena as A

ORACLE_SHA = '4efff6756e877af83034baf228c6fb59f35a5ec1724fc5c772d12a26a3c05f81'
ORACLE_PATH = (Path(__file__).resolve().parent.parent / 'reference/parallel_sort.py')


def _oracle():
    A.require(stat.S_ISREG(ORACLE_PATH.lstat().st_mode), 'DATA_ORACLE_FILE')
    raw = ORACLE_PATH.read_bytes()
    A.require(hashlib.sha256(raw).hexdigest() == ORACLE_SHA, 'DATA_ORACLE_PIN')
    name = '_ndx_sort_data_oracle_' + ORACLE_SHA[:16]
    A.require(name not in sys.modules, 'DATA_ORACLE_PRELOAD')
    module = types.ModuleType(name)
    module.__file__ = str(ORACLE_PATH)
    sys.modules[name] = module
    try:
        exec(compile(raw, str(ORACLE_PATH), 'exec'), module.__dict__)
    except BaseException:
        del sys.modules[name]
        raise
    return module


B = _oracle()
ROLES = ('keys0', 'keys1', 'sum', 'reduce')
POISON = 0xD15EA5E5
TOTAL_LIMIT = 64 * 1024 * 1024


@dataclass(frozen=True)
class DataLayout:
    keys: tuple
    max_groups: int
    buffer_words: int
    payload_offset_words: int = 64
    poison_word: int = POISON

    def validate(self):
        A.require(type(self.keys) is tuple and type(self.max_groups) is int
                  and (len(self.keys), self.max_groups) in ((515, 1), (1025, 800), (4096, 4)),
                  'DATA_CASE')
        A.require(all(type(k) is int and 0 <= k <= 0xffffffff for k in self.keys), 'DATA_KEYS')
        geo = B.geometry(len(self.keys), self.max_groups)
        live = max(geo.keys, 16 * geo.groups, 16)
        # DR-N1: oracle.bind alone admits a zero offset or no trailing guard.
        A.require(type(self.buffer_words) is int and type(self.payload_offset_words) is int
                  and self.payload_offset_words == 64
                  and self.buffer_words - (64 + live) >= 64, 'DATA_LAYOUT_GUARDS')
        required = ((256 + 4 * live + 256 + 4095) // 4096) * 4096
        A.require(self.buffer_words * 4 == required, 'DATA_LAYOUT_SIZE')
        A.require(type(self.poison_word) is int and self.poison_word == POISON, 'DATA_POISON')
        layout = B.BufferLayout(self.buffer_words, 64, POISON, geo.keys, 16 * geo.groups, 16)
        B.bind(self.keys, geo, layout)
        return geo, layout

    @property
    def logical_bytes(self):
        self.validate()
        return self.buffer_words * 4

    def initial_images(self, allocation_sizes):
        geo, layout = self.validate()
        A.require(type(allocation_sizes) is tuple and len(allocation_sizes) == 4
                  and all(type(n) is int and n >= self.buffer_words * 4 and n % 4096 == 0
                          for n in allocation_sizes)
                  and sum(allocation_sizes) <= TOTAL_LIMIT, 'DATA_IMAGE_SIZES')
        logical = B.bind(self.keys, geo, layout)
        return tuple(B.pack(logical[role]) + POISON.to_bytes(4, 'little') *
                     ((size - self.buffer_words * 4) // 4)
                     for role, size in zip(ROLES, allocation_sizes))


def layout_for(keys, max_groups):
    A.require(type(keys) is tuple and type(max_groups) is int
              and (len(keys), max_groups) in ((515, 1), (1025, 800), (4096, 4)), 'DATA_CASE')
    geo = B.geometry(len(keys), max_groups)
    words = (((256 + 4 * max(len(keys), 16 * geo.groups, 16) + 256 + 4095) // 4096) * 4096) // 4
    result = DataLayout(keys, max_groups, words)
    result.validate()
    return result
