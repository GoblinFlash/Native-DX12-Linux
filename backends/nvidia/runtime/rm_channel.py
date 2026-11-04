"""Channel prerequisite: owning RM identity tree, not a runnable channel yet.

Original implementation from REQUIREMENTS_CHANNEL C0/C3.3, BACKEND B3 and
the pinned ABI. Uses our Images and the reviewed team's Owner by import.
One ledger contains backend FD owners and RM objects. No VA allocation,
schedule, upload, publication or GPU entry point is provided in this increment.
Client free uses root=client, parent=0, object=client as an explicit PROFILE
choice; CPU checks establish emitted bytes, not acceptance by RM.
"""
from dataclasses import replace
from channel_images import Handles, Images
from replacement_inputs import arena as A


class IdentityTree:
    """One attempt; errors latch, cleanup is explicit and never retried.

The supplied backend is exclusively owned by this tree. Callers must not use
it concurrently or bypass this lifecycle. The future arena must use precisely
this same owners list; this increment does not expose a completed channel.
"""
    def __init__(self, backend, handles, card, uuid):
        A.require(backend.phase == 'NEW' and not backend.owners, 'TREE_BACKEND_FRESH')
        A.require(type(handles) is Handles and handles.client == 0, 'TREE_HANDLE_PLAN')
        # Check every planned handle before opening anything. The generated
        # client is checked for collision immediately after its allocation.
        candidate = 1
        while candidate in vars(handles).values():
            candidate += 1
        replace(handles, client=candidate).validate()
        A.require(type(uuid) is bytes and len(uuid) == 16, 'CHANNEL_UUID_PLAN')
        self.backend, self.abi, self.owners = backend, backend.abi, backend.owners
        self.images, self.plan, self.card, self.uuid = Images(self.abi), handles, card, uuid
        self.phase, self.failure, self.observed = 'NEW', None, []
        self._handles, self._instances = None, None

    def _failed(self, exc):
        self.phase = 'FAILED'
        self.failure = {'type': type(exc).__name__, 'reason': str(exc)}
        for owner in self.owners:
            if owner.state == A.PENDING:
                owner.state = A.UNCERTAIN

    def _call(self, struct, request, envelope, parameters=None):
        data = bytearray(envelope)
        aux = bytearray(parameters) if parameters is not None else None
        codec = self.abi.struct(struct)
        pointer = 'pAllocParms' if struct == 'NVOS21_PARAMETERS' else 'params'
        indirect = (codec.fields[pointer][0], aux) if aux is not None else None
        event = {'request': request, 'input': bytes(data).hex(),
                 'parameters_input': bytes(aux).hex() if aux is not None else None}
        self.observed.append(event)
        try:
            rc = self.backend.ioctl('ctl', self.abi.const(request), data, indirect=indirect)
            event['rc'] = rc
        except BaseException as exc:
            event['exception'] = type(exc).__name__
            raise
        finally:
            # Preserve driver-written bytes even if the backend/recorder fails.
            event['output'] = bytes(data).hex()
            event['parameters_output'] = bytes(aux).hex() if aux is not None else None
        return rc, data, aux

    def _free(self, root, parent, handle):
        codec = self.abi.struct('NVOS00_PARAMETERS')
        data = codec.pack({'hRoot': root, 'hObjectParent': parent, 'hObjectOld': handle})
        rc, raw, _ = self._call('NVOS00_PARAMETERS', 'IOCTL_RM_FREE', data)
        A.require(type(rc) is int and rc == 0 and codec.unpack(raw)['status'] == self.abi.const('NV_OK'),
                  'TREE_FREE_FAILED')

    def _allocate(self, image, *, client=False):
        codec = self.abi.struct('NVOS21_PARAMETERS')
        requested = codec.unpack(image.envelope)
        owner = A.Owner('rm:' + image.label, requested.copy())
        self.owners.append(owner)  # Before any possible acquiring effect.
        try:
            rc, raw, aux = self._call('NVOS21_PARAMETERS', 'IOCTL_RM_ALLOC_NVOS21',
                                      image.envelope, image.parameters if image.parameter_type else None)
        except A.Rejected as exc:
            self.owners.pop()  # Only a certified pre-effect refusal permits this.
            raise A.Stop('TREE_ALLOCATION_REJECTED', label=image.label) from exc
        except BaseException:
            owner.state = A.UNCERTAIN
            owner.returned = self.observed[-1].copy()
            raise
        owner.returned = {'rc': rc, 'envelope': bytes(raw), 'parameters': bytes(aux or b'')}
        out = codec.unpack(raw)
        try:
            A.require(type(rc) is int and rc == 0 and out['status'] == self.abi.const('NV_OK'),
                      'TREE_ALLOC_STATUS', rc=rc, status=out['status'])
            A.require(all(out[k] == requested[k] for k in ('hRoot', 'hObjectParent', 'hClass', 'paramsSize')),
                      'TREE_ALLOC_IDENTITY')
            if client:
                handle, pattern, evidence = self.images.client_result(rc, raw, aux)
                root, parent = handle, 0
                self.observed[-1]['client_return'] = dict(evidence, pattern=pattern)
            else:
                handle = requested['hObjectNew']
                A.require(out['hObjectNew'] == handle, 'TREE_ALLOC_IDENTITY')
                root, parent = requested['hRoot'], requested['hObjectParent']
        except BaseException:
            owner.state = A.UNCERTAIN
            raise
        owner.undo = lambda: self._free(root, parent, handle)
        owner.state = A.CERTAIN
        return handle

    def _query(self, image):
        codec = self.abi.struct('NVOS54_PARAMETERS')
        rc, raw, aux = self._call('NVOS54_PARAMETERS', 'IOCTL_RM_CONTROL',
                                  image.envelope, image.parameters)
        out, original = codec.unpack(raw), codec.unpack(image.envelope)
        A.require(type(rc) is int and rc == 0 and out['status'] == self.abi.const('NV_OK'),
                  'TREE_CONTROL_STATUS', rc=rc, status=out['status'])
        A.require(all(out[k] == original[k] for k in ('hClient', 'hObject', 'cmd', 'flags', 'paramsSize')),
                  'TREE_CONTROL_IDENTITY')
        return bytes(aux)

    def acquire(self):
        A.require(self.phase == 'NEW', 'TREE_CLOSED')
        self.phase = 'OPENING'
        try:
            self.backend.open_nodes()
            actual = self.backend.verify_card(self.card)
            self.backend.register_device()
            codec = self.abi.struct('UVM_INITIALIZE_PARAMS')
            data = codec.pack({})
            rc = self.backend.ioctl('uvm', self.abi.const('UVM_INITIALIZE'), data)
            A.require(type(rc) is int and rc == 0 and codec.unpack(data)['rmStatus'] == self.abi.const('NV_OK'),
                      'TREE_UVM_INITIALIZE')
            self.backend.initialize_mm()
            client = self._allocate(self.images.client(), client=True)
            handles = replace(self.plan, client=client)
            handles.validate()
            instances = self.images.decode_instances(self._query(self.images.id_info(client, actual.gpu_id)), actual.gpu_id)
            self._allocate(self.images.device(handles, instances))
            self._allocate(self.images.subdevice(handles, instances))
            ident, gid = self.images.subdevice_identity(handles)
            self.images.check_subdevice_identity(actual.gpu_id, self.uuid, self._query(ident), self._query(gid))
            self._handles, self._instances = handles, instances
            self.phase = 'IDENTIFIED'
            return handles, instances
        except BaseException as exc:
            self._failed(exc)
            raise

    def identity(self):
        A.require(self.phase == 'IDENTIFIED', 'TREE_IDENTITY_UNAVAILABLE')
        A.require(self.owners is self.backend.owners and self.backend.phase == 'ACTIVE'
                  and all(x.state == A.CERTAIN for x in self.owners), 'TREE_OWNER_BINDING')
        return self._handles, self._instances

    def teardown(self, safe_state):
        A.require(safe_state is True, 'TREE_TEARDOWN_UNSAFE')
        A.require(self.phase in ('FAILED', 'IDENTIFIED'), 'TREE_CLOSED')
        self.phase = 'CLOSING'
        try:
            A.require(self.owners is self.backend.owners, 'TREE_OWNER_BINDING')
            self.backend.begin_teardown(True)
            while self.owners:
                owner = self.owners[-1]
                A.require(owner.state == A.CERTAIN and callable(owner.undo), 'TREE_UNCERTAIN_OWNER')
                try:
                    owner.undo()
                except BaseException:
                    owner.state = A.UNCERTAIN
                    raise
                self.owners.pop()
            self.backend.close_fds()
            self.phase = 'CLOSED'
        except BaseException:
            self.phase = 'TERMINAL'
            raise
