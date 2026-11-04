"""Source-only binding to the reviewed, team-authored replacement, not old helpers."""
import hashlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / 'runtime'
ARENA_SHA = '8dd78bd5408e29281ac3953dbfd2abaddd7cb04e8d8050d970ff95b84d88c821'
ABI_SHA = '0fa893036bc32828bd96bb29659ea57caecd879a67160686eff53de610b21a07'


def checked(path, digest):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('REPLACEMENT_INPUT_PIN:' + str(path))
    return raw


def load():
    path = INPUT / 'rm_arena.py'
    raw = checked(path, ARENA_SHA)
    checked(ROOT / 'abi/abi.json', ABI_SHA)
    name = '_ndx_replacement_arena_' + ARENA_SHA[:16]
    # Never accept a module just because its __file__ matches.
    if name in sys.modules:
        raise ValueError('REPLACEMENT_MODULE_PRELOAD')
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), 'exec'), module.__dict__)
    except BaseException:
        del sys.modules[name]
        raise
    return module


arena = load()
