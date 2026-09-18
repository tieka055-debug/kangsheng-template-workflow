"""Batch runner: process every series drawing in the Feishu PIM table.

Per drawing:  download -> detect orientation -> auto-measure content groups
-> assign to fixed slots (frozen template) -> build -> coverage scan (nothing
missing) -> upload back under the same attachment name.

State is kept in batch_state.json so the run is resumable.
"""
from pathlib import Path
import argparse, io, json, re, subprocess, sys
import numpy as np
import fitz
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / 'work'
OUT_DIR = ROOT / 'outputs' / 'ZCode_V10'
STATE = WORK / 'batch_state.json'
BASE = 'TxgTbNZV8aieOJsT21pcr9jXnPf'
TABLE = 'tblkasFvHs3hl91c'
FIELD_ID = 'fldesr8bw9'   # 2D图纸

sys.path.insert(0, str(WORK))
from titleblock_factory import make_titleblock
from zcode_v10_bc21 import make_layout_background, show_component

# template slots on the 842x595 landscape sheet (x0,y0,x1,y1)
SLOTS = [
    (40, 40, 300, 220), (315, 40, 565, 220), (580, 40, 812, 225),
    (40, 235, 225, 355), (240, 235, 415, 355), (430, 235, 560, 355),
    (575, 240, 812, 400), (40, 370, 300, 440), (315, 368, 560, 440),
    (40, 452, 392, 540), (405, 405, 560, 445),
]

def sh(cmd):
    """run lark-cli (cmd = arg list), return (ok, stdout)"""
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    i = out.find('{')
    if i < 0:
        return r.returncode == 0, out
    try:
        d, _ = json.JSONDecoder().raw_decode(out[i:])
        return bool(d.get('ok')), out
    except Exception:
        return r.returncode == 0, out

def jout(cmd):
    ok, out = sh(cmd)
    i = out.find('{')
    if i < 0:
        return ok, {}
    try:
        d, _ = json.JSONDecoder().raw_decode(out[i:])
        return ok, d
    except Exception:
        return ok, {}

def load_records():
    ok, _ = sh(['lark-cli', 'base', '+record-list', '--base-token', BASE,
                '--table-id', TABLE, '--field-id', 'fldWJ3UAoU',
                '--field-id', FIELD_ID, '--format', 'ndjson',
                '--output', str(WORK / 'pim_records.ndjson'),
                '--overwrite', '--as', 'user'])
    rows = []
    for line in open(WORK / 'pim_records.ndjson', encoding='utf-8'):
        rows.append(json.loads(line))
    rows.sort(key=lambda r: r['record_id'])   # 稳定顺序：按 record_id（≈建表顺序）
    return rows

def detect_sideways(page):
    """rotation-0 page whose text runs vertical -> content drawn sideways"""
    vert = horz = 0
    for blk in page.get_text('dict')['blocks']:
        for line in blk.get('lines', []):
            dx, dy = line['dir']
            if abs(dx) > abs(dy): horz += 1
            else: vert += 1
    return vert > horz

