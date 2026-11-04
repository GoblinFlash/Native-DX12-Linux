"""CPU-only relocation, target admission and hardware-profile regression checks.

NDX12_TEST_ROOT is an owned writable directory. NDX12_RUNTIME_INPUTS points to
runtime-inputs from a completed build; its binary/header inputs are rechecked.
No device, library loader or GPU is invoked by these tests.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

P=Path(__file__).resolve().parents[1]
ABC='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


def pin(path):
    raw=path.read_bytes()
    return dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),size=len(raw),mode=stat.S_IMODE(path.stat().st_mode))


def assemble(directory):
    lock=json.loads((P/'tools/runtime/templates.json').read_bytes())
    directory.mkdir()
    raw=(P/'tools/runtime/templates.json').read_bytes();(directory/'template-lock.json').write_bytes(raw)
    built=Path(os.environ['NDX12_RUNTIME_INPUTS'])
    for row in lock['files']:
        loc=row['locator'];source=(P/loc.removeprefix('@PACKAGE@/')) if loc.startswith('@PACKAGE@/') else built/row['template']
        data=source.read_bytes()
        if len(data)!=row['template_bytes'] or hashlib.sha256(data).hexdigest()!=row['template_sha256']:
            raise AssertionError('TEST_INPUT_PIN:'+loc)
        dest=directory/row['template'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
    return hashlib.sha256(raw).hexdigest()


class RelocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=Path(tempfile.mkdtemp(prefix='release-install-',dir=Path(os.environ['NDX12_TEST_ROOT']).resolve(strict=True)))
        cls.bundle=cls.directory/'bundle';digest=assemble(cls.bundle)
        installer=load(P/'tools/runtime/installer.py','release_installer')
        cls.receipts=[]
        for n in ('one','different-longer-location'):
            root=cls.directory/n
            roots={'PACKAGE':root/'package','ARTIFACTS':root/'artifacts','HEADERS':root/'headers'}
            receipt=installer.install(cls.bundle,digest,roots,root)
            path=cls.directory/(n+'.json');path.write_text(json.dumps(receipt));cls.receipts.append((root,path))

    def test_noncanonical_roots_refuse_before_write(self):
        installer=load(P/'tools/runtime/installer.py','layout_installer')
        digest=hashlib.sha256((self.bundle/'template-lock.json').read_bytes()).hexdigest()
        for name in ('PACKAGE','HEADERS'):
            root=self.directory/('bad-layout-'+name)
            roots={'PACKAGE':root/'package','ARTIFACTS':root/'artifacts','HEADERS':root/'headers'}
            roots[name]=root/('nested/package' if name=='PACKAGE' else 'hdrs')
            with self.subTest(root=name):
                with self.assertRaisesRegex(ValueError,'ROOT_LAYOUT'):
                    installer.install(self.bundle,digest,roots,root)
                self.assertFalse(root.exists())

    def test_installed_bytes_do_not_depend_on_root(self):
        a,b=(root for root,_ in self.receipts)
        files={str(f.relative_to(a)):f.read_bytes() for f in a.rglob('*') if f.is_file()}
        other={str(f.relative_to(b)):f.read_bytes() for f in b.rglob('*') if f.is_file()}
        self.assertEqual(len(files),177);self.assertEqual(files,other)
        for raw in files.values():
            self.assertNotIn(str(self.directory).encode(),raw)
            self.assertNotIn(b'/home/',raw)

    def test_real_consumers_both_locations(self):
        for _,receipt in self.receipts:
            argv=[sys.executable,'-I','-B']+(['-O'] if not __debug__ else [])
            q=subprocess.run(argv+[str(P/'tools/runtime/verify.py'),str(receipt)],capture_output=True,text=True)
            self.assertEqual(q.returncode,0,q.stderr)
            self.assertEqual(json.loads(q.stdout)['runtime_pins'],81)

    def test_loader_negative_consumers(self):
        argv=[sys.executable,'-I','-B']+(['-O'] if not __debug__ else [])
        q=subprocess.run(argv+[str(Path(__file__).resolve()),'--loader-negatives',str(self.receipts[0][1])],capture_output=True,text=True)
        self.assertEqual(q.returncode,0,q.stderr)
        self.assertEqual(json.loads(q.stdout)['cases'],9)

    def test_real_card_info_consumer(self):
        argv=[sys.executable,'-I','-B']+(['-O'] if not __debug__ else [])
        q=subprocess.run(argv+[str(Path(__file__).resolve()),'--card-probe',str(self.receipts[0][1])],capture_output=True,text=True)
        self.assertEqual(q.returncode,0,q.stderr)
        self.assertEqual(json.loads(q.stdout)['cases'],3)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='reader-',dir=Path(os.environ['NDX12_TEST_ROOT']).resolve(strict=True)))
        self.module=load(P/'backends/nvidia/runtime/shader_info_check.py','reader_subject')
        self.module.HERE=self.root/'package/backends/nvidia/runtime'
        self.module.HERE.mkdir(parents=True)
        (self.root/'headers').mkdir();(self.root/'artifacts').mkdir()
        self.file=self.root/'headers/data';self.file.write_bytes(b'abc');self.file.chmod(0o644)

    def read(self,locator):return self.module.pinned(locator,ABC,3,0o644)

    def test_real_logical_consumer(self):
        self.assertEqual(self.read('@HEADERS@/data'),b'abc')

    def test_unsafe_locators_refuse(self):
        (self.root/'outside').write_bytes(b'abc')
        for path,reason in [('@HEADERS@/../outside','SOURCE_TRAVERSAL'),('@HEADERS@//etc/passwd','SOURCE_TRAVERSAL'),('@OTHER@/data','SOURCE_LOCATOR'),('@HEADERS@/a\\b','SOURCE_TRAVERSAL')]:
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,reason):self.read(path)

    def test_symlink_escape_refuses(self):
        outside=self.root/'outside';outside.write_bytes(b'abc')
        (self.root/'headers/link').symlink_to(outside)
        with self.assertRaises(ValueError):self.read('@HEADERS@/link')
        (self.root/'headers/dir').symlink_to(self.root)
        with self.assertRaises(ValueError):self.read('@HEADERS@/dir/outside')

    def test_missing_proc_refuses(self):
        with patch.object(Path,'is_dir',return_value=False):
            with self.assertRaisesRegex(ValueError,'SOURCE_PROC_UNAVAILABLE'):self.read('@HEADERS@/data')

    def test_in_place_change_refuses(self):
        original=os.fdopen;subject=self
        class MutatingRead:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):return self.stream.__exit__(*args)
            def fileno(self):return self.stream.fileno()
            def read(self,*args):
                raw=self.stream.read(*args);st=subject.file.stat()
                subject.file.write_bytes(b'abc')
                os.utime(subject.file,ns=(st.st_atime_ns,st.st_mtime_ns+1000000))
                return raw
        with patch.object(os,'fdopen',side_effect=lambda *a,**kw:MutatingRead(original(*a,**kw))):
            with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED_DURING_READ'):self.read('@HEADERS@/data')

    def test_open_descriptor_binds_content(self):
        original=os.open;count=[];saved=self.root/'saved'
        def opened(path,flags,*args,**kwargs):
            fd=original(path,flags,*args,**kwargs)
            if str(path).endswith('/data') and not flags&os.O_DIRECTORY:
                count.append(fd);self.file.rename(saved);self.file.write_bytes(b'bad')
            return fd
        with patch.object(os,'open',opened):
            self.assertEqual(self.read('@HEADERS@/data'),b'abc')
        self.assertEqual(len(count),1)
        with self.assertRaisesRegex(ValueError,'INFO_INPUT_PIN'):self.read('@HEADERS@/data')


class TargetTests(unittest.TestCase):
    def test_real_entrypoint_forwards_exact_dependency_set(self):
        m=load(P/'build.py','target_subject')
        for targets,expected in [('intel','intel'),('rtx','rtx'),('amd','rtx,amd'),('intel,rtx,amd','intel,rtx,amd')]:
            root=Path(tempfile.mkdtemp(prefix='targets-',dir=Path(os.environ['NDX12_TEST_ROOT']).resolve(strict=True)))
            argv=['build.py','--build-root',str(root/'build'),'--cache',str(root/'cache'),'--targets',targets]
            with patch.object(sys,'argv',argv),patch.object(m,'verify_sources',return_value={}),patch.object(m.subprocess,'run',side_effect=RuntimeError('PREPARER_REACHED')) as run:
                with self.assertRaisesRegex(RuntimeError,'PREPARER_REACHED'):m.main()
                cmd=run.call_args.args[0];self.assertIn('--targets',cmd)
                self.assertEqual(cmd[cmd.index('--targets')+1],expected)

    def test_unknown_target_before_preparer(self):
        m=load(P/'build.py','target_reject');root=Path(tempfile.mkdtemp(prefix='bad-target-',dir=Path(os.environ['NDX12_TEST_ROOT']).resolve(strict=True)))
        argv=['build.py','--build-root',str(root/'build'),'--cache',str(root/'cache'),'--targets','unknown']
        with patch.object(sys,'argv',argv),patch.object(m,'verify_sources',return_value={}),patch.object(m.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'TARGETS'):m.main()
            run.assert_not_called()


class BootstrapTests(unittest.TestCase):
    def test_actual_admit_rejects_wrong_pci_before_admission(self):
        m=load(P/'backends/nvidia/runtime/native_bootstrap.py','profile_subject')
        root=Path(tempfile.mkdtemp(prefix='pci-plan-',dir=Path(os.environ['NDX12_TEST_ROOT']).resolve(strict=True)))
        library=root/'not-a-library';library.write_bytes(b'CPU_ONLY_NOT_A_LIBRARY')
        admission=root/'admission.json';admission.write_text('{}')
        host=dict(kernel='synthetic',machine='x86_64',driver='615.78.08',model='NVIDIA GeForce RTX 4090',uuid='11'*16,
                  card=dict(domain=0,bus=1,slot=0,function=0,vendor=0x10de,device=0x2684,gpu_id=1,minor=0),nodes={})
        host['nodes']={k:dict(path=path,major=major,minor=minor) for k,path,major,minor in [('ctl','/dev/nvidiactl',195,255),('dev','/dev/nvidia0',195,0),('uvm','/dev/nvidia-uvm',511,0)]}
        base=dict(schema='native-affine-bootstrap.v1',nonce='CPU_ONLY',entry_sha256=pin(Path(m.__file__))['sha256'],loader=pin(P/'backends/nvidia/runtime/preparation_loader.py'),runtime=pin(P/'backends/nvidia/data/runtime_inputs.json'),abi=pin(P/'backends/nvidia/abi/abi.json'),library=pin(library),interpreter=dict(file=pin(Path(sys.executable).resolve()),version=sys.version,cache_tag=sys.implementation.cache_tag),host=host,admission=pin(admission),workload={},memory={},evidence=str(root/'not-executed'),record_budget={})
        for device,reason in [(0x2684,'BOOTSTRAP_ADMISSION_SCHEMA'),(0x2204,'BOOTSTRAP_GPU_DEVICE'),(0x2685,'BOOTSTRAP_GPU_DEVICE')]:
            value=copy.deepcopy(base);value['host']['card']['device']=device
            f=root/(str(device)+'.json');f.write_text(json.dumps(value))
            with self.subTest(device=hex(device)),self.assertRaisesRegex(m.BootstrapError,reason):m.admit(str(f),pin(f)['sha256'])


def loader_negatives(receipt_path):
    r=json.loads(Path(receipt_path).read_bytes());root=Path(r['roots']['PACKAGE'])
    loader=load(root/'backends/nvidia/runtime/preparation_loader.py','negative_loader')
    manifest=root/'backends/nvidia/data/runtime_inputs.json'
    spec=json.loads(manifest.read_bytes());temporary=Path(receipt_path).parent
    observed=[]
    def check(value,reason):
        raw=json.dumps(value).encode();f=temporary/('negative-'+str(len(observed))+'.json');f.write_bytes(raw)
        try:loader.verify(f,hashlib.sha256(raw).hexdigest())
        except Exception as error:
            if reason not in str(error):raise
        else:raise AssertionError('LOADER_FAIL_OPEN:'+reason)
        observed.append(reason)
    for locator,reason in [('@PACKAGE@/../outside','SOURCE_TRAVERSAL'),('@PACKAGE@//etc/passwd','SOURCE_TRAVERSAL'),('@UNKNOWN@/x','SOURCE_LOCATOR'),('@PACKAGE@/bad\\name','SOURCE_TRAVERSAL')]:
        value=copy.deepcopy(spec);value['entries']['flags']['path']=locator;check(value,reason)
    value=copy.deepcopy(spec);value['entries']['flags']['sha256']='0'*64;check(value,'LOADER_SOURCE_PIN:flags')
    flags=loader.PATHS['flags'];saved=flags.with_name('flags-test-saved');flags.rename(saved)
    try:
        check(spec,'No such file or directory')
        outside=temporary/'outside-flags';outside.write_bytes(saved.read_bytes())
        flags.symlink_to(outside)
        try:check(spec,'SOURCE_ESCAPE')
        finally:flags.unlink()
        flags.write_bytes(b'bad');flags.chmod(saved.stat().st_mode&0o777)
        check(spec,'LOADER_SOURCE_PIN:flags')
    finally:
        if flags.exists() or flags.is_symlink():flags.unlink()
        saved.rename(flags)
    original=os.open;calls=[]
    def opened(path,opts,*args,**kwargs):
        fd=original(path,opts,*args,**kwargs)
        if str(path).endswith('/mapping_flags.json') and not opts&os.O_DIRECTORY:
            calls.append(fd);flags.rename(saved);flags.write_bytes(b'bad')
        return fd
    try:
        with patch.object(os,'open',opened):snapshots=loader.verify(manifest,r['manifest_sha256'])
        if len(calls)!=1 or len(snapshots)!=81:raise AssertionError('DESCRIPTOR_READ_COUNT')
        observed.append('PIN_FROM_OPEN_DESCRIPTOR')
    finally:
        if saved.exists():flags.unlink();saved.rename(flags)
    if len(loader.verify(manifest,r['manifest_sha256']))!=81:raise AssertionError('RESTORE')
    print(json.dumps(dict(cases=len(observed),outcomes=observed,gpu='NOT_RUN')))


def card_probe(receipt_path):
    r=json.loads(Path(receipt_path).read_bytes());root=Path(r['roots']['PACKAGE'])
    loader=load(root/'backends/nvidia/runtime/preparation_loader.py','card_loader')
    modules=loader.Loader().load(root/'backends/nvidia/data/runtime_inputs.json',r['manifest_sha256'])
    L=modules['linux_backend'];A=modules['replacement_inputs'].arena
    abi=A.Abi(loader.PATHS['abi'],modules['replacement_inputs'].ABI_SHA)
    observed=[]
    for expected,actual,wanted in [(0x2204,0x2204,'CARD_GPU_PROFILE'),(0x2684,0x2204,'IDENTITY_MISMATCH'),(0x2684,0x2684,'ACCEPT')]:
        b=object.__new__(L.LinuxBackend);b.phase='ACTIVE';b.card_verified=False;b.abi=abi
        calls=[];fds=[]
        pci=abi.struct('nv_pci_info_t').pack(dict(domain=0,bus=1,slot=0,function=0,vendor_id=0x10de,device_id=actual))
        result=abi.struct('nv_ioctl_card_info_t').pack(dict(valid=1,pci_info=pci,gpu_id=1,minor_number=0))
        def ioctl(node,request,data):calls.append((node,request));data[:]=result;return 0
        def fd(node):fds.append(node);return 5
        b.ioctl=ioctl;b._fd=fd;b.fd_identity={'dev':(0,0,os.makedev(195,0))}
        try:b.verify_card(L.Card(0,1,0,0,0x10de,expected,1,0))
        except (A.Rejected,A.Stop) as error:
            if wanted not in str(error):raise
        else:
            if wanted!='ACCEPT':raise AssertionError('GPU_FAIL_OPEN:'+wanted)
        if wanted=='CARD_GPU_PROFILE' and (calls or fds):raise AssertionError('WRONG_PLAN_TOUCHED_DEVICE')
        if wanted=='IDENTITY_MISMATCH' and (len(calls)!=1 or fds or b.card_verified):raise AssertionError('WRONG_ACTUAL_CARD_ACCEPTED')
        if wanted=='ACCEPT' and (len(calls)!=1 or fds!=['dev'] or not b.card_verified):raise AssertionError('QUALIFIED_CARD_NOT_BOUND')
        observed.append(wanted)
    print(json.dumps(dict(cases=len(observed),outcomes=observed,gpu='NOT_RUN')))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--card-probe':card_probe(sys.argv[2])
    elif len(sys.argv)>1 and sys.argv[1]=='--loader-negatives':loader_negatives(sys.argv[2])
    else:unittest.main()
