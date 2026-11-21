#!/usr/bin/env python3
"""Charts and CSV tables for Experiments/Cube-Matrix.md and Experiments/Neural-Grid.md.

Every number is a median GPU duration in nanoseconds copied from the recorded campaigns named in SOURCES; nothing is
recomputed here. Palette: the benchmark charts' blue / orange / green (tools/nvidia_charts.py) on a white card.
Green is below 3:1 contrast on white, so every bar carries its value and every chart has a CSV table.
Static SVG for GitHub (no hover layer is possible in an <img>).

Writes ../charts/*.svg and ../data/*.csv.
Usage: python3 make_charts.py [--preview DIR]   (--preview also writes PNG previews; needs cairosvg)
"""
import csv
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent      # Experiments/
BLUE, ORANGE, GREEN = '#2a78d6', '#eb6834', '#1baf7a'
INK, INK2, INK3, GRID, CARD = '#0f2440', '#41536b', '#66758a', '#e3e8ef', '#ffffff'
FONT = "Arial, 'Liberation Sans', Helvetica, sans-serif"

SOURCES = {   # public campaign identifiers (Evidence identities in the pages); private result files are not named
    'cube-matrix-constant-loads': 'campaigns tc-061 (lighting) and tc-063 (decoder + lighting frame), RTX 4090',
    'neural-grid-bounce-cost': 'campaign ngb-4060-001, RTX 4060 Ti, 1920x1080',
    'neural-grid-tc-loads': 'campaign ngb-4090-054, RTX 4090, 1920x1080',
}

CHARTS = {
    'cube-matrix-constant-loads': dict(
        title='Cube Matrix on RTX 4090: strong vs constant buffer loads',
        subtitle='Median GPU time per frame, lower is better. Same source, same data, bit-exact images.',
        series=[('Strong GPU-scope loads (before)', BLUE), ('Constant loads (nir_opt_access / CAN_REORDER)', GREEN)],
        rows=[('Lighting, dense 64³ grid', (124800, 62608)),
              ('Lighting, sparse 64³ via block table', (242400, 73136)),
              ('Lighting, sparse 256³ via block table', (124240, 75040)),
              ('Frame: scalar 4-bit decoder + lighting', (508688, 268464)),
              ('Frame: Tensor Core decoder + lighting', (513072, 271280))]),
    'neural-grid-tc-loads': dict(
        title='Neural Grid bounce programs on RTX 4090: load kinds',
        subtitle='Median GPU time, 1920×1080, lower is better. Images bit-exact in all variants.',
        series=[('All loads strong (before)', BLUE), ('nir_opt_access (cmat loads stay strong)', ORANGE),
                ('All loads constant, incl. cmat', GREEN)],
        rows=[('Ray march only', (2947808, 1321584, 1321584)),
              ('Tensor Core, B by columns', (4002048, 4003376, 1191952)),
              ('Tensor Core, B by rows', (8143376, 8140640, 3561872)),
              ('Tensor Core + march, columns', (5738160, 4110448, 2302256)),
              ('Tensor Core + march, rows', (9675600, 8211088, 4612160))]),
    'neural-grid-bounce-cost': dict(
        title='Indirect light on RTX 4060 Ti: cube lookup vs rays',
        subtitle='Median GPU time, 1920×1080, lower is better (strong loads, before the compiler fix).',
        series=[('GPU time', BLUE)],
        rows=[('4 rays per pixel + filter', (56919744,)),
              ('1 ray per pixel + filter', (22922640,)),
              ('Cube lookup, 13 cm voxels', (697344,)),
              ('Cube lookup, 52 cm voxels', (687952,))]),
}


def esc(t):
    return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def format_duration(ns):
    if ns < 1_000_000:
        return f'{ns:,} ns'
    hundredths = (ns + 5000) // 10_000
    whole, fraction = divmod(hundredths, 100)
    return f'{whole}.{fraction:02d}'.rstrip('0').rstrip('.') + ' ms'


