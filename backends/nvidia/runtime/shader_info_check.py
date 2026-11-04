"""Original saved-artifact consistency check. Not packet or hardware admission.

Layout comes from our sizeof/offsetof probe of the pinned NAK API header.
No compiler/runtime implementation is imported. QMD is identity-checked only.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import stat

HERE = Path(__file__).resolve().parent
ABI_SHA = '1037557f3650fd506069a8000cae44effa7c80ce9acb1b55de8e4e3574ea7687'
INVENTORY_SHA = '561c74c38e47471fff27837f0cddea0766435f6faa8a9c32d1aef1c351f65703'
KINDS = ('count', 'reduce', 'scan', 'scanadd', 'scatter')
SCALARS = ('stage', 'sm', 'num_gprs', 'num_control_barriers', 'max_warps_per_sm',
           'num_instrs', 'num_static_cycles', 'num_spills_to_mem', 'num_fills_from_mem',
           'num_spills_to_reg', 'num_fills_from_reg', 'slm_size', 'crs_size')
LOCAL = tuple('cs.local_size[' + str(i) + ']' for i in range(3))
FIELDS = SCALARS + LOCAL + ('cs.smem_size',)


class Refused(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'INFO_JSON_DUPLICATE')
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=_object)


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


def pinned(path, digest, size=None, mode=None):
    st, raw = read_regular(path)
    require(hashlib.sha256(raw).hexdigest() == digest, 'INFO_INPUT_PIN')
    require(size is None or len(raw) == size, 'INFO_INPUT_SIZE')
    require(mode is None or stat.S_IMODE(st.st_mode) == mode, 'INFO_INPUT_MODE')
    return raw


def abi():
    value = parse(pinned((HERE.parent / 'data' / 'shader_info_abi.json'), ABI_SHA))
    require(value['size'] == 864 and value['little_endian'] is True
            and set(value['fields']) == set(FIELDS), 'INFO_ABI_PROFILE')
    return value


def decode(raw):
    layout = abi()
    require(type(raw) is bytes and len(raw) == layout['size'], 'INFO_RAW_SIZE')
    values, occupied = {}, set()
    for name, field in layout['fields'].items():
        begin, end = field['offset'], field['offset'] + field['size']
        values[name] = int.from_bytes(raw[begin:end], 'little', signed=field['signed'])
        occupied.update(range(begin, end))
    require(all(raw[i] == 0 for i in range(len(raw)) if i not in occupied), 'INFO_RESERVED_BYTES')
    return values


def compare(kind, code, raw_info, metadata):
    """Pure byte/metadata relation; caller must separately bind artifact identity."""
    require(type(kind) is str and kind in KINDS, 'INFO_KIND')
    require(type(code) is bytes and type(metadata) is dict, 'INFO_INPUT_TYPE')
    require(metadata.get('profile') == 'ffx-' + ('scan-add' if kind == 'scanadd' else kind), 'INFO_PROFILE_NAME')
    info = metadata.get('shader_info')
    require(type(info) is dict and set(info) == set(SCALARS) | {'cs'}, 'INFO_METADATA_SHAPE')
    require(all(type(info[k]) is int for k in SCALARS), 'INFO_METADATA_TYPE')
    cs = info['cs']
    require(type(cs) is dict and set(cs) == {'local_size', 'smem_size'}, 'INFO_METADATA_SHAPE')
    require(type(cs['local_size']) is list and len(cs['local_size']) == 3
            and all(type(v) is int for v in cs['local_size'])
            and type(cs['smem_size']) is int, 'INFO_METADATA_TYPE')
    expected = {k: info[k] for k in SCALARS}
    expected.update(zip(LOCAL, cs['local_size']))
    expected['cs.smem_size'] = cs['smem_size']
    observed = decode(raw_info)
    require(observed == expected, 'INFO_METADATA_MISMATCH')
    required = dict(stage=5, sm=89, num_gprs=24, num_control_barriers=1,
                    max_warps_per_sm=48, slm_size=0, crs_size=0,
                    num_spills_to_mem=0, num_fills_from_mem=0)
    require(all(observed[k] == v for k, v in required.items())
            and cs['local_size'] == [128, 1, 1], 'INFO_COMPUTE_PROFILE')
    require(type(metadata.get('code_bytes')) is int and len(code) == metadata['code_bytes']
            and len(code) == 16 * observed['num_instrs'] and len(code) > 0, 'INFO_CODE_LENGTH')
    return observed


def inspect():
    inventory = parse(pinned((HERE.parent / 'data' / 'parallel_sort_programs.json'), INVENTORY_SHA))
    require(set(inventory['programs']) == set(KINDS), 'INFO_PROGRAM_SET')
    result = {}
    for kind in KINDS:
        entries = inventory['programs'][kind]['artifacts']
        require(set(entries) == {'bin', 'info.bin', 'json', 'qmd'}, 'INFO_ARTIFACT_SET')
        images = {name: pinned(e['path'], e['sha256'], e['size'], e['mode'])
                  for name, e in entries.items()}
        require(len(images['qmd']) == 256, 'INFO_QMD_SIZE')
        result[kind] = compare(kind, images['bin'], images['info.bin'], parse(images['json']))
    return dict(status='SAVED_SHADER_INFO_CONSISTENT', fields=result,
                artifact_count=20, qmd_semantics_checked=False, gpu_executed=False)


AFFINE_INVENTORY_SHA = '45f4c504da82a3d0733c464259f83a8c22ef19403d1502798b5cd35bf66bdbdf'


def _affine_exact(actual, wanted):
    if type(actual) is not type(wanted):
        return False
    if type(wanted) is dict:
        return set(actual) == set(wanted) and all(_affine_exact(actual[k], v) for k, v in wanted.items())
    if type(wanted) is list:
        return len(actual) == len(wanted) and all(_affine_exact(a, b) for a, b in zip(actual, wanted))
    return actual == wanted


def compare_affine(code, raw_info, metadata):
    """Separate exact affine schema; pure relation, not live admission."""
    require(type(code) is bytes and type(metadata) is dict, 'INFO_AFFINE_TYPE')
    require(set(metadata) == {'schema','scope','profile','cb0','bindings','code_bytes',
                             'shader_info','target','gpu','dispatch','dispatchable'},
            'INFO_AFFINE_SHAPE')
    fixed = dict(schema='ndx12.direct.batch.compiler.v1', scope='CPU_ONLY',
                 profile='affine-u32', gpu='NOT_RUN', dispatch='BLOCKED', dispatchable=False)
    require(all(_affine_exact(metadata[k], v) for k, v in fixed.items()), 'INFO_AFFINE_PROFILE')
    cb = dict(layout='ndx12.nvidia.batch.cb0.v2', bytes=80, qmd_bytes=128,
              params_offset=48, param_mask=15)
    bindings = [dict(binding=0,reads=1,writes=0,base_offset=0,size_offset=8),
                dict(binding=1,reads=0,writes=1,base_offset=16,size_offset=24)]
    target = dict(sm=89,max_warps_per_mp=48,
                  origin='PINNED_SM89_ARCHITECTURAL_TABLE_NOT_OCCUPANCY_MEASUREMENT',
                  physical_device_verified=False)
    require(_affine_exact(metadata['cb0'], cb) and _affine_exact(metadata['bindings'], bindings)
            and _affine_exact(metadata['target'], target), 'INFO_AFFINE_INTERFACE')
    info = metadata['shader_info']
    require(type(info) is dict and set(info) == set(SCALARS) | {'cs'}
            and all(type(info[k]) is int for k in SCALARS), 'INFO_AFFINE_METADATA')
    require(_affine_exact(info['cs'], dict(local_size=[128,1,1],smem_size=0)),
            'INFO_AFFINE_LOCAL')
    expected = {k:info[k] for k in SCALARS}
    expected.update(zip(LOCAL, info['cs']['local_size']))
    expected['cs.smem_size'] = 0
    observed = decode(raw_info)
    require(observed == expected, 'INFO_AFFINE_RAW_MISMATCH')
    required = dict(stage=5,sm=89,num_gprs=24,num_control_barriers=0,
                    max_warps_per_sm=48,slm_size=0,crs_size=0,
                    num_spills_to_mem=0,num_fills_from_mem=0,
                    num_spills_to_reg=0,num_fills_from_reg=0)
    require(all(observed[k] == v for k,v in required.items()), 'INFO_AFFINE_COMPUTE')
    require(type(metadata['code_bytes']) is int and metadata['code_bytes'] == len(code)
            and len(code) == 16*observed['num_instrs'] and len(code) > 0,
            'INFO_AFFINE_CODE_LENGTH')
    return observed


def inspect_affine():
    inventory = parse(pinned((HERE.parent / 'data' / 'affine_programs.json'), AFFINE_INVENTORY_SHA))
    require(type(inventory) is dict and set(inventory) == {'schema','profile','artifacts'}
            and inventory['schema'] == 'affine-program-inputs.v1'
            and inventory['profile'] == 'affine-u32', 'INFO_AFFINE_INVENTORY')
    artifacts = inventory['artifacts']
    require(type(artifacts) is dict and set(artifacts) == {'bin','info.bin','json','qmd'},
            'INFO_AFFINE_ARTIFACT_SET')
    images = {}
    for name, spec in artifacts.items():
        path = Path('@ARTIFACTS@')/'nvidia/affine'/('shader.'+name)
        require(type(spec) is dict and set(spec) == {'path','size','mode','sha256'}
                and spec['path'] == str(path) and type(spec['size']) is int and spec['size'] > 0
                and type(spec['mode']) is int and spec['mode'] == 0o664
                and type(spec['sha256']) is str, 'INFO_AFFINE_ARTIFACT')
        images[name] = pinned(path,spec['sha256'],spec['size'],spec['mode'])
    info = compare_affine(images['bin'],images['info.bin'],parse(images['json']))
    require(len(images['qmd']) == 256, 'INFO_AFFINE_QMD_SIZE')
    return dict(status='SAVED_AFFINE_SHADER_INFO_CONSISTENT',fields=info,artifact_count=4,
                qmd_semantics_checked=False,gpu_executed=False,dispatchable=False)


if __name__ == '__main__':
    print(json.dumps(inspect(), sort_keys=True))
