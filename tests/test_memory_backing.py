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
                self.assertIn(SYSMEM, readme)
                self.assertIn(SYSMEM, svg.decode())
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
            self.assertIn('Native DX12 memory backing: UNKNOWN', text)
            self.assertNotIn(SYSMEM, text)
            metadata = json.loads(next(v for k, v in outputs.items() if k.endswith('/memory-backing.json')))
            self.assertEqual(metadata['native_dx12']['basis'], 'NOT_RECORDED')
            svg = next(v for k, v in outputs.items() if k.endswith('/chart.svg'))
            self.assertIn('Native DX12 memory backing: UNKNOWN', svg.decode())
            self.assertNotIn(SYSMEM, svg.decode())
            self.assertEqual(metadata['vulkan']['backing'], 'NOT_RECORDED')

    def test_changed_known_artifact_identity_is_unknown(self):
        """Changing a known version's pinned artifact cannot retain its old documented backing."""
        catalog = copy.deepcopy(core.catalog())
        catalog['v0.1.5']['archive_sha256'] = 'f'*64
        with mock.patch.object(core, 'catalog', return_value=catalog):
            p = core.prepare(fixtures.issue(), fixtures.bundle())
            outputs = core.render(p)
            metadata = json.loads(next(v for k, v in outputs.items() if k.endswith('/memory-backing.json')))
            self.assertEqual(metadata['native_dx12']['backing'], 'UNKNOWN')

    def test_issue_and_archive_memory_prose_cannot_override_release_evidence(self):
        """Untrusted memory claims never select the label or enter the public metadata."""
        issue = fixtures.issue()
        issue['body'] += '\n### Memory backing\n\nVRAM PRIVATE_MEMORY_CLAIM\n'
        files = fixtures.raw_files()
        run = json.loads(files['run.json']);run['memory_backing'] = 'VRAM PRIVATE_MEMORY_CLAIM'
        files['run.json'] = core.json_bytes(run)
        outputs = core.render(core.prepare(issue, fixtures.bundle(files)))
        text = b''.join(outputs.values()).decode()
        self.assertIn(SYSMEM, text)
        self.assertNotIn('PRIVATE_MEMORY_CLAIM', text)

    def test_manual_review_has_no_established_memory_claim(self):
        """A refused identity remains unknown even when it names a documented release."""
        p = core.prepare(fixtures.issue(gpu='RTX 3060'), fixtures.bundle())
        self.assertEqual(p['reason'], 'GPU_MISMATCH')
        outputs = core.render(p)
        metadata = json.loads(next(v for k, v in outputs.items() if k.endswith('/memory-backing.json')))
        self.assertEqual(metadata['native_dx12']['backing'], 'UNKNOWN')
        self.assertFalse(any(k.endswith('/measurements.csv') for k in outputs))

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

    def test_curated_charts_expose_native_label_and_separate_vulkan_metadata(self):
        """Every existing community chart carries visible Native-only backing and version evidence."""
        charts = sorted((ROOT/'Experiment Results/Community/charts').glob('*.svg'))
        self.assertEqual(len(charts), 4)
        for path in charts:
            with self.subTest(chart=path.name):
                root = ET.fromstring(path.read_bytes())
                caption = root.find('.//{http://www.w3.org/2000/svg}g[@id="memory-backing-label"]')
                self.assertIn(SYSMEM, ''.join(caption.itertext()))
                self.assertIn('Vulkan memory backing: NOT_RECORDED', ''.join(caption.itertext()))
                meta = root.find('{http://www.w3.org/2000/svg}metadata[@id="native-memory-backing"]')
                context = json.loads(meta.text)
                self.assertEqual(context['native_dx12']['release'], 'v0.1.4')
                self.assertEqual(context['native_dx12']['release_artifact_sha256'], core.catalog()['v0.1.4']['archive_sha256'])
                self.assertEqual(context['vulkan']['backing'], 'NOT_RECORDED')
                legend = root.find('.//{http://www.w3.org/2000/svg}g[@id="legend_1"]')
                if legend is not None:
                    self.assertEqual([t.text for t in legend.iter('{http://www.w3.org/2000/svg}text')],
                                     ['Native*', 'Vulkan reference'])

    def test_curated_pages_label_existing_results_without_removing_negative_evidence(self):
        """Label every existing result page while keeping clock/contention caveats and values."""
        root = ROOT/'Experiment Results/Community'
        pages = ['README.md', 'v0.1.4-submitted-data.md']
        for gpu in ('RTX_3060', 'RTX_3060_Ti', 'RTX_3090', 'RTX_4060_Laptop_GPU'):
            pages += ['NVIDIA/' + gpu + '/README.md', 'NVIDIA/' + gpu + '/v0.1.4/README.md']
        pages += ['NVIDIA/RTX_3060_Ti/issue-3.md', 'NVIDIA/RTX_3090/issue-5.md',
                  'NVIDIA/RTX_4060_Laptop_GPU/issue-2.md']
        for name in pages:
            with self.subTest(page=name):
                self.assertIn(SYSMEM, (root/name).read_text())
        self.assertIn('NOT_QUALIFIED', (root/'NVIDIA/RTX_3090/issue-5.md').read_text())
        self.assertIn('ONNX', (root/'NVIDIA/RTX_3060_Ti/issue-3.md').read_text())
        text = (root/'NVIDIA/RTX_4060_Laptop_GPU/issue-2.md').read_text()
        self.assertIn('| Affine | 15,776 | 10,112 |', text)

    def test_unknown_generated_page_can_coexist_with_curated_sysmem_pages(self):
        """A real refused-identity README must not inherit historical pages' SYSMEM requirement."""
        proposal = core.prepare(fixtures.issue(gpu='RTX 3060'), fixtures.bundle())
        outputs = core.render(proposal)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            shutil.copytree(ROOT/'Experiment Results/Community', target/'Experiment Results/Community')
            for name, data in outputs.items():
                path = target/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            readme = next(data.decode() for name, data in outputs.items() if name.endswith('/README.md'))
            self.assertIn('Native DX12 memory backing: UNKNOWN', readme)
            with mock.patch(__name__ + '.ROOT', target):
                self.test_curated_pages_label_existing_results_without_removing_negative_evidence()


if __name__ == '__main__':
    unittest.main()
