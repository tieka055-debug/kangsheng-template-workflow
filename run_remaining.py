"""Batch: rebuild every remaining row's 2D drawing with the ink pipeline v4.1
and swap into 替换图纸 (fldfi1Wnt8). Resumable via batch_v2_state.json."""
import json, os, re, subprocess, sys, time, traceback
from pathlib import Path
import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_ink import run_ink

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / 'work'
OUT = (ROOT / 'outputs' / 'ZCode_V10').resolve()
BASE = 'TxgTbNZV8aieOJsT21pcr9jXnPf'
TABLE = 'tblkasFvHs3hl91c'
FIELD = 'fldfi1Wnt8'
SRC_DIR = Path('/tmp/srcs')
QA_DIR = Path('/tmp/qa_batch')
STATE = WORK / 'batch_v2_state.json'
LOG = WORK / 'batch_v2_log.txt'
DONE_RECS = {'recvvfKwhohqfJ','recvvfKwKXdISu','recvvlxYFu9kwl','recvvlxYFuwJ4T',
             'recvvlxYFuSQ50','recvvlxYFuM579','recvvlxYFuCbsJ'}
for d in (SRC_DIR, QA_DIR, OUT):
    d.mkdir(parents=True, exist_ok=True)

def log(msg):
    line = f'[{time.strftime("%H:%M:%S")}] {msg}'
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + '\n')

