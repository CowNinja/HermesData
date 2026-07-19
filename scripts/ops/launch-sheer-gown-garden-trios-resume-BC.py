#!/usr/bin/env python3
"""Resume sheer-gown garden trios — B + C only (A already landed as standard__00763_.png).

Same design locks + seeds as launch-sheer-gown-garden-trios.py jobs 2–3.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\HermesData")
OPS = ROOT / "scripts" / "ops"
SANDBOX = Path(r"D:\PhronesisVault\Roleplay-Sandbox")
BATCH_SESSION = ROOT / "state" / "comfy-batch-session.json"
SUMMARY = SANDBOX / "runtime" / "batch-sheer-gown-garden-trios-latest.json"
COMFY_OUTPUT = Path(r"D:\ComfyUI\output")

os.environ["COMFY_URL"] = os.environ.get("COMFY_URL") or "http://127.0.0.1:8188"

WIDTH = 1216
HEIGHT = 832

# Seeds locked from first launch
SEED_A = 375400376
SEED_B = 375410349
SEED_C = 375420322

SHARED_SCENE = (
    "(3girls:1.55), exactly three distinct women, trio, three different faces, "
    "full body head to toe wide shot, entire figures visible head to shoes, "
    "standing close together arms around each other, intimate sister cluster, "
    "arms around waists and shoulders, slight hip cock, elegant sensual evening pose, "
    "looking toward camera with soft sister glances, "
    "Phronesis Manor formal rose garden, trimmed box hedges, lush red and blush roses in bloom, "
    "stone garden path, golden hour sunset, warm amber rim light, long soft shadows, "
    "cinematic dusk glow, elegant evening atmosphere, "
    "floor-length sheer chiffon evening gowns only, translucent elegant sheer fabric, "
    "soft elegant sheer silhouette and nipple shadow visible through fabric, tasteful dusk, "
    "no lining, nude under sheer gown, no underwear, no panties, no bra, no lingerie, "
    "statement evening jewelry, mixed formal updos and loose waves, "
    "voluptuous athletic bodies, gigantic perky breasts, long legs, childbearing hips, "
    "masterpiece, best quality, ultra detailed, coherent multi-person composition"
)

NEG_EXTRA = (
    "extra person, 4girls, crowd, duplicate face, clone, identical twins accident, "
    "underwear, panties, bra, thong, g-string, bikini, opaque dress, fully clothed opaque, "
    "short dress, mini dress, cropped top, pants, skirt suit, "
    "bedroom, indoor bedroom, studio seamless, plain background, "
    "text, watermark, logo, deformed hands, extra limbs, fused bodies, "
    "child, loli, teen, underage"
)

TRIOS_BC: list[tuple[list[str], str, str, int]] = [
    (
        ["becca-moreau", "lyra-voss", "chloe-ramirez"],
        "Trio B Cool light — Becca & Lyra & Chloe — 2/3",
        (
            "LEFT Becca Moreau: northern Italian Venetian Celtic pale creamy alabaster skin freckles "
            "deep chestnut brown hair, floor-length pearl-white sheer chiffon strapless column gown "
            "open back drape, chestnut soft updo with face tendrils, pearl and silver ear crawlers, "
            "CENTER Lyra Voss: biocrafted lilim pale alabaster luminescent glowing skin pure white-silver hair "
            "bicolored violet-gold eyes, floor-length ice-opal faint violet synthetic sheer minimal-strap gown "
            "catching glow, white-silver sleek elegant updo, crystal-violet drop earrings thin collar, "
            "RIGHT Chloe Ramirez: freckled Cuban-Mexican-Indian cinnamon tan skin wild auburn-red wavy hair "
            "green-hazel eyes, floor-length ivory champagne sheer mesh-chiffon soft cowl neck gown thigh slit, "
            "auburn hair mostly down with one side pin, warm gold drop earrings thin gold waist chain"
        ),
        SEED_B,
    ),
    (
        ["zara-mehra", "sassy-romano", "amira-khoury"],
        "Trio C Spice garden — Zara & Sassy & Amira — 3/3",
        (
            "LEFT Zara Mehra: South Indian Tamil Persian Gulf woman warm honey-brown sun-kissed skin "
            "darkest brown almost black wavy hair deep violet eyes, floor-length saffron-to-amethyst "
            "sheer draped sari-inspired evening column gown, near-black waves side fall, "
            "amethyst and gold temple jewelry, "
            "CENTER Sassy Romano: Persian Roma woman warm honey-olive skin darkest brown almost black "
            "thick long hair with white streak deep chocolate eyes, floor-length rose hot-pink smoke "
            "sheer bias slip gown high slit, dark hair with white streak loose, "
            "rose-gold statement chandelier earrings, "
            "RIGHT Amira Khoury: Arabian Levantine woman warm darkly tanned olive-gold skin "
            "jet-black pin-straight waist-length hair center part rare amber-hazel almond eyes, "
            "floor-length sheer sky-gold champagne arabesque chiffon deep V evening gown, "
            "jet pin-straight hair mostly down center part, crescent moon pendant fine gold body chain"
        ),
        SEED_C,
    ),
]


def _next_png_number() -> int:
    best = 0
    for path in COMFY_OUTPUT.glob("standard__*.png"):
        m = re.match(r"standard__(\d+)_\.png$", path.name)
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


def _identity_chunk(vr_mod, slug: str) -> str:
    cfg = vr_mod.load_visual_tags()
    cast = (cfg.get("cast") or {}).get(slug) or {}
    body = str(cast.get("body_tags") or cast.get("identity_lock") or "").strip()
    bust = str(cast.get("bust_emphasis") or "").strip()
    for tok in ("1girl,", "solo,", "1girl", "solo"):
        body = body.replace(tok, "")
    return ", ".join(x for x in [body.strip(" ,"), bust] if x)


def main() -> int:
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))

    try:
        from set_comfy_vram_mode import begin_batch_optimize, end_batch_restore

        print(f"VRAM optimize: {begin_batch_optimize()}")
    except Exception as exc:
        print(f"VRAM optimize skipped: {exc}")
        end_batch_restore = None  # type: ignore

    from comfy_variation_loop import run_jobs

    sys.path.insert(0, str(SANDBOX / "sandbox" / "lib"))
    import visual_registry as vr_mod

    start_png = _next_png_number()
    total = len(TRIOS_BC)
    labels = [t[1] for t in TRIOS_BC]
    session = {
        "active": True,
        "series": "Sheer gown garden trios resume BC",
        "recipe": "freeform_series",
        "total": total,
        "series_start_png": start_png,
        "delivered_count": 0,
        "labels": labels,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "render_count": total,
        "offset": 0,
        "intent_signature": "sheer_gown_garden_trios_resume_BC|2|2||B+C after A 00763 interrupted",
        "discord_channel": "1524821864956956793",
        "prior_ok": ["standard__00763_.png"],
        "canon_audit": {
            "resume": True,
            "trio_a_png": "standard__00763_.png",
            "trio_a_seed": SEED_A,
            "width": WIDTH,
            "height": HEIGHT,
        },
    }
    BATCH_SESSION.parent.mkdir(parents=True, exist_ok=True)
    BATCH_SESSION.write_text(json.dumps(session, indent=2), encoding="utf-8")
    print(f"Batch session armed start_png={start_png} total={total} (B+C) {WIDTH}x{HEIGHT}")

    jobs: list[dict] = []
    for i, (slugs, label, gown_block, seed) in enumerate(TRIOS_BC):
        id_parts = [_identity_chunk(vr_mod, s) for s in slugs]
        prompt = ", ".join(
            [
                SHARED_SCENE,
                "character identities left to right:",
                *id_parts,
                gown_block,
            ]
        )
        cfg = vr_mod.load_visual_tags()
        neg_base = str(cfg.get("negative_base") or "")
        neg = f"{neg_base}, {NEG_EXTRA}".strip(", ")
        jobs.append(
            {
                "slug": "+".join(slugs),
                "label": label,
                "prompt": prompt,
                "seed": seed,
                "tags": f"roleplay,trio,sheer-gown,garden,{','.join(slugs)}",
                "context": f"roleplay:trio:sheer-gown:resume:{i+2}",
                "negative_extra": neg,
                "hand_detailer": False,
                "width": WIDTH,
                "height": HEIGHT,
            }
        )
        print(f"  job {i+1}/{total}: {label} seed={seed} prompt_len={len(prompt)}")

    print("Queueing variation_loop…")
    report = run_jobs(jobs, draft=False)
    results = list(report.get("results") or [])
    ok = sum(1 for r in results if (r.get("ok") or r.get("success") or r.get("path") or r.get("png") or r.get("filename")) and not r.get("error"))
    fail = len(results) - ok if results else (0 if report.get("ok") else total)
    print("REPORT", json.dumps({k: report.get(k) for k in report if k != "results"}, default=str)[:800])
    for r in results:
        good = (r.get("ok") or r.get("success") or r.get("png") or r.get("filename") or r.get("path")) and not r.get("error")
        print(
            " ",
            "OK" if good else "FAIL",
            r.get("label") or r.get("slug"),
            "->",
            r.get("png") or r.get("filename") or r.get("path") or r.get("error") or r,
        )

    summary = {
        "ok": ok,
        "fail": fail,
        "recipe": "sheer_gown_garden_trios_resume_BC",
        "total": total,
        "prior_a": "standard__00763_.png",
        "mode": "variation_loop",
        "width": WIDTH,
        "height": HEIGHT,
        "series_start_png": start_png,
        "results": results,
        "error": report.get("error"),
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    session_done = {
        **session,
        "active": False,
        "delivered_count": ok,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary_path": str(SUMMARY),
        "error": report.get("error"),
    }
    BATCH_SESSION.write_text(json.dumps(session_done, indent=2, default=str), encoding="utf-8")
    print(f"Done: {ok} ok, {fail} failed — summary {SUMMARY}")

    if end_batch_restore:
        try:
            print(f"VRAM restore: {end_batch_restore()}")
        except Exception as exc:
            print(f"VRAM restore skipped: {exc}")

    return 0 if ok == total and not report.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
