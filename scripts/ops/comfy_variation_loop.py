#!/usr/bin/env python3
"""Queue a ComfyUI series in one session - seed increments, no per-image subprocess wait."""
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
    clear_queue,
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


def _lock_holder_alive() -> bool:
    if not RENDER_LOCK.is_file():
        return False
    try:
        raw = RENDER_LOCK.read_text(encoding="utf-8").strip()
        pid = int(raw.split(":", 1)[0])
    except (ValueError, OSError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        access = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(access, False, int(pid))
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _clear_stale_render_lock() -> bool:
    if not RENDER_LOCK.is_file():
        return False
    if _lock_holder_alive():
        return False
    try:
        RENDER_LOCK.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _acquire_lock(timeout_sec: int = 60) -> bool:
    RENDER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        _clear_stale_render_lock()
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
    steps: int | None = None,
    hand_detailer_cycles: int = 3,
    width: int | None = None,
    height: int | None = None,
    cfg: float | None = None,
    filename_prefix: str = "",
    mode: str = "varied",
) -> Namespace:
    m = gen.MODELS["pony"]
    return Namespace(
        model="pony",
        prompt=prompt,
        seed=seed,
        tags=tags,
        context=context,
        negative_extra=negative_extra,
        width=width or m["default_width"],
        height=height or m["default_height"],
        steps=steps or m["default_steps"],
        cfg=cfg if cfg is not None else m["default_cfg"],
        draft=draft,
        upscale=False,
        no_face_detailer=False,
        no_hand_detailer=not hand_detailer,
        no_detailers=False,
        hand_detailer_cycles=max(1, int(hand_detailer_cycles or 3)),
        filename_prefix=filename_prefix or "",
        mode=mode,
    )


def _user_outfit_overlay() -> str:
    """Pull OOC outfit/scene prose from last inbound (versatile batch hook)."""
    inbound = Path(r"D:\HermesData\state\rp-last-inbound.json")
    if not inbound.is_file():
        return ""
    try:
        import json

        data = json.loads(inbound.read_text(encoding="utf-8-sig"))
        text = str(data.get("text") or "").strip()
        if not text:
            return ""
        ops = Path(__file__).resolve().parent
        if str(ops) not in sys.path:
            sys.path.insert(0, str(ops))
        from rp_batch_spec import infer_scene_fragment  # noqa: WPS433

        return infer_scene_fragment(text, {})
    except Exception:
        return ""


