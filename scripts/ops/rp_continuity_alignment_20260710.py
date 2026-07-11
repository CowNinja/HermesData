#!/usr/bin/env python3
"""
Roleplay-Sandbox continuity alignment after full seed campaign (2026-07-10).
- Fix statuses / visual lock notes
- Create missing character sheets
- Rewrite cast indexes
- Refresh STATE for immersion
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

SANDBOX = Path(r"D:\PhronesisVault\Roleplay-Sandbox")
RUNTIME = SANDBOX / "runtime"
CHARS = RUNTIME / "characters"
VT_PATH = RUNTIME / "visual-tags.yaml"
TODAY = "2026-07-10"

CORE = {
    "alice-al-rashid",
    "chloe-ramirez",
    "becca-moreau",
    "emily-santos",
    "sassy-romano",
    "lyra-voss",
    "zara-mehra",
    "amira-khoury",
    "aisha-khoury",
    "wendy-hale",
}
TANK = {"valentina-ortiz", "priya-sharma", "noor-al-rashid"}
# everyone else in visual-tags cast = extended

SHEET_TEMPLATE = """---
campaign_id: "phronesis-harem-chronicle"
world_type: "harem"
type: character
name: "{name}"
role: "{role}"
status: {status}
introduced: seed-lock-2026-07-10
last-seen: "{today}"
current-location: "{location}"
current-mood: "{mood}"
physical-compliance: 8/10
relationships:
  jeff: "Master; sole male; body and devotion reserved for him and the sisterhood"
  alice: "High Priestess; vetter and guide into the household"
  other sisters: "learning bonds; sapphic warmth and competitive devotion"
archetype: true
locked: {locked}
visual_seed: {seed}
visual_canonical: "gallery/cast/{slug}/canonical/portrait.png"
---
# {name}

> *"{hook}"*

## Physical Profile

| Trait | Detail |
|-------|--------|
| **Ethnicity** | {ethnicity} |
| **Skin** | {skin} |
| **Hair** | {hair} |
| **Eyes** | {eyes} |
| **Height / Build** | Athletic feminine hourglass — narrow waist, wide hips, long lean legs, narrow feminine shoulders. Large firm perky breasts (Katie-scale goldilocks; soft squish). Toned abs OK. Not chubby. |
| **Face** | Clear beautiful face; same locked face across gens |
| **Age** | 18–22 (manor presentation) |
| **Visual SSOT** | `visual-tags.yaml` → `{slug}` · locked_seed `{seed}` · canonical portrait |

### Erotic Body Highlights

Voluptuous-athletic supermodel body. Large firm perky breasts that press together with soft squish. Narrow waist and wide hips. Tight eager mouth, pussy, and ass — prose heat; T2I uses happy-medium anatomy (not beefy, not blank). Loves flaunting for Master and sisters.

## Backstory

{backstory}

## Personality

{personality}

## Signature Traits

- Devoted to Jeff as sole male
- Sapphic warmth with sisters
- Visual identity locked for continuity (seed + canonical portrait)

## Current State

{current}

## Visual / Export Hooks

- Slug: `{slug}`
- Locked seed: `{seed}`
- Canonical: `gallery/cast/{slug}/canonical/portrait.png`
- Spec: `runtime/VISUAL-GENERATION-SPEC.md`, `PHYSICAL-CANON.md`

