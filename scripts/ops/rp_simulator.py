#!/usr/bin/env python3
"""RP Simulator - internal stack validation without Discord LLM loop."""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANDBOX_LIB = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\lib")
REPORT = ROOT / "logs" / "rp-simulator-report.json"
HEALTH = ROOT / "logs" / "wisdomvault-health.json"
COMFY_OUT = Path(r"D:\ComfyUI\output")

if str(SANDBOX_LIB) not in sys.path:
    sys.path.insert(0, str(SANDBOX_LIB))

from visual_registry import detect_image_intent  # noqa: E402

DEFAULT_CHANNEL = "1521146755985576116"

CANARY_PROMPTS = {
    "solo_explicit": (
        "OOC: nude alternate portrait alice, artistic, solo, full body, "
        "highly detailed nude, bare skin, no clothing, explicit"
    ),
    "group_arabian": (
        "OOC: three supermodel brunettes, darkly tanned, athletic voluptuous, "
        "wearing nothing, arabian women, group of three, highly detailed, artistic"
    ),
}


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def daemon_alive(lock_path: Path) -> bool:
    if not lock_path.is_file():
        return False
    try:
        pid = int(lock_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        import os

        os.kill(pid, 0)
        return True
    except OSError:
        return False


def load_health() -> dict | None:
    if not HEALTH.is_file():
        return None
    try:
        return json.loads(HEALTH.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None


def evaluate_intent(name: str, prompt: str) -> dict:
    spec = detect_image_intent(prompt, "", "")
    ok = spec is not None
    issues: list[str] = []
    if not ok:
        issues.append("no_image_intent")
    elif name == "group_arabian":
        mode = str(spec.get("mode") or "")
        scene = str(spec.get("scene") or spec.get("freeform_prompt") or "").lower()
        if mode not in ("group", "scene", "explicit", "freeform"):
            issues.append(f"unexpected_mode:{mode}")
        if "3girl" not in scene and "three" not in scene:
            issues.append("missing_group_count")
        if "arabian" not in scene and "levantine" not in scene:
            issues.append("missing_ethnicity_tags")
        if "nude" not in scene and "naked" not in scene and "no clothing" not in scene:
            issues.append("missing_nude_tags")
    elif name == "solo_explicit":
        if not spec.get("characters") and spec.get("reason") != "ooc_freeform":
            issues.append("missing_alice_cast")
    return {
        "prompt": prompt,
        "ok": ok and not issues,
        "spec": spec,
        "issues": issues,
    }


def latest_png() -> dict | None:
    files = sorted(COMFY_OUT.glob("standard__*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    p = files[0]
    return {"name": p.name, "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}


def run_render_test(prompt: str, channel: str) -> dict:
    bridge = ROOT / "scripts" / "ops" / "rp_bridge.py"
    py = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"
    if not bridge.is_file() or not py.is_file():
        return {"ok": False, "error": "bridge_or_python_missing"}
    import subprocess

    before = latest_png()
    t0 = time.time()
    proc = subprocess.run(
        [str(py), str(bridge), prompt, "--channel", channel],
        capture_output=True,
        text=True,
        timeout=1380,
    )
    elapsed = round(time.time() - t0, 1)
    result = None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                result = json.loads(line)
            except json.JSONDecodeError:
                pass
    after = latest_png()
    return {
        "ok": bool(result and result.get("ok")),
        "elapsed_s": elapsed,
        "result": result,
        "png_before": before,
        "png_after": after,
        "stderr": (proc.stderr or "")[-400:],
        "returncode": proc.returncode,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="RP internal simulator (no Discord agent)")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    parser.add_argument("--render", action="store_true", help="Run one live bridge render (slow)")
    parser.add_argument("--render-prompt", default=CANARY_PROMPTS["solo_explicit"])
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    ports = {8090: "llama", 8642: "gateway", 8188: "comfy", 8189: "gallery"}
    port_checks = {name: port_open(p) for p, name in ports.items()}
    delivery = daemon_alive(ROOT / "state" / "comfy-delivery-daemon.lock")
    render_lock = (ROOT / "state" / "roleplay-render.lock").is_file()

    intent_results = {k: evaluate_intent(k, v) for k, v in CANARY_PROMPTS.items()}
    fidelity_score = sum(1 for r in intent_results.values() if r["ok"]) / max(len(intent_results), 1)

    report: dict = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "version": "v0.4.13",
        "channel": args.channel,
        "ports": port_checks,
        "delivery_daemon": delivery,
        "render_lock": render_lock,
        "wisdomvault_health": load_health(),
        "intent_canaries": intent_results,
        "fidelity_parse_score": round(fidelity_score * 100),
        "latest_png": latest_png(),
        "recommendations": [],
    }

    if not all(port_checks.values()):
        down = [k for k, v in port_checks.items() if not v]
        report["recommendations"].append(f"Ports down: {', '.join(down)} - run Accelerate-Everything.ps1")
    if not delivery:
        report["recommendations"].append("Run Ensure-RP-Watchers.ps1 - delivery daemon offline")
    if render_lock:
        report["recommendations"].append("Clear stale roleplay-render.lock if no active render")
    for name, ir in intent_results.items():
        if ir.get("issues"):
            report["recommendations"].append(f"Intent {name}: {', '.join(ir['issues'])}")

    if args.render:
        report["live_render"] = run_render_test(args.render_prompt, args.channel)

    report["status"] = (
        "pass"
        if all(port_checks.values()) and delivery and fidelity_score >= 1.0
        else ("degraded" if any(port_checks.values()) else "fail")
    )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.json_only:
        print(json.dumps(report))
    else:
        print(f"RP Simulator: {report['status']} | fidelity_parse={report['fidelity_parse_score']}%")
        print(f"  ports={sum(port_checks.values())}/{len(port_checks)} delivery={delivery}")
        print(f"  report={REPORT}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())