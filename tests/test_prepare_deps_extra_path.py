"""CPU controls for the dependency builder's explicit tool directories."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SUBJECT = Path(__file__).resolve().parents[1] / 'deps/prepare_deps.py'
PROBE = 'ndx12-extra-path-test-tool'
MISSING = 'ndx12-deliberately-missing-build-stop'


class ExtraPathTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('deps_path_subject', SUBJECT)
        self.subject = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.subject)
        temp = tempfile.TemporaryDirectory(prefix='deps-path-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ('package', 'cache'):
            (self.root / name).mkdir()
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.root)

    def write_tool(self, directory, marker, origin):
        tool = directory / PROBE
        tool.write_text('#!/usr/bin/python3 -I\nfrom pathlib import Path\n'
                        'Path(' + repr(str(marker)) + ').write_text(' + repr(origin) + ')\n'
                        'print("bounded fixture version")\n')
        tool.chmod(0o755)

    def run_build(self, extra, name='build'):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ['build', '--package-root', str(self.root / 'package'),
                '--cache', str(self.root / 'cache'), '--build-root', str(self.root / name),
                '--targets', 'rtx']
        for path in extra:
            argv += ['--extra-path', str(path)]
        with mock.patch.object(self.subject, 'load_lock',
                               return_value=({'apt_packages': []}, {}, 'synthetic-lock')), \
                mock.patch.object(self.subject, 'apt_report', return_value=[]), \
                mock.patch.object(self.subject, 'TOOLS', [('probe', PROBE), ('stop', MISSING)]), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = self.subject.main(argv)
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_runner_rejects_separator_before_creating_its_output(self):
        selected = self.root / ('selected' + os.pathsep + 'relative')
        selected.mkdir()
        build = self.root / 'build'
        build.mkdir()
        with self.assertRaisesRegex(self.subject.Fail, '^EXTRA_PATH_SEPARATOR$'):
            self.subject.Runner(build, 1, False, [str(selected)])
        self.assertEqual(list(build.iterdir()), [])

    def test_cli_rejects_existing_separator_directory_before_any_probe(self):
        relative = self.root / 'unselected-relative'
        relative.mkdir()
        marker = self.root / 'unexpected-execution'
        self.write_tool(relative, marker, 'relative tool ran')
        self.write_tool(self.root, marker, 'current-directory tool ran')
        for index, suffix in enumerate(('unselected-relative', '')):
            with self.subTest(suffix=suffix):
                selected = self.root / ('selected' + os.pathsep + suffix)
                selected.mkdir()
                self.assertTrue(selected.is_absolute() and selected.is_dir())
                name = 'build-' + str(index)
                rc, stdout, stderr = self.run_build([selected], name)
                self.assertEqual(rc, 1)
                self.assertEqual(stderr, '')
                self.assertEqual(json.loads(stdout)['status'], 'FAIL:EXTRA_PATH_SEPARATOR')
                self.assertFalse(marker.exists())
                receipt = json.loads((self.root / name / 'deps.json').read_text())
                self.assertEqual(receipt['status'], 'FAIL:EXTRA_PATH_SEPARATOR')

    def test_legal_directory_with_spaces_runs_only_the_selected_tool(self):
        selected = self.root / 'selected tools'
        selected.mkdir()
        marker = self.root / 'selected-execution'
        self.write_tool(selected, marker, 'selected tool ran')
        rc, stdout, stderr = self.run_build([selected])
        self.assertEqual(rc, 1)  # The missing-tool sentinel stops before a build.
        self.assertEqual(stderr, '')
        self.assertTrue(json.loads(stdout)['status'].startswith('FAIL:TOOLS_MISSING:'))
        self.assertEqual(marker.read_text(), 'selected tool ran')
        result = json.loads((self.root / 'build/deps.json').read_text())
        invoked = Path(result['toolchain']['probe']['path'])
        self.assertTrue(invoked.is_absolute())
        self.assertEqual(invoked, selected / PROBE)

    def test_omitting_extra_path_does_not_search_the_current_directory(self):
        marker = self.root / 'unexpected-execution'
        self.write_tool(self.root, marker, 'current-directory tool ran')
        rc, stdout, stderr = self.run_build([])
        self.assertEqual(rc, 1)
        self.assertEqual(stderr, '')
        self.assertTrue(json.loads(stdout)['status'].startswith('FAIL:TOOLS_MISSING:'))
        self.assertFalse(marker.exists())
        result = json.loads((self.root / 'build/deps.json').read_text())
        self.assertNotIn('probe', result['toolchain'])

    def test_relative_directory_keeps_its_distinct_cli_refusal(self):
        relative = self.root / 'relative-tools'
        relative.mkdir()
        marker = self.root / 'unexpected-execution'
        self.write_tool(relative, marker, 'relative tool ran')
        rc, stdout, stderr = self.run_build(['relative-tools'])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(stderr)['status'], 'FAIL:EXTRA_PATH')
        self.assertEqual(stdout, '')
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