**Last Updated:** {today} | Continuity alignment after full seed campaign
"""


def load_vt():
    return yaml.safe_load(VT_PATH.read_text(encoding="utf-8"))


def fix_wendy():
    p = CHARS / "wendy-hale.md"
    t = p.read_text(encoding="utf-8")
    if t.startswith("|---"):
        t = "---" + t[4:]
        p.write_text(t, encoding="utf-8")
        print("fixed wendy frontmatter pipe")
    # ensure visual fields in frontmatter if missing
    if "visual_seed:" not in t:
        t = p.read_text(encoding="utf-8")
        t = t.replace("locked: true\n", "locked: true\nvisual_seed: 1717171717\nvisual_canonical: \"gallery/cast/wendy-hale/canonical/portrait.png\"\n", 1)
        p.write_text(t, encoding="utf-8")
        print("wendy visual_seed added")


def ensure_visual_block(path: Path, slug: str, seed, status: str, locked: bool):
    t = path.read_text(encoding="utf-8")
    # frontmatter status
    if t.startswith("|---"):
        t = "---" + t[4:]
    if not t.startswith("---"):
        return
    parts = t.split("---", 2)
    if len(parts) < 3:
        return
    fm, body = parts[1], parts[2]
    # status replace
    if re.search(r"^status:\s*.+$", fm, re.M):
        fm = re.sub(r"^status:\s*.+$", f"status: {status}", fm, count=1, flags=re.M)
    else:
        fm += f"\nstatus: {status}"
    if re.search(r"^locked:\s*.+$", fm, re.M):
        fm = re.sub(r"^locked:\s*.+$", f"locked: {'true' if locked else 'false'}", fm, count=1, flags=re.M)
    else:
        fm += f"\nlocked: {'true' if locked else 'false'}"
    if re.search(r"^last-seen:\s*.+$", fm, re.M):
        fm = re.sub(r"^last-seen:\s*.+$", f'last-seen: "{TODAY}"', fm, count=1, flags=re.M)
    # visual_seed
    if re.search(r"^visual_seed:\s*.+$", fm, re.M):
        fm = re.sub(r"^visual_seed:\s*.+$", f"visual_seed: {seed}", fm, count=1, flags=re.M)
    else:
        fm += f"\nvisual_seed: {seed}"
    if re.search(r"^visual_canonical:\s*.+$", fm, re.M):
        fm = re.sub(
            r"^visual_canonical:\s*.+$",
            f'visual_canonical: "gallery/cast/{slug}/canonical/portrait.png"',
            fm,
            count=1,
            flags=re.M,
        )
    else:
        fm += f'\nvisual_canonical: "gallery/cast/{slug}/canonical/portrait.png"'

    # body visual lock section
    block = (
        f"\n## Visual Lock (T2I continuity — {TODAY})\n\n"
        f"- **Slug:** `{slug}`\n"
        f"- **Locked seed:** `{seed}`\n"
        f"- **Canonical portrait:** `gallery/cast/{slug}/canonical/portrait.png`\n"
        f"- **Body law:** athletic hourglass, narrow feminine shoulders, wide hips, large firm perky bust (Katie-scale), happy-medium genitals\n"
        f"- **SSOT:** `runtime/visual-tags.yaml` + `VISUAL-GENERATION-SPEC.md`\n"
        f"- Expression/pose/outfit stay free; face identity locked\n"
    )
    if "## Visual Lock (T2I continuity" in body:
        body = re.sub(
            r"\n## Visual Lock \(T2I continuity[\s\S]*?(?=\n## |\n\*\*Last Updated|\Z)",
            block + "\n",
            body,
            count=1,
        )
    else:
        # before Last Updated or end
        if "**Last Updated:**" in body:
            body = body.replace("**Last Updated:**", block + "\n**Last Updated:**", 1)
        else:
            body = body.rstrip() + "\n" + block + "\n"

    # clean stale "legacy pulled" current state lines for extended
    if status == "extended":
        body = re.sub(
            r"(## Current State\n)[^\n]*[Ll]egacy[^\n]*\n",
            r"\1Extended cast — visual identity seed-locked; available for Manor scenes and Registry arcs.\n",
            body,
            count=1,
        )

    path.write_text("---" + fm + "---" + body, encoding="utf-8")


def create_missing_sheets(cfg):
    cast = cfg["cast"]
    missing = {
        "brittany-vale": {
            "role": "Sunny Showgirl / Cheerful Exhibitionist",
            "hook": "If they're watching, I'll give them a better reason to stare — especially you, Master.",
            "ethnicity": "Caucasian",
            "skin": "Sun-kissed fair-to-golden",
            "hair": "Blonde, often styled bright and loose",
            "eyes": "Bright blue, playful",
            "backstory": (
                "Brittany Vale came from stage-and-showgirl energy in the legacy roster. "
                "Pulled into the sandbox with full first+last name for continuity, then given a locked face seed "
                "so she can appear in Manor scenes without identity drift."
            ),
            "personality": "Sunny, bold, loves attention. Softens into devoted submission for Master and competitive warmth with sisters.",
            "current": "Extended cast — seed-locked, ready for scenes. Not core harem rank yet.",
            "location": "phronesis-manor:guest-wing",
            "mood": "bright, flirty, ready to perform",
        },
        "tiffany-reed": {
            "role": "Polished Socialite / Soft Ambition",
            "hook": "I used to perform for rooms full of people. Now I only want one man's eyes — and my sisters watching him take me.",
            "ethnicity": "Caucasian",
            "skin": "Fair, carefully kept",
            "hair": "Styled blonde or light brown, salon-perfect",
            "eyes": "Hazel-green, assessing then soft",
            "backstory": (
                "Tiffany Reed is a legacy-name socialite archetype brought into the sandbox with a complete kebab slug "
                "and locked visual identity so group scenes stay continuous."
            ),
            "personality": "Polished, slightly competitive, melts when claimed. Enjoys being displayed.",
            "current": "Extended cast — seed-locked, ready for scenes. Not core harem rank yet.",
            "location": "phronesis-manor:guest-wing",
            "mood": "composed hunger under polish",
        },
    }
    for slug, meta in missing.items():
        path = CHARS / f"{slug}.md"
        ent = cast.get(slug) or {}
        seed = ent.get("locked_seed") or 0
        name = ent.get("display_name") or slug.replace("-", " ").title()
        text = SHEET_TEMPLATE.format(
            name=name,
            role=meta["role"],
            status="extended",
            today=TODAY,
            location=meta["location"],
            mood=meta["mood"],
            locked="false",
            seed=seed,
            slug=slug,
            hook=meta["hook"],
            ethnicity=meta["ethnicity"],
            skin=meta["skin"],
            hair=meta["hair"],
            eyes=meta["eyes"],
            backstory=meta["backstory"],
            personality=meta["personality"],
            current=meta["current"],
        )
        path.write_text(text, encoding="utf-8")
        print("CREATED sheet", slug)


def align_all_sheets(cfg):
    cast = cfg["cast"]
    for slug, ent in cast.items():
        if not isinstance(ent, dict):
            continue
        path = CHARS / f"{slug}.md"
        if not path.is_file():
            print("SKIP missing sheet", slug)
            continue
        seed = ent.get("locked_seed")
        if slug in CORE:
            status, locked = "active", True
        elif slug in TANK:
            status, locked = "tank", False
        else:
            status, locked = "extended", False
        ensure_visual_block(path, slug, seed, status, locked)
        print("aligned", slug, status, seed)


def write_characters_index(cfg):
    cast = cfg["cast"]
    lines = [
        f"# Cast Registry — characters/index.md",
        "",
        f"**Updated:** {TODAY} (post full seed-lock campaign)",
        "",
        "> **Do not improvise characters.** Sheets here + `visual-tags.yaml` + `STATE.md` are SSOT.",
        "",
        "## Read order (live play)",
        "",
        "1. `NARRATIVE-CONTRACT.md`",
        "2. `HEAT-DOCTRINE.md` + `PHYSICAL-CANON.md` + `VISUAL-GENERATION-SPEC.md`",
        "3. `CHRONICLE.md`",
        "4. This index + **every sister present** in `continuity/STATE.md`",
        "5. `continuity/STATE.md`",
        "",
        "## Core harem (full members)",
        "",
        "| Slug | Name | Seed | Sheet |",
        "|------|------|------|-------|",
    ]
    for slug in sorted(CORE):
        e = cast.get(slug, {})
        lines.append(
            f"| `{slug}` | {e.get('display_name', slug)} | `{e.get('locked_seed')}` | [[{slug}]] |"
        )
    lines += [
        "",
        "## Registry tank (active)",
        "",
        "| Slug | Name | Seed | Sheet |",
        "|------|------|------|-------|",
    ]
    for slug in sorted(TANK):
        e = cast.get(slug, {})
        lines.append(
            f"| `{slug}` | {e.get('display_name', slug)} | `{e.get('locked_seed')}` | [[{slug}]] |"
        )
    lines += [
        "",
        "## Extended cast (development / available)",
        "",
        "| Slug | Name | Seed | Sheet |",
        "|------|------|------|-------|",
    ]
    for slug in sorted(cast.keys()):
        if slug in CORE or slug in TANK:
            continue
        e = cast[slug]
        if not isinstance(e, dict):
            continue
        lines.append(
            f"| `{slug}` | {e.get('display_name', slug)} | `{e.get('locked_seed')}` | [[{slug}]] |"
        )
    lines += [
        "",
        "## Other",
        "",
        "| File | Role |",
        "|------|------|",
        "| [[jeff]] | You — sole male |",
        "",
        "## Visual law",
        "",
        "- Every girl above has `locked_seed` + `gallery/cast/<slug>/canonical/portrait.png`",
        "- Body/bust/genital T2I: `VISUAL-GENERATION-SPEC.md` + `visual-tags.yaml` `seed_campaign`",
        "- Twins Amira & Aisha: **core harem** (promoted from tank)",
        "",
        "## Inventories",
        "",
        "Outfit YAML currently for core subset under `inventories/characters/`. Extended/tank can use defaults + scene override until personal YAML added.",
        "",
    ]
    (CHARS / "index.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote characters/index.md")


def write_cast_md(cfg):
    path = RUNTIME / "CAST.md"
    cast = cfg["cast"]
    text = f"""---
