#!/usr/bin/env python3
"""CPU, 128GB RAM, RTX 3060 VRAM, drive capacities. JSON stdout only."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _parse_args(argv: List[str] | None = None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_blob", default="")
    ap.add_argument("--include-top-procs", action="store_true")
    args = ap.parse_args(argv)
    payload: Dict[str, Any] = {}
    if args.json_blob:
        try:
            loaded = json.loads(args.json_blob)
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}
    if args.include_top_procs:
        payload["include_top_procs"] = True
    return payload


def _drives() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for letter in ("C", "D", "K"):
        root = f"{letter}:\\"
        try:
            u = shutil.disk_usage(root)
            free_gb = round(u.free / (1024**3), 2)
            total_gb = round(u.total / (1024**3), 2)
            used_gb = round(u.used / (1024**3), 2)
            rec: Dict[str, Any] = {
                "total_gb": total_gb,
                "used_gb": used_gb,
                "free_gb": free_gb,
                "used_pct": round(100.0 * u.used / u.total, 1) if u.total else None,
            }
            if letter == "C":
                rec["watch"] = "C_FREE_CRIT" if free_gb < 12 else ("C_FREE_LOW" if free_gb < 26 else "ok")
            out[letter] = rec
        except OSError as exc:
            out[letter] = {"error": str(exc)[:120]}
    return out


def _cpu_ram() -> Dict[str, Any]:
    try:
        import psutil
    except Exception:
        psutil = None  # type: ignore
    doc: Dict[str, Any] = {}
    if psutil:
        vm = psutil.virtual_memory()
        doc["cpu"] = {
            "logical": psutil.cpu_count(logical=True),
            "physical": psutil.cpu_count(logical=False),
            "percent": psutil.cpu_percent(interval=0.2),
        }
        doc["ram"] = {
            "total_gb": round(vm.total / (1024**3), 2),
            "used_gb": round(vm.used / (1024**3), 2),
            "available_gb": round(vm.available / (1024**3), 2),
            "percent": vm.percent,
            "expected_installed_gb": 128,
        }
    else:
        doc["cpu"] = {"logical": None, "error": "psutil_missing"}
        doc["ram"] = {"expected_installed_gb": 128, "error": "psutil_missing"}
    return doc


def _vram() -> Dict[str, Any]:
    smi = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    try:
        p = subprocess.run(
            [
                smi,
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
        line = (p.stdout or "").strip().splitlines()[0] if p.returncode == 0 else ""
        if not line:
            return {"ok": False, "error": (p.stderr or "nvidia-smi_empty")[:160]}
        parts = [x.strip() for x in line.split(",")]
        total = float(parts[1]) if len(parts) > 1 else None
        used = float(parts[2]) if len(parts) > 2 else None
        free = float(parts[3]) if len(parts) > 3 else None
        return {
            "ok": True,
            "name": parts[0] if parts else "unknown",
            "vram_total_mb": total,
            "vram_used_mb": used,
            "vram_free_mb": free,
            "vram_total_gb": round(total / 1024, 2) if total is not None else None,
            "vram_used_gb": round(used / 1024, 2) if used is not None else None,
            "gpu_util_pct": float(parts[4]) if len(parts) > 4 else None,
            "temp_c": float(parts[5]) if len(parts) > 5 else None,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def _top_procs(n: int = 5) -> List[Dict[str, Any]]:
    try:
        import psutil
    except Exception:
        return []
    rows = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            rss = int(proc.info["memory_info"].rss)
            rows.append({"pid": proc.info["pid"], "name": proc.info["name"], "rss_gb": round(rss / (1024**3), 3)})
        except (psutil.Error, OSError, TypeError):
            continue
    rows.sort(key=lambda r: r["rss_gb"], reverse=True)
    return rows[:n]


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    host = _cpu_ram()
    doc: Dict[str, Any] = {
        "ok": True,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cpu": host.get("cpu"),
        "ram": host.get("ram"),
        "gpu": _vram(),
        "drives": _drives(),
    }
    if payload.get("include_top_procs") in (True, "true", "1", 1, "yes"):
        doc["top_procs"] = _top_procs()
    return doc


def main() -> int:
    doc = run(_parse_args())
    print(json.dumps(doc, ensure_ascii=False))
    return 0 if doc.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
