#!/usr/bin/env python3
"""Promote Amira & Aisha Khoury from Registry tank → full core harem. Clean relics."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import yaml

SANDBOX = Path(r"D:\PhronesisVault\Roleplay-Sandbox")
REG = SANDBOX / "registry"
CAND = REG / "candidates"
PROMOTED = REG / "promoted" / "khoury-twins-20260710"
ARCHIVE_NOTE = SANDBOX / "registry" / "promoted" / "README.md"
LOG = SANDBOX / "logs" / f"twin-harem-promotion-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
STAMP = "2026-07-10"


def main() -> int:
    PROMOTED.mkdir(parents=True, exist_ok=True)
    moved = []
    for slug in ("amira-khoury", "aisha-khoury"):
        src = CAND / slug
        if not src.is_dir():
            print(f"SKIP missing {src}")
            continue
        dest = PROMOTED / slug
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(src), str(dest))
        moved.append(slug)
        # Update dossier + meta in promoted location
        dossier = dest / "dossier.md"
        if dossier.is_file():
            text = dossier.read_text(encoding="utf-8")
            text = text.replace("status: tank", f"status: promoted-harem\npromoted_at: {STAMP}\nformer_status: tank")
            text = text.replace("Registry Candidate (Tank)", "Full Harem Member (promoted from tank)")
            text = text.replace("type: registry-candidate", "type: harem-member\nformer_type: registry-candidate")
            # Title line
            text = text.replace(
                f"# {slug.split('-')[0].title()} Khoury — Registry Candidate (Tank)",
                f"# {slug.split('-')[0].title()} Khoury — Full Harem Member",
            )
            # Amira title may truncate
            text = text.replace(
                "# Amira Khoury — Registry Candidate (Tank)",
                "# Amira Khoury — Full Harem Member",
            )
            text = text.replace(
                "# Aisha Khoury — Registry Candidate (Tank)",
                "# Aisha Khoury — Full Harem Member",
            )
            # footer note
            if "PROMOTED TO FULL HAREM" not in text:
                text = text.rstrip() + (
                    f"\n\n---\n\n**PROMOTED TO FULL HAREM** ({STAMP}). "
                    "No longer Registry tank. SSOT character sheet: "
                    f"`runtime/characters/{slug}.md`. Locked seed campaign complete.\n"
                )
            dossier.write_text(text, encoding="utf-8")
        meta_p = dest / "meta.json"
        if meta_p.is_file():
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            meta["status"] = "promoted-harem"
            meta["former_status"] = "tank"
            meta["promoted_at"] = STAMP
            meta["harem_tier"] = "core"
            meta["character_sheet"] = f"runtime/characters/{slug}.md"
            meta["notes"] = (
                str(meta.get("notes") or "")
                + f" | Promoted from tank {STAMP}; core harem twin."
            ).strip(" |")
            meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"MOVED {slug} -> {dest}")

    # Pointer stubs left in candidates so old links don't 404 hard
    for slug in ("amira-khoury", "aisha-khoury"):
        stub = CAND / slug
        stub.mkdir(parents=True, exist_ok=True)
        (stub / "PROMOTED.md").write_text(
            f"""# {slug} — PROMOTED (not tank)

**Status:** full core harem member  
**Promoted:** {STAMP}  
**Dossier archive:** `registry/promoted/khoury-twins-20260710/{slug}/`  
**Live SSOT:** `runtime/characters/{slug}.md`  
**Visual SSOT:** `runtime/visual-tags.yaml` cast `{slug}`  
**Canonical portrait:** `gallery/cast/{slug}/canonical/portrait.png`

Do **not** treat this folder as an active tank candidate.
""",
            encoding="utf-8",
        )

    # promoted README
    ARCHIVE_NOTE.write_text(
        f"""# registry/promoted

Sisters who left the **Registry tank** and joined the **core harem**.

| Folder | Who | When |
|--------|-----|------|
| `khoury-twins-20260710/` | Amira & Aisha Khoury | {STAMP} |

