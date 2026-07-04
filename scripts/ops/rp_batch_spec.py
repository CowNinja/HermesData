"""First-principles RP batch series planning - any N, any cast, any scene recipe."""
from __future__ import annotations

import importlib.util
import itertools
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

OPS = Path(__file__).resolve().parent

if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))

from rp_sandbox_paths import BATCH_HAREM, BATCH_KITCHEN, SANDBOX, SANDBOX_LIB  # noqa: E402

CAST_ROSTER: tuple[str, ...] = (
    "alice",
    "chloe",
    "becca",
    "emily",
    "sassy",
    "lyra",
    "zara",
)

# Scene/pose rounds - cycled for variety when total > unique combinations
# Pose rounds - cycled when total > unique combination count; scene clauses scale to group_size.
GROUP_POSE_ROUNDS: list[tuple[str, str, str]] = [
    (
        "standing together",
        "",
        "standing side by side, arms around each other, full body, manor bedroom, silk sheets, warm golden cinematic lighting, looking at viewer, seductive",
    ),
    (
        "on all fours",
        "on-all-fours",
        "on all fours side by side, hands and knees, looking back at viewer, manor bedroom, silk sheets, soft golden lighting",
    ),
    (
        "reclining together",
        "",
        "reclining together on silk sheets, intimate pose, full body, warm golden bedroom lighting, looking at viewer",
    ),
    (
        "kneeling together",
        "",
        "kneeling on bed facing viewer, hands on thighs, seductive smiles, manor bedroom, soft pink and golden ambient light",
    ),
]

PAIR_POSE_ROUNDS: list[tuple[str, str, str]] = [
    (
        "standing together",
        "",
        "two girls standing side by side, arms around each other, full body, manor bedroom, silk sheets, warm golden cinematic lighting, looking at viewer, seductive",
    ),
    (
        "on all fours duo",
        "on-all-fours",
        "two girls on all fours side by side, hands and knees, looking back at viewer, manor bedroom, silk sheets, soft golden lighting",
    ),
    (
        "reclining together",
        "",
        "two girls reclining together on silk sheets, intimate pose, full body, warm golden bedroom lighting, looking at viewer",
    ),
    (
        "kneeling duo",
        "",
        "two girls kneeling on bed facing viewer, hands on thighs, seductive smiles, manor bedroom, soft pink and golden ambient light",
    ),
]

@dataclass
class RenderFrame:
    """One queued image - 1..N characters (solo / duo / trio / group)."""

    characters: list[str]
    mode: str = "explicit"
    scene: str = ""
    alternate: str = ""
    label: str = ""
    location: str = ""
    props: list[str] = field(default_factory=list)
    object_prompt: str = ""
    outfit_overrides: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SeriesPlan:
    series: str
    recipe: str
    total: int
    frames: list[RenderFrame] = field(default_factory=list)

    @property
    def labels(self) -> list[str]:
        return [f.label for f in self.frames[: self.total]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "series": self.series,
            "recipe": self.recipe,
            "total": self.total,
            "labels": self.labels,
            "frames": [f.to_dict() for f in self.frames],
        }


def _display(slug: str) -> str:
    return slug.strip().capitalize()


def _group_label(chars: tuple[str, ...] | list[str], pose_label: str) -> str:
    names = " & ".join(_display(c) for c in chars)
    return f"{names} - {pose_label}"


def _pair_label(a: str, b: str, pose_label: str) -> str:
    return _group_label((a, b), pose_label)


def _roster_cap(prompt: str, spec: dict | None) -> int:
    roster = roster_from_text(prompt, spec or {})
    return max(1, len(roster))


_WORD_TO_GIRL_COUNT = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
}

# Numeric or word count with optional intervening tokens ("four harem girls", "4 naked girls").
_GIRL_COUNT_RE = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven)\s+(?:\w+\s+){0,6}girls?\b",
    re.I,
)


def _token_to_girl_count(token: str) -> int:
    tok = str(token or "").strip().lower()
    if tok.isdigit():
        return int(tok)
    return int(_WORD_TO_GIRL_COUNT.get(tok, 0))


def _extract_freeform_scene_clause(text: str) -> str:
    """When no hint table matches, pass through the user's location/mood words verbatim."""
    body = re.sub(r"^OOC:\s*", "", text or "", flags=re.I).strip()
    body = re.sub(r"\b(?:series|batch)\s+of\s+\d+\s+images?\b", "", body, flags=re.I)
    body = re.sub(_GIRL_COUNT_RE, "", body)
    body = re.sub(r"\b(?:harem\s+)?girls?\s+together\b", "", body, flags=re.I)
    body = re.sub(r"\b(?:together|explicit|varied\s+poses?)\b", "", body, flags=re.I)
    body = re.sub(r"\s+", " ", body).strip(" ,.-")
    return body if len(body) >= 6 else ""


