#!/usr/bin/env python3
"""Silent-green stack pulse: GREEN when healthy (quiet), YELLOW/RED when not.

Research (2026-07-18): silent-green when healthy; soft-fail + receipts; circuit breakers;
single-instance checks (TrueFoundry loop engineering / our Codifying-Loops map).

Combines:
- single_gateway_instance_check (measure-only)
- :8091 sovereign proxy health
- optional silo six_numbers (metrics only)

Never kills or restarts. Exit 0 on GREEN/YELLOW (job ran); exit 2 on RED misconfig hard;
exit 1 on RED down (alert-worthy).

Usage:
  python silent_green_pulse.py
  python silent_green_pulse.py --with-silo
  python silent_green_pulse.py --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
PY = sys.executable
VAULT = Path(r"D:\PhronesisVault\Operations\logs")
RECEIPT = VAULT / "silent-green-pulse-latest.json"
JSONL = ROOT / "logs" / "silent-green-pulse.jsonl"


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def probe(url: str, timeout: float = 3.0) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "silent-green/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = (resp.read() or b"")[:300].decode("utf-8", errors="replace")
            return {"up": 200 <= int(resp.status) < 300, "status": int(resp.status), "body": body}
    except Exception as e:
        return {"up": False, "status": None, "error": f"{type(e).__name__}:{e}"}


def run_single_gateway() -> dict:
    r = subprocess.run(
        [PY, str(SCRIPTS / "single_gateway_instance_check.py")],
        capture_output=True,
        text=True,
        timeout=45,
        cwd=str(SCRIPTS),
    )
    # Prefer receipt file
    rec = Path(r"D:\PhronesisVault\Operations\logs\single-gateway-instance-latest.json")
    if rec.is_file():
        try:
            data = json.loads(rec.read_text(encoding="utf-8"))
            data["_check_rc"] = r.returncode
            return data
        except Exception:
            pass
    return {
        "status": "unknown",
        "ok": r.returncode == 0,
        "stdout": (r.stdout or "")[:400],
        "stderr": (r.stderr or "")[:200],
        "_check_rc": r.returncode,
    }


def run_silo_six() -> dict:
    r = subprocess.run(
        [PY, str(SCRIPTS / "silo_discord_six_numbers.py")],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(SCRIPTS),
    )
    nums = {}
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if "=" in line and line[0:1].isdigit():
            # 1 registry_total=123
            parts = line.split()
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                    if v.isdigit():
                        nums[k] = int(v)
    return {"ok": r.returncode == 0, "nums": nums, "raw_head": (r.stdout or "")[:300]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-silo", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    gw = run_single_gateway()
    p8091 = probe("http://127.0.0.1:8091/health")
    p8090 = probe("http://127.0.0.1:8090/health")  # may 404 but port up varies
    # 8090 may only expose /v1/models
    if not p8090.get("up"):
        p8090 = probe("http://127.0.0.1:8090/v1/models")

    silo = run_silo_six() if args.with_silo else None

    gw_status = (gw.get("status") or "").lower()
    gw_ok = bool(gw.get("ok")) or gw_status == "ok"
    multi = "multi" in gw_status

    if gw_ok and p8091.get("up") and not multi:
        color = "GREEN"
        summary = "silent-green: gateway single + 8091 up"
    elif multi or (not gw_ok and p8091.get("up")):
        color = "YELLOW"
        summary = "advisory: multi-listener or gateway soft issue; 8091 may still serve"
    else:
        color = "RED"
        summary = "down: gateway and/or 8091 unhealthy"

    payload = {
        "ts": utc(),
        "color": color,
        "summary": summary,
        "gateway": {
            "status": gw.get("status"),
            "ok": gw.get("ok"),
            "reason": gw.get("reason"),
            "listeners": gw.get("listeners") or gw.get("listener_pids"),
        },
        "proxy_8091": p8091,
        "llama_8090": p8090,
        "silo": silo,
        "actions": {
            "GREEN": "none (silent)",
            "YELLOW": "receipt only; heal authority = stack_healing / service loop",
            "RED": "alert; do not dual-start; use Phronesis gateway service restore",
        },
        "never": ["taskkill gateway from Discord", "clear STOP without Jeff", "invent KPIs"],
    }

    VAULT.mkdir(parents=True, exist_ok=True)
    JSONL.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"{color} | {summary}")
        print(f"  gateway={gw.get('status')} 8091_up={p8091.get('up')} 8090_up={p8090.get('up')}")
        if silo and silo.get("nums"):
            n = silo["nums"]
            print(
                f"  silo registry={n.get('registry_total')} landed={n.get('status_landed')} "
                f"ocr_open={n.get('ocr_open')}"
            )
        print(f"  receipt={RECEIPT}")

    if color == "GREEN":
        return 0
    if color == "YELLOW":
        return 0  # soft-fail seal: job succeeded with advisory
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
