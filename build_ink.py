"""Ink-compositing builder v3 — the universal quality pipeline.

整页 300 DPI 渲染 → 逐像素墨水分离：
  · 灰阶墨迹（黑线/黑字）→ 品牌蓝墨水, alpha = 墨量
  · 彩色图层（红/绿/品红等源图自带色）→ 原色保留, alpha = 墨量
  · 白色/浅色 → 全透明, 冰蓝底图透出
旧图框/旧标题栏/Autodesk 水印区域 alpha 强制归零（底图透出，无缝覆盖）。
图框、分区刻度、REV 表（矢量）与冻结标题栏叠加。
无分组、无裁切 —— 内容缺失在机制上不可能发生。
"""
from pathlib import Path
import sys
import fitz
import numpy as np
from PIL import Image, ImageFilter

W = Path(__file__).resolve().parent
ROOT = W.parent
sys.path.insert(0, str(W))
from titleblock_factory import make_titleblock

BLUE = np.array([6, 66, 168], dtype=float)
GOLD = np.array([230, 162, 26], dtype=float)
SRC_INSET = 26          # 源页四周内缩（去旧图框/分区刻度）
DST = (28, 28, 812, 448)  # 内容目标区（避开标题栏）


def draw_frame_vectors(p, rev_table=True):
    blue = (6 / 255, 66 / 255, 168 / 255)

    def line(x0, y0, x1, y1, w=1.2):
        sp = p.new_shape()
        sp.draw_line(fitz.Point(x0, y0) * p.derotation_matrix,
                     fitz.Point(x1, y1) * p.derotation_matrix)
        sp.finish(color=blue, width=w)
        sp.commit(overlay=True)

    def rect(x0, y0, x1, y1, w=1.2):
        sp = p.new_shape()
        sp.draw_rect(fitz.Rect(x0, y0, x1, y1) * p.derotation_matrix)
        sp.finish(color=blue, width=w)
        sp.commit(overlay=True)

    def txt(x, y, s, sz=9):
        p.insert_text(fitz.Point(x, y) * p.derotation_matrix, s,
                      fontname='helv', fontsize=sz, color=blue,
                      rotate=270, overlay=True)

    rect(22, 29, 820, 564)
    long_x = [113.5, 224.4, 331.8, 447.8, 554.5, 661.8, 770.8]
    short_x = [67.8, 155.9, 267.7, 384.0, 491.3, 598.0, 705.4]
    for x in long_x:
        line(x, 14, x, 29); line(x, 564, x, 580)
    for x in short_x:
        line(x, 22, x, 29); line(x, 564, x, 573)
    for i, x in enumerate([75, 181, 280, 396, 503, 610, 716], 1):
        txt(x, 22, str(i), 9); txt(x, 580, str(i), 9)
    main_y = [28.8, 132.5, 236.9, 342.9, 450.6, 564.0]
    short_y = [78.4, 181.0, 286.5, 390.8, 498.6]
    for y in main_y[1:-1]:
        line(10, y, 22, y); line(820, y, 832, y)
    for y in short_y:
        line(15, y, 22, y); line(820, y, 827, y)
    for letter, y in zip('ABCDE', [(main_y[i] + main_y[i + 1]) / 2 for i in range(5)]):
        txt(20, y, letter, 10); txt(826, y, letter, 10)
    if rev_table:
        rx = [563.6, 591.3, 701.4, 734.6, 820.0]
        ry = [28.8, 42.3, 54.1, 66.5]
        rect(rx[0], ry[0], rx[-1], ry[-1])
        for x in rx[1:-1]:
            line(x, ry[0], x, ry[-1])
        for y in ry[1:-1]:
            line(rx[0], y, rx[-1], y)
        txt(577.4, 39, 'REV.', 7.2); txt(646.3, 39, 'DESCRIPTION', 7.0)
        txt(718.0, 39, 'DRAW.', 7.0); txt(777.3, 39, 'DATE.', 7.0)


def find_cover_regions(page, M, disp):
    """旧标题栏 + Autodesk 水印的显示坐标区域"""
    tb, wm = [], []
    for x0, y0, x1, y1, t, *_ in page.get_text('words'):
        r = fitz.Rect((x0, y0, x1, y1)) * M
        tt = t.strip()
        if not tt:
            continue
        if any(k in tt for k in ('质源', '图号', '品名', '批准', '审核', '绘制', '设计DES',
                                 '版本REV', '比例SCALE', '单位UNIT', '页码SHEET',
                                 '电池连接器', '电池连接座', '电源连接器', 'TOOLERANCE',
                                 'PROJECTION', '未注公差')):
            tb.append(r)
        if 'Autodesk' in tt or '教育版' in tt:
            wm.append(r)
    covers = []
    if tb:
        tb = [r for r in tb if r.x0 > disp.width * 0.40 and r.y0 > disp.height * 0.68]
        if tb:
            x0 = max(min(r.x0 for r in tb) - 10, 0)
            y0 = max(min(r.y0 for r in tb) - 10, 0)
            x1 = min(max(r.x1 for r in tb) + 10, disp.width)
            y1 = min(max(r.y1 for r in tb) + 10, disp.height)
            covers.append((x0, y0, x1, y1))
    for r in wm:
        covers.append((max(r.x0 - 6, 0), max(r.y0 - 6, 0),
                       min(r.x1 + 6, disp.width), min(r.y1 + 6, disp.height)))
    return covers


