"""Ink-compositing builder v4 — the universal quality pipeline.

整页 300 DPI 渲染 → 逐像素墨水分离：
  · 灰阶墨迹（黑线/黑字）→ 品牌蓝墨水, alpha = 墨量
  · 彩色图层（红/绿/品红等源图自带色）→ 原色保留, alpha = 墨量
  · 白色/浅色 → 全透明, 冰蓝底图透出
旧图框/旧标题栏/Autodesk 水印区域 alpha 强制归零（底图透出，无缝覆盖）。
布局：整页 1:1 原位合成（不缩放、不重排），内容保持在原稿中的位置。
图框、分区刻度（矢量）与冻结标题栏叠加；右上角 REV 表仅在内容不与之
碰撞时绘制（布局紧张 → 自动去格子）。
"""
from pathlib import Path
import sys
import os
import fitz
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

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


def detect_old_frame(gray, S):
    """检测源页旧图框（显示坐标 px）：源模板为双重图框，分区数字/刻度
    （以及旧标题栏伸进框带的部分）夹在内外框之间，故取每侧最靠内的
    长横/竖线为内容边界。内框线细且浅，须用 lum<225 灰度掩码检测
    （墨水 alpha 掩码会漏检）。检测不到则返回 None。"""
    H, Wd = gray.shape
    hys = np.where(gray.sum(axis=1) / Wd > 0.5)[0]
    vxs = np.where(gray.sum(axis=0) / H > 0.5)[0]
    if len(hys) < 2 or len(vxs) < 2:
        return None
    # 图框线必然贴近页缘；排除页中部内容长线（如标题栏横线）
    edge_y, edge_x = int(0.08 * H), int(0.08 * Wd)
    hys_top = hys[hys < edge_y]
    hys_bot = hys[hys > H - edge_y]
    vxs_l = vxs[vxs < edge_x]
    vxs_r = vxs[vxs > Wd - edge_x]
    if any(len(v) == 0 for v in (hys_top, hys_bot, vxs_l, vxs_r)):
        return None
    top = int(hys_top.max())       # 每侧取最靠内的线（双重框的外框丢弃）
    bottom = int(hys_bot.min())
    left = int(vxs_l.max())
    right = int(vxs_r.min())
    if bottom - top < 0.75 * H or right - left < 0.75 * Wd:
        return None
    return top, bottom, left, right


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
                                 'PROJECTION', '未注公差', 'A4', '第1页', '共1页', '页第1页',
                                 '有限公司', '电子科技', '精密', 'MATERIAL', 'PART NO',
                                 'PART NAME', 'DRAWING NO', 'HOUSING', 'FINISHING',
                                 'APPROVAL', 'REVISION', 'DESCRIPTION', 'SUPPLIER', 'PART', 'CONNECTOR')):
            tb.append(r)
        if 'Autodesk' in tt or '教育版' in tt:
            wm.append(r)
    covers = []
    if tb:
        tb = [r for r in tb if r.y0 > disp.height * 0.58]
        if tb:
            x0 = max(min(r.x0 for r in tb) - 12, 0)
            y0 = max(min(r.y0 for r in tb) - 12, 0)
            x1 = min(max(r.x1 for r in tb) + 12, disp.width)
            y1 = min(max(r.y1 for r in tb) + 12, disp.height)
            covers.append((x0, y0, x1, y1))
    for r in wm:
        covers.append((max(r.x0 - 6, 0), max(r.y0 - 6, 0),
                       min(r.x1 + 6, disp.width), min(r.y1 + 6, disp.height)))
    return covers


