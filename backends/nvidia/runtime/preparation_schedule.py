"""One initial scheduling sequence, with no command publication.

Original implementation of PREPARATION-SCHEDULE. Only the header-derived Images
builder and our existing preparation layers are reused. Exclusive trusted state
ownership is required; no GPU completion or packet-semantics claim is made.
"""
import hashlib

from preparation_upload import InitialUpload
from replacement_inputs import arena as A


class InitialSchedule:
    def __init__(self, upload, *, bind_group=False, read_bytes=None):
        A.require(type(upload) is InitialUpload and upload.phase == 'DONE', 'SCHEDULE_UPLOAD')
        A.require(type(bind_group) is bool, 'SCHEDULE_PROFILE')
        A.require(read_bytes is None or callable(read_bytes), 'SCHEDULE_READER')
        objects = upload.objects
        A.require(getattr(objects, '_initial_schedule', None) is None, 'SCHEDULE_EXISTS')
        mapped = upload._live()
        result = upload.result
        A.require(type(result) is dict and result.get('status') == 'CPU_INITIAL_UPLOAD_VERIFIED'
                  and result.get('mapping_id') == mapped.mapping_id
                  and type(result.get('arena_bytes')) is int
                  and result['arena_bytes'] == mapped.length, 'SCHEDULE_UPLOAD_RESULT')
        digest = result.get('after_sha256')
        A.require(type(digest) is str and len(digest) == 64
                  and all(c in '0123456789abcdef' for c in digest), 'SCHEDULE_UPLOAD_DIGEST')
        self.upload, self.objects, self.session = upload, objects, upload.session
        self.tree, self.owners = objects._tree, objects.owners
        self.mapped, self.binding, self.digest = mapped, objects.binding(), digest
        self.bind_group = bind_group
        self.read_bytes = self._reader = read_bytes
        self.phase, self.owner, self.result = 'NEW', None, None
        self._owner = None
        self.failed_owner = None
        self.attempts = []
        self._attempts = self.attempts
        objects._initial_schedule = self

    def _check(self):
        A.require(self.objects._initial_schedule is self and self.upload.phase == 'DONE'
                  and self.objects._initial_upload is self.upload
                  and self.owners is self.tree.owners, 'SCHEDULE_OWNER')
        A.require(self.objects.binding() is self.binding, 'SCHEDULE_BINDING')
        A.require(self.attempts is self._attempts and self.owner is self._owner and (self.owner is None or
                  (self.owners[-1] is self.owner and self.owner.returned is self.attempts)),
                  'SCHEDULE_OWNER_CHANGED')
        A.require(self.read_bytes is self._reader, 'SCHEDULE_READER_CHANGED')
        self.upload._same(self.mapped)
        if self._reader is None:
            raw = self.upload._read(self.mapped)
        else:
            raw = self._reader(self.mapped.cpu_base, self.mapped.length)
            A.require(type(raw) is bytes and len(raw) == self.mapped.length, 'SCHEDULE_READ_RESULT')
            self.upload._same(self.mapped)
        A.require(self.read_bytes is self._reader, 'SCHEDULE_READER_CHANGED')
        A.require(hashlib.sha256(raw).hexdigest() == self.digest, 'SCHEDULE_IMAGE_CHANGED')
        offset = self.objects.config.userd_offset
        self.tree.images.check_initial_userd(raw[offset:offset + 512])

    def _retire(self):
        # This is a control-state obligation, not a separately allocated object.
        # Caller has explicitly entered known-safe teardown; no disable or retry.
        A.require(self.phase == 'ACKNOWLEDGED' and self.tree.backend.phase == 'CLEANUP'
                  and self.owners[-1] is self.owner and self.owner.state == A.CERTAIN,
                  'SCHEDULE_RETIRE_STATE')
        self.phase = 'RETIRED'

    def schedule(self):
        A.require(self.phase == 'NEW', 'SCHEDULE_CLOSED')
        self.phase = 'SCHEDULING'
        retained = None
        attempts = self.attempts
        try:
            def perform():
                nonlocal retained
                self._check()
                handles, _ = self.tree.identity()
                calls = self.tree.images.scheduling(handles, bind_group=self.bind_group)
                self.tree.images.validate_schedule_images(handles, calls)
                for index, image in enumerate(calls):
                    self._check()
                    if self.owner is None:
                        self.owner = A.Owner('control:initial_schedule', {
                            'channel': self.binding.channel, 'bind_group': self.bind_group,
                            'upload_sha256': self.digest})
                        self.owners.append(self.owner)
                        self._owner = self.owner
                        retained = self.owner
                    owned = self._owner
                    A.require(self.owner is owned and self.owners[-1] is owned,
                              'SCHEDULE_OWNER_CHANGED')
                    self.owner.state = A.PENDING
                    attempt = {'index': index, 'envelope': image.envelope.hex(),
                               'parameters': image.parameters.hex()}
                    self.attempts.append(attempt)
                    start = len(self.tree.observed)
                    try:
                        reply = self.tree._query(image)
                        A.require(reply == image.parameters, 'SCHEDULE_PARAMETERS_CHANGED')
                        attempt['acknowledged'] = True
                    except A.Rejected as exc:
                        attempt['rejected_before_effect'] = True
                        if index == 0:
                            A.require(self.owner is owned and self._owner is owned
                                      and self.owners[-1] is owned, 'SCHEDULE_OWNER_STACK')
                            self.owners.pop()
                            self.owner = self._owner = None
                            retained = None
                        raise A.Stop('SCHEDULE_REJECTED', index=index) from exc
                    finally:
                        attempt['events'] = [dict(e) for e in self.tree.observed[start:]]
                        owned.returned = attempts
                    A.require(self.owner is owned and self._owner is owned
                              and self.owners[-1] is owned and owned.returned is self.attempts
                              and self.attempts is self._attempts is attempts,
                              'SCHEDULE_OWNER_CHANGED')
                    self.owner.state = A.CERTAIN
                    self._check()
                self.owner.undo = self._retire
                self.result = {'status': 'CHANNEL_SCHEDULE_ACKNOWLEDGED',
                               'channel': self.binding.channel,
                               'bind_group': self.bind_group, 'controls': len(calls),
                               'upload_sha256': self.digest, 'work_published': False}
                self.phase = 'ACKNOWLEDGED'
                return dict(self.result)
            return self.session._mappings._guard(perform)
        except BaseException as exc:
            self.failed_owner = retained
            if retained is not None:
                retained.state = A.UNCERTAIN
            self.phase, self.objects.phase, self.session.phase = 'FAILED', 'FAILED', 'FAILED'
            self.objects.failure = {'type': type(exc).__name__, 'reason': str(exc)}
            self.tree._failed(exc)
            self.session._arena._fail('SCHEDULE_FAILED', self.objects.failure)
            raise
