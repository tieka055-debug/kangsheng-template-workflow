"""One-off rebuild: A01M-A-5P-M5双脚..pdf (token JSMCbQZvqo0MyKxx9gXcJODrn9c).

根因：源 PDF 是 CAD 曲线导出（7257x4535pt），除供应商水印外没有任何文字层，
find_cover_regions 的关键词匹配永远打不中旧英文标题栏 / 旧 REV 表；
同时 detect_old_frame 的 8% 边缘窗口(580pt)把真内框线(x=590/6666pt)排除在
候选外，误取分区带分隔线(484.6/6772pt)当内框 —— 于是分区字母 A-E
(x 517-544 / 6713-6742pt)、真内框竖线、旧标题栏、旧 REV 表全部留在
保留区里，随内容包围盒一起裁进成品。

修复：按 build_ink.build_ink 的大画幅流程重建（不改动任何共享脚本），
追加本图专属的几何覆盖矩形（显示坐标 pt），把旧标题栏复合体、旧 REV 表、
两侧分区带整体 alpha 归零后再裁内容包围盒。

可复用函数均从 build_ink import；用法: python3 rebuild_a01m.py
"""
import sys
from pathlib import Path

import numpy as np
import fitz
from PIL import Image

W = Path(__file__).resolve().parent
sys.path.insert(0, str(W))
from build_ink import (BLUE, GOLD, _pick_rotation, detect_old_frame,
                       draw_frame_vectors, find_cover_regions)
from titleblock_factory import make_titleblock

TOKEN = 'JSMCbQZvqo0MyKxx9gXcJODrn9c'
SRC = f'/tmp/srcs/{TOKEN}.pdf'
NAME = 'A01M-A-5P-M5双脚..pdf'
MODEL = 'A01M-A-5P-M5双脚.'
OUT = W.parent / 'outputs' / 'ZCode_V10' / NAME
QA = Path('/tmp/agent_qa/E') / f'{TOKEN[:16]}.png'

SRC_DPI = 200          # 源图渲染精度（内容最终缩到 <=750x400pt，200dpi 足够）
OUT_DPI = 300          # A4 画布精度，与 build_ink 一致

# 几何覆盖矩形（显示坐标 pt，rotation=0）。逐条经 100dpi 渲染 + 矢量路径
# 聚类实测，均不与真实内容相交（最左内容 x≈1475，NOTE 文字 y>=751，
# PCB LAYOUT 文字 x<=2560）：
COVERS = [
    (3600, 3460, 6774, 4333),  # 旧英文标题栏+公差块+公司名框复合体（右下）
    (4950, 165, 6774, 515),    # 旧 REV 表 REV./DESCRIPTION/DRAW./DATE.（右上）
    (484, 200, 594, 4333),     # 左分区带：字母 A-E + 真内框竖线 x=590
    (6664, 200, 6774, 4333),   # 右分区带：字母 A-E + 真内框竖线 x=6666
]


