"""Raster builder v2 — quality-first.

整页内容以 300 DPI 光栅一次性放置（原始布局/字体 100% 保留），
源图框、旧标题栏、Autodesk 水印用背景底图同位置像素无缝覆盖，
再叠加康生图框、分区刻度、REV 表与冻结标题栏。
"""
from pathlib import Path
import json, re, sys
import fitz
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / 'work'
sys.path.insert(0, str(WORK))
from titleblock_factory import make_titleblock

SRC_INSET = 24          # 源页面四周内缩（去旧图框/分区刻度）
WIN = (30, 36, 812, 559)  # 我们图框内的内容窗口 (display pt)

def display_pix(page, dpi=300):
    pix = page.get_pixmap(dpi=dpi)
    return Image.frombytes('RGB', (pix.width, pix.height), pix.samples)

def find_anchors(page, M):
    tb_words, wm_words = [], []
    for x0, y0, x1, y1, t, *_ in page.get_text('words'):
        r = fitz.Rect((x0, y0, x1, y1)) * M
        tt = t.strip()
        if not tt: continue
        if any(k in tt for k in ('质源', '图号', '品名', '批准', '审核', '绘制',
                                 '设计DES', '版本REV', '比例SCALE', '单位UNIT',
                                 '页码SHEET', '电池连接器', '电池连接座', '电源连接器',
                                 'TOOLERANCE', 'PROJECTION')):
            tb_words.append(r)
        if 'Autodesk' in tt or '教育版' in tt:
            wm_words.append(r)
    return tb_words, wm_words

def union_rect(rects, pad=8, clip=None):
    x0 = min(r.x0 for r in rects) - pad
    y0 = min(r.y0 for r in rects) - pad
    x1 = max(r.x1 for r in rects) + pad
    y1 = max(r.y1 for r in rects) + pad
    if clip is not None:
        x0 = max(x0, clip[0]); y0 = max(y0, clip[1])
        x1 = min(x1, clip[2]); y1 = min(y1, clip[3])
    return x0, y0, x1, y1

def build_raster(src_path, out_pdf, model, title_png, plate_png, dpi=300):
    src = fitz.open(src_path); page = src[0]
    if page.mediabox.height > page.mediabox.width and page.rotation == 0:
        page.set_rotation(270)
    M = page.rotation_matrix
    disp = page.rect                      # 842x595 display

    # --- 1. 300 DPI 渲染整页（横版显示方向） ---
    pix = page.get_pixmap(dpi=dpi)
    full = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    sc = full.width / disp.width          # px per pt

    # --- 2. 计算需要覆盖的区域（显示pt）：外边带 + 旧标题栏 + 水印 ---
    tb_words, wm_words = find_anchors(page, M)
    src_inset = SRC_INSET
    covers = []
    # 外边带：源图框+分区刻度+边缘水印（源页边缘 0..SRC_INSET 与对称边）
    covers.append((0, 0, disp.width, src_inset))
    covers.append((0, disp.height - src_inset, disp.width, disp.height))
    covers.append((0, 0, src_inset, disp.height))
    covers.append((disp.width - src_inset, 0, disp.width, disp.height))
    # 旧标题栏：右下象限内的相关文字并集成矩形
    tb = [r for r in tb_words if r.x0 > disp.width * 0.42 and r.y0 > disp.height * 0.7]
    if tb:
        covers.append(union_rect(tb, pad=10, clip=(0, 0, disp.width, disp.height)))
    # 水印
    for r in wm_words:
        covers.append((r.x0 - 6, r.y0 - 6, r.x1 + 6, r.y1 + 6))

    # --- 3. 覆盖区域映射到内容窗口坐标，并用底图同位置像素无缝覆盖 ---
    win_x0, win_y0, win_x1, win_y1 = WIN
    win_w, win_h = win_x1 - win_x0, win_y1 - win_y0
    # 内容裁剪：源页去掉四周边距
    crop_px = full.crop((int(src_inset * sc), int(src_inset * sc),
                         int((disp.width - src_inset) * sc),
                         int((disp.height - src_inset) * sc)))
    # 覆盖：在 crop 像素上贴底图对应区域
    plate = Image.open(plate_png).convert('RGB')
    plate_full = plate.resize((int(disp.width * dpi / 72), int(disp.height * dpi / 72)),
                              Image.LANCZOS)
    for (cx0, cy0, cx1, cy1) in covers:
        # 转为 crop 内坐标
        px0 = int((cx0 - src_inset) * sc); py0 = int((cy0 - src_inset) * sc)
        px1 = int((cx1 - src_inset) * sc); py1 = int((cy1 - src_inset) * sc)
        px0 = max(px0, 0); py0 = max(py0, 0)
        px1 = min(px1, crop_px.width); py1 = min(py1, crop_px.height)
        if px1 <= px0 or py1 <= py0: continue
        # 底图对应位置像素
        ox0 = int(win_x0 * dpi / 72 + (cx0 - src_inset) * dpi / 72)
        oy0 = int(win_y0 * dpi / 72 + (cy0 - src_inset) * dpi / 72)
        patch = plate_full.crop((ox0, oy0, ox0 + (px1 - px0), oy0 + (py1 - py0)))
        crop_px.paste(patch, (px0, py0))

    # --- 4. 内容窗口放置（PDF pt） ---
    out = fitz.open()
    p = out.new_page(width=595.276, height=841.89)
    p.set_rotation(270)
    # 背景底图铺满
    p.insert_image(p.cropbox, filename=str(plate_png),
                   keep_proportion=False, overlay=False)
    # 内容光栅放入窗口
    raster_png = WORK / '_raster_content.png'
    crop_px.save(raster_png, optimize=True)
    win_rect = fitz.Rect(*WIN) * p.derotation_matrix
    p.insert_image(win_rect, filename=str(raster_png),
                   keep_proportion=False, overlay=True, rotate=270)
    # 图框 + 分区 + REV 表（与模板一致，矢量重绘）
    draw_frame_vectors(p)
    # 冻结标题栏
    t = fitz.Rect(400, 450, 820, 564) * p.derotation_matrix
    p.insert_image(t, filename=str(title_png), rotate=270,
                   keep_proportion=False, overlay=True)
    if Path(out_pdf).exists(): Path(out_pdf).unlink()
    out.save(out_pdf, garbage=4, deflate=True, clean=True)
    out.close(); src.close()
    raster_png.unlink(missing_ok=True)

def draw_frame_vectors(p):
    """完整图框绘制：直线用 shape，文字用 helv"""
    blue = (6/255, 66/255, 168/255)
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
    for letter, y in zip('ABCDE', [(main_y[i]+main_y[i+1])/2 for i in range(5)]):
        txt(20, y, letter, 10); txt(826, y, letter, 10)
    # REV 表
    rx = [563.6, 591.3, 701.4, 734.6, 820.0]; ry = [28.8, 42.3, 54.1, 66.5]
    rect(rx[0], ry[0], rx[-1], ry[-1])
    for x in rx[1:-1]: line(x, ry[0], x, ry[-1])
    for y in ry[1:-1]: line(rx[0], y, rx[-1], y)
    txt(577.4, 39, 'REV.', 7.2); txt(646.3, 39, 'DESCRIPTION', 7.0)
    txt(718.0, 39, 'DRAW.', 7.0); txt(777.3, 39, 'DATE.', 7.0)