def build_harem_job(
    vr,
    *,
    slug: str,
    label: str,
    alternate: str,
    scene: str,
    base_seed: int,
    index: int,
    outfit_overlay: str = "",
    mode: str = "portrait",
) -> dict[str, Any]:
    explicit_variant = alternate.strip().lower().replace(" ", "-") if alternate else ""
    overlay = (outfit_overlay or _user_outfit_overlay()).strip()
    scene_merged = ", ".join(x for x in [scene.strip(), overlay] if x)
    cfg = vr.load_visual_tags()
    prompt = ""
    neg_extra = ""
    tag_list: list[str] = []
    try:
        sandbox_lib = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\lib")
        if str(sandbox_lib) not in sys.path:
            sys.path.insert(0, str(sandbox_lib))
        from prompt_compose import compose_cast_enriched  # noqa: WPS433

        prompt, neg_extra, tag_list = compose_cast_enriched(
            [slug],
            user_scene=scene_merged,
            mode=mode,
            canon_lock=False,
            explicit_variant=explicit_variant,
            cfg=cfg,
        )
    except Exception:
        prompt, neg_extra, tag_list = vr.build_prompt(
            mode=mode,
            characters=[slug],
            scene=scene_merged,
            explicit_variant=explicit_variant,
        )
    neg_prompt = f"{cfg.get('negative_base', '')}, {neg_extra}".strip(", ")
    seed = base_seed + index * 9973
    return {
        "slug": slug,
        "label": label,
        "prompt": prompt,
        "seed": seed,
        "tags": ",".join(tag_list),
        "context": f"roleplay:{mode}:{slug}:{explicit_variant or 'enriched'}",
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

    clear_queue()

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
            render_path = str(job.get("render_path") or "monolithic")
            if draft:
                fname_prefix = "draft_"
            else:
                # Same Comfy prefix as monolithic (standard_ -> standard__00209_.png)
                fname_prefix = "standard_"
            args = _build_args(
                gen,
                prompt=str(job["prompt"]),
                seed=seed,
                tags=str(job.get("tags") or ""),
                context=str(job.get("context") or ""),
                negative_extra=str(job.get("negative_extra") or ""),
                hand_detailer=bool(job.get("hand_detailer")),
                draft=draft,
                steps=int(job["steps"]) if job.get("steps") else None,
                hand_detailer_cycles=int(job.get("hand_detailer_cycles") or 3),
                width=int(job["width"]) if job.get("width") else None,
                height=int(job["height"]) if job.get("height") else None,
                cfg=float(job["cfg"]) if job.get("cfg") is not None else None,
                filename_prefix=fname_prefix,
            )
            regional_figures = list(job.get("regional_figures") or [])
            if draft:
                workflow = gen.build_draft_workflow(args, ids)
                render_mode = "draft"
            elif render_path == "regional" and regional_figures:
                workflow = gen.build_regional_workflow(args, ids, regional_figures)
                render_mode = "regional"
            else:
                workflow = gen.build_standard_workflow(args, ids)
                render_mode = "standard"
            pid = queue_prompt(workflow)
            prompt_ids.append(pid)
            meta.append(
                {
                    **job,
                    "prompt_id": pid,
                    "seed": seed,
                    "queued_at": time.strftime("%H:%M:%S"),
                    "render_mode": render_mode,
                }
            )

        q0 = queue_status()
        meta_by_pid = {str(m["prompt_id"]): m for m in meta}
        completed: list[dict[str, Any]] = []
        pony_model = gen.MODELS["pony"]
        last_complete_ts = started

        def _finalize(pid: str, outputs: dict[str, Any]) -> None:
            nonlocal last_complete_ts
            job = meta_by_pid.get(pid)
            if not job:
                return
            info = extract_image_info(outputs)
            if not info:
                completed.append({**job, "success": False, "error": "no_output"})
                return
            src = image_path_from_info(info)
            gal_path = str(src)
            if not draft:
                mode_key = str(job.get("render_mode") or "standard")
                job_w = int(job["width"]) if job.get("width") else pony_model["default_width"]
                job_h = int(job["height"]) if job.get("height") else pony_model["default_height"]
                job_steps = int(job["steps"]) if job.get("steps") else pony_model["default_steps"]
                job_cfg = float(job["cfg"]) if job.get("cfg") is not None else pony_model["default_cfg"]
                for attempt in range(8):
                    if src.is_file():
                        gal_path, gal_name = gen.gallery_log(
                            str(src),
                            job["prompt"],
                            "pony",
                            job["seed"],
                            mode_key,
                            negative=job.get("negative_extra") or "",
                            width=job_w,
                            height=job_h,
                            steps=job_steps,
                            cfg=job_cfg,
                            tags=job.get("tags") or "",
                            context=job.get("context") or "",
                        )
                        job["gallery_name"] = gal_name
                        break
                    time.sleep(0.5 if attempt < 7 else 1.0)
            now = time.time()
            render_sec = round(now - last_complete_ts, 1)
            last_complete_ts = now
            record = {
                **job,
                "success": True,
                "image": str(src),
                "gallery_image": gal_path,
                "png": src.name,
                "render_sec": render_sec,
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            completed.append(record)
            print(
                f"  OK {record.get('label', record.get('slug', '?'))} "
                f"seed={record.get('seed', '?')} -> {record.get('png', '?')}",
                flush=True,
            )
            prior = {}
            metrics_path = ROOT / "state" / "comfy-pipeline-metrics.json"
            if metrics_path.is_file():
                try:
                    raw = json.loads(metrics_path.read_text(encoding="utf-8-sig"))
                    if isinstance(raw, dict):
                        prior = raw
                except Exception:
                    pass
            timings = list(prior.get("frame_timings") or [])
            timings.append(
                {
                    "png": record.get("png"),
                    "label": record.get("label"),
                    "characters": record.get("characters"),
                    "render_sec": render_sec,
                    "completed_at": record.get("completed_at"),
                }
            )
            merge_metrics(
                {
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "variation_loop_progress": {
                        "done": len(completed),
                        "total": len(jobs),
                        "latest_png": record.get("png"),
                        "last_render_sec": render_sec,
                    },
                    "frame_timings": timings[-50:],
                }
            )
            try:
                from rp_batch_session import update_progress  # noqa: WPS433

                q = queue_status()
                pending = len((q.get("queue_pending") or [])) if isinstance(q, dict) else 0
                update_progress(
                    latest_png=str(record.get("png") or ""),
                    render_sec=render_sec,
                    queue_pending=pending,
                    label=str(record.get("label") or ""),
                )
            except Exception:
                pass

        results = wait_for_prompts(
            prompt_ids,
            timeout=timeout_per_image * max(1, len(jobs)),
            since_ts=started,
            on_complete=_finalize,
        )

        for job, pid in zip(meta, prompt_ids):
            if any(r.get("prompt_id") == pid for r in completed):
                continue
            outputs = results.get(pid) or {}
            _finalize(pid, outputs)

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
    parser = argparse.ArgumentParser(description="ComfyUI variation loop - queue series without subprocess-per-image")
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