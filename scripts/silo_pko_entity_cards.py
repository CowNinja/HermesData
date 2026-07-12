#!/usr/bin/env python3
"""PKO entity cards — rich vault pages (retroactive backfill OK).

Pulls full entity_context fields + person_file_graph samples + org/place cross-links.
Re-running overwrites cards with fuller detail as graph/OCR grow.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ENTITY = Path(r"D:\HermesData\config\entity_context.json")
GRAPH = Path(r"D:\HermesData\state\person_file_graph.sqlite3")
REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
OUT = Path(r"D:\PhronesisVault\Research\Silo-Entities")
INDEX = OUT / "00-INDEX.md"


def slug(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", name.strip(), flags=re.U)
    return s.strip("-")[:80] or "entity"


def main() -> int:
    data = json.loads(ENTITY.read_text(encoding="utf-8"))
    people = data.get("people") or []
    orgs = data.get("orgs") or []
    places = data.get("places") or []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    OUT.mkdir(parents=True, exist_ok=True)

    link_counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    if GRAPH.is_file():
        con = sqlite3.connect(str(GRAPH))
        for can, c in con.execute(
            """SELECT p.canonical, COUNT(*) FROM links l
               JOIN people p ON p.id=l.person_id GROUP BY p.canonical"""
        ):
            link_counts[str(can)] = int(c)
        for can, src in con.execute(
            """SELECT p.canonical, l.source_path FROM links l
               JOIN people p ON p.id=l.person_id"""
        ):
            samples.setdefault(str(can), [])
            if src and len(samples[str(can)]) < 12:
                samples[str(can)].append(src)
        con.close()

    # registry path hits by name token (light)
    reg_hits: dict[str, int] = {}
    if REG.is_file():
        rcon = sqlite3.connect(str(REG))
        for pe in people:
            can = pe.get("canonical")
            if not can or len(str(can)) < 5:
                continue
            # use longest name fragment
            names = pe.get("names") or [can]
            best = 0
            for n in names:
                n = str(n).strip()
                if len(n) < 5 or " " not in n and len(n) < 8:
                    continue
                try:
                    c = rcon.execute(
                        "SELECT COUNT(*) FROM ingest WHERE source_path LIKE ?",
                        (f"%{n}%",),
                    ).fetchone()[0]
                    best = max(best, int(c))
                except Exception:
                    pass
            if best:
                reg_hits[str(can)] = best
        rcon.close()

    written = 0
    index_lines = [
        f"# Silo entity cards — {ts}",
        "",
        "Rich PKO pages from `entity_context` + graph + registry. **Re-run anytime to retrofill.**",
        "",
        "| Person | Role | Domain | File links |",
        "|--------|------|--------|----------:|",
    ]

    for pe in people:
        can = pe.get("canonical")
        if not can:
            continue
        conf = pe.get("confidence") or ""
        # skip pure junk placeholders
        low = str(can).lower()
        if any(x in low for x in ("accepted", "dental enrollment", "blood chemistry", "fs i a l")):
            continue
        if conf not in ("confirmed", "high", "inferred", "") and not pe.get("notes") and not pe.get("role"):
            continue

        path = OUT / f"{slug(str(can))}.md"
        names = pe.get("names") or pe.get("aliases") or [can]
        lc = link_counts.get(str(can), 0)
        rh = reg_hits.get(str(can), 0)
        samp = samples.get(str(can), [])[:8]

        body = [
            f"# {can}",
            "",
            f"_Updated {ts} · auto PKO card · re-run backfills as graph grows_",
            "",
            "## Identity",
            f"- **Canonical:** {can}",
            f"- **Also known as:** {', '.join(str(n) for n in names[:12])}",
            f"- **Confidence:** {conf or 'n/a'}",
            f"- **Role:** {pe.get('role') or '—'}",
            f"- **Domain shelf:** `{pe.get('domain') or '—'}`",
        ]
        if pe.get("email"):
            body.append(f"- **Email:** `{pe.get('email')}`")
        if pe.get("org"):
            body.append(f"- **Org:** {pe.get('org')}")
        if pe.get("spouse"):
            body.append(f"- **Spouse:** {pe.get('spouse')}")
        if pe.get("tags"):
            body.append(f"- **Tags:** {', '.join(pe.get('tags') or [])}")
        if pe.get("birthday") or pe.get("dob"):
            body.append(f"- **Birthday:** {pe.get('birthday') or pe.get('dob')}")

        body += ["", "## Notes (codified)"]
        notes = pe.get("notes") or pe.get("note") or "_(thin — will thicken as OCR/links grow)_"
        body.append(str(notes))

        if pe.get("relationships"):
            body += ["", "## Relationships"]
            body.append(str(pe.get("relationships")))

        body += [
            "",
            "## Silo evidence",
            f"- **Graph file links:** {lc}",
            f"- **Registry path hits (name search):** {rh}",
            "",
            "### Sample source paths",
        ]
        if samp:
            for s in samp:
                body.append(f"- `{s}`")
        else:
            body.append("- _(no graph links yet — entity locked from interview/path rules)_")

        # soft related orgs by keyword in notes
        blob = json.dumps(pe).lower()
        related_orgs = []
        for o in orgs:
            on = str(o.get("canonical") or "")
            aliases = " ".join(str(x) for x in (o.get("names") or [])).lower()
            if on and (on.lower() in blob or any(a and a in blob for a in aliases.split() if len(a) > 4)):
                related_orgs.append(on)
        if related_orgs:
            body += ["", "## Related orgs/places (heuristic)"]
            for o in related_orgs[:8]:
                body.append(f"- [[{slug(o)}]]" if False else f"- **{o}**")

        body += [
            "",
            "## Twin / future use",
            "- Cite this card + source paths; do not invent relationships beyond Notes.",
            "- Depth increases when OCR/STT and graph workers re-link files.",
            "",
            "## See also",
            "- [[00-LIFE-GRAPH]]",
            "- [[00-INDEX]]",
            "- [[Navy-Career-Arc]]",
            "- [[Navy-Rank-And-Legal]]",
            "",
        ]
        path.write_text("\n".join(body), encoding="utf-8")
        written += 1
        index_lines.append(
            f"| [[{slug(str(can))}\\|{can}]] | {pe.get('role') or '—'} | {pe.get('domain') or '—'} | {lc} |"
        )

    # org cards (lighter)
    org_dir = OUT / "orgs"
    org_dir.mkdir(exist_ok=True)
    for o in orgs:
        can = o.get("canonical")
        if not can:
            continue
        op = org_dir / f"{slug(str(can))}.md"
        op.write_text(
            "\n".join(
                [
                    f"# {can}",
                    "",
                    f"_Org/command · {ts}_",
                    "",
                    f"- **Names:** {', '.join(str(x) for x in (o.get('names') or [can])[:10])}",
                    f"- **Domain:** {o.get('domain') or '—'}",
                    f"- **Type:** {o.get('type') or '—'}",
                    f"- **Notes:** {o.get('notes') or '—'}",
                    "",
                    "[[00-LIFE-GRAPH]]",
                ]
            ),
            encoding="utf-8",
        )

    index_lines += [
        "",
        f"_People cards written: **{written}** · Orgs: **{len(orgs)}** · Places in entity_context: **{len(places)}**_",
        "",
        "## Retrofill policy",
        "Re-run `python D:/HermesData/scripts/silo_pko_entity_cards.py` anytime — cards get richer as notes, graph links, and registry hits grow.",
    ]
    INDEX.write_text("\n".join(index_lines), encoding="utf-8")
    print(json.dumps({"written": written, "orgs": len(orgs), "out": str(OUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
