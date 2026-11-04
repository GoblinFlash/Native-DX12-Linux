"""Original affine value/image model only; not live allocation admission."""
from dataclasses import dataclass
import struct
from affine_reference import expected

ROLES = ('input', 'output', 'guard0', 'guard1')
POISON = 0xd15ea5e5
CASES = (1, 127, 128, 129, 515)


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


@dataclass(frozen=True)
class AffineLayout:
    values: tuple
    seed: int
    multiplier: int
    addend: int
    reserved: tuple = (0, 0, 0, 0)

    def validate(self):
        require(type(self) is AffineLayout, 'AFFINE_LAYOUT_TYPE')
        require(type(self.values) is tuple and len(self.values) in CASES,
                'AFFINE_DATA_CASE')
        require(all(type(x) is int and 0 <= x <= 0xffffffff
                    for x in (*self.values, self.seed, self.multiplier, self.addend)),
                'AFFINE_DATA_U32')
        require(type(self.reserved) is tuple and len(self.reserved) == 4
                and all(type(x) is int and x == 0 for x in self.reserved),
                'AFFINE_RESERVED')
        return self

    @property
    def params(self):
        self.validate()
        return (len(self.values), self.seed, self.multiplier, self.addend, *self.reserved)

    @property
    def grid(self):
        self.validate()
        return ((len(self.values) + 127) // 128, 1, 1)

    @property
    def logical_bytes(self):
        self.validate()
        return ((512 + 4 * len(self.values) + 4095) // 4096) * 4096

    def _images(self, sizes, completed):
        self.validate()
        require(type(sizes) is tuple and len(sizes) == 4
                and all(type(n) is int and self.logical_bytes <= n <= 65536
                        and n % 4096 == 0 for n in sizes), 'AFFINE_IMAGE_SIZES')
        result = []
        for role, size in zip(ROLES, sizes):
            raw = bytearray(POISON.to_bytes(4, 'little') * (size // 4))
            payload = self.values if role == 'input' else (
                expected(self.values, self.seed, self.multiplier, self.addend)
                if completed and role == 'output' else None)
            if payload is not None:
                struct.pack_into('<' + str(len(payload)) + 'I', raw, 256, *payload)
            result.append(bytes(raw))
        return tuple(result)

    def initial_images(self, sizes):
        return self._images(sizes, False)

    def expected_images(self, sizes):
        return self._images(sizes, True)
