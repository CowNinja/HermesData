#!/usr/bin/env python3
"""RP Bridge - OOC prompt to visual_registry to Comfy render to Discord (no LLM)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
SANDBOX_LIB = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\lib")
RENDER = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\render-roleplay-image.py")
DEFAULT_CHANNEL = "1521146755985576116"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(SANDBOX_LIB) not in sys.path:
    sys.path.insert(0, str(SANDBOX_LIB))

from windows_subprocess import prefer_pythonw, run_hidden  # noqa: E402
from visual_registry import detect_image_intent  # noqa: E402


def build_render_cmd(spec: dict) -> list[str]:
    # No --discord-delivery: comfy_delivery_daemon is the sole Discord poster.
    cmd = [prefer_pythonw(sys.executable), str(RENDER), "--json", "--standard", "--fresh", "--new-seed"]
    mode = str(spec.get("mode") or "portrait")
    chars = list(spec.get("characters") or [])
    if len(chars) >= 2 and mode == "portrait":
        mode = "duo"
    cmd.extend(["--mode", mode])
    if spec.get("alternate"):
        cmd.extend(["--alternate", str(spec["alternate"])])
    for i, c in enumerate(chars[:2]):
        if i == 0:
            cmd.extend(["--character", c])
        else:
            cmd.extend(["--with", c])
    if spec.get("scene"):
        cmd.extend(["--scene", str(spec["scene"])])
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct OOC to Comfy to Discord bridge")
    parser.add_argument("prompt", nargs="?", default="")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    parser.add_argument("--series", type=int, default=0, help="Delegate series-of-N to batch orchestrator")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    prompt = (args.prompt or "").strip()
    if not prompt:
        print(json.dumps({"ok": False, "error": "prompt required"}))
        return 1

    if args.series >= 2:
        orch = ROOT / "scripts" / "ops" / "rp_batch_orchestrator.py"
        spec = detect_image_intent(prompt, "", "") or {}
        spec["batch_count"] = args.series
        proc = run_hidden(
            [prefer_pythonw(sys.executable), str(orch), prompt, "--spec-json", json.dumps(spec)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in (proc.stdout or "").splitlines():
            if line.strip().startswith("{"):
                print(line.strip())
                return 0 if json.loads(line).get("ok") else 1
        print(json.dumps({"ok": False, "error": "orchestrator_failed", "stderr": (proc.stderr or "")[:300]}))
        return 1

    spec = detect_image_intent(prompt, "", "")
    if not spec:
        print(json.dumps({"ok": False, "error": "no_image_intent", "prompt": prompt}))
        return 1
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "spec": spec}))
        return 0

    proc = run_hidden(build_render_cmd(spec), capture_output=True, text=True, timeout=1320)
    result = None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                result = json.loads(line)
            except json.JSONDecodeError:
                pass
    if not result or not result.get("success"):
        print(json.dumps({"ok": False, "spec": spec, "stderr": (proc.stderr or "")[:500]}))
        return proc.returncode or 1

    image = result.get("gallery_image") or result.get("image") or ""
    if not image:
        print(json.dumps({"ok": False, "error": "no_image_path", "result": result}))
        return 1

    out = {
        "ok": True,
        "spec": spec,
        "image": image,
        "png": Path(image).name,
        "delivery": {"action": "deferred", "reason": "comfy_delivery_daemon_only"},
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())