def batch_intent_signature(prompt: str, spec: dict | None = None) -> str:
    """Stable fingerprint for resume-vs-fresh decisions — no hardcoded scene names."""
    enriched = enrich_spec_from_intent(prompt, spec or {})
    merged = merge_intent_texts(prompt, str((spec or {}).get("_inbound_text") or ""), enriched)
    core = re.sub(r"\s+", " ", merged.lower()).strip()[:400]
    return "|".join(
        [
            str(enriched.get("batch_recipe") or ""),
            str(enriched.get("group_size") or ""),
            str(enriched.get("batch_count") or ""),
            str(enriched.get("scene") or "").strip().lower()[:200],
            core,
        ]
    )


def infer_scene_fragment(prompt: str, spec: dict | None = None) -> str:
    """Extract freeform scene/location clause from OOC for any series (Swiss-army-knife hook)."""
    spec = spec or {}
    if spec.get("scene") or spec.get("scene_override"):
        return str(spec.get("scene") or spec.get("scene_override") or "").strip()
    lower = (prompt or "").lower()
    hints: list[tuple[str, str]] = [
        (r"\bmanor\s+bath\b", "manor bath, marble steam room, golden hour light, steam rising"),
        (r"\broman\s+bath\b", "roman bath, steam rising, golden hour light, marble tiles"),
        (r"\bkitchen\b", "manor kitchen, marble counters, warm overhead lighting"),
        (r"\bpool\b|\bpoolside\b", "outdoor poolside, sunlit water, lounge chairs"),
        (r"\bgarden\b", "manor garden, lush greenery, soft afternoon light"),
        (r"\bbedroom\b|\bmanor\s+bedroom\b", "manor bedroom, silk sheets, warm golden cinematic lighting"),
        (r"\bnursery\b", "manor nursery, soft pink ambient light, plush carpet"),
        (r"\bnight\b|\bat\s+night\b", "nighttime, moonlit windows, soft lamp glow"),
        (r"\bsteam(y|ing)?\b", "steamy atmosphere, warm humid air, glistening skin"),
        (r"\bgolden\s+hour\b", "golden hour lighting, warm cinematic glow"),
        (r"\bvaried\s+angles?\b", "varied camera angles, dynamic composition, multiple viewpoints"),
    ]
    for pattern, clause in hints:
        if re.search(pattern, lower):
            return clause
    freeform = _extract_freeform_scene_clause(prompt or "")
    return freeform


def merge_intent_texts(prompt: str, inbound_text: str = "", spec: dict | None = None) -> str:
    """Canonical merged OOC for inference (inbound wins over rewritten LLM prompt)."""
    spec = spec or {}
    texts = [t.strip() for t in (inbound_text, prompt, str(spec.get("scene") or "")) if t and t.strip()]
    return "\n".join(dict.fromkeys(texts)) or (prompt or "")


def enrich_spec_from_intent(
    prompt: str,
    spec: dict | None = None,
    *,
    inbound_text: str = "",
) -> dict[str, Any]:
    """Swiss-army-knife: derive batch_count, group_size, recipe, scene from any OOC phrasing."""
    spec = dict(spec or {})
    merged = merge_intent_texts(prompt, inbound_text, spec)
    group_size = int(spec.get("group_size") or 0) or infer_group_size(merged, spec)
    if group_size >= 2:
        spec["group_size"] = group_size
    recipe = str(spec.get("batch_recipe") or detect_recipe(merged, spec))
    spec["batch_recipe"] = recipe
    scene_frag = infer_scene_fragment(merged, spec)
    if scene_frag and not spec.get("scene"):
        spec["scene"] = scene_frag
    count = int(spec.get("batch_count") or 0)
    if count < 2:
        try:
            if str(SANDBOX_LIB) not in sys.path:
                sys.path.insert(0, str(SANDBOX_LIB))
            from visual_registry import _series_count  # noqa: WPS433

            count = max(count, int(_series_count(merged) or 0))
        except Exception:
            pass
    if count < 2:
        lower = merged.lower()
        if re.search(r"\b(?:one|a)\s+(?:portrait|image|picture)\s+per\s+harem\s+girl\b", lower):
            count = len(CAST_ROSTER)
        elif "harem girl" in lower and any(k in lower for k in ("each", "every", "per girl")):
            count = len(CAST_ROSTER)
        elif re.search(r"\bpair(?:s)?\s+of\s+(?:girls?|harem)\b", lower):
            m = re.search(r"\b(?:series|batch)\s+of\s+(\d+)\b", lower)
            count = int(m.group(1)) if m else 14
        elif group_size >= 2:
            m = re.search(r"\b(?:series|batch)\s+of\s+(\d+)\b", lower)
            count = int(m.group(1)) if m else max(7, group_size)
    if count >= 2:
        spec["batch_count"] = count
    return spec


