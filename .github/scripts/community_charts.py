"""Reuse the published v0.1.4 SVG layouts with validated, release-specific data.

No uploaded SVG is read. The two project-owned templates are pinned below;
fonts, colors, panels, legend and explanatory blocks come from those files.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

NS = 'http://www.w3.org/2000/svg'
TAG = '{' + NS + '}'
ET.register_namespace('', NS)
ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
TEMPLATES = {
    True: ('rtx-3060.svg', 'e765440716271ad13aeba960fb5bdc92080fd029d77f1ba2db64385d0f5775ec'),
    False: ('rtx-3090.svg', 'ea85da0bb463f299ba938716a67fafbdd265df939c6cea8027c62ce0f05833b2'),
}
SELECTED = (('compute', 'affine', ''), ('d4', '128x128', 'D4'),
            ('k', '64x64', 'root-uint4'), ('kw', '64x64', 'wave-root-uint4'))
COLORS = ('fill: #0c80bd', 'fill: #ef7100')


def template(qualified):
    """Read only the exact project template; reject unexplained layout changes."""
    name, expected = TEMPLATES[qualified]
    path = Path(__file__).resolve().parents[2] / 'Benchmark Results/charts' / name
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('CHART_TEMPLATE_IDENTITY')
    return ET.fromstring(raw)


def coordinates(path):
    """Read the eight coordinates of one pinned rectangular bar or panel."""
    values = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', path.get('d'))]
    if len(values) != 8:
        raise ValueError('CHART_TEMPLATE_RECTANGLE')
    return values


def move_text(node, y):
    """Retain typography and horizontal position while updating a data label's height."""
    node.set('y', f'{y:.6f}')
    node.set('transform', f'rotate(-0 {node.get("x")} {y:.6f})')


def rescale(axis, medians, format_duration):
    """Update only bars, tick values and numeric labels inside an existing panel."""
    values = [float(value) if value is not None else None for value in medians]
    paths = list(axis.iter(TAG + 'path'))
    background = next(x for x in paths if x.get('style') == 'fill: #ffffff')
    x0, bottom, x1, _, _, top, _, _ = coordinates(background)
    bars = [x for x in paths if x.get('style') in COLORS]
    if len(bars) != len(values):
        raise ValueError('CHART_TEMPLATE_BARS')
    positive = [v for v in values if v is not None]
    maximum = max(positive + [1]) * 1.3
    ticks = [g for g in axis.iter(TAG + 'g') if g.get('id', '').startswith('ytick_')]
    # The published charts use rounded locator steps, with independent panel limits.
    magnitude = 10 ** math.floor(math.log10(maximum / len(ticks)))
    step = next(x for x in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10)
                if x * magnitude >= maximum / len(ticks)) * magnitude
    for i, group in enumerate(ticks):
        if i * step > maximum:
            group.set('style', 'display: none')
            continue
        if group.get('style') == 'display: none':
            del group.attrib['style']
        y = bottom - (bottom - top) * i * step / maximum
        label = next(group.iter(TAG + 'text'))
        label.text = format_duration(f'{i * step:.12g}')
        grid = next(group.iter(TAG + 'path'))
        old_y = float(re.findall(r'-?\d+(?:\.\d+)?', grid.get('d'))[1])
        offset = float(label.get('y')) - old_y
        move_text(label, y + offset)
        grid.set('d', f'M {x0} {y:.6f} L {x1} {y:.6f}')
    texts = list(axis.iter(TAG + 'text'))
    for bar, value, median in zip(bars, values, medians):
        left, base, right, _, _, old_top, _, _ = coordinates(bar)
        center = (left + right) / 2
        annotation = next(t for t in texts if t.get('x') is not None and
                          abs(float(t.get('x')) - center) < 0.001
                          and re.fullmatch(r'~?[\d,.]+(?: ns| ms)?', t.text or ''))
        offset = float(annotation.get('y')) - old_top
        y = bottom if value is None else bottom - value / maximum * (bottom - top)
        if value is None:
            # Missing measurements are not zero-valued samples.
            bar.set('style', 'fill: none')
            annotation.text = 'NOT_RECORDED'
        else:
            annotation.text = format_duration(median, group=True)
        move_text(annotation, y + offset)
        bar.set('d', f'M {left} {base} L {right} {base} L {right} {y:.6f} L {left} {y:.6f} z')


