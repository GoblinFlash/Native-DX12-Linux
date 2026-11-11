"""Deterministic CPU tests. All API writes use a stateful fake, never GitHub."""
import copy
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / '.github/scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


writer = load('community_publish')
core = writer.intake


def issue(number=12, gpu='RTX 3090', version='v0.1.5'):
    return {'number': number, 'title': '[Results] '+gpu, 'state': 'open',
            'updated_at': '2026-11-11T00:00:00Z', 'author_association': 'NONE',
            'labels': [{'name': 'benchmark:submission'}, {'name': 'benchmark:intake-approved'}],
            'body': ('### GPU model\n\n'+gpu+'\n\n### Benchmark version\n\n'+version+
                '\n\n### GPU driver version\n\n620.70.06\n\n### Run status\n\nFull test completed\n\n'
                '### Results attachment or summary\n\n'
                'https://github.com/user-attachments/files/123/share-results-'+version+'.tar.gz\n\n'
                '### Additional details (optional)\n\nReview contention in the source Issue.\n')}


def raw_files(version='v0.1.5', gpu='NVIDIA GeForce RTX 3090'):
    processes = []
    for suite in core.SUITES:
        for s, case, variant, path, repeat in sorted(core.schedule(suite)):
            processes.append({'suite': s, 'case': case, 'variant': variant, 'path': path,
                'repeat': repeat, 'submission': 'RETURNED' if path == 'native' else 'NOT_RECORDED',
                'completion': 'CLOSED' if path == 'native' else 'EXECUTED',
                'correctness': 'BOUNDED_CORRECTNESS_VERIFIED', 'timing': 'OK',
                'kernel_records': 0, 'status': 'VERIFIED'})
    def counts(rows):
        return {'expected': len(rows), 'completed': len(rows), 'verified': len(rows),
                'failed': 0, 'held': 0, 'not_run': 0, 'unknown': 0}
    run = {'schema': 'ndx12-share.v2', 'identity': dict(core.catalog()[version],
                schema='ndx12-share.v2', status='VERIFIED'),
        'gpu': {'model': gpu, 'driver': '620.70.06', 'pci': '10de:2204', 'status': 'RECORDED'},
        'run': {'requested': list(core.SUITES), 'completed': list(core.SUITES),
                'not_started': [], 'failed': None, 'clocks': 'unchanged', 'overall': 'COMPLETE'},
        'totals': counts(processes), 'steps': [dict(suite=s, status='COMPLETE',
            counts=counts([p for p in processes if p['suite'] == s]),
            clock_check={'status': 'NOT_QUALIFIED', 'envelope_ns_per_tick': None,
                         'reason': 'CANARY_PRIVATE_HOST'}) for s in core.SUITES],
        'units': {'native': 'GPU_TICKS', 'vulkan': 'NS'},
        'system': {'hostname': 'CANARY_PRIVATE_HOST', 'path': '/home/private/secret',
                   'uuid': 'CANARY_UUID', 'ip': '192.0.2.99'}}
    files = {'run.json': core.json_bytes(run),
             'processes.csv': core.csv_text(processes, core.PROCESS_COLUMNS),
             'summary.txt': b'UNTRUSTED PERFORMANCE CLAIM CANARY_PRIVATE_HOST',
             'charts.html': b'<script>CANARY_PRIVATE_HOST</script>',
             'charts/results.svg': b'<svg><script>CANARY_UUID</script></svg>'}
    for suite in core.SUITES:
        for path in ('native', 'vulkan'):
            native = path == 'native'
            suffix = 'ticks' if native else 'ns'
            rows = []
            for n, p in enumerate(p for p in processes if p['suite'] == suite and p['path'] == path):
                if suite == 'compute':
                    row = {'case': p['case'], 'attempt': p['repeat'], 'work_'+suffix: 1000+n,
                           'empty_'+suffix: 32, 'clock_mode': 'UNCHANGED_UNKNOWN',
                           'requested_core_mhz': '', 'requested_memory_mhz': '',
                           'telemetry': 'LIVE', 'series_status': 'BOUNDED_SERIES_VERIFIED'}
                    if not native:
                        row['order'] = 'native-first'
                    columns = core.COMPUTE_COLUMNS if native else ['case', 'attempt', 'work_ns',
                        'empty_ns', 'order', 'clock_mode', 'requested_core_mhz', 'requested_memory_mhz', 'telemetry', 'series_status']
                    name = 'samples.csv' if native else 'compute-vulkan-samples.csv'
                else:
                    row = {'test': suite, 'shape': p['case'], 'arm': p['variant'] if native else 'vulkan',
                           'round': p['repeat']-1, 'process_median_'+suffix: 1000+n,
                           'first_'+suffix: 1000, 'warmup_'+suffix: 1000,
                           'empty_before_'+suffix: 32, 'empty_after_'+suffix: 32,
                           'clock_mode': 'UNCHANGED', 'telemetry': 'LIVE'}
                    columns = [x.replace('ticks', suffix) for x in core.FRAME_COLUMNS]
                    prefix = {'d4': 'test1-d4', 'k': 'test2-k', 'kw': 'test3-kw'}[suite]
                    name = prefix + ('-processes.csv' if native else '-vulkan-processes.csv')
                rows.append(row)
            files[name] = core.csv_text(rows, columns)
    return files


def bundle(files=None, entries=None, mtime=0):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT) as archive:
        if entries is None:
            entries = []
            for name, data in sorted((files or raw_files()).items()):
                item = tarfile.TarInfo('ndx12-results/'+name)
                item.size, item.mtime, item.mode = len(data), mtime, 0o644
                entries.append((item, data))
        for item, data in entries:
            archive.addfile(item, io.BytesIO(data) if data is not None else None)
    return gzip.compress(output.getvalue(), mtime=0)


def ready(number=12):
    p = core.prepare(issue(number), bundle())
    core.validate_proposal(p)
    return p


