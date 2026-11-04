"""CPU argument tests; no container engine or device is invoked."""
import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

spec=importlib.util.spec_from_file_location('launcher',Path(__file__).with_name('run.py'))
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ['NDX12_TEST_ROOT'])
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.cache=self.root/'cache with spaces';self.cache.mkdir()
        self.output=self.root/'output';self.output.mkdir()
        self.args=SimpleNamespace(engine='podman',dry_run=True,action='build',
              image='example.org/native/toolchain@sha256:'+'a'*64,cache=self.cache,
              output=self.output,jobs=2,targets='intel,rtx,amd')

    def test_build_is_networkless_and_device_free(self):
        argv=M.command(self.args)
        self.assertIn('--network=none',argv)
        self.assertIn('--cap-drop=ALL',argv)
        self.assertIn('--read-only',argv)
        self.assertIn('--pull=never',argv)
        self.assertNotIn('--privileged',argv)
        self.assertFalse(any(x.startswith(('--device','--gpus')) for x in argv))
        self.assertIn(f'type=bind,src={self.cache},dst=/cache,readonly',argv)
        self.assertNotIn('--offline',argv)  # Outer namespace, not nested unshare.

    def test_local_image_id_allowed(self):
        self.args.image="sha256:"+"b"*64
        self.assertIn(self.args.image,M.command(self.args))

    def test_mutable_image_refused(self):
        self.args.image='ubuntu:26.04'
        with self.assertRaisesRegex(ValueError,'IMAGE_DIGEST_REQUIRED'):M.command(self.args)

    def test_source_cache_refused(self):
        self.args.cache=M.PACKAGE
        with self.assertRaisesRegex(ValueError,'SOURCE_OVERLAP'):M.command(self.args)

    def test_nested_output_refused(self):
        self.args.output=self.cache/'nested';self.args.output.mkdir()
        with self.assertRaisesRegex(ValueError,'CACHE_OUTPUT_OVERLAP'):M.command(self.args)

    def test_symlink_overlap_refused(self):
        link=self.root/'link';link.symlink_to(self.cache);self.args.output=link
        with self.assertRaisesRegex(ValueError,'CACHE_OUTPUT_OVERLAP'):M.command(self.args)

    def test_existing_output_preserved(self):
        marker=self.output/'KEEP';marker.write_bytes(b'original')
        with self.assertRaisesRegex(ValueError,'OUTPUT_NOT_EMPTY'):M.command(self.args)
        self.assertEqual(marker.read_bytes(),b'original')

    def test_mount_syntax_refused(self):
        self.args.cache=self.root/'bad,path';self.args.cache.mkdir()
        with self.assertRaisesRegex(ValueError,'MOUNT_PATH_CHARACTER'):M.command(self.args)

    def test_fetch_is_explicit_network_action(self):
        self.args.action='fetch';argv=M.command(self.args)
        self.assertNotIn('--network=none',argv)
        self.assertIn(f'type=bind,src={self.cache},dst=/cache',argv)
        self.assertEqual(argv[-3:],['fetch','--cache','/cache'])


if __name__=='__main__':unittest.main()
