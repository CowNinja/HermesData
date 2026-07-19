#!/usr/bin/env python3
"""One-shot stack snapshot for Discord Hermes (cuts tasklist storms).

Usage:
  python stack_snapshot.py
  python stack_snapshot.py --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from atomic_io import atomic_write_json

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
PY = sys.executable
VAULT = Path(r"D:\PhronesisVault\Operations\logs")
RECEIPT = VAULT / "stack-snapshot-latest.json"


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def probe(url: str, timeout: float = 2.5) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "stack-snapshot/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"up": 200 <= int(resp.status) < 300, "status": int(resp.status)}
    except Exception as e:
        return {"up": False, "error": type(e).__name__}


def count_cmd(substr: str) -> int:
    """Count python/pythonw processes whose CommandLine contains substr.

    Do not count bash/powershell agent shells that embed the marker in -c
    payloads (false dual-continuous noise — 2026-07-19).
    """
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "(Get-CimInstance Win32_Process | Where-Object { "
                    "$_.Name -like 'python*' -and "
                    f"$_.CommandLine -like '*{substr}*' "
                    "}).Count"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
        return int((r.stdout or "0").strip() or "0")
    except Exception:
        return -1


def last_json(path: Path) -> dict | None:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ports = {
        "8642": probe("http://127.0.0.1:8642/health"),
        "8091": probe("http://127.0.0.1:8091/health"),
        "8090": probe("http://127.0.0.1:8090/v1/models"),
        "9119": probe("http://127.0.0.1:9119"),
        "3001": probe("http://127.0.0.1:3001/"),
    }

    # Note: Windows venv pythonw re-exec → parent+child often yields ~2 PIDs per role.
    # Dual-writer risk is logical duplicates of continuous, not launcher pairs.
    writers = {
        "continuous": count_cmd("silo_continuous_loop"),
        "orchestrator": count_cmd("silo_orchestrator_tick"),
        "focus": count_cmd("silo_focus_land"),
        "drain": count_cmd("g_to_k_safe_drain"),
        "gateway_run": count_cmd("gateway.run"),
        "gateway_service": count_cmd("hermes_gateway_service"),
        "meta": count_cmd("hermes_meta_watchdog"),
        "note": "counts include venv launcher+child pairs; ~2 per role is normal",
    }

    green = last_json(VAULT / "silent-green-pulse-latest.json")
    intent = last_json(VAULT / "intent-queue-latest.json")
    voice = last_json(VAULT / "voice-truth-last.json")
    recovery = last_json(VAULT / "propose-recovery-latest.json")

    # quick six numbers if cheap
    six = {}
    try:
        r = subprocess.run(
            [PY, str(SCRIPTS / "silo_discord_six_numbers.py")],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(SCRIPTS),
        )
        for line in (r.stdout or "").splitlines():
            if "=" in line and line[:1].isdigit():
                for part in line.split():
                    if "=" in part:
                        k, v = part.split("=", 1)
                        if v.isdigit():
                            six[k] = int(v)
    except Exception as e:
        six = {"error": str(e)}

    payload = {
        "ts": utc(),
        "ports": ports,
        "process_counts": writers,
        "silent_green": {
            "color": (green or {}).get("color"),
            "summary": (green or {}).get("summary"),
        },
        "last_intent": {
            "id": (intent or {}).get("id"),
            "status": (intent or {}).get("status"),
            "text": ((intent or {}).get("text") or "")[:80],
        }
        if intent
        else None,
        "last_voice": {
            "path": ((voice or {}).get("audio") or {}).get("path"),
            "from_tool": (voice or {}).get("from_tool"),
        }
        if voice
        else None,
        "last_recovery_class": (recovery or {}).get("class"),
        "silo_six": six,
        "hints": [
            "Issues → python propose_recovery.py --symptom \"...\"",
            "Future actions → conversation_intent_queue.py propose",
            "Voice → voice_truth_speak.py --from-tool six_numbers|talk_to_jan",
        ],
    }

    VAULT.mkdir(parents=True, exist_ok=True)
    atomic_write_json(RECEIPT, payload, indent=2)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"stack_snapshot {payload['ts']}")
        for k, v in ports.items():
            print(f"  :{k} up={v.get('up')}")
        print(
            f"  writers cont={writers['continuous']} orch={writers['orchestrator']} "
            f"focus={writers['focus']} drain={writers['drain']}"
        )
        print(
            f"  gateway_run={writers['gateway_run']} service={writers['gateway_service']} meta={writers['meta']}"
        )
        print(f"  green={payload['silent_green']}")
        if six and "registry_total" in six:
            print(
                f"  silo reg={six.get('registry_total')} landed={six.get('status_landed')} "
                f"ocr_open={six.get('ocr_open')}"
            )
        if payload["last_intent"]:
            print(f"  intent={payload['last_intent']}")
        print(f"  receipt={RECEIPT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
