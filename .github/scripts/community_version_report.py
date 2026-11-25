"""Build one release's reviewed-data report using the existing v0.1.4 structure.

Inputs are bounded, sanitized intake proposals, never uploaded code or graphics.
Writes are explicit, local and create-only; this command has no GitHub client.
"""
import argparse
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


V3_SUITES = (
    ('fwht', 'Test 4 — FWHT', (('128x128', 'block', '128×128 FWHT'),)),
    ('sponza', 'Test 5 — Sponza', (('64x64', 'scalar', '64×64 Scalar 4-bit'),
                                  ('64x64', 'tensor', '64×64 Tensor Core 4-bit'))),
    ('bounce', 'Test 5 — Neural Grid', (('1920x1080', 'constant', '1920×1080 Constant loads'),
                                        ('1920x1080', 'strong', '1920×1080 Strong loads'))),
)


def gpu_name(proposal):
    """Use only catalogue labels, never raw hardware names from the Issue/archive."""
    return core.GPUS.get(proposal['claimed_gpu'], 'Pending classification')


def anchor(proposal):
    """Match GitHub's heading anchor for the fixed GPU label and numeric Issue."""
    return gpu_name(proposal).lower().replace(' ', '-') + '--issue-' + str(proposal['issue'])


def observations(proposal):
    """Describe process completion and clock evidence for a measured export."""
    run = proposal['run']
    counts = run['counts']
    qualified = sum(s['reported_clock_qualification'] == 'QUALIFIED' for s in run['steps'])
    clock = ('QUALIFIED' if qualified == len(run['steps']) else 'NOT_QUALIFIED / NOT_RECORDED')
    return (f'{counts["verified"]}/{counts["expected"]} VERIFIED',
            f'{clock}, {qualified}/{len(run["steps"])} suites',
            'Reported ' + run['overall'] + '; original GPU receipts unavailable')


def overview(version, proposals, prefix=''):
    """Return the same four-column overview used for the previous release."""
    lines = ['| GPU | Exported process status | Reported host/GPU clock check | Important limitation |',
             '| --- | --- | --- | --- |']
    for proposal in proposals:
        name = gpu_name(proposal)
        url = prefix + version + '-submitted-data.md#' + anchor(proposal)
        lines.append('| [' + name + '](' + url + ') | ' + ' | '.join(observations(proposal)) + ' |')
    return '\n'.join(lines)


def measurement_lines(proposal, has_chart, folder_link, level='###'):
    """Status, memory backing, chart and every median table of one matching export.

    folder_link is the Issue folder relative to the page that shows it; level is the
    heading depth of the suite tables. The release report and the GPU pages share it.
    """
    status, clock, _ = observations(proposal)
    context = core.memory_backing(proposal)
    lines = ['GPU PCI ID: `' + proposal['pci'] + '` · Driver: `' + proposal['driver'] +
             '` · Export: **' + status + '** · Host/GPU clock check: **' + clock + '**.', '',
             '**' + core.memory_label(context) + '**. [Release evidence](' +
             context['native_dx12'].get('evidence_url', 'https://github.com/' + core.REPOSITORY + '/releases') + ').', '',
             ]
    if has_chart:
        lines += ['![' + gpu_name(proposal) + ' selected workload medians](' + folder_link + '/chart.svg)', '',
                  '*Selected medians from the four suites; all variants appear in the tables below.*', '']
    rows = core.summaries(proposal)
    lookup = {(x['suite'], x['case'], x['variant'], x['path']): x['median'] for x in rows}

    def number(key):
        value = lookup.get(key)
        if value is None:
            return 'NOT_RECORDED'
        return core.format_gpu_duration(value, group=True)
    suites = SUITES
    if core.release_schema(proposal['claimed_version']) == core.SHARE_V3:
        scheduled = {(row['suite'], row['case'], row['variant']) for row in proposal['processes']}
        suites = tuple((suite, title, variants + tuple(
            (shape, 'Q8PL', shape.replace('x', '×') + ' Q8PL')
            for shape in ('128x128', '32x512', '16x1024')
            if (suite, shape, 'Q8PL') in scheduled)) for suite, title, variants in SUITES)
        suites += tuple(suite for suite in V3_SUITES
                        if any(name == suite[0] for name, _, _ in scheduled))
    for suite, title, variants in suites:
        lines += [level + ' ' + title, '', '| Workload / native variant | Native ' +
                  context['native_dx12']['backing'] + ' median GPU time | Vulkan median GPU time (backing: ' +
                  context['vulkan']['backing'] + ') |',
                  '| --- | ---: | ---: |']
        for case, variant, label in variants:
            lines.append('| ' + label + ' | ' + number((suite, case, variant, 'native')) +
                         ' | ' + number((suite, case, '', 'vulkan')) + ' |')
        lines.append('')
    return lines


def gpu_section(proposal, has_chart, folder_link, report_link, level):
    """One submission on a GPU page: its source, measurements and links to the full data."""
    issue = str(proposal['issue'])
    return (['#' * (len(level) - 1) + ' [Issue #' + issue + '](https://github.com/' + core.REPOSITORY +
             '/issues/' + issue + ')', ''] + measurement_lines(proposal, has_chart, folder_link, level) +
            ['[Full sanitized per-Issue data](' + folder_link + '/README.md) · [All ' +
             proposal['claimed_version'] + ' submissions](' + report_link + '#' + anchor(proposal) + ')', ''])


