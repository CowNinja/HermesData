#!/usr/bin/env python3
"""Person <-> file link graph for twin/query.

Builds D:\\HermesData\\state\\person_file_graph.sqlite3
from entity_context + registry source/dest paths + optional .ocr.md peeks.

Hub-cap lock (2026-07-21, C6 re-inflate):
  Rebuild is additive (INSERT OR IGNORE). Without a post-build path_match
  cap, hubs like dameion re-inflate past board yellow (400) after every orch
  person_file_graph worker — even when densify hygiene later trims them.
  Lessons: entity-resolution degree caps (hub-and-spoke / power-law outliers),
  cap-at-write not only post-hoc, prefer multi-word person tokens.
  Default: keep at most --hub-keep path_match links per person (350 < yellow 400).
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
STATE_JSON = Path(r"D:\HermesData\state\person_file_graph_build.json")

# Board yellow floor is 400 path_match; keep below so C6 stays green after rebuild.
DEFAULT_HUB_KEEP = 350
DEFAULT_HUB_TRIM_ABOVE = 400


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


def add_sidecar_text_evidence(
    con: sqlite3.Connection,
    person_rows: list,
    id_map: dict,
    limit: int = 400,
    roots: list[Path] | None = None,
) -> dict:
    """Bounded text_match/sidecar_text links from .train.md / .ocr.md peeks.

    2026-07-21 C6 evidence-mix: board was 100% path_match. ER lesson (Splink /
    record linkage) — path co-occurrence is weak evidence; sidecar text is
    stronger and diversifies evidence_mix without reckless entity promote.

    UNIQUE(person_id, source_path): use sidecar path as source_path so text
    evidence coexists with path_match rows on the dest file.
    """
    if limit <= 0:
        return {"scanned": 0, "inserted": 0, "skipped": "limit_0"}
    SILO = Path(r"K:/Phronesis-Sovereign/Personal-Digital-Silo")
    roots = roots or [
        SILO / "Medical-Records",
        SILO / "Navy-Service",
        SILO / "Core-Personal" / "Family",
        SILO / "Core-Personal" / "Career",
        SILO / "Core-Personal" / "Projects" / "from-g-drive" / "Booksbloom",
    ]
    # multiword names only (already cleaned in person_rows)
    name_index: list[tuple[str, str, int]] = []  # (name_lower, canonical, pid)
    for can, names, _pdom in person_rows:
        pid = id_map.get(can)
        if not pid:
            continue
        for n in names:
            nl = (n or "").strip().lower()
            if len(nl) < 6:
                continue
            if " " not in nl and "-" not in nl and "@" not in nl:
                continue
            name_index.append((nl, can, pid))
    name_index.sort(key=lambda x: -len(x[0]))
    scanned = 0
    inserted = 0
    hits_by_ev = {"sidecar_text": 0}
    for root in roots:
        if not root.is_dir():
            continue
        for pat in ("*.train.md", "*.ocr.md"):
            try:
                iterator = root.rglob(pat)
            except Exception:
                continue
            for side in iterator:
                if scanned >= limit:
                    break
                if not side.is_file():
                    continue
                scanned += 1
                try:
                    if side.stat().st_size > 400_000:
                        continue
                    text = side.read_text(encoding="utf-8", errors="ignore")[:80_000].lower()
                except Exception:
                    continue
                if len(text) < 40:
                    continue
                dest = str(side)
                # strip sidecar suffix to related primary when obvious
                primary = re.sub(r"\.(train|ocr)\.md$", "", dest, flags=re.I)
                for nl, can, pid in name_index:
                    if "@" in nl:
                        hit = nl in text
                    else:
                        hit = nl in text
                    if not hit:
                        continue
                    src = str(side)  # unique vs path_match primary paths
                    try:
                        cur = con.execute(
                            "INSERT OR IGNORE INTO links(person_id, source_path, dest_path, domain, match_name, evidence, updated_at) "
                            "VALUES(?,?,?,?,?,?,?)",
                            (pid, src, primary, "sidecar_text", nl, "sidecar_text", utc()),
                        )
                        if cur.rowcount and cur.rowcount > 0:
                            inserted += 1
                            hits_by_ev["sidecar_text"] += 1
                    except Exception:
                        pass
                    break  # one person hit per sidecar (longest names first)
            if scanned >= limit:
                break
        if scanned >= limit:
            break
    return {
        "scanned": scanned,
        "inserted": inserted,
        "by_evidence": hits_by_ev,
        "name_index_n": len(name_index),
    }


def trim_path_match_hubs(
    con: sqlite3.Connection, keep: int = DEFAULT_HUB_KEEP, above: int = DEFAULT_HUB_TRIM_ABOVE
) -> list[dict]:
    """Cap path_match degree per person. Non-path_match evidence kept intact."""
    hubs = con.execute(
        """
        SELECT p.id, p.canonical, COUNT(*) c
        FROM links l JOIN people p ON p.id=l.person_id
        GROUP BY p.id
        HAVING c > ?
        ORDER BY c DESC
        """,
        (above,),
    ).fetchall()
    trimmed = []
    for pid, can, c in hubs:
        rows = con.execute(
            "SELECT id FROM links WHERE person_id=? AND evidence='path_match' ORDER BY id",
            (pid,),
        ).fetchall()
        if len(rows) > keep:
            drop = [r[0] for r in rows[:-keep]]
            con.executemany("DELETE FROM links WHERE id=?", [(i,) for i in drop])
            trimmed.append(
                {
                    "canonical": can,
                    "before": int(c),
                    "dropped_path_match": len(drop),
                    "keep_path_match": keep,
                }
            )
    return trimmed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-files", type=int, default=50000)
    ap.add_argument("--hub-keep", type=int, default=DEFAULT_HUB_KEEP,
                    help="max path_match links kept per person after build")
    ap.add_argument("--hub-trim-above", type=int, default=DEFAULT_HUB_TRIM_ABOVE,
                    help="only trim people whose total links exceed this")
    ap.add_argument("--no-hub-cap", action="store_true",
                    help="disable post-build hub cap (debug only)")
    ap.add_argument(
        "--sidecar-text-limit",
        type=int,
        default=500,
        help="max .train.md/.ocr.md peeks for sidecar_text evidence (0=skip)",
    )
    args = ap.parse_args()

    people_raw = json.loads(ENTITY.read_text(encoding="utf-8")).get("people") or []
    JUNK_CANON = {
        "relayed accepted", "accepted", "dental", "invitation dental", "notes",
        "doctor", "friend", "family", "dad", "mom",
    }
    people_raw = [pe for pe in people_raw if str(pe.get("canonical") or "").lower() not in JUNK_CANON]
    GRAPH.parent.mkdir(parents=True, exist_ok=True)
    g = sqlite3.connect(str(GRAPH), timeout=120)
    g.execute("PRAGMA busy_timeout=120000")
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
            "dameion",  # single-token hub spam; multi-word aliases still match
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

    # C6 evidence-mix: bounded sidecar text peeks (non-path evidence)
    sidecar = {"scanned": 0, "inserted": 0}
    if int(args.sidecar_text_limit) > 0:
        sidecar = add_sidecar_text_evidence(
            g, person_rows, id_map, limit=int(args.sidecar_text_limit)
        )
        g.commit()

    # C6 lock: never leave rebuild with path_match hubs above board yellow
    trimmed = []
    if not args.no_hub_cap:
        trimmed = trim_path_match_hubs(g, keep=int(args.hub_keep), above=int(args.hub_trim_above))
        g.commit()

    # stats
    total_people = g.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    total_links = g.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    evidence_mix = {
        str(a): int(b)
        for a, b in g.execute(
            "SELECT coalesce(evidence,'?'), COUNT(*) FROM links GROUP BY evidence"
        ).fetchall()
    }
    top = g.execute(
        """
        SELECT p.canonical, COUNT(*) c FROM links l
        JOIN people p ON p.id=l.person_id
        GROUP BY p.canonical ORDER BY c DESC LIMIT 15
        """
    ).fetchall()
    max_hub = int(top[0][1]) if top else 0
    g.close()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Person-file graph — {utc()}",
        "",
        f"- people: **{total_people}**",
        f"- links: **{total_links}** (new this run path matches counted loosely)",
        f"- max_hub: **{max_hub}**",
        f"- hubs_trimmed: **{len(trimmed)}** (path_match keep={args.hub_keep})",
        f"- sidecar_text: scanned **{sidecar.get('scanned')}** inserted **{sidecar.get('inserted')}**",
        f"- evidence_mix: `{json.dumps(evidence_mix)}`",
        "",
        "| Person | Files |",
        "|--------|------:|",
    ]
    for name, c in top:
        lines.append(f"| {name} | {c} |")
    LOG.write_text("\n".join(lines), encoding="utf-8")
    receipt = {
        "at": utc(),
        "people": total_people,
        "links": total_links,
        "max_hub": max_hub,
        "hubs_trimmed": trimmed,
        "hub_keep": int(args.hub_keep),
        "hub_cap_enabled": (not args.no_hub_cap),
        "sidecar_text": sidecar,
        "evidence_mix": evidence_mix,
        "top": [[a, int(b)] for a, b in top[:8]],
        "db": str(GRAPH),
        "limit_files": int(args.limit_files),
    }
    try:
        STATE_JSON.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
