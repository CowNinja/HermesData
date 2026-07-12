#!/usr/bin/env python3
"""PKO entity cards — durable vault pages citing silo provenance.

Writes D:\\PhronesisVault\\Research\\Silo-Entities\\ for confirmed people.
personal-knowledge-os posture: file knowledge, don't leave it in chat only.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ENTITY = Path(r"D:\HermesData\config\entity_context.json")
GRAPH = Path(r"D:\HermesData\state\person_file_graph.sqlite3")
OUT = Path(r"D:\PhronesisVault\Research\Silo-Entities")
INDEX = OUT / "00-INDEX.md"


def slug(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", name.strip(), flags=re.U)
    return s.strip("-")[:80] or "entity"


def main() -> int:
    data = json.loads(ENTITY.read_text(encoding="utf-8"))
    people = data.get("people") or []
    OUT.mkdir(parents=True, exist_ok=True)

    link_counts = {}
    if GRAPH.is_file():
        con = sqlite3.connect(str(GRAPH))
        for can, c in con.execute(
            """
            SELECT p.canonical, COUNT(*) FROM links l
            JOIN people p ON p.id=l.person_id GROUP BY p.canonical
            """
        ):
            link_counts[can] = c
        # sample files
        samples = {}
        for can, src in con.execute(
            """
            SELECT p.canonical, l.source_path FROM links l
            JOIN people p ON p.id=l.person_id
            ORDER BY p.canonical
            """
        ):
            samples.setdefault(can, [])
            if len(samples[can]) < 8:
                samples[can].append(src)
        con.close()
    else:
        samples = {}

    written = 0
    index_lines = [
        f"# Silo entity cards — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
        "Compiled from `entity_context` + person_file_graph. PKO posture.",
        "",
    ]

    for pe in people:
        can = pe.get("canonical")
        if not can or pe.get("confidence") not in (None, "confirmed", "high", "inferred"):
            # write confirmed + high priority always; skip pure placeholders with no names
            pass
        if not can:
            continue
        # Prefer confirmed / sisters / doctors / friends with notes
        conf = pe.get("confidence") or ""
        if conf not in ("confirmed", "high") and not pe.get("notes"):
            if not pe.get("role"):
                continue

        path = OUT / f"{slug(str(can))}.md"
        names = pe.get("names") or pe.get("aliases") or []
        body = [
            f"# {can}",
            "",
            f"- **Domain:** {pe.get('domain')}",
            f"- **Role:** {pe.get('role')}",
            f"- **Confidence:** {pe.get('confidence')}",
            f"- **Updated:** {pe.get('updated')}",
            f"- **Silo file links:** {link_counts.get(can, 0)}",
            "",
            "## Names / aliases",
            "",
        ]
        for n in names:
            body.append(f"- {n}")
        if pe.get("birthday"):
            body.append(f"\n**Birthday:** {pe.get('birthday')}\n")
        if pe.get("spouse"):
            body.append(f"\n**Spouse:** [[{slug(str(pe['spouse']))}|{pe['spouse']}]]\n")
        if pe.get("relationships"):
            body.append("\n## Relationships\n")
            for r in pe["relationships"]:
                body.append(f"- {r}")
        if pe.get("marital_history"):
            body.append("\n## Marital history\n")
            body.append("```json\n" + json.dumps(pe["marital_history"], indent=2) + "\n```\n")
        if pe.get("notes"):
            body.append(f"\n## Notes\n\n{pe['notes']}\n")
        if samples.get(can):
            body.append("\n## Sample source paths (silo)\n")
            for s in samples[can]:
                body.append(f"- `{s}`")
        body.append(
            f"\n---\n_Generated {datetime.now(timezone.utc).isoformat()} by silo_pko_entity_cards.py_\n"
        )
        path.write_text("\n".join(body), encoding="utf-8")
        written += 1
        index_lines.append(f"- [[{slug(str(can))}|{can}]] — {pe.get('role')} · links {link_counts.get(can, 0)}")

    INDEX.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    print(json.dumps({"written": written, "out": str(OUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
