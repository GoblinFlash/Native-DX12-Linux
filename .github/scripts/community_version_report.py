"""Build one release's chart report from validated measurements.

Inputs are bounded, sanitized intake proposals, never uploaded code or graphics.
Writes are explicit, local and create-only; this command has no GitHub client.
"""
import argparse
from collections import Counter
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('version_report_intake',
                                             Path(__file__).with_name('community_intake.py'))
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


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
    proposals.sort(key=lambda p: (p['claimed_gpu'], p['issue']))
    per_gpu = Counter(p['claimed_gpu'] for p in proposals)
    outputs, version_pages = {}, {}
    release = ['# Benchmark ' + version]
    for proposal in proposals:
        folder = core.record_folder(proposal)
        gpu = core.ROOT + proposal['claimed_gpu'] + '/'
        version_folder = gpu + version + '/'
        label = core.result_label(proposal)
        if proposal['issue'] not in existing_issues:
            outputs.update(core.render(proposal))
        repeated = per_gpu[proposal['claimed_gpu']] > 1
        page = version_pages.setdefault(version_folder, ['# ' + label])
        if repeated:
            run = f'Run {proposal["issue"]}'
            page.append('## ' + run)
            label += ' · ' + run
        page.append(core.chart_media(proposal, folder[len(version_folder):] + '/', distinguish_run=repeated))
        outputs[gpu + 'README.md'] = f'- [{version}]({version}/)\n'.encode()
        release.extend(['## ' + label, core.chart_media(proposal, folder[len(core.ROOT):] + '/',
                                                        distinguish_run=repeated)])
    for folder, sections in version_pages.items():
        outputs[folder + 'README.md'] = ('\n\n'.join(sections) + '\n').encode()
    outputs[core.ROOT + version + '-submitted-data.md'] = ('\n\n'.join(release) + '\n').encode()
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
