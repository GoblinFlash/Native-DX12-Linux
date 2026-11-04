"""Offline runtime materializer. Inputs are pinned source templates and built artifacts."""
import hashlib, json, os, re, stat, tempfile
from pathlib import Path, PurePosixPath

def require(ok, reason):
    if not ok: raise ValueError(reason)
def digest(raw): return hashlib.sha256(raw).hexdigest()
def unique(pairs):
    out={}
    for k,v in pairs:
        require(k not in out,'DUPLICATE_KEY');out[k]=v
    return out
def parse(raw): return json.loads(raw,object_pairs_hook=unique)
def encode(v): return (json.dumps(v,indent=2,sort_keys=True)+'\n').encode()
def lexical(path):
    p=Path(path)
    require(p.is_absolute() and '..' not in p.parts,'ROOT_PATH')
    for q in (p,*p.parents): require(not q.is_symlink(),'ROOT_SYMLINK')
    return p
def roots_checked(roots, authority):
    authority=lexical(authority)
    require(set(roots)=={'PACKAGE','ARTIFACTS','HEADERS'},'ROOT_SET')
    out={k:lexical(v) for k,v in roots.items()}
    for p in out.values():
        require(p!=authority and p.is_relative_to(authority),'ROOT_UNAUTHORIZED')
    for k,p in out.items():
        for n,q in out.items():
            if n!=k: require(not p.is_relative_to(q) and not q.is_relative_to(p),'ROOT_OVERLAP')
    require(out=={k:authority/k.lower() for k in ('PACKAGE','ARTIFACTS','HEADERS')},'ROOT_LAYOUT')
    return out
def resolve(locator, roots):
    require(type(locator) is str,'LOCATOR_TYPE')
    m=re.fullmatch(r'@(PACKAGE|ARTIFACTS|HEADERS)@/(.+)',locator)
    require(m is not None,'LOCATOR_ROOT')
    rel=m[2];parts=rel.split('/')
    require(all(x not in ('','.', '..') for x in parts) and '\\' not in rel,'LOCATOR_TRAVERSAL')
    root=lexical(roots[m[1]]);p=lexical(root.joinpath(*parts))
    require(p.is_relative_to(root),'LOCATOR_ESCAPE')
    return p

class InstallFailure(RuntimeError):
    """Original I/O failure plus preserved recovery evidence; not crash recovery."""
    def __init__(self, error, receipt, retry_ready):
        super().__init__('INSTALL_IO_FAILED:' + str(error) + ':receipt=' + str(receipt))
        self.receipt = receipt
        self.retry_ready = retry_ready


def _identity(path):
    st = lexical(path).lstat()
    return st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode)


def _receipt(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())


def _write_installation(contents, modes, roots, authority):
    # Exclusive writer ownership is required; this is not a hostile-filesystem sandbox.
    authority = lexical(authority)
    authority.mkdir(parents=True, exist_ok=True)
    files, directories = [], []

    def mkdir(path):
        lexical(path)
        if path == authority:
            return
        if path.exists():
            require(path.is_dir(), 'INSTALL_PARENT_TYPE')
            return
        mkdir(path.parent)
        path.mkdir()  # Never acquire ownership of another writer's existing directory.
        directories.append((path, _identity(path)))

    try:
        # Reserve all roots exclusively before writing a single output file.
        for root in roots.values():
            mkdir(root.parent)
            root.mkdir()
            directories.append((root, _identity(root)))
        for path, data in contents.items():
            lexical(path)
            mkdir(path.parent)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, modes[path])
            st = os.fstat(fd)
            files.append((path, (st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode))))
            try:
                stream = os.fdopen(fd, 'wb')
            except OSError:
                os.close(fd)
                raise
            with stream as f:
                f.write(data)
            os.chmod(path, modes[path])
    except OSError as error:
        # Persist the failure/move plan BEFORE moving anything. If storage is still
        # full, preserve the original paths and fail closed, without rollback.
        receipt = None
        try:
            saved = Path(tempfile.mkdtemp(prefix='failed-install-', dir=authority))
            plan = [{'path': str(p), 'saved': str(saved / ('file-' + str(i))),
                     'identity': list(identity)}
                    for i, (p, identity) in enumerate(files)]
            receipt = saved / 'failure.json'
            _receipt(receipt, {'schema': 'install-failure.v1', 'error': str(error),
                              'errno': error.errno, 'files': plan,
                              'roots': {k: str(v) for k, v in roots.items()}})
        except OSError as evidence_error:
            # A missing or incomplete failure record is not a usable receipt.
            raise InstallFailure(error, None, False) from evidence_error
        moved, recovery_errors = [], []
        for row in reversed(plan):
            path, target = Path(row['path']), Path(row['saved'])
            try:
                require(_identity(path) == tuple(row['identity'])
                        and row['identity'][2] == stat.S_IFREG, 'RECOVERY_FILE_IDENTITY')
                require(not target.exists(), 'RECOVERY_DESTINATION_EXISTS')
                os.rename(path, target)  # Retain full or partial bytes; never unlink files.
                moved.append(row)
            except (OSError, ValueError) as recovery_error:
                recovery_errors.append({'path': str(path), 'error': str(recovery_error)})
        for path, identity in reversed(directories):
            try:
                require(_identity(path) == identity and identity[2] == stat.S_IFDIR,
                        'RECOVERY_DIRECTORY_IDENTITY')
                path.rmdir()  # Only our inode, only if empty; foreign files prevent removal.
            except (OSError, ValueError) as recovery_error:
                recovery_errors.append({'path': str(path), 'error': str(recovery_error)})
        ready = not any(p.exists() or p.is_symlink() for p in roots.values())
        try:
            _receipt(saved / 'recovery.json', {'schema': 'install-recovery.v1',
                     'moved': moved, 'errors': recovery_errors, 'retry_ready': ready})
        except OSError as evidence_error:
            raise InstallFailure(error, receipt, False) from evidence_error
        raise InstallFailure(error, receipt, ready) from error