Active tank remains under `registry/candidates/` (Valentina, Priya, Noor, extended).
""",
        encoding="utf-8",
    )

    # HAREM-DOCTRINE
    doctrine = SANDBOX / "runtime" / "HAREM-DOCTRINE.md"
    dt = doctrine.read_text(encoding="utf-8")
    old = (
        "**Promoted to tank (Registry):** Amira & Aisha Khoury (Arabian twins), "
        "Valentina Ortiz, Priya Sharma, Noor al-Rashid."
    )
    new = (
        f"**Core harem (full members):** Alice, Chloe, Becca, Emily, Sassy, Lyra, Zara, "
        f"**Amira & Aisha Khoury** (Arabian twins — promoted from tank {STAMP}), Doctor Wendy.\n\n"
        f"**Active Registry tank:** Valentina Ortiz, Priya Sharma, Noor al-Rashid "
        f"(plus extended candidates under `registry/candidates/`)."
    )
    if old in dt:
        dt = dt.replace(old, new)
    elif "Active Registry tank" not in dt:
        dt = dt.replace(
            "**Promoted to tank (Registry):**",
            new + "\n\n**Promoted to tank (Registry) [superseded]:**",
        )
    # snowball already lists twins as sisters - ok
    doctrine.write_text(dt, encoding="utf-8")
    print("Updated HAREM-DOCTRINE.md")

    # STATE.md — mark twins as full sisters, not tank review subjects
    state = SANDBOX / "runtime" / "continuity" / "STATE.md"
    if state.is_file():
        st = state.read_text(encoding="utf-8")
        # prepend promotion banner if not present
        banner = (
            f"\n> **OOC {STAMP}:** Amira & Aisha Khoury **promoted out of Registry tank** "
            f"→ full core harem. Live tank = Valentina / Priya / Noor (+ extended). "
            f"See `registry/promoted/khoury-twins-20260710/`.\n"
        )
        if "promoted out of Registry tank" not in st:
            # insert after first heading block
            lines = st.splitlines(keepends=True)
            if lines and lines[0].startswith("#"):
                st = lines[0] + banner + "".join(lines[1:])
            else:
                st = banner + st
        st = st.replace("registry tank girls (Amira and Aisha Khoury dossiers)", "full-sister twins Amira and Aisha (post-promotion)")
        st = st.replace("twin's tank status", "twin's full harem sister status")
        st = st.replace("intellectual tank details", "intellectual sister devotion")
        st = st.replace("(gold-star, tank,", "(gold-star, full harem,")
        state.write_text(st, encoding="utf-8")
        print("Updated STATE.md")

    # RPG-CARD note
    rpg = SANDBOX / "docs" / "RPG-CARD-ARCHITECTURE.md"
    if rpg.is_file():
        rt = rpg.read_text(encoding="utf-8")
        rt = rt.replace(
            "Only Amira & Aisha are literal twins (currently tank/candidate status).",
            f"Only Amira & Aisha are literal twins (full core harem members as of {STAMP}; no longer tank).",
        )
        rpg.write_text(rt, encoding="utf-8")
        print("Updated RPG-CARD-ARCHITECTURE.md")

    # gallery README if tank line
    gal = SANDBOX / "gallery" / "README.md"
    if gal.is_file():
        gt = gal.read_text(encoding="utf-8")
        if "Tank candidates" in gt and "promoted" not in gt.lower():
            gt = gt.replace(
                "registry/                # Tank candidates (not yet core cast)",
                "registry/                # Tank candidates + promoted/ archive\n"
                "# promoted/               # Former tank now core (e.g. Khoury twins)",
            )
            gal.write_text(gt, encoding="utf-8")
            print("Updated gallery README")

    # registry 00-INDEX
    idx = REG / "00-INDEX.md"
    idx.write_text(
        f"""# registry — 00-INDEX

**Updated:** {STAMP}

## Cast lock
See `CAST-LOCK-RULE.md`

## Promoted from tank → core harem
| Who | Archive |
|-----|---------|
| Amira & Aisha Khoury | `promoted/khoury-twins-20260710/` |

Live character SSOT: `runtime/characters/amira-khoury.md`, `aisha-khoury.md`  
Visual SSOT: `runtime/visual-tags.yaml`

