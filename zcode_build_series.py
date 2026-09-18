"""Generic series-drawing builder on the frozen template.

Usage:
  python3 zcode_build_series.py --src <pdf> --out-name <name.pdf> --model <text>

Assumes the BC-21 family sheet layout (9 groups measured once); the layout is
verified per source before building (see --check-only).  Title block comes
from the frozen factory: only the model value is swapped.
"""
from pathlib import Path
import argparse, csv, re, sys
import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / 'work'
OUT_DIR = ROOT / 'outputs' / 'ZCode_V10'
sys.path.insert(0, str(WORK))
from titleblock_factory import make_titleblock
from zcode_v10_bc21 import (make_layout_background, show_component,
                            place, GOLD)

DEFAULT_GROUPS = [  # BC-21 family: (src display box, center, max w, max h)
    ((78, 47, 177, 171),  (150, 125), 110, 115),
    ((281, 45, 441, 179), (360, 125), 150, 125),
    ((589, 45, 821, 182), (690, 148), 250, 150),
    ((45, 210, 219, 344), (132, 262), 140, 120),
    ((225, 204, 412, 354), (297, 270), 170, 148),
    ((444, 238, 540, 311), (470, 272), 100, 88),
    ((595, 204, 772, 435), (150, 440), 135, 187),
    ((52, 357, 204, 539), (320, 425), 125, 140),
    ((253, 420, 438, 528), (690, 330), 212, 124),
]

def measure_groups(src_path, set_rot):
    src = fitz.open(src_path); p = src[0]
    if set_rot: p.set_rotation(270)
    M = p.rotation_matrix
    items = []
    for x0, y0, x1, y1, t, *_ in p.get_text('words'):
        r = fitz.Rect((x0, y0, x1, y1)) * M
        if r.width < 300 and r.height < 300: items.append(r)
    for d in p.get_drawings():
        r = d['rect'] * M
        if r.width < 300 and r.height < 300: items.append(r)
    seeds = [g[0] for g in DEFAULT_GROUPS]
    out = []
    for s in seeds:
        seed = fitz.Rect(s); box = fitz.Rect(seed)
        for r in items:
            c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
            if seed.contains(c): box |= r
        box = fitz.Rect(max(box.x0, seed.x0 - 12), max(box.y0, seed.y0 - 12),
                        min(box.x1, seed.x1 + 12), min(box.y1, seed.y1 + 12))
        out.append([box.x0, box.y0, box.x1, box.y1])
    src.close()
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out-name', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--set-rot-270', action='store_true',
                    help='source page is portrait with sideways content')
    ap.add_argument('--groups-json', default=None,
                    help='optional JSON file: [[box,cx,cy,maxw,maxh],...] overriding the default layout')
    ap.add_argument('--check-only', action='store_true')
    args = ap.parse_args()

    groups = DEFAULT_GROUPS
    if args.groups_json:
        import json
        raw = json.load(open(args.groups_json))
        groups = [(tuple(g[0]), tuple(g[1]), g[2], g[3]) for g in raw]

    if args.check_only:
        boxes = measure_groups(args.src, args.set_rot_270)
        drift = max(max(abs(x - y) for x, y in zip(bx, g[0]))
                    for bx, g in zip(boxes, groups))
        print('layout drift vs template: %.1fpt' % drift)
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT = OUT_DIR / args.out_name
    title_png = WORK / ('titleblock_%s.png' % re.sub(r'[^\w]+', '_', args.model))
    make_titleblock(args.model, title_png)
    make_layout_background()

    src = fitz.open(args.src); sp = src[0]
    if args.set_rot_270: sp.set_rotation(270)
    out = fitz.open()
    p = out.new_page(width=sp.mediabox.width, height=sp.mediabox.height)
    p.set_cropbox(sp.cropbox); p.set_rotation(sp.rotation)
    p.insert_image(p.cropbox, filename=str(WORK / 'zcode_v10_background.png'),
                   keep_proportion=False, overlay=False)

    source_svg = sp.get_svg_image(matrix=fitz.Matrix(1, 1), text_as_path=True)
    source_svg = source_svg.replace('<svg ', '<svg fill="#0642a8" ', 1)
    source_svg = (source_svg.replace('#000000', '#0642a8')
                            .replace('#00ffff', '#e6a21a')
                            .replace('#808080', '#6f9bcf'))
    for box, c, mw, mh in groups:
        show_component(p, source_svg, box, place(box, c, mw, mh))

    title_display = fitz.Rect(400, 450, 820, 564)
    p.insert_image(title_display * p.derotation_matrix, filename=str(title_png),
                   rotate=270, keep_proportion=False, overlay=True)

    if OUT.exists(): OUT.unlink()
    out.save(OUT, garbage=4, deflate=True, clean=False)
    out.close(); src.close()

    ri, ro = PdfReader(args.src), PdfReader(str(OUT))
    pi, po = ri.pages[0], ro.pages[0]
    ok = (round(float(pi.mediabox.width), 2) == round(float(po.mediabox.width), 2)
          and round(float(pi.mediabox.height), 2) == round(float(po.mediabox.height), 2))
    print('PASS' if ok else 'FAIL', OUT)

if __name__ == '__main__':
    main()
