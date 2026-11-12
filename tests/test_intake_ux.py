"""Regression checks for community Issue categorization and visible intake gates."""
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock

from test_community_intake import ROOT, FakeAPI, bundle, core, issue, raw_files, writer


class IntakeUXTests(unittest.TestCase):
    def test_hyrules_4060_alias_matches_exact_gpu_and_consumer(self):
        for alias in ('Nvidia GeForce 4060', 'GeForce 4060', 'NVIDIA GeForce RTX 4060'):
            with self.subTest(alias=alias):
                self.assertEqual(core.gpu_category(alias), 'NVIDIA/RTX_4060')
        self.assertEqual(core.gpu_category('Nvidia GeForce 4060 Ti'), 'NVIDIA/RTX_4060_Ti')
        self.assertEqual(core.gpu_category('Nvidia GeForce 4060 Laptop'),
                         'NVIDIA/RTX_4060_Laptop_GPU')
        for rejected in ('AMD GeForce 4060', 'Intel GeForce 4060',
                         'GeForce 4060; $(id)'):
            self.assertIsNone(core.gpu_category(rejected), rejected)

        submission = issue(gpu='Nvidia GeForce 4060')
        archive = bundle(raw_files(gpu='NVIDIA GeForce RTX 4060'))
        proposal = core.validate_proposal(core.prepare(submission, archive))
        self.assertEqual((proposal['state'], proposal['reason']), ('DATA_READY', 'OK'))
        self.assertIn('NVIDIA/RTX_4060/v0.1.5/issue-12', core.record_folder(proposal))

    def test_shortened_version_stays_manual_review_and_never_claims_numbers(self):
        proposal = core.prepare(issue(gpu='RTX 4060', version='v0.15'),
                                bundle(raw_files(gpu='NVIDIA GeForce RTX 4060')))
        self.assertEqual((proposal['state'], proposal['reason']),
                         ('MANUAL_REVIEW', 'VERSION_UNKNOWN'))
        self.assertFalse(proposal['measurements'])

    def test_category_workflow_resolves_supported_gpu_in_real_js(self):
        """Run production JS: labels precede dispatch; failures retry."""
        workflow = (ROOT / '.github/workflows/benchmark-gpu-categories.yml').read_text()
        self.assertIn('          script: |\n', workflow)
        script = textwrap.dedent(workflow.split('          script: |\n', 1)[1])

        def run_category(model, labels, fail_dispatch=False, attempt=1):
            body = '### GPU model\n\n' + model + '\n\n### Benchmark version\n\nv0.1.5\n'
            fixture = {'title': '[Results] Case', 'body': body,
                       'labels': [{'name': name} for name in labels]}
            prefix = ('const issue = ' + json.dumps(fixture) + ';\n'
                'const failDispatch = ' + json.dumps(fail_dispatch) + ';\n'
                'process.env.GITHUB_RUN_ATTEMPT = ' + json.dumps(str(attempt)) + ';\n'
                'const added = [], dispatched = [], order = [];\n'
                'const context = {repo:{owner:"GoblinFlash",repo:"Native-DX12-Linux"},'
                'payload:{issue:{number:15}}};\n'
                'const core = {info:()=>{}};\n'
                'const github = {rest:{issues:{get:async()=>({data:issue}),'
                'getLabel:async()=>({}),createLabel:async()=>({}),'
                'addLabels:async args=>{order.push("labels");added.push(...args.labels)},'
                'removeLabel:async()=>({})},'
                'actions:{createWorkflowDispatch:async args=>{'
                'order.push("dispatch");dispatched.push(args);'
                'if(failDispatch)throw Error("mock dispatch unavailable")}}}};\n')
            code = (prefix + '(async()=>{\nlet dispatchError = null;\ntry{\n' +
                script + '\n}catch(error){ dispatchError = error.message; }\n' +
                'process.stdout.write(JSON.stringify({added,dispatched,order,'
                'dispatchError}));\n'
                '})().catch(e=>{console.error(e);process.exit(1)});\n')
            result = subprocess.run(['node', '-e', code], text=True, capture_output=True,
                                    check=False, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

        examples = [
            ('Nvidia GeForce 4060', 'gpu:rtx-4060'),
            ('GeForce RTX 4070 Ti Super', 'gpu:rtx-4070-ti-super'),
            ('NVIDIA GeForce 4060 Laptop', 'gpu:rtx-4060-laptop'),
            ('NVIDIA GeForce RTX 5090 D', 'gpu:rtx-5090-d'),
            ('AMD GeForce 4060', 'gpu:unclassified'),
            ('RTX-3090', 'gpu:unclassified'),
            ('GeForce-RTX-4070-Ti', 'gpu:unclassified'),
        ]
        examples += [(name, 'gpu:' + name.lower().replace(' laptop gpu', ' laptop').replace(' ', '-'))
                     for name in core.GPU_NAMES]
        for model, expected in examples:
            with self.subTest(model=model):
                result = run_category(model, [])
                self.assertIn(expected, result['added'])
                self.assertIn('benchmark:submission', result['added'])
                self.assertEqual(result['order'], ['labels', 'dispatch'])
                self.assertIsNone(result['dispatchError'])
                self.assertEqual(result['dispatched'], [{
                    'owner': 'GoblinFlash', 'repo': 'Native-DX12-Linux',
                    'workflow_id': 'community-benchmark-intake.yml', 'ref': 'main',
                    'inputs': {'issue_number': '15', 'intake_mode': 'label-reconciled'},
                }])

        # A normal edit needs no extra dispatch: intake already sees its label.
        existing = run_category('Nvidia GeForce 4060',
                                ['benchmark:submission', 'gpu:rtx-4060'])
        self.assertEqual(existing['added'], [])
        self.assertEqual(existing['order'], [])
        self.assertIsNone(existing['dispatchError'])

        # Rerunning a previously failed categorizer must retry dispatch.
        rerun_existing = run_category('Nvidia GeForce 4060',
                                      ['benchmark:submission', 'gpu:rtx-4060'],
                                      attempt=2)
        self.assertEqual(rerun_existing['added'], [])
        self.assertEqual(rerun_existing['order'], ['dispatch'])

        # After addLabels succeeds but dispatch fails, rerunning the workflow
        # on the same Issue must retry dispatch with non-manual permissions.
        failed = run_category('Nvidia GeForce 4060', [], fail_dispatch=True)
        self.assertEqual(failed['order'], ['labels', 'dispatch'])
        self.assertEqual(failed['dispatchError'], 'mock dispatch unavailable')
        retried = run_category('Nvidia GeForce 4060', failed['added'], attempt=2)
        self.assertEqual(retried['added'], [])
        self.assertEqual(retried['order'], ['dispatch'])
        self.assertIsNone(retried['dispatchError'])
        self.assertEqual(retried['dispatched'][0]['inputs']['intake_mode'],
                         'label-reconciled')

    def test_completed_execution_with_failed_process_retains_valid_measurements(self):
        """Completed execution is not an all-VERIFIED correctness claim."""
        files = raw_files()
        processes = list(csv.DictReader(io.StringIO(files['processes.csv'].decode())))
        victim = next(row for row in processes if row['suite'] == 'd4' and
                      row['path'] == 'native')
        self.assertEqual(victim['status'], 'VERIFIED')
        self.assertEqual(victim['completion'], 'CLOSED')
        victim.update(status='FAIL', correctness='FAILED')
        files['processes.csv'] = core.csv_text(processes, core.PROCESS_COLUMNS)

        # A failed process must not retain its numeric sample.
        name = 'test1-d4-processes.csv'
        samples = list(csv.DictReader(io.StringIO(files[name].decode())))
        def is_failed_sample(row):
            return (row['shape'], row['arm'], int(row['round'])) == (
                victim['case'], victim['variant'], int(victim['repeat']) - 1)
        self.assertEqual(sum(is_failed_sample(row) for row in samples), 1)
        files[name] = core.csv_text([row for row in samples if not is_failed_sample(row)],
                                    core.FRAME_COLUMNS)

        data = json.loads(files['run.json'])
        data['run'].update(overall='FAILED',
                           completed=[suite for suite in core.SUITES if suite != 'd4'],
                           failed={'reason': 'PRIVATE_FAIL_CANARY'})
        failed_step = next(step for step in data['steps'] if step['suite'] == 'd4')
        failed_step['status'] = 'FAILED'
        for counter in (failed_step['counts'], data['totals']):
            counter['verified'] -= 1
            counter['failed'] += 1
        files['run.json'] = core.json_bytes(data)

        for claim in ('Full test completed', 'Selected tests completed'):
            with self.subTest(claim=claim):
                current = issue()
                current['body'] = current['body'].replace('Full test completed', claim)
                proposal = core.validate_proposal(core.prepare(current, bundle(files)))
                self.assertEqual((proposal['state'], proposal['reason']),
                                 ('DATA_READY', 'OK'))
                self.assertEqual(proposal['run']['overall'], 'FAILED')
                self.assertTrue(proposal['run']['failure_reported'])
                self.assertEqual(proposal['run']['counts']['completed'], 189)
                self.assertEqual(proposal['run']['counts']['failed'], 1)
                self.assertEqual(len(proposal['measurements']), 188)
                self.assertIn('NONCOMPLETE_RUN', proposal['warnings'])
                rendered = b'\n'.join(core.render(proposal).values())
                self.assertIn(b'UNVERIFIED', rendered)
                self.assertIn(b'Export consistency: CHECKED', rendered)
                self.assertIn(b'Owner acceptance: NOT_RECORDED', rendered)
                self.assertIn(b'Reported overall state: `FAILED`', rendered)
                self.assertNotIn(b'PRIVATE_FAIL_CANARY', rendered)
                api = FakeAPI(current=current)
                self.assertEqual(writer.publish(proposal, api, 12)['status'],
                                 'DRAFT_PR_CREATED')

        for negative in ('Stopped or interrupted before completion',
                         'Failed or refused to start'):
            with self.subTest(negative=negative):
                current = issue()
                current['body'] = current['body'].replace('Full test completed', negative)
                invalid = core.prepare(current, bundle(files))
                self.assertEqual((invalid['state'], invalid['reason']),
                                 ('MANUAL_REVIEW', 'RUN_CLAIM_MISMATCH'))
                self.assertEqual(invalid['measurements'], [])

        # Do not allow failed counts to masquerade as a successful overall.
        data['run'].update(overall='COMPLETE', completed=list(core.SUITES),
                           failed=None)
        failed_step['status'] = 'COMPLETE'
        files['run.json'] = core.json_bytes(data)
        forged = core.prepare(issue(), bundle(files))
        self.assertEqual((forged['state'], forged['reason']),
                         ('MANUAL_REVIEW', 'COUNTS_MISMATCH'))

    def test_queued_manual_dispatch_is_not_replaced(self):
        workflow = (ROOT / '.github/workflows/community-benchmark-intake.yml').read_text()
        concurrency = workflow.split('concurrency:\n', 1)[1].split('\npermissions:', 1)[0]
        self.assertIn('  queue: max\n', concurrency)
        self.assertIn('  cancel-in-progress: false\n', concurrency)

    def test_unsupported_release_suffix_never_claims_stable_measurements(self):
        archive = bundle(raw_files())
        for version in ('v0.1.5-rc.1', 'v0.1.5.1', 'v0.1.5+build',
                        'v0.1.5_rc', 'v0.1.5-rc.1 or v0.1.5'):
            with self.subTest(version=version):
                proposal = core.prepare(issue(version=version), archive)
                self.assertEqual((proposal['state'], proposal['reason']),
                                 ('MANUAL_REVIEW', 'VERSION_UNKNOWN'))
                self.assertFalse(proposal['measurements'])

        identity = core.catalog()['v0.1.5']
        annotated = ('v0.1.5 (package ' + identity['package_id'] +
                     ') archive SHA-256 ' + identity['archive_sha256'])
        proposal = core.prepare(issue(version=annotated), archive)
        self.assertEqual((proposal['state'], proposal['reason']), ('DATA_READY', 'OK'))

    def test_label_reconciled_dispatch_never_bypasses_intake_approval(self):
        with mock.patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch'}):
            event = {'inputs': {'issue_number': '15', 'intake_mode': 'label-reconciled'}}
            self.assertEqual(core.event_issue(event), (15, False))
            self.assertEqual(core.event_issue({'inputs': {'issue_number': '15'}}),
                             (15, True))  # Existing explicit manual route.
            with self.assertRaises(core.Refused):
                core.event_issue({'inputs': {'issue_number': '15',
                                             'intake_mode': 'invalid'}})
        current = issue(number=15)
        current.update(author_association='NONE', labels=['benchmark:submission'])
        with self.assertRaisesRegex(core.Refused, '^AWAITING_INTAKE_APPROVAL$'):
            core.eligible(current, manual=False)

        # Test the actual workflow consumer, not just the boolean helper.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            event_file = root / 'automatic-dispatch.json'
            event_file.write_text(json.dumps(event))
            proposal_file = root / 'proposal.json'
            summary = root / 'summary.md'
            ready_output = root / 'ready-output'
            with mock.patch.dict(os.environ, {
                'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_REPOSITORY': core.REPOSITORY,
                'GH_TOKEN': 'FAKE',
                'GITHUB_OUTPUT': str(ready_output),
                'GITHUB_STEP_SUMMARY': str(summary),
            }), mock.patch.object(core, 'GitHub') as api, \
                 mock.patch('sys.stdout', new_callable=io.StringIO):
                api.return_value.get.return_value = current
                self.assertEqual(core.prepare_main([
                    '--event', str(event_file), '--output', str(proposal_file)]), 0)
            self.assertFalse(proposal_file.exists())
            self.assertFalse(ready_output.exists())
            self.assertIn('AWAITING_INTAKE_APPROVAL', summary.read_text())

    def test_unapproved_and_closed_issues_report_visible_reason_without_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            event = root / 'event.json'
            event.write_text(json.dumps({'issue': {'number': 15}}))
            for state, reason in (('open', 'AWAITING_INTAKE_APPROVAL'),
                                  ('closed', 'NOT_ELIGIBLE')):
                with self.subTest(state=state):
                    summary = root / ('summary-' + state)
                    output = root / ('output-' + state)
                    current = issue(number=15)
                    current.update(author_association='NONE', state=state,
                                   labels=['benchmark:submission'])
                    with mock.patch.dict(os.environ, {
                        'GITHUB_EVENT_NAME': 'issues',
                        'GITHUB_REPOSITORY': 'GoblinFlash/Native-DX12-Linux',
                        'GH_TOKEN': 'FAKE',
                        'GITHUB_OUTPUT': str(root / 'ghoutput'),
                        'GITHUB_STEP_SUMMARY': str(summary),
                    }), mock.patch.object(core, 'GitHub') as api, \
                         mock.patch('sys.stdout', new_callable=io.StringIO) as printed:
                        api.return_value.get.return_value = current
                        self.assertEqual(core.prepare_main(['--event', str(event),
                            '--output', str(output)]), 0)
                    self.assertFalse(output.exists())
                    self.assertIn(reason, printed.getvalue())
                    self.assertIn(reason, summary.read_text())
                    self.assertIn('UNVERIFIED', summary.read_text())

    def test_issue_form_prevents_benchmark_version_typo(self):
        form = (ROOT / '.github/ISSUE_TEMPLATE/benchmark_results.yml').read_text()
        self.assertIn('  - type: dropdown\n    id: version', form)
        self.assertIn('        - v0.1.5', form)
        self.assertIn('        - v0.1.4', form)


if __name__ == '__main__':
    unittest.main()
