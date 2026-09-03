#!/usr/bin/env python3
"""Export top-500 KG nodes to a zero-dependency interactive HTML graph.

  python D:\\HermesData\\scripts\\ops\\export_kg_html.py
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

KG = Path(r"D:\HermesData\state\life_rag\kg.jsonl")
OUT = Path(r"D:\PhronesisVault\Operations\kg_interactive_graph.html")
TOP_N = 500
MAX_EDGES = 1800
BAN = (
    "patient-bloom",
    "medical-records",
    "navy-service",
    "roleplay-sandbox",
    "nutaku",
    "secrets-quarantine",
    "dicom",
    "volbrain",
    "deers",
)
SKIP_NODE = (
    "self",
    "unknown",
    "facebook",
    "linkedin",
    "twitter",
    "gmail",
    "phone",
    "live_sweep",
    "vector_sync",
    "contacts_audit",
    "comms_sync",
)

CLUSTERS = (
    ("family", ("gary", "sara", "jan", "jodi", "jenni", "anthony", "spencer", "blaizen", "bloom")),
    ("booksbloom", ("booksbloom", "books bloom")),
    ("fll", ("fll", "spike", "lego", "first lego")),
    ("albion", ("albion",)),
    ("hardware", ("optiplex", "qwythos", "8090", "3060", "hermes", "sovereign")),
)


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _banned(blob: str) -> bool:
    low = blob.lower().replace("/", "\\")
    if any(b in low for b in BAN):
        return True
    if "\\medical\\" in low or "/medical/" in blob.lower():
        return True
    return False


def _skip_node(name: str) -> bool:
    n = name.strip()
    if len(n) < 3 or n.isdigit():
        return True
    low = n.lower()
    if _banned(low):
        return True
    if any(s in low for s in SKIP_NODE):
        return True
    if "@" in n or n.startswith("email:"):
        return True
    if ":" in n and not any(c.isalpha() for c in n.split(":", 1)[0]):
        return True
    if "_" in n and " " not in n and len(n) > 24:
        return True
    return False


def cluster_of(name: str) -> str:
    low = name.lower()
    for cid, needles in CLUSTERS:
        if any(n in low for n in needles):
            return cid
    return "other"


def load() -> tuple[list[dict], list[dict], dict]:
    deg: Counter[str] = Counter()
    edges_all: list[tuple[str, str, str]] = []
    n_in = 0
    n_ban = 0
    if not KG.is_file():
        return [], [], {"error": "kg_missing", "path": str(KG)}
    with KG.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            n_in += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            s = str(rec.get("s") or "").strip()
            o = str(rec.get("o") or "").strip()
            r = str(rec.get("r") or "").strip() or "rel"
            blob = " ".join((s, r, o, str(rec.get("src") or ""), str(rec.get("path") or "")))
            if _banned(blob):
                n_ban += 1
                continue
            if _skip_node(s) or _skip_node(o):
                continue
            if s == o:
                continue
            deg[s] += 1
            deg[o] += 1
            edges_all.append((s, r, o))
    top = [name for name, _c in deg.most_common(TOP_N)]
    keep = set(top)
    nodes = [
        {
            "id": i,
            "label": name[:48],
            "full": name[:120],
            "deg": int(deg[name]),
            "cluster": cluster_of(name),
        }
        for i, name in enumerate(top)
    ]
    idx = {n["full"]: n["id"] for n in nodes}
    # remap if truncated full collision — use original name as key
    idx = {name: i for i, name in enumerate(top)}
    for n, name in zip(nodes, top):
        n["full"] = name[:120]
    edges = []
    seen = set()
    for s, r, o in edges_all:
        if s not in keep or o not in keep:
            continue
        a, b = idx[s], idx[o]
        key = (min(a, b), max(a, b), r[:24])
        if key in seen:
            continue
        seen.add(key)
        edges.append({"s": a, "o": b, "r": r[:32]})
        if len(edges) >= MAX_EDGES:
            break
    meta = {
        "ts": utc(),
        "kg_lines": n_in,
        "banned_dropped": n_ban,
        "nodes": len(nodes),
        "edges": len(edges),
        "top_n": TOP_N,
    }
    return nodes, edges, meta


HTML_HEAD = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Phronesis KG — top 500</title>
<style>
html,body{margin:0;height:100%;background:#0e1116;color:#d6dce6;font:14px/1.4 Segoe UI,system-ui,sans-serif}
#bar{padding:10px 16px;background:#161b22;border-bottom:1px solid #30363d;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
#bar b{color:#7ee787}
#hint{color:#8b949e;font-size:12px}
canvas{display:block;cursor:grab}
#tip{position:fixed;display:none;background:#1c2128;border:1px solid #30363d;padding:8px 10px;max-width:320px;pointer-events:none;border-radius:6px;font-size:12px}
.leg span{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:middle}
</style>
</head>
<body>
<div id="bar">
  <div><b>Phronesis life KG</b> — top degree nodes, banned silos dropped</div>
  <div class="leg">
    <span style="background:#e3b341"></span>family
    <span style="background:#58a6ff"></span>booksbloom
    <span style="background:#3fb950"></span>fll
    <span style="background:#d2a8ff"></span>albion
    <span style="background:#f85149"></span>hardware
    <span style="background:#6e7681"></span>other
  </div>
  <div id="hint">Drag · scroll zoom · click a node. Local file, no network.</div>
</div>
<canvas id="c"></canvas>
<div id="tip"></div>
<script>
"""

