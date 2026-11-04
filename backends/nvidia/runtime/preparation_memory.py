"""Read the initial USERD through the actual M1 arena binding, once.

Original code from preparation requirements and Python's byte-copy interface.
No legacy memory helper or vendor implementation template. This is not a poll,
GPU acquire fence, generic buffer API, MMIO accessor or publication mechanism.
Exclusive CPU VA/fd ownership is required across both snapshots and the copy.
"""
import ctypes

from channel_objects import ChannelConfig, ChannelObjects
from channel_resources import ArenaSession
from replacement_inputs import arena as A


def native_userd_copy(address, length):
    """Trusted primitive: caller must prove the mapping is live before calling.

    ctypes copies ordinary mapped sysmem. It supplies no device ordering proof.
    A concurrent unmap can cause a process fault; Python cannot recover it.
    """
    A.require(type(address) is int and 0 < address < 1 << 64 and address % 4 == 0
              and type(length) is int and length == 512 and address <= (1 << 64) - length,
              'USERD_NATIVE_SPAN')
    return ctypes.string_at(address, length)


class UserdReader:
    """Explicit callback for ChannelObjects.prepare; no fallback or retry."""
    def __init__(self, session, config, copy_bytes):
        A.require(type(session) is ArenaSession and session.phase == 'NEW', 'USERD_SESSION')
        A.require(type(config) is ChannelConfig and callable(copy_bytes), 'USERD_CONFIG')
        A.require(getattr(session, '_userd_reader', None) is None, 'USERD_READER_EXISTS')
        self.session, self.config, self.copy_bytes = session, config, copy_bytes
        self.phase = 'NEW'
        self.observed = None
        session._userd_reader = self

    def _source(self, address, length):
        session = self.session
        objects = getattr(session, '_channel_session', None)
        A.require(session._userd_reader is self and type(objects) is ChannelObjects
                  and objects._session is session and objects.config is self.config
                  and objects._read is self and objects.phase == 'PREPARING', 'USERD_READER_BINDING')
        binding = session.binding()
        manager = session._mappings
        mapped = manager.validate_binding(session._cpu_mapping)
        size = session._tree.abi.struct('Nvc56fControl').size
        A.require(size == 512 and mapped.profile == 'sysmem'
                  and (binding.cpu_base, binding.size) == (mapped.cpu_base, mapped.length),
                  'USERD_ARENA_BINDING')
        offset = self.config.userd_offset
        A.require(type(address) is int and type(length) is int and length == size
                  and address == mapped.cpu_base + offset and offset >= 0
                  and offset <= mapped.length and length <= mapped.length - offset,
                  'USERD_READ_SPAN')
        record = manager.records[mapped.mapping_id]
        A.require(manager._range(record)['state'] == 'M1_MATERIALIZED', 'USERD_MAPPING_STATE')
        manager._fd(record)
        rows = manager.backend._snapshot(mapped.cpu_base, mapped.length)
        A.require(len(rows) == 1 and rows[0].start == mapped.cpu_base
                  and rows[0].end == mapped.cpu_base + mapped.length
                  and rows[0].perms == 'rw-s' and rows[0].path == record.fingerprint[4],
                  'USERD_VMA_CHANGED')
        return mapped

    def __call__(self, address, length):
        A.require(self.phase == 'NEW', 'USERD_READER_CLOSED')
        self.phase = 'READING'
        try:
            manager = self.session._mappings
            A.require(manager is not None, 'USERD_MAPPING_MISSING')
            def read():
                mapped = self._source(address, length)
                raw = self.copy_bytes(address, length)
                A.require(type(raw) is bytes and len(raw) == length, 'USERD_COPY_RESULT')
                A.require(self._source(address, length) is mapped, 'USERD_BINDING_CHANGED')
                self.observed = {'mapping_id': mapped.mapping_id, 'cpu_address': address,
                                 'length': length, 'bytes': raw}
                return raw
            raw = manager._guard(read)
            self.phase = 'DONE'
            return raw
        except BaseException:
            self.phase = 'FAILED'
            raise