def _apply_user_scene_to_frame(frame: RenderFrame, scene_frag: str) -> None:
    """User OOC location overrides template bedroom/kitchen stubs."""
    if not scene_frag:
        return
    base = str(frame.scene or "").strip()
    if scene_frag.lower() in base.lower():
        return
    for stub in (
        "manor bedroom, silk sheets, warm golden cinematic lighting",
        "manor bedroom, silk sheets, soft golden lighting",
        "manor bedroom",
        "silk sheets",
    ):
        base = re.sub(re.escape(stub), "", base, flags=re.I)
    base = re.sub(r",\s*,", ",", base).strip(" ,")
    frame.scene = f"{base}, {scene_frag}".strip(", ") if base else scene_frag


def infer_group_size(prompt: str, spec: dict | None = None) -> int:
    """Parse how many girls per frame (1=solo, 2=pair, 3=triplet, N=group). No hard cap beyond roster."""
    spec = spec or {}
    cap = _roster_cap(prompt, spec)
    if spec.get("group_size"):
        return max(1, min(cap, int(spec["group_size"])))
    lower = (prompt or "").lower()
    if re.search(r"\b(entire\s+harem|all\s+(?:seven|7)\s+(?:harem\s+)?girls?|full\s+harem)\b", lower):
        return cap
    if re.search(r"\bentire\s+cast\b|\ball\s+girls\b", lower):
        return cap
    explicit = 0
    for match in _GIRL_COUNT_RE.finditer(lower):
        n = _token_to_girl_count(match.group(1))
        if n >= 2:
            explicit = max(explicit, n)
    if explicit >= 2:
        return min(cap, explicit)
    if re.search(r"\b(sextet|six\s+girls?|6\s*girls?)\b", lower):
        return min(cap, 6)
    if re.search(r"\b(quintet|five\s+girls?|5\s*girls?)\b", lower):
        return min(cap, 5)
    if re.search(r"\b(quartet|four\s+girls?|4\s*girls?)\b", lower):
        return min(cap, 4)
    if re.search(r"\b(triplet|triplets|trio|three\s+girls?|3\s*girls?)\b", lower):
        return min(cap, 3)
    if re.search(r"\b(pair|pairs|duo|duos|two\s+girls?|2\s*girls?|couple)\b", lower):
        return 2
    return 1


def _group_scene_clause(group_size: int, scene_template: str) -> str:
    if group_size <= 1:
        return scene_template
    prefix = f"{group_size} girls "
    if scene_template.startswith("standing"):
        return prefix + scene_template
    if scene_template.startswith("on all fours"):
        return prefix + scene_template
    if scene_template.startswith("reclining"):
        return prefix + scene_template
    if scene_template.startswith("kneeling"):
        return prefix + scene_template
    return f"{group_size} girls {scene_template}"


def roster_from_text(text: str, spec: dict | None = None) -> list[str]:
    if spec:
        chars = [str(c).lower().strip() for c in (spec.get("characters") or []) if c]
        if chars:
            order = {s: i for i, s in enumerate(CAST_ROSTER)}
            return sorted(chars, key=lambda s: order.get(s, 99))
    lower = (text or "").lower()
    found = [s for s in CAST_ROSTER if re.search(rf"\b{s}\b", lower)]
    return found or list(CAST_ROSTER)


def infer_batch_intent(
    prompt: str,
    *,
    inbound_text: str = "",
    spec: dict | None = None,
) -> tuple[int, str, str]:
    """Return (count, delegate_prompt, recipe). count=0 means no batch delegation."""
    delegate = inbound_text.strip() if inbound_text.strip() else prompt
    enriched = enrich_spec_from_intent(prompt, spec, inbound_text=inbound_text)
    count = int(enriched.get("batch_count") or 0)
    recipe = str(enriched.get("batch_recipe") or detect_recipe(delegate, enriched))
    return count, delegate, recipe


