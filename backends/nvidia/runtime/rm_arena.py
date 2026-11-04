"""Scope-A replacement: RM/UVM allocation and mapping of the control arena (REQUIREMENTS_A.md, DELTA-A-REQ-01;
DELTA-A-CODE-02 after Codex review A-CODE-F1..F4).

Written from the allowed headers (via abi/abi.json produced by abi/abi_probe.c), REQUIREMENTS_A.md and
SOURCE_LEDGER.md. No tinygrad, alloc_one.py, submit_cpu.py or rm_resources.py fragment was used as a template.
Not clean-room: the author has seen those files before; the discipline is that every value here has a tag in
REQUIREMENTS_A (DOC / PROFILE / UNKNOWN) and that the three A3.2 unknowns (u1 fd meaning, u2 materialization step,
u3 MAP_FIXED on the raw path) are delegated to the injected Backend, which must state its reading, never filled in
here from the inherited helper.

Lifecycle (A7, A-CODE-F1): an Arena is OPEN while steps may run; the first Stop or backend exception inside an effect
moves it to FAILED, where exactly one teardown(True) is still permitted if every acquired owner has a certain identity;
after a successful teardown it is TORN; after a teardown failure or an uncertain owner it is TERMINAL. In FAILED,
TORN and TERMINAL every further effect is refused before any backend call (zero additional effects). Nothing is
retried. Control-flow interruptions (including KeyboardInterrupt and SystemExit) retain the original exception,
latch TERMINAL and make new acquisitions uncertain. Teardown is terminal-latched before undo begins and reaches
TORN only after every undo and ledger update succeeds; interrupted undo is retained UNCERTAIN.

Ownership (A-CODE-F2, F2-R): every acquiring effect records an Owner before the backend call (PENDING, with the
requested identity); after the call it is CERTAIN (with the undo bound to the validated identity) or UNCERTAIN.
Failure classification (F2-R): the only NOT_ACQUIRED outcome is a `Rejected` exception raised by the backend, which
certifies that it refused the request before any effect; every other unsuccessful outcome (nonzero rc, driver status
!= NV_OK, any other exception, a success with a different identity) is an effect of unknown extent and leaves the
owner UNCERTAIN. The integer rc and the status field carry no atomicity guarantee in the declarations, so this module
never infers "no effect" from them. UNCERTAIN owners are never freed by a guess: teardown stops at them and retains
everything below them.

This module performs no I/O by itself. The live Linux backend is a separate deliverable of the same author
(REQUIREMENTS_BACKEND.md; Codex reviews it and owns VM/GPU execution); CPU tests use a scripted fake
(test_rm_arena.py).
"""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path

ABI_PATH = Path(__file__).resolve().parent.parent / 'abi/abi.json'
ABI_SHA = '0fa893036bc32828bd96bb29659ea57caecd879a67160686eff53de610b21a07'
PAGE = 4096
U32 = 0xffffffff
U64 = 0xffffffffffffffff
S32 = (-(1 << 31), (1 << 31) - 1)
MIB = 1 << 20


class Stop(Exception):
    """First error stops the sequence (A7). `reason` is a stable token; `details` carry the observed values."""

    def __init__(self, reason, **details):
        super().__init__(reason if not details else '%s %s' % (reason, details))
        self.reason = reason
        self.details = details


class Rejected(Exception):
    """Raised by a Backend *before* it performs any effect, certifying that the request was refused with no kernel or
    mapping side effect (e.g. closed descriptor, argument it will not pass on). It is the only failure the module
    classifies as NOT_ACQUIRED. A backend must not raise it after issuing the ioctl/mmap."""


def require(ok, reason, **details):
    if not ok:
        raise Stop(reason, **details)


def is_int(x):
    return type(x) is int


# ----------------------------------------------------------------------------- ABI from the C probe

class StructCodec:
    """Serializes one header structure using the probed offsets. Unspecified fields are zero. Driver-written
    ([OUT]) fields are read back with unpack(); the caller decides which ones it validates."""
    TAG_RANGE = {'u8': (0, 0xff), 'u16': (0, 0xffff), 'u32': (0, U32), 'u64': (0, U64), 'ptr': (0, U64), 's32': S32}
    MEASURED = {'u8': 0, 'u16': 0, 'u32': 0, 'u64': 0, 's32': 1, 'ptr': 2}
    ARRAY_ELEM = {'array_u32': 4, 'array_u64': 8}   # fixed arrays of unsigned integers (DELTA-A-ABI-02)

    def __init__(self, abi, name, spec):
        self.abi, self.name, self.size, self.align = abi, name, spec['size'], spec['align']
        self.fields = {}
        for k, v in spec['fields'].items():
            off, size, tag, measured, align = v
            expected = self.MEASURED.get(tag, -1)
            require(measured == expected and off % align == 0, 'ABI_FIELD_SHAPE', struct=name, field=k, tag=tag,
                    measured=measured, offset=off, align=align)
            self.fields[k] = (off, size, tag)

    def pack(self, values):
        require(type(values) is dict, 'ABI_VALUES_TYPE', struct=self.name)
        unknown = set(values) - set(self.fields)
        require(not unknown, 'ABI_UNKNOWN_FIELD', struct=self.name, fields=sorted(unknown))
        out = bytearray(self.size)
        for name, (off, size, tag) in self.fields.items():
            if name not in values:
                continue
            v = values[name]
            if tag in self.TAG_RANGE:
                lo, hi = self.TAG_RANGE[tag]
                require(is_int(v) and lo <= v <= hi, 'ABI_RANGE', struct=self.name, field=name, value=v)
                out[off:off + size] = v.to_bytes(size, 'little', signed=(tag == 's32'))
            elif tag == 'bytes':
                require(type(v) is bytes and len(v) == size, 'ABI_BYTES_LENGTH', struct=self.name, field=name)
                out[off:off + size] = v
            elif tag in self.ARRAY_ELEM:
                w = self.ARRAY_ELEM[tag]
                require(type(v) in (list, tuple) and len(v) * w <= size and all(is_int(x) and 0 <= x < (1 << (8 * w)) for x in v),
                        'ABI_ARRAY_VALUES', struct=self.name, field=name)
                for i, x in enumerate(v):   # unspecified trailing elements stay zero
                    out[off + i * w:off + (i + 1) * w] = x.to_bytes(w, 'little')
            elif tag.startswith('struct:'):
                inner = self.abi.struct(tag.split(':', 1)[1])
                b = inner.pack(v) if type(v) is dict else v
                require(type(b) in (bytes, bytearray) and len(b) == size, 'ABI_INNER_LENGTH', struct=self.name, field=name)
                out[off:off + size] = b
            elif tag.startswith('array:'):
                inner = self.abi.struct(tag.split(':', 1)[1])
                require(type(v) is list and len(v) * inner.size <= size, 'ABI_ARRAY_LENGTH', struct=self.name,
                        field=name, count=len(v))
                for i, item in enumerate(v):
                    out[off + i * inner.size:off + (i + 1) * inner.size] = inner.pack(item)
            else:
                raise Stop('ABI_TAG', struct=self.name, field=name, tag=tag)
        return out

    def unpack(self, data):
        require(type(data) in (bytes, bytearray) and len(data) == self.size, 'ABI_UNPACK_LENGTH', struct=self.name,
                got=len(data) if type(data) in (bytes, bytearray) else None)
        out = {}
        for name, (off, size, tag) in self.fields.items():
            raw = bytes(data[off:off + size])
            if tag in self.TAG_RANGE:
                out[name] = int.from_bytes(raw, 'little', signed=(tag == 's32'))
            elif tag in self.ARRAY_ELEM:
                w = self.ARRAY_ELEM[tag]
                out[name] = tuple(int.from_bytes(raw[i:i + w], 'little') for i in range(0, size, w))
            else:
                out[name] = raw
        return out


