#!/usr/bin/env python3
"""Cube Matrix icon for Experiments/Cube-Matrix.md: an isometric 4 x 4 x 4 block of voxels.

Each voxel is a small cube with a gap to its neighbours and a soft gradient. Colours use the benchmark chart palette
(blue / green / orange) in horizontal bands; one front-top corner voxel is left out to show the inside of the block.
The pattern is illustrative, not scene data. Voxels are drawn back to front; a soft ellipse grounds the block.

Writes ../charts/cube-matrix.svg (self-contained, readable on light and dark backgrounds).
Usage: python3 make_cube_logo.py [--preview DIR]   (--preview also writes PNG previews; needs cairosvg)
"""
import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent      # Experiments/
N, S, GAP = 4, 26.0, 0.12           # voxels per edge, voxel pitch in px, gap as a fraction of the pitch
C30, S30 = math.cos(math.pi / 6), 0.5
EDGE = '#1f2937'
# The benchmark chart palette (tools/nvidia_charts.py: blue, orange, green).
BLUE, GREEN, ORANGE = (0x2a, 0x78, 0xd6), (0x1b, 0xaf, 0x7a), (0xeb, 0x68, 0x34)
FACE = {'top': 1.0, 'right': 0.80, 'left': 0.62}
EMPTY = {(3, 3, 3)}     # one unbuilt front-top corner


def proj(x, y, z):
    return ((x - y) * C30 * S, (x + y) * S30 * S - z * S)


def light(x, y, z):
    """Illustrative banding value: blue on top, green in the middle, orange below."""
    z = N - 1 - z
    return max(0.0, min(1.0, 0.18 + 0.22 * z + 0.10 * x - 0.05 * y))


def rgb_for(v):
    """Three bands of the palette; within a band the colour brightens slightly with the light value."""
    base, lo, hi = (BLUE, 0.0, 0.40) if v < 0.40 else (GREEN, 0.40, 0.62) if v < 0.62 else (ORANGE, 0.62, 1.0)
    t = (v - lo) / (hi - lo)
    return tuple(c * (0.92 + 0.16 * t) for c in base)


def hexc(rgb, k=1.0):
    return '#%02x%02x%02x' % tuple(max(0, min(255, round(c * k))) for c in rgb)


def voxel_faces(x, y, z):
    g = GAP / 2
    a0, a1 = g, 1 - g
    X0, X1, Y0, Y1, Z0, Z1 = x + a0, x + a1, y + a0, y + a1, z + a0, z + a1
    return {'top': [proj(X0, Y0, Z1), proj(X1, Y0, Z1), proj(X1, Y1, Z1), proj(X0, Y1, Z1)],
            'right': [proj(X1, Y0, Z0), proj(X1, Y1, Z0), proj(X1, Y1, Z1), proj(X1, Y0, Z1)],
            'left': [proj(X0, Y1, Z0), proj(X1, Y1, Z0), proj(X1, Y1, Z1), proj(X0, Y1, Z1)]}


def main():
    vox = [(x, y, z) for x in range(N) for y in range(N) for z in range(N) if (x, y, z) not in EMPTY]
    vox.sort(key=lambda p: (p[0] + p[1] + p[2], p[2]))          # back to front
    pts = [q for p in vox for f in voxel_faces(*p).values() for q in f]
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    pad = 6
    shadow_y = max(ys) + 4
    x0, y0 = min(xs) - pad, min(ys) - pad
    ground_cy, ground_ry = shadow_y - y0 - 2, N * S * 0.20
    w, h = max(xs) - x0 + pad, ground_cy + ground_ry + 2       # the whole ground ellipse inside the view box
    cx = (proj(N, 0, 0)[0] + proj(0, N, 0)[0]) / 2 - x0
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.1f %.1f" width="%d" height="%d" role="img" '
           'aria-label="Cube Matrix: a 4 by 4 by 4 block of voxels; sunlit voxels warm, shadowed voxels blue, '
           'removed voxels are empty space that is not stored">' % (w, h, round(w), round(h)),
           '<title>Cube Matrix</title>', '<defs>',
           '<radialGradient id="ground" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#000" stop-opacity="0.35"/>'
           '<stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>']
    grads, body = {}, []
    for x, y, z in vox:
        base = rgb_for(light(x, y, z))
        for face, poly in voxel_faces(x, y, z).items():
            k = FACE[face]
            key = (hexc(base, k * 1.10), hexc(base, k * 0.88))
            if key not in grads:
                gid = 'g%d' % len(grads)
                grads[key] = gid
                out.append('<linearGradient id="%s" x1="0" y1="0" x2="0.6" y2="1"><stop offset="0" stop-color="%s"/>'
                           '<stop offset="1" stop-color="%s"/></linearGradient>' % (gid, key[0], key[1]))
            d = ' '.join('%.2f,%.2f' % (px - x0, py - y0) for px, py in poly)
            body.append('<polygon points="%s" fill="url(#%s)" stroke="%s" stroke-opacity="0.55" stroke-width="0.8" '
                        'stroke-linejoin="round"/>' % (d, grads[key], EDGE))
            if face == 'top':      # thin highlight on the front edges of the top face
                (ax, ay), (bx, by), (cx2, cy2) = poly[1], poly[2], poly[3]
                body.append('<polyline points="%.2f,%.2f %.2f,%.2f %.2f,%.2f" fill="none" stroke="#ffffff" '
                            'stroke-opacity="0.35" stroke-width="0.9"/>' % (ax - x0, ay - y0, bx - x0, by - y0, cx2 - x0, cy2 - y0))
    out.append('</defs>')
    out.append('<ellipse cx="%.2f" cy="%.2f" rx="%.2f" ry="%.2f" fill="url(#ground)"/>'
               % (cx, ground_cy, N * S * C30 * 0.95, ground_ry))
    out += body
    out.append('</svg>')
    svg = '\n'.join(out) + '\n'
    (OUT / 'charts').mkdir(exist_ok=True)
    (OUT / 'charts/cube-matrix.svg').write_text(svg, encoding='utf-8')
    if '--preview' in sys.argv:
        import cairosvg
        preview = Path(sys.argv[sys.argv.index('--preview') + 1])
        preview.mkdir(parents=True, exist_ok=True)
        for bg, name in (('#ffffff', 'light'), ('#0d1117', 'dark')):
            cairosvg.svg2png(bytestring=svg.encode(), write_to=str(preview / ('cube-matrix-%s.png' % name)),
                             output_width=round(w * 2), background_color=bg)
    print('svg', len(svg), 'B', '%.0fx%.0f' % (w, h), 'voxels', len(vox))


if __name__ == '__main__':
    main()
