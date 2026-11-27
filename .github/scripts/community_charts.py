"""Plot sanitized series using the SVG layout from benchmark v0.1.5, tools/nvidia_charts.py."""
import html
import json
import math
import re
import textwrap
from itertools import cycle

WIDTH = 1400
PAD = 64
PANEL_GAP = 28
LEGEND_GAP = 40
MAX_PANELS_PER_ROW = 4
PLOT_LEFT = 110
PLOT_RIGHT = 24
MIN_VALUE_FONT = 8  # Below this size in a full-width panel, use the bar's tooltip.
PLOT_HEIGHT = 300
INK = '#0f2440'          # primary text
INK_2 = '#41536b'        # secondary text
INK_3 = '#66758a'        # muted text
GRID = '#e3e8ef'
AXIS = '#9aa6b6'
CARD = '#f6f8fb'
WHISKER = '#1c2836'
FONT = "Arial, 'Liberation Sans', Helvetica, 'Helvetica Neue', sans-serif"   # Arial metrics everywhere
# Validated with the dataviz palette checker (light, white surface, all pairs): blue, orange, aqua.
NATIVE, VULKAN, VARIANT = '#2a78d6', '#eb6834', '#1baf7a'


def text_width(text, size, bold=False):
    """Conservative width estimate for the Arial-metric FONT stack (measured <= 0.52 em, bold <= 0.56)."""
    return len(text) * size * (0.60 if bold else 0.56)


def wrap(text, size, width, bold=False):
    words, lines, line = text.split(), [], ''
    for word in words:
        trial = (line + ' ' + word).strip()
        if line and text_width(trial, size, bold) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines or ['']


def nice_axis(top):
    """Axis maximum and step: 4-6 clean ticks above the largest drawn value."""
    if top <= 0:
        return 1.0, 0.25
    raw = top / 5
    power = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        step = factor * power
        if step >= raw:
            break
    maximum = step * math.ceil(top / step)
    if maximum < top * 1.12:            # room for the value label above the tallest mark
        maximum += step
    return maximum, step


class Canvas:
    def __init__(self):
        self.parts = []

    def text(self, x, y, text, size, color=INK, bold=False, anchor='start'):
        weight = ' font-weight="700"' if bold else ''
        self.parts.append('<text x="%.1f" y="%.1f" font-size="%d" fill="%s"%s text-anchor="%s">%s</text>'
                          % (x, y, size, color, weight, anchor, html.escape(text)))

    def raw(self, markup):
        self.parts.append(markup)


def bar_path(x, y, w, h, r=4):
    """Column with a 4 px rounded data end and a square base."""
    r = min(r, w / 2, h)
    return ('M%.1f,%.1f V%.1f Q%.1f,%.1f %.1f,%.1f H%.1f Q%.1f,%.1f %.1f,%.1f V%.1f Z'
            % (x, y + h, y + r, x, y, x + r, y, x + w - r, x + w, y, x + w, y + r, y + h))


def legend_rows(series):
    """Keep each swatch and label together within the chart margins."""
    row, width = [], 0
    for item in series:
        item_width = 28 + text_width(item['label'], 17)
        if row and width + LEGEND_GAP + item_width > WIDTH - 2 * PAD:
            yield row, width
            row, width = [], 0
        width += (LEGEND_GAP if row else 0) + item_width
        row.append((item, item_width))
    if row:
        yield row, width


def layout(spec, format_duration, backing):
    c = Canvas()
    series = {s['key']: s for s in spec['series']}
    y = 76
    c.text(PAD, y, spec['title'], 38, bold=True)
    y += 42
    c.text(PAD, y, spec['subtitle'], 24, INK_2)
    for line in wrap('  ·  '.join(spec.get('context', [])), 17, WIDTH - 2 * PAD):
        y += 32
        c.text(PAD, y, line, 17, INK_3)
    y += 22
    c.raw('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>' % (PAD, y, WIDTH - PAD, y, GRID))
    y += 44
    for index, (row, width) in enumerate(legend_rows(spec['series'])):
        if index:
            y += 28
        x = (WIDTH - width) / 2
        for item, item_width in row:
            c.raw('<rect x="%.1f" y="%.1f" width="18" height="14" rx="3" fill="%s"/>' % (x, y - 12, item['color']))
            c.text(x + 28, y, item['label'], 17)
            x += item_width + LEGEND_GAP
    if spec.get('banner'):
        y += 30
        lines = wrap(spec['banner'], 17, WIDTH - 2 * PAD - 32, bold=True)
        c.raw('<rect x="%d" y="%.1f" width="%d" height="%d" rx="8" fill="#fff3e0"/>'
              % (PAD, y, WIDTH - 2 * PAD, 18 + 24 * len(lines)))
        for line in lines:
            y += 24
            c.text(PAD + 16, y, line, 17, bold=True)
        y += 18
    if spec.get('rows') is None:
        panel_bottom = panel_rows(c, series, spec['groups'], y + 30, format_duration)
    else:
        for row in spec['rows']:
            y += 52
            c.text(PAD, y, row['heading'], 22, bold=True)
            y = panel_rows(c, series, row['groups'], y + 16, format_duration)
        panel_bottom = y
    height = int(panel_bottom + 40)
    title = html.escape(spec['title'])
    head = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" '
            'aria-label="%s"><title>%s</title><rect width="100%%" height="100%%" fill="#ffffff"/>'
            '<g font-family="%s">' % (WIDTH, height, WIDTH, height, title, title, html.escape(FONT)))
    metadata = '<metadata>' + html.escape(json.dumps(backing, sort_keys=True)) + '</metadata>'
    return (head + ''.join(c.parts) + '</g>' + metadata + '</svg>\n').encode()