def _pick_rotation(page):
    """四个旋转角打分选正立方向：文字以横向为主 + 内容外廓呈横向。"""
    base = page.rotation
    # 旧逻辑优先角：竖版介质 → 270，横版 → 保持；0/180 打平时选它
    old_pref = (base + 270) % 360 if page.mediabox.height > page.mediabox.width else base
    best = {}
    for extra in (0, 90, 180, 270):
        page.set_rotation((base + extra) % 360)
        try:
            pix = page.get_pixmap(dpi=36)
            a = np.asarray(Image.frombytes('RGB', (pix.width, pix.height),
                                           pix.samples)).astype(float)
            lum = 0.299*a[..., 0] + 0.587*a[..., 1] + 0.114*a[..., 2]
            inkf = lum < 200
            xs = np.where(inkf.sum(axis=0) > 0)[0]
            ys = np.where(inkf.sum(axis=1) > 0)[0]
            if len(xs) and len(ys):
                ar = (xs[-1] - xs[0]) / max(ys[-1] - ys[0], 1)
                best[(base + extra) % 360] = 6 if ar > 1.15 else (-6 if ar < 0.87 else 0)
            else:
                best[(base + extra) % 360] = 0
        except Exception:
            best[(base + extra) % 360] = 0
    top = max(best.values())
    cands = [r for r, sc in best.items() if sc == top]
    best_rot = old_pref if old_pref in cands else cands[0]
    forced = os.environ.get('BLD_INK_ROT')
    if forced:
        best_rot = (base + int(forced)) % 360
    page.set_rotation(best_rot)
    return best_rot


