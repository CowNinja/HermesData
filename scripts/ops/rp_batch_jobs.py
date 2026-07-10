"""Build Comfy variation-loop jobs from RenderFrame plans - sandbox canon enforced."""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path
from typing import Any

OPS = Path(__file__).resolve().parent

if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))

from rp_sandbox_paths import SANDBOX_LIB  # noqa: E402

from rp_batch_canon import (  # noqa: E402
    cast_canon_meta,
    enrich_scene,
    outfit_for_character,
    validate_cast_slugs,
)
from rp_batch_spec import RenderFrame, SeriesPlan  # noqa: E402

SEED_STEP = 9973
# Regional auto-route off until Phase 2b (IPAdapter) validates fidelity. Set RP_RENDER_REGIONAL_MIN=4 to re-enable.
REGIONAL_MIN = int(os.environ.get("RP_RENDER_REGIONAL_MIN", "99") or "99")


def render_path_for(chars: list[str]) -> str:
    """Monolithic for N<=3; regional area-conditioning for N>=REGIONAL_MIN."""
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))
    if str(SANDBOX_LIB) not in sys.path:
        sys.path.insert(0, str(SANDBOX_LIB))
    from prompt_compose import render_path_for_count  # noqa: WPS433

    return render_path_for_count(len(chars), threshold=REGIONAL_MIN)


def batch_speed_profile() -> dict[str, Any]:
    """Tune batch render cost vs quality. Env: RP_BATCH_SPEED=quality|fast|turbo."""
    mode = str(os.environ.get("RP_BATCH_SPEED", "quality") or "quality").strip().lower()
    if mode == "fast":
        return {"steps": 22, "hand_detailer_cycles": 1, "profile": "fast"}
    if mode == "turbo":
        return {"steps": 20, "hand_detailer_cycles": 0, "profile": "turbo"}
    return {"steps": 28, "hand_detailer_cycles": 3, "profile": "quality"}


def _load_registry():
    if str(SANDBOX_LIB) not in sys.path:
        sys.path.insert(0, str(SANDBOX_LIB))
    import visual_registry  # noqa: WPS433

    return visual_registry