class FakeAPI:
    """Enforces the Git/PR protocol and keeps failure/retry state."""
    def __init__(self, current=None, existing=None):
        self.issue = current or issue()
        self.calls, self.writes, self.prs = [], [], []
        self.base, self.base_tree = 'a'*40, 'b'*40
        self.entries = existing or []
        self.blobs, self.trees, self.commits, self.refs = {}, {self.base_tree: self.entries}, {}, {}
        self.fail_pr_once = False
        self.edit_on_issue_read = None
        self.issue_reads = 0

    def get(self, endpoint):
        self.calls.append(('GET', endpoint))
        if endpoint == 'issues/'+str(self.issue['number']):
            self.issue_reads += 1
            if self.edit_on_issue_read == self.issue_reads:
                self.issue['body'] += '\nEdited after preparation.'
            return copy.deepcopy(self.issue)
        if endpoint == 'git/ref/heads/main':
            return {'object': {'sha': self.base}}
        if endpoint == 'git/commits/'+self.base:
            return {'tree': {'sha': self.base_tree}}
        if endpoint.startswith('git/commits/'):
            return self.commits[endpoint.rsplit('/', 1)[1]]
        if endpoint.startswith('git/trees/'):
            key = endpoint.split('/')[2].split('?')[0]
            return {'truncated': False, 'tree': copy.deepcopy(self.trees[key])}
        if endpoint.startswith('pulls?'):
            return copy.deepcopy(self.prs)
        if endpoint.startswith('git/ref/heads/community/'):
            branch = endpoint[len('git/ref/heads/'):]
            if branch not in self.refs:
                raise core.Refused('API_404')
            return {'object': {'sha': self.refs[branch]}}
        if endpoint.startswith('compare/'):
            parent, head = endpoint[len('compare/'):].split('...')
            if head == self.base:
                return {'merge_base_commit': {'sha': parent}, 'behind_by': 0}
            commit = self.commits[head]
            return {'files': [{'filename': p['path'], 'status': 'added'}
                for p in self.trees[commit['tree']['sha']] if p['path'] not in {x['path'] for x in self.entries}]}
        raise AssertionError('unexpected GET '+endpoint)

    def post(self, endpoint, data):
        self.calls.append(('POST', endpoint))
        self.writes.append((endpoint, copy.deepcopy(data)))
        if endpoint == 'git/blobs':
            self.assert_data(set(data) == {'content', 'encoding'} and data['encoding'] == 'utf-8')
            key = writer.git_blob(data['content'].encode());self.blobs[key] = data['content']
            return {'sha': key}
        if endpoint == 'git/trees':
            self.assert_data(data['base_tree'] == self.base_tree)
            key = 'c'*40;self.trees[key] = self.entries + copy.deepcopy(data['tree'])
            return {'sha': key}
        if endpoint == 'git/commits':
            self.assert_data(data['parents'] == [self.base])
            key = 'd'*40;self.commits[key] = {'message': data['message'],
                'tree': {'sha': data['tree']}, 'parents': [{'sha': self.base}]}
            return {'sha': key}
        if endpoint == 'git/refs':
            self.assert_data(data['ref'].startswith('refs/heads/community/benchmark-issue-'))
            branch = data['ref'][len('refs/heads/'):]
            self.assert_data(branch not in self.refs);self.refs[branch] = data['sha']
            return {'object': {'sha': data['sha']}}
        if endpoint == 'pulls':
            self.assert_data(data['draft'] is True and data['base'] == 'main')
            if self.fail_pr_once:
                self.fail_pr_once = False
                raise core.Refused('API_403')
            self.prs.append({'number': 20, 'state': 'open', **data})
            return {'number': 20}
        raise AssertionError('unexpected write '+endpoint)

    @staticmethod
    def assert_data(condition):
        if not condition:
            raise AssertionError('fake API rejected unsafe or unsupported behavior')


