"""CPU-only integration checks for aggregate refresh in the existing draft writer."""
import copy
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
    for path in (ROOT / 'Experiment Results').rglob('*'):
        if path.is_file() and path.suffix in ('.md', '.json', '.csv', '.svg'):
            put(api, path.relative_to(ROOT).as_posix(), path.read_bytes())
    return api


def draft_files(api):
    """Observe the actual proposed Git tree's output content."""
    return {row['path']: api.blobs[row['sha']].encode() for row in api.trees['c' * 40]}


class AggregateTests(unittest.TestCase):
    def test_new_record_and_its_version_report_are_in_the_same_draft(self):
        """A successful draft must include the new record, overview table and release report."""
        api = FakeAPI()
        result = writer.publish(ready(), api, 12)
        self.assertEqual(result['status'], 'DRAFT_PR_CREATED')
        entries = {row['path']: row for row in api.trees['c' * 40]}
        report = 'Experiment Results/Community/v0.1.5-submitted-data.md'
        self.assertIn(report, entries)
        self.assertIn('Issue #12', api.blobs[entries[report]['sha']])
        root = api.blobs[entries['Experiment Results/README.md']['sha']]
        self.assertIn('| GPU | Exported process status |', root)
        self.assertIn('v0.1.5-submitted-data.md', root)

    def test_issue_11_conflict_explains_duplicate_and_required_correction(self):
        """A shared bundle cannot supply RTX3090 values; changing its name is no correction."""
        proposals = [core.load_json((ROOT / core.ROOT / name).read_bytes()) for name in (
            'NVIDIA/RTX_3060/v0.1.5/issue-10/record.json',
            'Pending_Classification/v0.1.5/issue-11/record.json')]
        docs = aggregate.document_set('v0.1.5', proposals, core)
        text = docs[core.ROOT + 'v0.1.5-submitted-data.md'][0].decode()
        self.assertIn('identical to Issue #10', text)
        self.assertIn('10de:2503', text)
        self.assertIn('genuine share-results bundle', text)
        self.assertIn('Renaming', text)
        self.assertNotIn('RTX_3090/v0.1.5/issue-11/chart.svg', text)

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
        self.assertIn(b'5 public submissions checked', files[path])
        self.assertIn(b'Issue #12', files[path])
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
        put(api, path, api.blobs[old['sha']].replace('20,416', '20,417', 1))
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
        self.assertIn(b'Issue #10:', index)
        self.assertIn(b'Issue #12:', index)
        report = files[core.ROOT + 'v0.1.5-submitted-data.md']
        self.assertIn(b'rtx-3060--issue-10', report)
        self.assertIn(b'rtx-3060--issue-12', report)

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
        self.assertIn(b'Native DX12 memory backing: UNKNOWN',
                      files[core.ROOT + 'v0.1.6-submitted-data.md'])
        root = files['Experiment Results/README.md']
        self.assertIn('## Community Benchmark Data — v0.1.6'.encode(), root)
        self.assertIn('## Community Benchmark Data — v0.1.5'.encode(), root)
        self.assertIn(b'Individual intake records (all benchmark versions)', root)
        for name, oid in before.items():
            if name.startswith(core.ROOT) and '/README.md' not in name and name not in writer.INDEXES:
                self.assertEqual(writer.git_blob(files[name]), oid, name)

    def test_v14_additions_do_not_touch_curated_v14_report_or_indexes(self):
        """Historical v0.1.4 has a separate additional-intake report and GPU index."""
        api = seeded();api.issue = issue(version='v0.1.4')
        curated = core.ROOT + 'v0.1.4-submitted-data.md'
        owner_notes = b'Owner note: retain the curated measurements.\n'
        put(api, curated, owner_notes + (ROOT / curated).read_bytes())
        before = {r['path']: api.blobs[r['sha']].encode() for r in api.entries
                  if '/v0.1.4' in r['path']}
        p = core.prepare(api.issue, bundle(raw_files('v0.1.4')))
        writer.publish(p, api, 12)
        files = draft_files(api)
        self.assertIn(core.ROOT + 'v0.1.4-intake-data.md', files)
        self.assertIn(core.ROOT + 'NVIDIA/RTX_3090/v0.1.4/intake-README.md', files)
        report = files[core.ROOT + 'v0.1.4-intake-data.md']
        self.assertIn(b'(v0.1.4-intake-data.md#rtx-3090--issue-12)', report)
        self.assertNotIn(b'v0.1.4-submitted-data.md#', report)
        self.assertIn('## RTX 3090 — [Issue #12]'.encode(), report)
        for name, raw in before.items():
            self.assertEqual(files[name], raw, name)
        for name in ('Experiment Results/README.md', core.ROOT + 'README.md'):
            old = (ROOT / name).read_bytes()
            heading = (b'\n## Community Benchmark Data ' + '— v0.1.4'.encode() if
                       name.startswith('Experiment Results/README') else b'\n## Curated v0.1.4 report')
            self.assertEqual(files[name][files[name].index(heading):], old[old.index(heading):])

    def test_unknown_release_remains_individual_manual_record(self):
        """No arbitrary unrecognized release path is created."""
        api = FakeAPI(issue(version='v9.9.9'))
        p = core.prepare(api.issue, bundle())
        result = writer.publish(p, api, 12)
        self.assertEqual(len(result['files']), 5)
        self.assertFalse(any('v9.9.9' in name for name in result['files']))

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
            put(api, core.ROOT + 'NVIDIA/RTX_3090/v0.1.5/issue-' + str(n) + '/record.json', '{}')
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
        put(api, core.ROOT + 'NVIDIA/RTX_3090/v0.1.5/issue-13/record.json',
            core.json_bytes(ready(13)))
        api.base, api.base_tree = 'e'*40, 'f'*40
        api.trees[api.base_tree] = api.entries
        old_writes = len(api.writes)
        with self.assertRaisesRegex(core.Refused, '^EXISTING_BRANCH_CHANGED$'):
            writer.publish(ready(), api, 12)
        self.assertEqual(len(api.writes), old_writes)

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
                    del files[removed]
                    api.entries[:] = [r for r in api.entries if r['path'] != removed]
                    proposals = aggregate.records(api, api.entries, 'v0.1.5', core)
                    self.assertEqual(len(proposals), 3)
                    for name, (raw, key) in aggregate.document_set('v0.1.5', proposals, core).items():
                        files[name] = aggregate.wrap(raw, key)
                    for name, prefix in [('Experiment Results/README.md', 'Community/'),
                                         (core.ROOT + 'README.md', '')]:
                        files[name] = aggregate.wrap(aggregate.overview('v0.1.5', proposals, prefix, core),
                                                     'overview:v0.1.5')
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
                             {'status': 'AGGREGATES_CURRENT', 'versions': ['v0.1.5']})
            self.assertEqual(files, {p.relative_to(root).as_posix(): p.read_bytes()
                                     for p in root.rglob('*') if p.is_file()})



if __name__ == '__main__':
    unittest.main()