def detect_recipe(prompt: str, spec: dict | None = None) -> str:
    spec = spec or {}
    if spec.get("batch_recipe"):
        return str(spec["batch_recipe"])
    gs = infer_group_size(prompt, spec)
    if gs >= 4:
        return "harem_group"
    if gs == 3:
        return "harem_triplets"
    if gs == 2:
        return "harem_pairs"
    lower = (prompt or "").lower()
    if any(
        k in lower
        for k in (
            "pair",
            "pairs",
            "duo",
            "duos",
            "two girls",
            "2 girls",
            "couple",
        )
    ):
        return "harem_pairs"
    if any(k in lower for k in ("crawl", "crawling", "kitchen")):
        return "kitchen_crawl"
    if any(k in lower for k in ("harem girl", "harem girls", "per harem", "harem portrait")):
        return "harem_solo"
    if "portrait" in lower and any(s in lower for s in CAST_ROSTER):
        return "harem_solo"
    return str(spec.get("batch_recipe") or "harem_solo")


def series_name_for_recipe(recipe: str, *, group_size: int = 0) -> str:
    if recipe == "harem_group" and group_size:
        return f"Harem group ({group_size})"
    return {
        "harem_solo": "Harem portraits",
        "harem_pairs": "Harem pairs",
        "harem_triplets": "Harem triplets",
        "harem_group": "Harem group",
        "kitchen_crawl": "Kitchen crawl",
        "custom": "Custom series",
    }.get(recipe, recipe.replace("_", " ").title())


def recipe_for_group_size(group_size: int) -> str:
    return {
        1: "harem_solo",
        2: "harem_pairs",
        3: "harem_triplets",
    }.get(group_size, "harem_group")


def build_group_frames(roster: list[str], group_size: int, total: int) -> list[RenderFrame]:
    """Universal N-girl combinations - any group_size >= 1, any total."""
    if group_size < 1:
        return []
    if group_size == 1:
        return build_solo_frames(total)
    combos = list(itertools.combinations(roster, group_size))
    if not combos:
        return []
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))
    from batch_series_pool import expand_pool  # noqa: WPS433

    rounds = GROUP_POSE_ROUNDS if group_size != 2 else PAIR_POSE_ROUNDS
    slots = expand_pool(combos, total)
    frames: list[RenderFrame] = []
    for i, combo in enumerate(slots):
        pose_label, alternate, scene_tpl = rounds[i % len(rounds)]
        scene = _group_scene_clause(group_size, scene_tpl)
        frames.append(
            RenderFrame(
                characters=list(combo),
                mode="explicit",
                scene=scene,
                alternate=alternate,
                label=_group_label(combo, pose_label),
            )
        )
    return frames


def build_pair_frames(roster: list[str], total: int) -> list[RenderFrame]:
    return build_group_frames(roster, 2, total)


def build_triplet_frames(roster: list[str], total: int) -> list[RenderFrame]:
    return build_group_frames(roster, 3, total)


def build_solo_frames(total: int) -> list[RenderFrame]:
    harem_py = BATCH_HAREM
    if not harem_py.is_file():
        return []
    spec = importlib.util.spec_from_file_location("batch_harem_series", harem_py)
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    portraits = list(getattr(mod, "PORTRAITS", []) or [])
    alt_rounds = list(getattr(mod, "PORTRAITS_ALT_ROUNDS", []) or [])
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))
    from batch_series_pool import expand_pool  # noqa: WPS433

    def _round_label(item: tuple[str, str, str, str], round_idx: int) -> tuple[str, str, str, str]:
        slug, label, alternate, scene = item
        return (slug, f"{label} (pass {round_idx + 1})", alternate, scene)

    pool = expand_pool(portraits, total, rounds=alt_rounds, decorate=_round_label)
    return [
        RenderFrame(
            characters=[slug],
            mode="explicit",
            scene=scene,
            alternate=alternate,
            label=f"{_display(slug)} - {label}",
        )
        for slug, label, alternate, scene in pool
    ]


def build_kitchen_frames(total: int) -> list[RenderFrame]:
    kitchen_py = BATCH_KITCHEN
    if not kitchen_py.is_file():
        return []
    spec = importlib.util.spec_from_file_location("batch_kitchen", kitchen_py)
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    variations = list(getattr(mod, "VARIATIONS", []) or [])
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))
    from batch_series_pool import expand_pool  # noqa: WPS433

    def _pass_label(item: tuple[str, str], round_idx: int) -> tuple[str, str]:
        label, scene = item
        return (f"{label} (pass {round_idx + 1})", scene)

    pool = expand_pool(variations, total, decorate=_pass_label)
    return [
        RenderFrame(
            characters=["alice", "chloe"],
            mode="explicit",
            scene=scene,
            alternate="on-all-fours",
            label=f"Alice & Chloe - {label}",
        )
        for label, scene in pool
    ]