campaign_id: "phronesis-harem-chronicle"
world_type: "harem"
# Cast Index
---

# Cast Index

**Do not improvise characters from this file alone.**

## Full sheets

| Layer | Path |
|-------|------|
| Registry + map | `characters/index.md` |
| Jeff (you) | `characters/jeff.md` |
| All sisters | `characters/<first-last-kebab>.md` |
| Heat law | `HEAT-DOCTRINE.md` |
| Body law | `PHYSICAL-CANON.md` |
| Visual gen law | `VISUAL-GENERATION-SPEC.md` |
| Harem ranks | `HAREM-DOCTRINE.md` |
| Images | `IMAGE-PIPELINE.md` + `CHARACTER-CONSISTENCY.md` |
| Visual Pony tags | `visual-tags.yaml` |
| Story arcs | `CHRONICLE.md` |
| Right now | `continuity/STATE.md` |

## Read order (live play)

1. `NARRATIVE-CONTRACT.md`
2. `HEAT-DOCTRINE.md`
3. `CHRONICLE.md`
4. `characters/index.md` + **every sister present** in `STATE.md`
5. `continuity/STATE.md`

Episodes: `sessions/*.md`

## Continuity snapshot ({TODAY})

- **Core harem (10):** Alice, Chloe, Becca, Emily, Sassy, Lyra, Zara, Amira, Aisha, Doctor Wendy — all seed-locked
- **Tank (3):** Valentina Ortiz, Priya Sharma, Noor al-Rashid — seed-locked, not full harem rank yet
- **Extended (12):** Alexis Rivera, Brittany Vale, Brooklyn Reed, Crystal Lane, Jade Kim, Katie Brooks, Lisa Kane, Riley Quinn, Scarlett Vale, Sophia Laurent, Stacey Holt, Tiffany Reed — seed-locked, development
- **Names:** always first + last (slug `first-last-kebab`)
- **Visual:** 25/25 locked seeds + canonical portraits