def chart(name, spec):
    W, left, right = 860, 300, 135
    bar, gap_bar, gap_row = 16, 2, 18
    n = len(spec['series'])
    top = 96 + 22 * ((n + 1) // 2) if n > 1 else 84    # a single series needs no legend
    row_h = n * bar + (n - 1) * gap_bar + gap_row
    H = top + row_h * len(spec['rows']) + 30
    vmax = max(v for _, vals in spec['rows'] for v in vals)
    scale = (W - left - right) / vmax
    o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" font-family="%s" role="img" '
         'aria-label="%s">' % (W, H, W, H, FONT, esc(spec['title'])), '<title>%s</title>' % esc(spec['title']),
         '<rect width="%d" height="%d" rx="10" fill="%s" stroke="%s"/>' % (W, H, CARD, GRID),
         '<text x="24" y="36" font-size="19" font-weight="700" fill="%s">%s</text>' % (INK, esc(spec['title'])),
         '<text x="24" y="60" font-size="13" fill="%s">%s</text>' % (INK2, esc(spec['subtitle']))]
    for i, (label, colour) in enumerate(spec['series'] if n > 1 else []):   # legend, two per line
        lx, ly = 24 + (i % 2) * 400, 88 + 22 * (i // 2)
        o.append('<rect x="%d" y="%d" width="12" height="12" rx="3" fill="%s"/>' % (lx, ly - 10, colour))
        o.append('<text x="%d" y="%d" font-size="13" fill="%s">%s</text>' % (lx + 18, ly, INK2, esc(label)))
    for g in range(1, 5):                                           # recessive grid
        x = left + (W - left - right) * g / 4
        o.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s"/>' % (x, top - 8, x, H - 26, GRID))
        o.append('<text x="%.1f" y="%d" font-size="11" fill="%s" text-anchor="middle">%s</text>'
                 % (x, H - 10, INK3, format_duration(int(round(vmax * g / 4, -3)))))
    o.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s"/>' % (left, top - 8, left, H - 26, INK3))
    for r, (label, vals) in enumerate(spec['rows']):
        y0 = top + r * row_h
        o.append('<text x="%d" y="%.1f" font-size="13" fill="%s" text-anchor="end">%s</text>'
                 % (left - 10, y0 + (n * bar + (n - 1) * gap_bar) / 2 + 4, INK, esc(label)))
        for s, v in enumerate(vals):
            y = y0 + s * (bar + gap_bar)
            w = max(2.0, v * scale)
            colour = spec['series'][s][1]
            o.append('<path d="M%d,%d h%.1f a4,4 0 0 1 4,4 v%d a4,4 0 0 1 -4,4 h-%.1f z" fill="%s"/>'
                     % (left, y, w - 4, bar - 8, w - 4, colour))
            note = format_duration(v) if s == 0 else '%s  (%.2f×)' % (format_duration(v), v / vals[0])
            o.append('<text x="%.1f" y="%d" font-size="12" fill="%s">%s</text>' % (left + w + 6, y + bar - 4, INK2, note))
    o.append('</svg>')
    svg = '\n'.join(o) + '\n'
    (OUT / 'charts' / (name + '.svg')).write_text(svg, encoding='utf-8')
    with (OUT / 'data' / (name + '.csv')).open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['case'] + [s + ' (ns)' for s, _ in spec['series']] + ['source'])
        for label, vals in spec['rows']:
            w.writerow([label] + list(vals) + [SOURCES[name]])
    if '--preview' in sys.argv:
        import cairosvg
        preview = Path(sys.argv[sys.argv.index('--preview') + 1])
        preview.mkdir(parents=True, exist_ok=True)
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(preview / (name + '.png')), output_width=W)


def main():
    for d in ('charts', 'data'):
        (OUT / d).mkdir(exist_ok=True)
    for name, spec in CHARTS.items():
        chart(name, spec)
        print(name)


if __name__ == '__main__':
    main()
