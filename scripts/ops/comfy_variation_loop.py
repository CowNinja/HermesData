#!/usr/bin/env python3
"""Queue a ComfyUI series in one session — seed increments, no per-image subprocess wait."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import sys
import time
from argparse import Namespace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SANDBOX_LIB = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\lib")
GENERATE_PY = Path(
    os.environ.get(
        "COMFY_GENERATE_PY",
        r"D:\HermesData\skills\creative\uncensored-image-generation\scripts\generate.py",
    )
)
RENDER_LOCK = Path(r"D:\HermesData\state\roleplay-render.lock")

if str(ROOT / "scripts" / "ops") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "ops"))

from comfy_queue_client import (  # noqa: E402
    comfy_up,
    extract_image_info,
    image_path_from_info,
    merge_metrics,
    queue_prompt,
    queue_status,
    wait_for_prompts,
)


def _load_generate():
    os.environ.setdefault("HERMES_PYTHONW_REEXEC", "1")
    spec = importlib.util.spec_from_file_location("comfy_generate", GENERATE_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {GENERATE_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_registry():
    if str(SANDBOX_LIB) not in sys.path:
        sys.path.insert(0, str(SANDBOX_LIB))
    import visual_registry  # noqa: WPS433

    return visual_registry


def _acquire_lock(timeout_sec: int = 60) -> bool:
    RENDER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with RENDER_LOCK.open("x", encoding="utf-8") as fh:
                fh.write(f"{os.getpid()}:{time.time():.0f}")
            return True
        except FileExistsError:
            time.sleep(1)
    return False


def _release_lock() -> None:
    try:
        RENDER_LOCK.unlink(missing_ok=True)
    except OSError:
        pass


def _build_args(
    gen,
    *,
    prompt: str,
    seed: int,
    tags: str,
    context: str,
    negative_extra: str,
    hand_detailer: bool,
    draft: bool,
) -> Namespace:
    m = gen.MODELS["pony"]
    return Namespace(
        model="pony",
        prompt=prompt,
        seed=seed,
        tags=tags,
        context=context,
        negative_extra=negative_extra,
        width=m["default_width"],
        height=m["default_height"],
        steps=m["default_steps"],
        cfg=m["default_cfg"],
        draft=draft,
        upscale=False,
        no_face_detailer=False,
        no_hand_detailer=not hand_detailer,
        no_detailers=False,
    )


def build_harem_job(
    vr,
    *,
    slug: str,
    label: str,
    alternate: str,
    scene: str,
    base_seed: int,
    index: int,
) -> dict[str, Any]:
    explicit_variant = alternate.strip().lower().replace(" ", "-") if alternate else ""
    prompt, neg_extra, tag_list = vr.build_prompt(
        mode="explicit",
        characters=[slug],
        scene=scene,
        explicit_variant=explicit_variant,
    )
    cfg = vr.load_visual_tags()
    neg_prompt = f"{cfg.get('negative_base', '')}, {neg_extra}".strip(", ")
    seed = base_seed + index * 9973
    return {
        "slug": slug,
        "label": label,
        "prompt": prompt,
        "seed": seed,
        "tags": ",".join(tag_list),
        "context": f"roleplay:explicit:{slug}:{explicit_variant or 'portrait'}",
        "negative_extra": neg_prompt,
        "hand_detailer": False,
    }


def run_jobs(
    jobs: list[dict[str, Any]],
    *,
    draft: bool = False,
    timeout_per_image: float = 900.0,
    seed_wildcard_step: int = 9973,
) -> dict[str, Any]:
    if not jobs:
        return {"ok": False, "error": "no_jobs"}
    if not comfy_up():
        return {"ok": False, "error": "comfy_down"}

    if not _acquire_lock():
        return {"ok": False, "error": "render_busy"}

    gen = _load_generate()
    started = time.time()
    prompt_ids: list[str] = []
    meta: list[dict[str, Any]] = []

    try:
        ids = gen.IDGen()
        base_seed = random.randint(0, 2**32 - 1)
        for i, job in enumerate(jobs):
            seed = int(job.get("seed") or (base_seed + i * seed_wildcard_step))
            args = _build_args(
                gen,
                prompt=str(job["prompt"]),
                seed=seed,
                tags=str(job.get("tags") or ""),
                context=str(job.get("context") or ""),
                negative_extra=str(job.get("negative_extra") or ""),
                hand_detailer=bool(job.get("hand_detailer")),
                draft=draft,
            )
            if draft:
                workflow = gen.build_draft_workflow(args, ids)
            else:
                workflow = gen.build_standard_workflow(args, ids)
            pid = queue_prompt(workflow)
            prompt_ids.append(pid)
            meta.append({**job, "prompt_id": pid, "seed": seed, "queued_at": time.strftime("%H:%M:%S")})

        q0 = queue_status()
        results = wait_for_prompts(
            prompt_ids,
            timeout=timeout_per_image * max(1, len(jobs)),
            since_ts=started,
        )

        completed: list[dict[str, Any]] = []
        for job, pid in zip(meta, prompt_ids):
            outputs = results.get(pid) or {}
            info = extract_image_info(outputs)
            if not info:
                completed.append({**job, "success": False, "error": "no_output"})
                continue
            src = image_path_from_info(info)
            gal_path = str(src)
            if not draft and src.is_file():
                m = gen.MODELS["pony"]
                gal_path, gal_name = gen.gallery_log(
                    str(src),
                    job["prompt"],
                    "pony",
                    job["seed"],
                    "standard",
                    negative=job.get("negative_extra") or "",
                    width=m["default_width"],
                    height=m["default_height"],
                    steps=m["default_steps"],
                    cfg=m["default_cfg"],
                    tags=job.get("tags") or "",
                    context=job.get("context") or "",
                )
                job["gallery_name"] = gal_name
            completed.append(
                {
                    **job,
                    "success": True,
                    "image": str(src),
                    "gallery_image": gal_path,
                    "png": src.name,
                }
            )

        elapsed = time.time() - started
        ok = sum(1 for r in completed if r.get("success"))
        report = {
            "ok": ok == len(jobs),
            "mode": "variation_loop",
            "queued": len(jobs),
            "completed": ok,
            "failed": len(jobs) - ok,
            "elapsed_sec": round(elapsed, 1),
            "avg_sec_per_image": round(elapsed / max(1, len(jobs)), 1),
            "queue_at_start": q0,
            "queue_at_end": queue_status(),
            "results": completed,
        }
        merge_metrics(
            {
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "last_variation_loop": report,
            }
        )
        return report
    finally:
        _release_lock()


def load_harem_portraits() -> list[tuple[str, str, str, str]]:
    harem_py = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\batch-harem-series.py")
    if not harem_py.is_file():
        return []
    spec = importlib.util.spec_from_file_location("batch_harem_series", harem_py)
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(getattr(mod, "PORTRAITS", []) or [])


def harem_jobs_from_portraits(
    portraits: list[tuple[str, str, str, str]],
    *,
    base_seed: int | None = None,
) -> list[dict[str, Any]]:
    vr = _load_registry()
    seed_base = base_seed if base_seed is not None else random.randint(0, 2**32 - 1)
    jobs: list[dict[str, Any]] = []
    for i, row in enumerate(portraits):
        slug, label, alternate, scene = row
        jobs.append(
            build_harem_job(
                vr,
                slug=slug,
                label=label,
                alternate=alternate,
                scene=scene,
                base_seed=seed_base,
                index=i,
            )
        )
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="ComfyUI variation loop — queue series without subprocess-per-image")
    parser.add_argument("--harem", action="store_true", help="Run built-in harem portrait series")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--jobs-json", default="", help="JSON list of job dicts")
    args = parser.parse_args()

    jobs: list[dict[str, Any]] = []
    if args.jobs_json:
        jobs = json.loads(args.jobs_json)
    elif args.harem:
        jobs = harem_jobs_from_portraits(load_harem_portraits())

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "jobs": len(jobs)}))
        return 0

    if not jobs:
        print(json.dumps({"ok": False, "error": "no_jobs"}))
        return 1

    report = run_jobs(jobs, draft=args.draft)
    print(json.dumps(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())