HTML_TAIL = r"""
const C={family:'#e3b341',booksbloom:'#58a6ff',fll:'#3fb950',albion:'#d2a8ff',hardware:'#f85149',other:'#6e7681'};
const canvas=document.getElementById('c'), ctx=canvas.getContext('2d');
const tip=document.getElementById('tip');
let W=0,H=0,scale=1,ox=0,oy=0,drag=null,px=0,py=0;
function resize(){W=canvas.width=innerWidth;H=canvas.height=innerHeight-document.getElementById('bar').offsetHeight;canvas.style.height=(H)+'px';}
addEventListener('resize',resize);resize();
const N=DATA.nodes, E=DATA.edges;
N.forEach((n,i)=>{n.x=Math.cos(i)*220+ (Math.random()-0.5)*80; n.y=Math.sin(i)*220+(Math.random()-0.5)*80; n.vx=0;n.vy=0;});
function tick(){
  const k=0.004, damp=0.86;
  for(let i=0;i<N.length;i++){
    for(let j=i+1;j<N.length;j++){
      let dx=N[j].x-N[i].x, dy=N[j].y-N[i].y;
      let d2=dx*dx+dy*dy+40;
      let f=180/d2;
      dx*=f; dy*=f;
      N[i].vx-=dx; N[i].vy-=dy; N[j].vx+=dx; N[j].vy+=dy;
    }
  }
  for(const e of E){
    const a=N[e.s], b=N[e.o];
    let dx=b.x-a.x, dy=b.y-a.y;
    a.vx+=dx*k; a.vy+=dy*k; b.vx-=dx*k; b.vy-=dy*k;
  }
  for(const n of N){
    n.vx+=(-n.x)*0.0008; n.vy+=(-n.y)*0.0008;
    n.vx*=damp; n.vy*=damp;
    if(n!==drag){n.x+=n.vx; n.y+=n.vy;}
  }
}
function toScreen(n){return [n.x*scale+W/2+ox, n.y*scale+H/2+oy];}
function draw(){
  ctx.clearRect(0,0,W,H);
  ctx.strokeStyle='#30363d'; ctx.lineWidth=0.6;
  for(const e of E){
    const a=toScreen(N[e.s]), b=toScreen(N[e.o]);
    ctx.beginPath(); ctx.moveTo(a[0],a[1]); ctx.lineTo(b[0],b[1]); ctx.stroke();
  }
  for(const n of N){
    const [x,y]=toScreen(n);
    const r=Math.min(9, 3+Math.sqrt(n.deg)*0.35);
    ctx.fillStyle=C[n.cluster]||C.other;
    ctx.beginPath(); ctx.arc(x,y,r,0,6.28); ctx.fill();
    if(scale>0.85 && (n.cluster!=='other' || n.deg>12)){
      ctx.fillStyle='#c9d1d9'; ctx.font='11px Segoe UI'; ctx.fillText(n.label, x+r+2, y+3);
    }
  }
}
let frames=0;
function loop(){ if(frames<420) tick(); frames++; draw(); requestAnimationFrame(loop);}
loop();
function hit(mx,my){
  for(let i=N.length-1;i>=0;i--){
    const [x,y]=toScreen(N[i]);
    const r=Math.min(12, 4+Math.sqrt(N[i].deg)*0.4)+4;
    if((mx-x)**2+(my-y)**2 < r*r) return N[i];
  }
  return null;
}
canvas.addEventListener('mousedown', e=>{
  const n=hit(e.offsetX,e.offsetY);
  if(n){drag=n; canvas.style.cursor='grabbing';}
  px=e.offsetX; py=e.offsetY;
});
addEventListener('mouseup', ()=>{drag=null; canvas.style.cursor='grab';});
canvas.addEventListener('mousemove', e=>{
  if(drag){
    drag.x += (e.offsetX-px)/scale; drag.y += (e.offsetY-py)/scale;
    drag.vx=0; drag.vy=0;
  } else if(e.buttons===1){
    ox += e.offsetX-px; oy += e.offsetY-py;
  }
  px=e.offsetX; py=e.offsetY;
  const n=hit(e.offsetX,e.offsetY);
  if(n){
    tip.style.display='block'; tip.style.left=(e.clientX+12)+'px'; tip.style.top=(e.clientY+12)+'px';
    tip.innerHTML='<b>'+n.full.replace(/[<>]/g,'')+'</b><br>cluster '+n.cluster+' · degree '+n.deg;
  } else tip.style.display='none';
});
canvas.addEventListener('wheel', e=>{
  e.preventDefault();
  const f=e.deltaY<0?1.12:0.9;
  scale=Math.min(4, Math.max(0.25, scale*f));
},{passive:false});
</script>
</body></html>
"""


def main() -> int:
    nodes, edges, meta = load()
    payload = {"meta": meta, "nodes": nodes, "edges": edges}
    js = "const DATA=" + json.dumps(payload, ensure_ascii=False) + ";\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HTML_HEAD + js + HTML_TAIL, encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), **meta, "bytes": OUT.stat().st_size}, indent=2))
    return 0 if nodes else 1


if __name__ == "__main__":
    raise SystemExit(main())