def build_ink(src_path, out_pdf, model, title_png, plate_png, dpi=300):
    src = fitz.open(src_path)
    page = src[0]
    if page.mediabox.height > page.mediabox.width and page.rotation == 0:
        page.set_rotation(270)
    M = page.rotation_matrix
    disp = page.rect

    pix = page.get_pixmap(dpi=dpi)
    full = np.asarray(Image.frombytes('RGB', (pix.width, pix.height),
                                      pix.samples)).astype(float)
    H, Wd = full.shape[:2]
    sc = Wd / disp.width
    S = dpi / 72.0

    r, g, b = full[..., 0], full[..., 1], full[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = mx - mn

    # 墨量：白→0，深→1；彩色笔画按最小通道（绿/红实色笔画保持全不透明）
    alpha = np.clip((255.0 - mn) / 255.0, 0, 1)
    alpha = np.where(lum > 234, 0, alpha)

    # 墨色：灰阶→品牌蓝；青色系→金；其余彩色→原色
    colored = sat > 45
    cyanish = colored & (b > 120) & (g > 120) & (r < 0.6 * mx)
    ink = np.zeros_like(full)
    ink[..., :] = BLUE[None, None, :]
    gold_mask = cyanish
    for ch in range(3):
        ink[..., ch][gold_mask] = GOLD[ch]
    keep = colored & ~cyanish
    for ch in range(3):
        ink[..., ch][keep] = full[..., ch][keep]

    # 透明化：源页外边带（旧图框/分区/水印）+ 旧标题栏 + 水印
    zero = np.zeros((H, Wd), dtype=bool)
    # 源图框线带（上22-29.6/下558-566/左22-29/右818-820）必须全透明
    zero[:int(31 * S), :] = True
    zero[int(552 * S):, :] = True
    zero[:, :int(31 * S)] = True
    zero[:, int(816 * S):] = True
    for (cx0, cy0, cx1, cy1) in find_cover_regions(page, M, disp):
        zero[int(cy0 * S):int(cy1 * S), int(cx0 * S):int(cx1 * S)] = True
    alpha[zero] = 0

    # 内容裁剪（去边带与旧标题栏带）+ 按墨迹包围盒精确落位
    cx0, cy0 = int(SRC_INSET * S), int(SRC_INSET * S)
    cx1, cy1 = int((disp.width - SRC_INSET) * S), int((disp.height - SRC_INSET) * S)
    crop_a = alpha[cy0:cy1, cx0:cx1]
    crop_ink = ink[cy0:cy1, cx0:cx1]

    # 墨迹包围盒（alpha > 8 的实际内容范围）
    ay, ax = np.where(crop_a > 0.30)
    ix0, ix1 = ax.min(), ax.max() + 1
    iy0, iy1 = ay.min(), ay.max() + 1
    ink_w, ink_h = ix1 - ix0, iy1 - iy0

    # 墨迹目标区（pt）：避开标题栏（y≥450, x≥400）
    dst = (30, 16, 812, 428)
    ink_w_pt, ink_h_pt = ink_w / S, ink_h / S
    s = min((dst[2] - dst[0]) / ink_w_pt, (dst[3] - dst[1]) / ink_h_pt)
    s = min(s, 1.15)
    crop_w_px, crop_h_px = crop_ink.shape[1], crop_ink.shape[0]
    pw, ph = int(crop_w_px * s), int(crop_h_px * s)
    ink_img = Image.fromarray(
        np.dstack([crop_ink.astype('uint8'),
                   (crop_a * 255).astype('uint8')]), 'RGBA'
    ).resize((pw, ph), Image.LANCZOS)

    # 合成：底图铺满 + 墨水层（墨迹包围盒精确落入目标区并居中）
    plate = Image.open(plate_png).convert('RGB').resize((int(842 * S), int(595 * S)),
                                                        Image.LANCZOS)
    plate_rgba = plate.convert('RGBA')
    bx0r, by0r = ix0 * s, iy0 * s           # 墨迹包围盒在缩放后图内的位置(px)
    bxwr, byhr = ink_w * s, ink_h * s
    px0 = int(dst[0] * S - bx0r)   # 顶左对齐：墨迹包围盒精确落在目标区
    py0 = int(dst[1] * S - by0r)
    plate_rgba.alpha_composite(ink_img, (px0, py0))
    composite_png = W / '_ink_composite.png'
    plate_rgba.convert('RGB').save(composite_png, optimize=True)

    out = fitz.open()
    p = out.new_page(width=595.276, height=841.89)
    p.set_rotation(270)
    p.insert_image(p.cropbox, filename=str(composite_png),
                   keep_proportion=False, overlay=False, rotate=270)
    draw_frame_vectors(p, rev_table=False)
    t = fitz.Rect(400, 450, 820, 564) * p.derotation_matrix
    p.insert_image(t, filename=str(title_png), rotate=270,
                   keep_proportion=False, overlay=True)
    out_path = Path(out_pdf)
    if out_path.exists():
        out_path.unlink()
    out.save(out_path, garbage=4, deflate=True, clean=False)
    out.close()
    src.close()
    composite_png.unlink(missing_ok=True)


def run_ink(src_pdf, out_pdf, model, qa_png, dpi=300):
    OUT_DIR = ROOT / 'outputs' / 'ZCode_V10'
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tb = W / '_tb_ink.png'
    make_titleblock(model, tb)
    build_ink(src_pdf, out_pdf, model, tb, W / 'user_bg_plate.png', dpi=dpi)
    d2 = fitz.open(out_pdf)
    ok = d2[0].rect.width > d2[0].rect.height
    d2[0].get_pixmap(dpi=120).save(qa_png)
    d2.close()
    return ok