def build_custom_frames(spec: dict) -> list[RenderFrame]:
    raw = spec.get("frames") or spec.get("jobs") or []
    frames: list[RenderFrame] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        chars = [str(c).lower() for c in (item.get("characters") or item.get("character") or [])]
        if isinstance(item.get("character"), str):
            chars = [item["character"].lower()]
        frames.append(
            RenderFrame(
                characters=chars,
                mode=str(item.get("mode") or "explicit"),
                scene=str(item.get("scene") or ""),
                alternate=str(item.get("alternate") or ""),
                label=str(item.get("label") or ""),
            )
        )
    return frames


def resolve_series_plan(
    prompt: str,
    spec: dict | None = None,
    *,
    total: int | None = None,
    recipe: str | None = None,
) -> SeriesPlan:
    spec = dict(spec or {})
    if str(SANDBOX_LIB) not in sys.path:
        sys.path.insert(0, str(SANDBOX_LIB))
    try:
        from visual_registry import _series_count  # noqa: WPS433

        inferred = int(_series_count(prompt or "") or 0)
    except Exception:
        inferred = 0
    count = total or int(spec.get("batch_count") or 0) or inferred
    if count < 1:
        count = len(CAST_ROSTER)
    recipe_use = recipe or detect_recipe(prompt, spec)
    roster = roster_from_text(prompt, spec)

    if recipe_use == "custom" or spec.get("frames") or spec.get("jobs"):
        frames = build_custom_frames(spec)
        if not frames and spec.get("plan_json"):
            try:
                plan_data = json.loads(spec["plan_json"])
                frames = build_custom_frames(plan_data)
            except json.JSONDecodeError:
                pass
        recipe_use = "custom"
    elif recipe_use in ("harem_pairs", "harem_triplets", "harem_group"):
        gs = {
            "harem_pairs": 2,
            "harem_triplets": 3,
        }.get(recipe_use) or int(spec.get("group_size") or infer_group_size(prompt, spec))
        gs = max(2, gs) if recipe_use != "harem_group" else max(2, gs)
        if recipe_use == "harem_group":
            gs = max(2, int(spec.get("group_size") or infer_group_size(prompt, spec)))
        frames = build_group_frames(roster, gs, count)
        recipe_use = recipe_for_group_size(gs) if gs <= 3 else "harem_group"
    elif recipe_use == "kitchen_crawl":
        frames = build_kitchen_frames(count)
    else:
        frames = build_solo_frames(count)
        recipe_use = "harem_solo"

    if not frames:
        raise ValueError(f"no_frames_for_recipe:{recipe_use}")

    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))
    from rp_batch_canon import plan_canon_audit, validate_cast_slugs  # noqa: WPS433

    for frame in frames[:count]:
        validate_cast_slugs([c.lower() for c in frame.characters])
    _ = plan_canon_audit(frames[:count])

    gs_final = len(frames[0].characters) if frames else 0
    series = str(
        spec.get("series_name")
        or series_name_for_recipe(recipe_use, group_size=gs_final)
    )
    default_location = str(spec.get("location") or spec.get("current_location") or "")
    merged = merge_intent_texts(prompt, str(spec.get("_inbound_text") or ""), spec)
    scene_frag = infer_scene_fragment(merged, spec) or str(spec.get("scene") or "").strip()
    for frame in frames[:count]:
        if default_location and not frame.location:
            frame.location = default_location
        _apply_user_scene_to_frame(frame, scene_frag)

    return SeriesPlan(series=series, recipe=recipe_use, total=count, frames=frames[:count])


def compose_series_from_intent(
    prompt: str,
    spec: dict | None = None,
    *,
    total: int | None = None,
    recipe: str | None = None,
) -> SeriesPlan:
    """Single Swiss-army-knife entry: any N series, any group size, any scene from OOC or spec."""
    return resolve_series_plan(prompt, spec, total=total, recipe=recipe)


def slice_plan(plan: SeriesPlan, *, offset: int = 0, limit: int = 0) -> SeriesPlan:
    frames = plan.frames[offset:]
    if limit and limit > 0:
        frames = frames[:limit]
    return SeriesPlan(
        series=plan.series,
        recipe=plan.recipe,
        total=plan.total,
        frames=frames,
    )