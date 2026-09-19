"""Per-drawing quality build: SVG-space measure -> global-fit build -> QA render."""
from pathlib import Path
import sys, json, re
import fitz
import numpy as np
from PIL import Image, ImageFilter
from collections import deque

W = Path(__file__).resolve().parent
ROOT = W.parent
OUT = ROOT / 'outputs' / 'ZCode_V10'
sys.path.insert(0, str(W))
from titleblock_factory import make_titleblock
from zcode_v10_bc21 import make_layout_background, show_component
from build_raster import build_raster  # noqa: F401  (备用的光栅方案)


def svg_boxes(src_path):
    src = fitz.open(src_path)
    sp = src[0]
    if sp.mediabox.height > sp.mediabox.width and sp.rotation == 0:
        sp.set_rotation(270)
    svg = sp.get_svg_image(matrix=fitz.Matrix(1, 0, 0, 1, 0, 0))
    doc = fitz.open(stream=svg.encode(), filetype='svg')
    pix = doc[0].get_pixmap(dpi=150)
    a = np.asarray(Image.frombytes('RGB', (pix.width, pix.height), pix.samples)).astype(int)
    sc = a.shape[1] / 841.89
    ink = a.mean(axis=2) < 150
    ink[:int(32 * sc), :] = False
    ink[int(556 * sc):, :] = False
    ink[:, :int(32 * sc)] = False
    ink[:, int(816 * sc):] = False
    dil = np.asarray(Image.fromarray((ink * 255).astype('uint8')).filter(
        ImageFilter.MaxFilter(13))) > 0
    k = 4
    small = dil[::k, ::k]
    lab = np.zeros(small.shape, dtype=int)
    cur = 0
    comps = []
    h, w = small.shape
    for i in range(h):
        for j in range(w):
            if small[i, j] and lab[i, j] == 0:
                cur += 1
                q = deque([(i, j)])
                lab[i, j] = cur
                bx0 = bx1 = j
                by0 = by1 = i
                n = 0
                while q:
                    y, x = q.popleft()
                    n += 1
                    if x < bx0: bx0 = x
                    if x > bx1: bx1 = x
                    if y < by0: by0 = y
                    if y > by1: by1 = y
                    for ddy in (-1, 0, 1):
                        for ddx in (-1, 0, 1):
                            ny = y + ddy
                            nx = x + ddx
                            if 0 <= ny < h and 0 <= nx < w and small[ny, nx] and lab[ny, nx] == 0:
                                lab[ny, nx] = cur
                                q.append((ny, nx))
                bw = (bx1 - bx0) * k / sc
                bh = (by1 - by0) * k / sc
                if n * k * k > 800 and bw > 25 and bh > 18:
                    comps.append([bx0 * k / sc, by0 * k / sc,
                                  (bx1 + 1) * k / sc, (by1 + 1) * k / sc])
    comps.sort(key=lambda c: -(c[2] - c[0]) * (c[3] - c[1]))
    src.close()
    return comps, ink, sc


def extract_model(page, M, fallback):
    anchor = None
    words = []
    for x0, y0, x1, y1, t, *_ in page.get_text('words'):
        r = fitz.Rect((x0, y0, x1, y1)) * M
        words.append((r, t.strip()))
        if ('图号' in t or 'MODEL' in t) and anchor is None:
            anchor = r
    if anchor is not None:
        cy = (anchor.y0 + anchor.y1) / 2
        cands = [w for r, w in words
                 if r is not anchor and abs((r.y0 + r.y1) / 2 - cy) < 16
                 and r.x0 > anchor.x1 - 10 and r.x0 < anchor.x1 + 200
                 and '图号' not in w and 'MODEL' not in w]
        if cands:
            cands.sort()
            return ''.join(cands)
    fb = re.sub(r'^2D_', '', fallback.rsplit('.', 1)[0])
    return re.sub(r'[（(]cad2pdf[)）]', '', fb).strip('_ ')