def sh_json(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    i = out.find('{')
    if i < 0:
        return r.returncode == 0, {}
    try:
        d, _ = json.JSONDecoder().raw_decode(out[i:])
        return bool(d.get('ok', True)), d
    except Exception:
        return False, {}

def model_from_name(name):
    m = re.sub(r'^2D_', '', name)
    m = re.sub(r'\s*Model\s*\.pdf$', '', m, flags=re.I)
    m = re.sub(r'\(cad2pdf\)\.pdf$', '', m, flags=re.I)
    m = re.sub(r'\.pdf$', '', m, flags=re.I)
    return m.strip() or name

def download(token, name, rec):
    dst = SRC_DIR / f'{token}.pdf'
    if dst.exists() and dst.stat().st_size > 1000:
        return dst
    ok, _ = sh_json(['lark-cli', 'base', '+record-download-attachment',
                     '--base-token', BASE, '--table-id', TABLE,
                     '--record-id', rec, '--file-token', token,
                     '--output', str(dst), '--overwrite', '--as', 'user'])
    if ok and dst.exists() and dst.stat().st_size > 1000:
        return dst
    return None

def is_branded(src_pdf):
    """源文件已含品牌标题栏（右下角大图）→ 之前做过的成品，不重制。"""
    try:
        d = fitz.open(src_pdf)
        p = d[0]
        zone_d = fitz.Rect(400, 450, 820, 564)
        zone_m = zone_d * p.derotation_matrix   # mediabox 空间
        for img in p.get_image_info():
            r = fitz.Rect(img['bbox'])
            r_area = max(r.width * r.height, 1.0)
            if r_area < 15000:
                continue
            # 标题栏图片：基本完整落在标题栏区内（整页扫描图不算）
            for zone in (zone_d, zone_m):
                inter = r & zone
                if not inter.is_empty and inter.width * inter.height > 0.9 * r_area:
                    d.close()
                return True
        d.close()
    except Exception:
        pass
    return False

def sanity(out_pdf, src_pdf, clearance):
    d = fitz.open(out_pdf)
    p = d[0]
    ok_size = p.rect.width > p.rect.height
    d.close()
    if not ok_size:
        return 'orientation'
    if clearance is not None and clearance < 0.70:
        return 'review:clearance'
    return 'ok'

state = json.load(open(STATE)) if STATE.exists() else {}

# ---- pending source list ----
sources = {}
for line in open('/tmp/orig_field.ndjson'):
    r = json.loads(line)
    if r['record_id'] in DONE_RECS:
        continue
    for a in (r.get('2D图纸') or []):
        sources.setdefault(a['file_token'], {'name': a['name'], 'records': []})
        sources[a['file_token']]['records'].append(r['record_id'])

limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
todo = [t for t in sources if state.get(t, {}).get('status') != 'ok']
if limit:
    todo = todo[:limit]
log(f'=== batch start: {len(todo)} of {len(sources)} sources pending ===')

os.chdir(OUT)  # lark-cli upload allowlist: cwd
for i, tok in enumerate(todo, 1):
    info = sources[tok]
    name = info['name']
    out_name = name if name.lower().endswith('.pdf') else name + '.pdf'
    log(f'[{i}/{len(todo)}] {name}')
    try:
        pdf = download(tok, name, info['records'][0])
        if not pdf:
            raise RuntimeError('download failed')
        branded = is_branded(pdf)
        if not branded:
            model = model_from_name(name)
            out_pdf = OUT / out_name
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ok = run_ink(str(pdf), str(out_pdf), model, str(QA_DIR / f'{tok[:12]}.png'))
            clearance = None
            m = re.search(r'scale ([\d.]+)', buf.getvalue())
            if m:
                clearance = float(m.group(1))
            if not ok or not out_pdf.exists():
                raise RuntimeError('build failed')
            chk = sanity(out_pdf, pdf, clearance)
        else:
            chk = 'branded:as-is'
            out_pdf = OUT / out_name
            out_pdf.write_bytes(pdf.read_bytes())
        ok2, res = sh_json(['lark-cli', 'base', '+record-upload-attachment',
                            '--base-token', BASE, '--table-id', TABLE,
                            '--record-id', info['records'][0], '--field-id', FIELD,
                            '--file', out_name, '--as', 'user'])
        new = None
        for rrec, flds in (res.get('data', {}).get('attachments') or {}).items():
            for f in (flds.get(FIELD) or []):
                if f.get('file_token') and f.get('file_token') != tok:
                    new = f['file_token']
        if not ok2 or not new:
            raise RuntimeError(f'upload failed {str(res)[:120]}')
        model = model_from_name(name)
        state[tok] = {'status': 'ok', 'name': name, 'new_token': new,
                      'clearance': clearance if not branded else None,
                      'check': chk, 'records': info['records'], 'model': model}
        extra = f'clearance={clearance}' if not branded else 'as-is(已认可成品)'
        log(f'  ok  {chk}  {extra}  token={new[:10]}')
    except Exception as e:
        state[tok] = {'status': 'fail', 'name': name, 'error': str(e)[:200],
                      'records': info['records']}
        log(f'  FAIL {name}: {str(e)[:150]}')
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))

# ---- per-record field updates ----
log('=== record field updates ===')
rec_tokens = {}
for tok, st in state.items():
    if st.get('status') != 'ok':
        continue
    for rec in st.get('records', []):
        rec_tokens.setdefault(rec, []).append(st['new_token'])
upd_fail = []
recs = sorted(rec_tokens)
for j, rec in enumerate(recs, 1):
    payload = {'update_records': {rec: {'替换图纸': [{'file_token': t} for t in rec_tokens[rec]]}}}
    json.dump(payload, open('/tmp/upd_batch.json', 'w'), ensure_ascii=False)
    ok, _ = sh_json(['lark-cli', 'base', '+record-batch-update',
                     '--base-token', BASE, '--table-id', TABLE,
                     '--json', '@/tmp/upd_batch.json', '--as', 'user'])
    if not ok:
        upd_fail.append(rec)
        log(f'  ✗ update {rec}')
    if j % 20 == 0:
        log(f'  updates {j}/{len(recs)}')
    time.sleep(0.2)
log(f'=== done: files ok={sum(1 for s in state.values() if s.get("status")=="ok")}, '
    f'fail={sum(1 for s in state.values() if s.get("status")=="fail")}, '
    f'records updated={len(recs)-len(upd_fail)}, update fails={len(upd_fail)} ===')
