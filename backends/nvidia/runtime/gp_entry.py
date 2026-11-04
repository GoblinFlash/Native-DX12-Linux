"""Original CPU GPFIFO address entry from header fields and C2.1 PROFILE.

Bytes only; no ring publication, live resource admission or hardware claim.
"""
import struct
from replacement_inputs import arena as A


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _fields():
    abi = A.Abi()
    return tuple((abi.const(name + '_SHIFT'), abi.const(name + '_MASK'))
                 for name in ('NVC56F_GP_ENTRY0_GET', 'NVC56F_GP_ENTRY1_GET_HI',
                              'NVC56F_GP_ENTRY1_LENGTH'))


def _request(address, byte_length):
    require(type(address) is int and type(byte_length) is int, 'GP_INPUT_TYPE')
    require(0 < address < 1 << 40 and address % 4 == 0, 'GP_ADDRESS')
    require(0 < byte_length <= ((1 << 21)-1)*4 and byte_length % 4 == 0, 'GP_LENGTH')
    require(byte_length <= (1 << 40)-address, 'GP_END')


def image(address, byte_length):
    _request(address, byte_length)
    (ls, lm), (hs, hm), (ns, nm) = _fields()
    low = A.field_set((address >> ls) & lm, ls, lm)
    high = A.field_set(address >> 32, hs, hm)
    length = A.field_set(byte_length // 4, ns, nm)
    return struct.pack('<II', low, high | length)


def decode(raw):
    require(type(raw) is bytes and len(raw) == 8, 'GP_IMAGE_TYPE_SIZE')
    low, high = struct.unpack('<II', raw)
    (ls, lm), (hs, hm), (ns, nm) = _fields()
    require(low & ~(lm << ls) == 0
            and high & ~((hm << hs) | (nm << ns)) == 0, 'GP_UNSELECTED_BITS')
    address = (A.field_value(low, ls, lm) << ls) | (A.field_value(high, hs, hm) << 32)
    byte_length = A.field_value(high, ns, nm) * 4
    _request(address, byte_length)
    return address, byte_length


def verify(raw, address, byte_length):
    _request(address, byte_length)
    require(decode(raw) == (address, byte_length), 'GP_TARGET_MISMATCH')
    require(raw == image(address, byte_length), 'GP_IMAGE_MISMATCH')
    return raw
