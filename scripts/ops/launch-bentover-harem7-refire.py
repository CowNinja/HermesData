#!/usr/bin/env python3
"""Re-fire 7-girl harem bent-over-spread series + Discord-ready batch session."""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\HermesData")
OPS = ROOT / "scripts" / "ops"
SANDBOX = Path(r"D:\PhronesisVault\Roleplay-Sandbox")
BATCH_SESSION = ROOT / "state" / "comfy-batch-session.json"
SUMMARY = SANDBOX / "runtime" / "batch-freeform_series-latest.json"
COMFY_OUTPUT = Path(r"D:\ComfyUI\output")

# Gallery :8189 returns HTML 200 for /system_stats — force real Comfy.
os.environ["COMFY_URL"] = os.environ.get("COMFY_URL") or "http://127.0.0.1:8188"

HAREM = [
    ("alice-al-rashid", "Alice-Al-Rashid"),
    ("chloe-ramirez", "Chloe-Ramirez"),
    ("becca-moreau", "Becca-Moreau"),
    ("emily-santos", "Emily-Santos"),
    ("sassy-romano", "Sassy-Romano"),
    ("lyra-voss", "Lyra-Voss"),
    ("zara-mehra", "Zara-Mehra"),
]

SCENE = (
    "seductive nude, on hands and knees, ass up, both hands spreading plump ass cheeks wide, "
    "bent-over-spread, looking back at viewer, manor bedroom, warm golden light, "
    "sheer black thigh high stockings with lace tops"
)
ALT = "bent-over-spread"
MODE = "explicit"
TOTAL = 7


def _next_png_number() -> int:
    best = 0
    for path in COMFY_OUTPUT.glob("standard__*.png"):
        m = re.match(r"standard__(\d+)_\.png$", path.name)
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


def main() -> int:
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))

    # Prefer image VRAM profile when helper exists.
    try:
        from set_comfy_vram_mode import begin_batch_optimize  # noqa: WPS433

        vr = begin_batch_optimize()
        print(f"VRAM optimize: {vr}")
    except Exception as exc:
        print(f"VRAM optimize skipped: {exc}")

    from comfy_variation_loop import build_harem_job, run_jobs  # noqa: WPS433

    sys.path.insert(0, str(SANDBOX / "sandbox" / "lib"))
    import visual_registry as vr_mod  # noqa: WPS433

    start_png = _next_png_number()
    labels = [f"{disp} - hands & knees - {i}/{TOTAL}" for i, (_, disp) in enumerate(HAREM, 1)]
    intent = (
        f"freeform_series|1|{TOTAL}||series of {TOTAL} seductive nude harem girls, each solo, "
        "on hands and knees, spreading plump ass cheeks wide with both hands, bent-over-spread, looking back"
    )
    session = {
        "active": True,
        "series": "Harem bent-over-spread",
        "recipe": "freeform_series",
        "total": TOTAL,
        "series_start_png": start_png,
        "delivered_count": 0,
        "labels": labels,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "render_count": TOTAL,
        "offset": 0,
        "intent_signature": intent,
        "discord_channel": "1524821864956956793",
        "canon_audit": {"cast_count": TOTAL, "slugs": [s for s, _ in HAREM]},
    }
    BATCH_SESSION.parent.mkdir(parents=True, exist_ok=True)
    BATCH_SESSION.write_text(json.dumps(session, indent=2), encoding="utf-8")
    print(f"Batch session armed start_png={start_png} total={TOTAL}")

    base_seed = random.randint(0, 2**32 - 1)
    jobs = []
    for i, (slug, disp) in enumerate(HAREM):
        label = labels[i]
        jobs.append(
            build_harem_job(
                vr_mod,
                slug=slug,
                label=label,
                alternate=ALT,
                scene=SCENE,
                base_seed=base_seed,
                index=i,
                outfit_overlay="",
                mode=MODE,
            )
        )
        print(f"  job {i+1}/{TOTAL}: {slug} seed={jobs[-1]['seed']} prompt_len={len(jobs[-1]['prompt'])}")

    print("Queueing variation_loop…")
    report = run_jobs(jobs, draft=False)
    print("REPORT", json.dumps({k: report.get(k) for k in report if k != "results"}, default=str))
    results = list(report.get("results") or [])
    if not results and report.get("error"):
        print("FATAL", report.get("error"))
        BATCH_SESSION.write_text(json.dumps({**session, "active": False, "error": report.get("error"), "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2), encoding="utf-8")
        return 2
    ok = sum(1 for r in results if r.get("success"))
    fail = len(results) - ok
    for r in results:
        print(
            f"  {'OK' if r.get('success') else 'FAIL'} {r.get('label') or r.get('slug')} "
            f"seed={r.get('seed')} -> {r.get('png') or r.get('error')}"
        )

    try:
        sess = json.loads(BATCH_SESSION.read_text(encoding="utf-8-sig"))
    except Exception:
        sess = session
    sess["active"] = False
    sess["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    sess["render_ok"] = ok
    sess["render_fail"] = fail
    # Do NOT claim Discord delivery from render success — delivery daemon owns delivered_count.
    sess["render_completed"] = ok
    sess.setdefault("delivered_count", int(sess.get("delivered_count") or 0))
    BATCH_SESSION.write_text(json.dumps(sess, indent=2), encoding="utf-8")

    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(
        json.dumps(
            {
                "ok": ok,
                "fail": fail,
                "recipe": "freeform_series",
                "series": "Harem bent-over-spread",
                "total": TOTAL,
                "mode": "variation_loop",
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Done: {ok} ok, {fail} failed — summary {SUMMARY}")
    try:
        from set_comfy_vram_mode import end_batch_restore  # noqa: WPS433

        print("VRAM restore:", end_batch_restore())
    except Exception:
        pass
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
