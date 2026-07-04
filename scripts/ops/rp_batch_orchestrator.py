#!/usr/bin/env python3
"""Launch RP batch series scripts from OOC intent (bypasses per-image agent loop)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS = Path(__file__).resolve().parent
BATCH_SESSION = ROOT / "state" / "comfy-batch-session.json"
PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"
LOG = ROOT / "logs" / "rp-batch-orchestrator.log"

if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))

from rp_sandbox_paths import (  # noqa: E402
    BATCH_HAREM as HAREM,
    BATCH_KITCHEN as KITCHEN,
    BATCH_RP_SERIES as UNIVERSAL,
    SANDBOX,
    assert_sandbox_layout,
)

from rp_batch_launch_lock import check_running, make_signature  # noqa: E402
from rp_batch_spec import (  # noqa: E402
    batch_intent_signature,
    detect_recipe,
    infer_group_size,
    resolve_series_plan,
)


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _active_batch() -> dict:
    if not BATCH_SESSION.is_file():
        return {}
    try:
        data = json.loads(BATCH_SESSION.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            return {}
        if data.get("active"):
            return data
        delivered = int(data.get("delivered_count") or 0)
        total = int(data.get("total") or 0)
        if total >= 2 and delivered < total:
            return data
    except Exception:
        pass
    return {}


def _batch_count(spec: dict, prompt: str) -> int:
    count = int(spec.get("batch_count") or 0)
    if count >= 2:
        return count
    m = re.search(r"\b(?:series|batch)\s+of\s+(\d+)", prompt or "", re.I)
    if m:
        return int(m.group(1))
    return 0


def _count_args(count: int) -> list[str]:
    return ["--total", str(count)] if count >= 2 else []


def _recipe_args(prompt: str, spec: dict) -> list[str]:
    recipe = detect_recipe(prompt, spec)
    return ["--recipe", recipe]


def _pick_script(prompt: str, spec: dict) -> tuple[Path, list[str], str]:
    """Universal executor is default; legacy scripts kept as fallback."""
    count = _batch_count(spec, prompt)
    if UNIVERSAL.is_file():
        try:
            plan = resolve_series_plan(prompt, spec, total=count or None)
            extra = _count_args(count or plan.total) + _recipe_args(prompt, spec)
            return UNIVERSAL, extra, plan.series
        except Exception:
            pass
    count_args = _count_args(count)
    lower = (prompt or "").lower()
    if any(k in lower for k in ("harem girl", "harem girls", "per harem", "harem portrait")):
        return HAREM, count_args, "Harem portraits"
    if any(k in lower for k in ("crawl", "crawling", "hands and knees", "on all fours", "kitchen")):
        return KITCHEN, count_args, "Kitchen crawl"
    return HAREM, count_args, "Harem portraits"


def _session_matches_new_intent(data: dict, spec: dict, prompt: str) -> bool:
    """Fresh OOC after /reset must not inherit offset/limit from a different series."""
    old_sig = str(data.get("intent_signature") or "").strip()
    new_sig = batch_intent_signature(prompt, spec)
    if old_sig and new_sig and old_sig != new_sig:
        return False
    new_gs = int(spec.get("group_size") or 0) or infer_group_size(prompt, spec)
    old_series = str(data.get("series") or "")
    if new_gs >= 2 and old_series and f"({new_gs})" not in old_series:
        return False
    new_count = int(spec.get("batch_count") or 0)
    old_total = int(data.get("total") or 0)
    if new_count >= 2 and old_total >= 2 and new_count != old_total:
        return False
    return True


def _resume_args(script: Path, spec: dict, prompt: str) -> list[str]:
    if not BATCH_SESSION.is_file():
        return []
    try:
        data = json.loads(BATCH_SESSION.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            return []
        if not _session_matches_new_intent(data, spec, prompt):
            return []
        delivered = int(data.get("delivered_count") or 0)
        total = int(data.get("total") or 0)
        if total < 2 or delivered >= total:
            return []
        count = total or _batch_count(spec, prompt)
        remaining = total - delivered
        recipe = str(data.get("recipe") or detect_recipe(prompt, spec))
        args = [
            "--offset",
            str(delivered),
            "--limit",
            str(remaining),
            *_count_args(count),
        ]
        if script == UNIVERSAL:
            args.extend(["--recipe", recipe])
        return args
    except Exception:
        return []


def _parse_int_flag(argv: list[str], flag: str, default: int = 0) -> int:
    for i, token in enumerate(argv):
        if token == flag and i + 1 < len(argv):
            try:
                return int(argv[i + 1])
            except ValueError:
                return default
    return default


def _parse_str_flag(argv: list[str], flag: str, default: str = "") -> str:
    for i, token in enumerate(argv):
        if token == flag and i + 1 < len(argv):
            return str(argv[i + 1])
    return default


def _preflight_session_stub(
    prompt: str,
    spec: dict,
    *,
    label: str,
    recipe: str,
    total: int,
    offset: int,
    limit: int,
) -> None:
    """Write active session before Popen so duplicate orchestrator calls bail early."""
    try:
        from rp_batch_canon import plan_canon_audit  # noqa: WPS433
        from rp_batch_session import start_session  # noqa: WPS433
        from rp_batch_spec import resolve_series_plan, slice_plan  # noqa: WPS433

        plan = resolve_series_plan(prompt, spec, total=total or None, recipe=recipe or None)
        plan = slice_plan(plan, offset=offset, limit=limit or 0)
        full = resolve_series_plan(prompt, spec, total=plan.total)
        start_session(
            series=plan.series or label,
            recipe=plan.recipe or recipe,
            total=plan.total,
            labels=[f.label for f in full.frames],
            render_count=len(plan.frames),
            offset=offset,
            canon_audit=plan_canon_audit(plan.frames),
            intent_signature=batch_intent_signature(prompt, spec),
        )
        _log(f"preflight session stub {plan.series} {plan.total} frames")
    except Exception as exc:
        _log(f"preflight session stub skipped: {exc}")


def launch(prompt: str, spec: dict, *, dry_run: bool = False) -> dict:
    assert_sandbox_layout()
    active = _active_batch()
    lock_state = check_running()
    if active and lock_state.get("running"):
        return {
            "ok": True,
            "action": "already_running",
            "series": active.get("series"),
            "recipe": active.get("recipe"),
            "delivered_count": active.get("delivered_count"),
            "total": active.get("total"),
            "pid": lock_state.get("pid"),
        }
    if active and not lock_state.get("running"):
        _log(
            f"resume stale session {active.get('series')} "
            f"{active.get('delivered_count')}/{active.get('total')} (batch process dead)"
        )

    script, extra, label = _pick_script(prompt, spec)
    if not script.is_file():
        return {"ok": False, "error": "batch_script_missing", "script": str(script)}

    spec_json = json.dumps(spec, ensure_ascii=False) if spec else ""
    args = [str(PY), "-u", str(script)]
    if script == UNIVERSAL and spec_json:
        args.extend(["--spec-json", spec_json])
    if prompt:
        args.append(prompt)
    resume = _resume_args(script, spec, prompt)
    tail = resume if resume else extra
    args.extend(tail)

    recipe = _parse_str_flag(tail, "--recipe", detect_recipe(prompt, spec))
    total = _parse_int_flag(tail, "--total", _batch_count(spec, prompt))
    offset = _parse_int_flag(resume, "--offset", 0)
    limit = _parse_int_flag(resume, "--limit", 0)
    lock_sig = make_signature(
        recipe=recipe,
        total=total,
        offset=offset,
        limit=limit,
        script=script.name,
    )
    lock_state = check_running(lock_sig)
    if lock_state.get("running"):
        return {
            "ok": True,
            "action": "already_running",
            "reason": "batch_launch_lock",
            "signature": lock_sig,
            "pid": lock_state.get("pid"),
            "series": label,
            "recipe": recipe,
        }

    if dry_run:
        return {"ok": True, "dry_run": True, "series": label, "cmd": args, "signature": lock_sig}

    _preflight_session_stub(
        prompt,
        spec,
        label=label,
        recipe=recipe,
        total=total,
        offset=offset,
        limit=limit,
    )

    vram_profile = "triplet_smoke" if recipe == "harem_triplets" else "batch_default"
    if total >= 4 or "group" in recipe:
        vram_profile = "group_4plus"
    try:
        from set_comfy_vram_mode import begin_batch_optimize  # noqa: WPS433

        vram = begin_batch_optimize(profile=vram_profile)
        if vram.get("changed"):
            _log(f"vram optimize {vram.get('prior_mode')} -> lowvram profile={vram_profile}")
    except Exception as exc:
        _log(f"vram optimize skipped: {exc}")

    _log(f"launch {label}: {' '.join(args)}")
    proc = subprocess.Popen(
        args,
        cwd=str(script.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    count = _batch_count(spec, prompt)
    recipe = detect_recipe(prompt, spec)
    return {
        "ok": True,
        "action": "launched",
        "series": label,
        "recipe": recipe,
        "batch_count": count,
        "pid": proc.pid,
        "script": str(script),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="?", default="")
    parser.add_argument("--spec-json", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec: dict = {}
    if args.spec_json:
        try:
            spec = json.loads(args.spec_json)
        except json.JSONDecodeError:
            pass

    if not spec:
        sys.path.insert(0, str(SANDBOX / "lib"))
        from visual_registry import detect_image_intent  # noqa: WPS433

        spec = detect_image_intent(args.prompt, "", "") or {}

    count = int(spec.get("batch_count") or 0)
    if count < 2:
        m = re.search(r"\b(?:series|batch)\s+of\s+(\d+)", args.prompt or "", re.I)
        if m:
            count = int(m.group(1))
    if count < 2:
        print(json.dumps({"ok": False, "error": "batch_count_below_2", "spec": spec}))
        return 1

    spec["batch_count"] = count
    result = launch(args.prompt, spec, dry_run=args.dry_run)
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())