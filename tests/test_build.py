"""CPU-only source-lock and command-failure regression tests.

Set NDX12_TEST_ROOT to an output directory. All test directories are retained.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("package_build",PACKAGE/"build.py")
build=importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
ABC_SHA="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


class SourceLockTests(unittest.TestCase):
    def setUp(self):
        parent=Path(os.environ["NDX12_TEST_ROOT"]).resolve()
        parent.mkdir(parents=True,exist_ok=True)
        self.root=Path(tempfile.mkdtemp(prefix="source-lock-",dir=parent))
        self.package=self.root/"package"
        self.package.mkdir()
        (self.package/"unit.txt").write_bytes(b"abc")
        self.manifest={"schema":"ndx12.source-lock.v1","files":[
            {"path":"unit.txt","bytes":3,"sha256":ABC_SHA}]}
        self.save()

    def save(self):
        (self.package/"sources.lock.json").write_text(json.dumps(self.manifest))

    def test_valid(self):
        self.assertEqual(build.verify_sources(self.package),self.manifest)

    def test_changed_same_size(self):
        (self.package/"unit.txt").write_bytes(b"abd")
        with self.assertRaisesRegex(ValueError,"SOURCE_PIN:unit.txt"):
            build.verify_sources(self.package)

    def test_missing(self):
        (self.package/"unit.txt").rename(self.package/"held.txt")
        with self.assertRaises(FileNotFoundError):build.verify_sources(self.package)

    def test_traversal(self):
        (self.root/"unit.txt").write_bytes(b"abc")
        self.manifest["files"][0]["path"]="../unit.txt"
        self.save()
        with self.assertRaisesRegex(ValueError,"SOURCE_PATH"):build.verify_sources(self.package)

    def test_symlink_matching_bytes(self):
        (self.package/"unit.txt").rename(self.root/"held.txt")
        (self.package/"unit.txt").symlink_to(self.root/"held.txt")
        with self.assertRaisesRegex(ValueError,"SOURCE_SYMLINK"):build.verify_sources(self.package)

    def test_duplicate_key(self):
        path=self.package/"sources.lock.json"
        path.write_text('{"schema":"ndx12.source-lock.v1",'+path.read_text()[1:])
        with self.assertRaisesRegex(ValueError,"SOURCE_DUPLICATE_KEY"):build.verify_sources(self.package)

    def test_command_failure_retains_evidence(self):
        output=self.root/"output"
        output.mkdir()
        runner=build.Build(self.package,output,{})
        with self.assertRaisesRegex(ValueError,"COMMAND_FAILED:expected-failure"):
            runner.run([sys.executable,"-I","-c","import sys; print('retained'); sys.exit(7)"],"expected-failure")
        record=json.loads((output/"logs/001-expected-failure.result.json").read_bytes())
        self.assertEqual(record["returncode"],7)
        self.assertEqual((output/"logs/001-expected-failure.stdout").read_bytes(),b"retained\n")

    def runner(self, deps):
        output=self.root/"output"
        output.mkdir()
        return build.Build(self.package,output,deps)

    def test_environment_does_not_inherit_host(self):
        with patch.dict(os.environ,{"CPATH":"poison","LD_PRELOAD":"poison","HOME":"poison","PATH":"poison"}):
            runner=self.runner({})
        raw=runner.run([sys.executable,"-I","-c","import os,json; print(json.dumps(dict(os.environ)))"],"environment")
        env=json.loads(raw)
        self.assertNotIn("CPATH",env)
        self.assertNotIn("LD_PRELOAD",env)
        self.assertEqual(env["PATH"],"/usr/bin:/bin")
        self.assertEqual(env["HOME"],str(runner.output/"home"))
        self.assertEqual(env["TMPDIR"],str(runner.output/"tmp"))

    def intel_inputs(self):
        depsroot=self.root/"dependency-build"
        rows={}
        for name in ("libndx12-experimental.so","ndx12-m1","ndx12-m3","ndx12-m3-texture",
                     "ndx12-m3-depth","ndx12-gallium-probe"):
            rel="src/gallium/"+name
            path=depsroot/rel
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b"abc")
            rows[rel]={"path":str(path),"bytes":3,"sha256":ABC_SHA}
        converter=depsroot/"libdxil-spirv-c-shared.so"
        converter.write_bytes(b"abc")
        return {"mesa_intel":{"build":str(depsroot),"outputs":rows,
                              "converter_copy":{"soname":"libdxil-spirv-c-shared.so.2"}},
                "dxil_spirv":{"c_shared":{"path":str(converter),"bytes":3,"sha256":ABC_SHA}}}

    def test_intel_copies_without_running_or_writing_dependencies(self):
        deps=self.intel_inputs()
        before={r["path"]:Path(r["path"]).stat() for r in deps["mesa_intel"]["outputs"].values()}
        runner=self.runner(deps)
        runner.run=lambda *a,**k: self.fail("INTEL_MUST_NOT_RUN_NINJA")
        self.assertEqual(len(runner.intel(2)),7)
        for path,stat in before.items():
            self.assertEqual(Path(path).read_bytes(),b"abc")
            self.assertEqual(Path(path).stat().st_mtime_ns,stat.st_mtime_ns)
            self.assertEqual((runner.output/"intel"/Path(path).name).read_bytes(),b"abc")

    def test_intel_modified_converter_refused(self):
        deps=self.intel_inputs()
        Path(deps["dxil_spirv"]["c_shared"]["path"]).write_bytes(b"abd")
        runner=self.runner(deps)
        with self.assertRaisesRegex(ValueError,"INTEL_CONVERTER_PIN"):
            runner.intel(2)
        self.assertFalse((runner.output/"intel/libdxil-spirv-c-shared.so.2").exists())

    def test_intel_unexpected_converter_soname_refused(self):
        deps=self.intel_inputs()
        deps["mesa_intel"]["converter_copy"]["soname"]="libdxil-spirv-c-shared.so.3"
        runner=self.runner(deps)
        with self.assertRaisesRegex(ValueError,"INTEL_CONVERTER_SONAME"):
            runner.intel(2)
        self.assertFalse((runner.output/"intel/libdxil-spirv-c-shared.so.2").exists())

    def test_intel_modified_output_refused(self):
        deps=self.intel_inputs()
        Path(next(iter(deps["mesa_intel"]["outputs"].values()))["path"]).write_bytes(b"abd")
        runner=self.runner(deps)
        with self.assertRaisesRegex(ValueError,"INTEL_OUTPUT_PIN:libndx12-experimental.so"):
            runner.intel(2)
        self.assertEqual(list((runner.output/"intel").iterdir()),[])

    def test_ffx_base_content_and_exact_set(self):
        base=self.root/"ffx"
        base.mkdir()
        (base/"input").write_bytes(b"abc")
        runner=self.runner({"ffx_base":{"root":str(base),"files":{"input":ABC_SHA}}})
        self.assertEqual(runner.verify_ffx_base(),base)
        (base/"extra").write_bytes(b"abc")
        with self.assertRaisesRegex(ValueError,"FFX_BASE_PIN"):runner.verify_ffx_base()

    def test_ffx_base_changed_bytes(self):
        base=self.root/"ffx"
        base.mkdir()
        (base/"input").write_bytes(b"abd")
        runner=self.runner({"ffx_base":{"root":str(base),"files":{"input":ABC_SHA}}})
        with self.assertRaisesRegex(ValueError,"FFX_BASE_PIN"):runner.verify_ffx_base()

    def test_dxil_libraries_require_and_check_pins(self):
        mesa=self.root/"mesa"
        dxil=self.root/"dxil"
        for name in ("src/compiler/nir/libnir.a","src/compiler/libcompiler.a","src/util/libmesa_util.a",
                     "src/util/blake3/libblake3.a","src/c11/impl/libmesa_util_c11.a"):
            path=mesa/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"abc")
        records={}
        for name in ("bc/libllvm-bc.a","third_party/libbc-decoder.a","libdxil-utils.a","libdxil-debug.a"):
            path=dxil/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"abc")
            records[name]={"path":str(path),"bytes":3,"sha256":ABC_SHA}
        deps={"mesa_rtx":{"build":str(mesa)},"dxil_spirv":{"build":str(dxil),"libraries":records}}
        runner=self.runner(deps)
        self.assertEqual(len(runner.libraries()),9)
        (dxil/"bc/libllvm-bc.a").write_bytes(b"abd")
        with self.assertRaisesRegex(ValueError,"DXIL_LIBRARY_PIN:bc/libllvm-bc.a"):runner.libraries()
        del records["bc/libllvm-bc.a"]
        with self.assertRaisesRegex(ValueError,"DXIL_LIBRARY_UNPINNED:bc/libllvm-bc.a"):runner.libraries()


class CacheArgumentTests(unittest.TestCase):
    def setUp(self):
        parent=Path(os.environ["NDX12_TEST_ROOT"]).resolve()
        parent.mkdir(parents=True,exist_ok=True)
        self.directory=Path(tempfile.mkdtemp(prefix="cache-args-",dir=parent))
        self.output=self.directory/"build"

    def invoke(self, extra):
        argv=["build.py","--build-root",str(self.output),"--offline",*extra]
        # Stop at the external preparer boundary: these tests never run a build.
        with patch.object(sys,"argv",argv), patch.object(build,"verify_sources",return_value={}), \
             patch.object(build.subprocess,"run",side_effect=RuntimeError("PREPARER_REACHED")) as run:
            try:
                build.main()
            finally:
                self.calls=run.call_args_list

    def test_cache_required(self):
        with self.assertRaises(SystemExit) as caught:self.invoke([])
        self.assertEqual(caught.exception.code,2)
        self.assertEqual(self.calls,[])
        self.assertFalse(self.output.exists())

    def test_cache_inside_build_refused(self):
        with self.assertRaisesRegex(ValueError,"CACHE_INSIDE_BUILD_ROOT"):
            self.invoke(["--cache",str(self.output/"cache")])
        self.assertEqual(self.calls,[])
        self.assertFalse(self.output.exists())

    def test_cache_equal_build_refused(self):
        with self.assertRaisesRegex(ValueError,"CACHE_INSIDE_BUILD_ROOT"):
            self.invoke(["--cache",str(self.output)])
        self.assertEqual(self.calls,[])

    def test_symlink_cache_inside_build_refused(self):
        self.output.mkdir()
        target=self.output/"cache";target.mkdir()
        alias=self.directory/"alias";alias.symlink_to(target,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,"CACHE_INSIDE_BUILD_ROOT"):
            self.invoke(["--cache",str(alias)])
        self.assertEqual(self.calls,[])
        self.assertEqual(list(target.iterdir()),[])

    def test_external_cache_reaches_preparer(self):
        cache=self.directory/"cache"
        with self.assertRaisesRegex(RuntimeError,"PREPARER_REACHED"):
            self.invoke(["--cache",str(cache)])
        self.assertEqual(len(self.calls),1)
        argv=self.calls[0].args[0]
        self.assertEqual(argv[argv.index("--cache")+1],str(cache))
        self.assertEqual(argv[argv.index("--build-root")+1],str(self.output))
        self.assertFalse(self.output.exists())


if __name__=="__main__":unittest.main()
