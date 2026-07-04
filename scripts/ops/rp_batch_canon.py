"""Sandbox canon enforcement - cast, inventory, location props for batch renders."""
from __future__ import annotations

import sys
from typing import Any

from rp_sandbox_paths import (  # noqa: E402
    INVENTORIES,
    RUNTIME,
    SANDBOX_LIB,
    VISUAL_TAGS,
    assert_sandbox_layout,
)


def _ensure_sandbox_lib() -> None:
    assert_sandbox_layout()
    if str(SANDBOX_LIB) not in sys.path:
        sys.path.insert(0, str(SANDBOX_LIB))


def load_cast_registry() -> dict[str, Any]:
    _ensure_sandbox_lib()
    from visual_registry import load_visual_tags  # noqa: WPS433

    return (load_visual_tags() or {}).get("cast") or {}


def known_cast_slugs() -> list[str]:
    return sorted(load_cast_registry().keys())


def validate_cast_slugs(slugs: list[str]) -> list[str]:
    """Raise ValueError if any slug missing from visual-tags.yaml cast."""
    registry = load_cast_registry()
    missing = [s for s in slugs if s not in registry]
    if missing:
        raise ValueError(
            f"unknown_cast_slugs:{','.join(missing)} - "
            f"add to Roleplay-Sandbox/runtime/visual-tags.yaml cast section"
        )
    return [s for s in slugs if s in registry]


def cast_canon_meta(slug: str) -> dict[str, Any]:
    registry = load_cast_registry()
    entry = registry.get(slug) or {}
    return {
        "slug": slug,
        "display_name": entry.get("display_name") or slug.capitalize(),
        "ethnicity_lane": entry.get("ethnicity_lane"),
        "bust_emphasis": entry.get("bust_emphasis"),
        "has_explicit_identity": bool(entry.get("explicit_identity")),
        "locked_seed": entry.get("locked_seed"),
        "portrait_path": entry.get("portrait_path"),
        "inventory": str(INVENTORIES / "characters" / f"{slug}.yaml"),
    }


def location_prop_tags(location_id: str) -> str:
    _ensure_sandbox_lib()
    from inventory_registry import load_location_inventory  # noqa: WPS433

    inv = load_location_inventory(location_id)
    parts: list[str] = []
    for block in (inv.get("fixtures") or []) + (inv.get("props") or []):
        if not isinstance(block, dict):
            continue
        prompt = str(block.get("image_prompt") or "").strip()
        if prompt:
            parts.append(prompt)
    return ", ".join(parts)


def character_prop_tags(slug: str, *, prop_ids: list[str] | None = None) -> str:
    """Equipped + held items from character inventory YAML (when props requested)."""
    _ensure_sandbox_lib()
    from inventory_registry import load_character_inventory  # noqa: WPS433

    inv = load_character_inventory(slug)
    parts: list[str] = []
    want = {p.strip() for p in (prop_ids or []) if p.strip()}
    for it in inv.get("personal_items") or []:
        if not isinstance(it, dict):
            continue
        pid = str(it.get("id") or "")
        prompt = str(it.get("image_prompt") or "").strip()
        if not prompt:
            continue
        if want and pid not in want:
            continue
        if want or it.get("equipped") or it.get("held"):
            parts.append(prompt)
    return ", ".join(parts)


def enrich_scene(
    scene: str,
    *,
    location: str = "",
    characters: list[str] | None = None,
    props: list[str] | None = None,
    object_prompt: str = "",
) -> str:
    """Merge location fixtures + character held/equipped props into scene text."""
    chunks = [scene.strip(), object_prompt.strip()]
    if location:
        loc_tags = location_prop_tags(location)
        if loc_tags:
            chunks.append(loc_tags)
    if characters:
        for slug in characters:
            char_props = character_prop_tags(slug, prop_ids=props)
            if char_props:
                chunks.append(char_props)
    return ", ".join(x for x in chunks if x)


def outfit_for_character(slug: str, overrides: dict[str, str] | None = None) -> str:
    if overrides and overrides.get(slug):
        return overrides[slug]
    _ensure_sandbox_lib()
    from inventory_registry import get_active_outfit_prompt  # noqa: WPS433

    return get_active_outfit_prompt(slug) or ""


def plan_canon_audit(frames: list[Any]) -> dict[str, Any]:
    """Snapshot cast canon used by a series plan (for session + vault audit)."""
    slugs: set[str] = set()
    for frame in frames:
        for c in getattr(frame, "characters", []) or []:
            slugs.add(str(c).lower())
    validate_cast_slugs(sorted(slugs))
    return {
        "visual_tags": str(VISUAL_TAGS),
        "sandbox_root": str(RUNTIME.parent),
        "cast_count": len(slugs),
        "cast": {s: cast_canon_meta(s) for s in sorted(slugs)},
    }