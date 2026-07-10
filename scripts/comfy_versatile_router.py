#!/usr/bin/env python3
"""Prompt-first Comfy routing -- guide without pigeonholing (registry opt-in only)."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CONFIG_PATH = Path(r"D:\HermesData\config\comfy_versatile.yaml")
_SANDBOX_LIB = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\lib")

CAST_SLUGS = (
    "alice",
    "chloe",
    "zara",
    "lyra",
    "becca",
    "emily",
    "sassy",
    "valentina",
)

_OOC_PREFIX = re.compile(r"^\s*(?:OOC:\s*)?", re.I)
_CHANNEL_PREFIX = re.compile(r"^\s*\[[^\]]+\]\s*", re.I)

_GIRL_COUNT_RE = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:\w+\s+){0,10}"
    r"(?:girls?|women|brunettes?|blondes?|redheads?|models?|figures?)\b",
    re.I,
)

_WORD_COUNTS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_SOLO_PER_IMAGE_RE = re.compile(
    r"\b(?:one|a|single)\s+(?:girl|woman)\s+per\s+(?:image|picture|portrait|photo)\b"
    r"|\b(?:solo|distinct)\s+images?\b"
    r"|\bone\s+per\s+image\b"
    r"|\beach\s+image\s+shows\s+(?:a\s+)?(?:different|distinct|unique)\b",
    re.I,
)

_PONY_QUALITY = "score_9, score_8_up, score_7_up, masterpiece, best quality"


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


def normalize_prompt_text(text: str) -> str:
    t = _CHANNEL_PREFIX.sub("", text or "").strip()
    t = re.sub(r"^OOC:\s*", "", t, flags=re.I).strip()
    return t


def extract_cast_names(text: str) -> List[str]:
    lower = normalize_prompt_text(text).lower()
    return [s for s in CAST_SLUGS if re.search(rf"\b{re.escape(s)}\b", lower)]


def _token_count(token: str) -> int:
    tok = str(token or "").strip().lower()
    if tok.isdigit():
        return int(tok)
    return int(_WORD_COUNTS.get(tok, 0))


def infer_group_size_per_frame(text: str) -> int:
    lower = normalize_prompt_text(text).lower()
    if _SOLO_PER_IMAGE_RE.search(lower):
        return 1
    if re.search(r"\b(?:solo|alone|single\s+figure|1girl)\b", lower):
        if not re.search(r"\btogether\b", lower):
            return 1
    explicit = 0
    for match in _GIRL_COUNT_RE.finditer(lower):
        n = _token_count(match.group(1))
        if n >= 1:
            if re.search(r"\btogether\b|\bin\s+one\s+image\b|\bsame\s+image\b", lower):
                return min(n, 10)
            if re.search(r"\bper\s+image\b|\bsolo\s+images?\b", lower):
                return 1
            explicit = max(explicit, n)
    if explicit >= 2 and re.search(r"\btogether\b|\bgroup\b|\ball\s+in\b", lower):
        return min(explicit, 10)
    if explicit >= 2 and _SOLO_PER_IMAGE_RE.search(lower):
        return 1
    if explicit >= 2:
        return min(explicit, 10)
    if re.search(r"\b(duo|pair|couple|two\s+girls?\s+together)\b", lower):
        return 2
    if re.search(r"\b(trio|triplet|three\s+girls?\s+together)\b", lower):
        return 3
    return 1


def infer_batch_count(text: str) -> int:
    try:
        import sys
        sys.path.insert(0, r"D:PhronesisVaultRoleplay-Sandboxsandboxlib")
        from visual_registry import resolve_image_count
        return resolve_image_count(text)
    except Exception:
        pass
    lower = normalize_prompt_text(text).lower()
    m = re.search(r"\b(?:series|batch)\s+of\s+(\d+)\b", lower)
    if m:
        return int(m.group(1))
    m = re.search(r"\bexactly\s+(\d+)\s+(?:distinct\s+)?(?:solo\s+)?images?\b", lower)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)\s+(?:distinct\s+)?(?:solo\s+)?(?:images?|pictures?|portraits?)\b", lower)
    if m and any(k in lower for k in ("series", "batch", "exactly", "distinct", "per image", "solo images")):
        return int(m.group(1))
    if _SOLO_PER_IMAGE_RE.search(lower):
        for match in _GIRL_COUNT_RE.finditer(lower):
            n = _token_count(match.group(1))
            if n >= 2:
                return n
    # Explicit single markers return 0 (no batch)
    if re.search(r"\b(one|single|a single)\s+(?:image|picture|portrait|photo)\b", lower):
        return 0
    return 0


def is_non_character_subject(text: str) -> bool:
    cfg = _load_yaml(CONFIG_PATH)
    markers = list((cfg.get("registry_opt_in") or {}).get("never_for_subjects") or [])
    lower = normalize_prompt_text(text).lower()
    return any(m in lower for m in markers)


def registry_opt_in(text: str, cast: List[str]) -> bool:
    cfg = _load_yaml(CONFIG_PATH)
    lower = normalize_prompt_text(text).lower()
    if is_non_character_subject(text):
        return False
    if re.search(r"\bfreeform\b", lower):
        return False
    markers = list((cfg.get("registry_opt_in") or {}).get("markers") or [])
    if any(m in lower for m in markers):
        return bool(cast)
    require_cast = bool((cfg.get("registry_opt_in") or {}).get("require_cast_name", True))
    if require_cast:
        return len(cast) > 0
    return False


def infer_model(text: str, hint: str = "") -> str:
    cfg = _load_yaml(CONFIG_PATH)
    lower = normalize_prompt_text(text).lower()
    hint_l = (hint or "").strip().lower()
    if hint_l in ("pony", "juggernaut"):
        return hint_l
    jug = list((cfg.get("model_hints") or {}).get("juggernaut") or [])
    pony = list((cfg.get("model_hints") or {}).get("pony") or [])
    if any(k in lower for k in jug):
        return "juggernaut"
    if any(k in lower for k in pony):
        return "pony"
    default = str((cfg.get("defaults") or {}).get("model") or "pony")
    if is_non_character_subject(text):
        return "juggernaut"
    return default


def extract_user_scene(text: str, cast: Optional[List[str]] = None) -> str:
    """Pull scene/pose/mood from user words; strip cast slugs and control tokens."""
    body = normalize_prompt_text(text)
    for word in ("fresh", "canon", "freeform", "dossier", "locked", "OOC", "portrait", "picture", "image", "render", "generate"):
        body = re.sub(rf"\b{re.escape(word)}\b", "", body, flags=re.I)
    for slug in cast or extract_cast_names(text):
        body = re.sub(rf"\b{re.escape(slug)}\b", "", body, flags=re.I)
    body = re.sub(
        r"\b(?:series|batch)\s+of\s+\d+\s+images?\b",
        "",
        body,
        flags=re.I,
    )
    body = re.sub(_GIRL_COUNT_RE, "", body)
    body = re.sub(r"\s+", " ", body).strip(" ,.-")
    return body


def infer_mode_from_text(text: str) -> str:
    """Guide mode without forcing explicit from skimpy/clothed keywords."""
    lower = normalize_prompt_text(text).lower()
    if re.search(r"\b(canon|dossier|locked)\b", lower):
        return "portrait"
    if re.search(
        r"\b(skimpy|tube\s+top|ribbon|strapless|loincloth|wearing|they\s+wear|"
        r"underboob|sideboob|barely\s+covering|hot\s+pink|micro\s+top)\b",
        lower,
    ):
        return "tease"
    if re.search(r"\b(nude|naked|explicit|nsfw|spread|on\s+all\s+fours|uncensored)\b", lower):
        return "explicit"
    if re.search(r"\b(establishing|wide\s+shot|landscape|exterior|no\s+people|no\s+humans)\b", lower):
        return "establishing"
    if re.search(r"\b(tease|lingerie)\b", lower):
        return "tease"
    if re.search(r"\b(scene|together|duo|kiss|kitchen|garden|bedroom|volcano|grotto)\b", lower):
        return "scene"
    return "portrait"


def _load_compose():
    if str(_SANDBOX_LIB) not in sys.path:
        sys.path.insert(0, str(_SANDBOX_LIB))
    from prompt_compose import compose_cast_enriched  # noqa: WPS433

    return compose_cast_enriched


def compose_character_enriched_prompt(
    text: str,
    cast: List[str],
    *,
    mode: str = "",
    canon_lock: bool = False,
) -> Tuple[str, str, str]:
    """Merge sandbox identity layers under user scene (Grok-imagine + consistency)."""
    scene = extract_user_scene(text, cast)
    mode_use = mode or infer_mode_from_text(text)
    compose = _load_compose()
    prompt, neg, tags = compose(
        cast[:10],
        user_scene=scene,
        mode=mode_use,
        canon_lock=canon_lock,
    )
    return prompt, neg, ",".join(tags)


def canon_suffixes_enabled(text: str) -> bool:
    cfg = _load_yaml(CONFIG_PATH)
    if not bool((cfg.get("canon_suffixes") or {}).get("apply_by_default", False)):
        lower = normalize_prompt_text(text).lower()
        when = list((cfg.get("canon_suffixes") or {}).get("dossier_suffix_only_when") or [])
        return any(w in lower for w in when)
    return True


def compose_freeform_prompt(text: str, *, model: str = "pony") -> Tuple[str, str]:
    """Pass user words through with pose-first weighting (Grok-imagine + CLIP-safe tags)."""
    body = extract_user_scene(text) or normalize_prompt_text(text)
    body = re.sub(r"\b(?:fresh|canon|freeform)\b", "", body, flags=re.I)
    body = re.sub(r"\s+", " ", body).strip(" ,.")
    cfg = _load_yaml(CONFIG_PATH)
    use_quality = bool((cfg.get("defaults") or {}).get("quality_prefix_for_pony", True))
    gs = infer_group_size_per_frame(text)
    pose_block = ""
    outfit_block = ""
    pose_neg = ""
    try:
        if str(_SANDBOX_LIB) not in sys.path:
            sys.path.insert(0, str(_SANDBOX_LIB))
        from prompt_compose import (  # noqa: WPS433
            condense_outfit_prose,
            pose_negative_guard,
            pose_weighted_clause,
            user_wants_skimpy_outfit,
        )

        pose_block = pose_weighted_clause(body)
        if user_wants_skimpy_outfit(body):
            outfit_block = condense_outfit_prose(body)
        pose_neg = pose_negative_guard(body)
    except Exception:
        pass
    parts: List[str] = []
    if model == "pony" and use_quality and not body.lower().startswith("score_"):
        parts.append(_PONY_QUALITY)
    if gs >= 2:
        parts.append(f"({gs}girls:1.4), exactly {gs} distinct figures, group composition")
    if pose_block:
        parts.append(pose_block)
    if outfit_block:
        parts.append(outfit_block)
    elif body:
        parts.append(body)
    prompt = ", ".join(p for p in parts if p)
    neg = "worst quality, low quality, blurry, watermark, text, bad anatomy, extra limbs"
    if gs >= 3:
        neg += ", extra person, crowd, too many people, duplicate, clone"
    if pose_neg:
        neg = f"{neg}, {pose_neg}"
    return prompt.strip(", "), neg


@dataclass
class VersatileRoute:
    path: str
    model: str
    final_prompt: str
    negative_extra: str
    use_registry: bool
    characters: List[str] = field(default_factory=list)
    registry_mode: str = "freeform"
    fresh: bool = True
    group_size: int = 1
    batch_count: int = 0
    tags: str = "freeform"
    aspect: str = "portrait"
    no_detailers: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "model": self.model,
            "final_prompt": self.final_prompt,
            "negative_extra": self.negative_extra,
            "use_registry": self.use_registry,
            "characters": self.characters,
            "registry_mode": self.registry_mode,
            "fresh": self.fresh,
            "group_size": self.group_size,
            "batch_count": self.batch_count,
            "tags": self.tags,
            "aspect": self.aspect,
            "no_detailers": self.no_detailers,
        }


def route_image_prompt(
    prompt: str,
    *,
    model_hint: str = "",
    spec: Optional[Dict[str, Any]] = None,
) -> VersatileRoute:
    spec = dict(spec or {})
    text = prompt or ""
    cast = list(spec.get("characters") or extract_cast_names(text))
    use_registry = registry_opt_in(text, cast)
    if spec.get("reason") == "ooc_freeform":
        use_registry = False
    if spec.get("freeform_prompt"):
        use_registry = False

    model = infer_model(text, model_hint)
    fresh = bool((spec.get("fresh") is True) or re.search(r"\bfresh\b", text, re.I))
    cfg = _load_yaml(CONFIG_PATH)
    if bool((cfg.get("defaults") or {}).get("fresh_on_ooc", True)) and re.search(r"\bOOC:", text, re.I):
        fresh = True

    group_size = int(spec.get("group_size") or 0) or infer_group_size_per_frame(text)
    batch_count = int(spec.get("batch_count") or 0) or infer_batch_count(text)

    no_detailers = is_non_character_subject(text) or group_size >= 4
    canon_lock = bool(spec.get("canon_lock")) or (canon_suffixes_enabled(text) and bool(cast))

    if use_registry and cast:
        mode = str(spec.get("mode") or infer_mode_from_text(text))
        cast_use = cast[:10] if group_size >= 3 else cast[: max(2, group_size)]
        if group_size == 1 and len(cast_use) > 1:
            cast_use = cast_use[:1]

        if canon_lock:
            path = "canon"
            final_prompt = normalize_prompt_text(text)
            neg = ""
            tags = f"roleplay,{mode},{cast_use[0]},canon"
            use_reg = True
        else:
            path = "character_enriched"
            try:
                final_prompt, neg, tags = compose_character_enriched_prompt(
                    text,
                    cast_use,
                    mode=mode,
                    canon_lock=False,
                )
            except Exception:
                final_prompt, neg = compose_freeform_prompt(text, model=model)
                tags = "freeform,enriched,fallback"
            use_reg = False

        aspect = "landscape" if group_size >= 2 else "portrait"
        return VersatileRoute(
            path=path,
            model=model,
            final_prompt=final_prompt,
            negative_extra=neg,
            use_registry=use_reg,
            characters=cast_use,
            registry_mode=mode,
            fresh=fresh if not canon_lock else False,
            group_size=group_size,
            batch_count=batch_count,
            tags=tags,
            aspect=aspect,
            no_detailers=no_detailers,
        )

    final_prompt, neg = compose_freeform_prompt(text, model=model)
    if spec.get("freeform_prompt"):
        final_prompt = str(spec["freeform_prompt"])
    if spec.get("negative_extra"):
        neg = str(spec["negative_extra"])

    aspect = "square" if is_non_character_subject(text) else "portrait"
    if group_size >= 2:
        aspect = "landscape"

    return VersatileRoute(
        path="freeform",
        model=model,
        final_prompt=final_prompt,
        negative_extra=neg,
        use_registry=False,
        characters=[],
        registry_mode="freeform",
        fresh=True,
        group_size=group_size,
        batch_count=batch_count,
        tags="freeform,versatile",
        aspect=aspect,
        no_detailers=no_detailers,
    )


def main() -> int:
    import json
    import sys

    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "a red apple on a wooden table"
    print(json.dumps(route_image_prompt(prompt).to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())