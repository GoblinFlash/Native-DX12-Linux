"""Initial sysmem upload, preserving the whole RM-owned USERD and all holes.

Original code from PREPARATION-UPLOAD; no former uploader used as a template.
Exclusive VA/fd/state ownership is required. No scheduling or publication.
"""
import ctypes
from dataclasses import dataclass
import hashlib

from channel_objects import ChannelObjects
from replacement_inputs import arena as A

LIMIT = 256 * 1024 * 1024


def native_span(address, length):
    A.require(type(address) is int and 0 < address < 1 << 64
              and type(length) is int and 0 < length <= LIMIT
              and address <= (1 << 64) - length, 'UPLOAD_NATIVE_SPAN')


def native_read(address, length):
    """Trusted ordinary-memory copy, not volatile or an acquire fence."""
    native_span(address, length)
    return ctypes.string_at(address, length)


def native_write(address, data):
    """Caller must own the live ordinary-memory mapping, exclusively."""
    A.require(type(data) is bytes, 'UPLOAD_NATIVE_BYTES')
    native_span(address, len(data))
    ctypes.memmove(address, data, len(data))


@dataclass(frozen=True)
class Span:
    offset: int
    data: bytes


class InitialUpload:
    def __init__(self, objects, read_bytes, write_bytes):
        A.require(type(objects) is ChannelObjects and objects.phase == 'PREPARED', 'UPLOAD_CHANNEL')
        A.require(callable(read_bytes) and callable(write_bytes), 'UPLOAD_CALLBACKS')
        A.require(getattr(objects, '_initial_upload', None) is None, 'UPLOAD_EXISTS')
        self.objects, self.session = objects, objects._session
        self.read_bytes, self.write_bytes = read_bytes, write_bytes
        self.phase, self.result = 'NEW', None
        objects._initial_upload = self

    def _live(self):
        o, s = self.objects, self.session
        A.require(o._initial_upload is self and o._session is s and o.phase == 'PREPARED',
                  'UPLOAD_OWNER')
        o.binding()
        arena = s.binding()
        m = s._mappings
        mapped = m.validate_binding(s._cpu_mapping)
        A.require(mapped.profile == 'sysmem' and 0 < mapped.length <= LIMIT
                  and (arena.cpu_base, arena.size) == (mapped.cpu_base, mapped.length),
                  'UPLOAD_ARENA')
        record = m.records[mapped.mapping_id]
        A.require(m._range(record)['state'] == 'M1_MATERIALIZED', 'UPLOAD_MAPPING_STATE')
        m._fd(record)
        rows = m.backend._snapshot(mapped.cpu_base, mapped.length)
        A.require(len(rows) == 1 and rows[0].start == mapped.cpu_base
                  and rows[0].end == mapped.cpu_base + mapped.length
                  and rows[0].perms == 'rw-s' and rows[0].path == record.fingerprint[4],
                  'UPLOAD_VMA_CHANGED')
        return mapped

    def _plan(self, spans, mapped):
        A.require(type(spans) is tuple and 1 <= len(spans) <= 128, 'UPLOAD_PLAN')
        userd = self.objects.config.userd_offset
        size = self.objects.abi.struct('Nvc56fControl').size
        A.require(size == 512 and 0 <= userd <= mapped.length - size, 'UPLOAD_USERD')
        ends = []
        for span in spans:
            A.require(type(span) is Span and type(span.offset) is int
                      and type(span.data) is bytes and len(span.data) > 0, 'UPLOAD_SPAN_TYPE')
            a, n = span.offset, len(span.data)
            A.require(0 <= a <= mapped.length and n <= mapped.length - a, 'UPLOAD_CONTAINMENT')
            A.require(a + n <= userd or a >= userd + size, 'UPLOAD_USERD_OVERLAP')
            A.require(all(a + n <= b or e <= a for b, e in ends), 'UPLOAD_SPAN_OVERLAP')
            ends.append((a, a + n))
        return userd, size

    def _same(self, mapped):
        A.require(self._live() is mapped, 'UPLOAD_BINDING_CHANGED')

    def _read(self, mapped):
        self._same(mapped)
        raw = self.read_bytes(mapped.cpu_base, mapped.length)
        A.require(type(raw) is bytes and len(raw) == mapped.length, 'UPLOAD_READ_RESULT')
        self._same(mapped)
        return raw

    def upload(self, spans):
        A.require(self.phase == 'NEW', 'UPLOAD_CLOSED')
        self.phase = 'UPLOADING'
        try:
            def perform():
                mapped = self._live()
                userd, size = self._plan(spans, mapped)
                before = self._read(mapped)
                self.objects._tree.images.check_initial_userd(before[userd:userd + size])
                expected = bytearray(before)
                for span in spans:
                    expected[span.offset:span.offset + len(span.data)] = span.data
                for span in spans:
                    self._same(mapped)
                    returned = self.write_bytes(mapped.cpu_base + span.offset, span.data)
                    A.require(returned is None, 'UPLOAD_WRITE_RESULT')
                    self._same(mapped)
                after = self._read(mapped)
                A.require(after == expected, 'UPLOAD_FULL_IMAGE_MISMATCH')
                return {'mapping_id': mapped.mapping_id, 'arena_bytes': mapped.length,
                        'written_bytes': sum(len(s.data) for s in spans),
                        'spans': tuple((s.offset, len(s.data), hashlib.sha256(s.data).hexdigest()) for s in spans),
                        'before_sha256': hashlib.sha256(before).hexdigest(),
                        'after_sha256': hashlib.sha256(after).hexdigest(),
                        'status': 'CPU_INITIAL_UPLOAD_VERIFIED', 'gpu_executed': False}
            self.result = self.session._mappings._guard(perform)
            self.phase = 'DONE'
            return self.result
        except BaseException as exc:
            self.phase, self.objects.phase, self.session.phase = 'FAILED', 'FAILED', 'FAILED'
            self.objects.failure = {'type': type(exc).__name__, 'reason': str(exc)}
            self.session._tree._failed(exc)
            self.session._arena._fail('UPLOAD_FAILED', self.objects.failure)
            raise
