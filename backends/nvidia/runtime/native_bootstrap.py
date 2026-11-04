"""Explicit one-shot native entry. Verification is CPU-only; execute needs owner GO.

Trusted isolated CPython/stdlib, reviewed source/plan pins and a detached,
exclusive admitted host are prerequisites. No fixture imports or injected factory.
"""
import argparse
from dataclasses import dataclass, fields, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
import types

HERE = Path(__file__).resolve().parent
_PLAN_LIMIT = 256 * 1024
_FILE_LIMIT = 64 * 1024 * 1024


class BootstrapError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise BootstrapError(reason)


def keys(value, names, reason):
    require(type(value) is dict and set(value) == set(names.split()), reason)


def integer(value, low, high, reason):
    require(type(value) is int and low <= value <= high, reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'BOOTSTRAP_DUPLICATE_KEY')
        result[key] = value
    return result


def parse(raw):
    require(type(raw) is bytes and 0 < len(raw) <= _PLAN_LIMIT, 'BOOTSTRAP_JSON_SIZE')
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(BootstrapError('BOOTSTRAP_JSON_CONSTANT')))


def path(value):
    require(type(value) is str and value.startswith('/') and all(ord(c) >= 32 for c in value),
            'BOOTSTRAP_PATH')
    p = Path(value)
    require('..' not in p.parts and str(p) == value, 'BOOTSTRAP_PATH')
    for part in (p, *p.parents):
        require(not part.is_symlink(), 'BOOTSTRAP_SYMLINK')
    return p


def read_pin(spec):
    keys(spec, 'path size mode sha256', 'BOOTSTRAP_FILE_SPEC')
    integer(spec['size'], 1, _FILE_LIMIT, 'BOOTSTRAP_FILE_SIZE')
    integer(spec['mode'], 0, 0o777, 'BOOTSTRAP_FILE_MODE')
    require(type(spec['sha256']) is str and len(spec['sha256']) == 64
            and all(c in '0123456789abcdef' for c in spec['sha256']), 'BOOTSTRAP_FILE_HASH')
    p = path(spec['path'])
    info = p.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_size == spec['size']
            and stat.S_IMODE(info.st_mode) == spec['mode'], 'BOOTSTRAP_FILE_METADATA')
    with p.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        require((opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino), 'BOOTSTRAP_FILE_IDENTITY')
        raw = stream.read(spec['size'] + 1)
    after = p.lstat()
    require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            'BOOTSTRAP_FILE_CHANGED')
    require(len(raw) == spec['size'] and digest(raw) == spec['sha256'], 'BOOTSTRAP_FILE_PIN')
    return raw


def frozen(value):
    if type(value) is dict:
        return types.MappingProxyType({k: frozen(v) for k, v in value.items()})
    if type(value) is list:
        return tuple(frozen(v) for v in value)
    return value


