"""CPU-only installer rollback checks using temporary package directories."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


INSTALLER = Path(__file__).resolve().parents[1] / 'NDX12_GPU_Benchmark/ndx12-install.py'


class PackageRestoreTests(unittest.TestCase):
    def run_failed_install(self, root, *, previous=True, restore_fails=False):
        spec = importlib.util.spec_from_file_location('benchmark_installer', INSTALLER)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        for name in ('OPT', 'LIBEXEC', 'ETC', 'BIN'):
            folder = root / name.lower()
            folder.mkdir()
            setattr(installer, name, str(folder))
        for name, folder in (('PACKAGE', 'OPT'), ('STARTER_PATH', 'LIBEXEC'), ('TRUST', 'ETC'),
                             ('COMMAND', 'BIN'), ('RECEIPT', 'ETC')):
            setattr(installer, name, str(Path(getattr(installer, folder)) / name.lower()))
        package = Path(installer.PACKAGE)
        if previous:
            package.mkdir()
            (package / 'old').write_text('previous package')

        def unpack(archive, staging):
            staged = Path(staging) / 'new-package'
            staged.mkdir()
            return str(staged)

        rename = installer.os.rename

        def fail_rename(source, destination):
            if Path(source).name == 'new-package':
                raise OSError('install rename failed')
            if '.replaced-' in str(source) and restore_fails:
                raise OSError('restore rename failed')
            return rename(source, destination)

        stderr = io.StringIO()
        old_umask = installer.os.umask(0o022)
        try:
            with contextlib.ExitStack() as stack:
                for name, value in (('check_requirements', None), ('own_sha256', 'test digest'),
                                    ('read_download', b'test data'), ('check_folders', []), ('say', None)):
                    stack.enter_context(patch.object(installer, name, return_value=value))
                stack.enter_context(patch.object(installer, 'unpack', side_effect=unpack))
                stack.enter_context(patch.object(installer, 'starter_check',
                                                side_effect=[(True, 'verified'), (False, 'old package')]))
                stack.enter_context(patch.object(installer.os, 'rename', side_effect=fail_rename))
                stack.enter_context(contextlib.redirect_stderr(stderr))
                self.assertEqual(installer.main([]), 1)
        finally:
            installer.os.umask(old_umask)
        self.assertFalse(list(root.rglob('*.new')))
        self.assertFalse(list(root.rglob('.install-*')))
        return package, stderr.getvalue()

    def test_failed_restore_reports_preserved_package_and_incomplete_status(self):
        with tempfile.TemporaryDirectory() as directory:
            package, output = self.run_failed_install(Path(directory), restore_fails=True)
            self.assertFalse(package.exists())
            aside, = package.parent.glob(package.name + '.replaced-*')
            self.assertEqual((aside / 'old').read_text(), 'previous package')
            self.assertIn(str(aside), output)
            self.assertIn('install rename failed', output)
            self.assertIn('restore rename failed', output)
            self.assertIn('The installation is incomplete', output)
            self.assertNotIn('Nothing was changed', output)

    def test_successful_restore_leaves_previous_package_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            package, output = self.run_failed_install(Path(directory))
            self.assertEqual((package / 'old').read_text(), 'previous package')
            self.assertFalse(list(package.parent.glob(package.name + '.replaced-*')))
            self.assertIn('Nothing was changed; the installed copy was left as it was.', output)
            self.assertNotIn('The installation is incomplete', output)

    def test_failure_without_previous_package_reports_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            package, output = self.run_failed_install(Path(directory), previous=False)
            self.assertFalse(package.exists())
            self.assertIn('Nothing was changed.', output)
            self.assertNotIn('The installation is incomplete', output)


if __name__ == '__main__':
    unittest.main()
