"""光栅管线批量：所有系列图重做为质量保证版（除已认可的4张）"""
from pathlib import Path
import json, subprocess, sys
import fitz

W = Path(__file__).resolve().parent
ROOT = W.parent
OUT = ROOT / 'outputs' / 'ZCode_V10'
BASE, TABLE, FIELD_ID = 'TxgTbNZV8aieOJsT21pcr9jXnPf', 'tblkasFvHs3hl91c', 'fldesr8bw9'
sys.path.insert(0, str(W))
from build_raster import build_raster
from batch_runner import extract_model
from titleblock_factory import make_titleblock

APPROVED = {'BC-21系列塑高2.25H Model.pdf', 'BC-21系列塑高1.7H Model.pdf',
            '2D_BC-26系列 2-6P.pdf', 'BC-60-2P全贴.pdf111'}

def sh_json(cmd, timeout=120):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = r.stdout + r.stderr
    i = out.find('{')
    if i < 0: return False, {}
    try:
        d, _ = json.JSONDecoder().raw_decode(out[i:])
        return bool(d.get('ok')), d
    except Exception:
        return False, {}

def main():
    rows = [json.loads(l) for l in open(W/'pim_final2.ndjson', encoding='utf-8')]
    # 按 token 聚合（跳过已认可/非PDF）
    tok = {}
    order = []
    for row in rows:
        for att in row.get('2D图纸') or []:
            name = att['name']
            if name in APPROVED or not name.lower().endswith('.pdf'):
                continue
            t = att['file_token']
            if t not in tok:
                tok[t] = {'name': name, 'records': []}
                order.append(t)
            tok[t]['records'].append(row['record_id'])
    print('待重做:', len(order), flush=True)
    done_set, fails = set(), []
    state_f = W/'raster_state.json'
    rstate = json.load(open(state_f, encoding='utf-8')) if state_f.exists() else {}
    for n, t in enumerate(order, 1):
        if rstate.get(t, {}).get('status') == 'done':
            continue
        info = tok[t]
        name, rec0 = info['name'], info['records'][0]
        print(f'[{n}/{len(order)}] {name}', flush=True)
        try:
            src_pdf = W / ('batch_%s.pdf' % t[:16])
            need_dl = True
            if src_pdf.exists():
                try:
                    d = fitz.open(src_pdf); d.close(); need_dl = False
                except Exception:
                    pass
            if need_dl:
                ok, _ = sh_json(['lark-cli', 'base', '+record-download-attachment',
                                 '--base-token', BASE, '--table-id', TABLE,
                                 '--record-id', rec0, '--file-token', t,
                                 '--output', str(src_pdf), '--overwrite', '--as', 'user'])
                if not ok: raise RuntimeError('download failed')
            src = fitz.open(src_pdf)
            page = src[0]
            if page.mediabox.height > page.mediabox.width and page.rotation == 0:
                page.set_rotation(270)
            M = page.rotation_matrix
            model = extract_model(page, M, name)
            src.close()
            tb_png = W / ('tb_r_%s.png' % t[:12])
            make_titleblock(model, tb_png)
            out_pdf = OUT / name
            build_raster(src_pdf, out_pdf, model, tb_png, W/'user_bg_plate.png')

            # 渲染校验：横版 + 非空
            d2 = fitz.open(out_pdf)
            if d2[0].rect.width < d2[0].rect.height:
                d2.close(); raise RuntimeError('still portrait')
            d2.close()

            new_token = None
            ok, out = sh_json(['lark-cli', 'base', '+record-upload-attachment',
                               '--base-token', BASE, '--table-id', TABLE,
                               '--record-id', rec0, '--field-id', FIELD_ID,
                               '--file', str(out_pdf), '--as', 'user'])
            if not ok: raise RuntimeError('upload failed')
            for rec in (out.get('data', {}).get('attachments') or {}).values():
                for f in (rec.get(FIELD_ID) or []):
                    if f.get('name') == name and f.get('file_token') != t:
                        new_token = f['file_token']
            if not new_token: raise RuntimeError('no new token')
            upd = {}
            for rid in info['records']:
                row = next(r for r in rows if r['record_id'] == rid)
                cell = [{'file_token': new_token if a['file_token'] == t else a['file_token']}
                        for a in (row.get('2D图纸') or [])]
                upd[rid] = {'2D图纸': cell}
            payload = W / 'raster_upd.json'
            payload.write_text(json.dumps({'update_records': upd}, ensure_ascii=False), encoding='utf-8')
            ok, _ = sh_json(['lark-cli', 'base', '+record-batch-update',
                             '--base-token', BASE, '--table-id', TABLE,
                             '--json', '@' + str(payload), '--as', 'user'])
            if not ok: raise RuntimeError('record update failed')
            rstate[t] = {'status': 'done', 'new_token': new_token, 'model': model}
            print('   ✓ 已回传 (model=%s)' % model, flush=True)
        except Exception as e:
            rstate[t] = {'status': 'fail', 'error': str(e)[:150]}
            print('   ✗', str(e)[:150], flush=True)
            fails.append(name)
        state_f.write_text(json.dumps(rstate, ensure_ascii=False, indent=1), encoding='utf-8')
    print('完成。失败 %d:' % len(fails), fails, flush=True)

if __name__ == '__main__':
    main()
