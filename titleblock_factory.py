"""Frozen title block factory.

The approved BC-60 sheet's title block (work/single_sample_titleblock.png,
byte-identical to the image embedded in the user-approved master PDF) is the
permanent template: frame, cells, labels, logo, tolerance block are frozen.

For a new product the ONLY operation is replacing the model value text:
wipe the old value (y283-309 band, clear of the MODEL: label and borders),
draw the new value at the master's size/colour, centred in the cell.
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
MASTER_PNG = ROOT / 'single_sample_titleblock.png'   # == approved master TB
BLUE = (4, 64, 168)                    # sampled master value ink #0440A8
CELL = (264, 231, 717, 340)            # model value cell (PNG px)
OLD_BBOX = (359, 279, 622, 313)        # old value ink bbox, inflated ~4px
TEXT_CY = 296                          # value optical centre line (PNG px)
TARGET_H = 26                          # master value ink height (PNG px)

def _cjk(size_px):
    return ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc',
                              round(size_px), index=2)

def _ink_box(text, size):
    f = _cjk(size)
    tmp = Image.new('L', (1200, 200), 0)
    ImageDraw.Draw(tmp).text((20, 50), text, font=f, fill=255)
    bb = tmp.getbbox()
    return bb[2] - bb[0], bb[3] - bb[1], f

def make_titleblock(model_text, out_path):
    im = Image.open(MASTER_PNG).convert('RGBA')
    d = ImageDraw.Draw(im)
    d.rectangle(OLD_BBOX, fill=(0, 0, 0, 0))   # cell interior is pure transparent
    # largest size matching the master's 26px ink height, fitting the cell
    size = TARGET_H / 0.86
    for _ in range(20):
        w_in, h_in, f = _ink_box(model_text, size)
        if h_in <= TARGET_H and w_in <= (CELL[2] - CELL[0]) - 24:
            break
        size -= 0.5
    w_in, h_in, f = _ink_box(model_text, size)
    tmp = Image.new('L', (1200, 200), 0)
    ImageDraw.Draw(tmp).text((20, 50), model_text, font=f, fill=255)
    tmask = tmp.crop((20, 50, 20 + w_in, 50 + h_in))
    txt = Image.new('RGBA', (w_in, h_in), (0, 0, 0, 0))
    solid = Image.new('RGBA', (w_in, h_in), BLUE + (255,))
    txt.paste(solid, (0, 0), tmask)
    cx = (CELL[0] + CELL[2]) / 2
    im.alpha_composite(txt, (round(cx - w_in / 2), round(TEXT_CY - h_in / 2)))
    im.save(out_path)
    return out_path

if __name__ == '__main__':
    import sys
    model = sys.argv[1] if len(sys.argv) > 1 else 'BC-21系列塑高2.25mm'
    out = sys.argv[2] if len(sys.argv) > 2 else str(ROOT / 'titleblock_product.png')
    make_titleblock(model, out)
    print('written', out)
