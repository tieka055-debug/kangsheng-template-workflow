"""Split a 2-up (portrait sheet with two landscape drawings) source into two
wrapped single-drawing PDFs, ready for build_ink."""
import sys, json
import fitz, numpy as np
from PIL import Image

def split(src_pdf, out_a, out_b, dpi=200):
    src = fitz.open(src_pdf); page = src[0]
    from build_ink import _pick_rotation
    _pick_rotation(page)
    pix = page.get_pixmap(dpi=dpi)
    a = np.asarray(Image.frombytes('RGB', (pix.width, pix.height), pix.samples)).astype(float)
    H, W = a.shape[:2]
    lum = 0.299*a[...,0]+0.587*a[...,1]+0.114*a[...,2]
    ink = lum < 200
    col = ink.sum(axis=0) / H
    mid = W // 2
    # 在中部 ±12% 找墨量最小的缝
    lo, hi = int(W*0.38), int(W*0.62)
    gap = lo + int(np.argmin(col[lo:hi]))
    def wrap(x0, x1, path):
        sub = a[:, x0:x1].astype('uint8')
        Image.fromarray(sub).save(path, 'PDF', resolution=float(dpi))
    wrap(0, gap + int(H*0.01), out_a)
    wrap(gap - int(H*0.01), W, out_b)
    return gap / W

if __name__ == '__main__':
    r = split(sys.argv[1], sys.argv[2], sys.argv[3])
    print('split at', round(r, 3))
