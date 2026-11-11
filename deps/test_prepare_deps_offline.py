#!/usr/bin/env python3
"""CPU regressions for dependency-tool isolation; no build or network activity.

Run with python3 -I -B and TMPDIR set to a disposable test-owned directory.
An optional first argument selects another prepare_deps.py for RED/GREEN runs.
The trusted launcher below is a routing double, not a real network namespace.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SUBJECT = Path(__file__).with_name('prepare_deps.py')
if __name__ == '__main__' and len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
    SUBJECT = Path(sys.argv.pop(1)).resolve()
spec = importlib.util.spec_from_file_location('prepare_deps_under_test', SUBJECT)
deps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deps)


class OfflineBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='deps-offline-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.safe = self.root / 'trusted'
        self.extra = self.root / 'extra'
        self.safe.mkdir()
        self.extra.mkdir()
        self.events = self.root / 'events.jsonl'
        self.marker = self.root / 'tool-ran'
        self.unshare = self.write_program(self.safe / 'unshare',
            'import json, os, sys\n'
            f'with open({str(self.events)!r}, "a") as log:\n'
            '    log.write(json.dumps(sys.argv[1:]) + "\\n")\n'
            'if sys.argv[1:] == ["--version"]:\n'
            '    print("trusted-unshare 1")\n'
            '    sys.exit(0)\n'
            'if sys.argv[1:3] != ["-rn", "--"]:\n'
            '    sys.exit(91)\n'
            'os.environ["TEST_OFFLINE_WRAPPED"] = "1"\n'
            'os.execvpe(sys.argv[3], sys.argv[3:], os.environ)\n')
        self.tool = self.write_program(self.extra / 'test-compiler',
            'import os, sys\n'
            f'with open({str(self.marker)!r}, "a") as output:\n'
            '    output.write(os.environ.get("TEST_OFFLINE_WRAPPED", "host") + "\\n")\n'
            'print("test-compiler 1")\n')
        self.spoof_marker = self.root / 'spoof-ran'
        self.write_program(self.extra / 'unshare',
            'import os, sys\n'
            f'open({str(self.spoof_marker)!r}, "w").write("spoof")\n'
            'if sys.argv[1:] == ["--version"]:\n'
            '    print("spoof-unshare 1")\n'
            'else:\n'
            '    os.execvpe(sys.argv[3], sys.argv[3:], os.environ)\n')
        patcher = mock.patch.object(deps, 'SAFE_PATH', str(self.safe))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_program(self, path, body):
        path.write_text('#!' + sys.executable + '\n' + body)
        path.chmod(0o755)
        return path

    def runner(self, offline=True):
        root = self.root / 'build'
        root.mkdir(exist_ok=True)
        return deps.Runner(root, 1, offline, [str(self.extra)])

    def discover(self, runner, tools=None):
        with mock.patch.object(deps, 'TOOLS', tools or [('cc', 'test-compiler')]):
            return deps.toolchain(runner if 'runner' in deps.toolchain.__code__.co_varnames[:1] else runner.env)

    def test_offline_version_probe_reaches_trusted_launcher(self):
        tools, missing = self.discover(self.runner())
        self.assertEqual(missing, [])
        self.assertEqual(tools['cc']['version'], ['test-compiler 1'])
        self.assertEqual(self.marker.read_text(), '1\n', 'version probe ran on host')
        self.assertIn(['-rn', '--', str(self.tool), '--version'],
                      [json.loads(line) for line in self.events.read_text().splitlines()])
        self.assertFalse(self.spoof_marker.exists())

    def test_offline_build_ignores_extra_path_unshare(self):
        runner = self.runner()
        self.assertEqual(runner.run('build', [self.tool], capture=True), b'test-compiler 1\n')
        self.assertEqual(self.marker.read_text(), '1\n', 'extra-path launcher bypassed isolation')
        self.assertFalse(self.spoof_marker.exists())

    def test_launcher_is_resolved_once_before_path_changes(self):
        runner = self.runner()
        with mock.patch.object(deps, 'SAFE_PATH', str(self.extra)), \
             mock.patch.object(deps.shutil, 'which', side_effect=AssertionError('launcher re-resolved')):
            runner.run('build', [self.tool])
        self.assertEqual(self.marker.read_text(), '1\n')
        self.assertFalse(self.spoof_marker.exists())

    def test_missing_trusted_launcher_refuses_before_tool_execution(self):
        self.unshare.unlink()
        with self.assertRaisesRegex(deps.Fail, '^UNSHARE_MISSING$'):
            self.runner()
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.spoof_marker.exists())

    def test_failed_isolation_refuses_probe_without_running_tool(self):
        self.write_program(self.unshare, 'import sys\nsys.exit(73)\n')
        with self.assertRaisesRegex(deps.Fail, '^TOOL_VERSION_FAILED:test-compiler$'):
            self.discover(self.runner())
        self.assertFalse(self.marker.exists(), 'tool ran after isolation failed')
        self.assertFalse(self.spoof_marker.exists())

    def test_failed_isolation_refuses_build_and_records_failure(self):
        self.write_program(self.unshare, 'import sys\nsys.exit(73)\n')
        runner = self.runner()
        with self.assertRaisesRegex(deps.Fail, '^PHASE_FAILED:build$'):
            runner.run('build', [self.tool])
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.spoof_marker.exists())
        self.assertEqual(json.loads((runner.root / 'commands.json').read_text())[0]['rc'], 73)

    def test_toolchain_records_trusted_unshare_identity(self):
        tools, missing = self.discover(self.runner(), [('unshare', 'unshare')])
        self.assertEqual(missing, [])
        self.assertEqual(tools['unshare']['path'], str(self.unshare.resolve()))
        self.assertEqual(tools['unshare']['sha256'], deps.sha256_file(self.unshare))
        self.assertEqual(tools['unshare']['version'], ['trusted-unshare 1'])
        self.assertFalse(self.spoof_marker.exists())

    def test_online_build_and_probe_preserve_host_execution(self):
        self.unshare.unlink()
        runner = self.runner(offline=False)
        runner.run('build', [self.tool], capture=True)
        tools, missing = self.discover(runner)
        self.assertEqual(missing, [])
        self.assertEqual(tools['cc']['version'], ['test-compiler 1'])
        self.assertEqual(self.marker.read_text(), 'host\nhost\n')
        self.assertFalse(self.events.exists())
        self.assertFalse(self.spoof_marker.exists())

    def test_stderr_version_and_missing_tool_are_preserved(self):
        self.write_program(self.tool, 'import sys\nprint("stderr version", file=sys.stderr)\n')
        tools, missing = self.discover(self.runner(), [('cc', 'test-compiler'), ('absent', 'not-installed')])
        self.assertEqual(tools['cc']['version'], ['stderr version'])
        self.assertEqual(missing, ['not-installed'])

    def test_cmd_build_uses_runner_for_discovery(self):
        package = self.root / 'package'
        package.mkdir()
        args = type('Args', (), dict(package_root=str(package), cache=str(self.root / 'cache'),
            build_root=str(self.root / 'build'), jobs=1, targets='rtx',
            extra_path=[str(self.extra)], offline=True))()
        with mock.patch.object(deps, 'load_lock', return_value=({'sources': []}, {}, 'test-lock')), \
             mock.patch.object(deps, 'TOOLS', [('cc', 'test-compiler'), ('missing', 'not-installed')]), \
             mock.patch.object(deps, 'apt_report', return_value=[]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(deps.cmd_build(args), 1)
        receipt = json.loads((self.root / 'build/deps.json').read_text())
        self.assertEqual(receipt['status'], 'FAIL:TOOLS_MISSING:not-installed')
        self.assertEqual(receipt['toolchain']['cc']['version'], ['test-compiler 1'])
        self.assertEqual(self.marker.read_text(), '1\n', 'cmd_build probe ran on host')
        self.assertFalse(self.spoof_marker.exists())

    def test_cmd_build_missing_launcher_records_refusal(self):
        self.unshare.unlink()
        package = self.root / 'package'
        package.mkdir()
        args = type('Args', (), dict(package_root=str(package), cache=str(self.root / 'cache'),
            build_root=str(self.root / 'build'), jobs=1, targets='rtx',
            extra_path=[str(self.extra)], offline=True))()
        with mock.patch.object(deps, 'load_lock', return_value=({'sources': []}, {}, 'test-lock')), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(deps.cmd_build(args), 1)
        receipt = json.loads((self.root / 'build/deps.json').read_text())
        self.assertEqual(receipt['status'], 'FAIL:UNSHARE_MISSING')
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.spoof_marker.exists())


if __name__ == '__main__':
    unittest.main()