def build():
    S = OUT_DPI / 72.0
    Ss = SRC_DPI / 72.0
    src = fitz.open(SRC)
    page = src[0]
    rot = _pick_rotation(page)
    M = page.rotation_matrix
    disp = page.rect
    print(f'  rotation {rot}, disp {disp.width:.0f}x{disp.height:.0f}pt')

    pix = page.get_pixmap(dpi=SRC_DPI)
    full = np.asarray(Image.frombytes('RGB', (pix.width, pix.height),
                                      pix.samples)).astype(np.float32)
    H, Wd = full.shape[:2]

    r, g, b = full[..., 0], full[..., 1], full[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = mx - mn

    # 墨量分离：与 build_ink 完全一致
    alpha = np.clip((255.0 - mn) / 255.0, 0, 1)
    alpha = np.where((lum > 234) & (sat < 18), 0, alpha)
    alpha = np.where(lum > 250, 0, alpha)
    colored = sat > 45
    greenish = colored & (g > 0.6 * mx) & (r < 0.6 * mx) & (b < 0.6 * mx)
    bluish = colored & (b > 0.6 * mx) & (r < 0.6 * mx) & (g < 0.6 * mx)
    gold_mask = colored & ~greenish & ~bluish
    ink = np.empty_like(full)
    ink[..., :] = BLUE[None, None, :]
    for ch in range(3):
        ink[..., ch][gold_mask] = GOLD[ch]
    del full, r, g, b, mx, mn, greenish, bluish, gold_mask

    # 透明化：检测到的旧图框以外全部 + 文字覆盖区 + 本图几何覆盖区
    frame = detect_old_frame(lum < 225, Ss)
    if frame:
        ft, fb, fl, fr = frame
        line = int(2 * Ss)
        z = np.ones((H, Wd), dtype=bool)
        z[ft + line:fb - line + 1, fl + line:fr - line + 1] = False
        print(f'  detected frame: ({fl/Ss:.0f},{ft/Ss:.0f})-({fr/Ss:.0f},{fb/Ss:.0f})pt'
              '  (分区带分隔线，真内框 590/6666 由 COVERS 兜底)')
    else:
        z = np.zeros((H, Wd), dtype=bool)
        z[:int(31 * Ss), :] = True
        z[int(552 * Ss):, :] = True
        z[:, :int(31 * Ss)] = True
        z[:, int(816 * Ss):] = True
    for (cx0, cy0, cx1, cy1) in list(find_cover_regions(page, M, disp)) + COVERS:
        z[int(cy0 * Ss):int(cy1 * Ss), int(cx0 * Ss):int(cx1 * Ss)] = True
    alpha[z] = 0
    del z

    # 图框内缘 28pt 带弱墨抑制（与 build_ink 一致）
    if frame:
        ft, fb, fl, fr = frame
        bd = int(28 * Ss)
        strong = np.zeros((H, Wd), dtype=bool)
        strong[ft:ft + bd, :] = True
        strong[fb - bd:fb + 1, :] = True
        strong[:, fl:fl + bd] = True
        strong[:, fr - bd:fr + 1] = True
        alpha[strong & (alpha < 0.30)] = 0
        del strong

    # 增显链：与 build_ink 完全一致
    grayish = sat < 18
    alpha = np.where(grayish, np.clip(alpha * 4.25, 0, 1), alpha)
    weak = (alpha > 0.04) & (alpha < 0.45)
    alpha = np.where(weak, np.clip(alpha * 3.0, 0, 1), alpha)
    alpha[alpha < 0.10] = 0
    vals = alpha[alpha > 0.12]
    if vals.size > 500:
        p90 = float(np.percentile(vals, 90))
        if 0.03 < p90 < 0.92:
            gain = min(0.92 / p90, 8.0)
            alpha = np.clip(alpha * gain, 0, 1)
            print(f'  auto-gain {gain:.2f} (p90 {p90:.2f})')

    # 大画幅：裁内容包围盒 → 等比缩放 → A4 图框内居中
    A4W, A4H = int(841.89 * S), int(595.276 * S)
    ys, xs = np.where(alpha > 0.3)
    bx0 = max(int(xs.min() - 20 * Ss), 0)
    bx1 = min(int(xs.max() + 20 * Ss), Wd)
    by0 = max(int(ys.min() - 20 * Ss), 0)
    by1 = min(int(ys.max() + 20 * Ss), H)
    cw, chh = bx1 - bx0, by1 - by0
    s = min((750 * S) / cw, (400 * S) / chh, 1.0)
    nw, nh = int(cw * s), int(chh * s)
    print(f'  content bbox pt: ({bx0/Ss:.0f},{by0/Ss:.0f})-({bx1/Ss:.0f},{by1/Ss:.0f}),'
          f' fit scale {s:.3f}')
    layer = Image.fromarray(
        np.dstack([ink[by0:by1, bx0:bx1].astype('uint8'),
                   (alpha[by0:by1, bx0:bx1] * 255).astype('uint8')]), 'RGBA'
    ).resize((nw, nh), Image.LANCZOS)
    px = (A4W - nw) // 2
    py = int(45 * S) + max(int((400 * S) - nh) // 2, 0)
    placed_alpha = np.zeros((A4H, A4W), dtype=float)
    placed_alpha[py:py + nh, px:px + nw] = np.asarray(layer)[..., 3] / 255.0
    del ink, alpha, ys, xs

    # 品牌右上角 REV 表碰撞检测（与 build_ink 一致）
    reg = placed_alpha[int(28.8 * S):int(66.5 * S),
                       int(563.6 * S):int(820.0 * S)]
    rev_table = bool((reg > 0.25).sum() < 150)
    print(f'  REV table: {"kept" if rev_table else "removed (tight layout)"}')
    del placed_alpha

    # 合成 + 出 PDF（与 build_ink 的输出结构一致）
    tb_png = W / '_tb_a01m.png'
    make_titleblock(MODEL, tb_png)
    plate = Image.open(W / 'user_bg_plate.png').convert('RGB')
    canvas = plate.resize((A4W, A4H), Image.LANCZOS).convert('RGBA')
    canvas.alpha_composite(layer, (px, py))
    comp = W / '_ink_composite_a01m.png'
    canvas.convert('RGB').save(comp, optimize=True)

    out = fitz.open()
    p = out.new_page(width=595.276, height=841.89)
    p.set_rotation(270)
    p.insert_image(p.cropbox, filename=str(comp),
                   keep_proportion=False, overlay=False, rotate=270)
    draw_frame_vectors(p, rev_table=rev_table)
    t = fitz.Rect(400, 450, 820, 564) * p.derotation_matrix
    p.insert_image(t, filename=str(tb_png), rotate=270,
                   keep_proportion=False, overlay=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    out.save(OUT, garbage=4, deflate=True, clean=False)
    out.close()
    src.close()
    comp.unlink(missing_ok=True)
    tb_png.unlink(missing_ok=True)

    d = fitz.open(OUT)
    QA.parent.mkdir(parents=True, exist_ok=True)
    d[0].get_pixmap(dpi=120).save(QA)
    d.close()
    print(f'  wrote {OUT}')
    print(f'  QA {QA}')


if __name__ == '__main__':
    build()
