#!/usr/bin/env python3
"""Sovereign Dawn Pulse - script-only morning health snapshot (no LLM).

Replaces fragile agent cron that failed with RuntimeError: Connection error
when phronesis-sovereign was cold.

Stdout is the briefing (cron delivers when non-empty).
"""
from __future__ import annotations

import json
import socket
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PORTS = {
    8090: "Qwythos llama",
    8091: "proxy router",
    8189: "ComfyUI",
    8642: "Hermes gateway",
}
OUT_MD = Path(r"D:\PhronesisVault\Operations\logs\dawn-pulse-latest.md")
JSONL = Path(r"D:\PhronesisVault\Operations\logs\dawn-pulse.jsonl")


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_snippet(url: str, timeout: float = 2.0) -> str:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read(200).decode("utf-8", errors="replace")
            return f"HTTP {r.status} {body[:120]}"
    except Exception as e:
        return f"ERR {type(e).__name__}"


def gpu_line() -> str:
    try:
        import subprocess

        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=8,
        ).strip()
        return out or "nvidia-smi empty"
    except Exception as e:
        return f"GPU n/a ({type(e).__name__})"


def main() -> int:
    now = datetime.now(timezone.utc).astimezone()
    lines = [f"# Dawn Pulse {now.strftime('%Y-%m-%d %H:%M %Z')}", ""]
    port_rows = []
    for port, label in PORTS.items():
        ok = port_open(port)
        port_rows.append({"port": port, "label": label, "up": ok})
        lines.append(f"- Port **{port}** ({label}): {'UP' if ok else 'DOWN'}")

    lines.append(f"- Proxy health: {http_snippet('http://127.0.0.1:8091/health')}")
    lines.append(f"- Llama health: {http_snippet('http://127.0.0.1:8090/health')}")
    lines.append(f"- GPU: {gpu_line()}")

    # Zero-newline quick signal
    try:
        import subprocess, sys

        r = subprocess.run(
            [sys.executable, r"D:\HermesData\scripts\hygiene_zero_newline_scripts.py", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(r.stdout or "{}")
        lines.append(f"- Script newline integrity: corrupt={payload.get('corrupt_count', '?')}")
    except Exception as e:
        lines.append(f"- Script newline integrity: n/a ({type(e).__name__})")

    lines.append("")
    lines.append("Hybrid: Grok drives chat; Qwythos grunts via :8091 / grunt_local.py.")
    lines.append("Remote: Tailscale + RustDesk primary; RDP backup when enabled.")
    text = "\n".join(lines) + "\n"

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(text, encoding="utf-8", newline="\n")
    rec = {
        "ts": now.isoformat(),
        "ports": port_rows,
        "gpu": gpu_line(),
    }
    with JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
