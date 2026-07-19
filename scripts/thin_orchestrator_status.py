#!/usr/bin/env python3
"""Thin orchestrator status — one script call for stack+gardener+insights pointers.

Grok/Hermes should prefer this single call over multi-tool spam.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")


def port_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as r:
                return True
        except Exception:
            return False


def main() -> int:
    # Inference is :8188; :8189 is gallery SPA only (HTML 200 ≠ Comfy API).
    ports = {
        8090: "qwythos",
        8091: "proxy",
        8642: "gateway",
        8188: "comfy",
        8189: "gallery",
    }
    # gateway may not have /health
    status = {}
    for port, name in ports.items():
        if port == 8642:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as r:
                    status[name] = "UP"
            except Exception:
                # try TCP-ish via health scripts — simple connect
                import socket
                s = socket.socket()
                s.settimeout(1.5)
                try:
                    s.connect(("127.0.0.1", port))
                    status[name] = "UP"
                except Exception:
                    status[name] = "DOWN"
                finally:
                    s.close()
        else:
            status[name] = "UP" if port_ok(port) else "DOWN"

    pointers = {
        "phase_b": str(VAULT / "Operations" / "logs" / "gardener-phase-b-latest.md"),
        "vaultwalker_feedback": str(VAULT / "Operations" / "logs" / "vaultwalker-feedback-latest.md"),
        "insights_lessons": str(VAULT / "Operations" / "logs" / "insights-lessons-latest.md"),
        "grand_vision": str(VAULT / "Operations" / "Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10.md"),
        "autonomy_path": str(VAULT / "Operations" / "Autonomy-Pathway-Dreamer-Worker-2026-07-10.md"),
        "home_parked": str(VAULT / "Operations" / "Home-When-Back-RDP-Recycle-Parked-2026-07-10.md"),
    }
    existing = {k: Path(v).exists() for k, v in pointers.items()}
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ports": status,
        "pointers": pointers,
        "exists": existing,
        "orchestrator_hint": "Grok plans; scripts/grunt execute; read phase_b for next human gates",
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
