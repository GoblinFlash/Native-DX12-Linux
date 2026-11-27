"""CPU-only regressions for catalogue-gated Share Results v3 and the draft writer."""
import csv
import io
import json
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from test_community_intake import FakeAPI, bundle, core, issue, load, raw_files, writer


VERSION = 'v9.0.0'  # synthetic catalogue entry, never a published release
DRIVER = '620.73.04'


def rows(raw):
    return list(csv.DictReader(io.StringIO(raw.decode())))


def v3_files(identity):
    files = raw_files()
    doc = json.loads(files['run.json'])
    doc.update(schema=core.SHARE_V3, units={'native': 'NS', 'vulkan': 'NS'},
               identity=dict(identity, schema=core.SHARE_V3, status='VERIFIED'))
    doc['identity'].pop('share_schema', None)
    doc['gpu'].update(model='NVIDIA GeForce RTX 5060 Ti', pci='10de:2d04', driver=DRIVER)
    doc['run']['clocks'] = {'mode': 'LOCK_REQUESTED', 'core_mhz': 2400, 'memory_mhz': 14001}
    doc['run']['requested'] = list(core.V3_SUITES)
    doc['run']['completed'] = list(core.V3_SUITES)

    count = lambda n: dict(expected=n, completed=n, verified=n, failed=0, held=0, not_run=0, unknown=0)
    process = rows(files['processes.csv'])
    for row in process:
        if row['path'] == 'native':
            row['submission'] = 'RETAINED_SESSION'
    keys = {(row['suite'], row['case'], row['variant'], row['path'], int(row['repeat'])) for row in process}
    q8 = set((suite, case, 'Q8PL', path, repeat) for suite, case, arm, path, repeat in keys if arm == 'D4')
    for suite, case, variant, path, repeat in sorted(q8 | set().union(*(
            core.v3_schedule(suite, set(), True) for suite in core.V3_FRAME_SUITES))):
        process.append(dict(suite=suite, case=case, variant=variant, path=path, repeat=repeat,
                            submission='RETAINED_SESSION' if path == 'native' else 'NOT_RECORDED',
                            completion='CLOSED' if path == 'native' else 'EXECUTED',
                            correctness='BOUNDED_CORRECTNESS_VERIFIED', timing='OK', kernel_records=0,
                            status='VERIFIED'))
    files['processes.csv'] = core.csv_text(process, core.PROCESS_COLUMNS)
    doc['steps'] = [dict(suite=suite, status='COMPLETE',
                         counts=count(sum(row['suite'] == suite for row in process)),
                         clock_check=dict(status='QUALIFIED', relative_rate_range=[0.98, 1.02]))
                    for suite in core.V3_SUITES]
    doc['totals'] = count(len(process))
    files['run.json'] = core.json_bytes(doc)

    for name in list(files):
        if name.endswith('.csv') and '-vulkan-' not in name and name != 'processes.csv':
            # CSV fixtures use the desktop v3 exact-ns headers and code placement.
            records = [{key.replace('_ticks', '_ns'): value for key, value in row.items()}
                       for row in rows(files[name])]
            for row in records:
                row.update(native_code='VRAM_BUFFER', telemetry='BEFORE_AFTER')
                if name == 'samples.csv' and row['case'] == 'parallel-sort':
                    row['work_ns'] = 2610752
            if name == 'test1-d4-processes.csv':
                records.extend([dict(row, arm='Q8PL') for row in records if row['arm'] == 'D4'])
            files[name] = core.csv_text(records, list(records[0]))
    for suite, (prefix, _, _) in core.V3_FRAME_SUITES.items():
        for path in ('native', 'vulkan'):
            native = path == 'native'
            records = []
            for row in process:
                if (row['suite'], row['path']) != (suite, path):
                    continue
                records.append(dict(test=suite, shape=row['case'], arm=row['variant'] if native else 'vulkan',
                    round=row['repeat']-1, process_median_ns='1000000.5' if native else '2345.125',
                    first_ns='1001', warmup_ns='1002', empty_before_ns='16', empty_after_ns='32',
                    clock_mode='LOCK_REQUESTED', telemetry='OFF',
                    **({'native_code': 'VRAM_BUFFER'} if native else {})))
            if records:
                name = prefix + ('-processes.csv' if native else '-vulkan-processes.csv')
                files[name] = core.csv_text(records, list(records[0]))
    return files


