"""Original u32 declaration primitive; no method/push or execution admission."""
from pathlib import Path
import hashlib
import json
import stat

HERE = Path(__file__).resolve().parent
TABLES = (
    ('push_fields.json', '7bf7fd7c0f488d9f17afbd4bd9af405b144b1a4505eb51e0065463376783dec1', 51825, 0o664),
    ('push_extra_fields.json', '1d62442fd52e86ea96a3ff806a6fa5245a6ecea6e94de3590d08cccd0e1760bb', 6129, 0o664),
)


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _pairs(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, 'PUSH_TABLE_DUPLICATE_KEY')
        result[name] = value
    return result


def declarations():
    result = {}
    for name, sha, size, mode in TABLES:
        path = HERE.parent / 'data' / name
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == mode
                and info.st_size == size, 'PUSH_TABLE_FILE')
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == sha, 'PUSH_TABLE_PIN')
        table = json.loads(raw, object_pairs_hook=_pairs)['declarations']
        require(type(table) is dict and not (set(result) & set(table)), 'PUSH_TABLE_SYMBOLS')
        result.update(table)
    require(len(result) == 178, 'PUSH_TABLE_COUNT')
    return result


def _row(name):
    require(type(name) is str, 'PUSH_SYMBOL')
    table = declarations()
    require(name in table, 'PUSH_SYMBOL')
    return table[name]


def value(name):
    row = _row(name)
    require(row['kind'] == 'value', 'PUSH_EXPECTED_VALUE')
    return row['value']


def interval(name):
    row = _row(name)
    require(row['kind'] == 'field', 'PUSH_EXPECTED_FIELD')
    return row['lo'], row['width']


def _word(word):
    require(type(word) is int and 0 <= word < 1 << 32, 'PUSH_WORD')


def read(word, name):
    _word(word)
    lo, width = interval(name)
    return (word >> lo) & ((1 << width)-1)


def write(word, name, number):
    _word(word)
    lo, width = interval(name)
    require(type(number) is int and 0 <= number < 1 << width, 'PUSH_FIELD_VALUE')
    mask = ((1 << width)-1) << lo
    return (word & ~mask) | (number << lo)
