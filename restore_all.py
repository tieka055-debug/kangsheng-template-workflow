"""把所有污染的 2D图纸 附件恢复为供应商原图"""
from pathlib import Path
import json, subprocess
W = Path(__file__).resolve().parent
BASE, TABLE, F = 'TxgTbNZV8aieOJsT21pcr9jXnPf', 'tblkasFvHs3hl91c', 'fldesr8bw9'

def sh_json(cmd, timeout=180):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = r.stdout + r.stderr
    i = out.find('{')
    if i < 0: return False, {}
    try:
        d, _ = json.JSONDecoder().raw_decode(out[i:])
        return bool(d.get('ok')), d
    except Exception:
        return False, {}

# 当前引用关系：record → [attachments]
rows = [json.loads(l) for l in open(W/'pim_audit.ndjson', encoding='utf-8')]
rec_by_id = {r['record_id']: r for r in rows}
rmap = json.load(open(W/'restore_map.json', encoding='utf-8'))  # name → [clean paths]

# 按 name 分组所有污染引用
refs = {}   # name → [record_ids]
for rid, pn, name, size in json.load(open(W/'polluted_rows.json', encoding='utf-8')):
    refs.setdefault(name, []).append(rid)

names = sorted(refs)
print('需恢复的不同文件:', len(names), flush=True)
name2newtok = {}
fail = []
for n, name in enumerate(names, 1):
    src = rmap[name][0]
    first_rid = refs[name][0]
    ok, d = sh_json(['lark-cli','base','+record-upload-attachment','--base-token',BASE,
                     '--table-id',TABLE,'--record-id',first_rid,'--field-id',F,
                     '--file',src,'--as','user'])
    nt = None
    if ok:
        for rec in (d.get('data',{}).get('attachments') or {}).values():
            for f in (rec.get(F) or []):
                if f['name'] == Path(src).name or f.get('size'):
                    cands = [f['file_token'] for f in rec.get(F) or []]
                # 取新上传的（尺寸匹配源文件的）
            for f in (rec.get(F) or []):
                if f['name'] == Path(src).name:
                    nt = f['file_token']   # 新上传的同名文件
    if not nt:
        print(f'[{n}] {name} ✗ 上传失败', flush=True); fail.append(name); continue
    name2newtok[name] = nt
    # 批量更新引用该文件的所有记录：旧污染 token → 新 token
    upd = {}
    for rid in refs[name]:
        cell = rec_by_id[rid].get('2D图纸') or []
        newcell = [{'file_token': nt if a['name'] == name and a['file_token'] not in name2newtok.values()
                    else a['file_token']} for a in cell]
        # 同名可能有多个污染 token（重复上传），全部映射到 nt
        newcell = []
        for a in cell:
            if a['name'] == name:
                newcell.append({'file_token': nt})
            else:
                newcell.append({'file_token': a['file_token']})
        upd[rid] = {'2D图纸': newcell}
    payload = W/'restore_upd_batch.json'
    payload.write_text(json.dumps({'update_records': upd}, ensure_ascii=False), encoding='utf-8')
    ok2, _ = sh_json(['lark-cli','base','+record-batch-update','--base-token',BASE,
                      '--table-id',TABLE,'--json','@'+str(payload),'--as','user'])
    print(f'[{n}/{len(names)}] {name} ✓ ({len(upd)} 记录)' if ok2 else f'[{n}] {name} ✗ 更新失败', flush=True)
json.dump(name2newtok, open(W/'restore_done.json','w'), ensure_ascii=False, indent=1)
print('失败:', fail, flush=True)
