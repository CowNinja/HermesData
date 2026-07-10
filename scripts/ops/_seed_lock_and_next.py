#!/usr/bin/env python3
"""Lock Emily #2 and prep+generate Sassy with Jeff canon body formula."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

PY = Path(r"D:\HermesData\hermes-agent\venv\Scripts\python.exe")
RENDER = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\render-roleplay-image.py")
VT = Path(r"D:\PhronesisVault\Roleplay-Sandbox\runtime\visual-tags.yaml")

NUDE = (
    "completely nude, fully naked, bare skin only, exposed nipples, exposed areola, "
    "exposed pussy, exposed asshole, uncensored nude, no clothing, bare feet, "
    "100 percent nude, full frontal nude"
)

SCENE = (
    "FACE CLEARLY VISIBLE looking at viewer, beautiful detailed face, head to toe in frame, "
    "voluptuous athletic 18-year-old supermodel physique, slim toned waist, flat stomach, "
    "long lean athletic legs, very large firm perky breasts pressing together deep cleavage, "
    "breasts squishing against each other, NOT chubby NOT plump NOT soft belly, "
    "tight neat pussy, small tight labia, not puffy labia, tight asshole, "
    "full frontal nude standing legs slightly apart, front view"
)


def lock_emily() -> None:
    seed = 5252525252
    src = Path(
        r"D:\ComfyUI\gallery\images\2026-07-10_145733_pony_standard_emily-santos-portrait_387591.png"
    )
    canon_dir = Path(
        r"D:\PhronesisVault\Roleplay-Sandbox\gallery\cast\emily-santos\canonical"
    )
    canon_dir.mkdir(parents=True, exist_ok=True)
    dest = canon_dir / "portrait.png"
    shutil.copy2(src, dest)
    (canon_dir / "portrait.meta.json").write_text(
        json.dumps(
            {
                "slug": "emily-santos",
                "seed": seed,
                "source_image": str(src),
                "locked_at": "2026-07-10",
                "note": "Jeff locked round2 #2 full frontal athletic tight",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    cfg = yaml.safe_load(VT.read_text(encoding="utf-8"))
    e = cfg["cast"]["emily-santos"]
    e["locked_seed"] = int(seed)
    e["portrait_path"] = dest.as_posix()

    # Prep Sassy with Jeff canon
    s = cfg["cast"]["sassy-romano"]
    s["bust_emphasis"] = (
        "very large firm perky breasts, full heavy bust, breasts pressing together, "
        "deep tight cleavage, breasts squishing against each other, "
        "voluptuous chest not ridiculous megabust"
    )
    s["identity_lock"] = (
        "portrait of Sassy, italian venetian woman, olive warm skin, dark wavy hair, "
        "striking eyes, beautiful clear face looking at viewer, same face"
    )
    s["body_lock"] = (
        "1girl, solo, italian woman, olive warm skin, dark wavy hair, "
        "voluptuous athletic 18-year-old supermodel physique, slim toned waist, flat stomach, "
        "long lean toned legs, firm high butt, very large firm breasts pressing together, "
        "not chubby, not plump, not thick, not soft belly"
    )
    s["portrait_prompt"] = (
        "full body head to toe FRONT VIEW standing pose of Sassy, beautiful italian venetian woman, "
        "FACE CLEARLY VISIBLE looking at viewer, beautiful detailed face, olive warm skin, "
        "dark wavy hair, striking eyes, "
        "voluptuous athletic 18-year-old supermodel physique, slim toned waist, flat stomach, "
        "long lean athletic legs, very large firm perky breasts pressing together with deep cleavage, "
        "breasts squishing against each other showing size, NOT chubby NOT plump NOT thick NOT soft belly, "
        "tight neat pussy, small tight labia, not puffy not plump fat pussy lips, tight asshole, smooth crotch, "
        f"{NUDE}, bare feet, full frontal nude, legs slightly apart to show pussy and asshole, "
        "arms at sides, looking at viewer, high quality pony style, masterpiece, best quality"
    )
    s["portrait_negative_extra"] = (
        "chubby, plump, thick thighs, soft belly, bbw, puffy pussy, plump labia, fat pussy lips, "
        "deformed face, face out of frame, head cropped, looking away, back view, face obscured, blurry face"
    )
    s["dossier_outfit"] = NUDE
    s["default_outfit"] = NUDE
    s["scene_outfit"] = NUDE
    s["explicit_identity"] = (
        "portrait of Sassy, clear face looking at viewer, italian woman, athletic supermodel, "
        "very large firm breasts pressing together, tight neat pussy, tight asshole, not chubby"
    )

    VT.write_text(
        yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print("LOCKED emily", seed, dest)
    print("Sassy prepped with Jeff canon")


def gen_sassy() -> int:
    seeds = [6161616161, 6262626262, 6363636363, 6464646464]
    slug = "sassy-romano"
    results = []
    for i, seed in enumerate(seeds, 1):
        print(f"=== [{i}/4] seed={seed} ===", flush=True)
        cmd = [
            str(PY),
            str(RENDER),
            "--character",
            slug,
            "--mode",
            "portrait",
            "--fresh",
            "--seed",
            str(seed),
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
        data = None
        for line in reversed((proc.stdout or "").splitlines()):
            if line.strip().startswith("{") and "success" in line:
                try:
                    data = json.loads(line.strip())
                    break
                except Exception:
                    pass
        if data and data.get("success"):
            path = data.get("gallery_image") or data.get("image")
            print("OK", path, flush=True)
            results.append({"index": i, "ok": True, "seed": seed, "image": path})
        else:
            print("FAIL", (proc.stderr or "")[-300:], flush=True)
            results.append({"index": i, "ok": False, "seed": seed})
    out = Path(r"D:\HermesData\state\sassy-seed-candidates-round1.json")
    out.write_text(
        json.dumps({"character": slug, "results": results}, indent=2), encoding="utf-8"
    )
    ok = sum(1 for r in results if r.get("ok"))
    print("SUCCESS", ok, "/4", "->", out)
    return 0 if ok == 4 else 1


if __name__ == "__main__":
    lock_emily()
    raise SystemExit(gen_sassy())
