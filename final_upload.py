"""Upload every rebuilt output and swap 替换图纸 per record."""
import json, os, subprocess, sys, time
from pathlib import Path
BASE = 'TxgTbNZV8aieOJsT21pcr9jXnPf'; TABLE = 'tblkasFvHs3hl91c'; FIELD = 'fldfi1Wnt8'
OUT = (Path('.').resolve().parent / 'outputs' / 'ZCode_V10').resolve()
os.chdir(OUT)

def sh_json(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr; i = out.find('{')
    if i < 0: return False, {}
    try:
        d, _ = json.JSONDecoder().raw_decode(out[i:]); return bool(d.get('ok', True)), d
    except Exception: return False, {}

st = json.load(open(str(Path('.').resolve() / 'batch_v2_state.json')))
# 特殊: 拼版拆分的两个系列,一行两个 PDF
JUMBO = {
    'SX5TbKdr4oJJkQxo': ['5.0间距母座系列-A.pdf', '5.0间距母座系列-B.pdf'],
    'YiTBbT5gkoCQeSxV': ['KS-5.0S系列-A.pdf', 'KS-5.0S系列-B.pdf'],
}
items = [(t, s) for t, s in st.items()
         if s.get('status') == 'ok' and s.get('check') != 'branded:as-is']
only = sys.argv[1] if len(sys.argv) > 1 else None
if only:
    items = [(t, s) for t, s in items if only in s['name']]
print(f'upload {len(items)} entries', flush=True)
fails = []
for i, (tok, s) in enumerate(items, 1):
    name = s['name']
    files = JUMBO.get(tok, [name])
    tokens = []
    for f in files:
        if not os.path.exists(f):
            fails.append(f); print(f'  ✗ missing file {f}', flush=True); continue
        rec = s['records'][0]
        ok, res = sh_json(['lark-cli', 'base', '+record-upload-attachment',
                           '--base-token', BASE, '--table-id', TABLE,
                           '--record-id', rec, '--field-id', FIELD,
                           '--file', f, '--as', 'user'])
        new = None
        for rr, flds in (res.get('data', {}).get('attachments') or {}).items():
            for x in (flds.get(FIELD) or []):
                if x.get('file_token'): new = x['file_token']
        if ok and new:
            tokens.append(new)
        else:
            fails.append(f); print(f'  ✗ upload {f}', flush=True)
    if not tokens:
        continue
    payload = {'update_records': {r: {'替换图纸': [{'file_token': t} for t in tokens]}
                                  } for r in s['records']}
    json.dump(payload, open('/tmp/upd_f.json', 'w'), ensure_ascii=False)
    ok, _ = sh_json(['lark-cli', 'base', '+record-batch-update',
                     '--base-token', BASE, '--table-id', TABLE,
                     '--json', '@/tmp/upd_f.json', '--as', 'user'])
    if not ok:
        fails.append(name); print(f'  ✗ update {name}', flush=True)
    if i % 15 == 0:
        print(f'... {i}/{len(items)}', flush=True)
    time.sleep(0.15)
print(f'UPLOAD DONE fails={len(fails)}', flush=True)
