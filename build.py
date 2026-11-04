#!/usr/bin/env python3
"""Ubuntu source build entrypoint. No hardware execution or system installation."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import shutil
import struct
import subprocess
import sys
import time


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    data = Path(path).read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def verify_sources(package):
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,"SOURCE_DUPLICATE_KEY")
            result[key]=value
        return result
    manifest=json.loads((package/"sources.lock.json").read_bytes(),object_pairs_hook=unique)
    require(set(manifest)=={"schema","files"} and manifest["schema"]=="ndx12.source-lock.v1","SOURCE_LOCK_SCHEMA")
    require(type(manifest["files"]) is list and bool(manifest["files"]),"SOURCE_LOCK_EMPTY")
    seen=set()
    for record in manifest["files"]:
        require(type(record) is dict and set(record)=={"path","sha256","bytes"},"SOURCE_RECORD")
        name=record["path"]
        require(type(name) is str and name not in seen and name!="sources.lock.json","SOURCE_DUPLICATE_PATH")
        parts=name.split("/")
        require(all(p not in ("",".","..") for p in parts) and "\\" not in name,"SOURCE_PATH")
        path=package.joinpath(*parts)
        require(path.is_relative_to(package) and all(not q.is_symlink() for q in [path,*path.parents]),"SOURCE_SYMLINK")
        require(type(record["bytes"]) is int and record["bytes"]>=0 and
                identity(path)=={k:record[k] for k in ("sha256","bytes")},"SOURCE_PIN:"+name)
        seen.add(name)
    return manifest


def compile_flags(build):
    rows = json.loads((build / "compile_commands.json").read_bytes())
    matches = [r for r in rows if r["file"].endswith("/nak_nir.c")]
    require(len(matches) == 1, "NAK_COMPILE_ROW")
    row = matches[0]
    args = row.get("arguments") or shlex.split(row["command"])
    flags, pos = [], 1
    while pos < len(args):
        arg = args[pos]
        if arg in ("-o", "-MF", "-MT", "-MQ"):
            pos += 2
            continue
        if arg not in ("-c", "-MD", "-MMD", row["file"]):
            if arg.startswith("-I"):
                arg = "-I" + str((Path(row["directory"]) / arg[2:]).resolve())
            flags.append(arg)
        pos += 1
    return flags + ["-ffunction-sections", "-fdata-sections", "-fPIC"]


class Build:
    def __init__(self, package, output, deps):
        self.package, self.output, self.deps = package, output, deps
        self.logs = output / "logs"
        self.logs.mkdir()
        self.sequence = 0
        home, temporary = output/"home", output/"tmp"
        home.mkdir()
        temporary.mkdir()
        self.env = {"PATH":"/usr/bin:/bin", "HOME":str(home), "TMPDIR":str(temporary),
                    "LANG":"C.UTF-8", "LC_ALL":"C.UTF-8"}

    def run(self, args, name, expected=0, timeout=180, env=None):
        args = list(map(str, args))
        self.sequence += 1
        prefix = self.logs / (str(self.sequence).zfill(3) + "-" + name)
        record = {"argv": args, "gpu": "NOT_RUN", "expected": expected}
        write_json(prefix.with_suffix(".intent.json"), record)
        start = time.monotonic()
        with prefix.with_suffix(".stdout").open("xb") as stdout, prefix.with_suffix(".stderr").open("xb") as stderr:
            process = subprocess.Popen(args, cwd=self.output, env=env or self.env,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                rc = process.wait(timeout=timeout)
            except BaseException as error:
                if process.returncode is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                record.update(status="INTERRUPTED_OR_TIMEOUT", error=type(error).__name__,
                              returncode=process.returncode, seconds=time.monotonic()-start)
                try:
                    write_json(prefix.with_suffix(".result.json"), record)
                except OSError as evidence_error:
                    error.add_note("EVIDENCE_FAILED: " + str(evidence_error))
                raise
        record.update(returncode=rc, seconds=time.monotonic()-start)
        write_json(prefix.with_suffix(".result.json"), record)
        require(rc == expected, "COMMAND_FAILED:" + name + ":" + str(prefix))
        return prefix.with_suffix(".stdout").read_bytes()

    def tool(self, name):
        record = self.deps["toolchain"][name]
        path = Path(record["path"])
        require(identity(path) == {k: record[k] for k in ("sha256", "bytes")}, "TOOL_PIN:" + name)
        return path

    def libraries(self, nak=False):
        mesa = Path(self.deps["mesa_rtx"]["build"])
        dxil = Path(self.deps["dxil_spirv"]["build"])
        names = ["src/compiler/nir/libnir.a", "src/compiler/libcompiler.a",
                 "src/util/libmesa_util.a", "src/util/blake3/libblake3.a", "src/c11/impl/libmesa_util_c11.a"]
        if nak:
            names = ["src/nouveau/compiler/libnak.a", "src/nouveau/compiler/libnak_rs.a",
                     "src/nouveau/nil/libnil.a", "src/nouveau/nil/liblibnil_format_table.a",
                     "src/nouveau/headers/libnvidia_headers_c.a", "src/compiler/rust/libcompiler_c_helpers.a",
                     "src/compiler/rust/libcompiler_bindings.a"] + names
        libs = [mesa / name for name in names] + [dxil / name for name in
                ("bc/libllvm-bc.a", "third_party/libbc-decoder.a", "libdxil-utils.a", "libdxil-debug.a")]
        require(all(p.is_file() for p in libs), "LIBRARY_MISSING")
        recorded=self.deps["dxil_spirv"].get("libraries",{})
        for path in libs:
            if path.is_relative_to(dxil):
                name=str(path.relative_to(dxil))
                require(name in recorded,"DXIL_LIBRARY_UNPINNED:"+name)
                require(identity(path)=={k:recorded[name][k] for k in ("sha256","bytes")},
                        "DXIL_LIBRARY_PIN:"+name)
        return libs

    def reader_flags(self):
        source = Path(self.deps["dxil_spirv"]["source"])
        return ["-std=c++17", "-O2", "-fPIC", "-DHAVE_LLVMBC", "-ffunction-sections", "-fdata-sections",
                *["-I" + str(source / n) for n in ("bc", "util", "debug", "third_party/bc-decoder")]]

    def link(self, objects, libs, output, name):
        self.run([self.tool("cxx"), *objects, "-Wl,--gc-sections", "-Wl,--start-group", *libs,
                  "-Wl,--end-group", "-lz", "-lzstd", "-lm", "-ldl", "-pthread", "-o", output], name)

    def shader(self, source, output, name):
        record=self.deps["dxc"]["bin"]
        require(identity(record["path"])=={k:record[k] for k in ("sha256","bytes")},"DXC_PIN")
        self.run([record["path"], "-T", "cs_6_0", "-E", "main", "-O3", source, "-Fo", output], name)

    def abi(self):
        root=Path(self.deps["nvidia_headers"]["root"])
        expected=json.loads((self.package/"backends/nvidia/abi/abi.json").read_bytes())
        headers=expected["probe"]["header_closure"]
        for row in headers:
            require(identity(root/row["path"])["sha256"]==row["sha256"],"ABI_HEADER_PIN:"+row["path"])
        includes=["kernel-open/common/inc","kernel-open/nvidia-uvm","src/common/sdk/nvidia/inc",
                  "src/nvidia/arch/nvalloc/unix/include","src/common/inc/swref/published"]
        executable=self.output/"abi-probe"
        self.run([self.tool("cc"),"-std=gnu11","-Wall","-Wextra",*["-I"+str(root/p) for p in includes],
                  self.package/"tools/abi/nvidia_probe.c","-o",executable],"abi-build")
        observed=json.loads(self.run([executable],"abi-probe"))
        require(observed["constants"]==expected["constants"],"ABI_CONSTANTS")
        require(observed["structs"]==expected["structs"],"ABI_STRUCTS")
        return {"headers":len(headers),"constants":len(observed["constants"]),
                "structs":len(observed["structs"]),"full_document_regenerated":False}

    def affine(self):
        out = self.output / "affine"
        out.mkdir()
        source = self.package / "backends/nvidia/compiler/affine/dxil_shared"
        flags = compile_flags(Path(self.deps["mesa_rtx"]["build"]))
        self.run([self.tool("cxx"), *self.reader_flags(), "-c", source/"reader.cpp", "-o", out/"reader.o"], "affine-reader")
        self.run([self.tool("cc"), *flags, "-c", source/"compile.c", "-o", out/"compile.o"], "affine-compile")
        self.link([out/"reader.o", out/"compile.o"], self.libraries(nak=True), out/"direct-compile", "affine-link")
        symbols=self.run([self.tool("nm"),"-C",out/"direct-compile"],"affine-symbols")
        require(not any(token in symbols for token in
                (b"spirv_to_nir",b"spvValidate",b"legacy_spirv_main",b"dxil_spv::Converter")),"AFFINE_SPIRV_LINKED")
        self.shader(self.package/"shaders/affine_u32.hlsl", out/"shader.dxil", "affine-dxc")
        raw = self.run([out/"direct-compile", "affine-u32", out/"shader.dxil", out/"shader"], "affine-shader")
        # Artifact ABI preserves the emitter's member order; receipts use sorted keys.
        with (out/"shader.json").open("x",encoding="utf-8") as stream:
            json.dump(json.loads(raw),stream,indent=2)
            stream.write("\n")
        for profile in ("shared-reduce", "batch2d8x8"):
            self.run([out/"direct-compile", profile, out/"shader.dxil", out/("rejected-"+profile)], "reject-"+profile, expected=1)
            stderr = (self.logs / (str(self.sequence).zfill(3)+"-reject-"+profile+".stderr")).read_bytes()
            require(b"RTX_REJECT:DIRECT_PROFILE" in stderr, "PROFILE_REFUSAL_REASON")
        return {p.name: identity(p) for p in sorted(out.glob("shader.*"))}

    def amd(self):
        out = self.output/"amd"
        out.mkdir()
        core = self.package/"src/compiler/dxil/core"
        source = self.package/"backends/amd"
        mesa = Path(self.deps["mesa_rtx"]["source"])
        flags = compile_flags(Path(self.deps["mesa_rtx"]["build"])) + ["-I"+str(p) for p in
                (core, source, mesa/"src/gallium/include", mesa/"src/gallium/auxiliary")]
        objects = []
        for name, path in [("reader",core/"dxil_reader.cpp"),("emitter",core/"nir_emitter.c"),
                           ("adapter",source/"backend_radeonsi.c"),("inspect",source/"cpu_inspect.c"),
                           ("test",self.package/"tests/amd/test_adapter.c")]:
            obj=out/(name+".o")
            self.run([self.tool("cxx" if path.suffix==".cpp" else "cc"),
                      *(self.reader_flags() if path.suffix==".cpp" else flags), "-c", path, "-o", obj], "amd-"+name)
            objects.append(obj)
        self.link(objects, self.libraries(), out/"test_adapter", "amd-link")
        for name in ("baseline", "arithmetic", "boundary", "bitwise"):
            self.shader(self.package/"tests/amd/shaders"/(name+".hlsl"),out/(name+".dxil"),"amd-dxc-"+name)
        total=0
        for group, count in [("caps",12),("lower",23),("view",11),("state",6),("bind",4)]:
            result=self.run([out/"test_adapter",group,out/"baseline.dxil"],"amd-test-"+group)
            require(result.count(b"PASS:")==count,"AMD_TEST_COUNT:"+group)
            total+=count
        for name,n,formula in [("baseline",1024,lambda x:3*x+7),("arithmetic",1024,lambda x:5*x+11),
                               ("boundary",65,lambda x:3*x+7),("bitwise",1024,lambda x:(x^0x55)+19)]:
            self.run([out/"test_adapter","inspect",out/(name+".dxil"),out/(name+".nir"),out/(name+".bin")],"amd-image-"+name)
            expected=[0xc0decafe]*32+[formula(x) if x<n else 0xc0decafe for x in range(1024)]+[0xc0decafe]*32
            require(list(struct.unpack("<1088I",(out/(name+".bin")).read_bytes()))==expected,"AMD_IMAGE:"+name)
        return {"controls":total,"images":4,"gpu":"NOT_RUN","full_frontend_link":False}

    def intel(self, jobs):
        directory=Path(self.deps["mesa_intel"]["build"])
        names=["libndx12-experimental.so", "ndx12-m1", "ndx12-m3", "ndx12-m3-texture",
               "ndx12-m3-depth", "ndx12-gallium-probe"]
        out=self.output/"intel"
        out.mkdir()
        result={}
        for name in names:
            rel="src/gallium/"+name
            record=self.deps["mesa_intel"]["outputs"][rel]
            source=directory/rel
            require(Path(record["path"]).resolve()==source.resolve(),"INTEL_OUTPUT_PATH:"+name)
            data=source.read_bytes()
            actual={"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)}
            require(actual=={k:record[k] for k in ("sha256","bytes")},"INTEL_OUTPUT_PIN:"+name)
            target=out/name
            with target.open("xb") as stream:stream.write(data)
            target.chmod(0o755)
            require(identity(target)==actual,"INTEL_COPY_PIN:"+name)
            result[name]=actual
        # The converter SONAME is pinned by this package's dxil-spirv revision.
        record=self.deps["dxil_spirv"]["c_shared"]
        source=Path(record["path"])
        data=source.read_bytes()
        actual={"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)}
        require(actual=={k:record[k] for k in ("sha256","bytes")},"INTEL_CONVERTER_PIN")
        name="libdxil-spirv-c-shared.so.2"
        require(self.deps["mesa_intel"]["converter_copy"]["soname"]==name,"INTEL_CONVERTER_SONAME")
        target=out/name
        with target.open("xb") as stream:stream.write(data)
        target.chmod(0o755)
        require(identity(target)==actual,"INTEL_CONVERTER_COPY_PIN")
        result[name]=actual
        write_json(out/"copy-result.json",{"status":"VERIFIED_DEPENDENCY_OUTPUTS_COPIED","files":result})
        return result

    def verify_ffx_base(self):
        base=Path(self.deps["ffx_base"]["root"])
        expected=self.deps["ffx_base"]["files"]
        actual={str(p.relative_to(base)):identity(p)["sha256"] for p in base.rglob("*") if p.is_file()}
        require(actual==expected,"FFX_BASE_PIN")
        return base

    def ffx(self):
        base=self.verify_ffx_base()
        scripts=self.package/"tools/shaders/parallel_sort"
        recipe=json.loads((scripts/"ffx_recipe.json").read_bytes())
        roots={"ffx":str(base),"mesa_build":self.deps["mesa_rtx"]["build"],
               "mesa_source":self.deps["mesa_rtx"]["source"]}
        paths={name:{"root":"ffx","path":value} for name,value in
               [("base","base"),("extra","extra"),("shaders","shaders"),
                ("upstream","upstream"),("ordinary_spv","ordinary.spv")]}
        converter=Path(self.deps["dxil_spirv"]["build"])/"dxil-spirv"
        tools={"dxc":Path(self.deps["dxc"]["bin"]["path"]),"spirv":converter,
               "cc":self.tool("cc"),"cxx":self.tool("cxx"),"spirv_dis":self.tool("spirv_dis")}
        files={p.resolve() for p in base.rglob("*") if p.is_file()}
        for name,path in tools.items():
            path=path.resolve(strict=True)
            roots["tool_"+name]=str(path.parent)
            paths[name]={"root":"tool_"+name,"path":path.name}
            files.add(path)
        for row in recipe["libraries"]:
            files.add((Path(roots[row["root"]])/row["path"]).resolve(strict=True))
        pins=[]
        for path in sorted(files):
            candidates=[(name,Path(root)) for name,root in roots.items() if path.is_relative_to(Path(root))]
            require(bool(candidates),"FFX_INPUT_ROOT:"+str(path))
            name,root=max(candidates,key=lambda v:len(v[1].parts))
            pins.append(dict(root=name,path=str(path.relative_to(root)),**identity(path)))
        config={"schema":"private-ffx-build.v1","roots":roots,"paths":paths,"pins":pins,
                "compile_flags":recipe["compile_flags"],"libraries":recipe["libraries"]}
        config_path=self.output/"ffx-config.json"
        write_json(config_path,config)
        config_sha=identity(config_path)["sha256"]
        env=dict(self.env)
        env["LD_LIBRARY_PATH"]=str(Path(self.deps["dxil_spirv"]["build"]))
        result={}
        for stage,script in [("count","count"),("reduce","reduce"),("scan","scan"),
                             ("scanadd","scan_add"),("scatter","scatter")]:
            out=self.output/("ffx-"+stage)
            self.run([sys.executable,"-I","-B",scripts/("build_"+script+"_adapter.py"),
                      "--config",config_path,"--config-sha256",config_sha,"--output-root",out],
                     "ffx-"+stage,timeout=600,env=env)
            result[stage]={p.name:identity(p) for p in sorted((out/"build/normal").glob(stage+".*"))}
        return result

    def runtime(self):
        helper=self.package/"tools/runtime/installer.py"
        spec=importlib.util.spec_from_file_location("runtime_installer",helper)
        installer=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        raw=(self.package/"tools/runtime/templates.json").read_bytes()
        lock=json.loads(raw)
        bundle=self.output/"runtime-inputs"
        bundle.mkdir()
        (bundle/"template-lock.json").write_bytes(raw)
        for row in lock["files"]:
            locator=row["locator"]
            if locator.startswith("@PACKAGE@/"):
                source=self.package/locator.removeprefix("@PACKAGE@/")
            elif locator.startswith("@HEADERS@/"):
                name=locator.removeprefix("@HEADERS@/")
                if name=="clc56f.h":
                    source=Path(self.deps["nvidia_headers"]["root"])/"src/common/sdk/nvidia/inc/class"/name
                else:
                    source=Path(self.deps["mesa_rtx"]["source"])/"src/nouveau/headers/nvidia/classes"/name
            else:
                rel=locator.removeprefix("@ARTIFACTS@/")
                if rel.startswith("nvidia/affine/"):
                    source=self.output/"affine"/Path(rel).name
                elif rel.startswith("nvidia/parallel_sort/"):
                    stage=Path(rel).parts[2]
                    source=self.output/("ffx-"+stage)/"build/normal"/Path(rel).name
                elif rel.startswith("build_inputs/parallel_sort/"):
                    source=Path(self.deps["ffx_base"]["root"])/rel.removeprefix("build_inputs/parallel_sort/")
                else:
                    raise ValueError("UNKNOWN_RUNTIME_INPUT:"+locator)
            require(identity(source)=={"sha256":row["template_sha256"],"bytes":row["template_bytes"]},
                    "BUILT_RUNTIME_INPUT_PIN:"+locator)
            destination=bundle/row["template"]
            destination.parent.mkdir(parents=True,exist_ok=True)
            with destination.open("xb") as stream:stream.write(source.read_bytes())
        authority=self.output/"runtime"
        roots={"PACKAGE":authority/"package","ARTIFACTS":authority/"artifacts","HEADERS":authority/"headers"}
        result=installer.install(bundle,hashlib.sha256(raw).hexdigest(),roots,authority)
        receipt=self.output/"runtime-install.json"
        write_json(receipt,result)
        checks=[]
        for optimized in (False,True):
            command=[sys.executable,"-I","-B"]+(["-O"] if optimized else [])
            raw=self.run([*command,self.package/"tools/runtime/verify.py",receipt],
                         "runtime-optimized" if optimized else "runtime-normal")
            checks.append(json.loads(raw))
        self.run([self.tool("cc"),"-std=c11","-O2","-Wall","-Wextra","-Werror","-fno-lto",
                  "-I",self.package/"backends/nvidia","-fPIC","-fvisibility=hidden","-shared","-nostdlib",
                  "-Wl,--no-undefined","-Wl,-z,noexecstack","-Wl,-z,relro","-Wl,-z,now",
                  self.package/"backends/nvidia/native_words.c","-o",self.output/"libndxwords.so"],"native-words")
        return {"checks":checks,"native_words":identity(self.output/"libndxwords.so")}


def dependency_targets(targets):
    # AMD CPU adapter consumes the RTX-configured NIR headers and libraries.
    return [t for t in ('intel','rtx','amd') if t in targets or (t == 'rtx' and 'amd' in targets)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root",required=True,type=Path)
    parser.add_argument("--cache",required=True,type=Path)
    parser.add_argument("--jobs",type=int,choices=range(1,5),default=2)
    parser.add_argument("--offline",action="store_true")
    parser.add_argument("--targets",default="intel,rtx,amd")
    parser.add_argument("--deps-result",type=Path,help="reuse an explicitly pinned successful dependency build")
    parser.add_argument("--deps-result-sha256")
    parser.add_argument("--extra-path",action="append",default=[])
    args=parser.parse_args()
    package=Path(__file__).resolve().parent
    source_manifest=verify_sources(package)
    targets=args.targets.split(",")
    require(bool(targets) and len(set(targets))==len(targets) and set(targets)<=set(("intel","rtx","amd")),"TARGETS")
    root=args.build_root.resolve()
    require(not root.is_relative_to(package) and not package.is_relative_to(root),"BUILD_SOURCE_OVERLAP")
    cache=args.cache.resolve()
    require(not cache.is_relative_to(package) and not package.is_relative_to(cache),"CACHE_SOURCE_OVERLAP")
    require(not cache.is_relative_to(root),"CACHE_INSIDE_BUILD_ROOT")
    # The dependency preparer owns dependency outputs; adapters reserve a separate subtree.
    command=[sys.executable,"-I",str(package/"deps/prepare_deps.py"),"build","--package-root",str(package),
             "--cache",str(cache),"--build-root",str(root),"--jobs",str(args.jobs),
             "--targets",",".join(dependency_targets(targets))]
    if args.offline:command.append("--offline")
    for path in args.extra_path:command.extend(["--extra-path",path])
    if args.deps_result:
        require(identity(args.deps_result)["sha256"]==args.deps_result_sha256,"DEPS_RESULT_PIN")
        deps=json.loads(args.deps_result.read_bytes())
        root.mkdir(parents=True,exist_ok=True)
    else:
        require(args.deps_result_sha256 is None,"DEPS_RESULT_REQUIRED")
        subprocess.run(command,check=True)
        deps=json.loads((root/"deps.json").read_bytes())
    require(deps["schema"]=="ndx12.ubuntu-deps-result.v1" and deps["status"]=="PASS","DEPS_SCHEMA")
    require(deps["lock_sha256"]==identity(package/"deps/deps.lock.json")["sha256"],"DEPS_LOCK_PIN")
    require(Path(deps["package_root"]).resolve()==package,"DEPS_PACKAGE_ROOT")
    require("amd" not in targets or "mesa_rtx" in deps,"AMD_REQUIRES_MESA_RTX")
    # Validate every recorded binary before executing any project build step.
    def verify_recorded(value):
        if isinstance(value,dict):
            if {"path","sha256","bytes"}<=set(value):
                require(identity(value["path"])=={k:value[k] for k in ("sha256","bytes")},"DEPS_BINARY_PIN:"+value["path"])
            for child in value.values():verify_recorded(child)
        elif isinstance(value,list):
            for child in value:verify_recorded(child)
    verify_recorded(deps)
    output=root/"project"
    output.mkdir()
    build=Build(package,output,deps)
    results={"gpu":"NOT_RUN","targets":targets}
    if "intel" in targets:results["intel"]=build.intel(args.jobs)
    if "rtx" in targets:
        results["abi"]=build.abi()
        results["affine"]=build.affine()
        results["ffx"]=build.ffx()
        results["runtime"]=build.runtime()
    if "amd" in targets:results["amd"]=build.amd()
    results["status"]="OFFLINE_BUILD_CPU_VERIFIED"
    require(verify_sources(package)==source_manifest,"SOURCE_CHANGED_DURING_BUILD")
    write_json(output/"build-results.json",results)
    print(json.dumps({"status":results["status"],"targets":targets,"gpu":"NOT_RUN"}))


if __name__=="__main__":
    main()
