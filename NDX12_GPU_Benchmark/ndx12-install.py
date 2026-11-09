#!/usr/bin/python3 -I
"""Installer of the Native DX12 NVIDIA benchmark v21 r12 (release archive 845cb9a3, external starter 8cd0ca34).

Put this file in one folder with the two release files it names (ARCHIVE and STARTER below) and run, from anywhere:

    sudo /usr/bin/python3 -I ndx12-install.py

The installer carries the three trusted SHA-256 values of this release, so nothing is typed by hand. It reads both
files once into memory and checks them against these values. It checks that the system folders it writes to belong
to root and are writable by root only, and that no installed file is a symbolic link. It unpacks into a private
staging folder and has the external starter verify the staged package. Only then does it replace anything. It then
checks the result once more with the installed starter. It prints READY or what blocks the installation; a refusal
leaves the installed version as it was. It never runs anything from the package and never starts GPU work.

Installed (the same layout as the manual steps in the package README):
    /opt/ndx12/<NAME>/                    the package, owned by root
    /usr/local/libexec/ndx12_start.py     the external starter that verifies the package before every start
    /etc/ndx12/v21.manifest.sha256        the trusted MANIFEST.sha256 value the starter checks against
    /usr/local/bin/ndx12-benchmark        the start command: ndx12-benchmark (menu) or ndx12-benchmark --check
    /etc/ndx12/<NAME>.install.json        the install receipt: release name, package revision and the SHA-256 values
                                          checked here; the benchmark names its release in the share file from it

Trust: this file is the trust anchor. Its pins are only as trustworthy as the place this file came from (see
HOW_TO_RUN.md); a checksum downloaded next to the archive or computed from the download adds nothing.
"""
import sys

# -I must hold before any other module is imported: without it Python first searches this file's folder, where a
# planted tarfile.py or hashlib.py would run as root.
if not sys.flags.isolated:
    sys.stderr.write('NOT INSTALLED: run the installer in isolated mode:  sudo /usr/bin/python3 -I ndx12-install.py\n')
    raise SystemExit(2)

import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tarfile  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402

PUBLIC_VERSION = 'v0.1.1'        # proposal for the owner's decision (v0.1.0 is the published r9 release)
PACKAGE_ID = 'v21-r12'           # the package revision; tools/nvidia_desktop.py PACKAGE_ID must be the same
NAME = 'ndx12-native-benchmark-v21-615.78.08-620.70.06'
ARCHIVE = NAME + '.tar.gz'
ARCHIVE_SHA256 = '845cb9a3c2847438953c3db376811897bfe20b2fe7c6e80cc25edade3588852f'
ARCHIVE_BYTES = 2532955
STARTER = 'ndx12_start.py'
STARTER_SHA256 = '8cd0ca349f4535741ae8a673b3aa10de4a0b5f953c283543a453a850337aced5'
STARTER_BYTES = 10958
MANIFEST_SHA256 = '0985df2e38963a6fe7ee02e36bf4eb51672f130c838c05a3de3b45e798d4ef72'

OPT, PACKAGE = '/opt/ndx12', '/opt/ndx12/' + NAME
LIBEXEC, STARTER_PATH = '/usr/local/libexec', '/usr/local/libexec/ndx12_start.py'
ETC, TRUST = '/etc/ndx12', '/etc/ndx12/v21.manifest.sha256'
RECEIPT = '/etc/ndx12/%s.install.json' % NAME     # read by the benchmark (tools/nvidia_desktop.py install_receipt)
RECEIPT_SCHEMA = 'ndx12-install-receipt.v1'
BIN, COMMAND = '/usr/local/bin', '/usr/local/bin/ndx12-benchmark'
RESULTS = '/var/tmp/ndx12-results'
PYTHON = '/usr/bin/python3'
# Folders that must exist, and folders created (mode 0755) when missing; parents come first.
SYSTEM_FOLDERS = ['/', '/usr', '/etc']
CREATED_FOLDERS = ['/usr/local', LIBEXEC, BIN, '/opt', OPT, ETC]
OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK

COMMAND_TEXT = '''#!/bin/sh
# ndx12-benchmark: start the Native DX12 NVIDIA benchmark v21 through its external starter, which checks the
# package against the trusted manifest value, file by file, before anything from the package runs.
# Installed by ndx12-install.py. Usage:
#   ndx12-benchmark            the benchmark menu
#   ndx12-benchmark --check    verify the installation only; starts nothing
#   ndx12-benchmark -- ARGS    pass ARGS unchanged to the package entry point (expert options)
STARTER=/usr/local/libexec/ndx12_start.py
PACKAGE=/opt/ndx12/{name}
TRUST=/etc/ndx12/v21.manifest.sha256
usage() {{
    echo 'usage: ndx12-benchmark            start the benchmark menu'
    echo '       ndx12-benchmark --check    verify the installation only'
    echo '       ndx12-benchmark -- ARGS    pass ARGS to the package entry point'
}}
case "${{1-}}" in
    '') ;;
    --check|--check-only)
        [ "$#" -eq 1 ] || {{ usage >&2; exit 2; }}
        set -- --check-only ;;
    --) ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac
if [ "$(/usr/bin/id -u)" = 0 ]; then
    exec /usr/bin/python3 -I -B "$STARTER" --package "$PACKAGE" --trust "$TRUST" "$@"
fi
if [ ! -x /usr/bin/sudo ]; then
    echo 'ndx12-benchmark: the benchmark needs root and /usr/bin/sudo was not found; run it as root.' >&2
    exit 1
fi
echo 'ndx12-benchmark: the benchmark runs as root; sudo may ask for your password.' >&2
exec /usr/bin/sudo /usr/bin/python3 -I -B "$STARTER" --package "$PACKAGE" --trust "$TRUST" "$@"
'''.format(name=NAME)


class Blocked(Exception):
    """A reason the installation cannot go on; the message is shown to the user as it is. changed: whether this run
    had already replaced installed files (then the installation is incomplete, not untouched)."""

    def __init__(self, message, changed=False):
        super().__init__(message)
        self.changed = changed


def say(text):
    print(text, flush=True)


def lstat(path):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def folder_problem(path, info):
    """None for a folder only root can change, else why not (the starter's rule, without the sticky exception)."""
    if stat.S_ISLNK(info.st_mode):
        return '%s is a symbolic link' % path
    if not stat.S_ISDIR(info.st_mode):
        return '%s is not a folder' % path
    if info.st_uid != 0:
        return '%s belongs to user id %d, not root' % (path, info.st_uid)
    if info.st_mode & 0o022:
        return '%s can be changed by other users (mode %04o)' % (path, stat.S_IMODE(info.st_mode))
    if info.st_mode & (stat.S_ISUID | stat.S_ISGID):
        return '%s has a set-id mode bit (mode %04o)' % (path, stat.S_IMODE(info.st_mode))
    return None


def check_requirements():
    if os.geteuid() != 0:
        raise Blocked('the installer needs root. Run it as:  sudo /usr/bin/python3 -I ndx12-install.py')
    if os.path.realpath(sys.executable) != os.path.realpath(PYTHON):
        raise Blocked('run the installer with %s (the interpreter the benchmark uses), not %s'
                      % (PYTHON, sys.executable))
    gil = getattr(sys, '_is_gil_enabled', lambda: True)()
    if sys.version_info < (3, 13) or not gil:
        raise Blocked('%s is Python %d.%d%s; the benchmark needs CPython 3.13 or newer with the GIL'
                      % (PYTHON, sys.version_info[0], sys.version_info[1], '' if gil else ' without the GIL'))
    if not os.access('/bin/bash', os.X_OK):
        raise Blocked('/bin/bash was not found; the starter runs the package entry point with it')


def read_download(folder, name, size, digest, what):
    """The whole file in memory, checked against the pin of this installer: later changes to the download folder
    cannot reach the bytes that are installed."""
    path = os.path.join(folder, name)
    try:
        fd = os.open(path, OPEN_FLAGS)
    except FileNotFoundError:
        raise Blocked('%s was not found next to the installer (%s). Download it from the same release and put it '
                      'in that folder.' % (name, folder)) from None
    except OSError as error:
        raise Blocked('%s cannot be opened (%s); it must be a regular file, not a link.'
                      % (path, error.strerror or error)) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise Blocked('%s is not a regular file.' % path)
        if info.st_size != size:
            raise Blocked('%s is not %s of this release (%d bytes, expected %d). Download it again from the release; '
                          'a copy from elsewhere will not do.' % (path, what, info.st_size, size))
        chunks, total = [], 0
        while total <= size:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    finally:
        os.close(fd)
    data = b''.join(chunks)
    got = hashlib.sha256(data).hexdigest()
    if len(data) != size or got != digest:
        raise Blocked('%s is not %s of this release (SHA-256 %s, expected %s). Download it again from the release; '
                      'a copy from elsewhere will not do.' % (path, what, got, digest))
    return data


