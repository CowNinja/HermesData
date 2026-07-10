#!/usr/bin/env python3
"""Load Phase 8 module registry -- swap modules via YAML without code rebuild."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

REGISTRY_PATH = Path(r"D:\HermesData\config\phase8_modules.yaml")


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_registry(path: Path | None = None) -> Dict[str, Any]:
    return _load_yaml(path or REGISTRY_PATH)


def list_modules(*, enabled_only: bool = True) -> List[Dict[str, Any]]:
    reg = load_registry()
    mods = reg.get("modules") or {}
    out: List[Dict[str, Any]] = []
    for name, cfg in mods.items():
        if not isinstance(cfg, dict):
            continue
        if enabled_only and not cfg.get("enabled", True):
            continue
        out.append({"name": name, **cfg})
    out.sort(key=lambda m: int(m.get("order") or 99))
    return out


def main() -> int:
    print(json.dumps({"modules": list_modules()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())