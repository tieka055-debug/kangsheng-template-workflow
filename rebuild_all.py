"""Rebuild all non-branded/non-oversized files with the current pipeline and
verify each with the coverage checker."""
import json, sys, io, contextlib, re
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from build_ink import run_ink
import verify_pair

WORK = Path('.').resolve()
OUT = (WORK.parent / 'outputs' / 'ZCode_V10').resolve()
QA = Path('/tmp/qa_v2'); QA.mkdir(exist_ok=True)
st = json.load(open('batch_v2_state.json'))
os.chdir(OUT) if False else None

items = [(t, s) for t, s in st.items()
         if s.get('status') == 'ok' and s.get('new_token')
         and s.get('check') != 'branded:as-is']
only = sys.argv[1] if len(sys.argv) > 1 else None
if only:
    items = [(t, s) for t, s in items if only in s['name']]
print(f'rebuild {len(items)} files', flush=True)
bad = 0
for i, (tok, s) in enumerate(items, 1):
    name = s['name']
    src = f'/tmp/srcs/{tok}.pdf'
    out_pdf = OUT / name
    if not out_pdf.exists():
        out_pdf.write_bytes(open(src, 'rb').read())
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = run_ink(src, str(out_pdf), s.get('model') or name, str(QA / f'{tok[:16]}.png'))
        m = re.search(r'scale ([\d.]+)', buf.getvalue())
        cl = float(m.group(1)) if m else None
        anchor = 'frame'
        vp = f'/tmp/verify_v2/{tok[:16]}.json'
        Path('/tmp/verify_v2').mkdir(exist_ok=True)
        import fitz
        d = fitz.open(out_pdf)
        _r = d[0].rect
        d.close()
        if _r.width > _r.height:
            verify_pair.main(src, str(out_pdf), cl if cl else 1.0, vp, anchor)
            v = json.load(open(vp))
            verdict = 'ok' if v['ok'] else f"missing:{len(v['missing'])}"
        else:
            verdict = 'skip:portrait'
        if not ok:
            verdict = 'build-failed'
        s['rebuild'] = {'verdict': verdict, 'clearance': cl}
        tag = 'OK ' if verdict == 'ok' else 'WARN'
        if verdict != 'ok':
            bad += 1
        print(f'[{i}/{len(items)}] {tag} {verdict} cl={cl} {name[:44]}', flush=True)
    except Exception as e:
        s['rebuild'] = {'verdict': f'error:{str(e)[:120]}'}
        bad += 1
        print(f'[{i}/{len(items)}] ERR {name[:40]}: {str(e)[:120]}', flush=True)
    json.dump(st, open('batch_v2_state.json', 'w'), ensure_ascii=False, indent=1)
print(f'REBUILD DONE bad={bad}/{len(items)}', flush=True)