def check_folders():
    """Every folder written to and every folder above them, before anything is written."""
    problems, missing = [], []
    for path in SYSTEM_FOLDERS + CREATED_FOLDERS:
        info = lstat(path)
        if info is None:
            if path in SYSTEM_FOLDERS:
                problems.append('%s does not exist' % path)
            else:
                missing.append(path)
            continue
        problem = folder_problem(path, info)
        if problem:
            problems.append(problem)
    for path, kind in ((PACKAGE, 'folder'), (STARTER_PATH, 'file'), (TRUST, 'file'), (COMMAND, 'file'),
                       (RECEIPT, 'file')):
        info = lstat(path)
        if info is None:
            continue
        if stat.S_ISLNK(info.st_mode):
            problems.append('%s is a symbolic link; nothing of the installation may be a link (remove it: sudo rm %s)'
                            % (path, path))
        elif kind == 'file' and not stat.S_ISREG(info.st_mode):
            problems.append('%s exists and is not a regular file' % path)
        elif kind == 'folder' and not stat.S_ISDIR(info.st_mode):
            problems.append('%s exists and is not a folder' % path)
    # The results folder that the package uses by default: the starter refuses to start if it is unsafe.
    for path in ('/var', '/var/tmp', RESULTS):
        info = lstat(path)
        if info is None:
            break
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 \
                or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX) or (path == RESULTS and info.st_mode & 0o022):
            problems.append('%s must be a folder that only root can change (the benchmark writes its results there)'
                            % path)
    if problems:
        raise Blocked('these folders or files are not safe to install into:\n    ' + '\n    '.join(problems)
                      + '\n  Fix them (they must belong to root and be writable by root only) and run the installer '
                      'again.')
    return missing


def unpack(data, staging):
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            members = archive.getmembers()
            for member in members:
                if not (member.name == NAME or member.name.startswith(NAME + '/')) or not (member.isreg() or member.isdir()):
                    raise Blocked('the archive holds an unexpected entry (%s); it is not this release.' % member.name)
            archive.extractall(staging, members=members, filter='data')
    except (tarfile.TarError, OSError) as error:
        raise Blocked('the archive could not be unpacked (%s).' % error) from None
    with open(os.path.join(staging, NAME, 'MANIFEST.sha256'), 'rb') as stream:
        got = hashlib.sha256(stream.read()).hexdigest()
    if got != MANIFEST_SHA256:
        raise Blocked('the unpacked MANIFEST.sha256 is %s, expected %s.' % (got, MANIFEST_SHA256))
    return os.path.join(staging, NAME)


