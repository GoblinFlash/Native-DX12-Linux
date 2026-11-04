"""Independent integer oracle for the original affine shader; no GPU input."""
U32 = 0xffffffff


def expected(values, seed, multiplier, addend):
    if type(values) is not tuple or len(values) not in (1, 127, 128, 129, 515):
        raise ValueError('AFFINE_CASE')
    if any(type(v) is not int or not 0 <= v <= U32
           for v in (*values, seed, multiplier, addend)):
        raise ValueError('AFFINE_U32')
    return tuple((((v * multiplier) + addend) & U32) ^ seed for v in values)


def self_check():
    # Literal examples distinguish overflow-before-XOR from unbounded arithmetic.
    values = (0, 1, U32, 0x80000000) + (0,) * 123
    if expected(values, 0x55, 3, 5)[:4] != (0x50, 0x5d, 0x57, 0x80000050):
        raise ValueError('AFFINE_SELF_CHECK_LITERAL')
    for n in (1, 127, 128, 129, 515):
        source = tuple((i * 997) & U32 for i in range(n))
        result = expected(source, 0x713ac6d5, 1664525, 1013904223)
        if result == source:
            raise ValueError('AFFINE_SELF_CHECK_TRANSFORM')
        if not all(a ^ b == 1 for a, b in zip(
                result, expected(source, 0x713ac6d4, 1664525, 1013904223))):
            raise ValueError('AFFINE_SELF_CHECK_SEED')


if __name__ == '__main__':
    self_check()
    print('AFFINE_CPU_REFERENCE_OK_NOT_GPU')