class IntakeTests(unittest.TestCase):
    def test_real_consumers_full_numeric_output_both_versions(self):
        for version in ('v0.1.4', 'v0.1.5'):
            with self.subTest(version=version):
                p = core.validate_proposal(core.prepare(issue(version=version), bundle(raw_files(version))))
                self.assertEqual(p['state'], 'DATA_READY')
                self.assertEqual(len(p['measurements']), 189)
                self.assertEqual(len(core.summaries(p)), 27)
                self.assertEqual(core.summaries(p)[0]['n'], 7)
                outputs = core.render(p)
                self.assertEqual(len(outputs), 6)
                self.assertTrue(all('/NVIDIA/RTX_3090/'+version+'/issue-12/' in path for path in outputs))

    def test_deterministic_bytes(self):
        self.assertEqual(bundle(), bundle())
        self.assertEqual(core.render(ready()), core.render(ready()))

    def test_no_uploaded_html_svg_prose_or_host_fields(self):
        p = ready();output = b''.join(core.render(p).values())
        for canary in (b'CANARY', b'192.0.2.99', b'/home/private', b'<script>', b'UNTRUSTED PERFORMANCE CLAIM'):
            self.assertNotIn(canary, output)
        self.assertIn(b'UNVERIFIED', output)
        self.assertIn(b'NOT_QUALIFIED', output)
        self.assertIn(b'Separate scales', output)
        self.assertEqual({r['unit'] for r in p['measurements']}, {'GPU_TICKS', 'NS'})

    def test_exact_gpu_suffixes_and_unknown(self):
        names = ('RTX 3060', 'RTX 3060 Ti', 'RTX 3060 Laptop', 'RTX 4090', 'RTX 4090 D', 'RTX 4090 Laptop GPU')
        self.assertEqual(len({core.gpu_category(x) for x in names}), len(names))
        for model in ('../../RTX 3090', 'RTX 3090; $(id)', 'Unrecognized Test GPU'):
            p = core.prepare(issue(gpu=model), bundle())
            self.assertEqual(p['reason'], 'GPU_UNKNOWN')
            self.assertIn('/Pending_Classification/', core.record_folder(p))

    def test_gpu_mismatch_refuses_numeric_data(self):
        p = core.prepare(issue(gpu='RTX 3090'), bundle(raw_files(gpu='NVIDIA GeForce RTX 3060')))
        self.assertEqual(p['reason'], 'GPU_MISMATCH')
        self.assertEqual(p['state'], 'MANUAL_REVIEW')
        self.assertEqual(p['measurements'], [])
        self.assertIn('/Pending_Classification/v0.1.5/', core.record_folder(p))
        self.assertEqual(len(core.render(p)), 2)

    def test_version_identity_driver_mismatches(self):
        for field, replacement, reason in [('public_version', 'v0.1.4', 'VERSION_MISMATCH'),
            ('archive_sha256', 'f'*64, 'IDENTITY_MISMATCH'), ('archive_bytes', True, 'IDENTITY_MISMATCH'),
            ('installer_sha256', 'f'*64, 'IDENTITY_MISMATCH')]:
            with self.subTest(field=field):
                f = raw_files();r = json.loads(f['run.json']);r['identity'][field] = replacement;f['run.json'] = core.json_bytes(r)
                self.assertEqual(core.prepare(issue(), bundle(f))['reason'], reason)
        x = issue();x['body'] = x['body'].replace('620.70.06', '615.78.08')
        self.assertEqual(core.prepare(x, bundle())['reason'], 'DRIVER_MISMATCH')

    def test_claimed_package_and_runtime_hash(self):
        for suffix in (' (package v21-r99)', ' archive SHA-256 '+('f'*64)):
            x = issue();x['body'] = x['body'].replace('v0.1.5\n\n###', 'v0.1.5'+suffix+'\n\n###')
            self.assertEqual(core.prepare(x, bundle())['reason'], 'IDENTITY_MISMATCH')

    def test_duplicate_issue_fields_and_versions(self):
        x = issue();x['body'] += '\n### GPU model\nRTX 3060'
        self.assertEqual(core.prepare(x, bundle())['reason'], 'ISSUE_DUPLICATE_FIELD')
        x = issue();x['body'] = x['body'].replace('v0.1.5\n\n###', 'v0.1.5 or v0.1.4\n\n###')
        self.assertEqual(core.prepare(x, bundle())['reason'], 'VERSION_UNKNOWN')

    def test_attachment_selection_and_absence(self):
        x = issue();x['body'] = x['body'].replace('https://github.com/', 'https://invalid.example/')
        self.assertEqual(core.prepare(x)['reason'], 'ATTACHMENT_MISSING')
        x = issue();x['body'] += '\nhttps://github.com/user-attachments/files/999/share-results.tar.gz'
        self.assertEqual(core.prepare(x)['reason'], 'ATTACHMENT_AMBIGUOUS')
        def unavailable(_):
            raise core.Refused('ATTACHMENT_UNAVAILABLE')
        with self.assertRaisesRegex(core.Refused, '^ATTACHMENT_UNAVAILABLE$'):
            core.prepare(issue(), fetch=unavailable)

    def test_legacy_and_bounded_numeric_prefixed_attachment_urls(self):
        class Response(io.BytesIO):
            headers = {}
            def geturl(self):return 'https://objects.githubusercontent.com/attachment'
        for name in ('share-results.tar.gz', 'share-results-v0.1.5.tar.gz',
                     '3090-share-results-v0.1.5.tar.gz', '770-share-results.tar.gz'):
            url = 'https://github.com/user-attachments/files/123/'+name
            x = issue();x['body'] = x['body'].replace('share-results-v0.1.5.tar.gz', name)
            with self.subTest(name=name, consumer='selection'):
                self.assertEqual(core.attachment_url(x), url)
            opener = mock.Mock();opener.open.return_value = Response(b'bounded bytes')
            with self.subTest(name=name, consumer='download'):
                self.assertEqual(core.download(url, opener), b'bounded bytes')
                self.assertEqual(opener.open.call_args.args[0].full_url, url)
        x = issue();x['body'] += '\nhttps://github.com/user-attachments/files/456/3090-share-results-v0.1.5.tar.gz'
        with self.assertRaisesRegex(core.Refused, '^ATTACHMENT_AMBIGUOUS$'):core.attachment_url(x)

    def test_archive_filename_prefix_never_identifies_hardware(self):
        for claimed, expected in [('RTX 3060', 'OK'), ('RTX 3090', 'GPU_MISMATCH')]:
            x = issue(gpu=claimed)
            x['body'] = x['body'].replace('share-results-v0.1.5.tar.gz', '3090-share-results-v0.1.5.tar.gz')
            fetched = []
            def fetch(url):
                fetched.append(url)
                return bundle(raw_files(gpu='NVIDIA GeForce RTX 3060'))
            with self.subTest(claimed=claimed):
                p = core.validate_proposal(core.prepare(x, fetch=fetch))
                self.assertEqual(p['reason'], expected)
                self.assertEqual(len(fetched), 1)
                if expected == 'OK':
                    self.assertEqual(p['archive_gpu'], 'NVIDIA/RTX_3060')
                    self.assertIn('/NVIDIA/RTX_3060/v0.1.5/', core.record_folder(p)+'/')
                    self.assertNotIn(b'3090-share-results', b''.join(core.render(p).values()))
                else:self.assertEqual(p['measurements'], [])

    def test_archive_prefix_and_version_bounds_reject_paths_and_code(self):
        class Response(io.BytesIO):
            headers = {}
            def geturl(self):return 'https://objects.githubusercontent.com/attachment'
        for name in ('99-share-results.tar.gz', '12345-share-results.tar.gz',
                     '03090-share-results.tar.gz', '3090-ti-share-results.tar.gz',
                     '../3090-share-results.tar.gz', '3090/../share-results.tar.gz',
                     '3090;id-share-results.tar.gz', '3090%2f-share-results.tar.gz',
                     '3090-share-results.tar.gz.py', 'share-results-v1000.1.5.tar.gz'):
            url = 'https://github.com/user-attachments/files/123/'+name
            opener = mock.Mock();opener.open.return_value = Response(b'not downloaded')
            with self.subTest(name=name):
                with self.assertRaisesRegex(core.Refused, '^ATTACHMENT_URL$'):core.download(url, opener)
                opener.open.assert_not_called()

    def test_driver_stack_formats_are_bounded_and_not_copied(self):
        for value in ('620.70.06, proprietary', '620.70.06 (NVIDIA Open)',
                      '620.70.06 NVIDIA proprietary', '620.70.06, NVIDIA Open kernel module'):
            x = issue();x['body'] = x['body'].replace('620.70.06\n', value+'\n')
            with self.subTest(value=value):
                p = core.validate_proposal(core.prepare(x, bundle()))
                self.assertEqual(p['state'], 'DATA_READY')
                self.assertEqual(p['driver'], '620.70.06')
        for value in ('620.70.06; $(id)', '620.70.060', '620.70.06 (NVIDIA Open',
                      '620.70.06 proprietary)', '620.70.06 '+'x'*100):
            x = issue();x['body'] = x['body'].replace('620.70.06\n', value+'\n')
            with self.subTest(value=value):self.assertEqual(core.prepare(x, bundle())['reason'], 'DRIVER_MISMATCH')

    def test_attachment_http_permanent_vs_transient_failures(self):
        url = 'https://github.com/user-attachments/files/123/share-results.tar.gz'
        for code in (404, 410, 403, 429, 500):
            opener = mock.Mock()
            opener.open.side_effect = core.urllib.error.HTTPError(url, code, 'PRIVATE_HTTP_MESSAGE', {}, None)
            reason = 'ATTACHMENT_GONE' if code in (404, 410) else 'ATTACHMENT_UNAVAILABLE'
            with self.subTest(code=code), self.assertRaisesRegex(core.Refused, '^'+reason+'$'):
                core.download(url, opener)

    def test_transient_download_creates_no_proposal_or_ready_output(self):
        api = FakeAPI();opener = mock.Mock()
        opener.open.side_effect = core.urllib.error.URLError('PRIVATE_DNS_DETAIL')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);event = root/'event.json';proposal = root/'proposal.json';output = root/'step-output'
            event.write_bytes(core.json_bytes({'issue': {'number': 12}}))
            env = {'GITHUB_EVENT_NAME':'issues', 'GITHUB_REPOSITORY':core.REPOSITORY,
                   'GH_TOKEN':'NOT_A_REAL_TOKEN', 'GITHUB_OUTPUT':str(output)}
            with mock.patch.dict(os.environ, env), mock.patch.object(core, 'GitHub', return_value=api), \
                    mock.patch.object(core.urllib.request, 'build_opener', return_value=opener):
                with self.assertRaisesRegex(core.Refused, '^ATTACHMENT_UNAVAILABLE$'):
                    core.prepare_main(['--event',str(event),'--output',str(proposal)])
            self.assertFalse(proposal.exists());self.assertFalse(output.exists());self.assertEqual(api.writes, [])
        def timeout(_):raise core.Refused('ATTACHMENT_TIMEOUT')
        with self.assertRaisesRegex(core.Refused, '^ATTACHMENT_TIMEOUT$'):core.prepare(issue(), fetch=timeout)

    def test_permanent_missing_attachment_is_manual_review_without_numbers(self):
        def gone(_):raise core.Refused('ATTACHMENT_GONE')
        p = core.validate_proposal(core.prepare(issue(), fetch=gone))
        self.assertEqual(p['reason'], 'ATTACHMENT_GONE')
        self.assertEqual(p['measurements'], [])

    def test_gzip_limits_truncation_and_concatenation(self):
        with mock.patch.object(core, 'MAX_COMPRESSED', 32):
            with self.assertRaisesRegex(core.Refused, '^COMPRESSED_LIMIT$'):
                core.read_share_members(b'x'*33)
        with mock.patch.object(core, 'MAX_EXPANDED', 4096):
            with self.assertRaisesRegex(core.Refused, '^EXPANDED_LIMIT$'):
                core.read_share_members(gzip.compress(b'\0'*8192, mtime=0))
        for data in (b'not gzip', bundle()[:-8], bundle()+bundle()):
            with self.subTest(length=len(data)), self.assertRaisesRegex(core.Refused, '^GZIP_FORMAT$'):
                core.read_share_members(data)

    def test_archive_types_never_followed(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.GNUTYPE_SPARSE):
            item = tarfile.TarInfo('ndx12-results/run.json');item.type = kind
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):item.linkname = '/private/target'
            with self.subTest(kind=kind), self.assertRaisesRegex(core.Refused, '^TAR_TYPE$'):
                core.read_share_members(bundle(entries=[(item, None)]))

    def test_paths_duplicate_and_code_members(self):
        for name, reason in [('/run.json', 'TAR_PATH'), ('../run.json', 'TAR_PATH'),
            ('ndx12-results/../run.json', 'MEMBER_NOT_ALLOWLISTED'),
            ('ndx12-results/evil.py', 'MEMBER_NOT_ALLOWLISTED')]:
            item = tarfile.TarInfo(name);item.size = 1
            with self.subTest(name=name), self.assertRaisesRegex(core.Refused, '^'+reason+'$'):
                core.read_share_members(bundle(entries=[(item, b'x')]))
        item = tarfile.TarInfo('ndx12-results/run.json');item.size = 2
        with self.assertRaisesRegex(core.Refused, '^DUPLICATE_MEMBER$'):
            core.read_share_members(bundle(entries=[(item, b'{}'), (item, b'{}')]))

    def test_member_count_and_declared_size(self):
        item = tarfile.TarInfo('ndx12-results');item.type = tarfile.DIRTYPE
        with self.assertRaisesRegex(core.Refused, '^MEMBER_COUNT$'):
            core.read_share_members(bundle(entries=[(item, None)]*65))
        item = tarfile.TarInfo('ndx12-results/run.json');item.size = core.MAX_MEMBER+1
        raw = item.tobuf(format=tarfile.USTAR_FORMAT) + b'\0'*1024
        with self.assertRaisesRegex(core.Refused, '^MEMBER_SIZE$'):
            core.read_share_members(gzip.compress(raw, mtime=0))

    def test_pax_mtime_only(self):
        self.assertEqual(len(core.read_share_members(bundle(mtime=0.125))), 10)
        item = tarfile.TarInfo('ndx12-results/run.json');item.size = 2;item.pax_headers = {'path': '../../bad'}
        with self.assertRaisesRegex(core.Refused, '^PAX_FIELD$'):
            core.read_share_members(bundle(entries=[(item, b'{}')]))

    def test_json_duplicate_nonfinite_and_number_length(self):
        for raw, reason in [(b'{"x":1,"x":2}', 'JSON_DUPLICATE_KEY'),
            (b'{"x":NaN}', 'JSON_NUMBER_LIMIT'), (b'{"x":1e999}', 'JSON_NUMBER_LIMIT'),
            (b'{"x":'+b'1'*100+b'}', 'JSON_NUMBER_LIMIT')]:
            with self.subTest(raw=raw[:40]), self.assertRaisesRegex(core.Refused, '^'+reason+'$'):
                core.load_json(raw)

    def test_malformed_nested_mappings_become_manual_review(self):
        for field in ('gpu', 'identity', 'units', 'run'):
            for malformed in (None, [], 'PRIVATE_BAD_FIELD', 7):
                f = raw_files();r = json.loads(f['run.json']);r[field] = malformed
                f['run.json'] = core.json_bytes(r)
                with self.subTest(field=field, malformed=malformed):
                    p = core.validate_proposal(core.prepare(issue(), bundle(f)))
                    self.assertEqual(p['state'], 'MANUAL_REVIEW')
                    self.assertEqual(p['reason'], 'SCHEMA')
                    self.assertEqual(p['measurements'], [])
        for mode in ('step', 'clock'):
            f = raw_files();r = json.loads(f['run.json'])
            if mode == 'step':r['steps'][0] = None
            else:r['steps'][0]['clock_check'] = 'PRIVATE_BAD_FIELD'
            f['run.json'] = core.json_bytes(r)
            with self.subTest(mode=mode):
                p = core.validate_proposal(core.prepare(issue(), bundle(f)))
                self.assertEqual(p['reason'], 'SCHEMA')
                self.assertNotIn(b'PRIVATE_BAD_FIELD', b''.join(core.render(p).values()))

    def test_csv_schedule_values_and_counts(self):
        for change, reason in [('formula', 'PROCESS_SCHEDULE'), ('repeat', 'CSV_VALUE'),
            ('duplicate', 'PROCESS_SCHEDULE'), ('header', 'CSV_HEADER'), ('counts', 'COUNTS_MISMATCH')]:
            f = raw_files()
            if change == 'counts':
                r = json.loads(f['run.json']);r['totals']['verified'] = 188;f['run.json'] = core.json_bytes(r)
            else:
                rows = list(csv.DictReader(io.StringIO(f['processes.csv'].decode())))
                if change == 'formula':rows[0]['case'] = '=1+2'
                if change == 'repeat':rows[0]['repeat'] = '1e0'
                if change == 'duplicate':rows[-1] = rows[0]
                f['processes.csv'] = core.csv_text(rows, core.PROCESS_COLUMNS)
                if change == 'header':f['processes.csv'] = f['processes.csv'].replace(b'suite,case', b'suite,suite', 1)
            with self.subTest(change=change):
                self.assertEqual(core.prepare(issue(), bundle(f))['reason'], reason)

    def test_metrics_missing_duplicate_and_formula(self):
        for mode, reason in [('missing', 'MEASUREMENTS_MISSING'), ('duplicate', 'MEASUREMENT_STATUS_MISMATCH'), ('formula', 'CSV_VALUE')]:
            f = raw_files();rows = list(csv.DictReader(io.StringIO(f['samples.csv'].decode())))
            if mode == 'missing':rows.pop()
            if mode == 'duplicate':rows[-1] = rows[0]
            if mode == 'formula':rows[0]['work_ticks'] = '=1+2'
            f['samples.csv'] = core.csv_text(rows, core.COMPUTE_COLUMNS)
            with self.subTest(mode=mode):self.assertEqual(core.prepare(issue(), bundle(f))['reason'], reason)

    def test_kernel_records_and_clock_caveats_retained(self):
        f = raw_files();rows = list(csv.DictReader(io.StringIO(f['processes.csv'].decode())));rows[0]['kernel_records'] = '1'
        f['processes.csv'] = core.csv_text(rows, core.PROCESS_COLUMNS)
        p = core.validate_proposal(core.prepare(issue(), bundle(f)))
        self.assertIn('KERNEL_RECORDS_REPORTED', p['warnings'])
        self.assertIn('BACKGROUND_NOT_ASSESSED', p['warnings'])
        self.assertTrue(all(x['reported_clock_qualification'] == 'NOT_QUALIFIED' for x in p['run']['steps']))

    def test_complete_run_contradictions_fail_closed(self):
        for field, value in [('completed', []), ('not_started', ['kw']),
                             ('failed', {'reason': 'PRIVATE_FAILURE_DETAIL'})]:
            f = raw_files();r = json.loads(f['run.json']);r['run'][field] = value
            f['run.json'] = core.json_bytes(r)
            with self.subTest(field=field):
                p = core.prepare(issue(), bundle(f))
                self.assertEqual(p['reason'], 'RUN_CLAIM_MISMATCH')
                self.assertEqual(p['measurements'], [])
                self.assertNotIn(b'PRIVATE_FAILURE_DETAIL', b''.join(core.render(p).values()))

    def test_issue_negative_run_claim_contradicts_complete_archive(self):
        for claim in ('Stopped or interrupted before completion', 'Failed or refused to start'):
            x = issue();x['body'] = x['body'].replace('Full test completed', claim)
            with self.subTest(claim=claim):
                self.assertEqual(core.prepare(x, bundle())['reason'], 'RUN_CLAIM_MISMATCH')

    def test_failed_compute_series_never_loses_negative_evidence(self):
        f = raw_files();f['samples.csv'] = f['samples.csv'].replace(b'BOUNDED_SERIES_VERIFIED', b'FAILED')
        p = core.prepare(issue(), bundle(f))
        self.assertEqual(p['reason'], 'MEASUREMENT_STATUS_MISMATCH')
        self.assertEqual(p['measurements'], [])

    def test_completed_count_matches_exported_completion_fields(self):
        f = raw_files();rows = list(csv.DictReader(io.StringIO(f['processes.csv'].decode())))
        rows[0].update(status='NOT_RUN', submission='NOT_RUN', completion='NOT_RUN',
                       correctness='NOT_RUN', timing='NOT_RUN')
        f['processes.csv'] = core.csv_text(rows, core.PROCESS_COLUMNS)
        r = json.loads(f['run.json']);r['run'].update(overall='PARTIAL', completed=[])
        for step in r['steps']:step['status'] = 'PARTIAL'
        for counts in (r['totals'], next(s['counts'] for s in r['steps'] if s['suite'] == rows[0]['suite'])):
            counts['verified'] -= 1;counts['not_run'] += 1
        f['run.json'] = core.json_bytes(r)
        self.assertEqual(core.prepare(issue(), bundle(f))['reason'], 'COUNTS_MISMATCH')

    def test_partial_failure_caveat_and_rejected_full_claim(self):
        f = raw_files();r = json.loads(f['run.json'])
        r['run'].update(overall='STOPPED', completed=[], failed={'reason': 'PRIVATE_FAILURE_DETAIL'})
        for step in r['steps']:step['status'] = 'STOPPED'
        f['run.json'] = core.json_bytes(r)
        self.assertEqual(core.prepare(issue(), bundle(f))['reason'], 'RUN_CLAIM_MISMATCH')
        x = issue();x['body'] = x['body'].replace('Full test completed', 'Stopped or interrupted before completion')
        p = core.validate_proposal(core.prepare(x, bundle(f)))
        self.assertEqual(p['run']['overall'], 'STOPPED')
        self.assertTrue(p['run']['failure_reported'])
        self.assertIn('NONCOMPLETE_RUN', p['warnings'])
        self.assertNotIn(b'PRIVATE_FAILURE_DETAIL', b''.join(core.render(p).values()))

    def test_not_run_suite_cannot_contain_completed_measurements(self):
        f = raw_files();r = json.loads(f['run.json'])
        r['run'].update(overall='STOPPED', completed=['d4','k','kw'], not_started=['compute'])
        next(s for s in r['steps'] if s['suite']=='compute')['status'] = 'NOT_RUN'
        f['run.json'] = core.json_bytes(r)
        x = issue();x['body'] = x['body'].replace('Full test completed', 'Stopped or interrupted before completion')
        self.assertEqual(core.prepare(x, bundle(f))['reason'], 'COUNTS_MISMATCH')

    def test_writer_refuses_not_run_suite_before_api_calls(self):
        p = ready();p['run']['overall'] = 'STOPPED'
        next(s for s in p['run']['steps'] if s['suite']=='compute')['status'] = 'NOT_RUN'
        p['warnings'].append('NONCOMPLETE_RUN')
        api = FakeAPI()
        with self.assertRaisesRegex(core.Refused, '^COUNTS_MISMATCH$'):writer.publish(p, api, 12)
        self.assertEqual(api.calls, [])

    def test_legitimate_not_run_suite_keeps_only_executed_suites(self):
        f = raw_files();r = json.loads(f['run.json'])
        r['run'].update(overall='STOPPED', completed=['d4','k','kw'], not_started=['compute'])
        rows = list(csv.DictReader(io.StringIO(f['processes.csv'].decode())))
        count = 0
        for row in rows:
            if row['suite']=='compute':
                count += 1
                row.update(status='NOT_RUN', submission='NOT_RUN', completion='NOT_RUN', correctness='NOT_RUN', timing='NOT_RUN')
        f['processes.csv'] = core.csv_text(rows, core.PROCESS_COLUMNS)
        step = next(s for s in r['steps'] if s['suite']=='compute');step['status'] = 'NOT_RUN'
        step['counts'].update(verified=0, completed=0, not_run=count)
        r['totals'].update(verified=189-count, completed=189-count, not_run=count)
        f['run.json'] = core.json_bytes(r)
        del f['samples.csv'];del f['compute-vulkan-samples.csv']
        x = issue();x['body'] = x['body'].replace('Full test completed', 'Stopped or interrupted before completion')
        p = core.validate_proposal(core.prepare(x, bundle(f)))
        self.assertEqual(p['state'], 'DATA_READY')
        self.assertEqual(len(p['measurements']), 147)
        self.assertTrue(all(v['suite']!='compute' for v in p['measurements']))
        self.assertIn('NONCOMPLETE_RUN', p['warnings'])

    def test_downloader_size_timeout_and_no_credentials(self):
        class Response(io.BytesIO):
            headers = {}
            def geturl(self):return 'https://objects.githubusercontent.com/attachment'
        opener = mock.Mock()
        opener.open.return_value = Response(b'abc')
        url = 'https://github.com/user-attachments/files/123/share-results.tar.gz'
        self.assertEqual(core.download(url, opener), b'abc')
        request = opener.open.call_args[0][0]
        self.assertNotIn('Authorization', request.headers)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 15)
        response = Response(b'abc');response.headers = {'Content-Length': str(core.MAX_COMPRESSED+1)}
        opener.open.return_value = response
        with self.assertRaisesRegex(core.Refused, '^COMPRESSED_LIMIT$'):core.download(url, opener)
        opener.open.return_value = Response(b'abcd')
        with mock.patch.object(core, 'MAX_COMPRESSED', 3):
            with self.assertRaisesRegex(core.Refused, '^COMPRESSED_LIMIT$'):core.download(url, opener)
        opener.open.return_value = Response(b'abc')
        with mock.patch.object(core.time, 'monotonic', side_effect=[0, 46]):
            with self.assertRaisesRegex(core.Refused, '^ATTACHMENT_TIMEOUT$'):core.download(url, opener)

    def test_tar_checksum_truncation_and_trailer(self):
        raw = bytearray(gzip.decompress(bundle()))
        raw[0] ^= 1
        with self.assertRaisesRegex(core.Refused, '^TAR_CHECKSUM$'):
            core.read_share_members(gzip.compress(raw, mtime=0))
        for invalid in (bytes(raw[:511]), b'\0'*512):
            with self.assertRaises(core.Refused):core.read_share_members(gzip.compress(invalid, mtime=0))

    def test_writer_artifact_schema_rejects_extra_text_paths_and_types(self):
        for mutate in (lambda p:p.update(files={'../../evil.py':'code'}),
            lambda p:p.update(reason='PRIVATE_HOST'), lambda p:p.update(issue=True),
            lambda p:p['run']['steps'].append('raw-host'),
            lambda p:p['measurements'][0].update(case='PRIVATE_HOST')):
            p = ready();mutate(p)
            with self.subTest(mutate=mutate), self.assertRaises(core.Refused):core.validate_proposal(p)

    def test_approval_gate_not_correctness_acceptance(self):
        x = issue();x['labels'] = ['benchmark:submission']
        with self.assertRaisesRegex(core.Refused, '^AWAITING_INTAKE_APPROVAL$'):core.eligible(x)
        core.eligible(x, manual=True)
        x['author_association'] = 'COLLABORATOR';core.eligible(x)
        x['pull_request'] = {};x['pull_request']['url'] = 'unused'
        with self.assertRaisesRegex(core.Refused, '^NOT_ELIGIBLE$'):core.eligible(x)

    def test_untrusted_urls_and_redirects(self):
        for url in ('http://github.com/x', 'https://localhost/x', 'https://github.com@127.0.0.1/x',
            'https://objects.githubusercontent.com:4430/x', 'https://github.com.evil.example/x'):
            with self.subTest(url=url), self.assertRaisesRegex(core.Refused, '^ATTACHMENT_URL$'):core.safe_download_url(url)
        redirect = core.DownloadRedirects()
        with self.assertRaisesRegex(core.Refused, '^ATTACHMENT_URL$'):
            redirect.redirect_request(None, None, 302, None, {}, 'http://127.0.0.1/')
        with self.assertRaisesRegex(core.Refused, '^API_REDIRECT$'):core.NoRedirect().redirect_request()

    def test_api_read_client_cannot_write(self):
        api = core.GitHub('NOT_A_REAL_TOKEN')
        with self.assertRaisesRegex(core.Refused, '^API_WRITE_DISABLED$'):api.post('pulls', {})
        for method in ('PATCH', 'DELETE', 'PUT'):
            with self.subTest(method=method), self.assertRaisesRegex(core.Refused, '^API_WRITE_DISABLED$'):
                core.GitHub('NOT_A_REAL_TOKEN', writable=True).request(method, 'issues/12')

    def test_real_api_client_accepts_compare_but_not_traversal(self):
        opener = mock.Mock();opener.open.return_value = io.BytesIO(b'{"behind_by":0}')
        api = core.GitHub('NOT_A_REAL_TOKEN', opener=opener)
        self.assertEqual(api.get('compare/'+'a'*40+'...'+'b'*40), {'behind_by': 0})
        for endpoint in ('../issues', '/issues', 'x/../issues', 'https://evil.example/x',
                         'x%2f..%2fissues', 'issues#secret', 'issues\\other'):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(core.Refused, '^API_ENDPOINT$'):
                api.get(endpoint)

    def test_local_cli_and_relocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);i = root/'issue.json';i.write_bytes(core.json_bytes(issue()));b = root/'bundle.tar.gz';b.write_bytes(bundle())
            for folder in ('location-a', 'location with spaces'):
                target = root/folder;target.mkdir()
                for name in ('community_intake.py', 'community_releases.json'):
                    shutil.copyfile(SCRIPTS/name, target/name)
                out = target/'proposal.json'
                result = subprocess.run([sys.executable, '-I', '-B', str(target/'community_intake.py'),
                    '--issue-json', str(i), '--bundle', str(b), '--output', str(out)], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(result.stdout, b'DATA_READY:OK\n')
                self.assertEqual(core.load_json(out.read_bytes())['state'], 'DATA_READY')

    def test_write_output_does_not_follow_aliases_or_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);target = root/'proposal.json';core.write_new(target, b'one')
            with self.assertRaises(FileExistsError):core.write_new(target, b'two')
            alias = root/'alias';alias.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(core.Refused, '^OUTPUT_ALIAS$'):core.write_new(alias/'other.json', b'two')
            self.assertEqual(target.read_bytes(), b'one')


