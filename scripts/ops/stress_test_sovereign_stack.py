#!/usr/bin/env python3
"""15-turn FIFO / VRAM / trim / drop probe against :8091/:8090. No SAT heal.

  python D:\\HermesData\\scripts\\ops\\stress_test_sovereign_stack.py
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(r"D:\HermesData\state")
OUT_MD = STATE / "stress_test_report_latest.md"
OUT_JSON = STATE / "stress_test_report_latest.json"
PROXY = "http://127.0.0.1:8091/v1/chat/completions"
VRAM_CAP_GB = 11.2
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

TURNS = [
    ("banter1", "Say one word: GREEN.", False),
    ("tool_tel", "Call system_telemetry. No prose.", True),
    ("banter2", "One short beat: still here.", False),
    ("tool_v", "vault_search query Booksbloom roots vault max_hits 3. Tool only.", True),
    ("banter3", "Ack.", False),
    ("tool_svc", "service_manager action status target all. Tool only.", True),
    ("banter4", "ok", False),
    ("tool_date", "terminal Get-Date. Tool only.", True),
    ("banter5", "copy.", False),
    ("tool_v2", "vault_search query FLL roots vault. Tool only.", True),
    ("banter6", "still green?", False),
    ("tool_tel2", "system_telemetry. Tool only.", True),
    ("banter7", "one word.", False),
    ("tool_svc2", "service_manager status 8090. Tool only.", True),
    ("banter8", "done.", False),
]


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def vram() -> dict:
    try:
        p = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,memory.free,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        parts = [x.strip() for x in (p.stdout or "").split(",") if x.strip()]
        used = float(parts[0]) / 1024.0
        total = float(parts[1]) / 1024.0
        return {"ok": True, "used_gb": round(used, 3), "total_gb": round(total, 2), "temp_c": float(parts[3]) if len(parts) > 3 else None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


def fifo() -> dict:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8091/health", timeout=3) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        q = d.get("inference_queue") or {}
        return {"waiting": q.get("waiting_count"), "active": q.get("active"), "ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


def post(user: str, tools: bool, timeout: int = 90) -> dict:
    body = {
        "model": "phronesis-sovereign-auto",
        "messages": [
            {"role": "system", "content": "Do NOT describe tool use in prose. Short answers."},
            {"role": "user", "content": user},
        ],
        "max_tokens": 96 if not tools else 192,
        "temperature": 0.2,
        "stream": False,
    }
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "system_telemetry",
                    "description": "CPU RAM VRAM drives",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "vault_search",
                    "description": "Search vault",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}, "roots": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "service_manager",
                    "description": "Local daemon status",
                    "parameters": {
                        "type": "object",
                        "properties": {"action": {"type": "string"}, "target": {"type": "string"}},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "terminal",
                    "description": "Shell",
                    "parameters": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                        "required": ["command"],
                    },
                },
            },
        ]
        body["tool_choice"] = "auto"
    t0 = time.perf_counter()
    req = urllib.request.Request(
        PROXY,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        dt = time.perf_counter() - t0
        msg = ((data.get("choices") or [{}])[0].get("message") or {})
        return {
            "ok": True,
            "sec": round(dt, 3),
            "finish": ((data.get("choices") or [{}])[0].get("finish_reason")),
            "has_tools": bool(msg.get("tool_calls")),
            "names": [(tc.get("function") or {}).get("name") for tc in (msg.get("tool_calls") or [])][:4],
        }
    except Exception as exc:
        return {"ok": False, "sec": round(time.perf_counter() - t0, 3), "error": str(exc)[:180]}


def trim_probe() -> dict:
    pad = "FOUR WORLDS " * 4000
    body = {
        "model": "phronesis-sovereign-auto",
        "messages": [
            {"role": "system", "content": pad},
            {"role": "user", "content": "Reply with the single word TRIMMED."},
        ],
        "max_tokens": 16,
        "temperature": 0,
    }
    t0 = time.perf_counter()
    req = urllib.request.Request(
        PROXY,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        dt = time.perf_counter() - t0
        txt = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        return {"ok": True, "sec": round(dt, 3), "http": 200, "reply_prefix": txt[:80]}
    except urllib.error.HTTPError as e:
        return {"ok": e.code in (200, 400), "http": e.code, "sec": round(time.perf_counter() - t0, 3), "note": "trim_or_reject"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def drop_probe() -> dict:
    try:
        s = socket.create_connection(("127.0.0.1", 8091), timeout=3)
        s.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 99999\r\n\r\n{")
        s.close()
        time.sleep(0.4)
        with urllib.request.urlopen("http://127.0.0.1:8091/health", timeout=3) as r:
            return {"ok": r.status == 200, "proxy_after": r.status}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def main() -> int:
    v0 = vram()
    f0 = fifo()
    rows = []
    vram_series = [v0]
    abort = False
    for i, (tid, user, tools) in enumerate(TURNS, 1):
        rec = post(user, tools)
        rec["id"] = tid
        rec["i"] = i
        rec["fifo"] = fifo()
        rec["vram"] = vram()
        rows.append(rec)
        vram_series.append(rec["vram"])
        used = (rec["vram"] or {}).get("used_gb")
        if isinstance(used, (int, float)) and used > VRAM_CAP_GB:
            abort = True
            rec["abort"] = "vram_cap"
            break
        time.sleep(0.15)
    trim = trim_probe()
    drop = drop_probe()
    v1 = vram()
    used_vals = [r.get("used_gb") for r in vram_series if isinstance(r, dict) and isinstance(r.get("used_gb"), (int, float))]
    ok_n = sum(1 for r in rows if r.get("ok"))
    lat = [r["sec"] for r in rows if r.get("ok")]
    doc = {
        "ts": utc(),
        "turns_ok": ok_n,
        "turns_n": len(rows),
        "abort_vram": abort,
        "latency_s": {"n": len(lat), "max": max(lat) if lat else None, "mean": round(sum(lat) / len(lat), 3) if lat else None},
        "vram_start_gb": v0.get("used_gb"),
        "vram_end_gb": v1.get("used_gb"),
        "vram_max_gb": max(used_vals) if used_vals else None,
        "vram_cap_gb": VRAM_CAP_GB,
        "vram_stable": (max(used_vals) <= VRAM_CAP_GB) if used_vals else False,
        "fifo_start": f0,
        "trim": trim,
        "drop_recovery": drop,
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    md = [
        "# Sovereign stack stress test",
        "",
        f"stamped={doc['ts']}",
        f"turns {doc['turns_ok']}/{doc['turns_n']} ok",
        f"latency mean={doc['latency_s']['mean']}s max={doc['latency_s']['max']}s",
        f"VRAM start={doc['vram_start_gb']} end={doc['vram_end_gb']} max={doc['vram_max_gb']} cap={VRAM_CAP_GB} stable={doc['vram_stable']}",
        f"trim_ok={trim.get('ok')} drop_proxy_after={drop.get('proxy_after') or drop.get('ok')}",
        f"abort_vram={abort}",
        "",
    ]
    for r in rows:
        md.append(f"- {r.get('i')} {r.get('id')} ok={r.get('ok')} {r.get('sec')}s tools={r.get('names')} finish={r.get('finish')}")
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"STRESS ok={doc['turns_ok']}/{doc['turns_n']} vram_max={doc['vram_max_gb']} stable={doc['vram_stable']}")
    print("WROTE", OUT_MD)
    return 0 if doc["turns_ok"] >= 10 and doc["vram_stable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
