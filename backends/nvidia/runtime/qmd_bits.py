"""Original bit-image primitive, not QMD admission or a publication API."""
from pathlib import Path
import hashlib
import json

TABLE_SHA = '45934cb38bfc01c6ed5260bb3560efef3d4d0a1cf389036c4ca8d703b2baee62'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def fields():
    p = Path(__file__).resolve().parent.parent / 'data/qmd_fields.json'
    require(not p.is_symlink() and p.is_file(), 'QMD_FIELDS_FILE')
    raw = p.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == TABLE_SHA, 'QMD_FIELDS_PIN')
    return json.loads(raw)['fields']


def interval(name):
    require(type(name) is str, 'QMD_FIELD_NAME')
    table = fields()
    require(name in table, 'QMD_FIELD_NAME')
    f = table[name]
    return f['lo'], f['width']


def _image(raw):
    require(type(raw) is bytes and len(raw) == 256, 'QMD_IMAGE_SIZE')
    return int.from_bytes(raw, 'little')


def read(raw, name):
    image = _image(raw)
    lo, width = interval(name)
    return (image >> lo) & ((1 << width) - 1)


def write(raw, name, value):
    image = _image(raw)
    lo, width = interval(name)
    require(type(value) is int and 0 <= value < 1 << width, 'QMD_FIELD_VALUE')
    mask = ((1 << width) - 1) << lo
    return ((image & ~mask) | (value << lo)).to_bytes(256, 'little')
