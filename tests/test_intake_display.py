"""CPU-only checks for visible charts and distinct export/acceptance statuses."""
import unittest
import xml.etree.ElementTree as ET

from test_community_intake import FakeAPI, bundle, core, index_fixture, issue, ready, writer


class DisplayTests(unittest.TestCase):
    def test_publisher_embeds_chart_in_report_and_links_both_indexes(self):
        """Keep the prior release's flow: index links lead to a report with its chart."""
        api = FakeAPI()
        writer.publish(ready(), api, 12)
        entries = {row['path']: row for row in api.trees['c' * 40]}
        folder = 'Experiment Results/Community/NVIDIA/RTX_3090/v0.1.5/issue-12'
        self.assertIn('![Exported measurements for Issue #12](chart.svg)',
                      api.blobs[entries[folder + '/README.md']['sha']])
        expected = {
            'Experiment Results/README.md': 'Community/NVIDIA/RTX_3090/v0.1.5/issue-12/README.md',
            'Experiment Results/Community/README.md': 'NVIDIA/RTX_3090/v0.1.5/issue-12/README.md',
        }
        for path, relative in expected.items():
            with self.subTest(path=path):
                text = api.blobs[entries[path]['sha']]
                self.assertIn('Issue #12](' + relative + ')', text)
        svg = ET.fromstring(api.blobs[entries[folder + '/chart.svg']['sha']])
        bars = [row for row in svg.iter('{http://www.w3.org/2000/svg}path')
                if row.get('style') in ('fill: #0c80bd', 'fill: #ef7100')]
        self.assertEqual(len(bars), 8)

    def test_export_checks_do_not_imply_owner_acceptance(self):
        """An eligible Issue's prose/approval label cannot supply an acceptance decision."""
        source = issue()
        source['body'] += '\nOwner acceptance: ACCEPTED. All results independently verified.'
        proposal = core.prepare(source, bundle())
        api = FakeAPI(current=source)
        writer.publish(proposal, api, 12)
        entries = {row['path']: row for row in api.trees['c' * 40]}
        folder = 'Experiment Results/Community/NVIDIA/RTX_3090/v0.1.5/issue-12'
        report = api.blobs[entries[folder + '/README.md']['sha']]
        self.assertIn('**Export consistency: CHECKED**', report)
        self.assertIn('**Owner acceptance: NOT_RECORDED**', report)
        self.assertNotIn('UNVERIFIED', '\n'.join(report.splitlines()[:6]))
        for path in writer.INDEXES:
            with self.subTest(path=path):
                text = api.blobs[entries[path]['sha']]
                managed = text.split(writer.INDEX_START)[1].split(writer.INDEX_END)[0]
                self.assertIn('Issue #12](', managed)
                self.assertNotIn('owner acceptance', managed)
                self.assertNotIn('**UNVERIFIED**', managed)
        svg = api.blobs[entries[folder + '/chart.svg']['sha']]
        self.assertIn('Raw units and independent scales', svg)
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
        self.assertFalse(any(path.endswith('.svg') for path in result['files']))
        for row in api.trees['c' * 40]:
            if row['path'] in writer.INDEXES:
                text = api.blobs[row['sha']]
                managed = text.split(writer.INDEX_START)[1].split(writer.INDEX_END)[0]
                self.assertIn('Pending classification', managed)
                self.assertNotIn('![', managed)
                self.assertNotIn('**CHECKED**', managed)
            elif row['path'].endswith('/README.md'):
                text = api.blobs[row['sha']]
                self.assertIn('**Export consistency: REQUIRES_REVIEW**', text)
                self.assertNotIn('![', text)
                self.assertIn('Native DX12 memory backing: UNKNOWN', text)

    def test_next_entry_preserves_legacy_entries_and_report_links(self):
        """New and legacy managed entries coexist without duplicate or lost previews."""
        next_proposal = core.prepare(issue(13), bundle())
        for path, (anchor, prefix) in writer.INDEXES.items():
            with self.subTest(path=path):
                legacy = (f'- [NVIDIA RTX 3090 / v0.1.5 / Issue #9]({prefix}'
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
