"""逐张隔离跑：每张独立子进程 + 240s 超时，卡死只废一张"""
from pathlib import Path
import json, subprocess, sys
W = Path(__file__).resolve().parent
order = json.load(open(W/'draw_order.json'))
state = json.load(open(W/'batch_state.json', encoding='utf-8'))
skip = {'done','skipped'}
seq = []
seen = set()
for pref in order:
    for t in state:
        if t.startswith(pref) and t not in seen:
            seq.append(t); seen.add(t)
for t in state:
    if t not in seen: seq.append(t); seen.add(t)
pending = [t for t in seq if state.get(t,{}).get('status') not in skip]
print('待处理:', len(pending), flush=True)
for n, tok in enumerate(pending, 1):
    name = state.get(tok,{}).get('name','?')
    print(f'[{n}/{len(pending)}] {name}', flush=True)
    try:
        r = subprocess.run(['python3', str(W/'batch_runner.py'),
                            '--token', tok, '--upload'],
                           capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        print('    ✗ 超时(240s)', flush=True)
        continue
    tail = (r.stdout+r.stderr).strip().splitlines()
    ok = any('✓' in l for l in tail)
    print('   ', '✓ 完成' if ok and r.returncode==0 else ('✗ 超时/失败' if r.returncode!=0 else '✗ 未通过遗漏扫描'), flush=True)
print('全部结束', flush=True)