def auto_groups(page):
    """content boxes in display pt (dark-ink components, frame/watermark strips excluded)"""
    pix = page.get_pixmap(dpi=100)
    img = np.asarray(Image.frombytes('RGB', (pix.width, pix.height), pix.samples)).astype(int)
    H, W = img.shape[:2]; sc = W / 841.89
    ink = (img.mean(axis=2) < 150)
    ink[:, :int(20 * sc)] = False; ink[:, int(822 * sc):] = False
    ink[:int(26 * sc), :] = False; ink[int(558 * sc):, :] = False
    rad = max(3, int(9 * sc))
    dil = Image.fromarray((ink * 255).astype('uint8')).filter(
        ImageFilter.MaxFilter(2 * rad + 1))
    d = np.asarray(dil) > 0
    k = 4
    small = d[::k, ::k]
    lab = np.zeros(small.shape, dtype=int); cur = 0
    from collections import deque
    boxes = []
    for i in range(small.shape[0]):
        for j in range(small.shape[1]):
            if small[i, j] and lab[i, j] == 0:
                cur += 1; q = deque([(i, j)]); lab[i, j] = cur
                x0 = x1 = j; y0 = y1 = i; n = 0
                while q:
                    y, x = q.popleft(); n += 1
                    x0 = min(x0, x); x1 = max(x1, x); y0 = min(y0, y); y1 = max(y1, y)
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = y + dy, x + dx
                            if 0 <= ny < small.shape[0] and 0 <= nx < small.shape[1] \
                               and small[ny, nx] and lab[ny, nx] == 0:
                                lab[ny, nx] = cur; q.append((ny, nx))
                bw, bh = (x1 - x0) * k / sc, (y1 - y0) * k / sc
                if n > 30 and bw >= 10 and bh >= 10:
                    # drop the source's own frame: spans most of the sheet
                    if bw > 0.75 * 842 and bh > 0.75 * 595:
                        continue
                    boxes.append((x0 * k / sc, y0 * k / sc, (x1 + 1) * k / sc, (y1 + 1) * k / sc))
    boxes.sort(key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    return boxes

def pack(boxes):
    """greedy assign boxes to slots: best (largest) scale first"""
    slots, out = list(SLOTS), []
    for b in sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
        bw, bh = b[2] - b[0], b[3] - b[1]
        best = None
        for si, (sx0, sy0, sx1, sy1) in enumerate(slots):
            s = min((sx1 - sx0) / bw, (sy1 - sy0) / bh)
            fit = (sx1 - sx0) * (sy1 - sy0) - bw * s * bh * s   # wasted area
            if best is None or fit < best[0]:
                best = (fit, si, s)
        _, si, s = best
        sx0, sy0, sx1, sy1 = slots.pop(si)
        w, h = bw * s, bh * s
        cx, cy = (sx0 + sx1) / 2, (sy0 + sy1) / 2
        out.append((tuple(b), (cx, cy), w, h))
    return out

def extract_model(page, M, fallback):
    anchor = None
    words = []
    for x0, y0, x1, y1, t, *_ in page.get_text('words'):
        r = fitz.Rect((x0, y0, x1, y1)) * M
        words.append((r, t.strip()))
        if ('图号' in t or 'MODEL：' in t) and anchor is None:
            anchor = r
    if anchor is not None:
        cy = (anchor.y0 + anchor.y1) / 2
        cands = [w for r, w in words
                 if r is not anchor and abs((r.y0 + r.y1) / 2 - cy) < 14
                 and r.x0 > anchor.x1 - 10 and r.x0 < anchor.x1 + 170
                 and '图号' not in w and 'MODEL' not in w]
        if cands:
            cands.sort(key=lambda r: r.x0)
            return ''.join(w for w in cands)
    fb = re.sub(r'^2D_', '', fallback.rsplit('.', 1)[0])
    fb = re.sub(r'[（(]cad2pdf[)）]', '', fb).strip('_ ')
    return fb

def coverage_ok(src_path, set_rot, placed):
    """nothing but frame/watermark strips may remain outside placed boxes"""
    src = fitz.open(src_path); p = src[0]
    if set_rot: p.set_rotation(270)
    pix = p.get_pixmap(dpi=100)
    img = np.asarray(Image.frombytes('RGB', (pix.width, pix.height), pix.samples)).astype(int)
    H, W = img.shape[:2]; sc = W / 841.89
    ink = (img.mean(axis=2) < 150)
    ink[:, :int(20 * sc)] = False; ink[:, int(822 * sc):] = False
    ink[:int(26 * sc), :] = False; ink[int(558 * sc):, :] = False
    mask = np.zeros_like(ink)
    for (x0, y0, x1, y1), c, mw, mh in placed:
        r = fitz.Rect(x0, y0, x1, y1)  # source box
        pass
    # placed source boxes (not target rects) define covered source area
    for box, c, mw, mh in placed:
        x0, y0, x1, y1 = box
        mask[int(y0 * sc):int(y1 * sc), int(x0 * sc):int(x1 * sc)] = True
    rest = ink & ~mask
    k = 4
    small = rest[::k, ::k]
    from collections import deque
    lab = np.zeros(small.shape, dtype=int); cur = 0
    for i in range(small.shape[0]):
        for j in range(small.shape[1]):
            if small[i, j] and lab[i, j] == 0:
                cur += 1; q = deque([(i, j)]); lab[i, j] = cur
                n = 0
                while q:
                    y, x = q.popleft(); n += 1
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = y + dy, x + dx
                            if 0 <= ny < small.shape[0] and 0 <= nx < small.shape[1] \
                               and small[ny, nx] and lab[ny, nx] == 0:
                                lab[ny, nx] = cur; q.append((ny, nx))
                if n * k * k >= 260:      # ~ significant leftover ink
                    return False, n * k * k
    return True, 0

def build(src_path, out_pdf, model, groups, title_png, bg_png):
    make_titleblock(model, title_png)
    make_layout_background()
    src = fitz.open(src_path); sp = src[0]
    out = fitz.open()
    p = out.new_page(width=sp.mediabox.width, height=sp.mediabox.height)
    p.set_cropbox(sp.cropbox); p.set_rotation(sp.rotation)
    p.insert_image(p.cropbox, filename=str(bg_png), keep_proportion=False, overlay=False)
    svg = sp.get_svg_image(matrix=fitz.Matrix(1, 1), text_as_path=True)
    svg = svg.replace('<svg ', '<svg fill="#0642a8" ', 1)
    svg = (svg.replace('#000000', '#0642a8')
              .replace('#00ffff', '#e6a21a')
              .replace('#808080', '#6f9bcf'))
    from zcode_v10_bc21 import place
    for box, c, mw, mh in groups:
        show_component(p, svg, box, place(box, c, mw, mh))
    t = fitz.Rect(400, 450, 820, 564) * p.derotation_matrix
    p.insert_image(t, filename=str(title_png), rotate=270,
                   keep_proportion=False, overlay=True)
    if Path(out_pdf).exists(): Path(out_pdf).unlink()
    out.save(out_pdf, garbage=4, deflate=True, clean=False)
    out.close(); src.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--upload', action='store_true', help='push finished PDFs back to Feishu')
    args = ap.parse_args()

    state = json.load(open(STATE, encoding='utf-8')) if STATE.exists() else {}
    # three drawings already replaced via the manual first pass
    for old in ('Z02Obrqipod737xDeOHcUtPLnbf', 'O6UIbEbdCoYwsLxEBXpceIbmnhe',
                'O4a6bzDsZoCOlsxYcdTcEVefnId'):
        state.setdefault(old, {'status': 'done', 'note': 'replaced in first pass'})
    rows = load_records()
    # distinct drawings in first-appearance order
    order = {}
    for row in rows:
        for att in row.get('2D图纸') or []:
            order.setdefault(att['file_token'],
                             {'name': att['name'], 'size': att['size'], 'records': []})
            order[att['file_token']]['records'].append(row['record_id'])

    done_new_tokens = {'Q8DpbiXlVoDQcKx2kfFce5phnod', 'NawQbBfuuojeXvxZDjMcEjEYnYd',
                       'Bjxhb6VVaobICtx7irjc0mePnjd'}
    order_file = WORK / 'draw_order.json'
    if order_file.exists():
        prefixes = json.load(open(order_file, encoding='utf-8'))
        seq = []
        seen = set()
        for pref in prefixes:
            for t in order:
                if t.startswith(pref) and t not in seen:
                    seq.append(t); seen.add(t)
        for t in order:                      # 首拉里没有的记录附件排在最后
            if t not in seen:
                seq.append(t); seen.add(t)
        todo = [t for t in seq if t not in state and t not in done_new_tokens]
    else:
        todo = [t for t in order if t not in state and t not in done_new_tokens]
    if args.limit: todo = todo[:args.limit]
    print('待处理 %d 张' % len(todo))

    results = []
    for n, token in enumerate(todo, 1):
        info = order[token]
        name = info['name']
        rec0 = info['records'][0]
        st = {'name': name, 'records': info['records'], 'status': 'download'}
        state[token] = st
        print(f'[{n}/{len(todo)}] {name}')
        try:
            src_pdf = WORK / ('batch_%s.pdf' % token[:16])
            ok, _ = jout(['lark-cli', 'base', '+record-download-attachment',
                          '--base-token', BASE, '--table-id', TABLE,
                          '--record-id', rec0, '--file-token', token,
                          '--output', str(src_pdf), '--overwrite', '--as', 'user'])
            if not ok: raise RuntimeError('download failed')
            src = fitz.open(src_pdf); page = src[0]
            set_rot = False
            if page.rotation == 0 and detect_sideways(page):
                set_rot = True
            if set_rot: page.set_rotation(270)
            boxes = auto_groups(page)
            if not boxes: raise RuntimeError('no content groups found')
            groups = pack(boxes)
            M = page.rotation_matrix
            model = extract_model(page, M, name)
            src.close()

            ok, leftover = coverage_ok(src_pdf, set_rot, groups)
            if not ok:
                st.update(status='coverage-fail', leftover=leftover)
                print('   ✗ 遗漏扫描未通过 (leftover=%d)' % leftover)
                results.append((name, 'coverage-fail')); state[token] = st
                (STATE).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
                continue

            safe = re.sub(r'[^\w\u4e00-\u9fff.-]+', '_', model)[:40]
            out_pdf = OUT_DIR / name
            title_png = WORK / ('tb_%s.png' % abs(hash(model)))
            build(src_pdf, out_pdf, model, groups, title_png,
                  WORK / 'zcode_v10_background.png')

            new_token = None
            if args.upload:
                ok, out = jout(['lark-cli', 'base', '+record-upload-attachment',
                                '--base-token', BASE, '--table-id', TABLE,
                                '--record-id', rec0, '--field-id', FIELD_ID,
                                '--file', str(out_pdf), '--as', 'user'])
                if not ok: raise RuntimeError('upload failed: ' + str(out)[:300])
                for rec in (out.get('data', {}).get('attachments') or {}).values():
                    for f in (rec.get(FIELD_ID) or []):
                        if f.get('name') == name and f.get('file_token') != token:
                            new_token = f['file_token']
                upd = {}
                for rid in info['records']:
                    row = next(r for r in rows if r['record_id'] == rid)
                    cell = [{ 'file_token': new_token if a['file_token'] == token
                              else a['file_token'] } for a in (row.get('2D图纸') or [])]
                    upd[rid] = {'2D图纸': cell}
                payload = WORK / 'batch_upd.json'
                payload.write_text(json.dumps({'update_records': upd}, ensure_ascii=False), encoding='utf-8')
                ok, _ = jout(['lark-cli', 'base', '+record-batch-update',
                              '--base-token', BASE, '--table-id', TABLE,
                              '--json', '@' + str(payload), '--as', 'user'])
                if not ok: raise RuntimeError('record update failed')

            st.update(status='done', model=model, out=str(out_pdf),
                      new_token=new_token, uploaded=bool(args.upload))
            print('   ✓ %s (model=%s%s)' % (out_pdf.name, model,
                  ' 已回传' if args.upload else ' 本地'))
            results.append((name, 'done'))
        except Exception as e:
            st.update(status='error', error=str(e)[:200])
            print('   ✗', e)
            results.append((name, 'error: %s' % e))
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')

    ok_n = sum(1 for _, s in results if s == 'done')
    print('\n完成 %d / %d' % (ok_n, len(results)))
    for name, s in results:
        if s != 'done': print('  需人工:', name, '→', s)

if __name__ == '__main__':
    main()
