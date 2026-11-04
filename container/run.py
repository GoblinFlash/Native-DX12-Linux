"""Build-only OCI launcher. No devices, host package installation or GPU action."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

PACKAGE=Path(__file__).resolve().parents[1]
IMAGE=re.compile(r"(?:[a-z0-9][a-z0-9./:_-]*@)?sha256:[a-f0-9]{64}\Z")


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def external(path):
    path=path.resolve(strict=True)
    require(path.is_dir(),"DIRECTORY_REQUIRED")
    require(not path.is_relative_to(PACKAGE) and not PACKAGE.is_relative_to(path),"SOURCE_OVERLAP")
    require(not any(c in str(path) for c in (",","\n","\r")),"MOUNT_PATH_CHARACTER")
    return path


def command(args):
    engine=shutil.which(args.engine)
    require(engine is not None or args.dry_run,"CONTAINER_ENGINE_MISSING:"+args.engine)
    engine=engine or args.engine
    if args.action=="image-build":
        return [engine,"build","--platform=linux/amd64","--tag",args.tag,
                "--file",str(PACKAGE/"container/Containerfile"),str(PACKAGE)]
    require(args.image is not None and IMAGE.fullmatch(args.image),"IMAGE_DIGEST_REQUIRED")
    cache=external(args.cache)
    argv=[engine,"run","--rm","--pull=never","--platform=linux/amd64",
          "--cap-drop=ALL","--security-opt=no-new-privileges","--pids-limit=512",
          "--user",str(os.getuid())+":"+str(os.getgid()),"--read-only",
          "--tmpfs","/tmp:rw,nosuid,nodev,size=512m","--env","HOME=/tmp",
          "--mount",f"type=bind,src={PACKAGE},dst=/package,readonly",
          "--mount",f"type=bind,src={cache},dst=/cache"+("" if args.action=="fetch" else ",readonly")]
    if args.engine=="podman":argv += ["--userns=keep-id"]
    if args.action=="fetch":
        return argv+[args.image,"python3","-I","-B","deps/prepare_deps.py","fetch","--cache","/cache"]
    output=external(args.output)
    require(not output.is_relative_to(cache) and not cache.is_relative_to(output),"CACHE_OUTPUT_OVERLAP")
    require(not any(output.iterdir()),"OUTPUT_NOT_EMPTY")
    # Outer network namespace replaces nested unshare, which OCI seccomp may deny.
    return argv+["--network=none","--mount",f"type=bind,src={output},dst=/output",args.image,
                 "python3","-I","-B","build.py","--build-root","/output/build",
                 "--cache","/cache","--jobs",str(args.jobs),"--targets",args.targets]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("image-build","fetch","build"))
    p.add_argument("--engine",choices=("podman","docker"),default="podman")
    p.add_argument("--image",help="Local sha256:image-ID or repository@sha256:digest")
    p.add_argument("--tag",default="native-dx12-toolchain:experimental")
    p.add_argument("--cache",type=Path)
    p.add_argument("--output",type=Path)
    p.add_argument("--jobs",type=int,choices=(1,2,3,4),default=2)
    p.add_argument("--targets",choices=("intel","rtx","amd","intel,rtx,amd"),default="intel,rtx,amd")
    p.add_argument("--dry-run",action="store_true")
    args=p.parse_args()
    require(args.action=="image-build" or args.cache is not None,"CACHE_REQUIRED")
    require(args.action!="build" or args.output is not None,"OUTPUT_REQUIRED")
    argv=command(args)
    print(json.dumps({"argv":argv,"gpu":"NOT_RUN","network":"none" if args.action=="build" else "enabled","dry_run":args.dry_run}),flush=True)
    if not args.dry_run:
        return subprocess.run(argv,check=False).returncode
    return 0


if __name__=="__main__":
    raise SystemExit(main())
