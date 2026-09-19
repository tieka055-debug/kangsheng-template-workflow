"""Row 18 (BC-17系列母座): group-measured relayout in the approved style.
Groups are cut from the ink layer and re-composited 1:1 (translation only)."""
import sys
sys.path.insert(0, '.')
import numpy as np
import fitz
from PIL import Image
from scipy import ndimage
from build_ink import detect_old_frame, find_cover_regions, BLUE, GOLD, W
from titleblock_factory import make_titleblock
from pathlib import Path

SRC = '/Users/vill/Downloads/图纸/BC-17系列3-10P.pdf'
OUT = Path('../outputs/ZCode_V10/2D_BC-17系列3-10P.pdf')
DPI = 300
S = DPI / 72.0

# ---- ink separation (same rules as build_ink) ----
src = fitz.open(SRC); page = src[0]
if page.mediabox.height > page.mediabox.width and page.rotation == 0:
    page.set_rotation(270)
M = page.rotation_matrix; disp = page.rect
pix = page.get_pixmap(dpi=DPI)
a = np.asarray(Image.frombytes('RGB', (pix.width, pix.height), pix.samples)).astype(float)
H, Wd = a.shape[:2]
r, g, b = a[..., 0], a[..., 1], a[..., 2]
lum = 0.299*r + 0.587*g + 0.114*b
mx = np.maximum(np.maximum(r, g), b); mn = np.minimum(np.minimum(r, g), b)
sat = mx - mn
alpha = np.clip((255.0 - mn) / 255.0, 0, 1)
alpha = np.where(lum > 234, 0, alpha)
colored = sat > 45
greenish = colored & (g > 0.6*mx) & (r < 0.6*mx) & (b < 0.6*mx)
gold_mask = colored & ~greenish
ink = np.zeros_like(a)
ink[..., :] = BLUE[None, None, :]
for ch in range(3):
    ink[..., ch][gold_mask] = GOLD[ch]
frame = detect_old_frame(lum < 225, S)
ft, fb, fl, fr = frame
line = int(2 * S)
zero = np.ones((H, Wd), dtype=bool)
zero[ft+line:fb-line+1, fl+line:fr-line+1] = False
for (cx0, cy0, cx1, cy1) in find_cover_regions(page, M, disp):
    zero[int(cy0*S):int(cy1*S), int(cx0*S):int(cx1*S)] = True
alpha[zero] = 0
alpha[alpha < 0.30] = 0
src.close()

# ---- group cut (measured boxes, pt) with pad ----
PAD = 3
GROUPS = {  # name: (x0,y0,x1,y1) source pt (from connected components)
    'G1_front': (112.1, 58.1, 290.6, 232.3),
    'G2_side':  (302.2, 51.4, 465.6, 239.3),
    'G3_pin':   (517.2, 85.7, 666.2, 211.2),
    'G4_pcb':   (523.4, 215.0, 768.2, 413.0),
    'G5_view':  (78.0, 279.4, 281.5, 397.9),
    'G6_iso':   (327.4, 283.7, 475.9, 398.4),
    'G7_spec':  (31.2, 388.3, 262.8, 554.6),
    'G8_table': (271.4, 407.3, 475.4, 583.2),
    'G9_cap':   (544.8, 421.0, 724.1, 469.2),
}
# 按源 y 序切割，切完即清零该组区域：相邻框的重叠带不会把
# 邻组的像素偷进别的组（性能字块顶部曾因此带走小视图的尺寸线）
cuts = {}
for name, (x0, y0, x1, y1) in sorted(GROUPS.items(), key=lambda kv: kv[1][1]):
    px0, py0 = int((x0-PAD)*S), int((y0-PAD)*S)
    px1, py1 = int((x1+PAD)*S), int((y1+PAD)*S)
    cuts[name] = (
        Image.fromarray(np.dstack([ink[py0:py1, px0:px1].astype('uint8'),
                                   (alpha[py0:py1, px0:px1]*255).astype('uint8')])),
        (x1-x0+2*PAD, y1-y0+2*PAD),
    )
    alpha[py0:py1, px0:px1] = 0

# ---- packer: fixed anchors first, then first-fit; blocks: title & REV ----
placed = {}
occ = np.zeros((H, Wd), dtype=bool)
def block(x0, y0, x1, y1):
    occ[int(y0*S):int(y1*S)+1, int(x0*S):int(x1*S)+1] = True
block(396, 448, 822, 566)   # title block zone
block(560, 26, 822, 68)     # REV table zone
def fits(x0, y0, x1, y1):
    if x0 < 40 or y0 < 38 or x1 > 814 or y1 > 556:
        return False
    return not occ[int(y0*S):int(y1*S)+1, int(x0*S):int(x1*S)+1].any()

PLAN = [
    ('G1_front', (55, 45)),
    ('G2_side', (245, 40)),
    ('G6_iso', (418, 73)),
    ('G3_pin', (610, 76)),
    ('G7_spec', (576, 213)),
    ('G9_cap', (545, 390)),
    ('G8_table', (45, 238)),
    ('G4_pcb', (270, 238)),
    ('G5_view', (45, 428)),
]
for name, pref in PLAN:
    img, (w, h) = cuts[name]
    if not fits(pref[0], pref[1], pref[0] + w, pref[1] + h):
        sys.exit(f'slot blocked for {name}')
    pos = pref
    x0, y0 = pos
    placed[name] = (x0, y0, x0 + w, y0 + h)
    block(x0, y0, x0 + w, y0 + h)
    globals().setdefault('layers', []).append((img, (int(x0*S), int(y0*S))))
    print(f'{name}: ({x0:.0f},{y0:.0f})-({x0+w:.0f},{y0+h:.0f})')

# ---- composite ----
plate = Image.open(W / 'user_bg_plate.png').convert('RGB')
plate = plate.resize((Wd, H), Image.LANCZOS).convert('RGBA')
for img, (px, py) in layers:
    plate.alpha_composite(img, (px, py))
comp = W / '_ink_composite18.png'
plate.convert('RGB').save(comp, optimize=True)

out = fitz.open()
p = out.new_page(width=595.276, height=841.89)
p.set_rotation(270)
p.insert_image(p.cropbox, filename=str(comp), keep_proportion=False, overlay=False, rotate=270)
from build_ink import draw_frame_vectors
draw_frame_vectors(p, rev_table=True)
tb = W / '_tb_ink.png'
make_titleblock('BC-17系列母座', tb)
t = fitz.Rect(400, 450, 820, 564) * p.derotation_matrix
p.insert_image(t, filename=str(tb), rotate=270, keep_proportion=False, overlay=True)
if OUT.exists():
    OUT.unlink()
out.save(OUT, garbage=4, deflate=True, clean=False)
out.close()
d2 = fitz.open(OUT)
d2[0].get_pixmap(dpi=120).save('/tmp/qa_row18c.png')
d2.close()
comp.unlink()
print('saved', OUT)
