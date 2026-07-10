#!/usr/bin/env python3
"""Garden wall helpers -- RP/explicit sandbox must not leak to fleet, K:, or coordination."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

CONFIG_PATH = Path(r"D:\HermesData\config\rp_garden_wall.yaml")

_DEFAULT_EXCLUDED = (
    r"D:\PhronesisVault\Roleplay-Sandbox",
    r"D:\PhronesisVault\Discord\RPG",
    r"D:\HermesData\ComfyUI\output",
)

_EXPLICIT_MARKERS = (
    "ooc:",
    "harem",
    "explicit",
    "nsfw",
    "erotic",
    "uncensored",
    "roleplay-sandbox",
)


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


def excluded_paths() -> List[Path]:
    cfg = _load_yaml(CONFIG_PATH)
    raw = (cfg.get("excluded_paths") or []) + list(_DEFAULT_EXCLUDED)
    out: List[Path] = []
    seen: set[str] = set()
    for item in raw:
        p = Path(str(item)).resolve()
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def is_rp_or_explicit_path(path: str | Path) -> bool:
    try:
        resolved = Path(path).resolve()
    except Exception:
        resolved = Path(str(path))
    text = str(resolved).lower().replace("/", "\\")
    for ex in excluded_paths():
        ex_text = str(ex).lower().replace("/", "\\")
        if text == ex_text or text.startswith(ex_text + "\\"):
            return True
    return False


def contains_explicit_markers(text: str) -> Tuple[bool, str]:
    low = (text or "").lower()
    for marker in _EXPLICIT_MARKERS:
        if marker in low:
            return True, f"explicit:{marker}"
    for ex in excluded_paths():
        frag = str(ex).lower()
        if frag in low:
            return True, "sandbox_path"
    return False, ""


def assert_safe_for_export(text: str, *, context: str = "export") -> None:
    hit, reason = contains_explicit_markers(text)
    if hit:
        raise ValueError(f"garden_wall_blocked:{context}:{reason}")


def audit_isolation() -> Dict[str, Any]:
    cfg = _load_yaml(CONFIG_PATH)
    sandbox_root = Path(
        str((cfg.get("sandbox") or {}).get("root") or _DEFAULT_EXCLUDED[0])
    )
    k_root = Path(r"K:\Phronesis-Sovereign")
    leaks: List[str] = []
    if k_root.is_dir():
        # Shallow scan only -- avoid full K: walk on large archives
        for hit in list(k_root.iterdir()) + list((k_root / "Personal-Digital-Silo").iterdir() if (k_root / "Personal-Digital-Silo").is_dir() else []):
            if is_rp_or_explicit_path(hit):
                leaks.append(str(hit))
            if len(leaks) >= 20:
                break
    return {
        "sandbox_root": str(sandbox_root),
        "sandbox_exists": sandbox_root.is_dir(),
        "orchestrator_excluded": bool((cfg.get("sandbox") or {}).get("orchestrator_excluded", True)),
        "outbound_blocked": bool((cfg.get("rules") or {}).get("outbound_blocked", True)),
        "k_silo_leak_count": len(leaks),
        "k_silo_leak_samples": leaks[:5],
        "isolated": len(leaks) == 0,
    }


def main() -> int:
    import json

    print(json.dumps({"garden_wall": audit_isolation()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())