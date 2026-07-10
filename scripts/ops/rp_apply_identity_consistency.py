#!/usr/bin/env python3
"""Apply Tier-A character consistency to Roleplay-Sandbox visual-tags.yaml.

- Derive/write identity_lock (face/hair/skin/eyes) per cast — NO fixed expression
- body_lock from body_tags + bust (optional cache field)
- locked_seed from canonical portrait.meta.json when missing
- expression stays dynamic via scene text (prompt_compose.expression_layer)

Does NOT freeze faces into one emotion — expression is a separate runtime layer.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

VISUAL = Path(r"D:\PhronesisVault\Roleplay-Sandbox\runtime\visual-tags.yaml")
CAST_ROOT = Path(r"D:\PhronesisVault\Roleplay-Sandbox\gallery\cast")

CORE = [
    "alice-al-rashid",
    "chloe-ramirez",
    "becca-moreau",
    "zara-mehra",
    "amira-khoury",
    "aisha-khoury",
    "emily-santos",
    "sassy-romano",
    "lyra-voss",
    "wendy-hale",
]

# Tokens that belong to FACE identity (stable)
_FACE_KEEP = re.compile(
    r"\b("
    r"arabian|levantine|saudi|latina|indian|mixed ethnicity|venetian|italian|celtic|"
    r"persian|roma|lebanese|brazilian|tamil|south indian|caucasian|biocrafted|lilim|synthetic|"
    r"woman|girl|"
    r"skin|olive|caramel|tan|cinnamon|honey|bronze|alabaster|porcelain|pale|freckles|"
    r"hair|wavy|straight|auburn|red|black|brunette|blonde|silver|white|streak|ponytail|bun|"
    r"eyes|amber|brown|hazel|green|blue|violet|gold|bicolored|topaz|steel|"
    r"face|jaw|cheekbones|lips shape|nose|"
    r"glow|luminescent"
    r")\b",
    re.I,
)

# Strip from identity (expression / pose / clothes / body bulk)
_STRIP_FROM_IDENTITY = re.compile(
    r"\b("
    r"seductive|slutty|smile|smiling|bedroom eyes|come hither|ahegao|surprised|shock|"
    r"expression|looking at viewer|looking back|biting (?:lower )?lip|licking lips|"
    r"flushed|aroused|desperate|hungry|inviting|submissive|"
    r"full body|head to toe|standing|sitting|kneeling|pose|contrapposto|"
    r"nude|naked|clothing|bikini|dress|robe|lingerie|stockings|outfit|skimpy|"
    r"breasts|breast|bust|cup|waist|hips|thighs|legs|ass|voluptuous|athletic|"
    r"perky|firm|huge|large|narrow|wide|build|figure|torso|chest|"
    r"portrait of|full length"
    r")\b",
    re.I,
)


def _tokens(text: str) -> list[str]:
    return [t.strip() for t in re.split(r",", text or "") if t.strip()]


def derive_identity_lock(entry: dict) -> str:
    """Stable face/hair/skin/eyes only — never bakes a fixed emotion."""
    if str(entry.get("identity_lock") or "").strip():
        # Normalize existing if user already set one
        return str(entry["identity_lock"]).strip()

    parts: list[str] = []
    display = str(entry.get("display_name") or "").strip()
    if display:
        # First personal name (skip titles like Doctor)
        titles = {"doctor", "dr", "dr.", "lady", "miss", "ms", "mrs", "mr"}
        bits = display.replace(".", " ").split()
        first = next((b for b in bits if b.lower() not in titles), bits[0])
        parts.append(f"portrait of {first}")

    eth = str(entry.get("ethnicity_lane") or "").strip()
    if eth:
        parts.append(f"{eth} woman" if "woman" not in eth else eth)

    # Prefer face cues from body_tags then explicit_identity / portrait_prompt
    pool = " , ".join(
        str(entry.get(k) or "")
        for k in ("body_tags", "explicit_identity", "portrait_prompt")
    )
    kept: list[str] = []
    seen: set[str] = set()
    for tok in _tokens(pool):
        low = tok.lower()
        if _STRIP_FROM_IDENTITY.search(tok) and not _FACE_KEEP.search(tok):
            continue
        # Keep if face-related or short descriptive face token
        if _FACE_KEEP.search(tok) or any(
            x in low for x in ("skin", "hair", "eyes", "freckle", "streak", "olive", "tan")
        ):
            # drop pure body size even if mixed
            if re.search(r"\b(breast|cup|hips|waist|thigh|ass|voluptuous|athletic)\b", low):
                # allow only if also face-related heavily
                if not re.search(r"\b(skin|hair|eyes|freckle)\b", low):
                    continue
            key = re.sub(r"\s+", " ", low)
            if key not in seen:
                seen.add(key)
                kept.append(tok)

    # Cap length — identity should be tight
    kept = kept[:14]
    blob = ", ".join(parts + kept)
    # Weight wrapper applied at compose time; store raw tags here
    return re.sub(r"\s+", " ", blob).strip(" ,")


def derive_body_lock(entry: dict) -> str:
    body = str(entry.get("body_tags") or entry.get("tags") or "").strip()
    bust = str(entry.get("bust_emphasis") or "").strip()
    # Remove pure face-color duplicates lightly — body_lock may still include ethnicity for shape context
    parts = [body, bust]
    return ", ".join(p for p in parts if p)


def seed_from_meta(slug: str) -> int | None:
    for base in (CAST_ROOT / slug, CAST_ROOT / slug.split("-")[0]):
        meta = base / "canonical" / "portrait.meta.json"
        if not meta.is_file():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            seed = data.get("seed")
            if seed is not None:
                return int(seed)
        except Exception:
            continue
    return None


def main() -> int:
    bak = VISUAL.with_suffix(
        f".yaml.bak-identity-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    shutil.copy2(VISUAL, bak)
    print(f"backup {bak}")

    cfg = yaml.safe_load(VISUAL.read_text(encoding="utf-8")) or {}
    cast = cfg.setdefault("cast", {})

    # Global consistency policy (documentation for compose + humans)
    cfg["consistency"] = {
        "schema": 1,
        "principle": (
            "Same face/body identity every gen; expression/pose/outfit are dynamic. "
            "identity_lock never includes emotion. Use expression_layer from scene heat."
        ),
        "identity_weight": 1.25,
        "body_weight": 1.12,
        "expression_weight": 1.05,
        "ipadapter_status": (
            "deferred — Comfy only exposes ImpactIPAdapterApplySEGS; "
            "install IPAdapter-Plus or InstantID for true face-ref lock (Tier B)"
        ),
    }

    n_id = n_seed = 0
    for slug, entry in cast.items():
        if not isinstance(entry, dict):
            continue
        ident = derive_identity_lock(entry)
        if ident:
            entry["identity_lock"] = ident
            n_id += 1
        body_lock = derive_body_lock(entry)
        if body_lock:
            entry["body_lock"] = body_lock

        if entry.get("locked_seed") in (None, "", 0, "0"):
            seed = seed_from_meta(slug)
            if seed is not None:
                entry["locked_seed"] = seed
                n_seed += 1
                print(f"  seed-lock {slug} <- {seed}")
        # Core list callout if still missing seed
        if slug in CORE and entry.get("locked_seed") in (None, "", 0, "0"):
            print(f"  WARN no seed for core {slug} (generate portrait --lock-seed)")

    VISUAL.write_text(
        yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote identity_lock for {n_id} cast; new seeds {n_seed}")
    print(f"updated {VISUAL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
