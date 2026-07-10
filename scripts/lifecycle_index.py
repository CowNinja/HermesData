#!/usr/bin/env python3
"""Progressive file lifecycle index (SQLite) + status machine.

Statuses:
  untouched → inventoried → queued → copied → verified
  → purge_eligible (class 2 only) → purged
  blocked | leave_alone

AI:
  - Rules/touch_policy first (deterministic)
  - Optional local grunt for ambiguous domain labels
  - Never purge without Jeff gate
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:\HermesData\state\lifecycle_index.sqlite3")
REG = Path(r"D:\HermesData\config\touch_policy_registry.json")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\lifecycle-index-latest.md")
sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
from touch_policy import classify as touch_classify  # noqa: E402
from relevance_score import score_path  # noqa: E402

STATUSES = (
    "untouched",
    "inventoried",
    "queued",
    "copied",
    "verified",
    "purge_eligible",
    "purged",
    "blocked",
    "leave_alone",
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
          path TEXT PRIMARY KEY,
          volume TEXT,
          class INTEGER,
          class_note TEXT,
          status TEXT,
          dest_k TEXT,
          sha256 TEXT,
          size INTEGER,
          domain_guess TEXT,
          ai_labels TEXT,
          last_seen TEXT,
          updated TEXT,
          notes TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          path TEXT,
          event TEXT,
          detail TEXT,
          ts TEXT
        )
        """
    )
    con.commit()
    migrate(con)
    return con


