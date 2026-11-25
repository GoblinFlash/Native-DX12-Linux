"""CPU-only memory-backing output tests; transports and result bundles are synthetic."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('intake_fixtures', ROOT / 'tests/test_community_intake.py')
fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixtures)
core = fixtures.core
SYSMEM = 'Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM)'


class MemoryBackingTests(unittest.TestCase):
    def test_both_releases_render_exact_native_scope_and_metadata(self):
        """Render real README/SVG/sidecar consumers for each independently documented release."""
        for version in ('v0.1.4', 'v0.1.5'):
            with self.subTest(version=version):
                proposal = core.prepare(fixtures.issue(version=version), fixtures.bundle(fixtures.raw_files(version)))
                outputs = core.render(proposal)
                readme = next(v.decode() for k, v in outputs.items() if k.endswith('/README.md'))
                svg = next(v for k, v in outputs.items() if k.endswith('/chart.svg'))
                self.assertNotIn(SYSMEM, readme)
                metadata = json.loads(next(v for k, v in outputs.items() if k.endswith('/memory-backing.json')))
                self.assertEqual(metadata['native_dx12']['backing'], 'SYSMEM')
                self.assertEqual(metadata['native_dx12']['scope'], 'data_buffers')
                self.assertEqual(metadata['native_dx12']['release_artifact_sha256'], core.catalog()[version]['archive_sha256'])
                self.assertEqual(metadata['vulkan']['backing'], 'NOT_RECORDED')
                root = ET.fromstring(svg)
                embedded = root.find('{http://www.w3.org/2000/svg}metadata')
                self.assertEqual(json.loads(embedded.text), metadata)

    def test_future_release_is_unknown_even_with_reused_artifact(self):
        """An admitted future catalogue identity must not inherit a known release's placement label."""
        catalog = copy.deepcopy(core.catalog())
        catalog['v0.1.6'] = dict(catalog['v0.1.5'], public_version='v0.1.6')
        with mock.patch.object(core, 'catalog', return_value=catalog):
            p = core.prepare(fixtures.issue(version='v0.1.6'), fixtures.bundle(fixtures.raw_files('v0.1.6')))
            self.assertEqual(p['state'], 'DATA_READY')
            outputs = core.render(p)
            text = next(v.decode() for k, v in outputs.items() if k.endswith('/README.md'))
            self.assertNotIn('memory backing:', text)
            self.assertNotIn(SYSMEM, text)
            metadata = json.loads(next(v for k, v in outputs.items() if k.endswith('/memory-backing.json')))
            self.assertEqual(metadata['native_dx12']['basis'], 'NOT_RECORDED')
            svg = next(v for k, v in outputs.items() if k.endswith('/chart.svg'))
            self.assertEqual(json.loads(ET.fromstring(svg).find('{*}metadata').text), metadata)
            self.assertNotIn(SYSMEM, svg.decode())
            self.assertEqual(metadata['vulkan']['backing'], 'NOT_RECORDED')

    def test_changed_known_artifact_identity_is_unknown(self):
        """Changing a known version's pinned artifact cannot retain its old documented backing."""
        catalog = copy.deepcopy(core.catalog())
        catalog['v0.1.5']['archive_sha256'] = 'f'*64
        with mock.patch.object(core, 'catalog', return_value=catalog):
            p = core.prepare(fixtures.issue(), fixtures.bundle())
            self.assertEqual(core.memory_backing(p)['native_dx12']['backing'], 'UNKNOWN')
            with self.assertRaisesRegex(core.Refused, '^REPORT_TIMESTAMP_PROFILE$'):
                core.render(p)

    def test_issue_and_archive_memory_prose_cannot_override_release_evidence(self):
        """Untrusted memory claims never select the label or enter the public metadata."""
        issue = fixtures.issue()
        issue['body'] += '\n### Memory backing\n\nVRAM PRIVATE_MEMORY_CLAIM\n'
        files = fixtures.raw_files()
        run = json.loads(files['run.json']);run['memory_backing'] = 'VRAM PRIVATE_MEMORY_CLAIM'
        files['run.json'] = core.json_bytes(run)
        outputs = core.render(core.prepare(issue, fixtures.bundle(files)))
        text = b''.join(outputs.values()).decode()
        self.assertEqual(core.memory_backing(core.prepare(issue, fixtures.bundle(files)))['native_dx12']['backing'], 'SYSMEM')
        self.assertNotIn('PRIVATE_MEMORY_CLAIM', text)

    def test_manual_review_has_no_established_memory_claim(self):
        """A refused identity remains unknown even when it names a documented release."""
        p = core.prepare(fixtures.issue(gpu='RTX 3060'), fixtures.bundle())
        self.assertEqual(p['reason'], 'GPU_MISMATCH')
        self.assertEqual(core.memory_backing(p)['native_dx12']['backing'], 'UNKNOWN')
        self.assertEqual(core.render(p), {})

    def test_writer_derives_memory_output_without_accepting_extra_proposal_fields(self):
        """Real writer rendering emits release-derived metadata; forged extra fields fail before API."""
        api = fixtures.FakeAPI()
        p = fixtures.ready()
        result = fixtures.writer.publish(p, api, 12)
        self.assertTrue(any(k.endswith('/memory-backing.json') for k in result['files']))
        p['memory_backing'] = 'VRAM'
        rejected = fixtures.FakeAPI()
        with self.assertRaisesRegex(core.Refused, '^PROPOSAL_SCHEMA$'):
            fixtures.writer.publish(p, rejected, 12)
        self.assertEqual(rejected.calls, [])

    def test_curated_pages_label_existing_results_without_removing_negative_evidence(self):
        root = ROOT / 'Benchmark Results/NVIDIA'
        records = sorted(root.glob('*/v0.1.4/issue-*/record.json'))
        self.assertEqual(len(records), 4)
        for path in records:
            proposal = json.loads(path.read_text())
            folder = path.parent
            metadata = json.loads((folder / 'memory-backing.json').read_text())
            self.assertEqual(metadata, core.memory_backing(proposal))
            self.assertEqual(metadata['native_dx12']['backing'], 'SYSMEM')
            self.assertEqual(metadata['vulkan']['backing'], 'NOT_RECORDED')
            self.assertEqual((folder / 'README.md').read_text().count('!['), 4)
            if proposal['claimed_gpu'] == 'NVIDIA/RTX_3090':
                self.assertTrue(all(s['reported_clock_qualification'] == 'NOT_QUALIFIED'
                                    for s in proposal['run']['steps']))
                self.assertIn('independent scale', (folder / 'chart.svg').read_text())

    def test_unknown_generated_page_can_coexist_with_curated_sysmem_pages(self):
        """A measured export with unknown backing can coexist with the historical SYSMEM pages."""
        catalog = copy.deepcopy(core.catalog())
        catalog['v0.1.6'] = dict(catalog['v0.1.5'], public_version='v0.1.6')
        with mock.patch.object(core, 'catalog', return_value=catalog):
            proposal = core.prepare(fixtures.issue(version='v0.1.6'), fixtures.bundle(fixtures.raw_files('v0.1.6')))
            outputs = core.render(proposal)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            shutil.copytree(ROOT/'Benchmark Results', target/'Benchmark Results')
            for name, data in outputs.items():
                path = target/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            readme = next(data.decode() for name, data in outputs.items() if name.endswith('/README.md'))
            self.assertNotIn('memory backing:', readme)
            with mock.patch(__name__ + '.ROOT', target):
                self.test_curated_pages_label_existing_results_without_removing_negative_evidence()


if __name__ == '__main__':
    unittest.main()
