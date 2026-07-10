#!/usr/bin/env python3
"""Patch prompt_compose.py for identity_lock + dynamic expression layers."""
from __future__ import annotations

import ast
from pathlib import Path

path = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\lib\prompt_compose.py")
text = path.read_text(encoding="utf-8")

header = r'''"""Compose Pony prompts: identity (fixed face) + body + expression (dynamic) + outfit + scene."""
from __future__ import annotations

import re
from typing import Any

from inventory_registry import (  # noqa: E402
    get_active_outfit_prompt,
    get_wardrobe_entry,
    load_character_inventory,
)
from visual_registry import load_visual_tags, resolve_cast_slug, resolve_inventory_id  # noqa: E402

# Layer order is fixed for cross-generation consistency (see IMAGE-PIPELINE.md).
# identity = same face; expression = dynamic emotion (never baked into identity_lock).
LAYER_ORDER = (
    "quality",
    "identity",
    "body",
    "expression",
    "outfit",
    "accessories",
    "held",
    "scene",
    "suffix",
)

# Scene/OOC text → expression tags (face stays locked; emotion changes).
_EXPRESSION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(surpris|shock|startl|wide[- ]eyed|gasp)\w*\b", re.I),
     "surprised expression, wide eyes, parted lips, soft gasp"),
    (re.compile(r"\b(desire|lust|hungry|desperate|wanting|aching|need(y|ing)?)\b", re.I),
     "lustful expression, flushed cheeks, parted lips, desire in eyes"),
    (re.compile(r"\b(seduc|bedroom eyes|come hither|sultry|teas(e|ing)|coquett)\w*\b", re.I),
     "seductive smile, bedroom eyes, sultry look"),
    (re.compile(r"\b(ahegao|mind.?break|overwhelmed with pleasure)\b", re.I),
     "ahegao, rolling eyes, tongue out, overwhelmed pleasure"),
    (re.compile(r"\b(shy|bashful|embarrassed|blush)\w*\b", re.I),
     "shy expression, blushing, averted gaze, soft smile"),
    (re.compile(r"\b(angry|glare|fierce|scowl)\w*\b", re.I),
     "fierce expression, intense eyes, sharp gaze"),
    (re.compile(r"\b(soft|tender|loving|devoted|warm smile)\b", re.I),
     "soft loving expression, warm eyes, gentle smile"),
    (re.compile(r"\b(orgasm|climax|cumming|ecstasy)\b", re.I),
     "ecstatic expression, eyes half-closed, open mouth, pleasure"),
    (re.compile(r"\b(smirk|smug|confident)\b", re.I),
     "confident smirk, knowing eyes"),
    (re.compile(r"\b(cry|tearful|sob)\w*\b", re.I),
     "tearful expression, wet eyes, emotional"),
]


def expression_layer(scene: str = "", *, explicit: bool = False) -> str:
    """Dynamic facial emotion from scene/heat text — never part of identity_lock."""
    text_s = scene or ""
    hits: list[str] = []
    for pat, phrase in _EXPRESSION_PATTERNS:
        if pat.search(text_s) and phrase not in hits:
            hits.append(phrase)
        if len(hits) >= 2:
            break
    if hits:
        return ", ".join(hits)
    if explicit:
        return "seductive expression, bedroom eyes, inviting look"
    return ""


def _consistency_weights(cfg: dict[str, Any]) -> tuple[float, float, float]:
    c = cfg.get("consistency") or {}
    return (
        float(c.get("identity_weight") or 1.25),
        float(c.get("body_weight") or 1.12),
        float(c.get("expression_weight") or 1.05),
    )


def _weight(tag_blob: str, w: float) -> str:
    blob = (tag_blob or "").strip().strip(",")
    if not blob:
        return ""
    if abs(w - 1.0) < 0.02:
        return blob
    return f"({blob}:{w:.2f})"


def identity_body_layers(
    cast: dict[str, Any],
    cfg: dict[str, Any],
    *,
    scene: str = "",
    explicit: bool = False,
) -> dict[str, str]:
    """Fixed face + body locks; expression separate and dynamic."""
    iw, bw, ew = _consistency_weights(cfg)
    ident = str(cast.get("identity_lock") or "").strip()
    if not ident:
        body = str(cast.get("body_tags") or "")
        toks = [t.strip() for t in body.split(",") if t.strip()][:8]
        ident = ", ".join(toks)
    body_lock = str(cast.get("body_lock") or "").strip()
    if not body_lock:
        body = str(cast.get("body_tags") or cast.get("tags") or "").strip()
        bust = str(cast.get("bust_emphasis") or cfg.get("bust_global") or "").strip()
        body_lock = ", ".join(x for x in (body, bust) if x)
    expr = expression_layer(scene, explicit=explicit)
    return {
        "identity": _weight(ident, iw) if ident else "",
        "body": _weight(body_lock, bw) if body_lock else "",
        "expression": _weight(expr, ew) if expr else "",
    }


def _strip_default_expression_from_suffix(suffix: str, has_custom_expression: bool) -> str:
    """When scene supplies expression, drop baked seductive defaults from suffix."""
    if not has_custom_expression or not suffix:
        return suffix
    drop = re.compile(
        r"\b(seductive smile|slutty expression|bedroom eyes|come hither expression|"
        r"lustful seductive expression|inviting pose)\b,?\s*",
        re.I,
    )
    return drop.sub("", suffix).strip(" ,")


def _item_visual_prompt(item: dict[str, Any]) -> str:
    return str(item.get("image_prompt") or "").strip()


'''