class PublisherTests(unittest.TestCase):
    def test_comments_and_category_labels_do_not_invalidate_source(self):
        p = ready();api = FakeAPI()
        api.issue['labels'] += [{'name':'gpu:rtx-3090'}, {'name':'unrelated-maintainer-label'}]
        api.issue['updated_at'] = '2026-11-11T02:00:00Z'
        self.assertEqual(core.issue_fingerprint(api.issue), p['source_revision'])
        self.assertEqual(writer.publish(p, api, 12)['status'], 'DRAFT_PR_CREATED')

    def test_orphan_retry_after_comment_or_category_label_changes(self):
        api = FakeAPI();api.fail_pr_once = True
        with self.assertRaisesRegex(core.Refused, '^API_403$'):writer.publish(ready(), api, 12)
        api.issue['labels'].append({'name':'gpu:rtx-3090'})
        api.issue['updated_at'] = '2026-11-11T02:00:00Z'
        p = core.prepare(api.issue, bundle());before = len(api.writes)
        self.assertEqual(writer.publish(p, api, 12)['status'], 'DRAFT_PR_CREATED')
        self.assertEqual([x[0] for x in api.writes[before:]], ['pulls'])

    def test_centralized_curated_issue_without_legacy_issue_page_is_reserved(self):
        x = issue(4, 'RTX 3060', 'v0.1.4');p = core.prepare(x, bundle(raw_files('v0.1.4', 'RTX 3060')))
        api = FakeAPI(x)
        self.assertEqual(writer.publish(p, api, 4)['status'], 'CURATED_MANUAL_MIGRATION')
        self.assertEqual(api.writes, [])

    def test_only_draft_pr_and_additive_fixed_paths(self):
        api = FakeAPI();p = ready();r = writer.publish(p, api, 12)
        self.assertEqual(r['status'], 'DRAFT_PR_CREATED')
        self.assertEqual(len(api.refs), 1)
        self.assertEqual(api.prs[0]['draft'], True)
        self.assertIn('UNVERIFIED', api.prs[0]['body'])
        self.assertEqual(set(x[0] for x in api.writes), {'git/blobs','git/trees','git/commits','git/refs','pulls'})
        self.assertTrue(all(path.startswith(core.ROOT+'NVIDIA/RTX_3090/v0.1.5/issue-12/') for path in r['files']))

    def test_duplicate_events_and_reopened_or_edited_issues(self):
        api = FakeAPI();writer.publish(ready(), api, 12);before = copy.deepcopy(api.writes)
        self.assertEqual(writer.publish(ready(), api, 12)['status'], 'EXISTING_PR_REQUIRES_REVIEW')
        api.issue['body'] += '\nEdited source';api.issue['updated_at'] = '2026-11-11T01:00:00Z'
        p = core.prepare(api.issue, bundle())
        self.assertEqual(writer.publish(p, api, 12)['status'], 'EXISTING_PR_REQUIRES_REVIEW')
        self.assertEqual(api.writes, before)

    def test_existing_curated_and_versioned_records_not_duplicated(self):
        for n, (gpu, version) in core.LEGACY.items():
            x = issue(n, core.GPUS[gpu], version)
            p = core.prepare(x, bundle(raw_files(version, 'NVIDIA GeForce '+core.GPUS[gpu])))
            path = core.ROOT+gpu+'/issue-'+str(n)+'.md'
            api = FakeAPI(x, [{'path':path,'type':'blob','mode':'100644','sha':'f'*40}])
            with self.subTest(issue=n):
                self.assertEqual(writer.publish(p, api, n)['status'], 'ALREADY_RECORDED')
                self.assertEqual(api.writes, [])
        api = FakeAPI(existing=[{'path':core.ROOT+'Pending_Classification/v0.1.4/issue-12/record.json','type':'blob'}])
        self.assertEqual(writer.publish(ready(), api, 12)['status'], 'ALREADY_RECORDED')

    def test_source_changes_at_each_recheck_fail_closed(self):
        for read_number in (1, 2, 3):
            api = FakeAPI();api.edit_on_issue_read = read_number
            with self.subTest(read=read_number), self.assertRaisesRegex(core.Refused, '^SOURCE_CHANGED$'):
                writer.publish(ready(), api, 12)
            self.assertEqual(api.prs, [])
            self.assertEqual(api.refs, {})
            if read_number < 3:self.assertEqual(api.writes, [])

    def test_new_ref_has_immediately_preceding_fresh_issue_check(self):
        api = FakeAPI();p = ready();result = writer.publish(p, api, 12)
        index = api.calls.index(('POST', 'git/refs'))
        self.assertEqual(api.calls[index-1], ('GET', 'issues/12'))
        self.assertEqual(result['source_status'], 'MATCH_AT_CHECK')
        self.assertIn('| Source status | `MATCH_AT_CHECK` |', api.prs[0]['body'])
        self.assertIn(p['source_revision'], api.prs[0]['body'])

    def test_change_after_commit_blocks_ref_and_pr(self):
        for mode in ('content', 'approval', 'closed', 'author-role'):
            api = FakeAPI();original_post = api.post
            if mode == 'author-role':
                api.issue.update(author_association='OWNER', labels=['benchmark:submission'])
            p = core.prepare(api.issue, bundle())
            def post(endpoint, data):
                result = original_post(endpoint, data)
                if endpoint == 'git/commits':
                    if mode == 'content':api.issue['body'] += '\nChanged before ref.'
                    if mode == 'approval':api.issue['labels'] = ['benchmark:submission']
                    if mode == 'closed':api.issue['state'] = 'closed'
                    if mode == 'author-role':api.issue['author_association'] = 'NONE'
                return result
            api.post = post
            reason = ('SOURCE_CHANGED' if mode == 'content' else
                      'NOT_ELIGIBLE' if mode == 'closed' else 'AWAITING_INTAKE_APPROVAL')
            with self.subTest(mode=mode), self.assertRaisesRegex(core.Refused, '^'+reason+'$'):
                writer.publish(p, api, 12)
            self.assertEqual(api.refs, {})
            self.assertEqual(api.prs, [])
            self.assertTrue(api.commits)  # Unreferenced objects are permitted; no durable branch.

    def test_real_writer_main_creates_pinned_stale_draft_after_new_ref(self):
        api = FakeAPI();p = ready();original_post = api.post
        def post(endpoint, data):
            result = original_post(endpoint, data)
            if endpoint == 'git/refs':
                api.issue['body'] = api.issue['body'].replace('RTX 3090', 'RTX 3060')+'\nPRIVATE_LATE_PROSE'
            return result
        api.post = post
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);event = root/'event.json';proposal = root/'proposal.json'
            event.write_bytes(core.json_bytes({'issue': {'number': 12}}));proposal.write_bytes(core.json_bytes(p))
            env = {'GITHUB_EVENT_NAME':'issues', 'GITHUB_REPOSITORY':core.REPOSITORY, 'GH_TOKEN':'NOT_A_REAL_TOKEN'}
            with mock.patch.dict(os.environ, env), mock.patch.object(core, 'GitHub', return_value=api), \
                    mock.patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(writer.main(['--event',str(event),'--proposal',str(proposal),'--apply']), 0)
        self.assertEqual(len(api.refs), 1);self.assertEqual(len(api.prs), 1)
        self.assertTrue(api.prs[0]['draft']);body = api.prs[0]['body']
        self.assertIn('| Source status | `STALE` |', body)
        self.assertIn(p['source_revision'], body)
        self.assertIn(core.issue_fingerprint(api.issue), body)
        self.assertIn(p['bundle_sha256'], body)
        self.assertIn(next(iter(api.refs.values())), body)
        self.assertNotIn('PRIVATE_LATE_PROSE', body)
        entry = next(x for x in api.trees['c'*40] if x['path'].endswith('/record.json'))
        committed = json.loads(api.blobs[entry['sha']])
        self.assertEqual(committed, p)  # Never rewrite the pinned snapshot from later Issue content.

    def test_new_ref_draft_survives_late_ineligibility_or_failed_observation(self):
        for mode in ('closed', 'approval-revoked', 'author-role-revoked', 'read-unavailable'):
            api = FakeAPI();original_post, original_get = api.post, api.get
            if mode == 'author-role-revoked':
                api.issue.update(author_association='OWNER', labels=['benchmark:submission'])
            p = core.prepare(api.issue, bundle())
            def post(endpoint, data):
                result = original_post(endpoint, data)
                if endpoint == 'git/refs':
                    if mode == 'closed':api.issue['state'] = 'closed'
                    if mode == 'approval-revoked':api.issue['labels'] = ['benchmark:submission']
                    if mode == 'author-role-revoked':api.issue['author_association'] = 'NONE'
                return result
            def get(endpoint):
                if mode == 'read-unavailable' and api.refs and endpoint == 'issues/12':
                    raise core.Refused('API_UNAVAILABLE')
                return original_get(endpoint)
            api.post, api.get = post, get
            with self.subTest(mode=mode):
                result = writer.publish(p, api, 12)
                expected = 'UNKNOWN' if mode == 'read-unavailable' else 'STALE'
                self.assertEqual(result['source_status'], expected)
                self.assertTrue(api.prs[0]['draft'])
                self.assertIn('| Source status | `'+expected+'` |', api.prs[0]['body'])
                eligibility = 'UNKNOWN' if mode == 'read-unavailable' else 'INELIGIBLE'
                self.assertIn('| Eligibility at observation | `'+eligibility+'` |', api.prs[0]['body'])
                self.assertIn(p['source_revision'], api.prs[0]['body'])
                if mode == 'author-role-revoked':
                    self.assertEqual(core.issue_fingerprint(api.issue), p['source_revision'])

    def test_existing_orphan_recovery_rechecks_source_and_eligibility_fail_closed(self):
        for mode in ('content', 'approval', 'read-unavailable'):
            api = FakeAPI();p = ready();api.fail_pr_once = True
            with self.assertRaisesRegex(core.Refused, '^API_403$'):writer.publish(p, api, 12)
            previous_reads, original_get, before = api.issue_reads, api.get, len(api.writes)
            def get(endpoint):
                result = original_get(endpoint)
                if endpoint == 'issues/12' and api.issue_reads == previous_reads+2:
                    if mode == 'read-unavailable':raise core.Refused('API_UNAVAILABLE')
                    if mode == 'content':result['body'] += '\nChanged during orphan recovery.'
                    else:result['labels'] = ['benchmark:submission']
                    api.issue = copy.deepcopy(result)
                return result
            api.get = get
            reason = ('SOURCE_CHANGED' if mode == 'content' else
                      'API_UNAVAILABLE' if mode == 'read-unavailable' else 'AWAITING_INTAKE_APPROVAL')
            with self.subTest(mode=mode), self.assertRaisesRegex(core.Refused, '^'+reason+'$'):
                writer.publish(p, api, 12)
            self.assertEqual(len(api.writes), before)
            self.assertEqual(api.prs, [])

    def test_pr_failure_then_retry_recovers_unchanged_branch(self):
        api = FakeAPI();api.fail_pr_once = True
        with self.assertRaisesRegex(core.Refused, '^API_403$'):writer.publish(ready(), api, 12)
        before = len(api.writes)
        self.assertEqual(writer.publish(ready(), api, 12)['status'], 'DRAFT_PR_CREATED')
        self.assertEqual([x[0] for x in api.writes[before:]], ['pulls'])

    def test_human_changed_orphan_branch_is_not_touched(self):
        api = FakeAPI();api.fail_pr_once = True
        with self.assertRaises(core.Refused):writer.publish(ready(), api, 12)
        api.commits['d'*40]['message'] = 'Human edit'
        before = len(api.writes)
        with self.assertRaisesRegex(core.Refused, '^EXISTING_BRANCH_CHANGED$'):writer.publish(ready(), api, 12)
        self.assertEqual(len(api.writes), before)

    def test_orphan_recovery_ancestor_and_exact_bytes(self):
        for mode in ('advanced-main', 'foreign-history', 'changed-blob', 'changed-mode', 'changed-diff'):
            api = FakeAPI();api.fail_pr_once = True
            with self.assertRaises(core.Refused):writer.publish(ready(), api, 12)
            previous_get = api.get
            if mode in ('advanced-main', 'foreign-history'):api.base = 'e'*40
            if mode == 'changed-blob':api.trees['c'*40][0]['sha'] = 'f'*40
            if mode == 'changed-mode':api.trees['c'*40][0]['mode'] = '120000'
            def altered_get(endpoint):
                if mode == 'foreign-history' and endpoint.endswith('...'+api.base):
                    return {'merge_base_commit': {'sha': 'f'*40}, 'behind_by': 1}
                result = previous_get(endpoint)
                if mode == 'changed-diff' and endpoint.startswith('compare/'):
                    result['files'][0]['status'] = 'modified'
                return result
            api.get = altered_get;before = len(api.writes)
            with self.subTest(mode=mode):
                if mode == 'advanced-main':
                    self.assertEqual(writer.publish(ready(), api, 12)['status'], 'DRAFT_PR_CREATED')
                    self.assertEqual([x[0] for x in api.writes[before:]], ['pulls'])
                else:
                    with self.assertRaisesRegex(core.Refused, '^EXISTING_BRANCH_CHANGED$'):writer.publish(ready(), api, 12)
                    self.assertEqual(len(api.writes), before)

    def test_base_path_collision_and_truncated_tree_stop_before_write(self):
        for mode in ('symlink', 'file', 'truncated', 'pr-limit'):
            api = FakeAPI()
            if mode in ('symlink', 'file'):
                api.entries.append({'path':core.ROOT.rstrip('/'), 'type':'blob',
                    'mode':'120000' if mode == 'symlink' else '100644'})
            previous_get = api.get
            def altered_get(endpoint):
                result = previous_get(endpoint)
                if mode == 'truncated' and endpoint.startswith('git/trees/'):result['truncated'] = True
                if mode == 'pr-limit' and endpoint.startswith('pulls?'):return [{}]*100
                return result
            api.get = altered_get
            with self.subTest(mode=mode), self.assertRaises(core.Refused):writer.publish(ready(), api, 12)
            self.assertEqual(api.writes, [])

    def test_artifact_rejected_before_any_api_request(self):
        p = ready();p['raw_hostname'] = 'PRIVATE_HOST';api = FakeAPI()
        with self.assertRaisesRegex(core.Refused, '^PROPOSAL_SCHEMA$'):writer.publish(p, api, 12)
        self.assertEqual(api.calls, [])

    def test_no_wrong_issue_no_unapproved_source(self):
        api = FakeAPI()
        with self.assertRaisesRegex(core.Refused, '^ISSUE_NUMBER_MISMATCH$'):writer.publish(ready(), api, 13)
        self.assertEqual(api.calls, [])
        api.issue['labels'] = ['benchmark:submission']
        with self.assertRaisesRegex(core.Refused, '^AWAITING_INTAKE_APPROVAL$'):writer.publish(ready(), api, 12)
        self.assertEqual(api.writes, [])

    def test_unknown_gpu_metadata_draft_uses_pending_classification(self):
        api = FakeAPI(issue(gpu='Unknown Model'))
        p = core.prepare(api.issue, bundle())
        result = writer.publish(p, api, 12)
        self.assertTrue(all('/Pending_Classification/v0.1.5/' in name for name in result['files']))
        self.assertEqual(len(result['files']), 2)


