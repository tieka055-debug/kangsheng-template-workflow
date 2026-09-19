"""Generic component relayout for sheets whose 1:1 content collides with the
brand title block. Groups = dilated connected components merged by proximity;
only groups that don't fit their source slot are moved (nearest-fit), so the
original composition is preserved as much as possible. All groups stay 1:1."""
import numpy as np
from scipy import ndimage

S = None  # set by caller (px per pt)

def plan_placements(alpha, S_px, min_mass=60):
    """returns list of (x0,y0,x1,y1,layer_rgba_uint8) in OUTPUT pt (A4 canvas)."""
    global S
    S = S_px
    H, W = alpha.shape
    A4W, A4H = int(841.89 * S), int(595.276 * S)

    # --- groups ---
    dil = ndimage.binary_dilation(alpha > 0.3, np.ones((3, 3)), iterations=2)
    lab, n = ndimage.label(dil)
    groups = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        m = (lab[sl] == i) & (alpha[sl] > 0.3)
        mass = int(m.sum())
        h, w = m.shape
        if mass < min_mass or h < 8 or w < 8:
            continue
        groups.append({'x0': sl[1].start, 'y0': sl[0].start,
                       'x1': sl[1].stop, 'y1': sl[0].stop,
                       'mass': mass, 'mask': m})
    # merge boxes with gap < 12pt (semantic grouping)
    def gap(a, b):
        dx = max(a['x0'] - b['x1'], b['x0'] - a['x1'], 0)
        dy = max(a['y0'] - b['y1'], b['y0'] - a['y1'], 0)
        return max(dx, dy) / S
    changed = True
    while changed and len(groups) > 1:
        changed = False
        groups.sort(key=lambda g: (g['y0'], g['x0']))
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                a, b = groups[i], groups[j]
                if gap(a, b) < 12:
                    a2 = {'x0': min(a['x0'], b['x0']), 'y0': min(a['y0'], b['y0']),
                          'x1': max(a['x1'], b['x1']), 'y1': max(a['y1'], b['y1']),
                          'mass': a['mass'] + b['mass'],
                          'mask': None}
                    groups[i] = a2
                    groups.pop(j)
                    changed = True
                    break
            if changed:
                break
    # re-extract masks per merged box (clean, no cross-contamination)
        for g in groups:
            if g['x0'] <= cx <= g['x1'] and g['y0'] <= cy <= g['y1']:
                ysl = sl[0].start - g['y0']; ysl1 = sl[0].stop - g['y0']
                xsl = sl[1].start - g['x0']; xsl1 = sl[1].stop - g['x0']
                g['layer'][ysl:ysl1, xsl:xsl1, 3] = (m * 255).astype('uint8')
                break
    groups = [g for g in groups if g['layer'][..., 3].sum() > 0]

    # --- pack: keep source slot when free, else nearest-fit ---
    occ = np.zeros((A4H, A4W), dtype=bool)
    def block(x0, y0, x1, y1):
        occ[int(y0 * S):int(y1 * S) + 1, int(x0 * S):int(x1 * S) + 1] = True
    # blocked: title block, REV zone, frame margins
    block(398, 448, 822, 566)
    block(558, 24, 824, 70)
    block(0, 0, 842, 40); block(0, 558, 842, 597)
    block(0, 0, 38, 597); block(816, 0, 842, 597)

    def fits(x0, y0, x1, y1):
        if x0 < 40 or y0 < 40 or x1 > 814 or y1 > 556:
            return False
        if x1 > 396 and y1 > 446:
            return False
        return not occ[int(y0 * S):int(y1 * S) + 1, int(x0 * S):int(x1 * S) + 1].any()

    placements = []
    groups.sort(key=lambda g: (round(g['y0'] / (H / 4)), g['x0']))
    for g in groups:
        wpt, hpt = (g['x1'] - g['x0']) / S, (g['y1'] - g['y0']) / S
        sx, sy = g['x0'] / S, g['y0'] / S   # source position in pt
        pos = None
        # 1) source slot
        if fits(sx, sy, sx + wpt, sy + hpt):
            pos = (sx, sy)
        else:
            # 2) nearest-fit spiral
            best = None
            for r in range(0, 620, 6):
                cands = []
                for dy in range(-r, r + 6, 6):
                    for dx in range(-r, r + 6, 6):
                        if max(abs(dx), abs(dy)) != r:
                            continue
                        cx, cy = sx + dx, sy + dy
                        cx = min(max(cx, 40), 814 - wpt)
                        cy = min(max(cy, 40), 556 - hpt)
                        if fits(cx, cy, cx + wpt, cy + hpt):
                            cands.append((cx - sx) ** 2 + (cy - sy) ** 2 and
                                         ((cx - sx) ** 2 + (cy - sy) ** 2, cx, cy))
                if cands:
                    best = min(cands)[1:]
                    break
            pos = best
        if pos is None:
            continue
        x0, y0 = pos
        block(x0, y0, x0 + wpt, y0 + hpt)
        px = int(x0 * S)
        py = int(y0 * S)
        placements.append((px, py, g['layer']))
    return placements
