"""One full initial upload of the four original data-resource BOs.

Expected bytes come from input keys and the reviewed scope-B oracle, never
observed output. Copy callbacks operate only on owned ordinary RAM, under the
existing exclusive VA/fd-table profile. No MMIO, submission or GPU completion.
"""
from dataclasses import dataclass
import hashlib
import threading

from data_resources import DataResources
from replacement_inputs import arena as A


@dataclass(frozen=True)
class DataUploadResult:
    mapping_ids: tuple
    allocation_sizes: tuple
    image_sha256: tuple
    written_bytes: int
    status: str = 'CPU_INITIAL_DATA_UPLOAD_VERIFIED'
    gpu_executed: bool = False


class InitialDataUpload:
    def __init__(self, resources, read_bytes, write_bytes):
        A.require(type(resources) is DataResources and resources.phase == 'READY', 'DATA_UPLOAD_RESOURCES')
        A.require(callable(read_bytes) and callable(write_bytes), 'DATA_UPLOAD_CALLBACKS')
        A.require(getattr(resources, '_initial_data_upload', None) is None, 'DATA_UPLOAD_EXISTS')
        self.resources, self.objects = resources, resources.objects
        self.layout, self.bindings = resources.layout, resources._result
        self.read_bytes, self.write_bytes = read_bytes, write_bytes
        self._callbacks = (read_bytes, write_bytes)
        self.thread, self.busy = threading.get_ident(), True
        self.phase, self.result, self.failure = 'NEW', None, None
        resources._initial_data_upload = self
        try:
            self._live()
        except BaseException as exc:
            self._fail(exc)
            raise
        finally:
            self.busy = False

    def _live(self):
        d = self.resources
        A.require(d._initial_data_upload is self and d.objects is self.objects
                  and d.layout is self.layout and self.read_bytes is self._callbacks[0]
                  and self.write_bytes is self._callbacks[1], 'DATA_UPLOAD_BINDING')
        A.require(getattr(self.objects, '_initial_schedule', None) is None
                  and getattr(self.objects, '_mapping_transport', None) is None,
                  'DATA_UPLOAD_TOO_LATE')
        A.require(d.binding() is self.bindings, 'DATA_UPLOAD_RESOURCE_CHANGED')
        return self.bindings

    def _admit(self, images):
        A.require(type(images) is tuple and len(images) == 4
                  and all(type(raw) is bytes for raw in images), 'DATA_UPLOAD_IMAGES')
        sizes = tuple(b.allocation_size for b in self.bindings)
        A.require(tuple(len(raw) for raw in images) == sizes, 'DATA_UPLOAD_LENGTHS')
        expected = self.layout.initial_images(sizes)
        A.require(images == expected, 'DATA_UPLOAD_INITIAL_MISMATCH')

    def _copy(self, fn, *args):
        self._live()
        d = self.resources
        A.require(not d.busy, 'DATA_UPLOAD_RESOURCE_BUSY')
        d.busy = True
        try:
            value = fn(*args)
        finally:
            d.busy = False
        self._live()
        return value

    def _fail(self, exc):
        self.phase = 'FAILED'
        self.failure = {'type': type(exc).__name__, 'message': str(exc)}
        self.resources._fail(exc)

    def upload(self, images):
        A.require(not self.busy and threading.get_ident() == self.thread, 'DATA_UPLOAD_BUSY')
        A.require(self.phase == 'NEW', 'DATA_UPLOAD_CLOSED')
        self.phase, self.busy = 'UPLOADING', True
        try:
            self._live()
            self._admit(images)  # All four, including guards/tails, before any byte callback.
            self._live()
            for binding, raw in zip(self.bindings, images):
                value = self._copy(self.write_bytes, binding.cpu_base, raw)
                A.require(value is None, 'DATA_UPLOAD_WRITE_RESULT')
            digests = []
            for binding, expected in zip(self.bindings, images):
                observed = self._copy(self.read_bytes, binding.cpu_base, binding.allocation_size)
                A.require(type(observed) is bytes and len(observed) == binding.allocation_size,
                          'DATA_UPLOAD_READ_RESULT')
                A.require(observed == expected, 'DATA_UPLOAD_FULL_IMAGE_MISMATCH', role=binding.role)
                digests.append(hashlib.sha256(observed).hexdigest())
            self._live()
            self.result = DataUploadResult(tuple(b.mapping.mapping_id for b in self.bindings),
                                           tuple(b.allocation_size for b in self.bindings),
                                           tuple(digests), sum(len(raw) for raw in images))
            self.phase = 'DONE'
            return self.result
        except BaseException as exc:
            self._fail(exc)
            raise
        finally:
            self.busy = False