def migrate(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(files)").fetchall()}
    for col, decl in [
        ("relevance", "TEXT"),
        ("relevance_score", "INTEGER"),
        ("silo_action", "TEXT"),
    ]:
        if col not in cols:
            con.execute(f"ALTER TABLE files ADD COLUMN {col} {decl}")
    con.commit()


def event(con: sqlite3.Connection, path: str, event: str, detail: str = "") -> None:
    con.execute(
        "INSERT INTO events(path,event,detail,ts) VALUES(?,?,?,?)",
        (path, event, detail, utc()),
    )


def upsert_inventoried(
    con: sqlite3.Connection,
    path: Path,
    cls: int,
    note: str,
    domain: str = "",
    ai_labels: str = "",
    relevance: str = "",
    relevance_score: int = 0,
    silo_action: str = "",
) -> None:
    st = "leave_alone" if cls == 1 else "inventoried"
    size = path.stat().st_size if path.is_file() else 0
    vol = path.drive.rstrip("\\") or path.parts[0] if path.parts else "?"
    con.execute(
        """
        INSERT INTO files(path,volume,class,class_note,status,size,domain_guess,ai_labels,relevance,relevance_score,silo_action,last_seen,updated,notes)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(path) DO UPDATE SET
          class=excluded.class,
          class_note=excluded.class_note,
          status=CASE
            WHEN files.status IN ('copied','verified','purge_eligible','purged','blocked') THEN files.status
            WHEN excluded.class=1 THEN 'leave_alone'
            WHEN excluded.relevance='noise' AND files.status IN ('inventoried','queued','untouched') THEN 'blocked'
            WHEN files.status='leave_alone' AND excluded.class!=1 THEN 'inventoried'
            ELSE files.status
          END,
          size=excluded.size,
          domain_guess=COALESCE(NULLIF(excluded.domain_guess,''), files.domain_guess),
          ai_labels=COALESCE(NULLIF(excluded.ai_labels,''), files.ai_labels),
          relevance=excluded.relevance,
          relevance_score=excluded.relevance_score,
          silo_action=excluded.silo_action,
          last_seen=excluded.last_seen,
          updated=excluded.updated
        """,
        (
            str(path),
            vol,
            cls,
            note,
            st if not (relevance=='noise' and cls!=1) else ('leave_alone' if cls==1 else 'blocked'),
            size,
            domain,
            ai_labels,
            relevance,
            relevance_score,
            silo_action,
            utc(),
            utc(),
            "",
        ),
    )
    event(con, str(path), "inventoried", f"class={cls} {note}")


def sha256_file(path: Path, limit: int = 32 * 1024 * 1024) -> str:
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


def local_ai_classify(name: str, timeout: int = 45) -> dict:
    """Optional local intelligence — fail soft."""
    script = Path(r"D:\HermesData\scripts\grunt_local.py")
    if not script.exists():
        return {}
    try:
        r = subprocess.run(
            [
                sys.executable,
                str(script),
                "classify",
                "--text",
                f"Classify personal archive file for life domain. Filename: {name}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (r.stdout or "").strip()
        # last json-looking line
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") and "domain" in line:
                return json.loads(line)
        return {"raw": out[:300]}
    except Exception as e:
        return {"error": str(e)}


def cmd_inventory(args: argparse.Namespace) -> int:
    con = connect()
    root = Path(args.root)
    if not root.exists():
        print(json.dumps({"error": f"missing {root}"}))
        return 1
    n = 0
    ai_n = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        rel = score_path(p, use_ai=bool(args.ai and ai_n < args.ai_limit))
        if args.ai and rel.get("ai") is not None:
            ai_n += 1
        cls = int(rel.get("class") or 2)
        note = str(rel.get("class_note") or "")
        domain = ""
        labels = json.dumps(rel.get("reasons") or [])[:500]
        if args.ai and cls == 2 and ai_n < args.ai_limit and not rel.get("ai"):
            ai = local_ai_classify(p.name)
            ai_n += 1
            if isinstance(ai, dict):
                domain = str(ai.get("domain") or "")
                labels = json.dumps(ai.get("labels") or ai)[:500]
        upsert_inventoried(
            con, p, cls, note, domain, labels,
            relevance=str(rel.get("relevance") or ""),
            relevance_score=int(rel.get("score") or 0),
            silo_action=str(rel.get("silo_action") or ""),
        )
        n += 1
        if n >= args.limit:
            break
    con.commit()
    write_receipt(con)
    print(json.dumps({"inventoried_wave": n, "ai_calls": ai_n, "db": str(DB)}, indent=2))
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    con = connect()
    paths = [
        r["path"]
        for r in con.execute(
            "SELECT path FROM files WHERE status='inventoried' AND class=2 AND IFNULL(relevance,'') != 'noise' LIMIT ?",
            (args.limit,),
        ).fetchall()
    ]
    n = 0
    for path in paths:
        con.execute(
            "UPDATE files SET status='queued', updated=? WHERE path=?",
            (utc(), path),
        )
        event(con, path, "queued", "")
        n += 1
    con.commit()
    print(json.dumps({"queued": n}, indent=2))
    write_receipt(con)
    return 0


def cmd_mark_copied(args: argparse.Namespace) -> int:
    """Mark path copied after external drain (or --path)."""
    con = connect()
    path = str(Path(args.path))
    dest = args.dest or ""
    digest = ""
    src = Path(path)
    if src.is_file():
        digest = sha256_file(src)
    con.execute(
        """
        UPDATE files SET status='copied', dest_k=?, sha256=?, updated=?
        WHERE path=?
        """,
        (dest, digest, utc(), path),
    )
    if con.total_changes == 0:
        cls, note = touch_classify(path)
        con.execute(
            """
            INSERT INTO files(path,volume,class,class_note,status,dest_k,sha256,size,last_seen,updated)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                path,
                Path(path).drive.rstrip("\\"),
                cls,
                note,
                "copied",
                dest,
                digest,
                src.stat().st_size if src.is_file() else 0,
                utc(),
                utc(),
            ),
        )
    event(con, path, "copied", dest)
    con.commit()
    print(json.dumps({"copied": path, "sha256": digest[:16]}, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    con = connect()
    rows = con.execute(
        "SELECT path, dest_k, sha256 FROM files WHERE status='copied' AND dest_k != '' AND dest_k IS NOT NULL LIMIT ?",
        (args.limit,),
    ).fetchall()
    ok = bad = 0
    for r in rows:
        src, dest, old = Path(r["path"]), Path(r["dest_k"] or ""), r["sha256"] or ""
        if not src.is_file() or not dest.is_file():
            con.execute(
                "UPDATE files SET status='blocked', notes=?, updated=? WHERE path=?",
                ("missing src or dest", utc(), r["path"]),
            )
            event(con, r["path"], "blocked", "missing file")
            bad += 1
            continue
        hs, hd = sha256_file(src), sha256_file(dest)
        if hs == hd:
            new_status = "verified"
            # class 2 may become purge_eligible only if flag
            if args.mark_purge_eligible:
                cls = con.execute(
                    "SELECT class FROM files WHERE path=?", (r["path"],)
                ).fetchone()
                if cls and cls["class"] == 2:
                    new_status = "purge_eligible"
            con.execute(
                "UPDATE files SET status=?, sha256=?, updated=? WHERE path=?",
                (new_status, hs, utc(), r["path"]),
            )
            event(con, r["path"], "verified", new_status)
            ok += 1
        else:
            con.execute(
                "UPDATE files SET status='blocked', notes=?, updated=? WHERE path=?",
                ("hash mismatch", utc(), r["path"]),
            )
            event(con, r["path"], "blocked", "hash mismatch")
            bad += 1
    con.commit()
    write_receipt(con)
    print(json.dumps({"verified_ok": ok, "blocked": bad}, indent=2))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    con = connect()
    rows = con.execute(
        "SELECT status, class, COUNT(*) c FROM files GROUP BY status, class ORDER BY class, status"
    ).fetchall()
    out = [dict(r) for r in rows]
    total = con.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    write_receipt(con)
    print(json.dumps({"total": total, "by_status_class": out, "db": str(DB)}, indent=2))
    return 0


def write_receipt(con: sqlite3.Connection) -> None:
    rows = con.execute(
        "SELECT status, class, COUNT(*) c FROM files GROUP BY status, class ORDER BY class, status"
    ).fetchall()
    total = con.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    lines = [
        f"# Lifecycle index receipt — {utc()}",
        "",
        f"**DB:** `{DB}`",
        f"**Total rows:** {total}",
        "",
        "| Class | Status | Count |",
        "|------:|--------|------:|",
    ]
    for r in rows:
        lines.append(f"| {r['class']} | {r['status']} | {r['c']} |")
    lines += [
        "",
        "Machine: untouched→inventoried→queued→copied→verified→purge_eligible→purged",
        "Class 1 leave_alone · Class 3 never purge via automation",
        "",
        "[[Operations/Three-Data-Classes-and-Touch-Policy-CANONICAL-2026-07-10]]",
        "[[Operations/Lifecycle-AI-Hybrid-Assessment-2026-07-10]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Lifecycle index")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inventory")
    p.add_argument("--root", required=True)
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--ai", action="store_true", help="Local grunt labels for class-2 sample")
    p.add_argument("--ai-limit", type=int, default=5)
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("queue")
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser("mark-copied")
    p.add_argument("--path", required=True)
    p.add_argument("--dest", default="")
    p.set_defaults(func=cmd_mark_copied)

    p = sub.add_parser("verify")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument(
        "--mark-purge-eligible",
        action="store_true",
        help="Class 2 verified → purge_eligible (still no delete)",
    )
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("stats")
    p.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
