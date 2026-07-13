#!/usr/bin/env python3
"""Ingestion registry — SSOT for what is already on K from external sources.

Tracks: source path, dest path, sha256, status, process flags, purge eligibility.
Prevents re-copy / re-process. Does NOT delete sources.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
K_SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\ingest-registry-latest.md")


def _connect_reg(path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path), timeout=60)
    try:
        con.execute("PRAGMA busy_timeout=60000")
        con.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return con


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = _connect_reg(DB)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS ingest (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_path TEXT,
          dest_path TEXT,
          sha256 TEXT,
          size INTEGER,
          domain TEXT,
          status TEXT,
          process_status TEXT,
          purge_eligible INTEGER DEFAULT 0,
          first_seen TEXT,
          last_seen TEXT,
          notes TEXT,
          UNIQUE(source_path, dest_path)
        );
        CREATE INDEX IF NOT EXISTS idx_ingest_source ON ingest(source_path);
        CREATE INDEX IF NOT EXISTS idx_ingest_dest ON ingest(dest_path);
        CREATE INDEX IF NOT EXISTS idx_ingest_sha ON ingest(sha256);
        CREATE TABLE IF NOT EXISTS hash_seen (
                  sha256 TEXT PRIMARY KEY,
                  first_dest TEXT,
                  count INTEGER DEFAULT 1,
                  updated TEXT
                );
        """
    )
    con.commit()
    return con