GPU_NOTE = 'Exported statuses and clock checks are reported evidence, not independent GPU qualification.'


def render(version, proposals, existing_issues=()):
    """Render a single release; preserve existing measurements and omit Issue-only submissions."""
    core.need(version in core.catalog() and type(proposals) is list and
              0 < len(proposals) <= 32, 'VERSION_REPORT_INPUT')
    seen = set()
    for proposal in proposals:
        core.validate_proposal(proposal)
        core.need(proposal['claimed_version'] == version and
                  (proposal['state'] != 'DATA_READY' or proposal['archive_version'] == version), 'VERSION_MISMATCH')
        core.need(proposal['issue'] not in seen, 'VERSION_REPORT_DUPLICATE')
        seen.add(proposal['issue'])
    proposals = [p for p in proposals if not core.issue_only_reason(p)]
    if not proposals:
        return {}
    proposals = sorted(proposals, key=lambda p: (gpu_name(p), p['issue']))
    modern = core.release_schema(version) == core.SHARE_V3
    backing = ('SYSMEM (system-memory buffers, not VRAM)' if
               all(core.memory_backing(p)['native_dx12']['backing'] == 'SYSMEM' for p in proposals)
               else 'UNKNOWN (release evidence NOT_RECORDED)')
    lines = ['# Community benchmark ' + version + ' — submitted measurement data', '',
             '**Native DX12 memory backing: ' + backing + '**, from the release-artifact evidence below. '
             'Vulkan memory backing: **NOT_RECORDED**; do not infer it from Native DX12.', '',
             f'{len(proposals)} public submissions checked for **{version} / {core.catalog()[version]["package_id"]}**. '
             'Values are extracted from public share archives; '
             'this is not an independent GPU rerun or blanket acceptance.', '',
             '## Submission overview', '', overview(version, proposals, ''), '',
             '## How to read these numbers', '',
             '- Native and Vulkan GPU durations use ns below 1 ms and ms from 1 ms. Charts share a scale '
             + ('within a workload only for complete exports with both paths present and all reported host/GPU '
                'clock checks qualified, with the nominal timer rate inside every reported range. '
                'Other exports use separate scales.' if modern else
                'within a workload only for complete exports with all four reported host/GPU clock checks qualified '
                'and all four envelopes including the nominal timer rate. Other exports use separate scales.'),
             '- Each table value is the median of exported process values. D4, K and WaveForm use medians '
             'of process medians; the full-work timing includes synchronization, not isolated shader timing.',
             '- The same four workload selections, panel layout, fonts, blue/orange series and explanations '
             'come from the published v0.1.4 chart templates. Every variant remains in the tables.',
             '- No cross-GPU ranking or speedup is calculated. Reported clock qualification is conditional '
             'and does not prove actual per-dispatch clocks, absence of contention or GPU receipt authenticity.', '']
    outputs = {}
    version_indexes, gpu_results = {}, {}
    for proposal in proposals:
        issue = proposal['issue']
        lines += ['## ' + gpu_name(proposal) + ' — [Issue #' + str(issue) +
                  '](https://github.com/' + core.REPOSITORY + '/issues/' + str(issue) + ')', '']
        rendered = core.render(proposal)
        folder = core.record_folder(proposal)
        if issue not in existing_issues:
            outputs.update(rendered)
        elif folder + '/chart.svg' in rendered:
            # Existing v1 records/CSV stay in place; only their chart presentation changes.
            outputs[folder + '/chart.svg'] = rendered[folder + '/chart.svg']
        has_chart = folder + '/chart.svg' in rendered
        lines += measurement_lines(proposal, has_chart, folder[len(core.ROOT):])
        lines += ['Submitted archive SHA-256: `' + proposal['bundle_sha256'] + '`.', '',
                  '[Full sanitized per-Issue data](' + folder[len(core.ROOT):] + '/README.md).', '']
        # The GPU's release page and its main page show the measurements themselves, not only links.
        gpu = core.ROOT + proposal['claimed_gpu'] + '/'
        core.need(folder.startswith(gpu + version + '/issue-'), 'VERSION_REPORT_INPUT')
        version_index = gpu + version + '/README.md'
        version_indexes.setdefault(version_index, ['# ' + gpu_name(proposal) +
                                                  ' — benchmark ' + version, ''])
        version_indexes[version_index] += gpu_section(proposal, has_chart, folder[len(gpu + version) + 1:],
                                                      '../../../' + version + '-submitted-data.md', '###')
        results = gpu + 'README.md'
        gpu_results.setdefault(results, ['## Benchmark ' + version + ' results', ''])
        gpu_results[results] += gpu_section(proposal, has_chart, folder[len(gpu):],
                                            '../../' + version + '-submitted-data.md', '####')
    for path, sections in list(version_indexes.items()) + list(gpu_results.items()):
        outputs[path] = ('\n'.join(sections) + '\n' + GPU_NOTE + '\n').encode()
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
