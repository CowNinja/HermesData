#!/usr/bin/env python3
"""Person ↔ file link graph for twin/query.

Builds D:\\HermesData\\state\\person_file_graph.sqlite3
from entity_context + registry source/dest paths + optional .ocr.md peeks.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
ENTITY = Path(r"D:\HermesData\config\entity_context.json")
GRAPH = Path(r"D:\HermesData\state\person_file_graph.sqlite3")
LOG = Path(r"D:\PhronesisVault\Operations\logs\person-file-graph-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS people (
          id INTEGER PRIMARY KEY,
          canonical TEXT UNIQUE,
          domain TEXT,
          role TEXT,
          names_json TEXT
        );
        CREATE TABLE IF NOT EXISTS links (
          id INTEGER PRIMARY KEY,
          person_id INTEGER,
          source_path TEXT,
          dest_path TEXT,
          domain TEXT,
          match_name TEXT,
          evidence TEXT,
          updated_at TEXT,
          UNIQUE(person_id, source_path)
        );
        CREATE INDEX IF NOT EXISTS idx_links_person ON links(person_id);
        CREATE INDEX IF NOT EXISTS idx_links_domain ON links(domain);
        """
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-files", type=int, default=50000)
    args = ap.parse_args()

    people_raw = json.loads(ENTITY.read_text(encoding="utf-8")).get("people") or []
    JUNK_CANON = {
        "relayed accepted", "accepted", "dental", "invitation dental", "notes",
        "doctor", "friend", "family", "dad", "mom",
    }
    people_raw = [pe for pe in people_raw if str(pe.get("canonical") or "").lower() not in JUNK_CANON]
    GRAPH.parent.mkdir(parents=True, exist_ok=True)
    g = sqlite3.connect(str(GRAPH))
    init_db(g)

    person_rows = []
    for pe in people_raw:
        can = pe.get("canonical")
        if not can:
            continue
        names = list(pe.get("names") or []) + list(pe.get("aliases") or [])
        names.append(str(can))
        # longest first
        STOP = {
            "accepted", "dental", "notes", "doctor", "friend", "family", "bloom",
            "sarah", "david", "admin", "user", "file", "copy", "medical", "navy",
        }
        cleaned = []
        for n in names:
            n = (n or "").strip()
            low = n.lower()
            if low in STOP:
                continue
            if "@" in n and "." in n:
                cleaned.append(n)  # email handle
                continue
            # multi-word only for people names (first principles: reduce false links)
            if " " not in n and "-" not in n:
                continue
            if len(n) < 6:
                continue
            cleaned.append(n)
        names = sorted(set(cleaned), key=len, reverse=True)
        g.execute(
            "INSERT INTO people(canonical, domain, role, names_json) VALUES(?,?,?,?) "
            "ON CONFLICT(canonical) DO UPDATE SET domain=excluded.domain, role=excluded.role, names_json=excluded.names_json",
            (can, pe.get("domain"), pe.get("role"), json.dumps(names)),
        )
        person_rows.append((can, names, pe.get("domain")))
    g.commit()

    # map canonical -> id
    id_map = {r[0]: r[1] for r in g.execute("SELECT canonical, id FROM people")}

    reg = sqlite3.connect(str(DB_REG))
    rows = reg.execute(
        "SELECT source_path, dest_path, domain FROM ingest LIMIT ?",
        (args.limit_files,),
    ).fetchall()
    reg.close()

    links = 0
    for src, dest, dom in rows:
        blob = f"{src or ''} {dest or ''}".lower()
        for can, names, pdom in person_rows:
            for n in names:
                nl = n.lower()
                if "@" in nl:
                    hit = nl in blob  # emails only exact
                elif " " in nl:
                    hit = nl in blob
                else:
                    # long single tokens only with word boundaries
                    hit = re.search(r"(?<![a-z0-9])" + re.escape(nl) + r"(?![a-z0-9])", blob) is not None
                if hit:
                    pid = id_map[can]
                    try:
                        g.execute(
                            "INSERT OR IGNORE INTO links(person_id, source_path, dest_path, domain, match_name, evidence, updated_at) "
                            "VALUES(?,?,?,?,?,?,?)",
                            (pid, src, dest, dom, n, "path_match", utc()),
                        )
                        if g.total_changes:
                            links += 1
                    except Exception:
                        pass
                    break
    g.commit()

    # stats
    total_people = g.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    total_links = g.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    top = g.execute(
        """
        SELECT p.canonical, COUNT(*) c FROM links l
        JOIN people p ON p.id=l.person_id
        GROUP BY p.canonical ORDER BY c DESC LIMIT 15
        """
    ).fetchall()
    g.close()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Person–file graph — {utc()}",
        "",
        f"- people: **{total_people}**",
        f"- links: **{total_links}** (new this run path matches counted loosely)",
        "",
        "| Person | Files |",
        "|--------|------:|",
    ]
    for name, c in top:
        lines.append(f"| {name} | {c} |")
    LOG.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "people": total_people,
                "links": total_links,
                "top": top[:8],
                "db": str(GRAPH),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
