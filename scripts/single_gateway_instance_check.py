#!/usr/bin/env python3
"""Single gateway instance soft-fail check (measure-only).

True double-boot signal = >1 distinct LISTENING PID on :8642.
Parent+child pythonw re-exec with one listener = OK (one instance).

Contract (Residual Hygiene soft-fail seal 2026-07-18):
- Always write receipt JSON.
- Exit 0 when job ran and left evidence (ok / partial / multi_listener advisory).
- Exit 1 only for misconfig (netstat/cmd unusable AND no health path at all is not hard —
  still soft). Hard-fail reserved if script itself cannot write receipt path parent.
- Non-empty stdout only when not clean single-instance healthy (cron alert).
- Never kills, never restarts. Heal authority stays stack_healing_once / Phronesis.ps1.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PORT = 8642
HEALTH_URL = f"http://127.0.0.1:{PORT}/health"
SEAL = "2026-07-18-single-gateway-soft-fail"
RECEIPT_DIR = Path(r"D:\PhronesisVault\Operations\logs")
RECEIPT = RECEIPT_DIR / "single-gateway-instance-latest.json"
JSONL = Path(r"D:\HermesData\logs\single-gateway-instance-check.jsonl")
HERMES_HOME = Path(r"D:\HermesData")


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def listeners_on_port(port: int = PORT) -> list[int]:
    pids: set[int] = set()
    try:
        r = subprocess.run(
            ["cmd.exe", "/c", f"netstat -ano | findstr :{port}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for line in (r.stdout or "").splitlines():
            if "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if len(parts) >= 5:
                try:
                    pid = int(parts[-1])
                    if pid > 4:
                        pids.add(pid)
                except ValueError:
                    pass
    except Exception:
        pass
    return sorted(pids)


def health_probe(timeout: float = 3.0) -> dict:
    try:
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = (resp.read() or b"")[:400].decode("utf-8", errors="replace")
            return {"up": 200 <= int(resp.status) < 300, "status": int(resp.status), "body_head": body}
    except urllib.error.HTTPError as e:
        return {"up": False, "status": int(getattr(e, "code", 0) or 0), "error": str(e)}
    except Exception as e:
        return {"up": False, "status": None, "error": f"{type(e).__name__}:{e}"}


def read_claimed_pid() -> int | None:
    for path in (HERMES_HOME / "gateway.pid", HERMES_HOME / "gateway" / "gateway.pid"):
        try:
            if path.is_file():
                raw = path.read_text(encoding="utf-8", errors="replace").strip()
                if raw.isdigit():
                    return int(raw)
        except Exception:
            continue
    return None


def write_receipt(payload: dict) -> None:
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    JSONL.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2) + "\n"
    tmp = RECEIPT.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(RECEIPT)
    with JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")


def main() -> int:
    try:
        listeners = listeners_on_port()
        health = health_probe()
        claimed = read_claimed_pid()
        n = len(listeners)
        multi = n > 1
        single_ok = n == 1 and bool(health.get("up"))
        down = n == 0 or not health.get("up")

        if single_ok:
            status = "ok"
            ok = True
            partial = False
            soft_fail = False
            reason = "single_listener_healthy"
        elif multi and health.get("up"):
            status = "multi_listener"
            ok = False
            partial = True
            soft_fail = True
            reason = "multi_LISTEN_on_8642_while_health_up"
        elif multi and not health.get("up"):
            status = "multi_listener_unhealthy"
            ok = False
            partial = True
            soft_fail = True
            reason = "multi_LISTEN_and_health_down"
        elif down:
            status = "down"
            ok = False
            partial = True
            soft_fail = True
            reason = "no_healthy_single_listener"
        else:
            status = "unknown"
            ok = False
            partial = True
            soft_fail = True
            reason = "probe_inconclusive"

        payload = {
            "at": _iso(),
            "ok": ok,
            "partial": partial,
            "soft_fail": soft_fail,
            "seal": SEAL,
            "status": status,
            "reason": reason,
            "port": PORT,
            "listener_count": n,
            "listeners": listeners,
            "multi_listener": multi,
            "health": health,
            "claimed_pid": claimed,
            "policy": {
                "true_double_boot": "multiple distinct LISTENING PIDs on :8642",
                "heal_authority": "stack_healing_once / Phronesis.ps1 gateway start",
                "this_job": "measure-only; never kill/restart",
                "doc": "Operations/SINGLE-GATEWAY-RESTORE.md",
            },
            "receipt": str(RECEIPT),
        }
        write_receipt(payload)

        # Silent when clean single instance (no_agent empty = no spam)
        if single_ok:
            return 0

        print(
            f"SingleGateway status={status} listeners={n} pids={listeners} "
            f"health_up={bool(health.get('up'))} soft_fail=1 receipt={RECEIPT}"
        )
        print(json.dumps(payload, indent=2))
        return 0
    except Exception as e:
        # Last resort: try minimal receipt, still soft if possible
        err_payload = {
            "at": _iso(),
            "ok": False,
            "partial": True,
            "soft_fail": True,
            "seal": SEAL,
            "status": "error",
            "reason": f"{type(e).__name__}:{e}",
            "receipt": str(RECEIPT),
        }
        try:
            write_receipt(err_payload)
            print(f"SingleGateway status=error soft_fail=1 receipt={RECEIPT} err={e}")
            return 0
        except Exception as e2:
            print(f"SingleGateway FAIL cannot_write_receipt err={e} write_err={e2}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
