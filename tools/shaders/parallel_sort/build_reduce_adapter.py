"""SORT-FFX-012 stage 2 CPU screen: FidelityFX ParallelSort FPS_CountReduce (wave reduce/elect) through the
private adapter. Stage 1 outputs are not touched; this stage uses the ...-012-S2 build/evidence namespace.

HLSL -> DXIL -> SPIR-V -> NIR -> NAK, normal and NDEBUG. No GPU, no vendor rebuild, no production path.
Outputs: build/<TASK>/{spirv,normal,ndebug}, evidence/<TASK>/{inputs.json,commands.jsonl,screen.json}.
"""
import difflib
import hashlib
import json
import math
import os
import signal
import tempfile
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

import importlib.util
_config_spec = importlib.util.spec_from_file_location('ffx_build_config', Path(__file__).with_name('ffx_build_config.py'))
_config_module = importlib.util.module_from_spec(_config_spec)
_config_spec.loader.exec_module(_config_module)
configure = _config_module.configure

TASK = 'NDX12-NVIDIA-SORT-FFX-012-S2'
CONVERT = ('--ssbo-uav', '--ssbo-alignment', '4', '--no-bda', '--no-compute-shader-derivatives')
PINS = {
    'nvidia_batch_compile.c': '7675310fef087f8b185ebb1bc36e7f228a1adea929a88ec36122c405dd9f20b6',
    'nvidia_shared_lowering.h': 'fb145a61d6a01c7b7e371114d69f69a3e49c66e22c5844316d40e7a1b3c66cbd',
    'nir_shared_range.h': '95194dcd90ca9ebee80ac8fe9cc368ad116bcf1627e4c0902c919cc1d7680047',
}
BASE_CODE = '6dfe0274a69ba3d02d9effded63c45078e13143f41af94ad87f35412f0125ee0'
HEADER_SHA = '50d6309459f2e2ce6abd9d48099d4e34d1b126b81a69e824443def0380723d84'
ORDINARY_PROFILE = 'readymade-hist-pred-guarded'
ARTIFACTS = ('bin', 'info.bin', 'qmd', 'nak.txt')


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def once(s, old, new):
    need(s.count(old) == 1, 'PATCH_CONTEXT:' + old[:80])
    return s.replace(old, new)


