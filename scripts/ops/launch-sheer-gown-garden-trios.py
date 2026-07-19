#!/usr/bin/env python3
"""Sheer-gown garden trios — Iter-1 lock (Jeff MC 2026-07-19).

Locks from interview:
1 A/B/C trios (3 images, 9 cast)
2 Unifying theme — same pose/camera/sheer/cut/light across all 3; only cast+signature colors differ
3B Clearly see-through chiffon, body readable, still wearing gowns
4A Signature colors per girl
5B All same cut: bias slip + high slit
6A Tight arms-around group hug, bodies touching
7D Lush garden sunset (generic, not manor-specific)
8C Prefer garden/count/colors over aggressive anti-nude
9A Thin type ID (hair/skin/eye), no dossier paste
10D Identical framing 1216x832 all three
11C Glam max jewelry + night-out hair
12B Fresh seeds
13A Success bar: count=3 + outdoor sunset + sheer colored gowns (faces secondary)
14B Generate immediately after lock
"""
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
SUMMARY = SANDBOX / "runtime" / "batch-sheer-gown-garden-trios-latest.json"
COMFY_OUTPUT = Path(r"D:\ComfyUI\output")

os.environ["COMFY_URL"] = os.environ.get("COMFY_URL") or "http://127.0.0.1:8188"

WIDTH = 1216
HEIGHT = 832

# Prompt topology: SCENE + COUNT + POSE + GOWN SYSTEM first; thin IDs + colors last.
# Deliberately avoid "nude under sheer" (teaches nude). Prefer clothed+see-through.
SHARED_SCENE = (
    "score_9, score_8_up, score_7_up, "
    "(masterpiece:1.2), (best quality:1.2), "
    "(outdoors:1.4), (lush garden:1.35), (sunset:1.4), golden hour, orange and amber sky, "
    "warm amber rim light, long soft shadows, cinematic dusk glow, depth of field, "
    "flowering garden, green foliage, garden path, roses and greenery, evening atmosphere, "
    "(3girls:1.65), (exactly three women:1.35), trio, three different faces, three distinct women, "
    "(full body:1.3), head to toe, wide shot, entire figures visible head to shoes, shoes visible, "
    "identical group framing, standing close together as one unit, "
    "(arms around each other:1.4), tight group hug, arms around waists and shoulders, "
    "bodies touching, intimate sister cluster, slight hip cock, looking toward camera, "
    "all three wearing the same gown silhouette in different signature colors, "
    "(sheer evening gown:1.45), (see-through dress:1.4), (translucent chiffon:1.35), "
    "(see-through clothes:1.3), floor-length bias slip gown, spaghetti straps, high side slit, "
    "(wearing dress:1.3), (clothed:1.2), dress on body, fabric covering torso and hips, "
    "clearly see-through chiffon, body readable through colored sheer fabric, "
    "nipples and mons faintly visible through fabric, elegant evening glamour, "
    "no underwear, no panties, no bra, no lingerie, no lining, "
    "glamorous night-out hair, big statement chandelier earrings, bold collars and necklaces, "
    "arm cuffs, evening jewelry overload, "
    "voluptuous athletic bodies, gigantic perky breasts, long legs, childbearing hips, "
    "coherent multi-person composition, photorealistic lighting"
)

# 8C: fight sheet/studio/count hard; nude lighter so garden+color can win
NEG_EXTRA = (
    "(4girls:1.45), 5girls, 6girls, crowd, extra person, "
    "multiple views, character sheet, reference sheet, turnaround, outfit sheet, "
    "simple background, grey background, beige background, plain background, seamless backdrop, "
    "studio backdrop, white void, indoor studio, solid color background, "
    "bright blue midday sky, overcast white void, fluorescent lighting, "
    "duplicate face, clone, identical faces, same face, "
    "opaque dress, thick fabric, heavy satin, fully opaque gown, "
    "short dress, mini dress, cropped top, pants, jeans, bikini, swimsuit, "
    "underwear, panties, bra, thong, "
    "bedroom, bed, indoor bedroom, marble ballroom columns, "
    "text, watermark, logo, deformed hands, extra limbs, fused bodies, "
    "child, loli, teen, underage"
)

