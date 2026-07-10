#!/usr/bin/env python3
"""Whitelisted local ops for Grok Discord bridge — fixes stack without Hermes narration."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\HermesData")
INBOX_FILE = ROOT / "state" / "grok-inbox.json"
VENV_PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"
PWSH = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")

OPS: dict[str, dict] = {
    "health": {
        "script": ROOT / "scripts" / "phronesis_fullstack_health.py",
        "kind": "python",
        "timeout": 60,
        "summary": "Full stack health JSON",
    },
    "heal": {
        "script": ROOT / "scripts" / "Phronesis-Heal.ps1",
        "kind": "powershell",
        "args": ["-Quiet"],
        "timeout": 300,
        "summary": "Phronesis-Heal stack recovery",
    },
    "restart_bridge": {
        "script": ROOT / "scripts" / "ops" / "Ensure-Grok-Direct-Bridge.ps1",
        "kind": "powershell",
        "args": ["-Restart", "-Quiet"],
        "timeout": 120,
        "summary": "Restart Grok direct Discord bridge",
    },
    "restart_proxy": {
        "script": ROOT / "scripts" / "Start-Sovereign-Proxy-8091.ps1",
        "kind": "powershell",
        "args": ["-Force"],
        "timeout": 120,
        "summary": "Restart sovereign proxy :8091",
    },
    "drain_inbox": {
        "script": ROOT / "scripts" / "grok_inbox_consumer.py",
        "kind": "python",
        "args": ["--once"],
        "timeout": 720,
        "summary": "Drain one Hermes inbox item",
    },
    "drain_all": {
        "script": ROOT / "scripts" / "grok_inbox_consumer.py",
        "kind": "python",
        "args": ["--drain-all"],
        "timeout": 3600,
        "summary": "Drain up to 5 Hermes inbox items",
    },
    "inbox_status": {
        "kind": "builtin",
        "summary": "Inbox pending/done/failed counts",
    },
    "queue_status": {
        "kind": "builtin",
        "summary": "Qwythos FIFO lane depths, active job, ETA",
    },
}

# Jeff mobile verbs → ops (first match wins)
USER_OP_PATTERNS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"\b(?:full\s+)?(?:stack\s+)?health\b|\bhealth\s+check\b|\bstatus\s+check\b", re.I), ["health", "queue_status", "inbox_status"]),
    (re.compile(r"\bqueue\s+status\b|\bfifo\s+status\b|\bmodel\s+queue\b|\bwaiting\s+for\s+model\b", re.I), ["queue_status"]),
    (re.compile(r"\bheal\s+(?:stack|now|everything)\b|\bphronesis\s+heal\b|\bfix\s+(?:stack|everything|it\s+now)\b", re.I), ["heal", "health"]),
    (re.compile(r"\brestart\s+bridge\b|\bfix\s+bridge\b|\bbridge\s+down\b", re.I), ["restart_bridge", "health"]),
    (re.compile(r"\brestart\s+proxy\b|\bfix\s+proxy\b|\bproxy\s+down\b", re.I), ["restart_proxy", "health"]),
    (re.compile(r"\bdrain\s+inbox\b|\bprocess\s+inbox\b|\bqueue\s+now\b", re.I), ["drain_inbox", "inbox_status"]),
    (re.compile(r"\btell\s+hermes\b|\btalk\s+to\s+hermes\b|\bhermes\s+fix\b|\bdrain\s+all\b", re.I), ["drain_all", "inbox_status"]),
    (re.compile(r"\b(?:ops|e2e)\s+(?:review|audit|check)\b|\bam\s+i\s+operational\b", re.I), ["health", "inbox_status", "heal"]),
]

GROK_OPS_TAG = re.compile(r"\bBRIDGE_OPS:\s*([a-z0-9_,\s]+)", re.I)


def _load_inbox() -> dict:
    if not INBOX_FILE.is_file():
        return {"items": []}
    try:
        return json.loads(INBOX_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"items": []}


def queue_status_text() -> str:
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:8091/v1/queue", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return f"fifo: unreachable ({exc})"
    lanes = data.get("fifo_lanes") or {}
    rp = int((lanes.get("roleplay") or {}).get("count") or 0)
    norm = int((lanes.get("normal") or {}).get("count") or 0)
    active = data.get("active")
    avg = data.get("avg_latency_sec")
    parts = [f"fifo: roleplay={rp} normal={norm}"]
    if active:
        run = active.get("run_so_far_sec") or active.get("wait_sec") or "?"
        parts.append(
            f"active={active.get('caller', '?')} model={active.get('model', '?')} run={run}s"
        )
    if avg is not None:
        parts.append(f"avg_gen={avg}s")
    if rp + norm > 0 and avg:
        parts.append(f"eta_backlog~{int((rp + norm) * float(avg))}s")
    heals = (data.get("stats") or {}).get("total_heals")
    if heals:
        parts.append(f"heals={heals}")
    return " | ".join(parts)


def inbox_status_text() -> str:
    inbox = _load_inbox()
    items = inbox.get("items") or []
    counts: dict[str, int] = {}
    for item in items:
        st = str(item.get("status") or "unknown")
        counts[st] = counts.get(st, 0) + 1
    pending = counts.get("pending", 0)
    parts = [f"pending={pending}"]
    for key in ("running", "done", "failed", "cancelled"):
        if counts.get(key):
            parts.append(f"{key}={counts[key]}")
    return "inbox: " + ", ".join(parts)


def _run_python(script: Path, args: list[str], timeout: int) -> tuple[int, str]:
    py = str(VENV_PY if VENV_PY.is_file() else sys.executable)
    proc = subprocess.run(
        [py, str(script), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(ROOT),
    )
    out = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, out[:1500]


def _run_powershell(script: Path, args: list[str], timeout: int) -> tuple[int, str]:
    cmd = [str(PWSH), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    out = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, out[:1500]


def run_op(name: str) -> dict:
    spec = OPS.get(name)
    if not spec:
        return {"op": name, "ok": False, "error": "unknown_op"}

    if spec.get("kind") == "builtin":
        if name == "inbox_status":
            text = inbox_status_text()
            return {"op": name, "ok": True, "output": text}
        if name == "queue_status":
            text = queue_status_text()
            return {
                "op": name,
                "ok": not text.startswith("fifo: unreachable"),
                "output": text,
            }
        return {"op": name, "ok": False, "error": "unknown_builtin"}

    script = spec.get("script")
    if not script or not Path(script).is_file():
        return {"op": name, "ok": False, "error": f"missing_script:{script}"}

    kind = spec.get("kind")
    args = list(spec.get("args") or [])
    timeout = int(spec.get("timeout") or 120)
    try:
        if kind == "python":
            code, out = _run_python(Path(script), args, timeout)
        elif kind == "powershell":
            code, out = _run_powershell(Path(script), args, timeout)
        else:
            return {"op": name, "ok": False, "error": f"bad_kind:{kind}"}
    except subprocess.TimeoutExpired:
        return {"op": name, "ok": False, "error": "timeout"}
    except Exception as exc:
        return {"op": name, "ok": False, "error": str(exc)[:200]}

    ok = code == 0
    if name == "health" and out:
        try:
            data = json.loads(out.splitlines()[-1] if "\n" in out else out)
            ok = data.get("status") in ("healthy", "degraded") or int(data.get("score") or 0) >= 60
            out = json.dumps(
                {
                    "status": data.get("status"),
                    "score": data.get("score"),
                    "bridge_ok": data.get("bridge_ok"),
                    "inbox_pending": data.get("inbox_pending"),
                }
            )
        except Exception:
            pass

    return {"op": name, "ok": ok, "exit_code": code, "output": out[:800]}


def detect_ops_from_user(text: str) -> list[str]:
    found: list[str] = []
    for pattern, ops in USER_OP_PATTERNS:
        if pattern.search(text or ""):
            for op in ops:
                if op not in found:
                    found.append(op)
    return found


def detect_ops_from_grok(reply: str) -> list[str]:
    ops: list[str] = []
    for match in GROK_OPS_TAG.finditer(reply or ""):
        for part in re.split(r"[\s,]+", match.group(1).strip().lower()):
            if part in OPS and part not in ops:
                ops.append(part)
    return ops


def run_ops(ops: list[str]) -> list[dict]:
    results: list[dict] = []
    for name in ops:
        results.append(run_op(name))
    return results


def format_ops_report(results: list[dict]) -> str:
    if not results:
        return ""
    lines = ["**🔧 Bridge local ops**"]
    for r in results:
        mark = "✅" if r.get("ok") else "🔴"
        op = r.get("op", "?")
        err = r.get("error")
        out = r.get("output")
        if err:
            lines.append(f"{mark} `{op}` — {err}")
        elif out:
            snippet = out.replace("\n", " ")[:220]
            lines.append(f"{mark} `{op}` — {snippet}")
        else:
            lines.append(f"{mark} `{op}` — done")
    return "\n".join(lines)[:1900]


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Grok bridge local ops")
    parser.add_argument("ops", nargs="*", help="Op names (health, heal, ...)")
    parser.add_argument("--detect", metavar="TEXT", help="Detect ops from user text")
    args = parser.parse_args()

    if args.detect:
        names = detect_ops_from_user(args.detect)
        print(json.dumps({"detected": names}))
        return 0

    names = args.ops or ["health", "inbox_status"]
    results = run_ops(names)
    print(format_ops_report(results))
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())