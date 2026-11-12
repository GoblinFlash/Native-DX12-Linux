"""Build one release's reviewed-data report using the existing v0.1.4 structure.

Inputs are bounded, sanitized intake proposals, never uploaded code or graphics.
Writes are explicit, local and create-only; this command has no GitHub client.
"""
import argparse
from decimal import Decimal
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('version_report_intake',
                                             Path(__file__).with_name('community_intake.py'))
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)

SUITES = (
    ('compute', 'Compute suite', (('affine', '', 'Affine'), ('affine515', '', 'Affine N515'),
                                  ('parallel-sort', '', 'ParallelSort N515'))),
    ('d4', 'Test 1 — D4', tuple((shape, variant, label + ' ' + arm)
                              for shape, label in (('128x128', '128×128'), ('32x512', '32×512'), ('16x1024', '16×1024'))
                              for variant, arm in (('B', 'Original'), ('D4', 'D4')))),
    ('k', 'Test 2 — K', tuple((shape, variant, label + ' ' + arm)
                            for shape, label in (('64x64', '64×64'), ('127x65', '127×65'))
                            for variant, arm in (('root-scalar', 'scalar'), ('root-uint4', 'uint4')))),
    ('kw', 'Test 3 — K WaveForm', tuple((shape, variant, label + ' ' + arm)
                                     for shape, label in (('64x64', '64×64'), ('127x65', '127×65'))
                                     for variant, arm in (('wave-root-scalar', 'scalar'), ('wave-root-uint4', 'uint4')))),
)


def gpu_name(proposal):
    """Use only catalogue labels, never raw hardware names from the Issue/archive."""
    return core.GPUS.get(proposal['claimed_gpu'], 'Pending classification')


def anchor(proposal):
    """Match GitHub's heading anchor for the fixed GPU label and numeric Issue."""
    return gpu_name(proposal).lower().replace(' ', '-') + '--issue-' + str(proposal['issue'])


def observations(proposal):
    """Keep refusal, process completion and reported clock evidence separate."""
    if proposal['state'] != 'DATA_READY':
        actual = core.GPUS.get(proposal['archive_gpu'], 'unknown')
        return ('No imported values', 'NOT_RECORDED',
                proposal['reason'] + ': archive reports ' + actual)
    run = proposal['run']
    counts = run['counts']
    qualified = sum(s['reported_clock_qualification'] == 'QUALIFIED' for s in run['steps'])
    clock = ('QUALIFIED' if qualified == len(run['steps']) else 'NOT_QUALIFIED / NOT_RECORDED')
    return (f'{counts["verified"]}/{counts["expected"]} VERIFIED',
            f'{clock}, {qualified}/{len(run["steps"])} suites',
            'Reported ' + run['overall'] + '; original GPU receipts unavailable')


def overview(version, proposals, prefix='Community/'):
    """Return the same four-column overview used for the previous release."""
    lines = ['| GPU | Exported process status | GPU tick-to-ns model | Important limitation |',
             '| --- | --- | --- | --- |']
    for proposal in proposals:
        name = gpu_name(proposal)
        if proposal['state'] == 'DATA_READY':
            url = prefix + version + '-submitted-data.md#' + anchor(proposal)
        else:
            name += ' (claimed)'
            url = 'https://github.com/' + core.REPOSITORY + '/issues/' + str(proposal['issue'])
        lines.append('| [' + name + '](' + url + ') | ' + ' | '.join(observations(proposal)) + ' |')
    return '\n'.join(lines)