def panel_width(count):
    return (WIDTH - 2 * PAD - PANEL_GAP * (count - 1)) / count


def heading_lines(label, width):
    # In the chart's bold Arial-metric font, m and w are the only allowed
    # case-name glyphs wider than two thirds of an em.
    char_width = 22 if 'm' in label or 'w' in label else 22 * 2 / 3
    return textwrap.wrap(label, width=max(1, int(width / char_width)))


def value_label(bar, slot):
    label = bar['value_text']
    if text_width(label, 15) > slot - 8:
        # Keep full precision in the tooltip when using a compact annotation.
        ms = label.endswith(' ms')
        value = bar['value'] / 1_000_000 if ms else bar['value']
        label = f'≈{value:.3g} ' + ('ms' if ms else 'ns')
    return label, min(15, (slot - 8) / text_width(label, 1))


def panel_labels_fit(group, plot_width):
    slot = plot_width / max(1, len(group['bars']))
    return all(value_label(bar, slot)[1] >= MIN_VALUE_FONT
               for bar in group['bars'] if bar['value'] is not None)


def panel_rows(c, series, groups, top, format_duration):
    bottom = top
    start = 0
    while start < len(groups):
        row = groups[start:start + MAX_PANELS_PER_ROW]
        while len(row) > 1:
            plot_width = panel_width(len(row)) - PLOT_LEFT - PLOT_RIGHT
            if all(panel_labels_fit(group, plot_width) for group in row):
                break
            row.pop()
        bottom = panel_row(c, series, row, top, format_duration)
        top = bottom + PANEL_GAP
        start += len(row)
    return bottom


def panel_row(c, series, groups, top, format_duration):
    """One row of panels (one per group) from y = top; returns the bottom of its panels."""
    panel_w = panel_width(max(1, len(groups)))
    headings = [heading_lines(g['label'], panel_w - 40) for g in groups]
    bar_label_lines = 1
    for g in groups:
        slot = (panel_w - PLOT_LEFT - PLOT_RIGHT) / max(1, len(g['bars']))
        for b in g['bars']:
            bar_label_lines = max(bar_label_lines, len(wrap(series[b['series']]['short'], 14, slot - 8)))
    extra_lines = max((len(lines) for lines in headings), default=1) - 1
    plot_top = top + 110 + 26 * extra_lines
    plot_bottom = plot_top + PLOT_HEIGHT
    panel_bottom = plot_bottom + 22 + 18 * bar_label_lines + 18
    for index, g in enumerate(groups):
        x0 = PAD + index * (panel_w + PANEL_GAP)
        c.raw('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="12" fill="%s"/>'
              % (x0, top, panel_w, panel_bottom - top, CARD))
        for line_index, line in enumerate(headings[index]):
            c.text(x0 + 20, top + 38 + line_index * 26, line, 22, bold=True)
        drawn = [b for b in g['bars'] if b['value'] is not None]
        highest = max([max(b['value'], b.get('high') or b['value']) for b in drawn] + [0])
        maximum, step = nice_axis(highest)
        left, right = x0 + PLOT_LEFT, x0 + panel_w - PLOT_RIGHT

        def ypos(v):
            return plot_bottom - PLOT_HEIGHT * v / maximum
        c.text(left - 54, plot_top - 22, 'GPU time', 14, INK_3)
        for tick_index in range(int(round(maximum / step)) + 1):
            tick = tick_index * step
            ty = ypos(tick)
            c.raw('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>'
                  % (left, ty, right, ty, AXIS if tick == 0 else GRID))
            c.text(left - 10, ty + 5, format_duration(f'{tick:.12g}', group=True), 14, INK_3, anchor='end')
        slot = (right - left) / max(1, len(g['bars']))
        bar_w = min(64, slot * 0.56)
        for k, b in enumerate(g['bars']):
            s = series[b['series']]
            cx = left + slot * (k + 0.5)
            if b['value'] is None:
                c.text(cx, plot_bottom - 12, 'not measured', 14, INK_3, anchor='middle')
            else:
                by = ypos(b['value'])
                tip = html.escape(b.get('tip', ''))
                c.raw('<g><title>%s</title><path d="%s" fill="%s"/></g>'
                      % (tip, bar_path(cx - bar_w / 2, by, bar_w, plot_bottom - by), s['color']))
                label_y = by
                if b.get('low') is not None and b.get('high') is not None and b['high'] > b['low']:
                    lo, hi = ypos(b['low']), ypos(b['high'])
                    c.raw('<path d="M%.1f,%.1f V%.1f M%.1f,%.1f H%.1f M%.1f,%.1f H%.1f" stroke="%s" '
                          'stroke-width="1.6" fill="none"/>' % (cx, lo, hi, cx - 7, hi, cx + 7, cx - 7, lo, cx + 7,
                                                               WHISKER))
                    label_y = min(label_y, hi)
                label, size = value_label(b, slot)
                if size >= MIN_VALUE_FONT:
                    c.text(cx, label_y - 10, label, size, anchor='middle')
            for m, line in enumerate(wrap(s['short'], 14, slot - 8)):
                c.text(cx, plot_bottom + 24 + 18 * m, line, 14, INK_2, anchor='middle')
    return panel_bottom

