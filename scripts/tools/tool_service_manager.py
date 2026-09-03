#!/usr/bin/env python3
"""Safe query/restart wrapper for local daemons. JSON stdout only.

Never restarts llama-server :8090. Restart requires confirm=true.
Targets: gateway :8642, proxy :8091, optional hybrid :8092, Ollama :11434.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.request
from typing import Any, Dict, List

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

TARGETS = {
    "gateway": {"port": 8642, "label": "gateway", "health": "http://127.0.0.1:8642/health"},
    "8642": {"port": 8642, "label": "gateway", "health": "http://127.0.0.1:8642/health"},
    "proxy": {"port": 8091, "label": "proxy", "health": "http://127.0.0.1:8091/health"},
    "8091": {"port": 8091, "label": "proxy", "health": "http://127.0.0.1:8091/health"},
    "8092": {"port": 8092, "label": "hybrid", "health": "http://127.0.0.1:8092/health"},
    "ollama": {"port": 11434, "label": "ollama", "health": "http://127.0.0.1:11434/api/tags"},
    "11434": {"port": 11434, "label": "ollama", "health": "http://127.0.0.1:11434/api/tags"},
    "brain": {"port": 8090, "label": "llama", "health": "http://127.0.0.1:8090/health"},
    "8090": {"port": 8090, "label": "llama", "health": "http://127.0.0.1:8090/health"},
}

RESTARTABLE = {"gateway", "proxy", "ollama"}
NEVER_RESTART = {"llama", "brain", "hybrid"}


def _parse_args(argv: List[str] | None = None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_blob", default="")
    ap.add_argument("--action", default="status")
    ap.add_argument("--target", default="all")
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args(argv)
    payload: Dict[str, Any] = {}
    if args.json_blob:
        raw = args.json_blob
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}
    payload.setdefault("action", args.action)
    payload.setdefault("target", args.target)
    if args.confirm:
        payload["confirm"] = True
    return payload


def _port_open(port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _http(url: str, timeout: float = 2.5) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()[:240].decode("utf-8", "replace")
            return {"up": r.status == 200, "status": r.status, "body": body}
    except Exception as exc:
        return {"up": False, "error": str(exc)[:160]}


def _probe(spec: Dict[str, Any]) -> Dict[str, Any]:
    port = int(spec["port"])
    health = _http(spec["health"])
    return {
        "label": spec["label"],
        "port": port,
        "listen": _port_open(port),
        "health": health,
        "ok": bool(health.get("up")),
    }


def _status(target: str) -> Dict[str, Any]:
    key = (target or "all").strip().lower()
    if key in ("all", "*", ""):
        keys = ["gateway", "proxy", "8092", "ollama", "brain"]
    else:
        if key not in TARGETS:
            return {"ok": False, "error": f"unknown_target:{key}"}
        keys = [key]
    services = [_probe(TARGETS[k]) for k in keys]
    return {
        "ok": True,
        "action": "status",
        "services": services,
        "law": [
            "never_restart_8090",
            "restart_requires_confirm",
            "no_sat_heal",
            "no_hybrid_start",
        ],
    }


def _run(cmd: List[str], timeout: int = 90) -> Dict[str, Any]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return {
            "rc": p.returncode,
            "stdout_tail": (p.stdout or "")[-400:],
            "stderr_tail": (p.stderr or "")[-200:],
        }
    except Exception as exc:
        return {"rc": -1, "error": str(exc)[:200]}


def _restart(target: str) -> Dict[str, Any]:
    key = (target or "").strip().lower()
    spec = TARGETS.get(key)
    if not spec:
        return {"ok": False, "error": f"unknown_target:{key}"}
    label = spec["label"]
    if label in NEVER_RESTART or key in ("8090", "brain", "8092"):
        return {
            "ok": False,
            "error": "restart_refused",
            "reason": "never_restart_8090_or_start_hybrid_14b",
            "target": label,
            "status": _probe(spec),
        }
    if label not in RESTARTABLE:
        return {"ok": False, "error": "restart_not_allowed", "target": label}

    if label == "proxy":
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            r"D:\HermesData\scripts\Start-Sovereign-Proxy-8091.ps1",
            "-Force",
        ]
        ran = _run(cmd, timeout=90)
        time.sleep(1.5)
        after = _probe(spec)
        return {"ok": bool(after.get("ok")), "action": "restart", "target": "proxy", "ran": ran, "after": after}

    if label == "gateway":
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            r"D:\HermesData\scripts\Ensure-HermesStack-Single.ps1",
            "-Recycle",
        ]
        ran = _run(cmd, timeout=120)
        time.sleep(1.0)
        after = _probe(spec)
        return {"ok": bool(after.get("ok")), "action": "restart", "target": "gateway", "ran": ran, "after": after}

    if label == "ollama":
        # Recycle the listener only if already running. Do not SAT --heal.
        before = _probe(spec)
        if not before.get("listen"):
            return {"ok": False, "error": "ollama_not_running", "before": before}
        _run(["taskkill", "/IM", "ollama.exe", "/F"], timeout=20)
        time.sleep(1.0)
        ollama = shutil_which_ollama()
        if ollama:
            subprocess.Popen(
                [ollama, "serve"],
                cwd=r"D:\HermesData",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW | 0x00000008 | 0x00000200,
            )
        deadline = time.time() + 20
        after = _probe(spec)
        while time.time() < deadline and not after.get("ok"):
            time.sleep(1.0)
            after = _probe(spec)
        return {"ok": bool(after.get("ok")), "action": "restart", "target": "ollama", "after": after}

    return {"ok": False, "error": "unhandled_target", "target": label}


def shutil_which_ollama() -> str | None:
    import shutil

    return shutil.which("ollama") or shutil.which("ollama.exe")


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    action = str(payload.get("action") or "status").strip().lower()
    target = str(payload.get("target") or "all").strip().lower()
    confirm = payload.get("confirm") in (True, "true", "1", 1, "yes")
    if action in ("", "status", "query", "health"):
        return _status(target)
    if action in ("restart", "recycle", "reload"):
        if not confirm:
            return {
                "ok": False,
                "error": "restart_requires_confirm_true",
                "hint": "Call again with confirm=true. :8090 is never restarted.",
                "status": _status(target),
            }
        if target in ("all", "*", ""):
            return {"ok": False, "error": "restart_all_refused", "hint": "Pick one target."}
        return _restart(target)
    return {"ok": False, "error": f"unknown_action:{action}"}


def main() -> int:
    doc = run(_parse_args())
    print(json.dumps(doc, ensure_ascii=False))
    return 0 if doc.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
