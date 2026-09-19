"""85 个空行：上传干净原图并填充单元格"""
from pathlib import Path
import json, subprocess
W = Path(__file__).resolve().parent
BASE, TABLE, F = 'TxgTbNZV8aieOJsT21pcr9jXnPf', 'tblkasFvHs3hl91c', 'fldesr8bw9'
def sh_json(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    out = r.stdout + r.stderr
    i = out.find('{')
    try:
        d, _ = json.JSONDecoder().raw_decode(out[i:])
        return bool(d.get('ok')), d
    except Exception:
        return False, {}

rows = [json.loads(l) for l in open(W/'main_full.ndjson', encoding='utf-8')]
copy_rows = [json.loads(l) for l in open(W/'copy_full.ndjson', encoding='utf-8')]
APPROVED = {'Q8DpbiXlVoDQcKx2kfFce5phnod','NawQbBfuuojeXvxZDjMcEjEYnYd','Bjxhb6VVaobICtx7irjc0mePnjd'}
cidx = {}
for r in copy_rows:
    if r.get('2D图纸'):
        cidx[((r.get('内部型号') or '').strip(), (r.get('中文产品名称') or '').strip())] = r['2D图纸']
name2file = {p.name: p for p in (W/'clean_orig').glob('*.pdf')}
done_tokens = {}
n = ok_n = fail_n = 0
for r in rows:
    cell = r.get('2D图纸') or []
    if cell: continue                                    # 已有内容的行跳过
    if cell and all(a['file_token'] in APPROVED for a in cell): continue
    # 该行应有的图纸名：从污染清单找（同一 record 的附件名）
    rid = r['record_id']
    name = None
    for pr, pn, nm, sz in json.load(open(W/'polluted_rows.json', encoding='utf-8')):
        if pr == rid: name = nm; break
    if not name:
        continue
    n += 1
    src = name2file.get(name)
    if not src:
        print(f'[{n}] {name} ✗ 缺干净文件', flush=True); fail_n += 1; continue
    if name in done_tokens:
        nt = done_tokens[name]
    else:
        ok, d = sh_json(['lark-cli','base','+record-upload-attachment','--base-token',BASE,
                         '--table-id',TABLE,'--record-id',rid,'--field-id',F,
                         '--file',str(src),'--as','user'])
        nt = None
        for rec in (d.get('data',{}).get('attachments') or {}).values():
            for f in (rec.get(F) or []):
                if f['name'] == name: nt = f['file_token']
        if not nt:
            print(f'[{n}] {name} ✗ 上传失败', flush=True); fail_n += 1; continue
        done_tokens[name] = nt
    json.dump({'update_records': {rid: {'2D图纸': [{'file_token': nt}]}}},
              open(W/'one_upd.json','w'), ensure_ascii=False)
    ok2, _ = sh_json(['lark-cli','base','+record-batch-update','--base-token',BASE,
                      '--table-id',TABLE,'--json','@'+str(W/'one_upd.json'),'--as','user'])
    if ok2: ok_n += 1
    else: fail_n += 1
    if n % 10 == 0: print(f'进度 {n}, 成功 {ok_n}, 失败 {fail_n}', flush=True)
print(f'结束: 处理 {n}, 成功 {ok_n}, 失败 {fail_n}', flush=True)
