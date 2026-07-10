#!/usr/bin/env python3
"""Download and register the unified sovereign generalist (abliterated 8B)."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT_SCRIPTS = Path(r"D:\PhronesisVault\scripts")
GGUF_MAP = Path(r"D:\PhronesisVault\Operations\LlamaCpp-GGUF-Map-v0.1.json")
MODELS_INI = Path(r"D:\PhronesisModels\presets\models.ini")
MOE_MAP = Path(r"D:\PhronesisVault\Operations\MoE-Task-Type-Map-v0.1.json")
PIN_CONFIG = Path(r"D:\PhronesisVault\Operations\lru-pinned-models-v0.1.json")

LOGICAL = "qwen2-5-7b"
FILENAME = "Qwen2.5-Coder-14B-Instruct-abliterated-Q5_K_M.gguf"
REPO = ""  # pre-downloaded on disk; set to HF repo if --download needed
CTX_SIZE = 12288
NGL = 99


def _download() -> dict:
    if not REPO:
        return {"ok": False, "reason": "no_repo_configured"}
    cmd = [
        sys.executable,
        str(VAULT_SCRIPTS / "model_inventory.py"),
        "--download",
        REPO,
        "--file",
        FILENAME,
    ]
    print("EXEC:", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {"ok": False}
    except Exception:
        return {"ok": proc.returncode == 0}


def _find_gguf() -> Path | None:
    roots = [
        Path(r"D:\PhronesisModels\models\current"),
        Path(r"D:\PhronesisModels\models\candidates"),
    ]
    for root in roots:
        p = root / FILENAME
        if p.is_file():
            return p
    return None


def _register(path: Path) -> None:
    entry = {
        "gguf_file": path.name,
        "path": str(path),
        "role": "unified_sovereign_generalist",
        "latency_budget_ms": 30000,
        "tier": "local_generalist",
        "port": 8090,
        "storage_tier": "current" if "current" in str(path) else "candidate",
        "uncensored": True,
        "ctx_size": CTX_SIZE,
    }
    if GGUF_MAP.is_file():
        data = json.loads(GGUF_MAP.read_text(encoding="utf-8"))
        data.setdefault("models", {})[LOGICAL] = entry
        data.setdefault("models", {})[path.name] = {**entry, "logical_name": LOGICAL}
        data.setdefault("filename_to_logical", {})[path.name] = LOGICAL
        data["reconciled_at"] = datetime.now(timezone.utc).isoformat()
        GGUF_MAP.write_text(json.dumps(data, indent=2), encoding="utf-8")

    if MODELS_INI.is_file():
        text = MODELS_INI.read_text(encoding="utf-8")
        if f"[{LOGICAL}]" not in text:
            block = (
                f"\n[{LOGICAL}]\n"
                f"model = {path}\n"
                f"ctx-size = {CTX_SIZE}\n"
                f"ngl = {NGL}\n"
            )
            MODELS_INI.write_text(text.rstrip() + block + "\n", encoding="utf-8")
        lines = []
        for line in MODELS_INI.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("models-max"):
                lines.append("models-max = 1")
            else:
                lines.append(line)
        if not any(l.strip().startswith("models-max") for l in lines):
            lines.insert(4, "models-max = 1")
        MODELS_INI.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if MOE_MAP.is_file():
        moe = json.loads(MOE_MAP.read_text(encoding="utf-8-sig"))
        ur = moe.setdefault("unified_router", {})
        ur["models_max_active"] = 1
        ur["models_max_idle"] = 1
        tiers = ur.setdefault("tier_logical_models", {})
        for key in list(tiers.keys()):
            tiers[key] = LOGICAL
        moe["description"] = (
            "Unified sovereign generalist — single abliterated model for all task types."
        )
        MOE_MAP.write_text(json.dumps(moe, indent=2), encoding="utf-8")

    pin = {
        "version": "v0.2",
        "approved_by": "Jeff — unified sovereign generalist pivot 2026-06-28",
        "vram_gb": 12,
        "pinned_logical_models": [LOGICAL],
        "generalist_logical": LOGICAL,
        "models_max_floor": 1,
        "ctx_size_default": CTX_SIZE,
        "ctx_size_12gb_single": CTX_SIZE,
        "keepalive_interval_sec": 300,
        "notes": (
            f"Single-pin {LOGICAL} @ ctx {CTX_SIZE} on 12GB VRAM. "
            "models-max=1 keeps generalist resident for sub-5s latency."
        ),
    }
    PIN_CONFIG.write_text(json.dumps(pin, indent=2), encoding="utf-8")
    print(f"Registered {LOGICAL} -> {path}")


def main() -> int:
    path = _find_gguf()
    if not path and REPO:
        result = _download()
        if not result.get("ok"):
            print("Download failed:", result)
            return 1
        path = _find_gguf()
    if not path:
        print("GGUF not found after download")
        return 1
    _register(path)
    reconcile = subprocess.run(
        [sys.executable, str(VAULT_SCRIPTS / "model_inventory.py"), "--reconcile"],
        capture_output=True,
        text=True,
    )
    print(reconcile.stdout)
    print("OK: unified generalist provisioned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