def render(proposal, rows, context, package_id, format_duration):
    """Render validated summaries using the prior release's shared and independent scale designs."""
    lookup = {(r['suite'], r['case'], r['variant'], r['path']): r for r in rows}
    chosen = []
    for suite, case, variant in SELECTED:
        chosen.append([lookup.get((suite, case, variant, 'native')),
                       lookup.get((suite, case, '', 'vulkan'))])
    steps = proposal['run']['steps']
    qualified_count = sum(s['reported_clock_qualification'] == 'QUALIFIED' for s in steps)
    qualified = (len(steps) == 4 and qualified_count == 4 and
                 proposal['run']['overall'] == 'COMPLETE' and
                 all(a is not None and b is not None for a, b in chosen) and
                 all(s['reported_ns_per_tick_envelope'][0] <= 1 <=
                     s['reported_ns_per_tick_envelope'][1] for s in steps))
    root = template(qualified)
    axes = [g for g in root.iter(TAG + 'g') if g.get('id', '').startswith('axes_')]
    values = [[r['median'] if r else None for r in pair] for pair in chosen]
    if qualified:
        for axis, pair in zip(axes, values):
            rescale(axis, pair, format_duration)
    else:
        for i, axis in enumerate(axes):
            rescale(axis, [pair[i] for pair in values], format_duration)
    gpu = proposal['claimed_gpu'].split('/')[-1].replace('_', ' ')
    version, issue = proposal['claimed_version'], proposal['issue']
    backing = context['native_dx12']['backing']
    counts = proposal['run']['counts']
    samples = [r['n'] for pair in chosen for r in pair if r]
    sample_text = str(min(samples)) if samples and min(samples) == max(samples) else (
        f'{min(samples)}–{max(samples)}' if samples else 'not recorded')
    for text in root.iter(TAG + 'text'):
        value = text.text or ''
        value = value.replace('RTX 3060' if qualified else 'RTX 3090', gpu)
        value = value.replace('v0.1.4', version).replace('v21-r14', package_id)
        value = value.replace('NVIDIA Open 620.70.06', 'NVIDIA driver ' + proposal['driver'])
        value = value.replace('ISSUE #4' if qualified else 'ISSUE #5', 'ISSUE #' + str(issue))
        value = value.replace('SYSMEM', backing)
        if value.startswith('Native DX12 memory backing:'):
            value = ('Native DX12 memory backing: SYSMEM (system-memory buffers, not VRAM)'
                     if backing == 'SYSMEM' else 'Native DX12 memory backing: UNKNOWN (release evidence NOT_RECORDED)')
        if value.startswith('Seven exported values per median;'):
            value = f'{sample_text} exported values per displayed median; {counts["verified"]}/{counts["expected"]} statuses VERIFIED. Original GPU receipts unavailable.'
        if value in ('Model clarified by reporter; maintainer acceptance pending.',
                     'Host/GPU clock check NOT_QUALIFIED for all four suites.'):
            value = 'Reported ' + proposal['run']['overall'] + '; see source Issue for context. No independent GPU rerun.'
        if not qualified and value.startswith('CLOCK NOT QUALIFIED'):
            value = f'CLOCK: {qualified_count}/{len(steps)} reported QUALIFIED — independent scales'
        if not qualified and value.startswith('Host/GPU clock check NOT_QUALIFIED;'):
            value = 'Panels use independent scales. No cross-API ratio or cross-GPU ranking. Missing values are not zero.'
        text.text = value
    # Keep the same visible design while replacing the old template's memory evidence.
    for node in list(root):
        if node.tag == TAG + 'metadata' and node.get('id') == 'native-memory-backing':
            root.remove(node)
    metadata = ET.Element(TAG + 'metadata', {'id': 'memory-backing'})
    metadata.text = json.dumps(context, sort_keys=True)
    root.insert(0, metadata)
    source = ET.SubElement(root, TAG + 'metadata', {'id': 'submitted-measurements'})
    source.text = json.dumps({'issue': issue, 'release': version,
        'bundle_sha256': proposal['bundle_sha256'], 'selected': chosen}, sort_keys=True)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True) + b'\n'
