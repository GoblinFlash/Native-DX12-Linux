#!/usr/bin/env python3
"""Pinned dependency acquisition and build for Native DX12 Linux on Ubuntu 26.04.

Subcommands
  fetch     acquire every pinned source into --cache (the only step that uses the
            network); every tree is checked against its full file manifest
  verify    re-check a populated cache without network
  build     copy verified trees into --build-root, build the dependency set and
            write --build-root/deps.json (schema ndx12.ubuntu-deps-result.v1)
  manifest  print the tree manifest of a directory (maintenance helper)

No step installs system packages, writes outside --cache/--build-root or falls
back to a different revision. Run with `python3 -I`.
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK_PATH = HERE / 'deps.lock.json'
LOCK_SCHEMA = 'ndx12.ubuntu-deps-lock.v1'
TREE_SCHEMA = 'ndx12.tree-manifest.v1'
RESULT_SCHEMA = 'ndx12.ubuntu-deps-result.v1'
MAX_JOBS = 4
TARGETS = ('intel', 'rtx', 'amd')
SAFE_PATH = '/usr/bin:/bin'
DXIL_SPIRV_LIBRARIES = ('bc/libllvm-bc.a', 'third_party/libbc-decoder.a', 'libdxil-utils.a', 'libdxil-debug.a')
# Build-root independence: Rust outputs map the build root to this token, and the
# dxil-spirv build uses exactly '$ORIGIN' as RUNPATH instead of absolute build paths.
BUILD_PREFIX_TOKEN = '@NDX12_BUILD@'


class Fail(Exception):
    """A refused or failed step; the message is a stable reason code."""


def need(condition, reason):
    if not condition:
        raise Fail(reason)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path):
    path = Path(path)
    return {'path': str(path), 'sha256': sha256_file(path), 'bytes': path.stat().st_size}


def elf_soname(data):
    """DT_SONAME of a little-endian ELF64 shared object, read from its SHT_DYNAMIC section."""
    need(data[:4] == b'\x7fELF' and data[4] == 2 and data[5] == 1, 'ELF_FORMAT')
    shoff, = struct.unpack_from('<Q', data, 0x28)
    shentsize, shnum = struct.unpack_from('<HH', data, 0x3a)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * shentsize) for i in range(shnum)]
    names = []
    for _, kind, _, _, offset, size, link, _, _, entsize in sections:
        if kind != 6:  # SHT_DYNAMIC
            continue
        strtab = sections[link][4]
        for pos in range(offset, offset + size, entsize):
            tag, value = struct.unpack_from('<qQ', data, pos)
            if tag == 14:  # DT_SONAME
                end = data.index(b'\0', strtab + value)
                names.append(data[strtab + value:end].decode())
    need(len(names) == 1, 'ELF_SONAME')
    return names[0]


def meson_string(value):
    return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"


def write_meson_native_file(out):
    """Meson native file with global rust_args; a file avoids splitting paths that contain spaces."""
    path = Path(out) / 'meson-native-reproducible.ini'
    # Meson machine files reject escaped quotes, so such build roots are refused, not mangled.
    need(not any(c in str(out) for c in "'\\\n"), 'BUILD_ROOT_UNSUPPORTED_CHARACTER')
    remap = '--remap-path-prefix=' + str(out) + '=' + BUILD_PREFIX_TOKEN
    path.write_text('[built-in options]\nrust_args = [' + meson_string(remap) + ']\n')
    return path


def write_json(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)


# ---------------------------------------------------------------- manifests

def scan_tree(root):
    """Return the regular files and symlinks below root (symlinks not followed)."""
    root = Path(root)
    files, links = {}, {}
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in list(dirnames):
            entry = base / name
            if entry.is_symlink():
                links[entry.relative_to(root).as_posix()] = os.readlink(entry)
                dirnames.remove(name)
        for name in filenames:
            entry = base / name
            rel = entry.relative_to(root).as_posix()
            if entry.is_symlink():
                links[rel] = os.readlink(entry)
            elif entry.is_file():
                files[rel] = (entry.stat().st_size, sha256_file(entry))
            else:
                raise Fail('SPECIAL_FILE:' + rel)
    return files, links


def manifest_of(root):
    files, links = scan_tree(root)
    return {'schema': TREE_SCHEMA,
            'files': [[path, size, digest] for path, (size, digest) in sorted(files.items())],
            'symlinks': [[path, target] for path, target in sorted(links.items())]}


def verify_tree(root, manifest):
    """Return a list of differences; empty means the tree matches exactly."""
    need(manifest.get('schema') == TREE_SCHEMA, 'MANIFEST_SCHEMA')
    files, links = scan_tree(root)
    expected = {path: (size, digest) for path, size, digest in manifest['files']}
    expected_links = {path: target for path, target in manifest['symlinks']}
    problems = []
    for path in sorted(set(expected) | set(files)):
        if path not in files:
            problems.append('MISSING:' + path)
        elif path not in expected:
            problems.append('EXTRA:' + path)
        elif files[path] != expected[path]:
            problems.append('CONTENT:' + path)
    for path in sorted(set(expected_links) | set(links)):
        if links.get(path) != expected_links.get(path):
            problems.append('SYMLINK:' + path)
    return problems


# ---------------------------------------------------------------- lock

def load_lock():
    raw = LOCK_PATH.read_bytes()
    lock = json.loads(raw)
    need(lock.get('schema') == LOCK_SCHEMA, 'LOCK_SCHEMA')
    names = [source['name'] for source in lock['sources']]
    need(len(names) == len(set(names)), 'LOCK_DUPLICATE_SOURCE')
    manifests = {}
    for source in lock['sources']:
        need(source['kind'] in ('git', 'tarball', 'file-set'), 'LOCK_KIND:' + source['name'])
        path = HERE / source['manifest']
        need(path.is_file(), 'MANIFEST_MISSING:' + source['name'])
        need(sha256_file(path) == source['manifest_sha256'], 'MANIFEST_PIN:' + source['name'])
        manifests[source['name']] = json.loads(path.read_bytes())
    blobs = {blob['sha256']: blob for blob in lock['blobs']}
    need(len(blobs) == len(lock['blobs']), 'LOCK_DUPLICATE_BLOB')
    return lock, manifests, hashlib.sha256(raw).hexdigest()


def git_env(home):
    env = {'PATH': SAFE_PATH, 'HOME': str(home), 'LANG': 'C.UTF-8',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0',
           'GIT_CONFIG_GLOBAL': '/dev/null'}
    return env


def run_git(args, cwd, env, log):
    result = subprocess.run(['git', *args], cwd=cwd, env=env, capture_output=True, text=True)
    log.append({'argv': ['git', *args], 'cwd': str(cwd), 'rc': result.returncode,
                'stderr_tail': result.stderr[-1500:]})
    need(result.returncode == 0, 'GIT_FAILED:' + ' '.join(args[:2]))
    return result.stdout


# ---------------------------------------------------------------- fetch

def fetch_git_checkout(url, commit, dest, env, log):
    dest.mkdir(parents=True, exist_ok=True)
    run_git(['init', '-q'], dest, env, log)
    # Local mirrors (overrides) may hold the commit without advertising it.
    run_git(['-c', 'protocol.file.allow=always', 'fetch', '-q', '--depth', '1', '--no-tags',
             url, commit], dest, env, log)
    run_git(['-c', 'advice.detachedHead=false', 'checkout', '-q', '--detach', 'FETCH_HEAD'], dest, env, log)
    head = run_git(['rev-parse', 'HEAD'], dest, env, log).strip()
    need(head == commit, 'GIT_COMMIT_MISMATCH:' + commit)


def fetch_git_source(source, work, overrides, env, log):
    url = overrides.get(source['name'], source['url'])
    fetch_git_checkout(url, source['commit'], work, env, log)
    for sub in source.get('submodules', []):
        parent = work / sub['parent'] if sub.get('parent') else work
        rel = Path(sub['path']).relative_to(sub['parent']) if sub.get('parent') else Path(sub['path'])
        listed = run_git(['ls-tree', 'HEAD', rel.as_posix()], parent, env, log).split()
        need(len(listed) >= 3 and listed[1] == 'commit' and listed[2] == sub['commit'],
             'GITLINK_MISMATCH:' + sub['path'])
        target = work / sub['path']
        need(target.is_dir() and not any(target.iterdir()), 'SUBMODULE_DIR:' + sub['path'])
        key = source['name'] + ':' + sub['path']
        fetch_git_checkout(overrides.get(key, sub['url']), sub['commit'], target, env, log)
    for git_dir in sorted(work.rglob('.git'), key=lambda p: len(p.parts), reverse=True):
        if git_dir.is_dir() and not git_dir.is_symlink():
            shutil.rmtree(git_dir)
        else:
            git_dir.unlink()


def download(url, dest, sha256, size, overrides):
    local = overrides.get(sha256)
    if local:
        shutil.copyfile(local, dest)
    else:
        need(url.startswith('https://'), 'URL_NOT_HTTPS:' + url)
        request = urllib.request.Request(url, headers={'User-Agent': 'ndx12-prepare-deps/1'})
        with urllib.request.urlopen(request, timeout=120) as response, open(dest, 'wb') as out:
            shutil.copyfileobj(response, out, 1 << 20)
    need(dest.stat().st_size == size, 'BLOB_SIZE:' + url)
    need(sha256_file(dest) == sha256, 'BLOB_SHA256:' + url)


def blob_path(cache, sha256):
    return cache / 'files' / sha256


def ensure_blob(cache, blob, overrides):
    target = blob_path(cache, blob['sha256'])
    if target.is_file() and sha256_file(target) == blob['sha256']:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.part')
    download(blob['url'], tmp, blob['sha256'], blob['bytes'], overrides)
    os.replace(tmp, target)
    return target


def extract_tarball(archive, work, strip):
    with tarfile.open(archive) as tar:
        members = []
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if len(parts) <= strip:
                continue
            member.name = Path(*parts[strip:]).as_posix()
            members.append(member)
        tar.extractall(work, members=members, filter='data')


def fetch_source(source, manifest, cache, args_overrides, tree_overrides, file_overrides, log):
    tree = cache / 'trees' / source['name']
    if tree.is_dir() and not verify_tree(tree, manifest):
        log.append({'source': source['name'], 'status': 'ALREADY_VERIFIED'})
        return 'ALREADY_VERIFIED'
    need(not tree.exists(), 'CACHE_TREE_DIFFERS:' + source['name'])
    work = cache / 'tmp' / (source['name'] + '.' + str(os.getpid()))
    if work.exists():
        shutil.rmtree(work)
    work.parent.mkdir(parents=True, exist_ok=True)
    home = cache / 'tmp' / ('home.' + str(os.getpid()))
    home.mkdir(parents=True, exist_ok=True)
    method = 'upstream'
    if source['name'] in tree_overrides:
        # A pre-extracted copy (for example a DXC prefix) is accepted only if
        # it matches the full pinned manifest; the archive digest is then not exercised.
        shutil.copytree(tree_overrides[source['name']], work, symlinks=True)
        method = 'tree-override'
    elif source['kind'] == 'git':
        fetch_git_source(source, work, args_overrides, git_env(home), log)
        method = 'git-override' if source['name'] in args_overrides else 'git'
    elif source['kind'] == 'tarball':
        archive = ensure_blob(cache, source['archive'], file_overrides)
        work.mkdir()
        extract_tarball(archive, work, source['archive'].get('strip_components', 0))
        method = 'tarball'
    else:
        work.mkdir()
        for item in source['files']:
            dest = work / item['path']
            dest.parent.mkdir(parents=True, exist_ok=True)
            download(item['url'], dest, item['sha256'], item['bytes'], file_overrides)
        method = 'file-set'
    problems = verify_tree(work, manifest)
    if problems:
        log.append({'source': source['name'], 'status': 'MANIFEST_MISMATCH', 'problems': problems[:40],
                    'problem_count': len(problems)})
        raise Fail('MANIFEST_MISMATCH:' + source['name'])
    tree.parent.mkdir(parents=True, exist_ok=True)
    os.replace(work, tree)
    shutil.rmtree(home, ignore_errors=True)
    log.append({'source': source['name'], 'status': 'VERIFIED', 'method': method,
                'files': len(manifest['files']), 'symlinks': len(manifest['symlinks'])})
    return method


def parse_pairs(values, label):
    result = {}
    for value in values or []:
        key, sep, path = value.partition('=')
        need(sep and key and path, label + '_SYNTAX')
        need(Path(path).is_absolute(), label + '_NOT_ABSOLUTE:' + key)
        result[key] = path
    return result


def cmd_fetch(args):
    lock, manifests, lock_sha = load_lock()
    cache = Path(args.cache)
    need(cache.is_absolute(), 'CACHE_NOT_ABSOLUTE')
    cache.mkdir(parents=True, exist_ok=True)
    git_overrides = parse_pairs(args.git_mirror, 'GIT_MIRROR')
    tree_overrides = parse_pairs(args.tree_override, 'TREE_OVERRIDE')
    file_overrides = {}
    for path in args.file_override or []:
        need(Path(path).is_absolute() and Path(path).is_file(), 'FILE_OVERRIDE:' + path)
        file_overrides[sha256_file(path)] = path
    selected = set(args.only.split(',')) if args.only else None
    log, methods = [], {}
    started = time.time()
    try:
        for blob in lock['blobs']:
            ensure_blob(cache, blob, file_overrides)
            methods['blob:' + blob['name']] = 'override' if blob['sha256'] in file_overrides else 'download'
        for source in lock['sources']:
            if selected and source['name'] not in selected:
                continue
            methods[source['name']] = fetch_source(source, manifests[source['name']], cache, git_overrides,
                                                   tree_overrides, file_overrides, log)
        status = 'PASS'
    except Fail as error:
        status = 'FAIL:' + str(error)
    receipt = {'schema': 'ndx12.ubuntu-deps-fetch.v1', 'status': status, 'lock_sha256': lock_sha,
               'methods': methods, 'seconds': round(time.time() - started, 1), 'log': log}
    write_json(cache / 'fetch-receipt.json', receipt)
    print(json.dumps({'status': status, 'methods': methods}, indent=2))
    return 0 if status == 'PASS' else 1


def cmd_verify(args):
    lock, manifests, lock_sha = load_lock()
    cache = Path(args.cache)
    report = {}
    for blob in lock['blobs']:
        path = blob_path(cache, blob['sha256'])
        report['blob:' + blob['name']] = 'OK' if path.is_file() and sha256_file(path) == blob['sha256'] else 'BAD'
    for source in lock['sources']:
        tree = cache / 'trees' / source['name']
        if not tree.is_dir():
            report[source['name']] = 'MISSING'
            continue
        problems = verify_tree(tree, manifests[source['name']])
        report[source['name']] = 'OK' if not problems else 'BAD:' + ';'.join(problems[:5])
    ok = all(value == 'OK' for value in report.values())
    print(json.dumps({'status': 'PASS' if ok else 'FAIL', 'lock_sha256': lock_sha, 'entries': report}, indent=2))
    return 0 if ok else 1


# ---------------------------------------------------------------- build

class Runner:
    def __init__(self, root, jobs, offline, extra_path=()):
        need(all(os.pathsep not in directory for directory in extra_path), 'EXTRA_PATH_SEPARATOR')
        self.root = root
        self.jobs = jobs
        self.offline = offline
        self.unshare = None
        if offline:
            launcher = shutil.which('unshare', path=SAFE_PATH)
            need(launcher, 'UNSHARE_MISSING')
            self.unshare = str(Path(launcher).resolve(strict=True))
        self.logs = root / 'logs'
        self.logs.mkdir(parents=True, exist_ok=True)
        self.records = []
        home = root / 'home'
        tmp = root / 'tmp'
        home.mkdir(exist_ok=True)
        tmp.mkdir(exist_ok=True)
        self.env = {'PATH': os.pathsep.join([*extra_path, SAFE_PATH]), 'HOME': str(home), 'TMPDIR': str(tmp), 'LANG': 'C.UTF-8',
                    'LC_ALL': 'C.UTF-8', 'CC': 'gcc-15', 'CXX': 'g++-15',
                    'CARGO_HOME': str(home / 'cargo'), 'XDG_CACHE_HOME': str(home / 'cache'),
                    'SOURCE_DATE_EPOCH': '0'}

    def execute(self, argv, **kwargs):
        """Run tools and builds through the same trusted offline boundary."""
        argv = [str(item) for item in argv]
        full = ([self.unshare, '-rn', '--'] if self.offline else []) + argv
        return subprocess.run(full, **kwargs)

    def run(self, phase, argv, cwd=None, extra_env=None, capture=False):
        env = dict(self.env)
        env.update(extra_env or {})
        argv = [str(item) for item in argv]
        log_path = self.logs / (phase + '.log')
        started = time.time()
        with open(log_path, 'wb') as log:
            result = self.execute(argv, cwd=cwd, env=env, stdout=subprocess.PIPE if capture else log,
                                  stderr=log)
        record = {'phase': phase, 'argv': argv, 'cwd': str(cwd) if cwd else None, 'rc': result.returncode,
                  'seconds': round(time.time() - started, 1), 'log': str(log_path),
                  'network_namespace': 'isolated' if self.offline else 'host'}
        self.records.append(record)
        write_json(self.root / 'commands.json', self.records)
        need(result.returncode == 0, 'PHASE_FAILED:' + phase)
        return result.stdout if capture else None


TOOLS = [('cc', 'gcc-15'), ('cxx', 'g++-15'), ('rustc', 'rustc'), ('bindgen', 'bindgen'),
         ('cbindgen', 'cbindgen'), ('meson', 'meson'), ('ninja', 'ninja'), ('cmake', 'cmake'),
         ('llvm_config', 'llvm-config-21'), ('pkg_config', 'pkg-config'), ('python', 'python3'),
         ('spirv_dis', 'spirv-dis'), ('patch', 'patch'), ('bison', 'bison'), ('flex', 'flex'),
         ('git', 'git'), ('unshare', 'unshare'), ('nm', 'nm'), ('ar', 'ar')]


def toolchain(runner):
    found, missing = {}, []
    for key, name in TOOLS:
        path = runner.unshare if key == 'unshare' and runner.offline else shutil.which(name, path=runner.env['PATH'])
        if not path:
            missing.append(name)
            continue
        path = os.path.abspath(path)
        real = Path(path).resolve()
        version = runner.execute([path, '--version'], env=runner.env, capture_output=True, text=True)
        need(version.returncode == 0, 'TOOL_VERSION_FAILED:' + name)
        found[key] = {'name': name, 'path': path, 'resolved': str(real), 'sha256': sha256_file(real),
                      'bytes': real.stat().st_size,
                      'version': (version.stdout or version.stderr).strip().splitlines()[0:1]}
    return found, missing


def apt_report(lock):
    names = [row['package'] for row in lock['apt_packages']]
    result = subprocess.run(['dpkg-query', '-W', '-f=${Package}\t${Version}\t${db:Status-Abbrev}\n', *names],
                            env={'PATH': SAFE_PATH, 'LANG': 'C'}, capture_output=True, text=True)
    installed = {}
    for line in result.stdout.splitlines():
        package, version, status = (line.split('\t') + ['', ''])[:3]
        if status.startswith('ii'):
            installed[package] = version
    rows = []
    for row in lock['apt_packages']:
        have = installed.get(row['package'])
        rows.append({'package': row['package'], 'observed_reference': row['version'], 'installed': have,
                     'state': 'MISSING' if have is None else ('SAME' if have == row['version'] else 'DIFFERENT')})
    return rows


def copy_tree(cache, name, dest, manifest):
    source = cache / 'trees' / name
    need(source.is_dir(), 'CACHE_MISSING:' + name)
    problems = verify_tree(source, manifest)
    need(not problems, 'CACHE_TREE_CHANGED:' + name)
    shutil.copytree(source, dest, symlinks=True)
    return str(dest)


def place_crates(lock, cache, mesa_source):
    packagecache = mesa_source / 'subprojects' / 'packagecache'
    packagecache.mkdir(parents=True, exist_ok=True)
    placed = []
    for blob in lock['blobs']:
        if blob.get('use') != 'mesa-wrap':
            continue
        path = blob_path(cache, blob['sha256'])
        need(path.is_file() and sha256_file(path) == blob['sha256'], 'CRATE_MISSING:' + blob['name'])
        shutil.copyfile(path, packagecache / blob['filename'])
        placed.append(blob['filename'])
    return placed


def package_file(package_root, rel, expected_sha=None):
    path = (package_root / rel).resolve(strict=True)
    need(path.is_relative_to(package_root), 'PACKAGE_PATH_ESCAPE:' + rel)
    if expected_sha:
        need(sha256_file(path) == expected_sha, 'PACKAGE_FILE_SHA:' + rel)
    return path


def build_ffx_base(lock, runner, package_root, cache, out, dxc_bin, dxil_spirv_bin, mesa_source, mesa_build):
    spec = lock['ffx_base']
    base = out / 'ffx-base'
    for sub in ('upstream/ffx-parallelsort', 'shaders/FFX-ParallelSort', 'base', 'extra'):
        (base / sub).mkdir(parents=True, exist_ok=True)
    header_tree = cache / 'trees' / 'ffx-parallelsort'
    header = header_tree / 'ffx-parallelsort' / 'FFX_ParallelSort.h'
    shutil.copyfile(header, base / 'upstream/ffx-parallelsort/FFX_ParallelSort.h')
    shutil.copyfile(header, base / 'shaders/FFX-ParallelSort/FFX_ParallelSort.h')
    for item in spec['package_copies']:
        source = package_file(package_root, item['from'], item['sha256'])
        shutil.copyfile(source, base / item['to'])
    produce = spec['ordinary_spv']
    hlsl = package_file(package_root, produce['hlsl'], produce['hlsl_sha256'])
    work = out / 'ffx-base-work'
    work.mkdir(exist_ok=True)
    runner.run('ffx-ordinary-dxc', [dxc_bin, *produce['dxc_args'], hlsl, '-Fo', work / 'ordinary.dxil'])
    runner.run('ffx-ordinary-spirv', [dxil_spirv_bin, work / 'ordinary.dxil', '--output', base / 'ordinary.spv',
                                      *produce['converter_args']])
    need(sha256_file(base / 'ordinary.spv') == produce['expected_sha256'], 'ORDINARY_SPV_DIFFERS')
    # Base producer: the pinned base adapter compiled against fresh Mesa reproduces the
    # expected baseline artifacts; a difference is a failure, never a substitution.
    recipe = json.loads(package_file(package_root, spec['recipe'], spec['recipe_sha256']).read_bytes())
    roots = {'mesa_build': str(mesa_build), 'mesa_source': str(mesa_source)}
    flags = [flag.format_map(roots) for flag in recipe['compile_flags']]
    libraries = []
    for item in recipe['libraries']:
        need(item.get('root') == 'mesa_build', 'FFX_LIBRARY_ROOT')
        libraries.append(str(mesa_build / item['path']))
    runner.run('ffx-base-compile', ['gcc-15', *flags, '-I' + str(base / 'base'), '-c',
                                    base / 'base/nvidia_batch_compile.c', '-o', work / 'base.o'])
    runner.run('ffx-base-link', ['g++-15', work / 'base.o', '-Wl,--start-group', *libraries, '-Wl,--end-group',
                                 *spec['link_libraries'], '-o', work / 'compile-nak'])
    stdout = runner.run('ffx-base-produce', [work / 'compile-nak', '--profile', spec['ordinary_profile'],
                                             base / 'ordinary.spv', work / 'shader'], capture=True)
    # The adapter reports its program description on stdout; the baseline stores it indented.
    (work / 'shader.json').write_text(json.dumps(json.loads(stdout), indent=2) + '\n')
    for name, expected in spec['expected_baselines'].items():
        produced = work / name
        need(produced.is_file() and sha256_file(produced) == expected, 'BASELINE_DIFFERS:' + name)
        shutil.copyfile(produced, base / 'base' / name)
    return base


def cmd_build(args):
    lock, manifests, lock_sha = load_lock()
    package_root = Path(args.package_root)
    cache = Path(args.cache)
    out = Path(args.build_root)
    for label, path in (('PACKAGE_ROOT', package_root), ('CACHE', cache), ('BUILD_ROOT', out)):
        need(path.is_absolute(), label + '_NOT_ABSOLUTE')
    package_root = package_root.resolve(strict=True)
    need(1 <= args.jobs <= MAX_JOBS, 'JOBS_RANGE')
    targets = tuple(t for t in args.targets.split(',') if t)
    need(targets and all(t in TARGETS for t in targets), 'TARGETS')
    need(not out.exists() or (out.is_dir() and not any(out.iterdir())), 'BUILD_ROOT_NOT_EMPTY')
    out.mkdir(parents=True, exist_ok=True)
    out = out.resolve()
    need(not out.is_relative_to(package_root) and not package_root.is_relative_to(out), 'BUILD_ROOT_OVERLAP')
    extra_path = [str(Path(p)) for p in (args.extra_path or [])]
    need(all(Path(p).is_absolute() and Path(p).is_dir() for p in extra_path), 'EXTRA_PATH')
    result = {'schema': RESULT_SCHEMA, 'status': 'IN_PROGRESS', 'lock_sha256': lock_sha, 'targets': list(targets),
              'jobs': args.jobs, 'offline': args.offline, 'package_root': str(package_root),
              'build_root': str(out), 'cache': str(cache), 'extra_path': extra_path}
    started = time.time()
    try:
        runner = Runner(out, args.jobs, args.offline, extra_path)
        tools, missing = toolchain(runner)
        result['toolchain'] = tools
        result['apt'] = apt_report(lock)
        need(not missing, 'TOOLS_MISSING:' + ','.join(missing))
        src = out / 'src'
        src.mkdir()
        j = str(args.jobs)
        pins = {s['name']: s.get('commit') or s.get('archive', {}).get('sha256') or s['manifest_sha256']
                for s in lock['sources']}
        result['pins'] = pins
        dxc = Path(copy_tree(cache, 'dxc', src / 'dxc', manifests['dxc']))
        result['dxc'] = {'bin': file_identity(dxc / 'bin/dxc'), 'libdir': str(dxc / 'lib')}
        dxil_src = Path(copy_tree(cache, 'dxil-spirv', src / 'dxil-spirv', manifests['dxil-spirv']))
        dxil_build = out / 'dxil-spirv-build'
        native = write_meson_native_file(out)
        result['reproducibility'] = {'build_prefix_token': BUILD_PREFIX_TOKEN,
                                     'meson_native_file': file_identity(native),
                                     'cmake_rpath': {'CMAKE_BUILD_WITH_INSTALL_RPATH': 'ON',
                                                     'CMAKE_INSTALL_RPATH': '$ORIGIN'}}
        # Build with the install RPATH: with install(TARGETS) and a plain build RPATH, CMake pads
        # the RUNPATH ('$ORIGIN:'), whose empty entry means the current directory.
        runner.run('dxil-spirv-config', ['cmake', '-S', dxil_src, '-B', dxil_build, '-G', 'Ninja',
                                         '-DCMAKE_BUILD_TYPE=Release', '-DDXIL_SPIRV_CLI=ON',
                                         '-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON', '-DCMAKE_INSTALL_RPATH=$ORIGIN'])
        runner.run('dxil-spirv-build', ['cmake', '--build', dxil_build, '-j', j, '--target', 'llvm-bc',
                                        'bc-decoder', 'dxil-utils', 'dxil-debug', 'dxil-spirv',
                                        'dxil-spirv-c-shared'])
        result['dxil_spirv'] = {'source': str(dxil_src), 'build': str(dxil_build),
                                'executable': file_identity(dxil_build / 'dxil-spirv'),
                                'c_shared': file_identity(dxil_build / 'libdxil-spirv-c-shared.so'),
                                'libraries': {t: file_identity(dxil_build / t) for t in DXIL_SPIRV_LIBRARIES}}
        if 'rtx' in targets or 'amd' in targets:
            mesa_src = Path(copy_tree(cache, 'mesa', src / 'mesa', manifests['mesa']))
            result['mesa_wraps'] = place_crates(lock, cache, mesa_src)
        if 'rtx' in targets:
            nv = Path(copy_tree(cache, 'nvidia-open-gpu-kernel-modules-headers', src / 'nvidia-headers',
                                manifests['nvidia-open-gpu-kernel-modules-headers']))
            result['nvidia_headers'] = {'root': str(nv)}
            copy_tree(cache, 'ffx-parallelsort', out / 'ffx-upstream', manifests['ffx-parallelsort'])
            mesa_rtx = out / 'mesa-rtx-build'
            runner.run('mesa-rtx-config', ['meson', 'setup', '--native-file', native, mesa_rtx, mesa_src,
                                           *lock['meson']['rtx']])
            runner.run('mesa-rtx-build', ['ninja', '-C', mesa_rtx, '-j', j, *lock['meson']['rtx_targets']])
            result['mesa_rtx'] = {'source': str(mesa_src), 'build': str(mesa_rtx),
                                  'libraries': {t: file_identity(mesa_rtx / t) for t in lock['meson']['rtx_targets']},
                                  'compile_commands': str(mesa_rtx / 'compile_commands.json')}
            ffx = build_ffx_base(lock, runner, package_root, cache, out, dxc / 'bin/dxc', dxil_build / 'dxil-spirv',
                                 mesa_src, mesa_rtx)
            result['ffx_base'] = {'root': str(ffx), 'files': {p.relative_to(ffx).as_posix(): sha256_file(p)
                                                               for p in sorted(ffx.rglob('*')) if p.is_file()}}
        if 'amd' in targets:
            drm_src = Path(copy_tree(cache, 'libdrm', src / 'libdrm', manifests['libdrm']))
            drm_build = out / 'libdrm-build'
            prefix = out / 'prefix' / 'libdrm-2.4.133'
            runner.run('libdrm-config', ['meson', 'setup', drm_build, drm_src, '--prefix=' + str(prefix),
                                         *lock['meson']['libdrm']])
            runner.run('libdrm-install', ['ninja', '-C', drm_build, '-j', j, 'install'])
            pcdirs = sorted({str(p.parent) for p in prefix.rglob('libdrm_amdgpu.pc')})
            need(len(pcdirs) == 1, 'LIBDRM_PKGCONFIG')
            version = runner.run('libdrm-version', ['pkg-config', '--modversion', 'libdrm_amdgpu'],
                                 extra_env={'PKG_CONFIG_PATH': pcdirs[0], 'PKG_CONFIG_LIBDIR': pcdirs[0]},
                                 capture=True).decode().strip()
            need(version == '2.4.133', 'LIBDRM_VERSION:' + version)
            result['libdrm'] = {'prefix': str(prefix), 'pkgconfig': pcdirs[0], 'version': version}
            amd_build = out / 'mesa-amd-build'
            runner.run('mesa-amd-config', ['meson', 'setup', '--native-file', native, amd_build, mesa_src,
                                           '--pkg-config-path=' + pcdirs[0], *lock['meson']['amd']])
            runner.run('mesa-amd-build', ['ninja', '-C', amd_build, '-j', j, *lock['meson']['amd_targets']])
            result['mesa_amd'] = {'source': str(mesa_src), 'build': str(amd_build),
                                  'libraries': {t: file_identity(amd_build / t) for t in lock['meson']['amd_targets']}}
        if 'intel' in targets:
            dxh = Path(copy_tree(cache, 'directx-headers', src / 'directx-headers', manifests['directx-headers']))
            result['directx_headers'] = {'root': str(dxh), 'include': str(dxh / 'include')}
            intel_src = Path(copy_tree(cache, 'mesa', src / 'mesa-intel', manifests['mesa']))
            result['mesa_intel_wraps'] = place_crates(lock, cache, intel_src)
            applied = []
            for item in lock['intel_patches']:
                patch = package_file(package_root, item['path'], item.get('sha256'))
                runner.run('intel-patch-' + Path(item['path']).stem,
                           ['patch', '-p1', '--forward', '--no-backup-if-mismatch', '-i', patch], cwd=intel_src)
                applied.append(file_identity(patch))
            probes = package_file(package_root, lock['intel_probe_root'])
            need(probes.is_dir(), 'INTEL_PROBE_ROOT')
            intel_build = out / 'mesa-intel-build'
            options = ['-Dndx12_package_root=' + str(package_root),
                       '-Dndx12_sdk_root=' + str(dxh / 'include'),
                       '-Dndx12_converter_source=' + str(dxil_src),
                       '-Dndx12_converter_build=' + str(dxil_build),
                       '-Dndx12_probe_root=' + str(probes)]
            runner.run('mesa-intel-config', ['meson', 'setup', '--native-file', native, intel_build, intel_src,
                                             *lock['meson']['intel'], *options])
            # Intel targets use RUNPATH $ORIGIN: place the verified converter library beside them
            # under its SONAME before linking, so the link and the later loader resolve it there.
            c_shared = result['dxil_spirv']['c_shared']
            data = Path(c_shared['path']).read_bytes()
            need(hashlib.sha256(data).hexdigest() == c_shared['sha256'] and len(data) == c_shared['bytes'],
                 'CONVERTER_PIN')
            soname = elf_soname(data)
            need(soname.startswith('libdxil-spirv-c-shared.so.') and '/' not in soname, 'CONVERTER_SONAME')
            gallium = intel_build / 'src' / 'gallium'
            gallium.mkdir(parents=True, exist_ok=True)
            converter_copy = gallium / soname
            with converter_copy.open('xb') as stream:
                stream.write(data)
            converter_copy.chmod(0o755)
            need(sha256_file(converter_copy) == c_shared['sha256'], 'CONVERTER_COPY_PIN')
            runner.run('mesa-intel-build', ['ninja', '-C', intel_build, '-j', j, *lock['meson']['intel_targets']])
            result['mesa_intel'] = {'source': str(intel_src), 'build': str(intel_build), 'patches': applied,
                                    'meson_options': options,
                                    'converter_copy': {'soname': soname, **file_identity(converter_copy)},
                                    'outputs': {t: file_identity(intel_build / t)
                                                for t in lock['meson']['intel_targets']}}
        result['status'] = 'PASS'
    except Fail as error:
        result['status'] = 'FAIL:' + str(error)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        result['status'] = 'FAIL:' + type(error).__name__ + ':' + str(error)[:300]
    result['seconds'] = round(time.time() - started, 1)
    write_json(out / 'deps.json', result)
    print(json.dumps({'status': result['status'], 'deps_json': str(out / 'deps.json'),
                      'seconds': result['seconds']}, indent=2))
    return 0 if result['status'] == 'PASS' else 1


def cmd_manifest(args):
    print(json.dumps(manifest_of(Path(args.root)), indent=1, sort_keys=True))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    fetch = sub.add_parser('fetch', help='acquire pinned sources into the cache')
    fetch.add_argument('--cache', required=True)
    fetch.add_argument('--only', help='comma-separated source names')
    fetch.add_argument('--git-mirror', action='append', metavar='NAME[:SUBPATH]=PATH',
                       help='use a local git repository instead of the upstream URL')
    fetch.add_argument('--tree-override', action='append', metavar='NAME=DIR',
                       help='accept an extracted tree that matches the full manifest')
    fetch.add_argument('--file-override', action='append', metavar='PATH',
                       help='local file used for the pinned blob with the same SHA-256')
    verify = sub.add_parser('verify', help='verify a populated cache')
    verify.add_argument('--cache', required=True)
    build = sub.add_parser('build', help='build the dependency set')
    build.add_argument('--package-root', required=True)
    build.add_argument('--cache', required=True)
    build.add_argument('--build-root', required=True)
    build.add_argument('--jobs', type=int, default=2)
    build.add_argument('--targets', default='intel,rtx,amd')
    build.add_argument('--offline', action='store_true', help='run tool version probes and build commands in a new network namespace')
    build.add_argument('--extra-path', action='append', metavar='DIR',
                       help='explicit tool directory searched before /usr/bin (for example an unpacked cbindgen .deb)')
    manifest = sub.add_parser('manifest', help='print a tree manifest')
    manifest.add_argument('root')
    args = parser.parse_args(argv)
    try:
        return {'fetch': cmd_fetch, 'verify': cmd_verify, 'build': cmd_build, 'manifest': cmd_manifest}[args.command](args)
    except Fail as error:
        print(json.dumps({'status': 'FAIL:' + str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
