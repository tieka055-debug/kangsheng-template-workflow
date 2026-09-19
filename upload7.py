"""Upload the rebuilt 7 PDFs and swap them into 替换图纸 (fldfi1Wnt8)."""
import json, subprocess, sys, time
from pathlib import Path

BASE = 'TxgTbNZV8aieOJsT21pcr9jXnPf'
TABLE = 'tblkasFvHs3hl91c'
FIELD = 'fldfi1Wnt8'
OUT = Path('../outputs/ZCode_V10').resolve()
import os
os.chdir(OUT)  # lark-cli 允许当前工作目录下的文件
ROWS = [
    ('recvvfKwhohqfJ', '2D_BC-21系列沉板1.25.pdf'),
    ('recvvfKwKXdISu', '2D_BC-22系列母座 Model.pdf'),
    ('recvvlxYFu9kwl', '2D_BC-16系列1.8H-R1.25 Model.pdf'),
    ('recvvlxYFuwJ4T', '2D_BC-16系列1.8H-R1.9 Model.pdf'),
    ('recvvlxYFuSQ50', '2D_BC-16系列2.2H-R1.25.pdf'),
    ('recvvlxYFuM579', '2D_BC-16系列2.2H-R1.9 Model.pdf'),
    ('recvvlxYFuCbsJ', '2D_BC-17系列3-10P.pdf'),
]

def sh_json(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    i = out.find('{')
    if i < 0:
        return False, {}
    try:
        d, _ = json.JSONDecoder().raw_decode(out[i:])
        return bool(d.get('ok', True)), d
    except Exception:
        return False, {}

# current tokens per record (to identify the NEW upload)
ok, cur = sh_json(['lark-cli', 'base', '+record-list', '--base-token', BASE,
                   '--table-id', TABLE, '--field-id', FIELD,
                   '--format', 'ndjson', '--output', '/tmp/cur_tokens.ndjson',
                   '--overwrite', '--as', 'user'])
old = {}
for line in open('/tmp/cur_tokens.ndjson', encoding='utf-8'):
    r = json.loads(line)
    atts = (r.get('fields') or {}).get('替换图纸') or []
    old[r['record_id']] = {a['file_token'] for a in atts}

fails = []
for rec, name in ROWS:
    pdf = OUT / name
    print('upload', name, flush=True)
    ok, res = sh_json(['lark-cli', 'base', '+record-upload-attachment',
                       '--base-token', BASE, '--table-id', TABLE,
                       '--record-id', rec, '--field-id', FIELD,
                       '--file', name, '--as', 'user'])
    new = None
    for rrec, flds in (res.get('data', {}).get('attachments') or {}).items():
        for f in (flds.get(FIELD) or []):
            if f.get('name') == name and f.get('file_token') not in old.get(rec, set()):
                new = f['file_token']
    if not ok or not new:
        print('  ✗ upload/parse failed', str(res)[:200], flush=True)
        fails.append(name)
        continue
    payload = {'update_records': {rec: {'替换图纸': [{'file_token': new}]}}}
    json.dump(payload, open('/tmp/upd.json', 'w'), ensure_ascii=False)
    ok, _ = sh_json(['lark-cli', 'base', '+record-batch-update',
                     '--base-token', BASE, '--table-id', TABLE,
                     '--json', '@/tmp/upd.json', '--as', 'user'])
    print('  ✓ swapped' if ok else '  ✗ update failed', flush=True)
    if not ok:
        fails.append(name)
    time.sleep(0.4)
print('FAILS:', fails)
sys.exit(1 if fails else 0)