# This order matches the benchmark report and is independent of CSV row order.
CASES = ('affine', 'affine515', 'parallel-sort', '128x128', '32x512', '16x1024',
         '64x64', '127x65', '1920x1080')
VARIANTS = {
    '': 'Native DX12', 'B': 'Original', 'D4': 'D4', 'Q8PL': 'Q8PL',
    'root-scalar': 'K root scalar', 'root-uint4': 'K root uint4',
    'wave-root-scalar': 'WF scalar', 'wave-root-uint4': 'WF uint4',
    'block': 'FWHT', 'scalar': 'Scalar', 'tensor': 'Tensor Core',
    'constant': 'Constant loads', 'strong': 'Strong loads',
}


def render_suite(title, label, proposal, step, rows, schedule, format_duration, backing, run_context):
    """Render every scheduled arm once, with the measured range and process count."""
    lookup = {(r['case'], r['variant'], r['path']): r for r in rows}
    # Cases and arms that a later release adds follow the known ones, under their own names.
    arms = {arm for _, arm, path in schedule if path == 'native'}
    variants = [v for v in VARIANTS if v in arms] + sorted(arms - set(VARIANTS))
    cases = [c for c in CASES if any(case == c for case, _, _ in schedule)]
    cases += sorted({case for case, _, _ in schedule} - set(CASES))
    series = [dict(key=('native', v), label=('Native DX12 · ' if v else '') + VARIANTS.get(v, v),
                   short=VARIANTS.get(v, v), color=color)
              for v, color in zip(variants, cycle((NATIVE, VARIANT, '#8555ac', '#b8860b')))]
    if any(path == 'vulkan' for _, _, path in schedule):
        series.append(dict(key=('vulkan', ''), label='Vulkan NVIDIA', short='Vulkan NVIDIA', color=VULKAN))
    groups = []
    for case in cases:
        bars = []
        for item in series:
            path, variant = item['key']
            if (case, variant, path) not in schedule:
                continue
            row = lookup.get((case, variant, path))
            bar = dict(series=item['key'], value=None)
            if row:
                median, low, high = (row[k] for k in ('median', 'minimum', 'maximum'))
                bar.update(value=float(median), low=float(low), high=float(high),
                           value_text=format_duration(median, group=True),
                           tip=(f'{item["label"]}, {case}: median {format_duration(median, group=True, exact=True)}, '
                                f'range {format_duration(low, group=True)} to {format_duration(high, group=True)}, '
                                f'{row["n"]} processes'))
            bars.append(bar)
        if bars:
            heading = case.replace('x', ' × ') if re.fullmatch(r'[0-9]+(?:x[0-9]+)+', case) else case
            groups.append(dict(label=heading, bars=bars))
    envelope = step['reported_ns_per_tick_envelope']
    overall = proposal['run']['overall']
    shared = (overall == 'COMPLETE' and step['reported_clock_qualification'] == 'QUALIFIED'
              and envelope and envelope[0] <= 1 <= envelope[1] and
              all(bar['value'] is not None for group in groups for bar in group['bars']))
    counts = proposal['run']['counts']
    context = [proposal['claimed_gpu'].split('/')[0] + ' driver ' + proposal['driver'],
               'Host/GPU clock check: ' + step['reported_clock_qualification'],
               f'Reported {overall} · {counts["verified"]}/{counts["expected"]} verified',
               'Native buffers (release): ' + backing['native_dx12']['backing']]
    if any(s['key'][0] == 'vulkan' for s in series):
        context.append('Vulkan buffers: ' + backing['vulkan']['backing'])
    if 'reported_os' in run_context:
        context.append(run_context['reported_os'])
    if 'reported_gpu_load' in run_context:
        context.append('Reported GPU load: ' + run_context['reported_gpu_load'])
    spec = dict(title=title, subtitle=label, series=series, groups=groups, context=context)
    if overall != 'COMPLETE':
        spec['banner'] = 'Reported run status: ' + overall
    if not shared:
        spec['rows'] = []
        for path, heading in (('native', 'Native DX12'), ('vulkan', 'Vulkan NVIDIA')):
            panels = [dict(label=g['label'], bars=[b for b in g['bars'] if b['series'][0] == path]) for g in groups]
            panels = [panel for panel in panels if panel['bars']]
            if panels:
                spec['rows'].append(dict(heading=heading + ' · independent scale', groups=panels))
    return layout(spec, format_duration, backing)