def candidate_source():
    c = (BASE / 'nvidia_batch_compile.c').read_text()
    entry = '   {"readymade-hist-pred-guarded", {16, 16, 1}, {1, 1, 1}, 1, 0, true, CB0_PARAM_SIZE, true, 1024, 2, 1, 1, 0x03},\n'
    c = once(c, entry, entry +
             '   /* SORT-FFX-012 stage 2: FidelityFX ParallelSort FPS_CountReduce (128 threads, wave-32 reduce). */\n'
             '   {"ffx-reduce", {128, 1, 1}, {1, 1, 1}, 4, 1, true, CB0_PARAM_SIZE, true, 512, 1, 0, 0, 0x14},\n')
    c = once(c, '   const struct profile *profile = select_profile(nir, requested);\n',
             '   const struct profile *profile = select_profile(nir, requested);\n'
             '   bool ffx = profile && !strncmp(profile->name, "ffx-", 4);\n'
             '   bool ffx_wave = profile && !strcmp(profile->name, "ffx-reduce");\n')
    # Narrow wave admission for ffx-reduce only: 32-bit scalar iadd reduce over the whole subgroup,
    # elect, and the subgroup size. Everything else keeps the shared-profile intrinsic list.
    c = once(c, '               if (profile->shared_profile && shared_intrinsic_allowed(in)) break;\n',
             '               if (profile->shared_profile && shared_intrinsic_allowed(in)) break;\n'
             '               if (ffx_wave && ((in->intrinsic == nir_intrinsic_reduce && in->def.bit_size == 32 &&\n'
             '                                 in->def.num_components == 1 &&\n'
             '                                 nir_intrinsic_reduction_op(in) == nir_op_iadd &&\n'
             '                                 nir_intrinsic_cluster_size(in) == 0) ||\n'
             '                                in->intrinsic == nir_intrinsic_elect ||\n'
             '                                in->intrinsic == nir_intrinsic_load_subgroup_size)) break;\n')
    c = once(c, '              if (profile->params && !param_alu_allowed(nir_instr_as_alu(kind_instr)->op)) {',
             '              if (profile->params && !param_alu_allowed(nir_instr_as_alu(kind_instr)->op) &&\n'
             '                  !(ffx && nir_instr_as_alu(kind_instr)->op == nir_op_ineg) &&\n'
             '                  !(ffx_wave && ffx_divisor_ok(nir_instr_as_alu(kind_instr)))) {')
    # udiv/umod only by the subgroup size or by a b0 word (host contract: NumReduceThreadgroupPerBin >= 1).
    c = once(c, '#include "nvidia_shared_lowering.h"\n',
             '#include "nvidia_shared_lowering.h"\n\n'
             '/* SORT-FFX-012 stage 2: unsigned division admitted only by the subgroup size or a b0 word. */\n'
             'static bool\n'
             'ffx_divisor_ok(nir_alu_instr *alu)\n'
             '{\n'
             '   if ((alu->op != nir_op_udiv && alu->op != nir_op_umod) || alu->def.bit_size != 32)\n'
             '      return false;\n'
             '   nir_scalar d = nir_scalar_chase_movs(nir_scalar_resolved(alu->src[1].src.ssa, alu->src[1].swizzle[0]));\n'
             '   if (!nir_scalar_is_intrinsic(d))\n'
             '      return false;\n'
             '   nir_intrinsic_op op = nir_scalar_intrinsic_op(d);\n'
             '   return op == nir_intrinsic_load_subgroup_size || op == nir_intrinsic_load_ubo;\n'
             '}\n')
    c = once(c, 'nir->info.shared_size > 4096) goto done;',
             'nir->info.shared_size > (ffx ? 8192u : 4096u)) goto done;')
    return c


def limits():
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024 ** 3, 4 * 1024 ** 3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run(argv, name, cwd=None, *, timeout=120):
    need(type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0,
         'COMMAND_TIMEOUT_VALUE')
    argv = list(map(str, argv))
    start = time.monotonic()
    attempt = Path(tempfile.mkdtemp(prefix='command-', dir=E))
    intent = dict(name=name, argv=argv, cwd=str(cwd or BUILD), timeout_seconds=timeout)
    with (attempt / 'intent.json').open('x') as f:
        json.dump(intent, f)
    process = None
    failure = None
    timed_out = False
    interrupted = None
    cleanup = dict(group_sigkill_sent=False, direct_child_reaped=False, errors=[])
    def stop_owned_group():
        # Never signal a potentially recycled group after the leader was reaped.
        if process.returncode is not None:
            cleanup['direct_child_reaped'] = True
            cleanup['errors'].append('group not signalled: direct child already reaped')
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
            cleanup['group_sigkill_sent'] = True
        except ProcessLookupError:
            pass
        except OSError as error:
            cleanup['errors'].append(str(error))
        try:
            process.wait(timeout=2)
            cleanup['direct_child_reaped'] = True
        except (subprocess.TimeoutExpired, OSError) as error:
            cleanup['errors'].append(str(error))

    with (attempt / 'stdout.bin').open('xb') as out, (attempt / 'stderr.bin').open('xb') as err:
        try:
            process = subprocess.Popen(argv, cwd=cwd or BUILD, stdout=out, stderr=err,
                                       start_new_session=True, preexec_fn=limits,
                                       env=dict(PATH='/usr/bin:/bin', LANG='C', LC_ALL='C', TMPDIR=str(BUILD / 'tmp')))
        except (OSError, subprocess.SubprocessError) as error:
            failure = error
        else:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                stop_owned_group()
            except BaseException as error:
                interrupted = error
                stop_owned_group()
    try:
        stdout = (attempt / 'stdout.bin').read_bytes()
        stderr = (attempt / 'stderr.bin').read_bytes()
        rc = process.returncode if process is not None else None
        status = 'INTERRUPTED' if interrupted is not None else 'TIMEOUT' if timed_out else 'SPAWN_ERROR' if failure is not None else 'SUCCESS' if rc == 0 else 'FAILED'
        record = dict(intent, rc=rc, status=status, seconds=round(time.monotonic() - start, 3),
                      pid=process.pid if process is not None else None,
                      process_group=process.pid if process is not None else None,
                      attempt=attempt.name, cleanup=cleanup,
                      stdout=stdout.decode(errors='replace')[-20000:], stderr=stderr.decode(errors='replace')[-20000:],
                      stdout_bytes=len(stdout), stderr_bytes=len(stderr), spawn_error=str(failure) if failure else None,
                      interruption=type(interrupted).__name__ if interrupted is not None else None)
        with (attempt / 'result.json').open('x') as f:
            json.dump(record, f)
        with (E / 'commands.jsonl').open('a') as f:
            f.write(json.dumps(record) + '\n')
    except BaseException as evidence_error:
        if interrupted is not None:
            interrupted.add_note('COMMAND_INTERRUPTION_EVIDENCE_FAILED:' + type(evidence_error).__name__)
            raise interrupted from evidence_error
        raise
    if interrupted is not None:
        raise interrupted
    if timed_out:
        raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr)
    if failure is not None:
        raise failure
    need(rc == 0, 'COMMAND_FAILED:' + str(name) + ':' + record['stderr'][-1600:])
    return stdout


