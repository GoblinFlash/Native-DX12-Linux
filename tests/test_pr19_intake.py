"""CPU-only regressions for reviewed PR19 index and orphan-recovery defects."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_community_intake import ROOT, FakeAPI, bundle, core, issue, raw_files, ready, writer, index_fixture
import test_community_intake as fixtures


class PR19Tests(unittest.TestCase):
    def test_live_indexes_have_managed_markers(self):
        """Live indexes may gain content; their managed marker contract remains visible."""
        for path in writer.INDEXES:
            body = (ROOT/path).read_text()
            self.assertEqual(body.count(writer.INDEX_START), 1)
            self.assertEqual(body.count(writer.INDEX_END), 1)

    def test_index_tests_survive_live_issue15_merge(self):
        """Normal live index content changes must not alter the writer's pinned test scenario."""
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp)
            p = core.prepare(issue(15, 'RTX 4060'), bundle(raw_files(gpu='NVIDIA GeForce RTX 4060')))
            for path, (anchor, prefix) in writer.INDEXES.items():
                content = writer.update_index(index_fixture(path), p, anchor, prefix)
                target = live/path;target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(content)
            with mock.patch.object(fixtures, 'ROOT', live), mock.patch(__name__ + '.ROOT', live):
                self.test_live_indexes_have_managed_markers()
                for path in writer.INDEXES:
                    self.assertIn('issue-15/README.md', (ROOT/path).read_text())
                fixtures.PublisherTests('test_issue_15_links_are_added_only_with_the_record').test_issue_15_links_are_added_only_with_the_record()
                self.test_issue15_is_created_with_its_indexes_in_one_draft()

    def test_updated_index_exact_byte_boundary(self):
        """The inclusive UTF-8 limit admits exactly128KiB and refuses the next byte."""
        for path, (anchor, prefix) in writer.INDEXES.items():
            with self.subTest(path=path):
                source = index_fixture(path)
                output = writer.update_index(source, ready(), anchor, prefix)
                padding = b'x'*(128*1024-len(output))
                self.assertEqual(len(writer.update_index(padding+source, ready(), anchor, prefix)),
                                 128*1024)
                with self.assertRaisesRegex(core.Refused, '^INDEX_FORMAT$'):
                    writer.update_index(b'x'+padding+source, ready(), anchor, prefix)

    def test_exact_pre_migration_blobs_through_publisher(self):
        """Real writer bootstraps both pinned historical indexes with their prose intact."""
        api = FakeAPI(); original = {}
        for path, (_anchor, prefix) in writer.INDEXES.items():
            name = 'results' if prefix else 'community'
            raw = (ROOT/'tests/fixtures'/('pre-index-'+name+'.md')).read_bytes()
            original[path] = raw
            object_id = writer.git_blob(raw)
            api.blobs[object_id] = raw.decode()
            next(row for row in api.entries if row['path'] == path)['sha'] = object_id
        self.assertEqual(writer.publish(ready(), api, 12)['status'], 'DRAFT_PR_CREATED')
        for path, raw in original.items():
            row = next(row for row in api.trees['c'*40] if row['path'] == path)
            changed = api.blobs[row['sha']].encode()
            self.assertIn(writer.INDEX_START.encode(), changed)
            for line in raw.splitlines():
                self.assertIn(line, changed)

    def test_output_limit_in_both_insertion_paths(self):
        """Oversized UTF-8 output fails before API writes, including initial bootstrap."""
        for bootstrap in (False, True):
            with self.subTest(bootstrap=bootstrap):
                api = FakeAPI()
                path, (anchor, prefix) = next(iter(writer.INDEXES.items()))
                source = index_fixture(path).decode()
                if bootstrap:
                    start = source.index('\n## Automated community intake')
                    stop = source.index(anchor, start)
                    source = source[:start] + source[stop:]
                raw = source.encode()
                # Stay within the input limit; use non-ASCII bytes to test encoded size.
                raw = ('é' * ((128 * 1024-len(raw)-2)//2)).encode() + b'\n' + raw
                object_id = writer.git_blob(raw)
                api.blobs[object_id] = raw.decode()
                next(row for row in api.entries if row['path'] == path)['sha'] = object_id
                mapping = {prefix: (object_id, anchor)}
                with mock.patch.object(writer, 'INDEX_BOOTSTRAP', mapping, create=True):
                    with self.assertRaisesRegex(core.Refused, '^INDEX_FORMAT$'):
                        writer.publish(ready(), api, 12)
                self.assertEqual(api.writes, [])

    def test_missing_both_markers_is_not_an_implicit_bootstrap(self):
        """A hand-edited marker-free index is refused through the real publisher."""
        api = FakeAPI()
        path, (anchor, _prefix) = next(iter(writer.INDEXES.items()))
        body = index_fixture(path).decode()
        start = body.index('\n## Automated community intake'); stop = body.index(anchor, start)
        raw = (body[:start] + body[stop:]).encode()
        object_id = writer.git_blob(raw)
        api.blobs[object_id] = raw.decode()
        next(row for row in api.entries if row['path'] == path)['sha'] = object_id
        with self.assertRaisesRegex(core.Refused, '^INDEX_FORMAT$'):
            writer.publish(ready(), api, 12)
        self.assertEqual(api.writes, [])

    def test_orphan_retry_checks_current_main_for_collisions(self):
        """Advancing main with a lone summary or aliased parent blocks recovery writes."""
        for ancestor_alias in (False, True):
            with self.subTest(ancestor_alias=ancestor_alias):
                api = FakeAPI(); proposal = ready(); api.fail_pr_once = True
                with self.assertRaisesRegex(core.Refused, '^API_403$'):
                    writer.publish(proposal, api, 12)
                historical = copy.deepcopy(api.entries)
                folder = core.record_folder(proposal)
                collision = {'path': folder if ancestor_alias else folder+'/summary.csv',
                             'type': 'blob', 'mode': '120000' if ancestor_alias else '100644',
                             'sha': 'f'*40}
                current = historical + [collision]
                api.base = 'e'*40
                previous_get = api.get
                def get(endpoint):
                    """Supply distinct current and historical Git trees without altering the orphan."""
                    if endpoint == 'git/commits/'+api.base:
                        return {'tree': {'sha': '7'*40}}
                    if endpoint == 'git/trees/'+'7'*40+'?recursive=1':
                        return {'truncated': False, 'tree': copy.deepcopy(current)}
                    return previous_get(endpoint)
                api.get = get
                before = len(api.writes)
                with self.assertRaisesRegex(core.Refused, '^BASE_OUTPUT_COLLISION$'):
                    writer.publish(proposal, api, 12)
                self.assertEqual(len(api.writes), before)
                self.assertEqual(api.prs, [])

    def test_issue15_is_created_with_its_indexes_in_one_draft(self):
        """No dangling Issue15 seed may block a validated real intake and index generation."""
        current = issue(15, 'RTX 4060', 'v0.1.5')
        proposal = core.prepare(current, bundle(raw_files('v0.1.5', 'NVIDIA GeForce RTX 4060')))
        api = FakeAPI(current=current)
        result = writer.publish(proposal, api, 15)
        self.assertEqual(result['status'], 'DRAFT_PR_CREATED')
        folder = core.record_folder(proposal)
        self.assertIn(folder+'/README.md', result['files'])
        for path, (_anchor, prefix) in writer.INDEXES.items():
            self.assertNotIn(b'issue-15/README.md', index_fixture(path))
            row = next(row for row in api.trees['c'*40] if row['path'] == path)
            self.assertIn(writer.index_entry(proposal, prefix), api.blobs[row['sha']])


if __name__ == '__main__':
    unittest.main()