class ShareV3Tests(unittest.TestCase):
    def setUp(self):
        trusted = core.catalog()
        self.identity = dict(trusted['v0.1.5'], public_version=VERSION, package_id='v21-r27',
                             share_schema=core.SHARE_V3)
        self.files = v3_files(self.identity)
        self.source = issue(number=1200, gpu='RTX 5060 Ti', version=VERSION)
        self.source['body'] = self.source['body'].replace('620.70.06', DRIVER)
        trusted[VERSION] = self.identity
        self.enterContext(patch.object(core, 'catalog', return_value=trusted))

    def prepared(self):
        return core.prepare(self.source, bundle(self.files))

    def test_benchmark_v3_round_trips_through_real_draft_writer(self):
        proposal = self.prepared()
        self.assertEqual(proposal['state'], 'DATA_READY', proposal['reason'])
        self.assertEqual(proposal['run']['counts']['verified'], 236)
        self.assertEqual(proposal['run']['clocks'], 'lock-requested')
        self.assertEqual({r['unit'] for r in proposal['measurements']}, {'NS'})
        self.assertNotIn('SEPARATE_TIMING_UNITS', proposal['warnings'])
        self.assertEqual(core.validate_proposal(core.load_json(core.json_bytes(proposal))), proposal)
        api = FakeAPI(current=self.source)
        published = writer.publish(proposal, api, 1200)
        self.assertEqual(len(api.prs), 1)
        self.assertTrue(api.prs[0]['draft'])
        data = published['files']
        folder = core.record_folder(proposal)
        self.assertIn(folder + '/chart.svg', data)
        output = core.render(proposal)
        self.assertIn(b'2.61 ms', output[folder + '/chart.svg'])
        self.assertIn(b'2610752', output[folder + '/measurements.csv'])
        ET.fromstring(output[folder + '/chart.svg'])
        self.assertIn(b'Host/GPU clock check: QUALIFIED', output[folder + '/chart.svg'])
        report = load('community_version_report')
        report.core = core
        combined = report.render(VERSION, [proposal])[core.ROOT + VERSION + '-submitted-data.md']
        self.assertIn(b'Q8PL', output[folder + '/d4-chart.svg'])
        for title in (b'FWHT', b'Sponza', b'Neural Grid'):
            self.assertIn(title, combined)

    def test_v3_release_without_catalogue_entry_is_imported_and_legacy_release_refused(self):
        self.assertNotIn('PACKAGE_NOT_CATALOGUED', self.prepared()['warnings'])
        uncatalogued = {key: value for key, value in core.catalog().items() if key != VERSION}
        with patch.object(core, 'catalog', return_value=uncatalogued):
            proposal = self.prepared()
            self.assertEqual((proposal['state'], proposal['reason']), ('DATA_READY', 'OK'))
            self.assertIn('PACKAGE_NOT_CATALOGUED', proposal['warnings'])
            self.assertEqual(core.validate_proposal(core.load_json(core.json_bytes(proposal))), proposal)
            forged = dict(proposal, warnings=[w for w in proposal['warnings'] if w != 'PACKAGE_NOT_CATALOGUED'])
            with self.assertRaisesRegex(core.Refused, '^PROPOSAL_SCHEMA$'):
                core.validate_proposal(forged)
            self.assertIn('/' + VERSION + '/issue-1200', core.record_folder(proposal))
        source = issue(gpu='RTX 5060 Ti', version='v0.1.5')
        self.assertEqual(core.prepare(source, bundle(self.files))['reason'], 'SCHEMA')

    def test_v3_refuses_legacy_units_and_marks_another_build_or_installation(self):
        run = json.loads(self.files['run.json'])
        run['units']['native'] = 'GPU_TICKS'
        self.files['run.json'] = core.json_bytes(run)
        self.assertEqual(self.prepared()['reason'], 'UNITS_MISMATCH')
        run['units']['native'] = 'NS'
        run['identity'].update(manifest_sha256='0' * 64, status='INSTALLED')
        self.files['run.json'] = core.json_bytes(run)
        proposal = self.prepared()
        self.assertEqual((proposal['state'], proposal['reason']), ('DATA_READY', 'OK'))
        self.assertIn('PACKAGE_NOT_CATALOGUED', proposal['warnings'])
        self.assertEqual(core.validate_proposal(core.load_json(core.json_bytes(proposal))), proposal)
        for status in ('UNKNOWN', 'MODIFIED', None):
            run['identity']['status'] = status
            self.files['run.json'] = core.json_bytes(run)
            with self.subTest(status=status):
                self.assertEqual(self.prepared()['reason'], 'IDENTITY_MISMATCH')

    def test_v3_takes_any_driver_version_named_by_both_issue_and_archive(self):
        run = json.loads(self.files['run.json'])
        run['gpu']['driver'] = '580.105.08'
        self.files['run.json'] = core.json_bytes(run)
        self.assertEqual(self.prepared()['reason'], 'DRIVER_MISMATCH')
        self.source['body'] = self.source['body'].replace(DRIVER, '580.105.08, NVIDIA Open kernel module')
        proposal = core.validate_proposal(self.prepared())
        self.assertEqual((proposal['state'], proposal['driver']), ('DATA_READY', '580.105.08'))

    def test_v3_case_added_by_a_later_release_is_imported_and_charted(self):
        def add_case(name, repeats):
            run = json.loads(self.files['run.json'])
            process = rows(self.files['processes.csv'])
            template = next(row for row in process if row['suite'] == 'compute' and row['path'] == 'native')
            process += [dict(template, case=name, repeat=str(r)) for r in repeats]
            samples = rows(self.files['samples.csv'])
            samples += [dict(samples[0], case=name, attempt=str(r)) for r in repeats]
            compute = next(step for step in run['steps'] if step['suite'] == 'compute')
            for counts in (run['totals'], compute['counts']):
                for key in ('expected', 'completed', 'verified'):
                    counts[key] += len(repeats)
            return dict(self.files, **{'run.json': core.json_bytes(run),
                                       'processes.csv': core.csv_text(process, core.PROCESS_COLUMNS),
                                       'samples.csv': core.csv_text(samples, list(samples[0]))})

        source = self.files
        self.files = add_case('parallel-sort4096-24', range(1, 8))
        proposal = self.prepared()
        self.assertEqual((proposal['state'], proposal['reason']), ('DATA_READY', 'OK'))
        self.assertEqual(proposal['run']['counts']['verified'], 243)
        self.assertEqual(core.validate_proposal(core.load_json(core.json_bytes(proposal))), proposal)
        chart = core.render(proposal)[core.record_folder(proposal) + '/chart.svg']
        ET.fromstring(chart)
        self.assertIn(b'parallel-sort4096-24', chart)
        for name, repeats in (('parallel-sort4096-24', range(1, 7)), ('Sort 24', range(1, 8)),
                              ('../sort', range(1, 8))):
            self.files = source
            self.files = add_case(name, repeats)
            with self.subTest(name=name, repeats=len(repeats)):
                self.assertEqual(self.prepared()['reason'], 'PROCESS_SCHEDULE')

    def test_v3_refuses_missing_repeat_and_contradictory_not_run(self):
        process = rows(self.files['processes.csv'])
        self.files['processes.csv'] = core.csv_text(process[:-1], core.PROCESS_COLUMNS)
        self.assertEqual(self.prepared()['reason'], 'PROCESS_SCHEDULE')
        process[0].update(status='NOT_RUN', completion='NOT_RUN')
        self.files['processes.csv'] = core.csv_text(process, core.PROCESS_COLUMNS)
        self.assertEqual(self.prepared()['reason'], 'PROCESS_CONTRADICTION')

    def test_v3_does_not_accept_a_vulkan_retained_session(self):
        process = rows(self.files['processes.csv'])
        next(row for row in process if row['path'] == 'vulkan')['submission'] = 'RETAINED_SESSION'
        self.files['processes.csv'] = core.csv_text(process, core.PROCESS_COLUMNS)
        self.assertEqual(self.prepared()['reason'], 'ENUM')

    def test_sponza_only_results_show_the_two_measured_bars(self):
        run = json.loads(self.files['run.json'])
        run['run']['requested'] = run['run']['completed'] = ['sponza']
        run['steps'] = [step for step in run['steps'] if step['suite'] == 'sponza']
        run['totals'] = run['steps'][0]['counts']
        process = [row for row in rows(self.files['processes.csv']) if row['suite'] == 'sponza']
        self.files = {
            'run.json': core.json_bytes(run),
            'processes.csv': core.csv_text(process, core.PROCESS_COLUMNS),
            'test5-sponza-processes.csv': self.files['test5-sponza-processes.csv'],
        }
        self.source['body'] = self.source['body'].replace('Full test completed', 'Selected tests completed')
        proposal = self.prepared()
        self.assertEqual(proposal['state'], 'DATA_READY', proposal['reason'])
        report = load('community_version_report')
        report.core = core
        outputs = report.render(VERSION, [proposal])
        self.assertNotIn(core.record_folder(proposal) + '/chart.svg', outputs)
        index = core.ROOT + proposal['claimed_gpu'] + '/' + VERSION + '/README.md'
        self.assertIn(b'](issue-1200/sponza-chart.svg)', outputs[index])
        self.assertEqual(outputs[index].count(b'!['), 1)
        svg = ET.fromstring(outputs[core.record_folder(proposal) + '/sponza-chart.svg'])
        self.assertEqual(len(svg.findall('.//{*}g/{*}title')), 2)
        self.assertIn('1 ms', ''.join(svg.itertext()))

    def test_unverified_scheduled_q8pl_remains_visible_without_times(self):
        archive = json.loads(self.files['run.json'])
        archive['run']['overall'] = 'PARTIAL'
        archive['run']['completed'].remove('d4')
        d4 = next(step for step in archive['steps'] if step['suite'] == 'd4')
        d4['status'] = 'PARTIAL'
        processes = rows(self.files['processes.csv'])
        failed = [row for row in processes if row['variant'] == 'Q8PL']
        for row in failed:
            row.update(status='FAIL', correctness='FAILED', timing='NOT_RECORDED')
        for counts in (archive['totals'], d4['counts']):
            counts['verified'] -= len(failed)
            counts['failed'] += len(failed)
        name = 'test1-d4-processes.csv'
        measurements = [row for row in rows(self.files[name]) if row['arm'] != 'Q8PL']
        self.files[name] = core.csv_text(measurements, measurements[0])
        self.files['run.json'] = core.json_bytes(archive)
        self.files['processes.csv'] = core.csv_text(processes, core.PROCESS_COLUMNS)
        proposal = self.prepared()
        self.assertEqual(proposal['state'], 'DATA_READY', proposal['reason'])
        report = load('community_version_report')
        report.core = core
        output = report.render(VERSION, [proposal])
        svg = ET.fromstring(output[core.record_folder(proposal) + '/d4-chart.svg'])
        self.assertEqual(len(svg.findall('.//{*}g/{*}title')), 9)
        self.assertEqual(sum(t.text == 'not measured' for t in svg.findall('.//{*}text')), 3)
        self.assertIn('Q8PL', ''.join(svg.itertext()))


if __name__ == '__main__':
    unittest.main()
