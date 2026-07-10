#!/usr/bin/env python3
"""Lock Sassy #3, force zero-clothing global portrait path, generate Lyra x4."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import yaml

PY = Path(r"D:\HermesData\hermes-agent\venv\Scripts\python.exe")
RENDER = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\render-roleplay-image.py")
VT = Path(r"D:\PhronesisVault\Roleplay-Sandbox\runtime\visual-tags.yaml")

NUDE = (
    "completely nude, fully naked, bare skin only, (no clothing:1.4), (nude:1.4), "
    "exposed nipples, erect nipples, exposed areola, exposed pussy, visible labia, "
    "exposed asshole, uncensored, bare feet, 100 percent nude, full frontal nude"
)

SCENE = (
    "FACE CLEARLY VISIBLE looking at viewer, beautiful detailed face, head to toe in frame, "
    "voluptuous athletic 18-year-old supermodel physique, slim toned waist, flat stomach, "
    "long lean athletic legs, very large firm perky breasts pressing together deep cleavage, "
    "breasts squishing against each other, NOT chubby NOT plump NOT soft belly, "
    "tight neat pussy, small tight labia, not puffy labia, tight asshole, "
    "full frontal nude standing legs slightly apart showing nipples and pussy clearly, front view"
)

CLOTHES_NEG = (
    "clothes, clothing, dressed, fabric, shirt, top, pants, skirt, dress, robe, chemise, "
    "bikini, micro bikini, lingerie, underwear, panties, bra, stockings, thighhighs, "
    "shoes, heels, jewelry covering, covered nipples, covered pussy, censored, bar censor"
)


def main() -> int:
    # --- Lock Sassy #3 ---
    seed = 6363636363
    src = Path(
        r"D:\ComfyUI\gallery\images\2026-07-10_150405_pony_standard_sassy-romano-portrait_83bde7.png"
    )
    canon_dir = Path(
        r"D:\PhronesisVault\Roleplay-Sandbox\gallery\cast\sassy-romano\canonical"
    )
    canon_dir.mkdir(parents=True, exist_ok=True)
    dest = canon_dir / "portrait.png"
    shutil.copy2(src, dest)
    (canon_dir / "portrait.meta.json").write_text(
        json.dumps(
            {
                "slug": "sassy-romano",
                "seed": seed,
                "source_image": str(src),
                "locked_at": "2026-07-10",
                "note": "Jeff locked round1 #3",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    cfg = yaml.safe_load(VT.read_text(encoding="utf-8"))
    sassy = cfg["cast"]["sassy-romano"]
    sassy["locked_seed"] = int(seed)
    sassy["portrait_path"] = dest.as_posix()

    # CRITICAL: dossier_suffix was re-adding skimpy clothing on every portrait
    cfg["dossier_suffix"] = (
        "full body shot, head to toe, front view standing pose, looking at viewer, "
        "completely nude, fully naked, bare skin only, exposed nipples, exposed pussy, "
        "bare feet, no clothing, uncensored, soft golden cinematic lighting"
    )
    # Strengthen global nude lock used by explicit path (also help portrait negatives)
    en = cfg.setdefault("explicit_nude_lock", {})
    en["prompt_tags"] = (
        "(no clothing:1.4), (bare skin only:1.3), (fully nude body:1.3), exposed breasts, "
        "exposed nipples, exposed pussy, completely naked, uncensored nude, bare feet, "
        "no shoes no stockings no fabric"
    )
    en["negative_extra"] = CLOTHES_NEG

    # Portrait mode negatives: strip clothes
    dm = cfg.setdefault("dossier_modes", {})
    port = dm.setdefault("portrait", {})
    old_neg = str(port.get("negative_extra") or "")
    if "bikini" not in old_neg:
        port["negative_extra"] = f"{old_neg}, {CLOTHES_NEG}".strip(", ")

    # Lyra prep — Jeff canon + character face
    lyra = cfg["cast"]["lyra-voss"]
    lyra["bust_emphasis"] = (
        "very large firm perky breasts, full heavy bust, breasts pressing together, "
        "deep tight cleavage, breasts squishing against each other, not ridiculous megabust"
    )
    lyra["identity_lock"] = (
        "portrait of Lyra, beautiful clear face looking at viewer, pale or luminous skin, "
        "distinctive hair, striking eyes, same face"
    )
    # try keep eth from yaml
    eth = lyra.get("ethnicity_lane") or "woman"
    lyra["portrait_prompt"] = (
        f"full body head to toe FRONT VIEW standing pose of Lyra, beautiful {eth} woman, "
        "FACE CLEARLY VISIBLE looking at viewer, beautiful detailed face, "
        "voluptuous athletic 18-year-old supermodel physique, slim toned waist, flat stomach, "
        "long lean athletic legs, very large firm perky breasts pressing together with deep cleavage, "
        "breasts squishing against each other showing size, NOT chubby NOT plump NOT thick NOT soft belly, "
        "tight neat pussy, small tight labia, not puffy not plump fat pussy lips, tight asshole, "
        f"{NUDE}, bare feet, full frontal nude, legs slightly apart showing nipples and pussy, "
        "arms at sides, looking at viewer, high quality pony style, masterpiece, best quality"
    )
    lyra["dossier_outfit"] = NUDE
    lyra["default_outfit"] = NUDE
    lyra["scene_outfit"] = NUDE
    lyra["portrait_negative_extra"] = CLOTHES_NEG + (
        ", chubby, plump, soft belly, puffy pussy, plump labia, deformed face, "
        "face out of frame, head cropped, looking away, back view"
    )
    for slug, ent in cfg["cast"].items():
        if isinstance(ent, dict):
            ent["dossier_outfit"] = NUDE
            ent["default_outfit"] = NUDE
            ent["scene_outfit"] = NUDE

    VT.write_text(
        yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print("LOCKED sassy", seed)
    print("dossier_suffix forced NUDE (clothing leak fix)")
    print("Lyra prepped")

    # Generate Lyra x4
    seeds = [7171717171, 7272727272, 7373737373, 7474747474]
    slug = "lyra-voss"
    results = []
    for i, s in enumerate(seeds, 1):
        print(f"=== [{i}/4] seed={s} ===", flush=True)
        cmd = [
            str(PY),
            str(RENDER),
            "--character",
            slug,
            "--mode",
            "portrait",
            "--fresh",
            "--seed",
            str(s),
            "--json",
            "--standard",
            "--skip-lock",
            "--outfit",
            NUDE,
            "--scene",
            SCENE,
        ]
        t0 = time.time()
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        print(f"rc={proc.returncode} {time.time() - t0:.1f}s", flush=True)
        # show if clothing words still in prompt tail
        out = proc.stdout or ""
        for marker in ("bikini", "chemise", "lingerie", "stockings", "IMAGE_PATH"):
            if marker in out.lower() or marker in out:
                pass
        data = None
        for line in reversed(out.splitlines()):
            if line.strip().startswith("{") and "success" in line:
                try:
                    data = json.loads(line.strip())
                    break
                except Exception:
                    pass
        if data and data.get("success"):
            path = data.get("gallery_image") or data.get("image")
            print("OK", path, flush=True)
            results.append({"index": i, "ok": True, "seed": s, "image": path})
        else:
            print("FAIL", (proc.stderr or "")[-400:], flush=True)
            results.append({"index": i, "ok": False, "seed": s})

    outp = Path(r"D:\HermesData\state\lyra-seed-candidates-round1.json")
    outp.write_text(
        json.dumps({"character": slug, "results": results}, indent=2), encoding="utf-8"
    )
    ok = sum(1 for r in results if r.get("ok"))
    print("SUCCESS", ok, "/4", "->", outp)
    return 0 if ok == 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