idx_inv = text.find("def get_inventory_visual_layers")
idx_compose = text.find("def compose_character_prompt")
idx_exp = text.find("_EXPLICIT_USER_RE = re.compile")
if min(idx_inv, idx_compose, idx_exp) < 0:
    raise SystemExit(f"markers missing {idx_inv, idx_compose, idx_exp}")

get_inv_only = text[idx_inv:idx_compose]

compose_new = r'''
def compose_character_prompt(
    character_id: str,
    *,
    mode: str = "portrait",
    scene: str = "",
    outfit_override: str = "",
    explicit_variant: str = "",
    cfg: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """
    Build positive prompt string and debug layer list.
    identity_lock = same face; expression_layer = dynamic emotion from scene.
    Portrait/dossier uses dossier_outfit unless inventory outfit_override or wardrobe active.
    """
    cfg = cfg or load_visual_tags()
    character_id = resolve_cast_slug(character_id, cfg=cfg)
    cast = (cfg.get("cast") or {}).get(character_id, {})
    quality = cfg.get("quality_prefix", "")
    id_layers = identity_body_layers(cast, cfg, scene=scene, explicit=(mode == "explicit"))

    if mode == "explicit":
        prose = str(cast.get("explicit_identity") or cast.get("portrait_prompt") or "").strip()
        if not cast.get("explicit_identity") and "full body" in prose.lower():
            prose = prose.split("full body", 1)[0].strip().rstrip(",")
        variant_key = explicit_variant.strip().lower().replace(" ", "-")
        variant_cfg = (cfg.get("explicit_variants") or {}).get(variant_key, {})
        bust_pose = str(variant_cfg.get("bust_pose_tags") or "").strip()
        if bust_pose:
            bust = bust_pose
        else:
            bust = str(cast.get("bust_emphasis") or cfg.get("bust_global") or "").strip()
        suffix_key = (cfg.get("dossier_modes") or {}).get("explicit", {}).get(
            "suffix_key", "explicit_suffix"
        )
        if variant_cfg.get("suffix_key"):
            suffix = cfg.get(str(variant_cfg["suffix_key"]), "")
        elif variant_cfg.get("suffix"):
            suffix = str(variant_cfg["suffix"])
        else:
            suffix = cfg.get(suffix_key, "")
        suffix = _strip_default_expression_from_suffix(suffix, bool(id_layers.get("expression")))
        nude_lock = str((cfg.get("explicit_nude_lock") or {}).get("prompt_tags") or "").strip()
        variant_addon = str((cast.get("explicit_variant_addons") or {}).get(variant_key) or "").strip()
        solo_weight = "(solo:1.4), (1girl:1.3), (nude:1.4), (completely naked:1.3), (bare skin:1.2), (no clothing:1.3)"
        prompt = ", ".join(
            x
            for x in [
                quality,
                id_layers.get("identity", ""),
                solo_weight,
                prose,
                id_layers.get("body", "") or bust,
                id_layers.get("expression", ""),
                nude_lock,
                suffix,
                variant_addon,
                scene,
            ]
            if x
        )
        debug = [
            f"identity={id_layers.get('identity', '')[:60]}",
            f"expression={id_layers.get('expression', '')[:40]}",
            f"explicit_from={prose[:80]}...",
            f"bust={bust[:40]}",
        ]
        return prompt.strip(", "), debug

    if mode in ("portrait", "tease"):
        prose = str(cast.get("portrait_prompt") or "").strip()
        bust = str(cast.get("bust_emphasis") or "").strip()
        if prose and not outfit_override:
            mode_cfg = (cfg.get("dossier_modes") or {}).get(mode) or {}
            suffix_key = mode_cfg.get("suffix_key", "dossier_suffix")
            suffix = cfg.get(suffix_key, "")
            suffix = _strip_default_expression_from_suffix(suffix, bool(id_layers.get("expression")))
            prompt = ", ".join(
                x
                for x in [
                    quality,
                    id_layers.get("identity", ""),
                    prose,
                    id_layers.get("body", "") or bust,
                    id_layers.get("expression", ""),
                    suffix,
                    scene,
                ]
                if x
            )
            debug = [
                f"identity={id_layers.get('identity', '')[:60]}",
                f"expression={id_layers.get('expression', '')[:40]}",
                f"portrait_prompt={prose[:80]}...",
            ]
            return prompt.strip(", "), debug
        if prose and outfit_override:
            mode_cfg = (cfg.get("dossier_modes") or {}).get(mode) or {}
            suffix_key = mode_cfg.get("suffix_key", "dossier_suffix")
            suffix = cfg.get(suffix_key, "")
            suffix = _strip_default_expression_from_suffix(suffix, bool(id_layers.get("expression")))
            prompt = ", ".join(
                x
                for x in [
                    quality,
                    id_layers.get("identity", ""),
                    prose,
                    outfit_override,
                    id_layers.get("expression", ""),
                    suffix,
                    scene,
                ]
                if x
            )
            debug = [
                f"identity={id_layers.get('identity', '')[:60]}",
                f"portrait_prompt={prose[:80]}...",
                f"outfit_override={outfit_override[:40]}",
            ]
            return prompt.strip(", "), debug

    body = id_layers.get("body") or str(cast.get("body_tags") or cast.get("tags") or "").strip()
    if body.startswith("1girl") and "solo" not in body and mode in ("portrait", "tease"):
        body = body.replace("1girl,", "1girl, solo,", 1) if "1girl," in body else f"1girl, solo, {body}"

    inv_layers = get_inventory_visual_layers(character_id)
    if outfit_override.strip():
        inv_layers = {"outfit": "", "accessories": "", "held": ""}
    outfit = outfit_override.strip() or inv_layers["outfit"]

    if not outfit:
        if mode in ("scene", "establishing"):
            outfit = str(cast.get("scene_outfit") or "").strip()
        else:
            outfit = str(cast.get("dossier_outfit") or cast.get("default_outfit") or "").strip()

    if not outfit and mode not in ("establishing",):
        outfit = get_active_outfit_prompt(character_id)

    mode_cfg = (cfg.get("scene_modes") or {}).get(mode) or (cfg.get("dossier_modes") or {}).get(mode) or {}
    suffix_key = mode_cfg.get("suffix_key", "dossier_suffix" if mode in ("portrait", "tease") else "scene_suffix")
    suffix = cfg.get(suffix_key, "")
    suffix = _strip_default_expression_from_suffix(suffix, bool(id_layers.get("expression")))

    layers = {
        "quality": quality,
        "identity": id_layers.get("identity", ""),
        "body": body,
        "expression": id_layers.get("expression", ""),
        "outfit": outfit,
        "accessories": inv_layers["accessories"],
        "held": inv_layers["held"],
        "scene": scene.strip(),
        "suffix": suffix,
    }

    raw = ", ".join(layers[k] for k in LAYER_ORDER if layers.get(k))
    seen: set[str] = set()
    tokens: list[str] = []
    for tok in raw.split(","):
        t = tok.strip()
        key = t.lower()
        if t and key not in seen:
            seen.add(key)
            tokens.append(t)
    prompt = ", ".join(tokens)
    debug = [
        f"{k}={layers[k][:60]}..." if len(layers.get(k, "")) > 60 else f"{k}={layers.get(k, '')}"
        for k in LAYER_ORDER
    ]
    return prompt.strip(", "), debug


'''

new_text = header + get_inv_only + compose_new + text[idx_exp:]
ast.parse(new_text)
path.write_text(new_text, encoding="utf-8")
print("OK", path, "bytes", path.stat().st_size)
