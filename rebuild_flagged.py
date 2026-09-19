import json, sys, io, contextlib, re
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from build_ink import run_ink
import verify_pair

WORK = Path('.').resolve()
OUT = (WORK.parent / 'outputs' / 'ZCode_V10').resolve()
st = json.load(open('batch_v2_state.json'))
os.chdir(OUT) if False else None
import os
os.chdir(OUT)

flagged = [(t, s) for t, s in st.items()
           if s.get('rebuild') and s['rebuild'].get('verdict') != 'ok']
print(f'rebuild {len(flagged)} flagged', flush=True)
still = 0
for i, (tok, s) in enumerate(flagged, 1):
    name = s['name']
    src = f'/tmp/srcs/{tok}.pdf'
    out_pdf = OUT / name
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = run_ink(src, str(out_pdf), s.get('model') or name,
                         f'/tmp/qa_v2/{tok[:16]}.png')
        m = re.search(r'scale ([\d.]+)', buf.getvalue())
        cl = float(m.group(1)) if m else None
        ag = re.search(r'auto-gain ([\d.]+)', buf.getvalue())
        gain = float(ag.group(1)) if ag else None
        vp = f'/tmp/verify_v2/{tok[:16]}.json'
        verify_pair.main(src, str(out_pdf), cl if cl else 1.0, vp, 'frame')
        v = json.load(open(vp))
        verdict = 'ok' if v['ok'] else f"missing:{len(v['missing'])}"
        s['rebuild'] = {'verdict': verdict, 'clearance': cl, 'auto_gain': gain}
        if verdict != 'ok':
            still += 1
        print(f'[{i}] {verdict} cl={cl} gain={gain} {name[:44]}', flush=True)
    except Exception as e:
        still += 1
        print(f'[{i}] ERR {name[:40]}: {str(e)[:120]}', flush=True)
    json.dump(st, open('batch_v2_state.json', 'w'), ensure_ascii=False, indent=1)
print(f'DONE still-bad={still}', flush=True)