def install(bundle, expected_lock, roots, authority):
    bundle=lexical(bundle);roots=roots_checked(roots,authority)
    lockraw=(bundle/'template-lock.json').read_bytes()
    require(digest(lockraw)==expected_lock,'LOCK_PIN')
    lock=parse(lockraw);require(lock['schema']=='ndx12.runtime-templates.v2','LOCK_SCHEMA')
    require(len(lock['source_paths'])==133 and len(set(lock['source_paths']))==133,'SOURCE_SET')
    require(all(not p.exists() for p in roots.values()),'DESTINATION_EXISTS')
    contents={};modes={};records={}
    for row in lock['files']:
        rel=row['template'];require('..' not in PurePosixPath(rel).parts and not rel.startswith('/'),'TEMPLATE_PATH')
        p=lexical(bundle/rel);st=p.lstat();require(stat.S_ISREG(st.st_mode),'TEMPLATE_REGULAR')
        b=p.read_bytes();require(len(b)==row['template_bytes'] and digest(b)==row['template_sha256'],'TEMPLATE_PIN:'+rel)
        dest=resolve(row['locator'],roots);require(dest not in contents,'DESTINATION_DUPLICATE')
        # Raw binary inputs are never decoded, rewritten or executed.
        # Preserve logical locators in installed bytes; consumers bind them to __file__.
        if row['text']:
            b.decode()  # Still reject malformed text templates.
        contents[dest]=b;modes[dest]=row['mode'];records[dest]=row
    # Fixed point over source hashes and manifest entries, all in memory.
    initial=dict(contents);identities={r['baseline_sha256']:p for p,r in records.items()}
    for _ in range(16):
        before=dict(contents)
        for p,base in initial.items():
            row=records[p]
            if not row['text']:continue
            if p.suffix=='.json':
                obj=parse(base)
                def pin(v):
                    if isinstance(v,dict):
                        locator=v.get('path','')
                        target=resolve(locator,roots) if type(locator) is str and locator.startswith('@') else Path(locator)
                        if target in contents and 'sha256' in v:
                            v.update(sha256=digest(contents[target]),size=len(contents[target]),mode=modes[target])
                        for x in v.values():pin(x)
                    elif isinstance(v,list):
                        for x in v:pin(x)
                pin(obj);contents[p]=encode(obj) if row['repin_json'] else base
            elif p.parent==roots['PACKAGE']/'backends/nvidia/runtime':
                s=base.decode()
                for old,target in identities.items():
                    s=s.replace(old,digest(contents[target]))
                    s=s.replace(old[:16],digest(contents[target])[:16])
                # Existing push-size guard follows exact reserialized source table.
                for old,target in identities.items():
                    if target.name in ('push_extra_fields.json','push_fields.json'):
                        n=records[target]['baseline_bytes']
                        s=s.replace(repr(digest(contents[target]))+', '+str(n)+',',
                                    repr(digest(contents[target]))+', '+str(len(contents[target]))+',')
                contents[p]=s.encode()
        if contents==before:break
    else:raise ValueError('PIN_CYCLE_OR_NONCONVERGENCE')
    _write_installation(contents, modes, roots, authority)
    manifest=roots['PACKAGE']/'backends/nvidia/data/runtime_inputs.json'
    return {'schema':'native-layout-installed.v1','roots':{k:str(v) for k,v in roots.items()},
            'manifest':str(manifest),'manifest_sha256':digest(contents[manifest]),
            'template_lock_sha256':expected_lock,'files':[
                {'path':str(p),'sha256':digest(b),'bytes':len(b),'mode':modes[p]}
                for p,b in sorted(contents.items())],
            'gpu':'NOT_RUN','status':'PRIVATE_NOT_RELEASE_CLEARED'}
