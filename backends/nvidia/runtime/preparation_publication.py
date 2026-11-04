"""Original CPU publication model; no native transport or completion path.

Callbacks are trusted synthetic effects, never hardware primitives. P0 selects
PUT=1 as an unqualified entry-index profile. An armed attempt remains retained.
"""
from copy import deepcopy

from preparation_schedule import InitialSchedule
from replacement_inputs import arena as A


def word_target(address, base, size):
    A.require(type(address) is int and address > 0 and address % 4 == 0
              and type(base) is int and type(size) is int and size >= 4
              and 0 <= base < 1 << 64 and size <= (1 << 64) - base
              and base <= address <= base + size - 4, 'PUBLICATION_WORD_TARGET')


class InitialPublication:
    def __init__(self, schedule, release, write32, *, mode, record=None):
        A.require(type(schedule) is InitialSchedule and schedule.phase == 'ACKNOWLEDGED',
                  'PUBLICATION_SCHEDULE')
        A.require(mode == 'CPU_MODEL' and type(mode) is str, 'PUBLICATION_MODEL_ONLY')
        A.require(callable(release) and callable(write32)
                  and (record is None or callable(record)), 'PUBLICATION_CALLBACKS')
        o, s, t = schedule.objects, schedule.session, schedule.tree
        A.require(getattr(o, '_initial_publication', None) is None, 'PUBLICATION_EXISTS')
        self.schedule, self.objects, self.session, self.tree = schedule, o, s, t
        self.backend, self.owners, self.mappings = t.backend, t.owners, s._mappings
        self.arena, self.config, self.resource_config = s._arena, o.config, s.config
        self.upload, self.binding = schedule.upload, schedule.binding
        self.arena_binding = s._binding
        self.handles, self.instances = t._handles, t._instances
        self.sysmem, self.usermode = s._cpu_mapping, o._usermode_mapping
        self.mapping_rows = tuple((b, self.mappings.records[b.mapping_id],
                                   self.mappings.records[b.mapping_id].spec,
                                   self.mappings.records[b.mapping_id].backing,
                                   self.mappings.records[b.mapping_id].fingerprint)
                                  for b in (self.sysmem, self.usermode))
        self.parents = tuple(self.owners)
        self.parent_undo = tuple(x.undo for x in self.parents)
        self.parent_values = deepcopy([(x.label, x.requested, x.returned) for x in self.parents])
        self.release, self.write32, self.record = release, write32, record
        self.phase, self.owner, self.failure, self.result = 'NEW', None, None, None
        self.events = []
        o._initial_publication = self

    def _dependencies(self, armed):
        o, s, t, m = self.objects, self.session, self.tree, self.mappings
        A.require(o._initial_publication is self and o._initial_schedule is self.schedule
                  and o._initial_upload is self.upload and o._session is s
                  and s._tree is t and t.backend is self.backend
                  and s._mappings is m and s._arena is self.arena
                  and self.schedule.upload is self.upload
                  and self.schedule.objects is o and self.schedule.session is s
                  and self.schedule.tree is t and self.schedule.owners is self.owners,
                  'PUBLICATION_ASSOCIATION')
        o._owned()
        A.require(self.owners is t.owners and self.owners is self.backend.owners,
                  'PUBLICATION_LEDGER')
        expected = self.parents + ((self.owner,) if armed else ())
        A.require(len(self.owners) == len(expected)
                  and all(x is y for x, y in zip(self.owners, expected)), 'PUBLICATION_LEDGER')
        A.require(all(x.state == A.CERTAIN and x.undo is undo
                      for x, undo in zip(self.parents, self.parent_undo))
                  and [(x.label, x.requested, x.returned) for x in self.parents] == self.parent_values,
                  'PUBLICATION_PARENT_CHANGED')
        if armed:
            A.require(self.owner is not None and self.owner.state == A.UNCERTAIN
                      and self.owner.undo is None, 'PUBLICATION_FLIGHT_OWNER')
        A.require(o.phase == 'PREPARED' and s.phase == 'ARENA_READY'
                  and t.phase == 'IDENTIFIED' and self.backend.phase == 'ACTIVE'
                  and not self.backend.pending and self.arena.phase == A.OPEN
                  and m.phase == 'ACTIVE' and self.schedule.phase == 'ACKNOWLEDGED'
                  and self.upload.phase == 'DONE', 'PUBLICATION_PHASE')
        A.require(o._binding is self.binding and self.schedule.binding is self.binding
                  and s._binding is self.arena_binding and o.config is self.config
                  and s.config is self.resource_config and t._handles is self.handles
                  and t._instances is self.instances and s._cpu_mapping is self.sysmem
                  and o._usermode_mapping is self.usermode, 'PUBLICATION_BINDING')
        for binding, rec, spec, backing, fingerprint in self.mapping_rows:
            A.require(m.records.get(binding.mapping_id) is rec and rec.spec is spec
                      and rec.backing is backing and rec.fingerprint == fingerprint,
                      'PUBLICATION_MAPPING_IDENTITY')
            A.require(m.validate_binding(binding) is binding
                      and (rec.fd, rec.rm_address) == (binding.fd, binding.rm_address)
                      and m._range(rec)['state'] == 'M1_MATERIALIZED', 'PUBLICATION_MAPPING')
            m._fd(rec)
            rows = self.backend._snapshot(binding.cpu_base, binding.length)
            A.require(len(rows) == 1 and rows[0].start == binding.cpu_base
                      and rows[0].end == binding.cpu_base + binding.length
                      and rows[0].perms == 'rw-s' and rows[0].path == fingerprint[4],
                      'PUBLICATION_VMA')

    def _addresses(self):
        b = self.binding
        A.require(self.sysmem.profile == 'sysmem' and self.usermode.profile == 'usermode'
                  and (self.arena_binding.cpu_base, self.arena_binding.size)
                      == (self.sysmem.cpu_base, self.sysmem.length)
                  and b.usermode_base == self.usermode.cpu_base
                  and b.userd_address == self.sysmem.cpu_base + self.config.userd_offset,
                  'PUBLICATION_ADDRESS_BINDING')
        control = self.tree.abi.struct('Nvc56fControl')
        # The pinned ABI's field tuple starts with its byte offset.
        put = b.userd_address + control.fields['GPPut'][0]
        A.require(control.size == 512 and self.config.userd_offset >= 0
                  and self.config.userd_offset <= self.sysmem.length - 512,
                  'PUBLICATION_USERD')
        A.require(b.doorbell_address == self.usermode.cpu_base
                  + self.tree.abi.const('NVC361_NOTIFY_CHANNEL_PENDING'), 'PUBLICATION_DOORBELL')
        word_target(put, self.sysmem.cpu_base, self.sysmem.length)
        word_target(b.doorbell_address, self.usermode.cpu_base, self.usermode.length)
        A.require(type(b.token) is int and 0 <= b.token < 1 << 32, 'PUBLICATION_TOKEN')
        return put, b.doorbell_address, b.token

    def _event(self, operation, effect, **fields):
        self._dependencies(True)
        event = {'index': len(self.events), 'operation': operation, 'attempted': False, **fields}
        self.events.append(event)
        # Recorder failure can occur either before or after the synthetic effect.
        if self.record is not None:
            self.record(dict(event))
        self._dependencies(True)
        event['attempted'] = True
        try:
            returned = effect()
            event['returned'] = returned
            event['call_returned'] = True
            A.require(returned is None, 'PUBLICATION_EFFECT_RESULT')
        except BaseException as exc:
            event['error'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        if self.record is not None:
            self.record(dict(event))
        self._dependencies(True)

    def publish(self):
        A.require(self.phase == 'NEW', 'PUBLICATION_CLOSED')
        self.phase = 'PREFLIGHT'
        try:
            self._dependencies(False)
            self.schedule._check()
            put, doorbell, token = self._addresses()
            self._dependencies(False)
            self.owner = A.Owner('work:initial_publication', {
                'channel': self.binding.channel, 'put_address': put, 'put': 1,
                'doorbell_address': doorbell, 'token': token,
                'upload_sha256': self.schedule.digest}, state=A.UNCERTAIN)
            self.owners.append(self.owner)
            self.owner.returned = self.events
            self.phase = 'ARMED'
            self._event('release_before_put', self.release)
            self._event('put', lambda: self.write32(put, 1), address=put, value=1)
            self._event('release_before_doorbell', self.release)
            self._event('doorbell', lambda: self.write32(doorbell, token), address=doorbell, value=token)
            self.result = {'status': 'CPU_PUBLICATION_SEQUENCE_RECORDED', 'mode': 'CPU_MODEL',
                           'completion_verified': False, 'retained': True,
                           'publication_attempts': 1, 'effects': len(self.events)}
            self.phase = 'PUBLISHED_UNCONFIRMED'
            return dict(self.result)
        except BaseException as exc:
            self.phase = 'FAILED_HELD' if self.owner is not None else 'REFUSED_BEFORE_ARM'
            if self.owner is not None:
                self.owner.state = A.UNCERTAIN
            self.failure = {'type': type(exc).__name__, 'message': str(exc)}
            # Preserve resources. No automatic cleanup and no retry transition.
            for layer in (self.objects, self.session, self.mappings, self.backend):
                if layer.phase in ('CLOSING', 'CLEANUP'):
                    layer.phase = 'TERMINAL'
                elif layer.phase not in ('TERMINAL', 'CLOSED', 'TORN'):
                    layer.phase = 'FAILED'
            if self.tree.phase not in ('TERMINAL', 'CLOSED'):
                self.tree._failed(exc)
            self.arena._fail('PUBLICATION_FAILED', self.failure)
            raise
