"""CPU-only model/PCI consistency regressions; no hardware identity is authenticated."""
import json
import unittest

from test_community_intake import FakeAPI, bundle, core, issue, raw_files, ready, writer


class PCIIdentityTests(unittest.TestCase):
    def test_explicit_pci_suffixes_must_match_the_recorded_field(self):
        """A second explicit PCI claim in either model field cannot contradict run.json."""
        for origin in ('issue', 'archive'):
            with self.subTest(origin=origin):
                files = raw_files(gpu='NVIDIA GeForce RTX 3060')
                current = issue(gpu='RTX 3060')
                if origin == 'issue':
                    current = issue(gpu='RTX 3060 (PCI 10de:2504)')
                else:
                    run = json.loads(files['run.json'])
                    run['gpu']['model'] += ' (PCI 10de:2504)'
                    files['run.json'] = core.json_bytes(run)
                p = core.prepare(current, bundle(files))
                self.assertEqual((p['state'], p['reason']), ('MANUAL_REVIEW', 'GPU_PCI_MISMATCH'))

    def test_unrecorded_gpu_status_stays_manual(self):
        """A plausible ID without a recorded observation does not admit numeric data."""
        files = raw_files(); run = json.loads(files['run.json'])
        run['gpu']['status'] = 'NOT_RECORDED'; files['run.json'] = core.json_bytes(run)
        p = core.prepare(issue(), bundle(files))
        self.assertEqual(p['reason'], 'GPU_PCI_UNVERIFIED')
        self.assertEqual(p['measurements'], [])

    def test_release_documented_ids_and_multiple_ids_for_one_model(self):
        """Known vendor data admits matching model IDs, including both3060 revisions."""
        for model, pci in [('RTX 3090', '10de:2204'), ('RTX 3060', '10de:2503'),
                           ('RTX 3060', '10DE:2504'), ('RTX 4060', '10de:2882')]:
            with self.subTest(model=model, pci=pci):
                files = raw_files(gpu='NVIDIA GeForce '+model)
                run = json.loads(files['run.json']); run['gpu']['pci'] = pci
                files['run.json'] = core.json_bytes(run)
                p = core.prepare(issue(gpu=model), bundle(files))
                self.assertEqual((p['state'], p['reason']), ('DATA_READY', 'OK'))
                self.assertEqual(p['pci'], pci.lower())
                self.assertEqual(p['schema'], 'ndx12.community-intake.v2')

    def test_mismatched_or_unrecorded_pci_never_exports_measurements(self):
        """Reject contradictions, missing IDs, unlisted devices and private/malformed fields."""
        for pci, reason in [('10de:2204', 'GPU_PCI_MISMATCH'),
                            ('10de:ffff', 'GPU_PCI_UNVERIFIED'),
                            (None, 'GPU_PCI_FORMAT'), ('PRIVATE_HOST', 'GPU_PCI_FORMAT'),
                            ({'id': '10de:2503'}, 'GPU_PCI_FORMAT')]:
            with self.subTest(pci=pci):
                files = raw_files(gpu='NVIDIA GeForce RTX 3060')
                run = json.loads(files['run.json']); run['gpu']['pci'] = pci
                files['run.json'] = core.json_bytes(run)
                p = core.prepare(issue(gpu='RTX 3060'), bundle(files))
                self.assertEqual((p['state'], p['reason']), ('MANUAL_REVIEW', reason))
                self.assertEqual(p['measurements'], [])
                rendered = b''.join(core.render(p).values())
                self.assertNotIn(b'PRIVATE_HOST', rendered)
                self.assertFalse(any(name.endswith('/measurements.csv') for name in core.render(p)))

    def test_writer_revalidates_pci_before_any_api_call(self):
        """Typed proposal forgery cannot bypass the same model/PCI consistency check."""
        for pci, reason in [('10de:2503', 'GPU_PCI_MISMATCH'),
                            ('10de:ffff', 'GPU_PCI_UNVERIFIED'),
                            ('bad', 'GPU_PCI_FORMAT')]:
            with self.subTest(pci=pci):
                p = ready(); p['pci'] = pci
                api = FakeAPI()
                with self.assertRaisesRegex(core.Refused, '^'+reason+'$'):
                    writer.publish(p, api, 12)
                self.assertEqual(api.calls, [])
        p = ready(); p['schema'] = 'ndx12.community-intake.v1'; p.pop('pci', None)
        with self.assertRaisesRegex(core.Refused, '^PROPOSAL_SCHEMA$'):
            core.validate_proposal(p)


if __name__ == '__main__':
    unittest.main()