def render(version, proposals, existing_issues=()):
    """Render a single release; preserve existing Issue data and retain refusals."""
    core.need(version in core.catalog() and type(proposals) is list and
              0 < len(proposals) <= 32, 'VERSION_REPORT_INPUT')
    seen = set()
    for proposal in proposals:
        core.validate_proposal(proposal)
        core.need(proposal['claimed_version'] == version and
                  (proposal['state'] != 'DATA_READY' or proposal['archive_version'] == version), 'VERSION_MISMATCH')
        core.need(proposal['issue'] not in seen, 'VERSION_REPORT_DUPLICATE')
        seen.add(proposal['issue'])
    proposals = sorted(proposals, key=lambda p: (gpu_name(p), p['issue']))
    ready = [p for p in proposals if p['state'] == 'DATA_READY']
    backing = ('SYSMEM (system-memory buffers, not VRAM)' if ready and
               all(core.memory_backing(p)['native_dx12']['backing'] == 'SYSMEM' for p in ready)
               else 'UNKNOWN (release evidence NOT_RECORDED)')
    lines = ['# Community benchmark ' + version + ' — submitted measurement data', '',
             '**Native DX12 memory backing: ' + backing + '**, from the release-artifact evidence below. '
             'Vulkan memory backing: **NOT_RECORDED**; do not infer it from Native DX12.', '',
             f'{len(proposals)} public submissions checked for **{version} / {core.catalog()[version]["package_id"]}**. '
             f'{len(ready)} have matching GPU/release exports. Values are extracted from public share archives; '
             'this is not an independent GPU rerun or blanket acceptance.', '',
             '## Submission overview', '', overview(version, proposals, ''), '',
             '## How to read these numbers', '',
             '- Native values are GPU timer ticks; Vulkan values are nanoseconds. Charts use the same conditional '
             '~1 ns/tick presentation as v0.1.4 only for complete exports with all four reported clock checks '
             'QUALIFIED and envelopes containing 1 ns/tick. Other cases retain separate raw-unit panels.',
             '- Each table value is the median of exported process values. D4, K and WaveForm use medians '
             'of process medians; the full-work timing includes synchronization, not isolated shader timing.',
             '- The same four workload selections, panel layout, fonts, blue/orange series and explanations '
             'come from the published v0.1.4 chart templates. Every variant remains in the tables.',
             '- No cross-GPU ranking or speedup is calculated. Reported clock qualification is conditional '
             'and does not prove actual per-dispatch clocks, absence of contention or GPU receipt authenticity.', '']
    outputs = {}
    version_indexes = {}
    for proposal in proposals:
        issue = proposal['issue']
        lines += ['## ' + gpu_name(proposal) + ' — [Issue #' + str(issue) +
                  '](https://github.com/' + core.REPOSITORY + '/issues/' + str(issue) + ')', '']
        status, clock, limit = observations(proposal)
        if proposal['state'] != 'DATA_READY':
            lines += ['**Manual review — ' + limit + '. No measurements or chart are assigned to this claimed GPU.**', '',
                      'Submitted archive SHA-256: `' + (proposal['bundle_sha256'] or 'NOT_RECORDED') + '`.', '']
            if proposal['reason'] == 'GPU_MISMATCH':
                matches = [p for p in ready if p['bundle_sha256'] == proposal['bundle_sha256']]
                if matches:
                    match = matches[0]
                    lines += ['This archive is identical to Issue #' + str(match['issue']) +
                              ': it identifies **' + gpu_name(match) + '**, PCI `' + match['pci'] +
                              '`. It supplies no results for the claimed GPU.', '']
                lines += ['The reporter must provide a genuine share-results bundle for **' + version +
                          '** from the claimed **' + gpu_name(proposal) + '**, with matching GPU model/PCI ID, '
                          'release identity and driver in `run.json` and the corresponding exported tables. '
                          'Renaming the archive or changing the Issue declaration does not correct the measurements. '
                          'A maintainer must reconcile the corrected submission before importing it.', '']
            continue
        rendered = core.render(proposal)
        folder = core.record_folder(proposal)
        if issue not in existing_issues:
            outputs.update(rendered)
        else:
            # Existing v1 records/CSV stay in place; only their chart presentation changes.
            outputs[folder + '/chart.svg'] = rendered[folder + '/chart.svg']
        context = core.memory_backing(proposal)
        lines += ['GPU PCI ID: `' + proposal['pci'] + '` · Driver: `' + proposal['driver'] +
                  '` · Export: **' + status + '** · Clock model: **' + clock + '**.', '',
                  '**' + core.memory_label(context) + '**. [Release evidence](' +
                  context['native_dx12'].get('evidence_url', 'https://github.com/' + core.REPOSITORY + '/releases') + ').', '',
                  '![' + gpu_name(proposal) + ' selected workload medians](' + folder[len(core.ROOT):] + '/chart.svg)', '',
                  '*Selected medians from the four suites; all variants appear in the tables below.*', '']
        rows = core.summaries(proposal)
        lookup = {(x['suite'], x['case'], x['variant'], x['path']): x['median'] for x in rows}
        def number(key):
            value = lookup.get(key)
            if value is None:
                return 'NOT_RECORDED'
            text = format(Decimal(str(value)), ',f')
            return text.rstrip('0').rstrip('.') if '.' in text else text
        for suite, title, variants in SUITES:
            lines += ['### ' + title, '', '| Workload / native variant | Native ' +
                      context['native_dx12']['backing'] + ' median (GPU ticks) | Vulkan median (ns) |',
                      '| --- | ---: | ---: |']
            for case, variant, label in variants:
                lines.append('| ' + label + ' | ' + number((suite, case, variant, 'native')) +
                             ' | ' + number((suite, case, '', 'vulkan')) + ' |')
            lines.append('')
        lines += ['Submitted archive SHA-256: `' + proposal['bundle_sha256'] + '`.', '',
                  '[Full sanitized per-Issue data](' + folder[len(core.ROOT):] + '/README.md).', '']
        version_index = core.ROOT + proposal['claimed_gpu'] + '/' + version + '/README.md'
        version_indexes.setdefault(version_index, ['# ' + gpu_name(proposal) +
                                                  ' — benchmark ' + version, ''])
        version_indexes[version_index].append('- [Issue #' + str(issue) +
            ': full measurements and chart](../../../' + version + '-submitted-data.md#' +
            anchor(proposal) + ') · [Source Issue](https://github.com/' + core.REPOSITORY +
            '/issues/' + str(issue) + ').')
    for path, links in version_indexes.items():
        outputs[path] = ('\n'.join(links) + '\n\nExported statuses and clock checks are reported evidence, '
                         'not independent GPU qualification.\n').encode()
    outputs[core.ROOT + version + '-submitted-data.md'] = '\n'.join(lines).encode()
    return outputs


def main():
    """Read bounded local proposals and create outputs only in a new local destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--proposal', type=Path, action='append', required=True)
    parser.add_argument('--existing-issue', type=int, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    core.need(len(args.proposal) <= 32, 'VERSION_REPORT_INPUT')
    proposals = []
    for path in args.proposal:
        core.need(path.stat().st_size <= core.MAX_PROPOSAL, 'JSON_LIMIT')
        proposals.append(core.load_json(path.read_bytes()))
    for name, data in render(args.version, proposals, args.existing_issue).items():
        core.write_new(args.output / name, data)


if __name__ == '__main__':
    main()
