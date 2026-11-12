"""CPU regressions for release-separated reports using the published v0.1.4 chart layout."""
import csv
import io
import json
import importlib.util
import unittest
import xml.etree.ElementTree as ET

from test_community_intake import ROOT, bundle, core, issue, raw_files

SPEC = importlib.util.spec_from_file_location('version_report', ROOT / '.github/scripts/community_version_report.py')
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class VersionReportTests(unittest.TestCase):
    def test_v15_has_its_own_gpu_table_and_full_report_link(self):
        """The v0.1.5 overview must match the existing table-and-report navigation."""
        text = (ROOT / 'Experiment Results/README.md').read_text()
        section = text.split('## Community Benchmark Data — v0.1.5\n', 1)[1].split(
            '## Community Benchmark Data — v0.1.4\n', 1)[0]
        self.assertIn('| GPU | Exported process status | GPU tick-to-ns model | Important limitation |', section)
        for gpu in ('RTX 3060', 'RTX 4060', 'RTX 4090'):
            self.assertIn('[' + gpu + ']', section)
        self.assertIn('Community/v0.1.5-submitted-data.md', section)

    def test_new_numeric_chart_reuses_published_four_panel_design(self):
        """New intake charts use the actual prior release's axes, colors and type styles."""
        files = raw_files()
        run = json.loads(files['run.json'])
        for step in run['steps']:
            step['clock_check'] = {'status': 'QUALIFIED', 'envelope_ns_per_tick': [0.98, 1.02]}
        files['run.json'] = core.json_bytes(run)
        output = core.render(core.prepare(issue(), bundle(files)))
        svg = ET.fromstring(next(v for k, v in output.items() if k.endswith('/chart.svg')))
        ns = '{http://www.w3.org/2000/svg}'
        axes = [x.get('id') for x in svg.iter(ns + 'g') if x.get('id', '').startswith('axes_')]
        self.assertEqual(axes, ['axes_1', 'axes_2', 'axes_3', 'axes_4'])
        fills = [x.get('style') for x in svg.iter(ns + 'path')]
        self.assertEqual(fills.count('fill: #0c80bd'), 5)  # four panels and legend
        self.assertEqual(fills.count('fill: #ef7100'), 5)
        text = ''.join(svg.itertext())
        for label in ('Compute · Affine', 'D4 · 128×128', 'K uint4 · 64×64',
                      'WaveForm uint4 · 64×64', 'What is being compared?', 'Scope and limitations'):
            self.assertIn(label, text)
        self.assertIn('CLOCK QUALIFIED 4/4 · conditional tick-to-ns model', text)

    def test_chart_driver_label_does_not_infer_driver_type(self):
        """Both published layouts label numeric driver versions without asserting Open."""
        for driver in ('615.78.08', '620.70.06'):
            for qualified in (False, True):
                with self.subTest(driver=driver, qualified=qualified):
                    files = raw_files()
                    run = json.loads(files['run.json'])
                    run['gpu']['driver'] = driver
                    if qualified:
                        for step in run['steps']:
                            step['clock_check'] = {'status': 'QUALIFIED', 'envelope_ns_per_tick': [0.98, 1.02]}
                    files['run.json'] = core.json_bytes(run)
                    source = issue();source['body'] = source['body'].replace('620.70.06', driver)
                    proposal = core.validate_proposal(core.prepare(source, bundle(files)))
                    output = core.render(proposal)
                    svg = ET.fromstring(next(v for k, v in output.items() if k.endswith('/chart.svg')))
                    text = ''.join(svg.itertext())
                    self.assertIn('NVIDIA driver ' + driver, text)
                    self.assertNotIn('NVIDIA Open', text)

    def test_unqualified_clock_uses_actual_requested_step_count(self):
        """Selected one-to-four-suite exports retain their actual clock denominator."""
        for count in (1, 2, 3, 4):
            with self.subTest(steps=count):
                files = raw_files()
                run = json.loads(files['run.json'])
                requested = list(core.SUITES)[:count]
                run['run'].update(requested=requested, completed=requested)
                run['steps'] = [step for step in run['steps'] if step['suite'] in requested]
                rows = [row for row in csv.DictReader(io.StringIO(files['processes.csv'].decode()))
                        if row['suite'] in requested]
                run['totals'].update(expected=len(rows), completed=len(rows), verified=len(rows))
                files['processes.csv'] = core.csv_text(rows, core.PROCESS_COLUMNS)
                files['run.json'] = core.json_bytes(run)
                for suite, names in {
                    'compute': ('samples.csv', 'compute-vulkan-samples.csv'),
                    'd4': ('test1-d4-processes.csv', 'test1-d4-vulkan-processes.csv'),
                    'k': ('test2-k-processes.csv', 'test2-k-vulkan-processes.csv'),
                    'kw': ('test3-kw-processes.csv', 'test3-kw-vulkan-processes.csv'),
                }.items():
                    if suite not in requested:
                        for name in names:
                            del files[name]
                source = issue()
                source['body'] = source['body'].replace('Full test completed', 'Selected tests completed')
                proposal = core.validate_proposal(core.prepare(source, bundle(files)))
                self.assertEqual(proposal['state'], 'DATA_READY')
                self.assertEqual(len(proposal['run']['steps']), count)
                output = core.render(proposal)
                svg = ET.fromstring(next(v for k, v in output.items() if k.endswith('/chart.svg')))
                self.assertIn(f'CLOCK: 0/{count} reported QUALIFIED — separate timer units',
                              ''.join(svg.itertext()))

    def test_report_refuses_mixed_versions_and_duplicate_issues(self):
        """A release page cannot silently import another release or duplicate a submission."""
        proposal = core.prepare(issue(), bundle())
        older = core.prepare(issue(version='v0.1.4'), bundle(raw_files('v0.1.4')))
        with self.assertRaisesRegex(report.core.Refused, '^VERSION_MISMATCH$'):
            report.render('v0.1.5', [proposal, older])
        with self.assertRaisesRegex(report.core.Refused, '^VERSION_REPORT_DUPLICATE$'):
            report.render('v0.1.5', [proposal, proposal])

    def test_conflicting_gpu_is_listed_without_measurements_or_chart(self):
        """A refused archive may explain the conflict but cannot become GPU benchmark data."""
        refused = core.prepare(issue(gpu='RTX 3060'), bundle())
        self.assertEqual(refused['reason'], 'GPU_MISMATCH')
        outputs = report.render('v0.1.5', [refused])
        self.assertEqual(list(outputs), ['Experiment Results/Community/v0.1.5-submitted-data.md'])
        text = next(iter(outputs.values())).decode()
        self.assertIn('GPU_MISMATCH', text)
        self.assertIn('No measurements or chart', text)
        self.assertNotIn('![', text)
        self.assertNotIn('189/189 VERIFIED', text)

    def test_existing_issue_record_and_csv_are_not_regenerated(self):
        """Re-charting a legacy Issue does not upgrade its record schema or overwrite data."""
        proposal = core.prepare(issue(), bundle())
        outputs = report.render('v0.1.5', [proposal], [12])
        self.assertTrue(any(x.endswith('/issue-12/chart.svg') for x in outputs))
        self.assertFalse(any(x.endswith(('/record.json', '.csv', '/memory-backing.json')) for x in outputs))

    def test_same_gpu_release_keeps_distinct_issues_in_one_version_index(self):
        """Separate submissions for one GPU share navigation, not measurements or identity."""
        first = core.prepare(issue(12), bundle())
        second = core.prepare(issue(13), bundle())
        outputs = report.render('v0.1.5', [first, second])
        index = outputs['Experiment Results/Community/NVIDIA/RTX_3090/v0.1.5/README.md'].decode()
        for number in (12, 13):
            self.assertIn('#rtx-3090--issue-' + str(number), index)
            self.assertIn('Experiment Results/Community/NVIDIA/RTX_3090/v0.1.5/issue-' +
                          str(number) + '/record.json', outputs)

    def test_unqualified_clock_keeps_published_separate_raw_unit_panels(self):
        """The old unqualified design retains both data series without a shared time axis."""
        output = core.render(core.prepare(issue(), bundle()))
        root = ET.fromstring(next(v for k, v in output.items() if k.endswith('/chart.svg')))
        ns = '{http://www.w3.org/2000/svg}'
        self.assertEqual([x.get('id') for x in root.iter(ns + 'g')
                          if x.get('id', '').startswith('axes_')], ['axes_1', 'axes_2'])
        text = ''.join(root.itertext())
        self.assertIn('Native — GPU timer ticks', text)
        self.assertIn('Vulkan reference — nanoseconds', text)
        self.assertIn('Do not compare these panels', text)


if __name__ == '__main__':
    unittest.main()
