"""Source-only local preparation closure; no resource construction or device execution.

Original implementation from the stated loader requirements. The caller must
pin this bootstrap and supply the expected manifest digest independently.
Trusted Python/stdlib and an exclusive process/module table are prerequisites.
Not a portable package, sandbox, provenance certificate or hardware launcher.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import sys
import types

HERE = Path(__file__).resolve().parent
TEAM = HERE
ORDER = ('replacement_inputs', 'linux_backend', 'channel_images', 'rm_channel',
         'mapping_flags', 'mapping_protocol', 'channel_resources', 'channel_objects', 'preparation_memory',
         'preparation_upload', 'preparation_schedule', 'gp_entry', 'push_bits', 'qmd_bits',
         'shader_info_check', 'sort_data_layout', 'affine_reference', 'affine_data', 'affine_images', 'data_resources', 'qmd_images',
         'sort_workload', 'cb0_images', 'control_layout', 'initial_data_upload',
         'push_images', 'control_images', 'packet_preparation', 'post_execution_images',
         'packet_schedule', 'native_words_binding', 'mapping_transport', 'packet_publication',
         'process_retention', 'native_packet_publication', 'native_packet_completion',
         'native_execution_health', 'native_execution', 'native_execution_evidence', 'native_retirement',
         'bootstrap_identity')
ARENA_NAME = '_ndx_replacement_arena_8dd78bd5408e2928'
ORACLE_NAME = '_ndx_sort_data_oracle_4efff6756e877af8'
PRIVATE = (ARENA_NAME, ORACLE_NAME)
NAMES = ORDER + PRIVATE
PACKAGE = HERE.parents[2]
PATHS = {
    'replacement_inputs': PACKAGE / 'backends/nvidia/runtime/replacement_inputs.py',
    'linux_backend': PACKAGE / 'backends/nvidia/runtime/linux_backend.py',
    'channel_images': PACKAGE / 'backends/nvidia/runtime/channel_images.py',
    'rm_channel': PACKAGE / 'backends/nvidia/runtime/rm_channel.py',
    'mapping_flags': PACKAGE / 'backends/nvidia/runtime/mapping_flags.py',
    'mapping_protocol': PACKAGE / 'backends/nvidia/runtime/mapping_protocol.py',
    'channel_resources': PACKAGE / 'backends/nvidia/runtime/channel_resources.py',
    'channel_objects': PACKAGE / 'backends/nvidia/runtime/channel_objects.py',
    'preparation_memory': PACKAGE / 'backends/nvidia/runtime/preparation_memory.py',
    'preparation_upload': PACKAGE / 'backends/nvidia/runtime/preparation_upload.py',
    'preparation_schedule': PACKAGE / 'backends/nvidia/runtime/preparation_schedule.py',
    'gp_entry': PACKAGE / 'backends/nvidia/runtime/gp_entry.py',
    'push_bits': PACKAGE / 'backends/nvidia/runtime/push_bits.py',
    'qmd_bits': PACKAGE / 'backends/nvidia/runtime/qmd_bits.py',
    'shader_info_check': PACKAGE / 'backends/nvidia/runtime/shader_info_check.py',
    'sort_data_layout': PACKAGE / 'backends/nvidia/runtime/sort_data_layout.py',
    'data_resources': PACKAGE / 'backends/nvidia/runtime/data_resources.py',
    'qmd_images': PACKAGE / 'backends/nvidia/runtime/qmd_images.py',
    'sort_workload': PACKAGE / 'backends/nvidia/runtime/sort_workload.py',
    'cb0_images': PACKAGE / 'backends/nvidia/runtime/cb0_images.py',
    'control_layout': PACKAGE / 'backends/nvidia/runtime/control_layout.py',
    'initial_data_upload': PACKAGE / 'backends/nvidia/runtime/initial_data_upload.py',
    'push_images': PACKAGE / 'backends/nvidia/runtime/push_images.py',
    'control_images': PACKAGE / 'backends/nvidia/runtime/control_images.py',
    'packet_preparation': PACKAGE / 'backends/nvidia/runtime/packet_preparation.py',
    'arena': PACKAGE / 'backends/nvidia/runtime/rm_arena.py',
    'abi': PACKAGE / 'backends/nvidia/abi/abi.json',
    'oracle': PACKAGE / 'backends/nvidia/reference/parallel_sort.py',
    'flags': PACKAGE / 'backends/nvidia/data/mapping_flags.json',
    'input:mapping_transport.py': PACKAGE / 'backends/nvidia/runtime/mapping_transport.py',
    'input:preparation_publication.py': PACKAGE / 'backends/nvidia/runtime/preparation_publication.py',
    'input:packet-source-inventory.json': PACKAGE / 'backends/nvidia/data/parallel_sort_programs.json',
    'input:packet-preparation-inputs.json': PACKAGE / 'backends/nvidia/data/packet_inputs.json',
    'input:push-profile-extra-declarations.json': PACKAGE / 'backends/nvidia/data/push_extra_fields.json',
    'input:push_fields.json': PACKAGE / 'backends/nvidia/data/push_fields.json',
    'input:qmd_fields.json': PACKAGE / 'backends/nvidia/data/qmd_fields.json',
    'input:shader_info_abi.json': PACKAGE / 'backends/nvidia/data/shader_info_abi.json',
    'header:clc56f': Path('@HEADERS@') / 'clc56f.h',
    'header:clc9c0': Path('@HEADERS@') / 'clc9c0.h',
    'header:clc9c0qmd': Path('@HEADERS@') / 'clc9c0qmd.h',
    'artifact:count.bin': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/count/count.bin',
    'artifact:count.info.bin': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/count/count.info.bin',
    'artifact:count.json': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/count/count.json',
    'artifact:count.qmd': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/count/count.qmd',
    'artifact:reduce.bin': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/reduce/reduce.bin',
    'artifact:reduce.info.bin': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/reduce/reduce.info.bin',
    'artifact:reduce.json': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/reduce/reduce.json',
    'artifact:reduce.qmd': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/reduce/reduce.qmd',
    'artifact:scan.bin': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scan/scan.bin',
    'artifact:scan.info.bin': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scan/scan.info.bin',
    'artifact:scan.json': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scan/scan.json',
    'artifact:scan.qmd': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scan/scan.qmd',
    'artifact:scanadd.bin': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scanadd/scanadd.bin',
    'artifact:scanadd.info.bin': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scanadd/scanadd.info.bin',
    'artifact:scanadd.json': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scanadd/scanadd.json',
    'artifact:scanadd.qmd': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scanadd/scanadd.qmd',
    'artifact:scatter.bin': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scatter/scatter.bin',
    'artifact:scatter.info.bin': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scatter/scatter.info.bin',
    'artifact:scatter.json': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scatter/scatter.json',
    'artifact:scatter.qmd': Path('@ARTIFACTS@') / 'nvidia/parallel_sort/scatter/scatter.qmd',
    'post_execution_images': PACKAGE / 'backends/nvidia/runtime/post_execution_images.py',
    'packet_schedule': PACKAGE / 'backends/nvidia/runtime/packet_schedule.py',
    'native_words_binding': PACKAGE / 'backends/nvidia/runtime/native_words_binding.py',
    'mapping_transport': PACKAGE / 'backends/nvidia/runtime/mapping_transport.py',
    'packet_publication': PACKAGE / 'backends/nvidia/runtime/packet_publication.py',
    'process_retention': PACKAGE / 'backends/nvidia/runtime/process_retention.py',
    'native_packet_publication': PACKAGE / 'backends/nvidia/runtime/native_packet_publication.py',
    'native_packet_completion': PACKAGE / 'backends/nvidia/runtime/native_packet_completion.py',
    'native_execution_health': PACKAGE / 'backends/nvidia/runtime/native_execution_health.py',
    'native_execution': PACKAGE / 'backends/nvidia/runtime/native_execution.py',
    'native_execution_evidence': PACKAGE / 'backends/nvidia/runtime/native_execution_evidence.py',
    'native_retirement': PACKAGE / 'backends/nvidia/runtime/native_retirement.py',
    'bootstrap_identity': PACKAGE / 'backends/nvidia/runtime/bootstrap_identity.py',
    'input:affine-program-inventory.json': PACKAGE / 'backends/nvidia/data/affine_programs.json',
    'artifact:affine-u32.bin': Path('@ARTIFACTS@') / 'nvidia/affine/shader.bin',
    'artifact:affine-u32.info.bin': Path('@ARTIFACTS@') / 'nvidia/affine/shader.info.bin',
    'artifact:affine-u32.json': Path('@ARTIFACTS@') / 'nvidia/affine/shader.json',
    'artifact:affine-u32.qmd': Path('@ARTIFACTS@') / 'nvidia/affine/shader.qmd',
    'affine_reference': PACKAGE / 'backends/nvidia/runtime/affine_reference.py',
    'affine_data': PACKAGE / 'backends/nvidia/runtime/affine_data.py',
    'affine_images': PACKAGE / 'backends/nvidia/runtime/affine_images.py',
}
MODES = {name: 0o664 for name in PATHS}
MODES['header:clc56f'] = 0o644


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'LOADER_DUPLICATE_KEY')
        result[key] = value
    return result


def source_path(value):
    value = str(value)
    path = Path(value)
    if not path.is_absolute():
        match = re.fullmatch(r'@(PACKAGE|ARTIFACTS|HEADERS)@/(.+)', value)
        require(match is not None, 'SOURCE_LOCATOR')
        parts = match[2].split('/')
        require(all(p not in ('', '.', '..') for p in parts) and '\\' not in match[2],
                'SOURCE_TRAVERSAL')
        roots = {'PACKAGE': HERE.parents[2], 'ARTIFACTS': HERE.parents[3] / 'artifacts',
                 'HEADERS': HERE.parents[3] / 'headers'}
        root = roots[match[1]]
        path = root.joinpath(*parts)
        require(path.resolve(strict=True).is_relative_to(root.resolve(strict=True)), 'SOURCE_ESCAPE')
    require('..' not in path.parts, 'SOURCE_TRAVERSAL')
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'SOURCE_SYMLINK')
    return path


def read_regular(value):
    path = source_path(value)
    require(Path('/proc/self/fd').is_dir(), 'SOURCE_PROC_UNAVAILABLE')
    directory = os.open('/', os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = None
    try:
        for part in path.parts[1:-1]:
            following = os.open('/proc/self/fd/' + str(directory) + '/' + part,
                                os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
            os.close(directory)
            directory = following
        descriptor = os.open('/proc/self/fd/' + str(directory) + '/' + path.name,
                             os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= 64 * 1024 * 1024, 'SOURCE_REGULAR_SIZE')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            raw = stream.read(64 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        require((info.st_size, info.st_mode, info.st_mtime_ns) ==
                (after.st_size, after.st_mode, after.st_mtime_ns) and len(raw) == info.st_size,
                'SOURCE_CHANGED_DURING_READ')
        return info, raw
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


PATHS = {name: source_path(path) for name, path in PATHS.items()}


def regular(path):
    # Check every lexical component; resolve() alone would hide a symlink.
    require(path.is_absolute() and '..' not in path.parts, 'LOADER_PATH')
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'LOADER_SYMLINK')
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode), 'LOADER_REGULAR')
    return info


def verify(manifest, expected_sha):
    require(type(expected_sha) is str and len(expected_sha) == 64
            and all(c in '0123456789abcdef' for c in expected_sha), 'LOADER_DIGEST')
    manifest = Path(manifest)
    _, raw = read_regular(manifest)
    require(digest(raw) == expected_sha, 'LOADER_MANIFEST_PIN')
    spec = json.loads(raw, object_pairs_hook=unique)
    require(type(spec) is dict and set(spec) == {'schema', 'entries'}
            and spec['schema'] == 'preparation-source.v3', 'LOADER_SCHEMA')
    entries = spec['entries']
    require(type(entries) is dict and set(entries) == set(PATHS), 'LOADER_ENTRY_SET')
    snapshots = {}
    for name, path in PATHS.items():
        entry = entries[name]
        require(type(entry) is dict and set(entry) == {'path', 'size', 'mode', 'sha256'},
                'LOADER_ENTRY')
        require(type(entry['path']) is str and entry['path'].startswith('@')
                and source_path(entry['path']) == path, 'LOADER_SOURCE_PATH:' + name)
        require(type(entry['size']) is int and entry['size'] > 0
                and type(entry['mode']) is int and entry['mode'] == MODES[name]
                and type(entry['sha256']) is str, 'LOADER_ENTRY_TYPES:' + name)
        info, content = read_regular(path)
        require((info.st_size, stat.S_IMODE(info.st_mode), digest(content)) ==
                (entry['size'], entry['mode'], entry['sha256']), 'LOADER_SOURCE_PIN:' + name)
        require(len(content) == entry['size'], 'LOADER_SOURCE_LENGTH:' + name)
        snapshots[name] = content
    return snapshots


class Loader:
    """One attempt per instance; refuse any preload, even a same-path module."""
    def __init__(self):
        self.phase = 'NEW'

    def load(self, manifest, expected_sha):
        require(self.phase == 'NEW', 'LOADER_CLOSED')
        self.phase = 'LOADING'
        created = {}
        private_present = {name: name in sys.modules for name in PRIVATE}
        try:
            require(all(name not in sys.modules for name in NAMES), 'LOADER_MODULE_PRELOAD')
            snapshots = verify(manifest, expected_sha)
            # Syntax of the entire source set is checked before executing one file.
            compiled = {name: compile(snapshots[name], str(PATHS[name]), 'exec')
                        for name in ORDER}
            compile(snapshots['arena'], str(PATHS['arena']), 'exec')
            compile(snapshots['oracle'], str(PATHS['oracle']), 'exec')
            for name in ORDER:
                require(name not in sys.modules, 'LOADER_MODULE_PRELOAD')
                module = types.ModuleType(name)
                module.__file__ = str(PATHS[name])
                created[name] = module
                sys.modules[name] = module
                exec(compiled[name], module.__dict__)
                # replacement_inputs itself compiles pinned team Arena bytes.
                if name == 'replacement_inputs':
                    arena = sys.modules.get(ARENA_NAME)
                    require(arena is module.arena and arena.__file__ == str(PATHS['arena']),
                            'LOADER_ARENA_BINDING')
                    created[ARENA_NAME] = arena
                if name == 'sort_data_layout':
                    oracle = sys.modules.get(ORACLE_NAME)
                    require(type(oracle) is types.ModuleType and oracle is module.B
                            and oracle.__file__ == str(PATHS['oracle']), 'LOADER_ORACLE_BINDING')
                    created[ORACLE_NAME] = oracle
            self.phase = 'READY'
            return types.MappingProxyType(dict(created))
        except BaseException:
            self.phase = 'FAILED'
            for name, module in reversed(tuple(created.items())):
                if sys.modules.get(name) is module:
                    del sys.modules[name]
            # A source module can fail after creating its private dependency but
            # before assigning arena/B. Pre-existing entries, even None, survive.
            for name in PRIVATE:
                if not private_present[name] and name in sys.modules:
                    del sys.modules[name]
            raise