# Thin type lines + signature color + unified bias-slip cut + glam
# (slugs, label, left/center/right block)
TRIOS: list[tuple[list[str], str, str]] = [
    (
        ["alice-al-rashid", "emily-santos", "aisha-khoury"],
        "Trio A Warm dusk — Alice & Emily & Aisha — 1/3",
        (
            "LEFT Alice: caramel olive skin, long wavy black hair with silver streak, amber-brown eyes, "
            "(deep crimson sheer bias slip gown:1.3), high slit, glamorous loose waves, massive gold collar, "
            "CENTER Emily: deep caramel-bronze skin, jet black hair, pale topaz eyes, "
            "(molten gold sheer bias slip gown:1.3), high slit, glam half-up hair, stacked gold necklaces, "
            "RIGHT Aisha: warm caramel olive skin, black hair, dark intense eyes, "
            "(deep wine garnet sheer bias slip gown:1.3), high slit, sleek high ponytail, huge gold hoops, "
            "three different face shapes, three different hair styles, no white gowns"
        ),
    ),
    (
        ["becca-moreau", "lyra-voss", "chloe-ramirez"],
        "Trio B Cool light — Becca & Lyra & Chloe — 2/3",
        (
            "LEFT Becca: pale creamy freckled skin, deep chestnut brown hair, "
            "(pearl white sheer bias slip gown:1.3), high slit, soft glam updo with tendrils, pearl ear crawlers, "
            "CENTER Lyra: pale luminescent skin, pure white-silver hair, violet-gold eyes, "
            "(ice opal violet sheer bias slip gown:1.3), high slit, sleek silver updo, crystal drop earrings, "
            "RIGHT Chloe: freckled cinnamon tan skin, wild auburn-red wavy hair, green-hazel eyes, "
            "(ivory champagne sheer bias slip gown:1.3), high slit, auburn hair mostly down glam waves, gold drops, "
            "three different face shapes, three different hair colors, all wearing sheer gowns not nude"
        ),
    ),
    (
        ["zara-mehra", "sassy-romano", "amira-khoury"],
        "Trio C Spice garden — Zara & Sassy & Amira — 3/3",
        (
            "LEFT Zara: warm honey-brown skin, darkest brown wavy hair, deep violet eyes, "
            "(saffron amethyst sheer bias slip gown:1.3), high slit, side-fall waves, amethyst gold temple jewelry, "
            "CENTER Sassy: honey-olive skin, near-black thick hair with white streak, deep chocolate eyes, "
            "(hot pink rose sheer bias slip gown:1.3), high slit, loose glam hair white streak visible, chandelier earrings, "
            "RIGHT Amira: olive-gold tan skin, jet-black pin-straight waist-length hair center part, amber-hazel eyes, "
            "(sky gold champagne sheer bias slip gown:1.3), high slit, pin-straight hair glam, crescent moon pendant, "
            "three different face shapes, three different hair textures, no blue gowns unless gold"
        ),
    ),
]


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

    try:
        from set_comfy_vram_mode import begin_batch_optimize, end_batch_restore  # noqa: WPS433

        vr_opt = begin_batch_optimize()
        print(f"VRAM optimize: {vr_opt}")
    except Exception as exc:
        print(f"VRAM optimize skipped: {exc}")
        end_batch_restore = None  # type: ignore

    from comfy_variation_loop import run_jobs  # noqa: WPS433

    sys.path.insert(0, str(SANDBOX / "sandbox" / "lib"))
    import visual_registry as vr_mod  # noqa: WPS433

    start_png = _next_png_number()
    total = len(TRIOS)
    labels = [t[1] for t in TRIOS]
    intent = (
        "sheer_gown_garden_trios_iter1|3|3||unified theme, clearly-see-through bias slip, "
        "tight hug, lush garden sunset generic, signature colors, thin ID, glam jewelry, fresh seeds"
    )
    session = {
        "active": True,
        "series": "Sheer gown garden trios Iter-1",
        "recipe": "freeform_series",
        "total": total,
        "series_start_png": start_png,
        "delivered_count": 0,
        "labels": labels,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "render_count": total,
        "offset": 0,
        "intent_signature": intent,
        "discord_channel": "1524821864956956793",
        "canon_audit": {
            "cast_count": 9,
            "trios": [t[0] for t in TRIOS],
            "width": WIDTH,
            "height": HEIGHT,
            "iter": 1,
            "locks": {
                "sheer": "3B_clearly_see_through",
                "colors": "4A_signature",
                "cut": "5B_bias_slip_high_slit",
                "pose": "6A_tight_hug",
                "garden": "7D_lush_garden_sunset_generic",
                "nude_priority": "8C_skin_ok_if_scene_lands",
                "id": "9A_thin_type",
                "frame": "10D_identical_1216x832",
                "jewelry": "11C_glam_max",
                "seeds": "12B_fresh",
                "success_bar": "13A_count_outdoor_sheer_color",
            },
        },
    }
    BATCH_SESSION.parent.mkdir(parents=True, exist_ok=True)
    BATCH_SESSION.write_text(json.dumps(session, indent=2), encoding="utf-8")
    print(f"Batch session armed start_png={start_png} total={total} {WIDTH}x{HEIGHT} iter=1")

    # Fresh seeds (12B) — not the prior 37540xxxx set
    base_seed = random.randint(0, 2**32 - 1)
    jobs: list[dict] = []
    cfg = vr_mod.load_visual_tags()
    neg_base = str(cfg.get("negative_base") or "")

    for i, (slugs, label, gown_block) in enumerate(TRIOS):
        # No dossier identity_chunk — thin lines live inside gown_block (9A)
        prompt = f"{SHARED_SCENE}, {gown_block}"
        neg = f"{neg_base}, {NEG_EXTRA}".strip(", ")
        seed = base_seed + i * 9973
        jobs.append(
            {
                "slug": "+".join(slugs),
                "label": label,
                "prompt": prompt,
                "seed": seed,
                "tags": f"roleplay,trio,sheer-gown,garden,iter1,{','.join(slugs)}",
                "context": f"roleplay:trio:sheer-gown:iter1:{i+1}",
                "negative_extra": neg,
                "hand_detailer": False,
                "width": WIDTH,
                "height": HEIGHT,
            }
        )
        print(f"  job {i+1}/{total}: {label} seed={seed} prompt_len={len(prompt)}")

    # Persist prompts+seeds for forensic compare
    prompt_dump = SUMMARY.parent / "batch-sheer-gown-garden-trios-iter1-prompts.json"
    prompt_dump.write_text(
        json.dumps(
            [
                {
                    "label": j["label"],
                    "seed": j["seed"],
                    "slug": j["slug"],
                    "prompt": j["prompt"],
                    "negative_extra": j["negative_extra"][:500],
                }
                for j in jobs
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Prompts dumped: {prompt_dump}")

    print("Queueing variation_loop…")
    report = run_jobs(jobs, draft=False)
    results = list(report.get("results") or [])
    ok = sum(1 for r in results if (r.get("ok") or r.get("path") or r.get("filename")) and not r.get("error"))
    if not ok and results:
        ok = sum(1 for r in results if not r.get("error") and (r.get("path") or r.get("filename")))
    fail = len(results) - ok if results else (0 if report.get("ok") else total)
    print("REPORT", json.dumps({k: report.get(k) for k in report if k != "results"}, default=str)[:800])
    for r in results:
        good = (r.get("ok") or r.get("path") or r.get("filename")) and not r.get("error")
        print(
            " ",
            "OK" if good else "FAIL",
            r.get("label") or r.get("slug"),
            "->",
            r.get("filename") or r.get("path") or r.get("error") or r,
        )

    summary = {
        "ok": ok,
        "fail": fail if results else (0 if ok else total),
        "recipe": "sheer_gown_garden_trios_iter1",
        "total": total,
        "mode": "variation_loop",
        "width": WIDTH,
        "height": HEIGHT,
        "series_start_png": start_png,
        "base_seed": base_seed,
        "results": results,
        "error": report.get("error"),
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "prompt_dump": str(prompt_dump),
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
        "base_seed": base_seed,
    }
    BATCH_SESSION.write_text(json.dumps(session_done, indent=2, default=str), encoding="utf-8")
    print(f"Done: {ok} ok, {summary['fail']} failed — summary {SUMMARY}")

    if end_batch_restore:
        try:
            print(f"VRAM restore: {end_batch_restore()}")
        except Exception as exc:
            print(f"VRAM restore skipped: {exc}")

    return 0 if ok == total and not report.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