def build_ink(src_path, out_pdf, model, title_png, plate_png, dpi=300):
    src = fitz.open(src_path)
    page = src[0]
    rot = _pick_rotation(page)
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

    # 墨量：无色白→0，深→1；彩色笔画按最小通道保持不透明。
    # 白色判定必须同时看饱和度：淡黄/淡红等浅色彩线（CAD 转换件）
    # 亮度高于 234 但饱和度高，是图形内容，不能当背景清掉。
    alpha = np.clip((255.0 - mn) / 255.0, 0, 1)
    alpha = np.where((lum > 234) & (sat < 18), 0, alpha)
    alpha = np.where(lum > 250, 0, alpha)

    # 墨色：双色调（认可版标准）——灰阶、绿、蓝(含CAD蓝底稿) → 品牌蓝；
    # 红/品红/黄/青 → 金色。不再保留源图原色。
    colored = sat > 45
    greenish = colored & (g > 0.6 * mx) & (r < 0.6 * mx) & (b < 0.6 * mx)
    bluish = colored & (b > 0.6 * mx) & (r < 0.6 * mx) & (g < 0.6 * mx)
    gold_mask = colored & ~greenish & ~bluish
    ink = np.zeros_like(full)
    ink[..., :] = BLUE[None, None, :]
    for ch in range(3):
        ink[..., ch][gold_mask] = GOLD[ch]

    # 透明化：旧图框/分区（内框以外全部，含框线、分区数字/刻度、
    # 旧标题栏伸进框带的部分）+ 旧标题栏 + 水印
    frame = detect_old_frame(lum < 225, S)
    forced_frame = os.environ.get('BLD_INK_FRAME')
    if forced_frame:
        vals = [float(v) for v in forced_frame.split(',')]
        frame = tuple(int(v * S) for v in vals)
    if frame:
        ft, fb, fl, fr = frame
        line = int(2 * S)   # 框线半宽余量
        zero = np.ones((H, Wd), dtype=bool)
        zero[ft + line:fb - line + 1, fl + line:fr - line + 1] = False
    else:
        zero = np.zeros((H, Wd), dtype=bool)
        zero[:int(31 * S), :] = True
        zero[int(552 * S):, :] = True
        zero[:, :int(31 * S)] = True
        zero[:, int(816 * S):] = True
    for (cx0, cy0, cx1, cy1) in find_cover_regions(page, M, disp):
        zero[int(cy0 * S):int(cy1 * S), int(cx0 * S):int(cx1 * S)] = True
    # 顶部旧修订栏（英文模板的 SYMBOL/REVISION/APPROVAL 行）
    for x0, y0, x1, y1, t, *_ in page.get_text('words'):
        r = fitz.Rect((x0, y0, x1, y1)) * M
        if r.y1 < disp.height * 0.12 and any(
                k in t for k in ('REVISION', 'APPROVAL', 'SYMBOL')):
            zero[max(int(r.y0 * S) - 4, 0):int(r.y1 * S) + 4,
                 max(int(r.x0 * S) - 4, 0):int(r.x1 * S) + 4] = True
    alpha[zero] = 0
    # 框线残迹（虚线内框/分区数字）只集中在图框内缘 28pt 带：强阈值压掉；
    # 页面中腹的浅灰内容线条（CAD 灰色图层, rgb~204）不能误杀——增显 1.8 倍
    if frame:
        ft, fb, fl, fr = frame
        bd = int(28 * S)
        strong = np.zeros((H, Wd), dtype=bool)
        strong[ft:ft + bd, :] = True; strong[fb - bd:fb + 1, :] = True
        strong[:, fl:fl + bd] = True; strong[:, fr - bd:fr + 1] = True
    else:
        bd = int(56 * S)
        strong = np.zeros((H, Wd), dtype=bool)
        strong[:bd, :] = True; strong[H - bd:, :] = True
        strong[:, :bd] = True; strong[:, Wd - bd:] = True
    alpha[strong & (alpha < 0.30)] = 0
    grayish = sat < 18
    alpha = np.where(grayish, np.clip(alpha * 4.25, 0, 1), alpha)
    # 低对比源：极浅像素(alpha 0.04-0.45)整体三倍增显
    weak = (alpha > 0.04) & (alpha < 0.45)
    alpha = np.where(weak, np.clip(alpha * 3.0, 0, 1), alpha)
    alpha[alpha < 0.10] = 0
    # 极淡源文件：笔画二值化加固 + 1px 加粗（BLD_INK_SOLID/BLD_INK_THICKEN 控制）
    if os.environ.get('BLD_INK_SOLID') == '1':
        alpha = np.where(alpha > 0.28, 0.97, alpha)
    if os.environ.get('BLD_INK_THICKEN') == '1':
        thick = ndimage.binary_dilation(alpha > 0.30, np.ones((3, 3)), iterations=1)
        alpha = np.where(thick, np.maximum(alpha, 0.85), alpha)
    # 供应商绿色水印（底部 16% 带内的绿字，如“广东诺德电子科技有限公司”）
    gband = int(H * 0.84)
    alpha[gband:, :][greenish[gband:, :]] = 0
    # 自适应对比度：按内容墨量 p90 归一到 0.92（浅灰 CAD 扫描件自动增显）
    vals = alpha[alpha > 0.12]
    target = float(os.environ.get('BLD_INK_TARGET', '0.92'))
    maxgain = float(os.environ.get('BLD_INK_MAXGAIN', '8'))
    if vals.size > 500:
        p90 = float(np.percentile(vals, 90))
        if 0.03 < p90 < target:
            gain = min(target / p90, maxgain)
            alpha = np.clip(alpha * gain, 0, 1)
            print(f'  auto-gain {gain:.2f} (p90 {p90:.2f})')

    # 大画幅源图（CAD 按 1:1 导出，页面远大于 A4）：
    # 裁出内容包围盒，等比缩到 (750×400)pt 以内，在图框内水平居中放置
    oversized = disp.width > 1200 or disp.height > 900
    A4W, A4H = int(841.89 * S), int(595.276 * S)
    if oversized:
        for (cx0, cy0, cx1, cy1) in find_cover_regions(page, M, disp):
            alpha[int(cy0 * S):int(cy1 * S), int(cx0 * S):int(cx1 * S)] = 0
        ys, xs = np.where(alpha > 0.3)
        bx0 = max(int(xs.min() - 20 * S), 0)
        bx1 = min(int(xs.max() + 20 * S), Wd)
        by0 = max(int(ys.min() - 20 * S), 0)
        by1 = min(int(ys.max() + 20 * S), H)
        cw, chh = bx1 - bx0, by1 - by0
        s = min((750 * S) / cw, (400 * S) / chh, 1.0)
        nw, nh = int(cw * s), int(chh * s)
        print(f'  oversized page {disp.width:.0f}x{disp.height:.0f}pt: fit scale {s:.3f}')
        layer = Image.fromarray(
            np.dstack([ink[by0:by1, bx0:bx1].astype('uint8'),
                       (alpha[by0:by1, bx0:bx1] * 255).astype('uint8')]), 'RGBA'
        ).resize((nw, nh), Image.LANCZOS)
        px = (A4W - nw) // 2
        py = int(45 * S) + max(int((400 * S) - nh) // 2, 0)
        rev_table = True
        placed_alpha = np.zeros((A4H, A4W), dtype=float)
        placed_alpha[py:py + nh, px:px + nw] = np.asarray(layer)[..., 3] / 255.0
    else:
        layer = None
        px = py = 0
        placed_alpha = alpha

    # REV 表碰撞检测：右上角格子区(563.6, 28.8)-(820, 66.5)内有墨迹
    # → 布局紧张，去掉格子；干净 → 照常保留
    rx0, ry0, rx1, ry1 = 563.6, 28.8, 820.0, 66.5
    reg = placed_alpha[int(ry0 * S):int(ry1 * S), int(rx0 * S):int(rx1 * S)]
    rev_table = bool((reg > 0.25).sum() < 150)

    # 避让微缩（仅 A4 正常路径）：整页等比、锚定图框内角(29,29)，内容任何
    # 情况下都不会戳出图框/标题栏：
    #   1) 标题栏区(400,450)-(820,564) → 该 x 带内容底须 ≤448pt
    #   2) 图框底/右 → 内容须收进 562/818pt
    s = 1.0
    if oversized:
        ink_img = layer
        clearance = None
        offx = offy = 0
    else:
        band = alpha[:, int(400 * S):int(820 * S)] > 0.25
        bys = np.where(band.any(axis=1))[0]
        if len(bys) and bys.max() >= int(448 * S):
            s = min(s, (448 * S - int(29 * S)) / (bys.max() + 1 - int(29 * S)))
        ays = np.where((alpha > 0.25).any(axis=1))[0]
        if len(ays) and ays.max() >= int(562 * S):
            s = min(s, (562 * S - int(29 * S)) / (ays.max() + 1 - int(29 * S)))
        axs = np.where((alpha > 0.25).any(axis=0))[0]
        if len(axs) and axs.max() >= int(818 * S):
            s = min(s, (818 * S - int(29 * S)) / (axs.max() + 1 - int(29 * S)))
        s = max(min(1.0, s), 0.05)
        clearance = s
        ink_img = Image.fromarray(
            np.dstack([ink.astype('uint8'),
                       (alpha * 255).astype('uint8')]), 'RGBA')
        offx = int(29 * (1 - s) * S)
        offy = int(29 * (1 - s) * S)
        if s < 0.995:
            ink_img = ink_img.resize((int(Wd * s), int(H * s)), Image.LANCZOS)
            print(f'  clearance: uniform scale {s:.3f} (frame-anchored)')

    # 合成：底图铺满 + 墨水层（A4 路径锚定图框内角；大画幅居中放置）
    plate = Image.open(plate_png).convert('RGB')
    canvas_w, canvas_h = (A4W, A4H) if oversized else (Wd, H)
    plate_rgba = plate.resize((canvas_w, canvas_h), Image.LANCZOS).convert('RGBA')
    plate_rgba.alpha_composite(ink_img, (px, py) if oversized else (offx, offy))
    composite_png = W / '_ink_composite.png'
    plate_rgba.convert('RGB').save(composite_png, optimize=True)

    out = fitz.open()
    p = out.new_page(width=595.276, height=841.89)
    p.set_rotation(270)
    p.insert_image(p.cropbox, filename=str(composite_png),
                   keep_proportion=False, overlay=False, rotate=270)
    draw_frame_vectors(p, rev_table=rev_table)
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
    return rev_table


def run_ink(src_pdf, out_pdf, model, qa_png, dpi=300):
    OUT_DIR = ROOT / 'outputs' / 'ZCode_V10'
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tb = W / '_tb_ink.png'
    make_titleblock(model, tb)
    rev = build_ink(src_pdf, out_pdf, model, tb, W / 'user_bg_plate.png', dpi=dpi)
    print(f'  REV table: {"kept" if rev else "removed (tight layout)"}')
    d2 = fitz.open(out_pdf)
    ok = d2[0].rect.width > d2[0].rect.height
    d2[0].get_pixmap(dpi=120).save(qa_png)
    d2.close()
    return ok