def run(src_pdf, out_pdf, model, qa_png, content_bottom=None, drop_y0=None):
    """SVG 测框（剔除旧标题栏带）→ 全局保位变换构建 → QA 渲染"""
    OUT_DIR = ROOT / 'outputs' / 'ZCode_V10'
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    boxes, svg_ink, svg_sc = svg_boxes(src_pdf)
    # 修剪：剔除源图框/旧标题栏/Autodesk水印带（y<30 或 y>485 的内容带）
    cleaned = []
    for b in boxes:
        by0, by1 = max(b[1], 30.0), min(b[3], 485.0)
        if by1 - by0 < 15:
            continue
        # 框内重测紧致墨迹包围盒
        sub = svg_ink[int(by0 * svg_sc):int(by1 * svg_sc),
                      int(b[0] * svg_sc):int(b[2] * svg_sc)]
        ys, xs = np.where(sub)
        if len(ys) == 0:
            continue
        nb = [b[0] + xs.min() / svg_sc, by0 + ys.min() / svg_sc,
              b[0] + (xs.max() + 1) / svg_sc, by0 + (ys.max() + 1) / svg_sc]
        if nb[2] - nb[0] < 15 or nb[3] - nb[1] < 15:
            continue
        cleaned.append([round(v, 1) for v in nb])
    boxes = cleaned
    if not boxes:
        raise RuntimeError('no content groups')
    ux0 = min(b[0] for b in boxes); uy0 = min(b[1] for b in boxes)
    ux1 = max(b[2] for b in boxes); uy1 = max(b[3] for b in boxes)
    # 目标区：图框内 (36,30)-(806,458)，等比缩放居中
    dst = (36, 30, 806, 458)
    s = min((dst[2] - dst[0]) / (ux1 - ux0), (dst[3] - dst[1]) / (uy1 - uy0))
    pw, ph = (ux1 - ux0) * s, (uy1 - uy0) * s
    dx = dst[0] + ((dst[2] - dst[0]) - pw) / 2
    dy = dst[1] + ((dst[3] - dst[1]) - ph) / 2
    gfit = json.dumps([ux0, uy0, ux1, uy1, dx, dy, dx + pw, dy + ph])

    make_titleblock(model, W / '_tb_row.png')
    make_layout_background(rev_table=False, out_path=W / 'zcode_v10_background_norev.png')

    src = fitz.open(src_pdf)
    sp = src[0]
    if sp.mediabox.height > sp.mediabox.width and sp.rotation == 0:
        sp.set_rotation(270)
    out = fitz.open()
    p = out.new_page(width=sp.mediabox.width, height=sp.mediabox.height)
    p.set_cropbox(sp.cropbox)
    p.set_rotation(sp.rotation)
    p.insert_image(p.cropbox, filename=str(W / 'zcode_v10_background_norev.png'),
                   keep_proportion=False, overlay=False)
    svg = sp.get_svg_image(matrix=fitz.Matrix(1, 0, 0, 1, 0, 0), text_as_path=True)
    svg = svg.replace('<svg ', '<svg fill="#0642a8" ', 1)
    svg = (svg.replace('#000000', '#0642a8')
              .replace('#00ffff', '#e6a21a')
              .replace('#808080', '#6f9bcf'))
    gx0, gy0, gx1, gy1, dx0, dy0, dx1, dy1 = json.loads(gfit)
    sc = s
    for box in boxes:
        px0 = dx0 + (box[0] - gx0) * sc
        py0 = dy0 + (box[1] - gy0) * sc
        px1 = dx0 + (box[2] - gx0) * sc
        py1 = dy0 + (box[3] - gy0) * sc
        show_component(p, svg, box, (px0, py0, px1, py1))
    t = fitz.Rect(400, 450, 820, 564) * p.derotation_matrix
    p.insert_image(t, filename=str(W / '_tb_row.png'), rotate=270,
                   keep_proportion=False, overlay=True)
    out_path = Path(out_pdf)
    if out_path.exists():
        out_path.unlink()
    out.save(out_path, garbage=4, deflate=True, clean=False)
    out.close()
    src.close()
    d2 = fitz.open(out_path)
    ok = d2[0].rect.width > d2[0].rect.height
    d2[0].get_pixmap(dpi=120).save(qa_png)
    d2.close()
    return ok, len(boxes), gfit