def frame_to_job(
    vr,
    frame: RenderFrame,
    *,
    base_seed: int,
    index: int,
) -> dict[str, Any]:
    raw_chars = [c.strip().lower() for c in frame.characters if c.strip()]
    explicit_variant = frame.alternate.strip().lower().replace(" ", "-") if frame.alternate else ""
    mode = frame.mode or ("explicit" if raw_chars else "establishing")

    if not raw_chars and mode == "freeform":
        scene = (frame.object_prompt or frame.scene or "").strip()
        try:
            scripts = Path(r"D:\HermesData\scripts")
            if str(scripts) not in sys.path:
                sys.path.insert(0, str(scripts))
            from comfy_versatile_router import compose_freeform_prompt  # noqa: WPS433

            prompt, neg_extra = compose_freeform_prompt(scene or "detailed artistic scene")
        except Exception:
            prompt = scene or "detailed artistic scene"
            neg_extra = "worst quality, low quality, blurry, bad anatomy"
        seed = base_seed + index * SEED_STEP
        speed = batch_speed_profile()
        return {
            "slug": "freeform",
            "label": frame.label,
            "characters": [],
            "prompt": prompt,
            "seed": seed,
            "tags": "freeform,versatile,batch",
            "context": f"roleplay:freeform:batch:{index}",
            "negative_extra": neg_extra,
            "hand_detailer": False,
            "hand_detailer_cycles": 0,
            "steps": int(speed.get("steps") or 28),
            "speed_profile": str(speed.get("profile") or "quality"),
            "canon": [],
            "location": frame.location,
            "render_path": "monolithic",
        }

    chars = validate_cast_slugs(raw_chars)

    pose_clause = str(frame.scene or "").strip()
    outfit_clause = str(frame.object_prompt or "").strip()
    scene = enrich_scene(
        pose_clause,
        location=frame.location,
        characters=chars if frame.props else None,
        props=frame.props or None,
        object_prompt="",
    )

    outfit = ""
    if len(chars) == 1:
        outfit = outfit_for_character(chars[0], frame.outfit_overrides)
    elif len(chars) >= 2 and mode not in ("explicit",):
        pass

    render_path = render_path_for(chars)
    cfg = vr.load_visual_tags()
    regional_figures: list[dict[str, Any]] = []
    versatile_enriched = str(mode) in ("portrait", "tease", "scene", "explicit", "exposed_partial") and bool(chars)
    if versatile_enriched and len(chars) <= 3:
        try:
            scripts = Path(r"D:\HermesData\scripts")
            if str(SANDBOX_LIB) not in sys.path:
                sys.path.insert(0, str(SANDBOX_LIB))
            if str(scripts) not in sys.path:
                sys.path.insert(0, str(scripts))
            from prompt_compose import compose_cast_enriched  # noqa: WPS433

            prompt, neg_extra, tag_list = compose_cast_enriched(
                chars,
                user_scene=scene,
                pose_clause=pose_clause,
                outfit_clause=outfit_clause,
                mode=mode,
                canon_lock=False,
                explicit_variant="",
                cfg=cfg,
            )
            neg_prompt = f"{cfg.get('negative_base', '')}, {neg_extra}".strip(", ")
            seed = base_seed + index * SEED_STEP
            slug = "-".join(chars)
            speed = batch_speed_profile()
            return {
                "slug": slug,
                "label": frame.label,
                "characters": chars,
                "prompt": prompt,
                "seed": seed,
                "tags": ",".join(tag_list),
                "context": f"roleplay:{mode}:{slug}:enriched",
                "negative_extra": neg_prompt,
                "hand_detailer": len(chars) == 2 and int(speed.get("hand_detailer_cycles") or 0) > 0,
                "hand_detailer_cycles": int(speed.get("hand_detailer_cycles") or 3),
                "steps": int(speed.get("steps") or 28),
                "speed_profile": str(speed.get("profile") or "quality"),
                "canon": [cast_canon_meta(c) for c in chars],
                "location": frame.location,
                "render_path": render_path_for(chars),
            }
        except Exception:
            pass
    if render_path == "regional":
        if str(SANDBOX_LIB) not in sys.path:
            sys.path.insert(0, str(SANDBOX_LIB))
        from prompt_compose import compose_group_regional  # noqa: WPS433

        prompt, regional_figures, neg_extra, tag_list = compose_group_regional(
            chars,
            mode=mode,
            scene=scene,
            outfit_override=outfit,
            explicit_variant=explicit_variant,
            cfg=cfg,
        )
    else:
        prompt, neg_extra, tag_list = vr.build_prompt(
            mode=mode,
            characters=chars,
            scene=scene,
            outfit=outfit,
            explicit_variant=explicit_variant,
        )
    neg_prompt = f"{cfg.get('negative_base', '')}, {neg_extra}".strip(", ")
    seed = base_seed + index * SEED_STEP
    slug = "-".join(chars) if chars else "scene"
    if len(chars) == 2:
        ctx_variant = explicit_variant or "duo"
    elif len(chars) == 3:
        ctx_variant = explicit_variant or "trio"
    elif len(chars) > 3:
        ctx_variant = explicit_variant or "group"
    else:
        ctx_variant = explicit_variant or "portrait"
    canon = [cast_canon_meta(c) for c in chars]
    speed = batch_speed_profile()
    hand_detailer = len(chars) == 2 and int(speed.get("hand_detailer_cycles") or 0) > 0
    job: dict[str, Any] = {
        "slug": slug,
        "label": frame.label,
        "characters": chars,
        "prompt": prompt,
        "seed": seed,
        "tags": ",".join(tag_list),
        "context": f"roleplay:{mode}:{slug}:{ctx_variant}",
        "negative_extra": neg_prompt,
        "hand_detailer": hand_detailer,
        "hand_detailer_cycles": int(speed.get("hand_detailer_cycles") or 3),
        "steps": int(speed.get("steps") or 28),
        "speed_profile": str(speed.get("profile") or "quality"),
        "canon": canon,
        "location": frame.location,
        "render_path": render_path,
    }
    if regional_figures:
        job["regional_figures"] = regional_figures
    if len(chars) >= 4:
        # Landscape + lower CFG: crowd-control pattern for multi-subject (monolithic + regional)
        job["width"] = 1024
        job["height"] = 832
        job["cfg"] = 6.5
    return job


def jobs_from_plan(plan: SeriesPlan, *, base_seed: int | None = None) -> list[dict[str, Any]]:
    vr = _load_registry()
    seed_base = base_seed if base_seed is not None else random.randint(0, 2**32 - 1)
    return [
        frame_to_job(vr, frame, base_seed=seed_base, index=i)
        for i, frame in enumerate(plan.frames)
    ]