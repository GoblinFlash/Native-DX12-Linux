"""CPU-only checks for visible charts and distinct export/acceptance statuses."""
import unittest
import xml.etree.ElementTree as ET

from test_community_intake import ROOT, FakeAPI, bundle, core, index_fixture, issue, ready, writer


class DisplayTests(unittest.TestCase):
    def test_nvidia_index_reaches_submitted_4090_report(self):
        """A GPU-model link must reach the actual release report, not a placeholder."""
        index = (ROOT / 'Benchmark Results/NVIDIA/README.md').read_text()
        self.assertIn('[NVIDIA GeForce RTX 4090](RTX_4090/)', index)
        page = ROOT / 'Benchmark Results/NVIDIA/RTX_4090/v0.1.5/README.md'
        self.assertEqual(page.read_text().count('!['), 4)
        self.assertIn('](issue-14/chart.svg)', page.read_text())
        self.assertNotIn('Issue #', page.read_text())

    def test_flat_vendor_layout_preserves_classification_and_existing_issues(self):
        """Results route into GPU folders directly, without a Community directory."""
        self.assertFalse((ROOT / 'Benchmark Results/Community').exists())
        self.assertEqual(core.record_folder(ready()),
                         'Benchmark Results/NVIDIA/RTX_3060_Ti/v0.1.5/issue-12')
        self.assertEqual(core.gpu_category('AMD Radeon RX 7900 XTX'), 'AMD/RX_7900_XTX')
        self.assertEqual(core.gpu_category('Intel Arc A770'), 'Intel/Arc_A770')
        mismatch = core.prepare(issue(gpu='RTX 3060'), bundle())
        self.assertEqual(core.render(mismatch), {})
        paths = [
            'Benchmark Results/NVIDIA/RTX_3090/issue-5.md',
            'Benchmark Results/NVIDIA/RTX_3060/v0.1.5/issue-10/record.json',
        ]
        records = [{'path': path, 'type': 'blob'} for path in paths]
        self.assertTrue(writer.existing_issue(records, 5))
        self.assertTrue(writer.existing_issue(records, 10))
        self.assertFalse(writer.existing_issue(records, 12))

    def test_publisher_embeds_chart_in_report_and_links_both_indexes(self):
        """Keep the prior release's flow: index links lead to a report with its chart."""
        api = FakeAPI()
        writer.publish(ready(), api, 12)
        entries = {row['path']: row for row in api.trees['c' * 40]}
        folder = 'Benchmark Results/NVIDIA/RTX_3060_Ti/v0.1.5/issue-12'
        self.assertIn('![NVIDIA GeForce RTX 3060 Ti · v0.1.5 · Compute suite](chart.svg)',
                      api.blobs[entries[folder + '/README.md']['sha']])
        expected = {
            'Benchmark Results/README.md': 'NVIDIA/RTX_3060_Ti/v0.1.5/issue-12/README.md',
            'Benchmark Results/SUBMISSIONS.md': 'NVIDIA/RTX_3060_Ti/v0.1.5/issue-12/README.md',
        }
        for path, relative in expected.items():
            with self.subTest(path=path):
                text = api.blobs[entries[path]['sha']]
                self.assertIn('v0.1.5](' + relative + ')', text)
        svg = ET.fromstring(api.blobs[entries[folder + '/chart.svg']['sha']])
        self.assertEqual(len(svg.findall('.//{*}g/{*}title')), 6)

    def test_export_checks_do_not_imply_owner_acceptance(self):
        """An eligible Issue's prose/approval label cannot supply an acceptance decision."""
        source = issue()
        source['body'] += '\nOwner acceptance: ACCEPTED. All results independently verified.'
        proposal = core.prepare(source, bundle())
        api = FakeAPI(current=source)
        writer.publish(proposal, api, 12)
        entries = {row['path']: row for row in api.trees['c' * 40]}
        folder = 'Benchmark Results/NVIDIA/RTX_3060_Ti/v0.1.5/issue-12'
        report = api.blobs[entries[folder + '/README.md']['sha']]
        self.assertNotIn('Export consistency:', report)
        self.assertNotIn('Owner acceptance:', report)
        self.assertNotIn('UNVERIFIED', '\n'.join(report.splitlines()[:6]))
        for path in writer.INDEXES:
            with self.subTest(path=path):
                text = api.blobs[entries[path]['sha']]
                managed = text.split(writer.INDEX_START)[1].split(writer.INDEX_END)[0]
                self.assertIn('v0.1.5](', managed)
                self.assertNotIn('owner acceptance', managed)
                self.assertNotIn('**UNVERIFIED**', managed)
        svg = api.blobs[entries[folder + '/chart.svg']['sha']]
        self.assertIn('independent scale', svg)
        self.assertEqual(api.blobs[entries[folder + '/record.json']['sha']], core.json_bytes(proposal).decode())
        self.assertIn('UNVERIFIED_SUBMISSION', proposal['warnings'])
        self.assertIn('NO_INDEPENDENT_GPU_RERUN', proposal['warnings'])
        self.assertNotIn('ACCEPTED', report)

    def test_manual_review_has_no_chart_or_checked_status(self):
        """A refused export must not gain a chart, CHECKED status or owner acceptance."""
        source = issue(gpu='Unknown Model')
        proposal = core.prepare(source, bundle())
        self.assertEqual(proposal['state'], 'MANUAL_REVIEW')
        api = FakeAPI(current=source)
        result = writer.publish(proposal, api, 12)
        self.assertEqual(result['status'], 'ISSUE_ONLY')
        self.assertEqual(api.writes, [])

    def test_next_entry_preserves_legacy_entries_and_report_links(self):
        """New and legacy managed entries coexist without duplicate or lost previews."""
        next_proposal = core.prepare(issue(13), bundle())
        for path, (anchor, prefix) in writer.INDEXES.items():
            with self.subTest(path=path):
                legacy = (f'- [NVIDIA RTX 3090 / v0.1.5 / Issue #9]('
                          'NVIDIA/RTX_3090/v0.1.5/issue-9/README.md) '
                          '— **UNVERIFIED** (`DATA_READY`); maintainer review required.\n')
                source = index_fixture(path).replace(
                    (writer.INDEX_START + '\n').encode(),
                    (writer.INDEX_START + '\n' + legacy).encode())
                first = writer.update_index(source, ready(), anchor, prefix)
                second = writer.update_index(first, next_proposal, anchor, prefix)
                added = (writer.index_entry(next_proposal, prefix) + '\n').encode()
                self.assertEqual(second.replace(added, b'', 1), first)
                self.assertIn(legacy.encode(), second)
                self.assertEqual(second.count(b'![Exported measurements'), 0)
                with self.assertRaisesRegex(core.Refused, '^INDEX_DUPLICATE$'):
                    writer.update_index(second, ready(), anchor, prefix)


if __name__ == '__main__':
    unittest.main()