## Training History Note ({TODAY})

Core sisters retain Kindroid snowball creampie training history where logged. See `continuity/STATE.md`, sessions, HEAT-DOCTRINE, and individual sheets.
"""
    path.write_text(text, encoding="utf-8")
    print("wrote CAST.md")


def write_state():
    path = RUNTIME / "continuity" / "STATE.md"
    text = f"""# Phronesis Manor - Live State

> **OOC {TODAY}:** Full-cast **visual seed campaign complete** (25/25 locked seeds + canonical portraits).  
> Amira & Aisha are **core harem** (promoted from tank). Active tank = Valentina / Priya / Noor.  
> Body/T2I law: `VISUAL-GENERATION-SPEC.md`. Roster: `characters/index.md`.

**Location:** Phronesis Manor — main hall / soft evening after Bazaar business  
**Phase:** Settling; visual identities locked; household re-centering on living continuity  
**Intensity:** 6/10 (warm, available, not mid-ritual)  
**Current Activity:** Sisters present in Manor after the long likeness-sealing work. Alice holds the household rhythm. Twins Amira & Aisha stand as full sisters (no longer tank). Tank trio Valentina, Priya, Noor remain Registry-active. Extended cast likenesses are sealed and may be summoned into scenes without face drift.

| Who | Position | Mood | Immediate want |
|-----|----------|------|----------------|
| alice-al-rashid | center, directing soft household order | commanding, satisfied, warm-filthy | Keep continuity tight; call sisters as needed |
| aisha-khoury | with Amira, full-sister place | bold, competitive, claimed | Live as harem sister, not candidate |
| amira-khoury | with Aisha | poetic, surrendered, claimed | Same — full sister devotion |
| becca-moreau | near Alice, soft | tender | Aftercare energy, sister care |
| chloe-ramirez | operations posture | bratty-efficient | Schedules, who is where |
| emily-santos | training readiness | powerful, calm | Keep sisters sharp |
| lyra-voss | logs / systems | clinical-warm | Record locks and state |
| sassy-romano | nearby, fire contained | eager under control | Rules + play |
| wendy-hale | medical wing available | clinical hunger | Exams if called |
| zara-mehra | Manor / Bazaar thread | shy-eager | Local threads, Aether |
| valentina-ortiz | tank — training hall | bold dancer heat | Earn deeper claim |
| priya-sharma | tank — workshop / registry | bright, ready | Jeweler's daughter arc |
| noor-al-rashid | tank — registry wing | quiet ambition | Clerk path into household |