def main():
    global HERE, AREA, BASE, BUILD, E, DXC, SPIRV, ORDINARY_SPV, SHADERS, UPSTREAM, CC, CXX, DIS
    config = configure()
    HERE, AREA = config['extra'], config['area']
    BASE, BUILD, E = config['base'], config['build'], config['evidence']
    DXC, SPIRV, ORDINARY_SPV = config['dxc'], config['spirv'], config['ordinary_spv']
    SHADERS, UPSTREAM = config['shaders'], config['upstream']
    CC, CXX, DIS = config['cc'], config['cxx'], config['spirv_dis']
    patch = config['patch_root'] / 'candidate_s2.patch'
    need(not BUILD.exists() and not E.exists() and not patch.exists() and not patch.is_symlink(), 'OUTPUT_EXISTS')
    need(shutil.disk_usage(AREA).free >= 2 * 1024 ** 3, 'SPACE_BUDGET')
    for n, digest in PINS.items():
        need(sha(BASE / n) == digest, 'BASE_SOURCE_DRIFT:' + n)
    need(sha(BASE / 'shader.bin') == BASE_CODE, 'BASE_CODE')
    header = SHADERS / 'FFX-ParallelSort/FFX_ParallelSort.h'
    need((UPSTREAM / 'ffx-parallelsort/FFX_ParallelSort.h').read_bytes() == header.read_bytes() and
         sha(header) == HEADER_SHA, 'FFX_HEADER_IDENTITY')
    flags, libs = config['flags'], config['libraries']
    sources = sorted(p for p in SHADERS.rglob('*') if p.is_file()) + sorted(p for p in UPSTREAM.rglob('*') if p.is_file())
    paths = [*(BASE / n for n in PINS), BASE / 'shader.bin', ORDINARY_SPV, Path(__file__), *sources, DXC, SPIRV,
             *(Path(x) for x in libs), CC, CXX, DIS, config['config'], *config['verified_files']]
    inputs = {str(p): dict(bytes=p.stat().st_size, sha256=sha(p)) for p in paths}
    # Reserve the separate patch before any producer/output write.
    # Retain a partial patch on failure; never reopen or overwrite it.
    config['patch_root'].mkdir(parents=True)
    with patch.open('x', encoding='utf-8') as patch_file:
        BUILD.mkdir(parents=True)
        (BUILD / 'tmp').mkdir()
        E.mkdir(parents=True)
        with (E / 'inputs.json').open('x') as f:
            f.write(json.dumps(inputs, indent=2) + '\n')
        candidate = candidate_source()
        patch_file.write(''.join(difflib.unified_diff(
            (BASE / 'nvidia_batch_compile.c').read_text().splitlines(True), candidate.splitlines(True),
            fromfile='007P/nvidia_batch_compile.c', tofile='012-S2/nvidia_batch_compile.c')))
    spirv = BUILD / 'spirv'
    spirv.mkdir()
    run([DXC, '-T', 'cs_6_0', '-E', 'FPS_CountReduce', '-O3', '-I', SHADERS, SHADERS / 'ParallelSortCountReduce.hlsl',
         '-Fo', spirv / 'reduce.dxil'], 'dxc-reduce', cwd=SHADERS)
    run([SPIRV, spirv / 'reduce.dxil', '--output', spirv / 'reduce.spv', *CONVERT], 'dxil-spirv-reduce')
    (spirv / 'reduce.spvasm').write_bytes(run([DIS, spirv / 'reduce.spv'], 'spirv-dis-reduce'))
    records = {}
    for mode in ('normal', 'ndebug'):
        out = BUILD / mode
        out.mkdir()
        (out / 'nvidia_batch_compile.c').write_text(candidate)
        for n in ('nvidia_shared_lowering.h', 'nir_shared_range.h'):
            shutil.copy2(BASE / n, out / n)
        run([CC, *flags, *(['-DNDEBUG'] if mode == 'ndebug' else []),
             '-c', out / 'nvidia_batch_compile.c', '-o', out / 'adapter.o'], mode + '-compile')
        run([CXX, out / 'adapter.o', '-Wl,--start-group', *libs, '-Wl,--end-group',
             '-lSPIRV-Tools', '-lz', '-lzstd', '-lm', '-ldl', '-pthread', '-o', out / 'compile-nak'], mode + '-link')
        ordinary = json.loads(run([out / 'compile-nak', '--profile', ORDINARY_PROFILE, ORDINARY_SPV, out / 'ordinary'], mode + '-ordinary'))
        (out / 'ordinary.json').write_text(json.dumps(ordinary, indent=2) + '\n')
        for s in ARTIFACTS:
            need((out / ('ordinary.' + s)).read_bytes() == (BASE / ('shader.' + s)).read_bytes(), 'ORDINARY_PROFILE_CHANGED:' + s)
        need((out / 'ordinary.json').read_bytes() == (BASE / 'shader.json').read_bytes(), 'ORDINARY_JSON')
        meta = json.loads(run([out / 'compile-nak', '--profile', 'ffx-reduce', spirv / 'reduce.spv', out / 'reduce'], mode + '-reduce'))
        (out / 'reduce.json').write_text(json.dumps(meta, indent=2) + '\n')
        records[mode] = dict(compiler_sha256=sha(out / 'compile-nak'), metadata=meta,
                             files={p.name: sha(p) for p in sorted(out.glob('reduce.*'))},
                             ordinary={p.name: sha(p) for p in sorted(out.glob('ordinary.*'))})
    for s in (*ARTIFACTS, 'buffer.nir', 'lowered.nir', 'json'):
        need((BUILD / 'normal' / ('reduce.' + s)).read_bytes() == (BUILD / 'ndebug' / ('reduce.' + s)).read_bytes(), 'NDEBUG:' + s)
    need(all(sha(Path(p)) == v['sha256'] for p, v in inputs.items()), 'INPUT_DRIFT')
    result = dict(status='CPU_COMPILED_NOT_QUALIFIED', gpu='NOT_RUN', task=TASK, records=records,
                  spirv=dict(dxil=sha(spirv / 'reduce.dxil'), spv=sha(spirv / 'reduce.spv')),
                  producer_sha256=sha(Path(__file__)), patch_sha256=sha(config['patch_root'] / 'candidate_s2.patch'))
    (E / 'screen.json').write_text(json.dumps(result, indent=2) + '\n')
    m = records['normal']['metadata']
    print(json.dumps(dict(m['shader_info'], code_bytes=m['code_bytes'], shared=m.get('shared_operations'),
                          proof=m.get('shared_range_proof')), indent=1))


if __name__ == '__main__':
    main()
