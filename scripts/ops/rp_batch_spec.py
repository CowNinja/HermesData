#!/usr/bin/env python3
"""First-principles RP batch series planning - any N, any cast, any scene recipe. ASCII only."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class RenderFrame:
    characters: List[str]
    mode: str = "portrait"
    scene: str = ""
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "characters": self.characters,
            "mode": self.mode,
            "scene": self.scene,
            "label": self.label,
        }


def _make_frame_label(slug: str, idx: int, total: int, prompt: str = "", scene: str = "") -> str:
    """Rich per-character or descriptive label. ASCII only."""
    lower = (prompt or "").lower()
    core = slug.title()
    if "base" in lower or "profile" in lower:
        core += " - base profile"
    elif "explicit" in lower:
        core += " - explicit"
    if "hands and knees" in lower or "on all fours" in lower:
        core += " - hands & knees"
    elif "nude" in lower or "naked" in lower:
        core += " - nude"
    if total > 1:
        return f"{core} - {idx + 1}/{total}"
    return core


def _group_label(chars: List[str], pose: str, idx: int, total: int, requested_gs: int = 0) -> str:
    gs = requested_gs or len(chars)
    names = " & ".join(c.title() for c in chars)
    if total > 1:
        return f"{gs} girls ({names}) - {pose} - {idx + 1}/{total}"
    return f"{len(chars)} girls ({names}) - {pose}"


def infer_group_size(prompt: str, spec: Optional[dict] = None) -> int:
    """Parse N from prompt. Explicit group of N wins for combined."""
    lower = (prompt or "").lower()
    if spec and spec.get("group_size"):
        return max(1, int(spec["group_size"]))
    m = re.search(r"group of (\d+)", lower)
    if m:
        return max(1, int(m.group(1)))
    m = re.search(r"(\d+) girls?", lower)
    if m:
        return max(1, int(m.group(1)))
    if ("amira" in lower and "aisha" in lower) and ("base" in lower or "profile" in lower) and "explicit" in lower:
        return 6
    if "twins" in lower or "two girls" in lower:
        return 2
    return 1


def _is_explicit_group(prompt: str) -> bool:
    return "group of" in (prompt or "").lower()


def build_user_cast_frames(
    total: int,
    prompt: str = "",
    roster: Optional[List[str]] = None,
    group_size: int = 0,
) -> List[RenderFrame]:
    """Build frames. Combined for group of N, per-character otherwise."""
    roster = roster or ["amira", "aisha"]
    gs = group_size or infer_group_size(prompt)
    explicit_group = _is_explicit_group(prompt)
    lower = (prompt or "").lower()
    frames: List[RenderFrame] = []
    pose = "hands & knees" if "hands" in lower else ("nude" if "nude" in lower else "base")
    if explicit_group and gs >= 2:
        for i in range(total):
            chars = roster[: min(gs, len(roster))]
            label = _group_label(chars, pose, i, total, requested_gs=gs)
            frames.append(RenderFrame(characters=chars, scene=prompt, label=label))
        return frames
    for i in range(total):
        slug = roster[i % len(roster)]
        label = _make_frame_label(slug, i, total, prompt)
        frames.append(RenderFrame(characters=[slug], scene=prompt, label=label))
    return frames


@dataclass
class SeriesPlan:
    series: str = "Series"
    total: int = 1
    frames: List[RenderFrame] = field(default_factory=list)
    recipe: str = "freeform"


def detect_recipe(prompt: str, spec: Optional[dict] = None) -> str:
    """Prompt-first recipe picker used by the batch orchestrator."""
    spec = spec or {}
    if spec.get("batch_recipe"):
        return str(spec["batch_recipe"])
    if spec.get("recipe"):
        return str(spec["recipe"])
    lower = (prompt or "").lower()
    if re.search(r"\bkitchen\s+crawl\b", lower) or (
        re.search(r"\bcrawl(?:ing)?\b", lower) and re.search(r"\bkitchen\b", lower)
    ):
        return "kitchen_crawl"
    if re.search(r"\btriplet\b|\bthree girls\b|\b3 girls\b", lower):
        return "harem_triplets"
    if re.search(r"\bpair\b|\btwo girls\b|\b2 girls\b|\bduo\b", lower) and "series" in lower:
        return "harem_pairs"
    if re.search(r"\bgroup of\s*\d+\b|\ball together\b|\bgroup portrait\b", lower):
        return "harem_group"
    if re.search(r"\bone of each\b|\bper harem\b|\bharem portrait\b|\bshowcase\b", lower):
        return "harem_solo"
    if re.search(r"\bseries\b|\bbatch\b", lower):
        return "freeform_series"
    return "freeform"


def resolve_series_plan(
    prompt: str,
    spec: Optional[dict] = None,
    total: Optional[int] = None,
    recipe: Optional[str] = None,
    **_kwargs: Any,
) -> SeriesPlan:
    spec = spec or {}
    gs = infer_group_size(prompt, spec)
    requested = total or int(spec.get("batch_count") or 0) or gs or 1
    explicit_group = _is_explicit_group(prompt)
    frames = build_user_cast_frames(
        requested, prompt=prompt, group_size=gs if explicit_group else 1
    )
    recipe_use = recipe or detect_recipe(prompt, spec)
    series = "Series" if explicit_group or requested >= 2 else "Individual"
    return SeriesPlan(
        total=len(frames),
        frames=frames,
        series=str(spec.get("series_name") or series),
        recipe=recipe_use,
    )


def compose_series_from_intent(
    prompt: str, spec: Optional[dict] = None, total: Optional[int] = None
) -> SeriesPlan:
    return resolve_series_plan(prompt, spec, total=total)


def infer_batch_intent(prompt: str, inbound_text: str = "") -> tuple:
    """Compatibility shim for image_generation_tool pre-delegation.

    Returns (count, delegate_prompt, recipe).
    """
    text = (prompt or "").strip()
    if inbound_text:
        text = (text + "\n" + inbound_text).strip()
    plan = resolve_series_plan(text)
    count = max(int(plan.total or 0), 0)
    recipe = plan.recipe or "freeform"
    return count, text, recipe


def enrich_spec_from_intent(
    prompt: str, spec: Optional[dict] = None, inbound_text: str = ""
) -> dict:
    """Merge series plan fields into a batch spec dict (ASCII-safe)."""
    base = dict(spec or {})
    text = (prompt or "").strip()
    if inbound_text:
        text = (text + "\n" + inbound_text).strip()
    plan = resolve_series_plan(text, base)
    base.setdefault("batch_mode", "series")
    base["total"] = int(plan.total or base.get("total") or 1)
    base["batch_count"] = int(base.get("batch_count") or plan.total or 1)
    base["recipe"] = plan.recipe or base.get("recipe") or "freeform"
    base["series"] = plan.series or base.get("series") or "Series"
    base["group_size"] = int(base.get("group_size") or infer_group_size(text, base) or 0)
    return base


def merge_intent_texts(prompt: str, inbound_text: str = "", spec: Optional[dict] = None) -> str:
    """Merge OOC prompt fragments for signature + planning."""
    spec = spec or {}
    texts: list[str] = []
    if (inbound_text or "").strip():
        texts.append(inbound_text.strip())
    elif spec.get("_inbound_text"):
        texts.append(str(spec["_inbound_text"]).strip())
    if (prompt or "").strip():
        texts.append(prompt.strip())
    scene_extra = str(spec.get("scene") or "").strip()
    if scene_extra:
        texts.append(scene_extra)
    return "\n".join(dict.fromkeys(t for t in texts if t)) or (prompt or "")


def batch_intent_signature(prompt: str, spec: Optional[dict] = None) -> str:
    """Stable fingerprint for resume-vs-fresh decisions (orchestrator preflight)."""
    spec = spec or {}
    enriched = enrich_spec_from_intent(prompt, spec)
    merged = merge_intent_texts(prompt, str(spec.get("_inbound_text") or ""), enriched)
    core = re.sub(r"\s+", " ", merged.lower()).strip()[:400]
    recipe = str(enriched.get("recipe") or detect_recipe(prompt, enriched) or "")
    gs = str(enriched.get("group_size") or infer_group_size(prompt, enriched) or "")
    count = str(enriched.get("batch_count") or enriched.get("total") or "")
    scene = str(enriched.get("scene") or "").strip().lower()[:200]
    return "|".join([recipe, gs, count, scene, core])


def slice_plan(plan: SeriesPlan, *, offset: int = 0, limit: int = 0) -> SeriesPlan:
    """Slice frames for resume (offset/limit) without changing plan.total identity."""
    frames = list(plan.frames[offset:])
    if limit and limit > 0:
        frames = frames[:limit]
    return SeriesPlan(
        series=plan.series,
        recipe=plan.recipe,
        total=plan.total,
        frames=frames,
    )


def infer_scene_fragment(prompt: str, spec: Optional[dict] = None) -> str:
    """Short location/mood fragment if present."""
    spec = spec or {}
    if spec.get("scene") or spec.get("scene_override"):
        raw = str(spec.get("scene") or spec.get("scene_override") or "").strip()
        if len(raw) < 160:
            return raw
    lower = (prompt or "").lower()
    for key in (
        "kitchen",
        "manor",
        "bedroom",
        "garden",
        "bath",
        "pool",
        "beach",
        "courtyard",
        "dawn",
        "candlelit",
        "library",
    ):
        if key in lower:
            return key
    return ""


def build_caption(
    plan=None,
    frame=None,
    png_name: str = "",
    labels=None,
    index: Optional[int] = None,
    series: str = "Series",
) -> str:
    """Single source. Prefers rich label. ASCII only."""
    if frame and frame.label:
        base = frame.label
        return base + (f" - {png_name}" if png_name else "")
    if labels and index is not None:
        base = labels[index]
        return base + (f" - {png_name}" if png_name else "")
    return (series + " " + (png_name or "")).strip()
