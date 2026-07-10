#!/usr/bin/env python3
"""Phase 8c holistic security audit -- Windows + Hermes ports (read-only)."""

from __future__ import annotations

import json
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

HERMES_ROOT = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
REPORT_PATH = VAULT / "Operations" / "logs" / "security-audit-home.json"

HERMES_PORTS = (8090, 8091, 8642, 9119, 3001, 8188)


def _probe_http(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return {"ok": True, "status": resp.status}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


def _windows_firewall_status() -> Dict[str, Any]:
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "show", "allprofiles", "state"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        text = (result.stdout or "") + (result.stderr or "")
        on = "ON" in text.upper()
        return {"ok": result.returncode == 0, "firewall_on": on, "snippet": text[:400]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_audit() -> Dict[str, Any]:
    probes: Dict[str, Any] = {}
    probes["llama"] = _probe_http("http://127.0.0.1:8090/health")
    probes["proxy"] = _probe_http("http://127.0.0.1:8091/health")
    probes["gateway"] = _probe_http("http://127.0.0.1:8642/health")
    probes["cli_dashboard"] = _probe_http("http://127.0.0.1:9119/api/status")
    probes["workspace"] = _probe_http("http://127.0.0.1:3001/api/auth-check")

    port_listeners = {str(p): _port_open(p) for p in HERMES_PORTS}
    fw = _windows_firewall_status()

    policy_path = VAULT / "docs" / "agent-coordination" / "holistic-security-policy.md"
    phase8_path = VAULT / "docs" / "agent-coordination" / "phase-8-side-projects.md"

    gaps: List[str] = []
    if not probes.get("cli_dashboard", {}).get("ok"):
        gaps.append("cli_dashboard_9119_down")
    if not probes.get("workspace", {}).get("ok"):
        gaps.append("workspace_3001_down")
    if not fw.get("firewall_on"):
        gaps.append("windows_firewall_not_on")

    core_ok = sum(1 for k in ("llama", "proxy", "gateway") if probes.get(k, {}).get("ok"))
    score = min(100, core_ok * 20 + (20 if probes.get("workspace", {}).get("ok") else 0)
                + (20 if probes.get("cli_dashboard", {}).get("ok") else 0))

    return {
        "module": "8c_holistic_security",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "status": "healthy" if score >= 80 else "degraded" if score >= 50 else "critical",
        "probes": probes,
        "port_listeners": port_listeners,
        "firewall": fw,
        "policy_exists": policy_path.is_file(),
        "phase8_spec_exists": phase8_path.is_file(),
        "gaps": gaps,
        "report_path": str(REPORT_PATH),
    }


def main() -> int:
    report = run_audit()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0 if report.get("status") != "critical" else 1


if __name__ == "__main__":
    raise SystemExit(main())