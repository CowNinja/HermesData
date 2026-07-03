#!/usr/bin/env python3
"""Quick benchmark — writes to temp file for monitoring."""
import subprocess, time, urllib.request, json, sys
from pathlib import Path

LOG = open(r'C:\Users\CowNi\AppData\Local\Temp\hermes-bench.log', 'w', buffering=1)
sys.stdout = LOG
sys.stderr = LOG

LLAMA = r'D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe'
DIR = Path(r'D:\PhronesisModels\models\candidates')

MODELS = [
    ('qwen2-5-7b',     'Qwen2.5-7B-Instruct-Q5_K_M.gguf',                    28),
    ('qwen3-5-9b',     'Qwen3.5-9B-Q4_K_M.gguf',                             99),
    ('qwen3-8b-ablit', 'Huihui-Qwen3-8B-abliterated-v2.i1-Q4_K_M.gguf',      99),
    ('llama-8b-ablit', 'Meta-Llama-3.1-8B-Instruct-abliterated-Q5_K_M.gguf', 99),
    ('coder-14b-ablit','Qwen2.5-Coder-14B-Instruct-abliterated-Q5_K_M.gguf', 99),
    ('llama-3-2-3b',   'Llama-3.2-3B-Instruct-Q4_K_M.gguf',                  35),
    ('rocinante-12b',  'Rocinante-12B-v1.1-Q4_K_M.gguf',                     35),
]

def kill():
    subprocess.run(['taskkill','/F','/IM','llama-server.exe'], capture_output=True, timeout=10)
    time.sleep(2)

def load(mp, ngl):
    cmd = [LLAMA,'--model',str(mp),'--host','127.0.0.1','--port','8090',
           '--ctx-size','8192','--n-gpu-layers',str(ngl),'--parallel','1','--cont-batching']
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for i in range(120):
        time.sleep(1)
        try:
            r = urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=2)
            if r.getcode() == 200:
                return proc
        except:
            pass
    proc.kill()
    return None

def query(prompt, max_tok=200):
    body = json.dumps({'messages':[{'role':'user','content':prompt}],
                       'max_tokens':max_tok,'temperature':0.1,'stream':True}).encode()
    req = urllib.request.Request('http://127.0.0.1:8090/v1/chat/completions',
                                 data=body, headers={'Content-Type':'application/json'})
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=90)
    text, reason, fc, n = '', '', None, 0
    for raw in resp:
        line = raw.decode().strip()
        if line == 'data: [DONE]': break
        if not line.startswith('data: '): continue
        try:
            d = json.loads(line[6:])
            delta = d['choices'][0].get('delta',{})
            c, rc = delta.get('content',''), delta.get('reasoning_content','')
            if c: text += c; n += 1
            if rc: reason += rc
            if fc is None and (c or rc): fc = time.time() - t0
        except: pass
    total = time.time() - t0
    ttft = fc if fc else total
    body_t = max(total - ttft, 0.01)
    tps = n / body_t if n > 0 else 0
    return ttft, tps, text, reason, n

PROMPTS = {
    'speed':    ('Say hello in exactly 5 words.', 32),
    'coding':   ('Write a Python function that sorts a dict by value desc, ties by key asc. Include type hints.', 256),
    'reasoning':('Two trains 300 miles apart move toward each other at 60mph and 80mph. When do they meet? Show work.', 200),
}

print('=== BENCHMARK v3 ===')
results = []
for mid, fname, ngl in MODELS:
    mp = DIR / fname
    if not mp.exists():
        print(f'SKIP {mid}: not found'); continue
    print(f'\n>> {mid} (ngl={ngl})')
    kill()
    tload = time.time()
    proc = load(mp, ngl)
    if not proc:
        print(f'  !LOAD FAILED'); continue
    load_s = time.time() - tload
    print(f'  Load: {load_s:.1f}s')
    r = {'id': mid, 'load_s': round(load_s,1), 'tests': {}}
    for pname, (prompt, mt) in PROMPTS.items():
        try:
            ttft, tps, text, reason, n = query(prompt, mt)
            r['tests'][pname] = {
                'ttft': round(ttft,3), 'tok_s': round(tps,1),
                'tokens': n, 'think_chars': len(reason),
                'text_chars': len(text),
                'preview': (reason + ' ' + text)[:150],
            }
            print(f'  {pname}: TTFT={ttft:.3f}s tok/s={tps:.1f} tok={n} think={len(reason)}c text={len(text)}c')
        except Exception as e:
            r['tests'][pname] = {'error': str(e)}
            print(f'  {pname}: ERROR {e}')
    results.append(r)
    proc.terminate()
    try: proc.wait(timeout=5)
    except: proc.kill()
    time.sleep(1)

print(f'\n{"="*70}')
print('RESULTS')
print(f'{"Model":<22} {"TTFT":>6} {"tok/s":>7} {"Load":>5} {"Think":>6}')
print('-' * 50)
for r in results:
    t = r.get('tests',{})
    sp = t.get('speed',{})
    print(f"{r['id']:<22} {sp.get('ttft','-'):>6} {sp.get('tok_s','-'):>7} {r.get('load_s','-'):>5}s {sp.get('think_chars',0):>6}c")

out = r'C:\Users\CowNi\AppData\Local\Temp\hermes-bench-results.json'
with open(out, 'w') as f:
    json.dump(results, f, indent=2)
print(f'\nWritten: {out}')
LOG.close()
