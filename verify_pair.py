"""Deterministic content-coverage verifier: every source ink component must
appear in the branded output at the expected (scaled) position.
usage: verify_pair.py src.pdf out.pdf clearance out.json"""
import sys, json
import numpy as np
import fitz
from PIL import Image
from scipy import ndimage
sys.path.insert(0, '.')
from build_ink import detect_old_frame, find_cover_regions

def source_mask(src_pdf, dpi=150):
    src = fitz.open(src_pdf); page = src[0]
    if page.mediabox.height > page.mediabox.width and page.rotation == 0:
        page.set_rotation(270)
    M = page.rotation_matrix; disp = page.rect
    pix = page.get_pixmap(dpi=dpi)
    a = np.asarray(Image.frombytes('RGB', (pix.width, pix.height), pix.samples)).astype(float)
    H, W = a.shape[:2]; S = dpi / 72.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = 0.299*r + 0.587*g + 0.114*b
    mn = np.minimum(np.minimum(r, g), b)
    alpha = np.clip((255.0 - mn) / 255.0, 0, 1)
    alpha = np.where(lum > 234, 0, alpha)
    frame = detect_old_frame(lum < 225, S)
    if frame:
        ft, fb, fl, fr = frame
        line = int(2 * S)
        zero = np.ones((H, W), dtype=bool)
        zero[ft+line:fb-line+1, fl+line:fr-line+1] = False
    else:
        zero = np.zeros((H, W), dtype=bool)
    for (cx0, cy0, cx1, cy1) in find_cover_regions(page, M, disp):
        zero[int(cy0*S):int(cy1*S), int(cx0*S):int(cx1*S)] = True
    pre = alpha.copy()
    alpha[zero] = 0
    alpha[alpha < 0.30] = 0
    src.close()
    return alpha, S, zero, pre

def out_mask(out_pdf, dpi=150):
    d = fitz.open(out_pdf); p = d[0]
    pix = p.get_pixmap(dpi=dpi)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).astype(float)
    d.close()
    # 色度判据：品牌蓝 b>>r、金 r>>b；冰蓝底图/白底色差小，不误判
    r, b = a[..., 0], a[..., 2]
    return (b - r > 60) | (r - b > 60), dpi / 72.0

def main(src_pdf, out_pdf, clearance, out_json, anchor='origin'):
    smask, S, zero, pre = source_mask(src_pdf)
    omask, OS = out_mask(out_pdf)
    OH, OW = omask.shape
    s = clearance if clearance else 1.0
    off = 29.0 * (1 - s) * S if anchor == "frame" else 0.0
    lab, n = ndimage.label(ndimage.binary_dilation(smask > 0.3, np.ones((3,3)), iterations=2))
    comps = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        m = (lab[sl] == i) & (smask[sl] > 0.3)
        mass = int(m.sum())
        h, w = m.shape
        if mass < 40 or h < 10 or w < 10:
            continue
        comps.append((sl, m, mass))
    missing, checked, removed_n = [], 0, 0
    odil = ndimage.binary_dilation(omask, np.ones((3,3)), iterations=2)
    for sl, m, mass in comps:
        zfrac = float(zero[sl][m].sum()) / max(mass, 1)
        if zfrac > 0.5:
            removed_n += 1
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        # expected placement in output px (origin-anchored uniform scale)
        ex0, ey0 = int((x0 * s) + off), int((y0 * s) + off)
        ex1, ey1 = int((x1 * s) + off), int((y1 * s) + off)
        if ex1 <= ex0 or ey1 <= ey0 or ex1 > OW or ey1 > OH:
            ex0, ey0 = min(ex0, OW-1), min(ey0, OH-1)
            ex1, ey1 = min(max(ex1, ex0+2), OW), min(max(ey1, ey0+2), OH)
        sub = Image.fromarray((m * 255).astype('uint8')).resize(
            (max(ex1 - ex0, 1), max(ey1 - ey0, 1)), Image.LANCZOS)
        sub = np.asarray(sub) > 100
        win = np.zeros(sub.shape, dtype=bool)
        sy0, sx0 = max(ey0, 0), max(ex0, 0)
        win[:min(sub.shape[0], OH - sy0), :min(sub.shape[1], OW - sx0)] = \
            odil[sy0:sy0 + min(sub.shape[0], OH - sy0),
                 sx0:sx0 + min(sub.shape[1], OW - sx0)]
        cov = float((sub & win).sum()) / max(int(sub.sum()), 1)
        checked += 1
        if cov < 0.55:
            missing.append({'bbox_pt': [round(x0/S,1), round(y0/S,1), round(x1/S,1), round(y1/S,1)],
                            'mass': mass, 'coverage': round(cov, 2)})
    missing.sort(key=lambda d: -d['mass'])
    res = {'src': src_pdf, 'out': out_pdf, 'clearance': clearance,
           'components': checked, 'removed_expected': removed_n,
           'missing': missing, 'ok': len(missing) == 0}
    json.dump(res, open(out_json, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({'ok': res['ok'], 'components': checked, 'missing': len(missing)}))

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4],
         sys.argv[5] if len(sys.argv) > 5 else 'origin')
