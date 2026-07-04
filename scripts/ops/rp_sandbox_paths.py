"""Canonical Roleplay-Sandbox paths - single source of truth.

Sandbox root (Jeff reminder): D:\\PhronesisVault\\Roleplay-Sandbox\\
Override via ROLEPLAY_SANDBOX_ROOT env var.
"""
from __future__ import annotations

import os
from pathlib import Path

SANDBOX_ROOT = Path(
    os.environ.get("ROLEPLAY_SANDBOX_ROOT", r"D:\PhronesisVault\Roleplay-Sandbox")
).resolve()

SANDBOX = SANDBOX_ROOT / "sandbox"
SANDBOX_LIB = SANDBOX / "lib"
RUNTIME = SANDBOX_ROOT / "runtime"
REGISTRY = SANDBOX_ROOT / "registry"
GALLERY = SANDBOX_ROOT / "gallery"
INVENTORIES = RUNTIME / "inventories"
VISUAL_TAGS = RUNTIME / "visual-tags.yaml"
STATE_MD = RUNTIME / "continuity" / "STATE.md"

BATCH_RP_SERIES = SANDBOX / "batch-rp-series.py"
BATCH_HAREM = SANDBOX / "batch-harem-series.py"
BATCH_KITCHEN = SANDBOX / "batch-kitchen-crawl-series.py"
RENDER_PY = SANDBOX / "render-roleplay-image.py"


def assert_sandbox_layout() -> dict[str, str]:
    """Verify sandbox exists; return key paths for logging/audit."""
    required = {
        "sandbox_root": str(SANDBOX_ROOT),
        "visual_tags": str(VISUAL_TAGS),
        "sandbox_lib": str(SANDBOX_LIB),
        "inventories": str(INVENTORIES),
        "render_py": str(RENDER_PY),
    }
    missing = [k for k, v in required.items() if k != "sandbox_root" and not Path(v).exists()]
    if not SANDBOX_ROOT.is_dir():
        raise FileNotFoundError(f"Roleplay-Sandbox not found: {SANDBOX_ROOT}")
    if missing:
        raise FileNotFoundError(f"sandbox_layout_missing:{','.join(missing)}")
    return required