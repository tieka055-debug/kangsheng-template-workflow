"""重建方向错误的作品并重传（官方通道，同名替换）"""
from pathlib import Path
import json, subprocess, sys
import fitz

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / 'work'
OUT_DIR = ROOT / 'outputs' / 'ZCode_V10'
BASE = 'TxgTbNZV8aieOJsT21pcr9jXnPf'
TABLE = 'tblkasFvHs3hl91c'
FIELD_ID = 'fldesr8bw9'
sys.path.insert(0, str(WORK))
from batch_runner import auto_groups, pack, coverage_ok, build

def sh_json(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    i = out.find('{')
    if i < 0: return False, {}
    try:
        d, _ = json.JSONDecoder().raw_decode(out[i:])
        return bool(d.get('ok')), d
    except Exception:
        return False, {}

def main():
    repair = json.load(open(WORK / 'qa_repair.json', encoding='utf-8'))
    state_path = WORK / 'batch_state.json'
    state = json.load(open(state_path, encoding='utf-8'))
    fixed, failed = [], []
    for n, item in enumerate(repair, 1):
        tok, out_pdf = item['token'], item['out']
        rec0 = item['records'][0]
        name = item['name']
        print(f'[{n}/{len(repair)}] {name}')
        try:
            src_pdf = WORK / ('batch_%s.pdf' % tok[:16])
            src = fitz.open(src_pdf); page = src[0]
            if page.mediabox.height > page.mediabox.width and page.rotation == 0:
                page.set_rotation(270)
            boxes = auto_groups(page)
            if not boxes: raise RuntimeError('no content groups')
            groups = pack(boxes)
            model = item['model']
            src.close()

            title_png = WORK / ('tb_%s.png' % abs(hash(model)))
            build(src_pdf, out_pdf, model, groups, title_png,
                  WORK / 'zcode_v10_background.png')

            # 渲染校验：必须横版
            d2 = fitz.open(out_pdf)
            if d2[0].rect.width < d2[0].rect.height:
                d2.close(); raise RuntimeError('still portrait!')
            d2.close()

            new_token = None
            ok, out = sh_json(['lark-cli', 'base', '+record-upload-attachment',
                               '--base-token', BASE, '--table-id', TABLE,
                               '--record-id', rec0, '--field-id', FIELD_ID,
                               '--file', str(out_pdf), '--as', 'user'])
            if not ok: raise RuntimeError('upload failed')
            for rec in (out.get('data', {}).get('attachments') or {}).values():
                for f in (rec.get(FIELD_ID) or []):
                    if f.get('name') == name and f.get('file_token') != tok:
                        new_token = f['file_token']
            if not new_token: raise RuntimeError('no new token')

            upd = {}
            for rid in item['records']:
                row = next(r for r in (json.loads(l) for l in open(WORK / 'pim_verify.ndjson', encoding='utf-8'))
                           if r['record_id'] == rid)
                cell = [{'file_token': new_token if a['file_token'] == tok else a['file_token']}
                        for a in (row.get('2D图纸') or [])]
                upd[rid] = {'2D图纸': cell}
            payload = WORK / 'qa_upd.json'
            payload.write_text(json.dumps({'update_records': upd}, ensure_ascii=False), encoding='utf-8')
            ok, _ = sh_json(['lark-cli', 'base', '+record-batch-update',
                             '--base-token', BASE, '--table-id', TABLE,
                             '--json', '@' + str(payload), '--as', 'user'])
            if not ok: raise RuntimeError('record update failed')
            state[tok] = {**state.get(tok, {}), 'status': 'done', 'new_token': new_token,
                          'repaired': True}
            fixed.append(name)
            print('   ✓ 修复并回传')
        except Exception as e:
            print('   ✗', str(e)[:150])
            failed.append({'name': name, 'error': str(e)[:150]})
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'\n修复 {len(fixed)} / 失败 {len(failed)}')
    if failed:
        json.dump(failed, open(WORK / 'qa_failed.json', 'w'), ensure_ascii=False, indent=1)

if __name__ == '__main__':
    main()