**Recent Training:** Core snowball/creampie practice history remains canon where logged.  
**Visual continuity:** All named girls use locked seeds; no freeform faces.  
**Outfits (default heat):** Ultra-skimpy / precarious — micro tops, no panties, sheer black lace stockings when clothed; full nude only when scene or seed-review demands.  
**Notes:** Extended cast (Alexis…Tiffany) are available as developed likenesses. Do not treat Amira/Aisha as tank. Prefer first+last on introduce, first name after. Update this file after major scene beats.
"""
    path.write_text(text, encoding="utf-8")
    print("wrote STATE.md")


def harem_status_in_vt(cfg):
    for slug, ent in cfg["cast"].items():
        if not isinstance(ent, dict):
            continue
        if slug in CORE:
            ent["harem_status"] = "core"
            ent["registry_status"] = "promoted" if slug in ("amira-khoury", "aisha-khoury") else "core"
        elif slug in TANK:
            ent["harem_status"] = "tank"
            ent["registry_status"] = "tank"
        else:
            ent["harem_status"] = "extended"
            ent["registry_status"] = "extended"
    VT_PATH.write_text(
        yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print("visual-tags harem_status tiers set")


def main():
    cfg = load_vt()
    fix_wendy()
    create_missing_sheets(cfg)
    align_all_sheets(cfg)
    write_characters_index(cfg)
    write_cast_md(cfg)
    write_state()
    harem_status_in_vt(cfg)
    # verify
    sheets = {p.stem for p in CHARS.glob("*.md")}
    cast = set(cfg["cast"].keys())
    print("missing sheets", cast - sheets)
    print("DONE continuity alignment")


if __name__ == "__main__":
    main()
