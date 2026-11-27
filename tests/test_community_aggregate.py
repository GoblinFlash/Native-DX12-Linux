"""CPU-only integration checks for aggregate refresh in the existing draft writer."""
import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_community_intake import ROOT, FakeAPI, ready, writer, core, issue, bundle, raw_files


aggregate = writer.aggregate


def put(api, name, data):
    """Seed actual base-tree bytes without invoking the simulated write endpoints."""
    raw = data.encode() if isinstance(data, str) else data
    oid = writer.git_blob(raw)
    api.blobs[oid] = raw.decode()
    api.entries[:] = [row for row in api.entries if row['path'] != name]
    api.entries.append({'path': name, 'sha': oid, 'mode': '100644', 'type': 'blob'})


def seeded():
    """Use the current exported candidate as the consumer's base-tree fixture."""
    api = FakeAPI()
    for path in (ROOT / 'Benchmark Results').rglob('*'):
        if path.is_file() and path.suffix in ('.md', '.json', '.csv', '.svg'):
            put(api, path.relative_to(ROOT).as_posix(), path.read_bytes())
    return api


def draft_files(api):
    """Observe the actual proposed Git tree's output content."""
    return {row['path']: api.blobs[row['sha']].encode() for row in api.trees['c' * 40]}


class AggregateTests(unittest.TestCase):
    def test_every_published_chart_matches_its_own_record(self):
        api = seeded()
        for version in ('v0.1.4', 'v0.1.5'):
            for proposal in aggregate.records(api, api.entries, version, core):
                folder = core.record_folder(proposal)
                with self.subTest(run=folder):
                    rendered = core.render(proposal)
                    for name, data in rendered.items():
                        if name.endswith(('.svg', '/README.md')):
                            self.assertEqual((ROOT / name).read_bytes(), data, name)
                    self.assertEqual(len(core.summaries(proposal)), 27)

    def test_matching_exports_without_measurements_are_not_counted_as_measured(self):
        """A validated failed-to-start export reaches the writer without invented samples."""
        for empty in (False, True):
            with self.subTest(empty=empty):
                files = raw_files()
                source = issue()
                if empty:
                    run = json.loads(files['run.json'])
                    run['run'].update(overall='FAILED', completed=[], not_started=list(core.SUITES),
                                      failed={'reason': 'Synthetic failed start'})
                    for counts in [run['totals']] + [step['counts'] for step in run['steps']]:
                        counts.update(completed=0, verified=0, not_run=counts['expected'])
                    for step in run['steps']:
                        step['status'] = 'NOT_RUN'
                    rows = list(csv.DictReader(io.StringIO(files['processes.csv'].decode())))
                    for row in rows:
                        row.update(status='NOT_RUN', submission='NOT_RUN', completion='NOT_RUN',
                                   correctness='NOT_RUN', timing='NOT_RUN')
                    files['run.json'] = core.json_bytes(run)
                    files['processes.csv'] = core.csv_text(rows, core.PROCESS_COLUMNS)
                    for name in list(files):
                        if name.endswith('.csv') and name != 'processes.csv':
                            del files[name]
                    source['body'] = source['body'].replace('Full test completed', 'Failed or refused to start')
                proposal = core.validate_proposal(core.prepare(source, bundle(files)))
                self.assertEqual(proposal['state'], 'DATA_READY')
                self.assertEqual(bool(proposal['measurements']), not empty)
                api = FakeAPI(current=source)
                result = writer.publish(proposal, api, 12)
                if empty:
                    self.assertEqual(result['reason'], 'NO_MEASUREMENTS')
                    self.assertEqual(result['status'], 'ISSUE_ONLY')
                    self.assertEqual(core.render(proposal), {})
                    self.assertEqual(aggregate.document_set('v0.1.5', [proposal], core), {})
                    self.assertEqual(api.writes, [])
                else:
                    self.assertEqual(result['status'], 'DRAFT_PR_CREATED')
                    for name in writer.INDEXES:
                        self.assertIn(b'issue-12/README.md', draft_files(api)[name])

    def test_new_record_and_its_version_report_are_in_the_same_draft(self):
        """A successful draft must include the new record, overview table and release report."""
        api = FakeAPI()
        result = writer.publish(ready(), api, 12)
        self.assertEqual(result['status'], 'DRAFT_PR_CREATED')
        entries = {row['path']: row for row in api.trees['c' * 40]}
        report = 'Benchmark Results/v0.1.5-submitted-data.md'
        self.assertIn(report, entries)
        self.assertIn('issue-12/kw-chart.svg', api.blobs[entries[report]['sha']])
        root = api.blobs[entries['Benchmark Results/README.md']['sha']]
        self.assertIn('NVIDIA GeForce RTX 3060 Ti', root)
        self.assertIn('v0.1.5-submitted-data.md', root)

    def test_conflicting_submission_is_omitted_from_all_release_documents(self):
        measured = ready(10)
        conflict = core.prepare(issue(11, 'RTX 3060'), bundle())
        self.assertEqual(conflict['reason'], 'GPU_MISMATCH')
        self.assertEqual(aggregate.document_set('v0.1.5', [measured, conflict], core),
                         aggregate.document_set('v0.1.5', [measured], core))

    def test_real_records_refresh_and_preserve_prior_data_and_owner_notes(self):
        """Actual v2 and pinned legacy15 sources feed one release refresh without old-data rewrites."""
        api = seeded()
        path = core.ROOT + 'v0.1.5-submitted-data.md'
        old = next(r for r in api.entries if r['path'] == path)
        put(api, path, 'Owner acceptance: Andrew approved Issue #10 separately.\n' +
            api.blobs[old['sha']] + '\nOwner note: retain background contention caveat.\n')
        before = {r['path']: r['sha'] for r in api.entries}
        result = writer.publish(ready(), api, 12)
        files = draft_files(api)
        self.assertEqual(result['status'], 'DRAFT_PR_CREATED')
        count = len(aggregate.records(api, api.entries, 'v0.1.5', core)) + 1
        self.assertEqual(files[path].count(b'!['), 4 * count)
        self.assertIn(b'issue-12/kw-chart.svg', files[path])
        self.assertTrue(files[path].startswith(b'Owner acceptance: Andrew approved'))
        self.assertTrue(files[path].endswith(b'Owner note: retain background contention caveat.\n'))
        for name, oid in before.items():
            if '/issue-' in name or '/v0.1.4' in name or '/charts/' in name:
                self.assertEqual(writer.git_blob(files[name]), oid, name)
        self.assertNotIn('acceptance: ACCEPTED', files[path].decode())

    def test_hand_edit_in_managed_report_stops_before_any_write(self):
        """A maintainer's edit inside generated content cannot silently disappear."""
        api = seeded()
        path = core.ROOT + 'v0.1.5-submitted-data.md'
        old = next(r for r in api.entries if r['path'] == path)
        put(api, path, api.blobs[old['sha']].replace('issue-10/chart.svg', 'issue-10/wrong.svg', 1))
        with self.assertRaisesRegex(core.Refused, '^AGGREGATE_EDITED$'):
            writer.publish(ready(), api, 12)
        self.assertEqual(api.writes, [])

    def test_malformed_and_unpinned_legacy_sources_fail_before_writes(self):
        """Malformed JSON shapes, wrong record identity and legacy byte drift stay manual."""
        name = core.ROOT + 'NVIDIA/RTX_3060/v0.1.5/issue-10/record.json'
        for value in ([], None, dict(ready(10), claimed_gpu=None)):
            with self.subTest(value_type=type(value).__name__):
                api = seeded();put(api, name, core.json_bytes(value))
                with self.assertRaises(core.Refused): writer.publish(ready(), api, 12)
                self.assertEqual(api.writes, [])
        api = seeded()
        legacy = core.ROOT + 'NVIDIA/RTX_4060/v0.1.5/issue-15/record.json'
        original = next(r for r in api.entries if r['path'] == legacy)
        put(api, legacy, api.blobs[original['sha']] + ' ')
        with self.assertRaisesRegex(core.Refused, '^AGGREGATE_LEGACY_RECORD$'):
            writer.publish(ready(), api, 12)
        self.assertEqual(api.writes, [])

    def test_same_gpu_has_two_issue_sections_and_one_version_index(self):
        """Same-GPU submissions append Issue-specific observations, never average them together."""
        api = seeded()
        submitted = issue(12, 'RTX 3060')
        api.issue = submitted
        p = core.prepare(submitted, bundle(raw_files(gpu='NVIDIA GeForce RTX 3060')))
        writer.publish(p, api, 12)
        files = draft_files(api)
        index = files[core.ROOT + 'NVIDIA/RTX_3060/v0.1.5/README.md']
        self.assertIn(b'](issue-10/chart.svg)', index)
        self.assertIn(b'](issue-12/chart.svg)', index)
        main = files[core.ROOT + 'NVIDIA/RTX_3060/README.md']
        self.assertEqual(main.count(b'[v0.1.5](v0.1.5/)'), 1)
        self.assertNotIn(b'![', main)
        report = files[core.ROOT + 'v0.1.5-submitted-data.md']
        self.assertIn(b'RTX_3060/v0.1.5/issue-10/chart.svg', report)
        self.assertIn(b'RTX_3060/v0.1.5/issue-12/chart.svg', report)

    def test_future_release_has_separate_section_and_unknown_memory(self):
        """Catalogue admission alone does not invent future memory-backing evidence."""
        api = seeded();api.issue = issue(version='v0.1.6')
        p = ready();p['claimed_version'] = p['archive_version'] = 'v0.1.6'
        p['source_revision'] = core.issue_fingerprint(api.issue)
        catalogue = copy.deepcopy(core.catalog())
        catalogue['v0.1.6'] = catalogue['v0.1.5']
        before = {r['path']:r['sha'] for r in api.entries}
        with patch.object(core, 'catalog', return_value=catalogue):
            writer.publish(p, api, 12)
        files = draft_files(api)
        self.assertEqual(json.loads(files[core.ROOT + 'NVIDIA/RTX_3060_Ti/v0.1.6/issue-12/memory-backing.json'])['native_dx12']['backing'],
                         'UNKNOWN')
        root = files['Benchmark Results/README.md']
        self.assertEqual(root.count('## Community Benchmark Data — v0.1.6'.encode()), 1)
        self.assertIn('## Community Benchmark Data — v0.1.5'.encode(), root)
        self.assertIn(b'Individual runs', root)
        for name, oid in before.items():
            if name.startswith(core.ROOT) and '/README.md' not in name and name not in writer.INDEXES:
                self.assertEqual(writer.git_blob(files[name]), oid, name)

    def test_release_overview_joins_an_existing_unmarked_section(self):
        """A manually archived run keeps its line; the generated block goes under the same heading."""
        raw = ('# Benchmark Results\n\n## Community Benchmark Data — v0.1.6\n\n- [Archived run](a/README.md)\n\n'
               '## Community Benchmark Data — v0.1.5\n').encode()
        updated = aggregate.update_overview(raw, 'v0.1.6', [ready()], [], '', core)
        self.assertEqual(updated.count('## Community Benchmark Data — v0.1.6'.encode()), 1)
        start = updated.index(b'<!-- ndx12:overview:v0.1.6:start -->')
        self.assertLess(updated.index('— v0.1.6\n'.encode()), start)
        self.assertLess(start, updated.index(b'- [Archived run]'))
        self.assertTrue(updated.endswith(b'- [Archived run](a/README.md)\n\n## Community Benchmark Data \xe2\x80\x94 v0.1.5\n'))

    def test_v14_additions_share_the_existing_version_and_preserve_old_runs(self):
        api = seeded()
        api.issue = issue(version='v0.1.4')
        release = core.ROOT + 'v0.1.4-submitted-data.md'
        put(api, release, b'Owner note.\n' + (ROOT / release).read_bytes())
        previous = {r['path']: r['sha'] for r in api.entries if '/issue-' in r['path']}
        writer.publish(core.prepare(api.issue, bundle(raw_files('v0.1.4'))), api, 12)
        files = draft_files(api)
        self.assertTrue(files[release].startswith(b'Owner note.\n'))
        page = files[core.ROOT + 'NVIDIA/RTX_3060_Ti/v0.1.4/README.md']
        self.assertIn(b'](issue-3/chart.svg)', page)
        self.assertIn(b'](issue-12/chart.svg)', page)
        for name, oid in previous.items():
            self.assertEqual(writer.git_blob(files[name]), oid)

    def test_unknown_release_remains_in_issues(self):
        """No arbitrary unrecognized release path is created."""
        api = FakeAPI(issue(version='v9.9.9'))
        p = core.prepare(api.issue, bundle())
        result = writer.publish(p, api, 12)
        self.assertEqual(result['status'], 'ISSUE_ONLY')
        self.assertEqual(api.writes, [])

    def test_oversized_record_and_too_many_records_are_rejected(self):
        """Count and byte ceilings apply before any remote write."""
        api = seeded()
        put(api, core.ROOT + 'NVIDIA/RTX_3060/v0.1.5/issue-10/record.json',
            'x' * (core.MAX_PROPOSAL + 1))
        with self.assertRaisesRegex(core.Refused, '^AGGREGATE_BLOB$'):
            writer.publish(ready(), api, 12)
        self.assertEqual(api.writes, [])
        api = FakeAPI()
        for n in range(100, 133):
            put(api, core.ROOT + 'NVIDIA/RTX_3060_Ti/v0.1.5/issue-' + str(n) + '/record.json', '{}')
        with self.assertRaisesRegex(core.Refused, '^AGGREGATE_RECORD_LIMIT$'):
            writer.publish(ready(), api, 12)
        self.assertEqual(api.writes, [])

    def test_retry_with_existing_aggregate_is_exact_and_idempotent(self):
        """The expanded file plan remains recoverable after a PR API failure."""
        api = seeded();api.fail_pr_once = True
        with self.assertRaisesRegex(core.Refused, '^API_403$'):
            writer.publish(ready(), api, 12)
        old_writes = len(api.writes)
        result = writer.publish(ready(), api, 12)
        self.assertEqual(result['status'], 'DRAFT_PR_CREATED')
        self.assertEqual([name for name, _ in api.writes[old_writes:]], ['pulls'])
        old_writes = len(api.writes)
        self.assertEqual(writer.publish(ready(), api, 12)['status'], 'EXISTING_PR_REQUIRES_REVIEW')
        self.assertEqual(len(api.writes), old_writes)

    def test_advanced_main_aggregate_source_stops_orphan_recovery(self):
        """A stale orphan cannot hide a concurrently merged record in a fresh-looking report."""
        api = seeded();api.fail_pr_once = True
        with self.assertRaises(core.Refused): writer.publish(ready(), api, 12)
        api.entries = copy.deepcopy(api.entries)
        put(api, core.ROOT + 'NVIDIA/RTX_3060_Ti/v0.1.5/issue-13/record.json',
            core.json_bytes(ready(13)))
        api.base, api.base_tree = 'e'*40, 'f'*40
        api.trees[api.base_tree] = api.entries
        old_writes = len(api.writes)
        with self.assertRaisesRegex(core.Refused, '^EXISTING_BRANCH_CHANGED$'):
            writer.publish(ready(), api, 12)
        self.assertEqual(len(api.writes), old_writes)

    def test_orphan_recovery_requires_unchanged_managed_index_blobs(self):
        """An unrelated main change is legal; either edited index prevents stale recovery."""
        for changed_index in (None, *writer.INDEXES):
            with self.subTest(changed_index=changed_index):
                api = seeded();api.fail_pr_once = True
                proposal = ready()
                with self.assertRaisesRegex(core.Refused, '^API_403$'):
                    writer.publish(proposal, api, 12)
                api.entries = copy.deepcopy(api.entries)
                if changed_index is None:
                    put(api, 'docs/unrelated-owner-note.md', b'# Unrelated owner note\n')
                else:
                    row = next(r for r in api.entries if r['path'] == changed_index)
                    put(api, changed_index, api.blobs[row['sha']] + '\nOwner note added on main.\n')
                api.base, api.base_tree = 'e' * 40, 'f' * 40
                api.trees[api.base_tree] = api.entries
                before = len(api.writes)
                if changed_index is None:
                    self.assertEqual(writer.publish(proposal, api, 12)['status'], 'DRAFT_PR_CREATED')
                    self.assertEqual([name for name, _ in api.writes[before:]], ['pulls'])
                else:
                    with self.assertRaisesRegex(core.Refused, '^EXISTING_BRANCH_CHANGED$'):
                        writer.publish(proposal, api, 12)
                    self.assertEqual(len(api.writes), before)
                    self.assertEqual(api.prs, [])

    def test_local_check_detects_stale_concurrent_merge_without_writes(self):
        """Two snapshot-valid drafts can combine into a stale aggregate; the verifier rejects it."""
        first = seeded();writer.publish(ready(), first, 12)
        second = seeded();second.issue = issue(13);writer.publish(ready(13), second, 13)
        merged = draft_files(first)
        for name in next(data['tree'] for endpoint, data in second.writes if endpoint == 'git/trees'):
            merged[name['path']] = second.blobs[name['sha']].encode()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, raw in merged.items():
                path = root / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(raw)
            before = {p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(core.Refused, '^AGGREGATE_EDITED$'):
                aggregate.verify(root, core)
            self.assertEqual(before, {p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()})


    def test_aggregate_growth_cannot_exceed_final_index_limit(self):
        """A pre-update index fitting 128KiB must not publish a larger final aggregate."""
        for name, (anchor, prefix) in writer.INDEXES.items():
            with self.subTest(index=name):
                api = seeded();row = next(x for x in api.entries if x['path'] == name)
                old = api.blobs[row['sha']].encode()
                length = len(writer.update_index(old, ready(), anchor, prefix))
                put(api, name, b'x' * (128 * 1024 - 1 - length) + old)
                with self.assertRaisesRegex(core.Refused, '^INDEX_FORMAT$'):
                    writer.publish(ready(), api, 12)
                self.assertEqual(api.writes, [])

    def test_local_checker_rejects_missing_inputs_and_unbacked_generated_content(self):
        """Missing directories or deleted last source records cannot yield an empty green check."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(core.Refused, '^AGGREGATE_LOCAL_INPUT$'):
                aggregate.verify(Path(tmp), core)
        for retained in ('overview', 'report', 'gpu', 'both'):
            with self.subTest(retained=retained), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in writer.INDEXES:
                    path = root / name;path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes((ROOT / name).read_bytes() if retained not in ('report', 'gpu') else b'# Results\n')
                if retained not in ('overview', 'gpu'):
                    name = core.ROOT + 'v0.1.5-submitted-data.md'
                    path = root / name;path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes((ROOT / name).read_bytes())
                if retained == 'gpu':
                    name = core.ROOT + 'NVIDIA/RTX_3060/v0.1.5/README.md'
                    path = root / name;path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes((ROOT / name).read_bytes())
                with self.assertRaisesRegex(core.Refused, '^AGGREGATE_SOURCE_MISSING$'):
                    aggregate.verify(root, core)

    def test_local_checker_rejects_orphan_documents_with_other_records_remaining(self):
        """Refreshing the remaining release must not hide an obsolete managed GPU index."""
        for orphan in ('gpu', 'report'):
            with self.subTest(orphan=orphan), tempfile.TemporaryDirectory() as tmp:
                api = seeded()
                files = {r['path']: api.blobs[r['sha']].encode() for r in api.entries}
                if orphan == 'gpu':
                    removed = core.ROOT + 'NVIDIA/RTX_4060/v0.1.5/issue-15/record.json'
                    before = len(aggregate.records(api, api.entries, 'v0.1.5', core))
                    del files[removed]
                    api.entries[:] = [r for r in api.entries if r['path'] != removed]
                    proposals = aggregate.records(api, api.entries, 'v0.1.5', core)
                    self.assertEqual(len(proposals), before - 1)
                    for name, (raw, key) in aggregate.document_set('v0.1.5', proposals, core).items():
                        start, end = (x.encode() for x in aggregate.markers(key))
                        old = files[name]
                        files[name] = (old[:old.index(start)] + aggregate.wrap(raw, key).rstrip() +
                                       old[old.index(end) + len(end):])
                    for name in writer.INDEXES:
                        key = 'overview:v0.1.5'
                        old = files[name]
                        start, end = (x.encode() for x in aggregate.markers(key))
                        content = aggregate.overview('v0.1.5', proposals, '', core)
                        files[name] = (old[:old.index(start)] + aggregate.wrap(content, key).rstrip() +
                                       old[old.index(end) + len(end):])
                else:
                    files[core.ROOT + 'v0.1.5-orphan-data.md'] = files[core.ROOT + 'v0.1.5-submitted-data.md']
                root = Path(tmp)
                for name, raw in files.items():
                    path = root / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(raw)
                with self.assertRaisesRegex(core.Refused, '^AGGREGATE_ORPHAN_DOCUMENT$'):
                    aggregate.verify(root, core)
                self.assertEqual(files, {p.relative_to(root).as_posix(): p.read_bytes()
                                         for p in root.rglob('*') if p.is_file()})

    def test_local_checker_preserves_unmarked_curated_history(self):
        """Curated v0.1.4 documents without managed markers do not require intake records."""
        api = seeded()
        files = {r['path']: api.blobs[r['sha']].encode() for r in api.entries}
        files[core.ROOT + 'v0.1.4-owner-data.md'] = b'# Curated history\nOwner notes stay here.\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, raw in files.items():
                path = root / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(raw)
            self.assertEqual(aggregate.verify(root, core),
                             {'status': 'AGGREGATES_CURRENT', 'versions': ['v0.1.4', 'v0.1.5']})
            self.assertEqual(files, {p.relative_to(root).as_posix(): p.read_bytes()
                                     for p in root.rglob('*') if p.is_file()})

    def test_gpu_version_index_keeps_the_curated_introduction(self):
        """The model page lists versions while each version keeps its own benchmarks."""
        api = seeded()
        submitted = issue(12, 'RTX 3060')
        api.issue = submitted
        p = core.prepare(submitted, bundle(raw_files(gpu='NVIDIA GeForce RTX 3060')))
        name = core.ROOT + 'NVIDIA/RTX_3060/README.md'
        before = (ROOT / name).read_bytes()
        writer.publish(p, api, 12)
        page = draft_files(api)[name]
        start, end = (m.encode() for m in aggregate.markers('results:NVIDIA/RTX_3060/v0.1.5'))
        region = page[page.index(start):page.index(end)]
        self.assertIn(b'- [v0.1.5](v0.1.5/)', region)
        self.assertNotIn(b'![', page)
        self.assertNotIn(b'Issue #', page)
        outside = lambda raw: raw[:raw.index(start)] + raw[raw.index(end):]
        self.assertEqual(outside(page), outside(before))
        self.assertIn(b'[v0.1.4](v0.1.4/)', page[page.index(end):])

    def test_gpu_folder_without_main_page_gets_one(self):
        """A first submission for a GPU creates the folder page that shows its results."""
        api = seeded()
        name = core.ROOT + 'NVIDIA/RTX_3060_Ti/README.md'
        api.entries[:] = [r for r in api.entries if r['path'] != name]
        writer.publish(ready(), api, 12)
        page = draft_files(api)[name]
        self.assertTrue(page.startswith(b'# NVIDIA GeForce RTX 3060 Ti\n'))
        self.assertIn(b'[v0.1.5](v0.1.5/)', page)

    def test_hand_edit_in_gpu_results_stops_before_any_write(self):
        """Generated GPU results are checked like the release report; an edit inside them is refused."""
        api = seeded()
        name = core.ROOT + 'NVIDIA/RTX_3060/README.md'
        old = next(r for r in api.entries if r['path'] == name)
        put(api, name, api.blobs[old['sha']].replace('[v0.1.5](v0.1.5/)', '[v0.1.5](bad/)', 1))
        submitted = issue(12, 'RTX 3060')
        api.issue = submitted
        with self.assertRaisesRegex(core.Refused, '^AGGREGATE_EDITED$'):
            writer.publish(core.prepare(submitted, bundle(raw_files(gpu='NVIDIA GeForce RTX 3060'))), api, 12)
        self.assertEqual(api.writes, [])

    def test_local_checker_rejects_edited_or_orphan_gpu_results(self):
        """The pre-merge check covers the GPU pages: edited numbers and results without a record fail."""
        for case in ('edited', 'orphan', 'wrong_gpu_on_valid_page'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for path in (ROOT / 'Benchmark Results').rglob('*'):
                    if path.is_file():
                        target = root / path.relative_to(ROOT)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(path.read_bytes())
                page = root / core.ROOT / 'NVIDIA/RTX_4090/README.md'
                raw = page.read_bytes()
                if case == 'edited':
                    page.write_bytes(raw.replace(b'](v0.1.5/)', b'](v0.1.6/)', 1))
                    reason = '^AGGREGATE_EDITED$'
                elif case == 'orphan':
                    region = raw[raw.index(b'<!-- ndx12:results:'):raw.index(b'v0.1.5:end -->') + 14]
                    other = root / core.ROOT / 'NVIDIA/RTX_4080/README.md'
                    other.parent.mkdir(parents=True)
                    other.write_bytes(b'# RTX 4080\n\n' + region.replace(b'RTX_4090', b'RTX_4080') + b'\n')
                    reason = '^AGGREGATE_ORPHAN_DOCUMENT$'
                else:
                    other = root / core.ROOT / 'NVIDIA/RTX_3060/README.md'
                    other.write_bytes(other.read_bytes() + b'\n' + aggregate.wrap(
                        b'## Unexpected results', 'results:NVIDIA/RTX_4080/v0.1.5'))
                    reason = '^AGGREGATE_ORPHAN_DOCUMENT$'
                self.assertEqual(aggregate.verify(ROOT, core)['status'], 'AGGREGATES_CURRENT')
                with self.assertRaisesRegex(core.Refused, reason):
                    aggregate.verify(root, core)

    def test_newer_release_results_go_above_earlier_ones(self):
        """Insertion order: above earlier results, else before the first section, else at the end."""
        older = aggregate.wrap(b'## Benchmark v0.1.5 results\n', 'results:NVIDIA/RTX_4090/v0.1.5')
        page = b'# RTX 4090\n\nIntro.\n\n' + older + b'\n## Submitting a result\n\nForm.\n'
        updated = aggregate.add_results(page, b'## Benchmark v0.1.6 results\n', 'results:NVIDIA/RTX_4090/v0.1.6', core)
        self.assertLess(updated.index(b'v0.1.6:start'), updated.index(b'v0.1.5:start'))
        self.assertEqual(updated.replace(aggregate.wrap(b'## Benchmark v0.1.6 results\n',
                                                        'results:NVIDIA/RTX_4090/v0.1.6') + b'\n', b'', 1), page)
        newest = aggregate.wrap(b'## Benchmark v0.1.10 results\n', 'results:NVIDIA/RTX_4090/v0.1.10')
        page = b'# RTX 4090\n\n' + newest + older + b'\n## Submitting a result\n'
        middle = aggregate.add_results(page, b'middle\n', 'results:NVIDIA/RTX_4090/v0.1.6', core)
        middle_block = aggregate.wrap(b'middle\n', 'results:NVIDIA/RTX_4090/v0.1.6') + b'\n'
        self.assertEqual(middle, b'# RTX 4090\n\n' + newest + middle_block + older + b'\n## Submitting a result\n')
        oldest = aggregate.add_results(middle, b'oldest\n', 'results:NVIDIA/RTX_4090/v0.1.4', core)
        oldest_block = aggregate.wrap(b'oldest\n', 'results:NVIDIA/RTX_4090/v0.1.4') + b'\n'
        self.assertEqual(oldest, b'# RTX 4090\n\n' + newest + middle_block + older + oldest_block +
                         b'\n## Submitting a result\n')
        first = aggregate.add_results(b'# GPU\n\nIntro.\n\n## Old results\n', b'new\n', 'results:NVIDIA/RTX_4090/v0.1.5', core)
        self.assertLess(first.index(b'v0.1.5:start'), first.index(b'## Old results'))
        plain = aggregate.add_results(b'# GPU\n\nIntro.\n', b'new\n', 'results:NVIDIA/RTX_4090/v0.1.5', core)
        self.assertTrue(plain.startswith(b'# GPU\n\nIntro.\n<!-- ndx12:results:'))
        with self.assertRaisesRegex(core.Refused, '^AGGREGATE_MARKERS$'):
            aggregate.add_results(updated, b'x\n', 'results:NVIDIA/RTX_4090/v0.1.6', core)

    def test_gpu_results_insertion_separates_a_line_without_a_newline(self):
        key = 'results:NVIDIA/RTX_4090/v0.1.6'
        block = aggregate.wrap(b'new\n', key) + b'\n'
        intro = b'# GPU\n\nIntro.'
        older = aggregate.wrap(b'old\n', 'results:NVIDIA/RTX_4090/v0.1.5')
        for suffix in (b'', older):
            with self.subTest(suffix=suffix):
                self.assertEqual(aggregate.add_results(intro + suffix, b'new\n', key, core),
                                 intro + b'\n' + block + suffix)


if __name__ == '__main__':
    unittest.main()
