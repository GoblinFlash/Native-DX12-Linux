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
    def test_version_navigation_and_all_numeric_bars(self):
        proposal = core.prepare(issue(), bundle())
        folder = core.record_folder(proposal)
        output = report.render('v0.1.5', [proposal])
        version_page = output[folder.rsplit('/', 1)[0] + '/README.md'].decode()
        self.assertNotIn('Issue #', version_page)
        self.assertEqual(version_page.count('!['), 4)
        for (suite, (name, title)), expected in zip(core.CHARTS.items(), (6, 9, 6, 6)):
            with self.subTest(suite=suite):
                self.assertIn(f'{title}](issue-12/{name})', version_page)
                chart = ET.fromstring(output[folder + '/' + name])
                tips = chart.findall('.//{*}g/{*}title')
                self.assertEqual(len(tips), expected)
                self.assertTrue(all('processes' in tip.text for tip in tips))

    def test_display_threshold_and_lossless_csv(self):
        for raw, shown in ((999999, '999999 ns'), (1000000, '1 ms'),
                           (1005000, '1.01 ms'), (2610752, '2.61 ms')):
            with self.subTest(raw=raw):
                self.assertEqual(core.format_gpu_duration(raw), shown)

        proposal = core.prepare(issue(), bundle())
        native = next(row for row in proposal['measurements']
                      if row['path'] == 'native' and row['case'] == 'affine')
        for row in proposal['measurements']:
            if row['path'] == 'native' and row['case'] == 'affine':
                row['value'] = 2610752
        outputs = core.render(proposal)
        folder = core.record_folder(proposal)
        self.assertEqual(native['unit'], 'GPU_TICKS')
        self.assertEqual(json.loads(outputs[folder + '/record.json']), proposal)
        saved = list(csv.DictReader(io.StringIO(outputs[folder + '/measurements.csv'].decode())))
        matching = [row for row in saved if row['path'] == 'native' and row['case'] == 'affine']
        self.assertEqual({(row['unit'], row['value']) for row in matching}, {('NS', '2610752')})
        self.assertIn(b'2.61 ms', outputs[folder + '/chart.svg'])
        self.assertIn(b'median 2.610752 ms', outputs[folder + '/chart.svg'])
        self.assertIn(b'](chart.svg)', outputs[folder + '/README.md'])

    def test_long_median_uses_compact_bar_label_and_precise_tooltip(self):
        proposal = core.prepare(issue(), bundle())
        step = next(s for s in proposal['run']['steps'] if s['suite'] == 'd4')
        step.update(reported_clock_qualification='QUALIFIED', reported_ns_per_tick_envelope=[0.98, 1.02])
        value = '1000.1234567890123456789'
        for row in proposal['measurements']:
            if (row['suite'], row['path'], row['case']) == ('d4', 'vulkan', '128x128'):
                row['value'] = value
        files = core.render(proposal)
        folder = core.record_folder(proposal)
        svg = ET.fromstring(files[folder + '/d4-chart.svg'])
        self.assertTrue(any(t.text.startswith('≈') for t in svg.findall('.//{*}text')))
        self.assertTrue(any(('median 1 ' + value[1:] + ' ns') in t.text for t in svg.findall('.//{*}g/{*}title')))
        self.assertIn(value.encode(), files[folder + '/summary.csv'])

    def test_historical_context_requires_the_reviewed_archive(self):
        record = ROOT / 'Benchmark Results/NVIDIA/RTX_3060/v0.1.5/issue-10/record.json'
        proposal = json.loads(record.read_bytes())
        context = core.run_context(proposal)
        self.assertEqual(context['reported_os'], 'Ubuntu 26.04.1 LTS')
        self.assertIn(context['archive_url'], record.with_name('README.md').read_text())
        self.assertEqual(context['native_timestamp']['ns_per_tick'], 1)
        self.assertNotIn('reported_os', core.run_context(dict(proposal, bundle_sha256='a' * 64)))
        chart = ET.parse(record.with_name('chart.svg'))
        visible = ' '.join(t.text or '' for t in chart.findall('.//{*}text'))
        for label in ('Native buffers (release): SYSMEM', 'Vulkan buffers: NOT_RECORDED', '189/189 verified'):
            self.assertIn(label, visible)
        ti = ROOT / 'Benchmark Results/NVIDIA/RTX_3060_Ti/v0.1.4/issue-3/chart.svg'
        self.assertIn('Concurrent ONNX workload', ' '.join(t.text or '' for t in ET.parse(ti).findall('.//{*}text')))

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
                self.assertEqual(sum(path.endswith('.svg') for path in output), count)
                self.assertIn('Host/GPU clock check: NOT_QUALIFIED', ''.join(svg.itertext()))

    def test_report_refuses_mixed_versions_and_duplicate_issues(self):
        """A release page cannot silently import another release or duplicate a submission."""
        proposal = core.prepare(issue(), bundle())
        older = core.prepare(issue(version='v0.1.4'), bundle(raw_files('v0.1.4')))
        with self.assertRaisesRegex(report.core.Refused, '^VERSION_MISMATCH$'):
            report.render('v0.1.5', [proposal, older])
        with self.assertRaisesRegex(report.core.Refused, '^VERSION_REPORT_DUPLICATE$'):
            report.render('v0.1.5', [proposal, proposal])

    def test_conflicting_gpu_alone_creates_no_report(self):
        refused = core.prepare(issue(gpu='RTX 3060'), bundle())
        self.assertEqual(refused['reason'], 'GPU_MISMATCH')
        self.assertEqual(report.render('v0.1.5', [refused]), {})

    def test_existing_issue_record_and_csv_are_not_regenerated(self):
        """Re-charting a legacy Issue does not upgrade its record schema or overwrite data."""
        proposal = core.prepare(issue(), bundle())
        outputs = report.render('v0.1.5', [proposal], [12])
        self.assertFalse(any(x.endswith('.svg') for x in outputs))
        self.assertTrue(any(b'issue-12/chart.svg' in data for data in outputs.values()))
        self.assertFalse(any(x.endswith(('/record.json', '.csv', '/memory-backing.json')) for x in outputs))

    def test_same_gpu_release_keeps_distinct_issues_in_one_version_index(self):
        """Separate submissions for one GPU share navigation, not measurements or identity."""
        first = core.prepare(issue(12), bundle())
        second = core.prepare(issue(13), bundle())
        outputs = report.render('v0.1.5', [first, second])
        index = outputs['Benchmark Results/NVIDIA/RTX_3060_Ti/v0.1.5/README.md'].decode()
        for number in (12, 13):
            self.assertIn(f'## Run {number}\n', index)
            self.assertIn(f'Run {number} · Test 3 — K WaveForm](issue-{number}/kw-chart.svg)', index)
            self.assertIn(f' · Run {number}\n'.encode(), outputs['Benchmark Results/v0.1.5-submitted-data.md'])
            self.assertIn('Benchmark Results/NVIDIA/RTX_3060_Ti/v0.1.5/issue-' +
                          str(number) + '/record.json', outputs)

    def test_shared_axis_depends_on_qualification_and_envelope(self):
        proposal = core.prepare(issue(), bundle())
        step = next(s for s in proposal['run']['steps'] if s['suite'] == 'compute')
        for status, envelope, shared in [('NOT_QUALIFIED', None, False),
                                         ('QUALIFIED', [1.01, 1.02], False),
                                         ('QUALIFIED', [0.98, 1.02], True)]:
            step.update(reported_clock_qualification=status, reported_ns_per_tick_envelope=envelope)
            chart = core.render(proposal)[core.record_folder(proposal) + '/chart.svg']
            self.assertEqual(b'independent scale' not in chart, shared)

if __name__ == '__main__':
    unittest.main()