def sha256_file(path: Path, limit: int = 64 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
            if n >= limit:
                h.update(b"|TRUNC")
                break
    return h.hexdigest()


def already_ingested_source(con: sqlite3.Connection, source: str) -> dict | None:
    r = con.execute(
        "SELECT * FROM ingest WHERE source_path=? AND status IN ('copied','verified','processed') ORDER BY id DESC LIMIT 1",
        (source,),
    ).fetchone()
    return dict(r) if r else None


def already_have_hash(con: sqlite3.Connection, digest: str) -> dict | None:
    r = con.execute("SELECT * FROM hash_seen WHERE sha256=?", (digest,)).fetchone()
    return dict(r) if r else None


def register(
    con: sqlite3.Connection,
    source: str,
    dest: str,
    digest: str = "",
    size: int = 0,
    domain: str = "",
    status: str = "copied",
    process_status: str = "unprocessed",
    notes: str = "",
) -> None:
    now = utc()
    con.execute(
        """
        INSERT INTO ingest(source_path,dest_path,sha256,size,domain,status,process_status,purge_eligible,first_seen,last_seen,notes)
        VALUES(?,?,?,?,?,?,?,0,?,?,?)
        ON CONFLICT(source_path, dest_path) DO UPDATE SET
          sha256=COALESCE(NULLIF(excluded.sha256,''), ingest.sha256),
          size=CASE WHEN excluded.size>0 THEN excluded.size ELSE ingest.size END,
          status=excluded.status,
          process_status=COALESCE(NULLIF(excluded.process_status,''), ingest.process_status),
          last_seen=excluded.last_seen,
          notes=COALESCE(NULLIF(excluded.notes,''), ingest.notes)
        """,
        (source, dest, digest, size, domain, status, process_status, now, now, notes),
    )
    if digest:
        row = con.execute("SELECT count FROM hash_seen WHERE sha256=?", (digest,)).fetchone()
        if row:
            con.execute(
                "UPDATE hash_seen SET count=count+1, updated=? WHERE sha256=?",
                (now, digest),
            )
        else:
            con.execute(
                "INSERT INTO hash_seen(sha256, first_dest, count, updated) VALUES(?,?,1,?)",
                (digest, dest, now),
            )


def backfill_from_meta(con: sqlite3.Connection, root: Path = K_SILO) -> int:
    n = 0
    for meta in root.rglob("*.meta.json"):
        # skip training derivative metas and mass noise
        if meta.name.endswith(".train.meta.json"):
            continue
        sp = str(meta)
        if "from-g-drive" not in sp and "pilot" not in sp.lower() and "_PILOT" not in sp:
            # only drain/pilot provenance unless has "source_root"
            try:
                peek = meta.read_text(encoding="utf-8", errors="replace")[:200]
            except Exception:
                continue
            if "source_root" not in peek and '"source"' not in peek:
                continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            continue
        source = data.get("source") or data.get("source_path")
        dest = data.get("dest") or data.get("dest_path")
        if not source or not dest:
            # train meta has source=dest often — skip non-drain
            if "from-g-drive" not in str(meta) and "pilot" not in str(meta).lower():
                continue
            dest = str(meta).replace(".meta.json", "")
            source = data.get("source") or dest
        digest = data.get("sha256") or ""
        domain = data.get("domain") or ""
        size = int(data.get("size") or 0)
        register(
            con,
            str(source),
            str(dest),
            digest=digest,
            size=size,
            domain=str(domain),
            status="copied",
            process_status="unprocessed",
            notes="backfill_meta",
        )
        n += 1
    con.commit()
    return n


def mark_process(con: sqlite3.Connection, dest: str, process_status: str) -> None:
    con.execute(
        "UPDATE ingest SET process_status=?, last_seen=? WHERE dest_path=?",
        (process_status, utc(), dest),
    )
    con.commit()


def set_purge_eligible(con: sqlite3.Connection, source: str, eligible: bool) -> None:
    """Only marks flag — never deletes."""
    con.execute(
        "UPDATE ingest SET purge_eligible=?, last_seen=? WHERE source_path=?",
        (1 if eligible else 0, utc(), source),
    )
    con.commit()


def stats(con: sqlite3.Connection) -> dict:
    total = con.execute("SELECT COUNT(*) c FROM ingest").fetchone()["c"]
    by_st = [
        dict(r)
        for r in con.execute(
            "SELECT status, COUNT(*) c FROM ingest GROUP BY status"
        ).fetchall()
    ]
    by_pr = [
        dict(r)
        for r in con.execute(
            "SELECT process_status, COUNT(*) c FROM ingest GROUP BY process_status"
        ).fetchall()
    ]
    hashes = con.execute("SELECT COUNT(*) c FROM hash_seen").fetchone()["c"]
    multi = con.execute(
        "SELECT COUNT(*) c FROM hash_seen WHERE count>1"
    ).fetchone()["c"]
    purge = con.execute(
        "SELECT COUNT(*) c FROM ingest WHERE purge_eligible=1"
    ).fetchone()["c"]
    return {
        "total_ingest_rows": total,
        "by_status": by_st,
        "by_process": by_pr,
        "unique_hashes": hashes,
        "hashes_with_dupes": multi,
        "purge_eligible_flags": purge,
        "db": str(DB),
    }


def write_receipt(con: sqlite3.Connection) -> None:
    s = stats(con)
    lines = [
        f"# Ingest registry — {utc()}",
        "",
        f"**DB:** `{DB}`",
        f"**Rows:** {s['total_ingest_rows']}",
        f"**Unique hashes:** {s['unique_hashes']} (multi-dest hashes: {s['hashes_with_dupes']})",
        f"**Purge-eligible flags (no deletes):** {s['purge_eligible_flags']}",
        "",
        "## By status",
    ]
    for r in s["by_status"]:
        lines.append(f"- {r['status']}: {r['c']}")
    lines.append("")
    lines.append("## By process_status")
    for r in s["by_process"]:
        lines.append(f"- {r['process_status']}: {r['c']}")
    lines += [
        "",
        "Used to skip re-copy and re-process. Freeing source drives = later Class-2 purge after verify.",
        "",
        "[[Operations/Ingest-Registry-and-Reprocess-Guard-CANONICAL-2026-07-10]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("backfill")
    p.set_defaults(func=lambda a: _cmd_backfill())

    p = sub.add_parser("stats")
    p.set_defaults(func=lambda a: _cmd_stats())

    p = sub.add_parser("has-source")
    p.add_argument("path")
    p.set_defaults(func=lambda a: _cmd_has(a.path))

    p = sub.add_parser("lookup-hash")
    p.add_argument("path", help="File to hash and lookup")
    p.set_defaults(func=lambda a: _cmd_hash(a.path))

    args = ap.parse_args()
    return args.func(args)


def _cmd_backfill() -> int:
    con = connect()
    n = backfill_from_meta(con)
    write_receipt(con)
    print(json.dumps({"backfilled": n, **stats(con)}, indent=2))
    return 0


def _cmd_stats() -> int:
    con = connect()
    write_receipt(con)
    print(json.dumps(stats(con), indent=2))
    return 0


def _cmd_has(path: str) -> int:
    con = connect()
    row = already_ingested_source(con, str(Path(path)))
    print(json.dumps(row or {"ingested": False}, indent=2, default=str))
    return 0


def _cmd_hash(path: str) -> int:
    con = connect()
    p = Path(path)
    digest = sha256_file(p) if p.is_file() else ""
    row = already_have_hash(con, digest) if digest else None
    print(json.dumps({"sha256": digest, "seen": row}, indent=2, default=str))
    return 0


# re-export helpers for drain import
if __name__ != "__main__":
    pass
else:
    import json as _json  # ensure name for cmds using json

# fix main cmds to import json at module level - already have json
import json  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
