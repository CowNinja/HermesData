#!/usr/bin/env python3
"""Probe NetAlertX API -- Fing-style discovery service (optional Docker)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict


def _load_probe_url() -> str:
    path = Path(r"D:\HermesData\config\network_tools.yaml")
    if not path.is_file():
        return "http://127.0.0.1:20211"
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tools = (data.get("discovery") or {}).get("optional_tools") or []
        for tool in tools:
            if isinstance(tool, dict) and tool.get("id") == "netalertx":
                return str(tool.get("probe_url") or "http://127.0.0.1:20211").rstrip("/")
    except Exception:
        pass
    return "http://127.0.0.1:20211"


def probe_netalertx(timeout: float = 5.0) -> Dict[str, Any]:
    base = _load_probe_url()
    urls = [base, f"{base}/", f"{base}/api"]
    last_err = ""
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return {
                    "ok": True,
                    "status": resp.status,
                    "url": url,
                    "deployed": True,
                    "hint": "NetAlertX live -- import devices via API or UI",
                }
        except Exception as exc:
            last_err = str(exc)
    return {
        "ok": False,
        "deployed": False,
        "url": base,
        "error": last_err,
        "hint": "Deploy NetAlertX Docker on host network; see network-tools-research.md",
    }


def main() -> int:
    print(json.dumps(probe_netalertx()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())