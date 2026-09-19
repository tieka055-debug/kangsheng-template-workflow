"""Measure content-group boxes in SVG-render coordinates."""
import sys, json
import fitz
import numpy as np
from PIL import Image, ImageFilter
from collections import deque


def svg_boxes(src_path):
    src = fitz.open(src_path)
    sp = src[0]
    if sp.mediabox.height > sp.mediabox.width and sp.rotation == 0:
        sp.set_rotation(270)
    svg = sp.get_svg_image(matrix=fitz.Matrix(1, 0, 0, 1, 0, 0))
    doc = fitz.open(stream=svg.encode(), filetype='svg')
    pix = doc[0].get_pixmap(dpi=150)
    a = np.asarray(Image.frombytes('RGB', (pix.width, pix.height), pix.samples)).astype(int)
    src_w = a.shape[1]
    sc = src_w / 841.89
    ink = a.mean(axis=2) < 150
    ink[:int(26 * sc), :] = False
    ink[int(558 * sc):, :] = False
    ink[:, :int(20 * sc)] = False
    ink[:, int(820 * sc):] = False
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
                    comps.append([round(bx0 * k / sc, 1), round(by0 * k / sc, 1),
                                  round((bx1 + 1) * k / sc, 1), round((by1 + 1) * k / sc, 1)])
    comps.sort(key=lambda c: -(c[2] - c[0]) * (c[3] - c[1]))
    src.close()
    return comps


if __name__ == '__main__':
    out = {}
    for tag, f in [('R1.25', 'work/2D_BC-16系列1.8H-R1.25 Model.pdf'),
                   ('R1.9', 'work/2D_BC-16系列1.8H-R1.9 Model.pdf')]:
        boxes = svg_boxes(f)
        out[tag] = boxes
        print(tag, ':')
        for c in boxes:
            print('  ', c)
    json.dump(out, open('work/bc16_svg_boxes.json', 'w'), indent=1)