def write_new(path, data, mode):
    """Create path (it must not exist) with O_EXCL and O_NOFOLLOW, write and flush it to disk. If writing fails, the
    file this call created is removed again; a path that already existed is never touched (O_EXCL refuses it)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
    try:
        try:
            os.fchmod(fd, mode)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
    except BaseException:
        try:
            os.unlink(path)      # created by this call in a root-only folder
        except OSError:
            pass
        raise


def remove_stale(path):
    info = lstat(path)
    if info is not None:
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            raise Blocked('%s is a folder; remove it and run the installer again.' % path)
        os.unlink(path)          # a link is removed, never followed


def starter_check(starter, package, trust):
    """Run the external starter in --check-only mode; it runs nothing from the package. (ok, its message)."""
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
    try:
        done = subprocess.run([PYTHON, '-I', '-B', starter, '--package', package, '--trust', trust, '--check-only'],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, 'the starter could not be run (%s)' % error
    out = (done.stdout + done.stderr).strip()
    return done.returncode == 0 and done.stdout.startswith('PACKAGE VERIFIED: '), out.splitlines()[-1] if out else ''


def sync_folder(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def receipt_text(installer_sha256):
    """The install receipt (JSON, one object): what this installer checked and installed. The archive SHA-256 is the
    pin of this installer, which the downloaded archive matched; an archive cannot carry its own SHA-256, so the
    benchmark takes it from here. installer_sha256: the SHA-256 of this installer file as it was read at the start."""
    return (json.dumps(dict(schema=RECEIPT_SCHEMA, public_version=PUBLIC_VERSION, package_id=PACKAGE_ID, package=NAME,
                            archive=ARCHIVE, archive_sha256=ARCHIVE_SHA256, archive_bytes=ARCHIVE_BYTES,
                            starter_sha256=STARTER_SHA256, manifest_sha256=MANIFEST_SHA256,
                            installer_sha256=installer_sha256, trust_name=os.path.basename(TRUST)),
                       indent=1, sort_keys=True) + '\n').encode()


def own_sha256():
    """SHA-256 of this installer file (recorded in the receipt; this file is the trust anchor, it cannot pin itself)."""
    path = os.path.abspath(__file__)
    try:
        fd = os.open(path, OPEN_FLAGS)
    except OSError as error:
        raise Blocked('the installer cannot read its own file %s (%s).' % (path, error.strerror or error)) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Blocked('%s is not a regular file.' % path)
        digest = hashlib.sha256()
        for chunk in iter(lambda: os.read(fd, 1 << 20), b''):
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def install(folder):
    check_requirements()
    os.umask(0o022)      # tar creates implicit parent folders with the process umask; root's may be 0002
    say('Native DX12 NVIDIA benchmark installer: %s %s (package %s)' % (PUBLIC_VERSION, NAME, PACKAGE_ID))
    receipt = receipt_text(own_sha256())
    archive = read_download(folder, ARCHIVE, ARCHIVE_BYTES, ARCHIVE_SHA256, 'the benchmark archive')
    starter = read_download(folder, STARTER, STARTER_BYTES, STARTER_SHA256, 'the starter')
    say('  downloaded files match this installer (archive %s..., starter %s...)' % (ARCHIVE_SHA256[:12], STARTER_SHA256[:12]))
    missing = check_folders()
    say('  system folders belong to root and only root can change them')

    created, staged, staging = [], [], None
    committed = False
    try:
        for path in missing:
            os.mkdir(path, 0o755)
            os.chmod(path, 0o755)
            created.append(path)
        staging = tempfile.mkdtemp(prefix='.install-', dir=OPT)
        package = unpack(archive, staging)
        new_starter, new_trust, new_command = STARTER_PATH + '.new', TRUST + '.new', COMMAND + '.new'
        new_receipt = RECEIPT + '.new'
        for path in (new_starter, new_trust, new_command, new_receipt):
            remove_stale(path)
        for path, data, mode in ((new_starter, starter, 0o755), (new_trust, (MANIFEST_SHA256 + '\n').encode(), 0o644),
                                 (new_command, COMMAND_TEXT.encode(), 0o755), (new_receipt, receipt, 0o644)):
            try:
                write_new(path, data, mode)
            except OSError as error:
                raise Blocked('%s could not be written (%s).' % (path, error.strerror or error)) from None
            staged.append(path)
        ok, message = starter_check(new_starter, package, new_trust)
        if not ok:
            raise Blocked('the starter refused the unpacked package: %s' % message)
        say('  unpacked package verified by the starter: %s' % message)

        # Keep an installed copy that already verifies (it may hold the saved run_benchmark.conf).
        kept = False
        if lstat(PACKAGE) is not None:
            kept, message = starter_check(new_starter, PACKAGE, new_trust)
        if kept:
            say('  the installed package verifies; it is kept as it is')
        else:
            aside = None
            if lstat(PACKAGE) is not None:
                aside = '%s.replaced-%s' % (PACKAGE, time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
                os.rename(PACKAGE, aside)
            try:
                os.rename(package, PACKAGE)
            except OSError:
                if aside:
                    os.rename(aside, PACKAGE)
                raise
            committed = True
            if aside:
                say('  the installed package did not verify (%s); it was moved to %s' % (message, aside))
        # The receipt goes last: after an interruption before it, the benchmark finds no receipt or the receipt of
        # an earlier installation, whose MANIFEST value is not this package's, and reports the release as unknown.
        for new, final in ((new_starter, STARTER_PATH), (new_trust, TRUST), (new_command, COMMAND),
                           (new_receipt, RECEIPT)):
            os.replace(new, final)
            staged.remove(new)
            committed = True
        for path in (OPT, LIBEXEC, ETC, BIN):
            sync_folder(path)
    except Blocked as reason:
        raise Blocked(str(reason), changed=committed) from None
    except OSError as error:
        raise Blocked('a file operation failed: %s' % error, changed=committed) from None
    finally:
        for path in staged:
            try:
                os.unlink(path)
            except OSError:
                pass
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        if not committed:
            for path in reversed(created):
                try:
                    os.rmdir(path)
                except OSError:
                    pass

    ok, message = starter_check(STARTER_PATH, PACKAGE, TRUST)
    if not ok:
        raise Blocked('the installed files did not verify: %s' % message, changed=True)
    say('  installed: %s, %s, %s, %s, %s' % (PACKAGE, STARTER_PATH, TRUST, COMMAND, RECEIPT))
    say('READY. Start the benchmark with:  ndx12-benchmark')
    say('  (it asks for your password through sudo; ndx12-benchmark --check verifies the installation only)')


def main(argv):
    if argv:
        sys.stderr.write('usage: sudo /usr/bin/python3 -I ndx12-install.py   (no arguments; the two release files '
                         'must be next to it)\n')
        return 2
    try:
        install(os.path.dirname(os.path.abspath(__file__)))
    except Blocked as reason:
        sys.stderr.write('NOT INSTALLED: %s\n' % reason)
        if reason.changed:
            sys.stderr.write('The installation is incomplete: some installed files were already replaced. Fix the '
                             'problem above and run the installer again.\n')
        elif lstat(PACKAGE) is not None:
            sys.stderr.write('Nothing was changed; the installed copy was left as it was. Check it with:  '
                             'ndx12-benchmark --check\n')
        else:
            sys.stderr.write('Nothing was changed.\n')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