class WorkflowTests(unittest.TestCase):
    def test_failed_job_retry_uses_successful_prepare_artifact_output(self):
        text = (ROOT/'.github/workflows/community-benchmark-intake.yml').read_text()
        prepare, propose = text.split('\n  propose:',1)
        self.assertIn('artifact_name: community-intake-${{ github.run_id }}-${{ github.run_attempt }}', prepare)
        self.assertIn('name: community-intake-${{ github.run_id }}-${{ github.run_attempt }}', prepare)
        self.assertIn('name: ${{ needs.prepare.outputs.artifact_name }}', propose)
        self.assertNotIn('github.run_attempt', propose)

    def test_production_entrypoints_with_fake_api_and_attachment(self):
        class Response(io.BytesIO):
            headers = {}
            def geturl(self):return 'https://objects.githubusercontent.com/attachment'
        api = FakeAPI();opener = mock.Mock();opener.open.return_value = Response(bundle())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);event = root/'event.json';proposal = root/'typed/proposal.json';output = root/'step-output'
            event.write_bytes(core.json_bytes({'issue': {'number': 12}}))
            env = {'GITHUB_EVENT_NAME':'issues', 'GITHUB_REPOSITORY':core.REPOSITORY,
                   'GH_TOKEN':'NOT_A_REAL_TOKEN', 'GITHUB_OUTPUT':str(output)}
            with mock.patch.dict(os.environ, env), mock.patch.object(core, 'GitHub', return_value=api) as client, \
                    mock.patch.object(core.urllib.request, 'build_opener', return_value=opener), \
                    mock.patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(core.prepare_main(['--event',str(event),'--output',str(proposal)]), 0)
                self.assertEqual(output.read_text(), 'ready=true\n')
                self.assertEqual(api.writes, [])
                self.assertEqual(writer.main(['--event',str(event),'--proposal',str(proposal),'--apply']), 0)
            self.assertEqual(client.call_args_list[0].kwargs, {})
            self.assertEqual(client.call_args_list[1].kwargs, {'writable': True})
            self.assertTrue(api.prs[0]['draft'])

    def test_manual_dispatch_issue_numbers_are_bounded(self):
        with mock.patch.dict(os.environ, {'GITHUB_EVENT_NAME':'workflow_dispatch'}):
            self.assertEqual(core.event_issue({'inputs': {'issue_number':'11'}}), (11, True))
            for value in (True, '-1', '01', '2147483648', '12;exit', None):
                with self.subTest(value=value), self.assertRaises(core.Refused):
                    core.event_issue({'inputs': {'issue_number':value}})

    def test_workflow_security_contract(self):
        text = (ROOT/'.github/workflows/community-benchmark-intake.yml').read_text()
        self.assertIn('permissions: {}', text)
        self.assertIn('types: [opened, reopened, edited, labeled]', text)
        self.assertEqual(text.count('persist-credentials: false'), 2)
        self.assertEqual(text.count('ref: ${{ github.sha }}'), 2)
        self.assertNotIn('pull_request_target', text)
        self.assertNotIn('${{ github.event.issue.body', text)
        self.assertNotIn('issues: write', text)
        self.assertIn('retention-days: 3', text)
        for action in [line.split('@')[1].split()[0] for line in text.splitlines() if 'uses:' in line]:
            self.assertRegex(action, '^[0-9a-f]{40}$')


if __name__ == '__main__':
    unittest.main()