class Abi:
    def __init__(self, path=ABI_PATH, expected_sha=ABI_SHA):
        raw = Path(path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        require(digest == expected_sha, 'ABI_PIN', got=digest)
        doc = json.loads(raw)
        self._structs = doc['structs']
        self.constants = doc['constants']
        self.probe = doc['probe']
        require(len(self.probe.get('header_closure', [])) > 0, 'ABI_CLOSURE_MISSING')
        for name in self._structs:   # every field shape is checked once at load time (tag vs measured, alignment)
            self.struct(name)

    def const(self, name):
        require(name in self.constants, 'ABI_CONST', name=name)
        return self.constants[name]

    def struct(self, name):
        require(name in self._structs, 'ABI_STRUCT', name=name)
        return StructCodec(self, name, self._structs[name])


def field_value(word, shift, mask):
    return (word >> shift) & mask


def field_set(value, shift, mask):
    require(is_int(value) and 0 <= value <= mask, 'FIELD_VALUE', value=value, mask=mask)
    return value << shift


# ----------------------------------------------------------------------------- pure checks (A1.4, A4.2, A5.4)

def contains(base, length, va_base, va_size):
    """A1.4: [base, base+length) inside [va_base, va_size) with va_size the exclusive endpoint; unbounded ints,
    the three checks in the documented order."""
    for v in (base, length, va_base, va_size):
        require(is_int(v) and v >= 0, 'CONTAIN_ARGS')
    require(length > 0, 'CONTAIN_EMPTY')
    require(base >= va_base, 'CONTAIN_BELOW_BASE', base=base, va_base=va_base)
    require(base <= va_size, 'CONTAIN_ABOVE_END', base=base, va_size=va_size)
    require(length <= va_size - base, 'CONTAIN_LENGTH', base=base, length=length, va_size=va_size)


ACCESS_KINDS = frozenset({'read', 'write', 'atomic'})
# Granted sets per documented UvmGpuMappingType value (nv_uvm_user_types.h:56-72). Default (0) has no documented
# granted set and is refused by the gate (Codex, DELTA-A-REQ-01 carry-forward 2).
GRANTED = {1: frozenset({'read', 'write', 'atomic'}), 2: frozenset({'read', 'write'}), 3: frozenset({'read'})}

# FFX sort workload consumer matrix (REQUIREMENTS_A A4.2); spans reached through the UVM mapping only.
FFX_CONSUMERS = {'code': {'read'}, 'cb': {'read'}, 'qmd': {'read'}, 'push': {'read'}, 'ring': {'read'},
                 'semaphore': {'write'}, 'bo': {'read', 'write'}}


def required_access(consumers):
    require(type(consumers) is dict and consumers, 'CONSUMERS_EMPTY')
    out = set()
    for span, kinds in consumers.items():
        require(type(span) is str and type(kinds) in (set, frozenset) and kinds and kinds <= ACCESS_KINDS,
                'CONSUMER_KINDS', span=span)
        out |= kinds
    return frozenset(out)


def permission_gate(required, mapping_type):
    require(type(required) is frozenset and required and required <= ACCESS_KINDS, 'PERMISSION_REQUIRED_SET')
    require(is_int(mapping_type) and 0 <= mapping_type <= 3, 'PERMISSION_VALUE', value=mapping_type)
    require(mapping_type != 0, 'PERMISSION_DEFAULT_UNPROVEN')
    granted = GRANTED[mapping_type]
    require(required <= granted, 'PERMISSION_INSUFFICIENT', required=sorted(required), granted=sorted(granted))
    return granted


def channel_region_length(records, total_buffer_size=None, budget=256 * MIB, factor=2, page=PAGE):
    """A5.4 aggregate. records: list of (alignment, size) from GET_CTX_BUFFER_INFO. Returns (length, max_alignment);
    (0, 0) for the documented zero-buffer case, which is consistent only with an absent or zero total (A-CODE-F4).
    All arithmetic in unbounded ints, result checked against u64."""
    require(type(records) in (list, tuple), 'REGION_RECORDS_TYPE')
    require(len(records) <= 64, 'REGION_COUNT', count=len(records))
    require(is_int(budget) and budget > 0 and is_int(factor) and factor >= 1 and is_int(page) and page > 0,
            'REGION_ARGS')
    if total_buffer_size is not None:
        require(is_int(total_buffer_size) and 0 <= total_buffer_size <= U64, 'REGION_TOTAL_TYPE',
                total=total_buffer_size)
    if not records:
        require(not total_buffer_size, 'REGION_TOTAL_WITHOUT_RECORDS', total=total_buffer_size)
        return 0, 0
    total, max_align = 0, 1
    for i, rec in enumerate(records):
        require(type(rec) is tuple and len(rec) == 2 and all(is_int(x) for x in rec), 'REGION_RECORD', index=i)
        alignment, size = rec
        require(size > 0, 'REGION_SIZE_ZERO', index=i)
        require(alignment > 0 and alignment & (alignment - 1) == 0, 'REGION_ALIGNMENT', index=i, alignment=alignment)
        total += -(-size // alignment) * alignment
        max_align = max(max_align, alignment)
    length = -(-(total * factor) // page) * page
    require(length <= budget, 'REGION_BUDGET', length=length, budget=budget)
    require(length <= U64 and max_align <= U64, 'REGION_U64')
    if total_buffer_size is not None:
        require(length >= total_buffer_size, 'REGION_BELOW_TOTAL', length=length, total=total_buffer_size)
    return length, max_align


# ----------------------------------------------------------------------------- backend protocol

class Backend:
    """Injected kernel boundary. The live implementation is REQUIREMENTS_BACKEND.md / linux_backend.py (same author;
    Codex reviews and executes). It must document its readings of the A3.2 unknowns u1-u3; this module validates
    results, it does not choose them.
    node: 'ctl' (RM control node), 'dev' (device node), 'uvm'.
    Contract on identities (A-CODE-F2): reserve()/materialize() must act at exactly the requested base; if they
    return another address the module records an UNCERTAIN owner and never guesses which range to release."""

    def ioctl(self, node, request, data, indirect=None):
        """Perform the ioctl with `data` (bytearray, mutated by the driver). `indirect` = (pointer_offset, aux)
        when `data` carries a pointer at pointer_offset that must address the `aux` buffer. Returns rc (0 = ok).
        Failure contract (F2-R): raise `Rejected` only for a refusal made before the call reaches the kernel; a
        nonzero rc, a driver status != NV_OK or any other exception is treated by the module as an effect of unknown
        extent (owner UNCERTAIN), never as proof of no acquisition."""
        raise NotImplementedError

    def device_fd(self):
        """u1: the file descriptor the NVOS33 wrapper expects (the backend states which node it opened)."""
        raise NotImplementedError

    def reserve(self, base, length):
        """A3.2: anonymous PROT_NONE, MAP_NORESERVE reservation at exactly `base`; returns the address.
        `Rejected` before any mmap is NOT_ACQUIRED; any other exception leaves the reservation UNCERTAIN."""
        raise NotImplementedError

    def materialize(self, base, length):
        """u2: the step that makes the RM CPU mapping visible at `base` after NVOS33; returns the address."""
        raise NotImplementedError

    def release(self, base, length):
        """munmap of a reservation or mapping created by reserve()/materialize()."""
        raise NotImplementedError


# ----------------------------------------------------------------------------- request

@dataclass(frozen=True)
class ArenaRequest:
    h_client: int
    h_device: int
    h_subdevice: int
    gpu_uuid: bytes
    rm_ctrl_fd: int
    memory_class: int          # A2.0: explicit, 0x3E or 0x40 (UNKNOWN which RM requires; comparison C2)
    size: int                  # multiple of PAGE (A2.2)
    base: int                  # CPU == GPU VA (A3.1), PAGE aligned, inside the VA space (A1.4)
    h_vas: int                 # caller-chosen nonzero handles (PROFILE); RM must return the same handle
    h_memory: int
    mapping_type: int = 1      # A4.2 PROFILE ReadWriteAtomic; gate refuses Default
    consumers: dict = field(default_factory=lambda: dict(FFX_CONSUMERS))
    page_faulting: bool = False   # A1.3 UNKNOWN; baseline off
    vidmem_hints: bool = False    # A2.3 UNKNOWN; baseline omitted
    format: int = 0               # A2.7: 0 = read back (arm a); nonzero = explicit request (arm b, allowed kind only)
    budget: int = 64 * MIB        # PROFILE cap on the returned size (carry-forward 1)
    layout_bytes: int = 0         # bytes the caller's layout needs; must fit the returned size
    uvm_init_flags: int = 0


def validate_request(req, abi):
    classes = {abi.const('NV01_MEMORY_SYSTEM'), abi.const('NV01_MEMORY_LOCAL_USER')}
    for name in ('h_client', 'h_device', 'h_subdevice', 'h_vas', 'h_memory'):
        v = getattr(req, name)
        require(is_int(v) and 0 < v <= U32, 'REQUEST_HANDLE', field=name)
    require(len({req.h_client, req.h_device, req.h_subdevice, req.h_vas, req.h_memory}) == 5, 'REQUEST_HANDLE_DUP')
    require(type(req.gpu_uuid) is bytes and len(req.gpu_uuid) == abi.const('NV_UUID_LEN'), 'REQUEST_UUID')
    require(is_int(req.rm_ctrl_fd) and 0 <= req.rm_ctrl_fd <= S32[1], 'REQUEST_FD')
    require(req.memory_class in classes, 'REQUEST_CLASS', value=req.memory_class)
    require(is_int(req.size) and req.size > 0 and req.size % PAGE == 0 and req.size <= U64, 'REQUEST_SIZE')
    require(is_int(req.base) and req.base >= 0 and req.base % PAGE == 0 and req.base <= U64, 'REQUEST_BASE')
    require(is_int(req.budget) and req.size <= req.budget <= U64, 'REQUEST_BUDGET')
    require(is_int(req.layout_bytes) and 0 <= req.layout_bytes <= req.size, 'REQUEST_LAYOUT')
    # A2.7 / A-CODE-F3: an explicit format may only name the allowed generic uncompressed kind.
    require(is_int(req.format) and req.format in (0, abi.const('NV_MMU_PTE_KIND_GENERIC_MEMORY')), 'REQUEST_FORMAT_KIND',
            value=req.format)
    require(type(req.page_faulting) is bool and type(req.vidmem_hints) is bool, 'REQUEST_BOOLS')
    require(is_int(req.uvm_init_flags) and 0 <= req.uvm_init_flags <= U64, 'REQUEST_UVM_FLAGS')
    permission_gate(required_access(req.consumers), req.mapping_type)


# ----------------------------------------------------------------------------- ownership and lifecycle

OPEN, FAILED, TORN, TERMINAL = 'OPEN', 'FAILED', 'TORN', 'TERMINAL'
PENDING, CERTAIN, UNCERTAIN = 'PENDING', 'CERTAIN', 'UNCERTAIN'


@dataclass
class Owner:
    label: str
    requested: object
    returned: object = None
    state: str = PENDING
    undo: object = None          # callable bound to the validated identity; None unless CERTAIN
    note: str = ''

    def summary(self):
        return (self.label, self.state, self.requested, self.returned)


class Arena:
    """Builds the arena step by step (A1-A6), records every driver-returned value in `observed`, keeps an ordered
    owner list for teardown (A7). See the module docstring for the lifecycle and ownership rules."""

    def __init__(self, req, backend, abi=None):
        self.abi = abi or Abi()
        validate_request(req, self.abi)
        self.req, self.backend = req, backend
        self.owners = []          # Owner records in creation order
        self.observed = {}
        self.phase = OPEN
        self.done = set()         # step labels already performed (duplicate acquisition guard)
        self.failure = None       # (reason, details) of the Stop that left OPEN
        self.c = self.abi.const

    # --- lifecycle boundary: every effect method starts here, before any backend call
    def _effect(self, label, once=True):
        require(self.phase == OPEN, 'LIFECYCLE_CLOSED', phase=self.phase, step=label, failure=self.failure)
        if once:
            require(label not in self.done, 'DUPLICATE_STEP', step=label)
            self.done.add(label)

    def _run(self, label, fn, once=True):
        self._effect(label, once)
        owner_start = len(self.owners)
        try:
            return fn()
        except Stop as e:
            self._fail(e.reason, e.details)
            raise
        except Rejected as e:        # certified pre-effect refusal outside an acquisition: nothing was acquired
            self._fail('BACKEND_REJECTED', {'step': label, 'message': str(e)})
            raise Stop('BACKEND_REJECTED', step=label, message=str(e)) from e
        except Exception as e:       # backend exceptions (OSError, ...) are failures of uncertain effect
            self._fail('BACKEND_EXCEPTION', {'step': label, 'type': type(e).__name__, 'error': str(e)})
            raise Stop('BACKEND_EXCEPTION', step=label, type=type(e).__name__, error=str(e)) from e
        except BaseException as e:   # retain control-flow interruption without converting/swallowing it
            self._fail('BACKEND_INTERRUPTED', {'step': label, 'type': type(e).__name__})
            self.phase = TERMINAL
            # A cancellation can arrive after _certain but before the whole step returns.
            for owner in self.owners[owner_start:]:
                owner.state, owner.note = UNCERTAIN, 'effect interrupted: ' + type(e).__name__
            raise

    def _fail(self, reason, details):
        if self.phase == OPEN:
            self.failure = (reason, dict(details))
            self.phase = FAILED
        for o in self.owners:
            if o.state == PENDING:   # the effect did not complete: its outcome is unknown
                o.state, o.note = UNCERTAIN, 'effect interrupted: ' + reason

    def retained(self):
        return [o.summary() for o in self.owners]

    # --- ownership primitives
    def _acquire(self, label, requested):
        o = Owner(label, requested)
        self.owners.append(o)
        return o

    def _certain(self, owner, returned, undo):
        owner.returned, owner.state, owner.undo = returned, CERTAIN, undo

    def _uncertain(self, owner, returned, note):
        owner.returned, owner.state, owner.note = returned, UNCERTAIN, note
        raise Stop(note.split(':')[0], requested=owner.requested, returned=returned, owner=owner.label)

    def _not_acquired(self, owner, exc):
        """NOT_ACQUIRED (F2-R): only on a `Rejected` raised by the backend before any effect. The owner record is
        dropped and the step stops with BACKEND_REJECTED; parents stay CERTAIN and one clean teardown remains allowed."""
        self.owners.remove(owner)
        raise Stop('BACKEND_REJECTED', owner=owner.label, requested=owner.requested, message=str(exc)) from exc

    def _unknown(self, owner, reason, **details):
        """Unsuccessful outcome of unknown extent (nonzero rc, driver status != NV_OK): the owner stays UNCERTAIN so
        teardown stops at it; no inference of 'no effect' from an integer (F2-R)."""
        owner.state, owner.note = UNCERTAIN, '%s: unsuccessful outcome of unknown extent' % reason
        raise Stop(reason, owner=owner.label, requested=owner.requested, classification='UNKNOWN_EFFECT', **details)

    # --- ioctl primitives
    def _ioctl(self, request_name, struct_name, values, node='ctl', indirect=None):
        codec = self.abi.struct(struct_name)
        data = codec.pack(values)
        rc = self.backend.ioctl(node, self.c(request_name), data, indirect)
        return rc, codec.unpack(data)

    def _rm(self, request_name, struct_name, values, node='ctl', indirect=None):
        rc, out = self._ioctl(request_name, struct_name, values, node, indirect)
        require(rc == 0, 'IOCTL_RC', request=request_name, rc=rc)
        return out

    def _status_ok(self, out, key):
        return out[key] == self.c('NV_OK')

    def _status(self, out, request_name, key):
        require(self._status_ok(out, key), 'RM_STATUS', request=request_name, status=out[key])

    def _rm_alloc(self, owner, h_parent, h_new, h_class, params_struct, params):
        """RM alloc with ownership: PENDING before the call; `Rejected` -> NOT_ACQUIRED; nonzero rc or status != OK ->
        UNCERTAIN (unknown extent); handle mismatch on success -> UNCERTAIN (which object RM bound is unknown);
        otherwise CERTAIN with undo = free(h_new)."""
        pcodec = self.abi.struct(params_struct)
        aux = pcodec.pack(params)
        nvos21 = self.abi.struct('NVOS21_PARAMETERS')
        ptr_off = nvos21.fields['pAllocParms'][0]
        try:
            rc, out = self._ioctl('IOCTL_RM_ALLOC_NVOS21', 'NVOS21_PARAMETERS',
                                  {'hRoot': self.req.h_client, 'hObjectParent': h_parent, 'hObjectNew': h_new,
                                   'hClass': h_class, 'paramsSize': pcodec.size}, indirect=(ptr_off, aux))
        except Rejected as e:
            self._not_acquired(owner, e)
        if rc != 0:
            self._unknown(owner, 'IOCTL_RC', request='RM_ALLOC', rc=rc)
        if not self._status_ok(out, 'status'):
            self._unknown(owner, 'RM_STATUS', request='RM_ALLOC', status=out['status'])
        if out['hObjectNew'] != h_new:
            self._uncertain(owner, out['hObjectNew'], 'RM_ALLOC_HANDLE: success reported with another handle')
        self._certain(owner, h_new, lambda: self._rm_free(h_parent, h_new))
        return pcodec.unpack(aux)

    def _rm_free(self, h_parent, h_object):
        out = self._rm('IOCTL_RM_FREE', 'NVOS00_PARAMETERS',
                       {'hRoot': self.req.h_client, 'hObjectParent': h_parent, 'hObjectOld': h_object})
        self._status(out, 'RM_FREE', 'status')

    def _uvm(self, request_name, struct_name, values):
        out = self._rm(request_name, struct_name, values, node='uvm')
        self._status(out, request_name, 'rmStatus')
        return out

    def _uvm_acquire(self, label, requested, request_name, struct_name, values, undo, identity=None):
        """UVM acquiring call: PENDING -> NOT_ACQUIRED only on `Rejected`; nonzero rc / status != OK -> UNCERTAIN;
        `identity` optionally returns (ok, returned) from the output to detect a changed identity (e.g. UUID) ->
        UNCERTAIN; otherwise CERTAIN."""
        owner = self._acquire(label, requested)
        try:
            rc, out = self._ioctl(request_name, struct_name, values, node='uvm')
        except Rejected as e:
            self._not_acquired(owner, e)
        if rc != 0:
            self._unknown(owner, 'IOCTL_RC', request=request_name, rc=rc)
        if not self._status_ok(out, 'rmStatus'):
            self._unknown(owner, 'RM_STATUS', request=request_name, status=out['rmStatus'])
        if identity is not None:
            ok, returned = identity(out)
            if not ok:
                self._uncertain(owner, returned, 'UVM_IDENTITY_CHANGED: success reported with another identity')
        self._certain(owner, requested, undo)
        return out

    # --- steps (each wrapped by _run through the public methods below)
    def _uvm_initialize(self):
        self._uvm('UVM_INITIALIZE', 'UVM_INITIALIZE_PARAMS', {'flags': self.req.uvm_init_flags})
        self.observed['uvm_initialized'] = True

    def _uvm_register_gpu(self):
        r = self.req
        out = self._uvm_acquire('uvm_gpu', r.gpu_uuid, 'UVM_REGISTER_GPU', 'UVM_REGISTER_GPU_PARAMS',
                                {'gpu_uuid': r.gpu_uuid, 'rmCtrlFd': r.rm_ctrl_fd, 'hClient': r.h_client, 'hSmcPartRef': 0},
                                undo=lambda: self._uvm('UVM_UNREGISTER_GPU', 'UVM_UNREGISTER_GPU_PARAMS', {'gpu_uuid': r.gpu_uuid}),
                                identity=lambda out: (out['gpu_uuid'] == r.gpu_uuid, out['gpu_uuid']))
        self.observed['numa'] = (out['numaEnabled'], out['numaNodeId'])

    def _create_vaspace(self):
        """A1.1-A1.4: FERMI_VASPACE_A with vaBase=0/vaSize=0, both read back; IS_EXTERNALLY_OWNED set."""
        r = self.req
        flags = self.c('NV_VASPACE_ALLOCATION_FLAGS_IS_EXTERNALLY_OWNED')
        if r.page_faulting:
            flags |= self.c('NV_VASPACE_ALLOCATION_FLAGS_ENABLE_PAGE_FAULTING')
        owner = self._acquire('vaspace', r.h_vas)
        out = self._rm_alloc(owner, r.h_device, r.h_vas, self.c('FERMI_VASPACE_A'), 'NV_VASPACE_ALLOCATION_PARAMETERS',
                             {'index': self.c('NV_VASPACE_ALLOCATION_INDEX_GPU_NEW'), 'flags': flags,
                              'vaSize': 0, 'vaBase': 0})
        va_base, va_size = out['vaBase'], out['vaSize']
        require(va_size > va_base, 'VASPACE_EMPTY', vaBase=va_base, vaSize=va_size)
        require(va_base % PAGE == 0 and va_size % PAGE == 0, 'VASPACE_UNALIGNED', vaBase=va_base, vaSize=va_size)
        self.observed['va_base'], self.observed['va_size'] = va_base, va_size
        self.observed['va_internal'] = (out['vaStartInternal'], out['vaLimitInternal'], out['bigPageSize'])

    def _uvm_register_vaspace(self):
        r = self.req
        self._uvm_acquire('uvm_vaspace', r.h_vas, 'UVM_REGISTER_GPU_VASPACE', 'UVM_REGISTER_GPU_VASPACE_PARAMS',
                          {'gpuUuid': r.gpu_uuid, 'rmCtrlFd': r.rm_ctrl_fd, 'hClient': r.h_client, 'hVaSpace': r.h_vas},
                          undo=lambda: self._uvm('UVM_UNREGISTER_GPU_VASPACE', 'UVM_UNREGISTER_GPU_VASPACE_PARAMS',
                                                 {'gpuUuid': r.gpu_uuid}))

    def memory_params(self):
        """A2.1-A2.9 request image. Only request fields are set; limit/offset/address stay 0 ([OUT])."""
        r, c = self.req, self.c
        flags = c('NVOS32_ALLOC_FLAGS_MAP_NOT_REQUIRED') | c('NVOS32_ALLOC_FLAGS_ALIGNMENT_FORCE')
        if r.vidmem_hints:
            flags |= c('NVOS32_ALLOC_FLAGS_IGNORE_BANK_PLACEMENT') | c('NVOS32_ALLOC_FLAGS_PERSISTENT_VIDMEM')
        attr = (field_set(c('NVOS32_ATTR_LOCATION_PCI'), c('NVOS32_ATTR_LOCATION_SHIFT'), c('NVOS32_ATTR_LOCATION_MASK'))
                | field_set(c('NVOS32_ATTR_PHYSICALITY_DEFAULT'), c('NVOS32_ATTR_PHYSICALITY_SHIFT'),
                            c('NVOS32_ATTR_PHYSICALITY_MASK')))
        attr2 = (field_set(c('NVOS32_ATTR2_GPU_CACHEABLE_DEFAULT'), c('NVOS32_ATTR2_GPU_CACHEABLE_SHIFT'),
                           c('NVOS32_ATTR2_GPU_CACHEABLE_MASK'))
                 | field_set(c('NVOS32_ATTR2_ZBC_DEFAULT'), c('NVOS32_ATTR2_ZBC_SHIFT'), c('NVOS32_ATTR2_ZBC_MASK')))
        return {'owner': r.h_client, 'type': c('NVOS32_TYPE_IMAGE'), 'flags': flags, 'attr': attr, 'attr2': attr2,
                'format': r.format, 'size': r.size, 'alignment': PAGE}

    def _allocate(self):
        """A2: allocate the arena; validate returned size/location/kind; record physicality/limit observations."""
        r, c = self.req, self.c
        params = self.memory_params()
        for name in ('limit', 'offset', 'address'):
            require(name not in params, 'ALLOC_OUT_FIELD_SET', field=name)
        owner = self._acquire('memory', r.h_memory)
        out = self._rm_alloc(owner, r.h_device, r.h_memory, r.memory_class, 'NV_MEMORY_ALLOCATION_PARAMS', params)
        size = out['size']
        require(size >= r.size, 'ALLOC_SIZE_SHORT', requested=r.size, returned=size)
        require(size % PAGE == 0, 'ALLOC_SIZE_UNALIGNED', returned=size)
        require(size <= r.budget, 'ALLOC_SIZE_BUDGET', returned=size, budget=r.budget)
        require(r.layout_bytes <= size, 'ALLOC_LAYOUT', layout=r.layout_bytes, returned=size)
        location = field_value(out['attr'], c('NVOS32_ATTR_LOCATION_SHIFT'), c('NVOS32_ATTR_LOCATION_MASK'))
        require(location == c('NVOS32_ATTR_LOCATION_PCI'), 'ALLOC_LOCATION', location=location)
        # A2.7 / A-CODE-F3: both arms accept only the allowed generic uncompressed kind (tu102/dev_mmu.h; L-A19).
        allowed = c('NV_MMU_PTE_KIND_GENERIC_MEMORY')
        require(out['format'] == allowed, 'ALLOC_FORMAT_KIND', requested=r.format, returned=out['format'], allowed=allowed)
        self.observed['arena_size'] = size
        self.observed['physicality'] = field_value(out['attr'], c('NVOS32_ATTR_PHYSICALITY_SHIFT'),
                                                   c('NVOS32_ATTR_PHYSICALITY_MASK'))
        self.observed['format'] = out['format']
        self.observed['attr'], self.observed['attr2'] = out['attr'], out['attr2']
        self.observed['limit_observation'] = out['limit']   # convention UNKNOWN; never a gate (A2.9)

    def _reserve(self, label, base, length):
        """Reservation with ownership: a different returned address is UNCERTAIN (no guessed release)."""
        owner = self._acquire(label, (base, length))
        try:
            addr = self.backend.reserve(base, length)
        except Rejected as e:
            self._not_acquired(owner, e)
        if addr != base:
            self._uncertain(owner, (addr, length), 'RESERVE_ADDRESS: reservation reported at another address')
        self._certain(owner, (base, length), lambda: self.backend.release(base, length))

    def _place(self):
        """Carry-forward 1: the whole returned size is placed and reserved; containment checked on that size."""
        r = self.req
        size = self.observed['arena_size']
        contains(r.base, size, self.observed['va_base'], self.observed['va_size'])
        self._reserve('reservation', r.base, size)

    def _map_cpu(self):
        """A3.2/A3.3: NVOS33 with MAP_FIXED at the reserved base, through the Linux fd wrapper; returned address
        and length validated. The fd (u1) and the materialization step (u2) come from the backend."""
        r, c = self.req, self.c
        size = self.observed['arena_size']
        fd = self.backend.device_fd()
        require(is_int(fd) and 0 <= fd <= S32[1], 'DEVICE_FD', fd=fd)
        flags = (field_set(c('NVOS33_FLAGS_MAP_FIXED_ENABLE'), c('NVOS33_FLAGS_MAP_FIXED_SHIFT'), 1)
                 | field_set(c('NVOS33_FLAGS_ACCESS_READ_WRITE'), c('NVOS33_FLAGS_ACCESS_SHIFT'), 3))
        inner = {'hClient': r.h_client, 'hDevice': r.h_device, 'hMemory': r.h_memory, 'offset': 0, 'length': size,
                 'pLinearAddress': r.base, 'flags': flags}
        owner = self._acquire('rm_cpu_map', (r.base, size))
        try:
            rc, out = self._ioctl('IOCTL_RM_MAP_MEMORY_FD', 'nv_ioctl_nvos33_parameters_with_fd', {'params': inner, 'fd': fd})
        except Rejected as e:
            self._not_acquired(owner, e)
        params = self.abi.struct('NVOS33_PARAMETERS').unpack(out['params'])
        if rc != 0:
            self._unknown(owner, 'IOCTL_RC', request='RM_MAP_MEMORY', rc=rc)
        if not self._status_ok(params, 'status'):
            self._unknown(owner, 'RM_STATUS', request='RM_MAP_MEMORY', status=params['status'])
        returned = (params['pLinearAddress'], params['length'])
        if returned != (r.base, size):
            self._uncertain(owner, returned, 'MAP_IDENTITY: RM mapping reported at another address or length')
        self._certain(owner, (r.base, size), lambda: self._unmap_cpu(r.base))
        mat = self._acquire('cpu_materialized', (r.base, size))
        try:
            addr = self.backend.materialize(r.base, size)
        except Rejected as e:
            self._not_acquired(mat, e)
        if addr != r.base:
            self._uncertain(mat, (addr, size), 'MATERIALIZE_ADDRESS: backend mapping reported at another address')
        self._certain(mat, (r.base, size), lambda: None)   # released together with the reservation range (one munmap)
        self.observed['cpu_base'] = r.base

    def _unmap_cpu(self, address):
        r = self.req
        out = self._rm('IOCTL_RM_UNMAP_MEMORY', 'NVOS34_PARAMETERS',
                       {'hClient': r.h_client, 'hDevice': r.h_device, 'hMemory': r.h_memory,
                        'pLinearAddress': address, 'flags': 0})
        self._status(out, 'RM_UNMAP_MEMORY', 'status')

    def _external_range(self):
        r = self.req
        size = self.observed['arena_size']
        self._uvm_acquire('uvm_external_range', (r.base, size), 'UVM_CREATE_EXTERNAL_RANGE',
                          'UVM_CREATE_EXTERNAL_RANGE_PARAMS', {'base': r.base, 'length': size},
                          undo=lambda: self._uvm('UVM_FREE', 'UVM_FREE_PARAMS', {'base': r.base}))

    def _map_gpu(self):
        """A4.1/A4.2: one GPU, permission from the gate, caching/format/compression Default (A2.5)."""
        r, c = self.req, self.c
        granted = permission_gate(required_access(r.consumers), r.mapping_type)
        size = self.observed['arena_size']
        attrs = {'gpuUuid': r.gpu_uuid, 'gpuMappingType': r.mapping_type,
                 'gpuCachingType': c('UvmGpuCachingTypeDefault'), 'gpuFormatType': c('UvmGpuFormatTypeDefault'),
                 'gpuElementBits': c('UvmGpuFormatElementBitsDefault'),
                 'gpuCompressionType': c('UvmGpuCompressionTypeDefault')}
        # The mapping lives and dies with the external range (UVM_FREE on the range base): no separate undo, but the
        # acquisition is recorded so a failure here leaves a visible record.
        self._uvm_acquire('uvm_gpu_map', (r.base, size), 'UVM_MAP_EXTERNAL_ALLOCATION',
                          'UVM_MAP_EXTERNAL_ALLOCATION_PARAMS',
                          {'base': r.base, 'length': size, 'offset': 0, 'perGpuAttributes': [attrs], 'gpuAttributesCount': 1,
                           'rmCtrlFd': r.rm_ctrl_fd, 'hClient': r.h_client, 'hMemory': r.h_memory},
                          undo=lambda: None)
        self.observed['gpu_base'] = r.base
        self.observed['granted'] = sorted(granted)

    # --- public effects (lifecycle-guarded)
    def uvm_initialize(self):
        return self._run('uvm_initialize', self._uvm_initialize)

    def uvm_register_gpu(self):
        return self._run('uvm_register_gpu', self._uvm_register_gpu)

    def create_vaspace(self):
        return self._run('create_vaspace', self._create_vaspace)

    def uvm_register_vaspace(self):
        return self._run('uvm_register_vaspace', self._uvm_register_vaspace)

    def allocate(self):
        return self._run('allocate', self._allocate)

    def place(self):
        return self._run('place', self._place)

    def map_cpu(self):
        return self._run('map_cpu', self._map_cpu)

    def external_range(self):
        return self._run('external_range', self._external_range)

    def map_gpu(self):
        return self._run('map_gpu', self._map_gpu)

    def build(self):
        """A0 order: UVM init, GPU, VA space, UVM VA space, allocation, placement, CPU map, external range, GPU map.
        The CPU-map-before-external-range order is the baseline arm of A8-C8."""
        for step in (self.uvm_initialize, self.uvm_register_gpu, self.create_vaspace, self.uvm_register_vaspace,
                     self.allocate, self.place, self.map_cpu, self.external_range, self.map_gpu):
            step()
        return self

    # --- A5: channel region (channel objects themselves are created outside this module)
    def ctx_buffer_records(self, h_channel):
        """A5.2/A5.3: GET_CTX_BUFFER_INFO on the subdevice. A non-OK status is a STOP (no constant fallback).
        A query, not an acquisition; it may be repeated per channel handle."""
        return self._run('ctx_buffer_records', lambda: self._ctx_buffer_records(h_channel), once=False)

    def _ctx_buffer_records(self, h_channel):
        r, c = self.req, self.c
        require(is_int(h_channel) and 0 < h_channel <= U32, 'CHANNEL_HANDLE')
        pcodec = self.abi.struct('NV2080_CTRL_GR_GET_CTX_BUFFER_INFO_PARAMS')
        aux = pcodec.pack({'hUserClient': r.h_client, 'hChannel': h_channel})
        ptr_off = self.abi.struct('NVOS54_PARAMETERS').fields['params'][0]
        out = self._rm('IOCTL_RM_CONTROL', 'NVOS54_PARAMETERS',
                       {'hClient': r.h_client, 'hObject': r.h_subdevice,
                        'cmd': c('NV2080_CTRL_CMD_GR_GET_CTX_BUFFER_INFO'), 'paramsSize': pcodec.size},
                       indirect=(ptr_off, aux))
        if out['status'] == c('NV_ERR_INSUFFICIENT_PERMISSIONS'):
            raise Stop('A5_3_PERMISSION', status=out['status'])
        self._status(out, 'RM_CONTROL_CTX_BUFFER_INFO', 'status')
        info = pcodec.unpack(aux)
        count = info['bufferCount']
        require(0 <= count <= c('NV2080_CTRL_GR_MAX_CTX_BUFFER_COUNT'), 'CTX_BUFFER_COUNT', count=count)
        rec = self.abi.struct('NV2080_CTRL_GR_CTX_BUFFER_INFO')
        raw = info['ctxBufferInfo']
        records = []
        for i in range(count):
            e = rec.unpack(raw[i * rec.size:(i + 1) * rec.size])
            records.append((e['alignment'], e['size']))
        self.observed['ctx_buffer_records'] = tuple(records)
        return records

    def register_channel(self, h_channel, region_base, records, total_buffer_size=None):
        """A5.4-A5.7: region length from the aggregate rule, base aligned to max alignment and inside the VA space,
        disjoint from the arena; then UVM_REGISTER_CHANNEL. One registration per channel handle."""
        return self._run('register_channel:%r' % (h_channel,),
                         lambda: self._register_channel(h_channel, region_base, records, total_buffer_size))

    def _register_channel(self, h_channel, region_base, records, total_buffer_size):
        r = self.req
        require(is_int(h_channel) and 0 < h_channel <= U32, 'CHANNEL_HANDLE')
        length, max_align = channel_region_length(records, total_buffer_size)
        if length:
            require(is_int(region_base) and region_base % max_align == 0, 'REGION_BASE_ALIGNMENT',
                    base=region_base, alignment=max_align)
            contains(region_base, length, self.observed['va_base'], self.observed['va_size'])
            arena = (r.base, r.base + self.observed['arena_size'])
            require(region_base + length <= arena[0] or arena[1] <= region_base, 'REGION_OVERLAPS_ARENA')
            self._reserve('channel_region:%d' % h_channel, region_base, length)
        else:
            region_base = 0
        self._uvm_acquire('uvm_channel:%d' % h_channel, h_channel, 'UVM_REGISTER_CHANNEL', 'UVM_REGISTER_CHANNEL_PARAMS',
                          {'gpuUuid': r.gpu_uuid, 'rmCtrlFd': r.rm_ctrl_fd, 'hClient': r.h_client, 'hChannel': h_channel,
                           'base': region_base, 'length': length},
                          undo=lambda: self._uvm('UVM_UNREGISTER_CHANNEL', 'UVM_UNREGISTER_CHANNEL_PARAMS',
                                                 {'hClient': r.h_client, 'hChannel': h_channel}))
        self.observed['channel_region:%d' % h_channel] = (region_base, length, max_align)
        return region_base, length

    # --- A7
    def teardown(self, safe_state):
        """Reverse order; only in a known safe state; allowed once from OPEN or FAILED; stops at the first failed
        or uncertain owner, retains the rest and latches TERMINAL (no retry, no further effects)."""
        require(safe_state is True, 'TEARDOWN_UNSAFE_STATE', retained=self.retained())
        require(self.phase in (OPEN, FAILED), 'LIFECYCLE_CLOSED', phase=self.phase, step='teardown',
                retained=self.retained())
        # Terminal latch covers interruptions between undo calls and ledger updates.
        # Only completing the entire reverse walk may promote this to TORN.
        self.phase = TERMINAL
        while self.owners:
            o = self.owners[-1]
            if o.state != CERTAIN:
                self.phase = TERMINAL
                raise Stop('TEARDOWN_UNCERTAIN_OWNER', owner=o.summary(), note=o.note, retained=self.retained())
            try:
                o.undo()
                self.owners.pop()
            except Stop as e:
                self.phase = TERMINAL
                raise Stop('TEARDOWN_STOPPED', failed=o.summary(), cause=e.reason, retained=self.retained())
            except Exception as e:
                self.phase = TERMINAL
                o.state, o.note = UNCERTAIN, 'undo raised ' + type(e).__name__
                raise Stop('TEARDOWN_STOPPED', failed=o.summary(), cause='BACKEND_EXCEPTION', error=str(e),
                           retained=self.retained()) from e
            except BaseException as e:
                self.phase = TERMINAL
                o.state, o.note = UNCERTAIN, 'undo interrupted: ' + type(e).__name__
                # Even a cancellation after pop must retain the ambiguous record.
                if not any(owner is o for owner in self.owners):
                    self.owners.append(o)
                raise
        self.phase = TORN
