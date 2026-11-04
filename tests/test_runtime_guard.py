"""CPU tests of the real verifier audit hook, isolated in child processes.

Only task-owned fixtures are touched. The deliberately empty installation is
rejected after hook setup; no runtime module, native library or device is loaded.
This is an audit-event guard, not a sandbox against arbitrary Python/native code.
"""
import errno
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PACKAGE=Path(__file__).resolve().parents[1]
CASES=("read", "read_fd", "ancestor_path", "ancestor_read", "read_outside", "write_text", "write_fd", "readwrite_fd",
       "create_readonly", "truncate_readonly", "append_fd", "fdopen_write",
       "remove", "rename", "chmod", "truncate", "mkdir", "rmdir", "link", "symlink", "utime", "posix_spawn", "exec", "fork", "forkpty", "kill", "import_source")


def probe(case, verifier, parent):
    directory=Path(tempfile.mkdtemp(prefix="audit-probe-",dir=parent))
    roots={name:directory/name.lower() for name in ("PACKAGE","ARTIFACTS","HEADERS")}
    for root in roots.values():root.mkdir()
    root=roots["PACKAGE"]
    victim=root/"victim";victim.write_bytes(b"KEEP")
    victim.chmod(0o600)
    empty=root/"empty";empty.mkdir()
    target=root/"target"
    outside=directory/"outside";outside.write_bytes(b"OUTSIDE")
    receipt=directory/"receipt.json"
    receipt.write_text(json.dumps({"roots":{k:str(v) for k,v in roots.items()},"files":[]}))
    source=root/"fresh_module.py";source.write_text("VALUE=73\n")
    sys.dont_write_bytecode=True
    spec=importlib.util.spec_from_file_location("guard_subject",verifier)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.dont_write_bytecode=False
    descriptor=os.open(victim,os.O_RDWR) if case=="fdopen_write" else None
    old_argv=sys.argv;sys.argv=[str(verifier),str(receipt)]
    try:
        try:module.main()
        except ValueError as error:
            if str(error)!="INSTALLATION_COUNT":raise
        else:raise AssertionError("SETUP_MUST_REJECT_EMPTY_INSTALLATION")
    finally:sys.argv=old_argv
    def opened(flags,path=victim):
        fd=os.open(path,flags,0o600)
        os.close(fd)
    def spawn():
        pid=os.posix_spawn("/usr/bin/true",["true"],{})
        os.waitpid(pid,0)
    def fork(pty=False):
        if pty:pid,fd=os.forkpty()
        else:pid=os.fork();fd=None
        if pid==0:os._exit(0)
        if fd is not None:os.close(fd)
        os.waitpid(pid,0)
    def execute():
        os.execv(sys.executable,[sys.executable,"-I","-c",
                 "import sys; sys.stderr.write('GUARD_ALLOWED:exec\\n'); sys.exit(41)"])
    def import_source():
        spec=importlib.util.spec_from_file_location("fresh_module",source)
        loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded)
        if loaded.VALUE!=73 or (root/"__pycache__").exists():
            raise AssertionError("IMPORT_CHANGED_OR_CACHE_CREATED")
    def ancestor_path():
        fd=os.open(directory,os.O_PATH|os.O_DIRECTORY)
        try:
            try:os.listdir(fd)
            except OSError as error:
                if error.errno!=errno.EBADF:raise
            else:raise AssertionError("ANCESTOR_LISTABLE")
        finally:os.close(fd)
    operations={
        "import_source":import_source,
        "ancestor_path":ancestor_path,
        "ancestor_read":lambda:opened(os.O_RDONLY|os.O_DIRECTORY,directory),
        "read":lambda:victim.read_bytes(),
        "read_fd":lambda:opened(os.O_RDONLY),
        "read_outside":lambda:outside.read_bytes(),
        "write_text":lambda:victim.write_bytes(b"BAD"),
        "write_fd":lambda:opened(os.O_WRONLY),
        "readwrite_fd":lambda:opened(os.O_RDWR),
        "create_readonly":lambda:opened(os.O_RDONLY|os.O_CREAT,target),
        "truncate_readonly":lambda:opened(os.O_RDONLY|os.O_TRUNC),
        "append_fd":lambda:opened(os.O_WRONLY|os.O_APPEND),
        "fdopen_write":lambda:os.fdopen(descriptor,"w",closefd=False).close(),
        "remove":lambda:os.remove(victim),
        "rename":lambda:os.rename(victim,target),
        "chmod":lambda:os.chmod(victim,0o777),
        "truncate":lambda:os.truncate(victim,0),
        "mkdir":lambda:os.mkdir(target),
        "rmdir":lambda:os.rmdir(empty),
        "link":lambda:os.link(victim,target),
        "symlink":lambda:os.symlink(victim,target),
        "utime":lambda:os.utime(victim,ns=(1,1)),
        "posix_spawn":spawn, "exec":execute, "fork":fork,
        "forkpty":lambda:fork(True), "kill":lambda:os.kill(os.getpid(),0),
    }
    before=victim.stat()
    expected=("READ_OUTSIDE_RUNTIME" if case in ("read_outside","ancestor_read") else
              "NATIVE_EFFECT_DENIED" if case in ("posix_spawn","exec","fork","forkpty","kill") else
              "WRITE_DURING_VERIFY")
    try:
        try:operations[case]()
        except (ValueError,PermissionError) as error:
            if case in ("read","read_fd","import_source","ancestor_path") or str(error)!=expected:raise
        else:
            if case not in ("read","read_fd","import_source","ancestor_path"):raise AssertionError("GUARD_ALLOWED:"+case)
        if victim.read_bytes()!=b"KEEP" or not empty.is_dir() or target.exists():
            raise AssertionError("FIXTURE_CHANGED:"+case)
        after=victim.stat()
        if (before.st_mode,before.st_mtime_ns)!=(after.st_mode,after.st_mtime_ns):
            raise AssertionError("METADATA_CHANGED:"+case)
        print(json.dumps({"case":case,"status":"PASS","optimized":not __debug__}))
    finally:
        if descriptor is not None:os.close(descriptor)


class AuditTests(unittest.TestCase):
    def test_real_operations(self):
        parent=Path(os.environ["NDX12_TEST_ROOT"]).resolve();parent.mkdir(parents=True,exist_ok=True)
        parent=Path(tempfile.mkdtemp(prefix="runtime-guard-",dir=parent))
        verifier=Path(os.environ.get("NDX12_VERIFIER_SOURCE",str(PACKAGE/"tools/runtime/verify.py"))).resolve()
        for case in CASES:
            with self.subTest(case=case):
                argv=[sys.executable,"-I"]+(["-O"] if not __debug__ else [])
                argv += [str(Path(__file__).resolve()),"--probe",case,str(verifier),str(parent)]
                result=subprocess.run(argv,capture_output=True,text=True)
                with (parent/(case+".json")).open("x") as f:
                    json.dump({"argv":argv,"returncode":result.returncode,"stdout":result.stdout,"stderr":result.stderr},f,indent=2)
                self.assertEqual(result.returncode,0,result.stderr)
                row=json.loads(result.stdout)
                self.assertEqual(row,{"case":case,"status":"PASS","optimized":not __debug__})


if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--probe":probe(sys.argv[2],Path(sys.argv[3]),Path(sys.argv[4]))
    else:unittest.main()