def plain(value):
    if value is None or type(value) in (str, int, bool, float):
        return value
    if type(value) is bytes:
        return {'bytes_hex': value.hex()}
    if isinstance(value, (dict, types.MappingProxyType)):
        return {k: plain(v) for k, v in value.items()}
    if type(value) in (tuple, list):
        return [plain(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    raise BootstrapError('BOOTSTRAP_EVENT_TYPE')


def encoded(value):
    return (json.dumps(plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


@dataclass(frozen=True)
class Prepared:
    raw: bytes
    sha256: str
    document: object
    modules: object
    abi: object
    handles: object
    card: object
    nodes: object
    arena: object
    channel: object
    layout: object
    slots: tuple


def admit(plan_path, expected_sha):
    p = path(plan_path)
    require(type(expected_sha) is str and len(expected_sha) == 64
            and all(c in '0123456789abcdef' for c in expected_sha), 'BOOTSTRAP_PLAN_HASH')
    require(stat.S_ISREG(p.lstat().st_mode) and 0 < p.stat().st_size <= _PLAN_LIMIT, 'BOOTSTRAP_PLAN_FILE')
    with p.open('rb') as stream:
        raw = stream.read(_PLAN_LIMIT + 1)
    require(len(raw) <= _PLAN_LIMIT and digest(raw) == expected_sha, 'BOOTSTRAP_PLAN_PIN')
    d = parse(raw)
    keys(d, 'schema nonce entry_sha256 loader runtime abi library interpreter host admission workload memory evidence record_budget',
         'BOOTSTRAP_PLAN_SCHEMA')
    require(d['schema'] in ('native-bootstrap.v1', 'native-affine-bootstrap.v1'), 'BOOTSTRAP_PLAN_SCHEMA')
    affine = d['schema'] == 'native-affine-bootstrap.v1'
    require(type(d['nonce']) is str and 1 <= len(d['nonce']) <= 128
            and all(c.isascii() and (c.isalnum() or c in '-_') for c in d['nonce']), 'BOOTSTRAP_NONCE')
    require(d['entry_sha256'] == digest(Path(__file__).read_bytes()), 'BOOTSTRAP_ENTRY_PIN')
    loader_raw = read_pin(d['loader'])
    require(d['loader']['path'] == str(HERE / 'preparation_loader.py'), 'BOOTSTRAP_LOADER_PATH')
    read_pin(d['runtime'])
    require(d['runtime']['path'] == str((HERE.parent / 'data' / 'runtime_inputs.json')), 'BOOTSTRAP_RUNTIME_PATH')
    abi_raw = read_pin(d['abi'])
    read_pin(d['library'])
    keys(d['interpreter'], 'file version cache_tag', 'BOOTSTRAP_INTERPRETER_SPEC')
    read_pin(d['interpreter']['file'])
    require(d['interpreter']['file']['path'] == str(Path(sys.executable).resolve())
            and d['interpreter']['version'] == sys.version
            and d['interpreter']['cache_tag'] == sys.implementation.cache_tag,
            'BOOTSTRAP_INTERPRETER_PIN')
    keys(d['host'], 'kernel machine driver model uuid card nodes', 'BOOTSTRAP_HOST_SPEC')
    host = d['host']
    require(all(type(host[k]) is str and host[k] for k in ('kernel','machine','driver','model','uuid'))
            and host['machine'] == 'x86_64' and host['model'].endswith('GeForce RTX 4090')
            and len(host['uuid']) == 32 and all(c in '0123456789abcdef' for c in host['uuid']), 'BOOTSTRAP_HOST_PROFILE')
    keys(host['card'], 'domain bus slot function vendor device gpu_id minor', 'BOOTSTRAP_CARD')
    for k, maximum in (('domain',65535),('bus',255),('slot',31),('function',7),('vendor',65535),
                        ('device',65535),('gpu_id',0xffffffff),('minor',0xfffff)):
        integer(host['card'][k], 0, maximum, 'BOOTSTRAP_CARD')
    require(host['card']['vendor'] == 0x10de, 'BOOTSTRAP_VENDOR')
    require(host['card']['device'] == 0x2684, 'BOOTSTRAP_GPU_DEVICE')
    keys(host['nodes'], 'ctl dev uvm', 'BOOTSTRAP_NODES')
    expected_nodes = {'ctl':'/dev/nvidiactl','dev':'/dev/nvidia'+str(host['card']['minor']),'uvm':'/dev/nvidia-uvm'}
    for k, node in host['nodes'].items():
        keys(node, 'path major minor', 'BOOTSTRAP_NODE')
        require(node['path'] == expected_nodes[k], 'BOOTSTRAP_NODE_PATH')
        integer(node['major'],0,4095,'BOOTSTRAP_NODE_NUMBER')
        integer(node['minor'],0,0xfffff,'BOOTSTRAP_NODE_NUMBER')
    admission = parse(read_pin(d['admission']))
    keys(admission, 'schema nonce host runtime_sha256 library_sha256 interpreter_sha256 entry_sha256 evidence',
         'BOOTSTRAP_ADMISSION_SCHEMA')
    require(admission['schema'] == 'native-host-admission.v1' and admission['nonce'] == d['nonce']
            and admission['host'] == host and admission['runtime_sha256'] == d['runtime']['sha256']
            and admission['library_sha256'] == d['library']['sha256']
            and admission['interpreter_sha256'] == d['interpreter']['file']['sha256']
            and admission['entry_sha256'] == d['entry_sha256'], 'BOOTSTRAP_ADMISSION_BINDING')
    keys(admission['evidence'], 'supervisor exclusive_gpu kernel_access filesystem owner_go', 'BOOTSTRAP_ADMISSION_EVIDENCE')
    for spec in admission['evidence'].values():
        read_pin(spec)  # Byte identity only; independent owner review supplies authority.
    w = d['workload']
    if affine:
        keys(w, 'profile values seed multiplier addend reserved prefix signal', 'BOOTSTRAP_WORKLOAD')
        require(w['profile'] == 'affine-u32', 'BOOTSTRAP_AFFINE_PROFILE')
        require(type(w['values']) is list and len(w['values']) in (1,127,128,129,515), 'BOOTSTRAP_AFFINE_CASE')
        for value in (*w['values'],w['seed'],w['multiplier'],w['addend']):
            integer(value,0,0xffffffff,'BOOTSTRAP_AFFINE_U32')
        require(type(w['reserved']) is list and len(w['reserved']) == 4
                and all(type(v) is int and v == 0 for v in w['reserved']), 'BOOTSTRAP_AFFINE_RESERVED')
        require(type(w['prefix']) is int and w['prefix'] == 1, 'BOOTSTRAP_PREFIX')
    else:
        keys(d['workload'], 'keys max_groups prefix signal', 'BOOTSTRAP_WORKLOAD')
        require(type(w['keys']) is list, 'BOOTSTRAP_KEYS')
        for key in w['keys']:
            integer(key,0,0xffffffff,'BOOTSTRAP_KEY')
        integer(w['max_groups'],1,800,'BOOTSTRAP_GROUPS')
        require(type(w['prefix']) is int and w['prefix'] in (1,40), 'BOOTSTRAP_PREFIX')
    integer(w['signal'],1,0xffffffff,'BOOTSTRAP_SIGNAL')
    require(type(d['memory']) is dict, 'BOOTSTRAP_MEMORY')
    extra = ' channel_region_alignment channel_region_factor' if d['memory'].get('channel_region_profile') == 'REPORTED_TOTAL_SIZE' else ''
    keys(d['memory'], 'handles arena channel region_maximum_size slots channel_region_profile' + extra, 'BOOTSTRAP_MEMORY')
    memory = d['memory']
    require(type(memory['channel_region_profile']) is str and memory['channel_region_profile'] in
            ('REQUIRED_BUFFER_INFO','ZERO_REGION','SIZE_QUERY_PROBE','REPORTED_TOTAL_SIZE'), 'BOOTSTRAP_REGION_PROFILE')
    keys(memory['handles'],'client device subdevice vas memory usermode tsg context channel compute','BOOTSTRAP_HANDLES')
    for value in memory['handles'].values():
        integer(value,0,0xffffffff,'BOOTSTRAP_HANDLES')
    require(memory['handles']['client'] == 0, 'BOOTSTRAP_CLIENT')
    keys(memory['arena'],'base size budget memory_class layout_bytes','BOOTSTRAP_ARENA')
    keys(memory['channel'],'usermode_base region_base ring_offset userd_offset','BOOTSTRAP_CHANNEL')
    require(type(memory['slots']) is list and len(memory['slots']) == 4, 'BOOTSTRAP_SLOTS')
    for slot in memory['slots']:
        keys(slot,'role memory base maximum_size','BOOTSTRAP_SLOT')
        for k in ('memory','base','maximum_size'):
            integer(slot[k],1,(1<<40)-1,'BOOTSTRAP_SLOT')
    integer(memory['region_maximum_size'],4096,(128 if memory['channel_region_profile'] == 'REPORTED_TOTAL_SIZE' else 64)*1024*1024,'BOOTSTRAP_REGION_SIZE')
    require(memory['region_maximum_size'] % 4096 == 0, 'BOOTSTRAP_REGION_SIZE')
    if memory['channel_region_profile'] == 'REPORTED_TOTAL_SIZE':
        require(type(memory['channel_region_alignment']) is int and memory['channel_region_alignment'] == 2 * 1024 * 1024
                and type(memory['channel_region_factor']) is int and memory['channel_region_factor'] in (1, 2)
                and memory['region_maximum_size'] == 128 * 1024 * 1024
                and memory['channel']['region_base'] % memory['channel_region_alignment'] == 0,
                'BOOTSTRAP_REGION_PROFILE')
    path(d['evidence'])
    require(not Path(d['evidence']).exists(), 'BOOTSTRAP_EVIDENCE_EXISTS')
    keys(d['record_budget'],'events bytes','BOOTSTRAP_RECORD_BUDGET')
    integer(d['record_budget']['events'],1,65536,'BOOTSTRAP_RECORD_BUDGET')
    integer(d['record_budget']['bytes'],4096,16*1024*1024,'BOOTSTRAP_RECORD_BUDGET')
    name = '_ndx_native_bootstrap_loader'
    require(name not in sys.modules, 'BOOTSTRAP_LOADER_PRELOAD')
    loader = types.ModuleType(name)
    loader.__file__ = d['loader']['path']
    sys.modules[name] = loader
    exec(compile(loader_raw, loader.__file__, 'exec'), loader.__dict__)
    modules = loader.Loader().load(Path(d['runtime']['path']), d['runtime']['sha256'])
    require(d['abi']['path'] == str(loader.PATHS['abi'])
            and d['abi']['sha256'] == modules['replacement_inputs'].ABI_SHA, 'BOOTSTRAP_ABI_BINDING')
    # Exact provenance string from the admitted ABI, not a caller's compatibility claim.
    # A different driver requires its own reviewed ABI/profile, never a plan override.
    require(parse(abi_raw)['probe']['headers'] ==
            'nvidia-open-gpu-kernel-modules ' + host['driver'] +
            ' export (hashes in SOURCE_LEDGER.md)', 'BOOTSTRAP_DRIVER_ABI')
    n = modules['native_words_binding']
    require((d['library']['sha256'],d['library']['size'],d['library']['mode']) ==
            (n.LIBRARY_SHA256,n.LIBRARY_SIZE,n.LIBRARY_MODE), 'BOOTSTRAP_LIBRARY_BINDING')
    abi = modules['replacement_inputs'].arena.Abi(d['abi']['path'], d['abi']['sha256'])
    b, ci = modules['linux_backend'], modules['channel_images']
    handles, card = ci.Handles(**memory['handles']), b.Card(**host['card'])
    nodes = {k:b.Node(**v) for k,v in host['nodes'].items()}
    # These constructors are pure configuration. This backend is never used by
    # the execution factory; LinuxOps is not constructed by verify-only.
    backend = b.LinuxBackend(abi,nodes,None,[],lambda event:None)
    tree = modules['rm_channel'].IdentityTree(backend,handles,card,bytes.fromhex(host['uuid']))
    arena = modules['channel_resources'].ArenaConfig(**memory['arena'])
    session = modules['channel_resources'].ArenaSession(tree,arena)
    channel = modules['channel_objects'].ChannelConfig(**memory['channel'])
    channel.validate(session)
    if affine:
        layout = modules['affine_data'].AffineLayout(tuple(w['values']),w['seed'],w['multiplier'],
                                                   w['addend'],tuple(w['reserved']))
        layout.validate()
    else:
        layout = modules['sort_data_layout'].layout_for(tuple(w['keys']),w['max_groups'])
    slots = tuple(modules['data_resources'].DataSlot(**s) for s in memory['slots'])
    require(tuple(s.role for s in slots) ==
            (modules['affine_data'].ROLES if affine else modules['sort_data_layout'].ROLES), 'BOOTSTRAP_DATA_ROLES')
    used_handles = tuple(v for v in memory['handles'].values() if v) + tuple(s.memory for s in slots)
    require(len(set(used_handles)) == len(used_handles) and all(s.memory <= 0xffffffff for s in slots), 'BOOTSTRAP_HANDLE_ALIAS')
    spans = [(arena.base,arena.size),(channel.usermode_base,abi.const('NVC361_NV_USERMODE__SIZE')),
             (channel.region_base,memory['region_maximum_size'])]
    for slot in slots:
        require(slot.base % 4096 == 0 and slot.maximum_size % 4096 == 0
                and layout.logical_bytes <= slot.maximum_size, 'BOOTSTRAP_DATA_SIZE')
        spans.append((slot.base,slot.maximum_size))
    require(sum(s.maximum_size for s in slots) + arena.size <= 64*1024*1024, 'BOOTSTRAP_MEMORY_BUDGET')
    for i,(base,size) in enumerate(spans):
        require(type(base) is int and base > 0 and base + size <= (1<<47 if i==1 else 1<<40), 'BOOTSTRAP_VA')
        require(all(base+size<=b or b+n<=base for b,n in spans[:i]), 'BOOTSTRAP_VA_ALIAS')
    modules['push_images'].check_window_spans(tuple(spans))
    work = layout if affine else modules['sort_workload'].plan(layout)
    control = modules['control_layout']
    control.plan(work,control.ModelArena(arena.base,arena.size,channel.ring_offset,
                 channel.userd_offset,modules['push_images'].byte_length(w['prefix'])))
    return Prepared(raw,expected_sha,frozen(d),modules,abi,handles,card,types.MappingProxyType(nodes),arena,channel,layout,slots)


def detached():
    require(os.getsid(0) == os.getpid(), 'BOOTSTRAP_NOT_SESSION_LEADER')
    status = Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
    require(int(status[4]) == 0 and not any(os.isatty(fd) for fd in (0,1,2)), 'BOOTSTRAP_CONTROLLING_TERMINAL')
    require(all(stat.S_ISREG(os.fstat(fd).st_mode) for fd in (1,2)), 'BOOTSTRAP_OUTPUT_FILES')
    stdin, null = os.fstat(0), os.stat('/dev/null')
    require(stat.S_ISCHR(stdin.st_mode) and stdin.st_rdev == null.st_rdev, 'BOOTSTRAP_STDIN')


def host_check(prepared):
    d, expected = prepared.document, prepared.document['host']
    require(sys.platform == 'linux' and sys.byteorder == 'little'
            and sys.implementation.name == 'cpython' and sys.flags.isolated == 1
            and sys.flags.dont_write_bytecode == 1
            and callable(getattr(sys,'_is_gil_enabled',None)) and sys._is_gil_enabled(), 'BOOTSTRAP_HOST_RUNTIME')
    uname = os.uname()
    require(uname.machine == expected['machine'] and uname.release == expected['kernel'], 'BOOTSTRAP_HOST_KERNEL')
    version = Path('/proc/driver/nvidia/version').read_text()
    require(expected['driver'] in version.split(), 'BOOTSTRAP_HOST_DRIVER')
    c = expected['card']
    bdf = f"{c['domain']:04x}:{c['bus']:02x}:{c['slot']:02x}.{c['function']:x}"
    device = Path('/sys/bus/pci/devices') / bdf
    require(int((device/'vendor').read_text(),16)==c['vendor']
            and int((device/'device').read_text(),16)==c['device'], 'BOOTSTRAP_HOST_PCI')
    info = Path('/proc/driver/nvidia/gpus',bdf,'information').read_text()
    rows = dict(line.split(':',1) for line in info.splitlines() if ':' in line)
    rows = {k.strip():v.strip() for k,v in rows.items()}
    require(rows.get('Model') == expected['model']
            and rows.get('GPU UUID','').removeprefix('GPU-').replace('-','').lower() == expected['uuid']
            and rows.get('Device Minor') == str(c['minor']), 'BOOTSTRAP_HOST_GPU')
    for node in prepared.nodes.values():
        metadata = Path(node.path).lstat()
        require(stat.S_ISCHR(metadata.st_mode) and os.major(metadata.st_rdev)==node.major
                and os.minor(metadata.st_rdev)==node.minor, 'BOOTSTRAP_HOST_NODE')
    return {'kernel':uname.release,'machine':uname.machine,'driver_text':version,'gpu_information':info,'bdf':bdf}


class Journal:
    def __init__(self, root, budget):
        self.root, self.budget = root, budget
        self.sequence, self.bytes = 0, 0
        self.last_event = None

    def append(self, source, event):
        self.last_event = {'source':source,'sequence':self.sequence,'event':plain(event)}
        self.sequence += 1
        raw = encoded(self.last_event)
        require(len(self.root.events) < self.budget['events'] and self.bytes+len(raw)<=self.budget['bytes'],
                'BOOTSTRAP_EVENT_BUDGET')
        self.bytes += len(raw)
        self.root.events.append(json.loads(raw))

    def backend(self, event):
        self.append('backend',event)

    def publication(self, event):
        self.append('publication',event)


def factory(root):
    p, r = root.prepared, root.registry
    m, d = p.modules, p.document
    r.checkpoint()
    require(all(sys.modules.get(name) is module for name,module in m.items()), 'BOOTSTRAP_MODULE_BINDING')
    require(digest(p.raw) == p.sha256, 'BOOTSTRAP_PLAN_CHANGED')
    root.health_object = m['native_execution_health'].KernelHealth()
    root.health_object.start()
    root.host_observation = host_check(p)
    root.journal.append('host',root.host_observation)
    identity = m['bootstrap_identity'].BootstrapIdentity(Path(d['evidence']),p.raw,p.sha256)
    identity.commit()
    r.checkpoint()
    words = m['native_words_binding'].NativeWords()
    r.attach('words',words)
    words.load(d['library']['path'])
    r.checkpoint()
    root.ops = m['linux_backend'].LinuxOps()
    backend = m['linux_backend'].LinuxBackend(p.abi,dict(p.nodes),root.ops,root.owners,root.recorder)
    r.attach('backend',backend)
    tree = m['rm_channel'].IdentityTree(backend,p.handles,p.card,bytes.fromhex(d['host']['uuid']))
    r.attach('tree',tree)
    root.session = m['channel_resources'].ArenaSession(tree,p.arena)
    root.objects = m['channel_objects'].ChannelObjects(root.session,p.channel,m['preparation_upload'].native_read,
                    region_profile=d['memory']['channel_region_profile'],
                    region_alignment=d['memory'].get('channel_region_alignment'),
                    region_factor=d['memory'].get('channel_region_factor'),
                    region_budget=d['memory']['region_maximum_size'] if d['memory']['channel_region_profile'] == 'REPORTED_TOTAL_SIZE' else None)
    identity.verify()
    r.checkpoint()
    root.objects.prepare()
    require(root.objects.binding().region_length <= d['memory']['region_maximum_size'], 'BOOTSTRAP_RETURNED_REGION')
    r.checkpoint()
    root.data = m['data_resources'].DataResources(root.objects,p.layout,p.slots)
    root.data.acquire()
    r.checkpoint()
    packet = m['packet_preparation'].PacketPreparation(root.data,m['preparation_upload'].native_read,
                                                       m['preparation_upload'].native_write)
    r.attach('preparation',packet)
    packet.prepare(d['workload']['prefix'],d['workload']['signal'])
    r.checkpoint()
    bridge = m['packet_schedule'].PacketSchedule(packet,bind_group=False)
    r.attach('schedule',bridge)
    bridge.schedule()
    r.checkpoint()
    controller = m['native_packet_publication'].PacketPublicationNative(bridge,words,record=root.observer)
    root.completion = m['native_packet_completion'].PacketCompletionNative(controller)
    r.attach('publication',controller)
    controller.publish()
    root.completion.finish()
    r.checkpoint()
    root.execution = m['native_execution'].NativeExecution(root.completion)
    root.execution.disable()
    root.store = m['native_execution_evidence'].EvidenceStore(identity.directory/'packet')
    root.retirement = m['native_retirement'].NativeRetirement(root.execution,root.store)
    return root.retirement.retire()


def report(root):
    r = root.registry
    profile = root.prepared.document['memory']['channel_region_profile']
    result = None if r.result is None else dict(plain(r.result),channel_region_profile=profile)
    value = {'channel_region_profile':profile,'nonce':root.nonce,'phase':r.phase,'owners':len(root.owners),
        'primary':None if r.primary is None else {'type':type(r.primary).__name__,'message':str(r.primary)},
        'result':result,'events':root.events,'last_event':root.journal.last_event,
        'native_execution_proven':False}
    root.diagnostic = encoded(value)
    directory = Path(root.prepared.document['evidence'])
    if directory.is_dir():
        fd = os.open(directory/'.diagnostic.pending',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
        root.diagnostic_fds.append(fd)
        try:
            offset = 0
            while offset < len(root.diagnostic):
                n = os.write(fd,root.diagnostic[offset:])
                require(type(n) is int and 0<n<=len(root.diagnostic)-offset,'BOOTSTRAP_DIAGNOSTIC_WRITE')
                offset += n
            os.fsync(fd)
            os.rename(directory/'.diagnostic.pending',directory/'diagnostic.json')
            parent = os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|os.O_NOFOLLOW)
            root.diagnostic_fds.append(parent)
            os.fsync(parent)
        finally:
            first = None
            while root.diagnostic_fds:
                try:
                    os.close(root.diagnostic_fds.pop())
                except BaseException as exc:
                    if first is None:
                        first = exc
            if first is not None:
                raise first
    print(json.dumps({'nonce':root.nonce,'phase':r.phase,'owners':len(root.owners),
                      'native_execution_proven':False}),file=sys.stderr,flush=True)
    os.fsync(2)


def execute(prepared):
    detached()
    r = prepared.modules['process_retention'].REGISTRY
    root = types.SimpleNamespace(**{name:None for name in r.NAMES})
    root.nonce, root.owners, root.events = prepared.document['nonce'], [], []
    root.prepared, root.registry = prepared, r
    root.diagnostic_fds = []
    root.journal = Journal(root,prepared.document['record_budget'])
    root.recorder, root.observer = root.journal.backend, root.journal.publication
    return r.serve(root,factory,reporters=(lambda registry:report(root),))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',required=True)
    parser.add_argument('--sha256',required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--verify-only',action='store_true')
    action.add_argument('--execute',action='store_true')
    args = parser.parse_args(argv)
    prepared = admit(args.plan,args.sha256)
    if args.verify_only:
        print(json.dumps({'status':'CPU_BOOTSTRAP_PLAN_VERIFIED','plan_sha256':prepared.sha256,
                          'native_execution_proven':False,'gpu_executed':False}))
        return 0
    return execute(prepared)


if __name__ == '__main__':
    raise SystemExit(main())