## Active tank / candidates
| Candidate | dossier | meta | notes |
|----------|---------|------|-------|
| `valentina-ortiz` | Y | Y | tank |
| `priya-sharma` | Y | Y | tank |
| `noor-al-rashid` | Y | Y | tank |
| extended cast (alexis, crystal, …) | varies | - | development |

**Stubs** under `candidates/amira-khoury` and `candidates/aisha-khoury` are pointers only (`PROMOTED.md`).

## Paths
- Active tank: `registry/candidates/`
- Promoted archive: `registry/promoted/`
- Core cast portraits: `gallery/cast/<slug>/canonical/`
""",
        encoding="utf-8",
    )
    print("Rewrote registry/00-INDEX.md")

    # visual-tags twin_pairs + harem_status
    vt = SANDBOX / "runtime" / "visual-tags.yaml"
    cfg = yaml.safe_load(vt.read_text(encoding="utf-8"))
    for slug in ("amira-khoury", "aisha-khoury"):
        e = cfg["cast"][slug]
        e["harem_status"] = "core"
        e["registry_status"] = "promoted"
        e["promoted_at"] = STAMP
    tp = cfg.setdefault("twin_pairs", {}).setdefault("khoury", {})
    tp["harem_status"] = "core"
    tp["registry_status"] = "promoted"
    tp["promoted_at"] = STAMP
    tp["tank"] = False
    vt.write_text(
        yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print("Updated visual-tags harem_status")

    # character sheets — ensure status active + note
    for slug, name in (("amira-khoury", "Amira"), ("aisha-khoury", "Aisha")):
        sheet = SANDBOX / "runtime" / "characters" / f"{slug}.md"
        if not sheet.is_file():
            continue
        t = sheet.read_text(encoding="utf-8")
        if "status: active" not in t and "status:" in t[:400]:
            t = t.replace("status: tank", "status: active", 1)
        if f"promoted out of tank {STAMP}" not in t:
            # after frontmatter
            if t.startswith("---"):
                parts = t.split("---", 2)
                if len(parts) >= 3:
                    body = parts[2]
                    note = (
                        f"\n\n> **Promotion ({STAMP}):** {name} is a **full core harem sister**, "
                        f"no longer Registry tank. Former tank dossier archived under "
                        f"`registry/promoted/khoury-twins-20260710/{slug}/`.\n"
                    )
                    t = "---" + parts[1] + "---" + note + body
            sheet.write_text(t, encoding="utf-8")
            print(f"Annotated {sheet.name}")

    # CANON-MAP light touch if line exists
    cm = SANDBOX / "docs" / "CANON-MAP.md"
    if cm.is_file():
        cmt = cm.read_text(encoding="utf-8")
        if "tank/candidate" in cmt.lower() or "registry/candidates/amira" in cmt:
            cmt2 = cmt.replace(
                "`registry/candidates/amira-khoury`, `aisha-khoury`",
                f"`runtime/characters/*-khoury.md` + `registry/promoted/khoury-twins-20260710/` (promoted {STAMP})",
            )
            if cmt2 != cmt:
                cm.write_text(cmt2, encoding="utf-8")
                print("Updated CANON-MAP.md")

    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(
        f"""# Twin promotion log — {STAMP}

## Action
Amira & Aisha Khoury: **Registry tank → full core harem**.

## Changes
- Moved `registry/candidates/{{amira,aisha}}-khoury/` → `registry/promoted/khoury-twins-20260710/`
- Left `PROMOTED.md` stubs in old candidate paths
- Updated: HAREM-DOCTRINE, STATE.md, RPG-CARD-ARCHITECTURE, registry/00-INDEX, visual-tags, character sheets
- Dossier/meta status → `promoted-harem`

## Active tank now
Valentina Ortiz · Priya Sharma · Noor al-Rashid (+ extended candidates)

## Seed locks (campaign)
- amira-khoury: see visual-tags locked_seed
- aisha-khoury: see visual-tags locked_seed
""",
        encoding="utf-8",
    )
    print("LOG", LOG)
    print("DONE moved", moved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
