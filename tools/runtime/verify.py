"""CPU verification of pinned runtime inputs with bounded Python audit guards."""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import threading


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blocked(*args, **kwargs):
    raise PermissionError("NATIVE_EFFECT_DENIED")


def main():
    receipt=json.loads(Path(sys.argv[1]).read_bytes())
    roots={name:Path(value).resolve(strict=True) for name,value in receipt["roots"].items()}
    require(set(roots)=={"PACKAGE","ARTIFACTS","HEADERS"},"ROOT_SET")
    permitted=[*roots.values(),Path(sys.base_prefix)/"lib"]
    def audit(event,args):
        if event=="open":
            if isinstance(args[0],(str,bytes,os.PathLike)):
                path=Path(os.fsdecode(args[0])).resolve()
                flags=args[2]
                ancestor=(type(flags) is int and flags & os.O_PATH and flags & os.O_DIRECTORY
                          and any(p.is_relative_to(path) for p in permitted))
                require(any(path.is_relative_to(p) for p in permitted) or ancestor,"READ_OUTSIDE_RUNTIME")
            mode=args[1] or ""
            flags=args[2]
            require(not any(c in mode for c in "wax+"),"WRITE_DURING_VERIFY")
            require(type(flags) is int and
                    flags & (os.O_ACCMODE|os.O_CREAT|os.O_TRUNC|os.O_APPEND)==0,
                    "WRITE_DURING_VERIFY")
        if event in ("os.remove","os.rename","os.chmod","os.chown","os.truncate",
                     "os.mkdir","os.rmdir","os.link","os.symlink","os.utime",
                     "os.setxattr","os.removexattr"):
            raise ValueError("WRITE_DURING_VERIFY")
        if event in ("ctypes.dlopen","subprocess.Popen","os.system","os.exec","os.posix_spawn",
                     "os.fork","os.forkpty","os.kill","os.killpg",
                     "socket.connect","socket.bind","socket.sendto","socket.sendmsg"):
            blocked()
    sys.dont_write_bytecode=True
    sys.addaudithook(audit)
    for name in ("CDLL","PyDLL","string_at","memmove"):
        setattr(ctypes,name,blocked)
    signal.signal=blocked
    threading.Thread.start=blocked
    records=receipt["files"]
    require(len(records)==177,"INSTALLATION_COUNT")
    expected=set()
    for row in records:
        path=Path(row["path"])
        require(not path.is_symlink() and path.resolve()==path,"INSTALLATION_SYMLINK")
        raw=path.read_bytes()
        require(len(raw)==row["bytes"] and sha(raw)==row["sha256"] and
                path.stat().st_mode&0o777==row["mode"],"INSTALLATION_PIN")
        expected.add(path)
    actual=set()
    for root in roots.values():
        for path in root.rglob("*"):
            require(not path.is_symlink(),"INSTALLATION_SYMLINK")
            if path.is_file():actual.add(path)
    require(actual==expected and len(expected)==177,"INSTALLATION_SET")
    path=roots["PACKAGE"]/"backends/nvidia/runtime/preparation_loader.py"
    spec=importlib.util.spec_from_file_location("runtime_loader",path)
    loader=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    manifest=roots["PACKAGE"]/"backends/nvidia/data/runtime_inputs.json"
    require(len(loader.verify(manifest,receipt["manifest_sha256"]))==81,"RUNTIME_81")
    modules=loader.Loader().load(manifest,receipt["manifest_sha256"])
    require(len(modules)==43,"MODULES_43")
    modules["packet_preparation"].input_pins()
    packet=json.loads((roots["PACKAGE"]/"backends/nvidia/data/packet_inputs.json").read_bytes())
    require(len(packet["entries"])==61,"PACKET_61")
    require(modules["shader_info_check"].inspect()["artifact_count"]==20,"FFX_ARTIFACTS")
    require(modules["shader_info_check"].inspect_affine()["artifact_count"]==4,"AFFINE_ARTIFACTS")
    code,qmd=modules["affine_images"].program()
    require(len(code)==912 and len(qmd)==256,"AFFINE_PROFILE")
    print(json.dumps({"status":"CPU_RUNTIME_VERIFIED","gpu":"NOT_RUN","optimized":not __debug__,
                      "runtime_pins":81,"packet_pins":61,"modules":43,"files":177}))


if __name__=="__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print("FAIL:" + str(error), file=sys.stderr)
        sys.exit(1)
