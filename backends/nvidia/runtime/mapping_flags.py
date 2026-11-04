"""Pure M1 flag profile, not connected to the native backend.

Header constants describe encodings. The admitted pairs are experimental
PROFILE choices from MAP-PROFILE-RESOLUTION.md, not GPU-qualified behavior.
No driver implementation is copied or adapted here.
"""
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

SUPPLEMENT_SHA = '04e8515b8891eba7f0d2653293152096f3a751945c667832bc49029251e2fe92'
ABI_SHA = '0fa893036bc32828bd96bb29659ea57caecd879a67160686eff53de610b21a07'
FIELDS = MappingProxyType({
    'ACCESS': ('READ_WRITE', 'READ_ONLY', 'WRITE_ONLY'),
    'PERSISTENT': ('DISABLE', 'ENABLE'),
    'SKIP_SIZE_CHECK': ('DISABLE', 'ENABLE'),
    'MEM_SPACE': ('CLIENT', 'USER'),
    'MAPPING': ('DEFAULT', 'DIRECT', 'REFLECTED'),
    'FIFO_MAPPING': ('DEFAULT', 'ENABLE'),
    'MAP_FIXED': ('DISABLE', 'ENABLE'),
    'RESERVE_ON_UNMAP': ('DISABLE', 'ENABLE'),
    'BUS': ('DEFAULT', 'COHERENT_LINK', 'PCIE'),
    'OS_DESCRIPTOR': ('DISABLE', 'ENABLE'),
    'CACHING_TYPE': ('CACHED', 'UNCACHED', 'WRITECOMBINED', 'WRITEBACK', 'DEFAULT', 'UNCACHED_WEAK'),
    'ALLOW_MAPPING_ON_HCC': ('NO', 'YES'),
})
MAP_CHOICES = MappingProxyType({
    'ACCESS': 'READ_WRITE', 'PERSISTENT': 'DISABLE',
    'SKIP_SIZE_CHECK': 'DISABLE', 'MEM_SPACE': 'CLIENT',
    'MAPPING': 'DEFAULT', 'FIFO_MAPPING': 'DEFAULT', 'MAP_FIXED': 'ENABLE',
    'RESERVE_ON_UNMAP': 'DISABLE', 'BUS': 'DEFAULT',
    'OS_DESCRIPTOR': 'DISABLE', 'CACHING_TYPE': 'CACHED', 'ALLOW_MAPPING_ON_HCC': 'NO',
})
PREFIX = 'NVOS33_FLAGS_'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def check_overlap(constants, existing):
    overlap = sorted(set(constants) & set(existing))
    require(bool(overlap), 'ABI_OVERLAP_EMPTY')
    for name in overlap:
        require(type(existing[name]) is int and constants[name] == existing[name],
                'ABI_OVERLAP:' + name)
    return tuple(overlap)


class Flags:
    def __init__(self, supplement_bytes, abi_bytes):
        require(hashlib.sha256(supplement_bytes).hexdigest() == SUPPLEMENT_SHA, 'SUPPLEMENT_PIN')
        require(hashlib.sha256(abi_bytes).hexdigest() == ABI_SHA, 'ABI_PIN')
        supplement = json.loads(supplement_bytes)
        require(set(supplement) == {'schema', 'constants'} and
                supplement['schema'] == 'mapping-flags-615.v1', 'SUPPLEMENT_SCHEMA')
        constants = supplement['constants']
        names = {PREFIX + field + '_' + name for field, values in FIELDS.items()
                 for name in ('SHIFT', 'MASK', 'SHIFTMASK') + values}
        require(set(constants) == names, 'SUPPLEMENT_NAMES')
        require(all(type(v) is int and 0 <= v <= 0xffffffff for v in constants.values()),
                'SUPPLEMENT_U32')
        self.constants = MappingProxyType(constants)
        self.overlap = check_overlap(constants, json.loads(abi_bytes)['constants'])
        self.output_mask = self.shiftmask('MAPPING') | self.shiftmask('CACHING_TYPE')

    def shift(self, field):
        return self.constants[PREFIX + field + '_SHIFT']

    def mask(self, field):
        """Unshifted width mask, as consumed by frozen Arena.field_value/set."""
        return self.constants[PREFIX + field + '_MASK']

    def shiftmask(self, field):
        return self.constants[PREFIX + field + '_SHIFTMASK']

    def value(self, field, name):
        require(field in FIELDS and name in FIELDS[field], 'FLAG_NAME')
        return self.constants[PREFIX + field + '_' + name]

    def encode(self, choices):
        require(set(choices) == set(FIELDS), 'FLAG_FIELD_SET')
        result = 0
        for field, name in choices.items():
            result |= self.value(field, name) << self.shift(field)
        return result

    def request(self, operation):
        require(operation in ('map', 'unmap'), 'FLAG_OPERATION')
        choices = dict(MAP_CHOICES)
        if operation == 'unmap':
            choices['MAP_FIXED'] = 'DISABLE'
        return self.encode(choices)

    def check_request(self, operation, word):
        self.u32(word)
        require(word == self.request(operation), 'REQUEST_FLAGS')

    @staticmethod
    def u32(word):
        require(type(word) is int and 0 <= word <= 0xffffffff, 'FLAGS_U32')

    def check_reply(self, profile, word):
        require(profile in ('sysmem', 'usermode'), 'MAP_CLASS_PROFILE')
        self.u32(word)
        require((word & ~self.output_mask) == (self.request('map') & ~self.output_mask),
                'OUTPUT_UNCHANGED_FIELDS')
        pair = {}
        for field in ('MAPPING', 'CACHING_TYPE'):
            value = (word >> self.shift(field)) & self.mask(field)
            require(value in {self.value(field, name) for name in FIELDS[field]},
                    'OUTPUT_UNDEFINED:' + field)
            pair[field] = value
        wanted_mapping = 'DIRECT' if profile == 'sysmem' else 'DEFAULT'
        require(pair['MAPPING'] == self.value('MAPPING', wanted_mapping) and
                pair['CACHING_TYPE'] == self.value('CACHING_TYPE', 'DEFAULT'),
                'OUTPUT_PROFILE_PAIR')


def load():
    here = Path(__file__).resolve().parent
    frozen = here.parent / 'abi/abi.json'
    return Flags((here.parent / 'data/mapping_flags.json').read_bytes(), frozen.read_bytes())
