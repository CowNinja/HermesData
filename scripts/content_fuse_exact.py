#!/usr/bin/env python3
"""Exact-hash content fusion for the Personal Digital Silo.

Same bytes, many paths → one fused knowledge object + full member provenance.
Does NOT delete evidence. Idempotent upsert into fused_index.sqlite3.

Phase 1 of Content-Fusion-Layer-CANONICAL-2026-07-12.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
FUSED_DB = Path(r"D:\HermesData\state\fused_index.sqlite3")
FUSED_ROOT = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo\_Fused\exact")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\content-fuse-exact-latest.md")
JSON_OUT = Path(r"D:\HermesData\state\silo_fused\exact_fuse_latest.json")

EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b"

DOMAIN_RANK = {
    "Medical-Records": 100,
    "Navy-Service": 95,
    "Core-Personal/Family": 90,
    "Core-Personal/Friends": 85,
    "Core-Personal/Finance": 70,
    "Core-Personal/Projects": 65,
    "Core-Personal/Career": 60,
    "Core-Personal/Education": 55,
    "Core-Personal/Spiritual": 50,
    "Digital-Footprint": 40,
    "Life-Archive": 35,
    "Core-Personal/_Inbox": 10,
    "": 5,
}

NOISE_NAME_RE = re.compile(
    r"(?i)(jquery|colorbox|email.?sherlock|\.download$|untitled report|"
    r"css\(\d+\)|init_embed|google4\.png|min\.js)"
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def domain_score(domain: str | None) -> int:
    if not domain:
        return 0
    if domain in DOMAIN_RANK:
        return DOMAIN_RANK[domain]
    for k, v in DOMAIN_RANK.items():
        if k and domain.startswith(k):
            return v
    return 20


def train_value(sha: str, size: int, paths: list[str]) -> str:
    if sha == EMPTY_SHA or size == 0:
        return "noise"
    if size < 64:
        return "noise"
    noise_hits = sum(1 for p in paths if NOISE_NAME_RE.search(p or ""))
    if noise_hits >= max(1, len(paths) // 2):
        return "noise"
    if size < 4096 and noise_hits:
        return "weak"
    # small identical blobs with huge fanout (voice envelopes etc.)
    if len(paths) >= 50 and size < 20_000:
        return "weak"
    if any("Medical" in (p or "") or "Navy" in (p or "") for p in paths):
        return "ok"
    return "ok"


def pick_primary(rows: list[sqlite3.Row]) -> sqlite3.Row:
    def key(r: sqlite3.Row):
        path = r["dest_path"] or ""
        name = Path(path).name
        noise = 1 if NOISE_NAME_RE.search(name) or NOISE_NAME_RE.search(path) else 0
        inbox = 1 if "_Inbox" in path or (r["domain"] or "").endswith("_Inbox") else 0
        return (
            -domain_score(r["domain"]),
            noise,
            inbox,
            -(r["size"] or 0),
            -(r["id"] or 0),
        )

    return sorted(rows, key=key)[0]


def ensure_db(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS fused_exact (
            cluster_id TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            primary_path TEXT,
            primary_domain TEXT,
            member_count INTEGER,
            size INTEGER,
            train_value TEXT,
            member_paths_json TEXT,
            domains_json TEXT,
            fused_summary TEXT,
            deltas_json TEXT,
            card_path TEXT,
            updated TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_fused_exact_sha ON fused_exact(sha256);
        CREATE INDEX IF NOT EXISTS idx_fused_exact_tv ON fused_exact(train_value);
        """
    )


def load_sidecar_text(primary: Path) -> str:
    """Pull any existing extract/train text near primary (not full re-OCR)."""
    chunks: list[str] = []
    candidates = [
        primary.with_suffix(primary.suffix + ".train.md"),
        Path(str(primary) + ".train.md"),
        primary.with_suffix(primary.suffix + ".extract.json"),
        Path(str(primary) + ".extract.json"),
    ]
    # also stem.train.md
    candidates.append(primary.parent / (primary.name + ".train.md"))
    for c in candidates:
        try:
            if c.is_file() and c.stat().st_size < 2_000_000:
                text = c.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    chunks.append(f"### from `{c.name}`\n\n{text[:12000]}")
        except OSError:
            continue
    return "\n\n".join(chunks)


def build_card(
    cluster_id: str,
    sha: str,
    primary: str,
    domain: str,
    size: int,
    tv: str,
    members: list[dict],
    body: str,
) -> str:
    lines = [
        f"# Fused exact cluster `{sha[:16]}`",
        "",
        f"- **cluster_id:** `{cluster_id}`",
        f"- **sha256:** `{sha}`",
        f"- **train_value:** {tv}",
        f"- **size_bytes:** {size}",
        f"- **member_count:** {len(members)}",
        f"- **primary:** `{primary}`",
        f"- **primary_domain:** {domain}",
        f"- **updated:** {utc()}",
        "",
        "## Why fused",
        "",
        "Exact same file bytes appear under multiple paths. "
        "This card is the **single playable object**; members are evidence only. "
        "Content differential is empty (bytes identical). Path/provenance differentials listed below.",
        "",
        "## Members (evidence paths)",
        "",
    ]
    for m in members[:200]:
        role = m.get("role", "member")
        lines.append(
            f"- **{role}** · `{m.get('domain')}` · `{m.get('path')}`"
        )
    if len(members) > 200:
        lines.append(f"- … +{len(members) - 200} more")
    lines += ["", "## Content body (from primary sidecars if any)", ""]
    if body:
        lines.append(body)
    else:
        lines.append(
            "_No extract/train sidecar on primary yet. "
            "Bytes are identical across members — one future extract covers all._"
        )
    lines += [
        "",
        "## Delta",
        "",
        "- **Content:** none (exact hash).",
        "- **Provenance:** multiple paths/domains as listed; prefer primary for open/read.",
        "",
        "[[Operations/Content-Fusion-Layer-CANONICAL-2026-07-12]]",
        "",
    ]
    return "\n".join(lines)


def fuse(
    *,
    min_count: int = 2,
    limit: int = 100,
    write_cards: bool = True,
    include_noise: bool = True,
) -> dict:
    if not REG.exists():
        raise SystemExit(f"missing registry {REG}")

    reg = sqlite3.connect(str(REG))
    reg.row_factory = sqlite3.Row
    clusters = reg.execute(
        """
        SELECT sha256, count, first_dest
        FROM hash_seen
        WHERE count >= ? AND sha256 IS NOT NULL AND sha256 != ''
        ORDER BY count DESC
        LIMIT ?
        """,
        (min_count, limit),
    ).fetchall()

    FUSED_DB.parent.mkdir(parents=True, exist_ok=True)
    fdb = sqlite3.connect(str(FUSED_DB))
    ensure_db(fdb)

    results = []
    wrote = 0
    skipped_noise = 0

    for crow in clusters:
        sha = crow["sha256"]
        rows = reg.execute(
            """
            SELECT id, dest_path, source_path, domain, size, status, process_status
            FROM ingest WHERE sha256=? ORDER BY id
            """,
            (sha,),
        ).fetchall()
        if len(rows) < 2:
            # hash_seen ahead of ingest; use first_dest only
            if crow["first_dest"]:
                rows = []
            else:
                continue

        if not rows:
            continue

        primary = pick_primary(rows)
        paths = [r["dest_path"] for r in rows if r["dest_path"]]
        size = int(primary["size"] or 0)
        tv = train_value(sha, size, paths)
        if tv == "noise" and not include_noise:
            skipped_noise += 1
            continue

        members = []
        domains = set()
        for r in rows:
            role = "primary" if r["dest_path"] == primary["dest_path"] else "duplicate_path"
            members.append(
                {
                    "path": r["dest_path"],
                    "domain": r["domain"],
                    "size": r["size"],
                    "role": role,
                    "process_status": r["process_status"],
                }
            )
            if r["domain"]:
                domains.add(r["domain"])

        cluster_id = f"exact:{sha}"
        body = ""
        ppath = Path(primary["dest_path"]) if primary["dest_path"] else None
        if ppath and ppath.exists():
            body = load_sidecar_text(ppath)

        summary = (
            f"Exact-hash cluster ×{len(members)} · train_value={tv} · "
            f"primary={Path(primary['dest_path']).name if primary['dest_path'] else '?'}"
        )
        deltas = {
            "content": "none_identical_bytes",
            "provenance": {
                "unique_paths": len(set(paths)),
                "domains": sorted(domains),
                "extra_paths_beyond_primary": max(0, len(members) - 1),
            },
        }

        card_path = None
        if write_cards and tv != "noise":
            sha16 = sha[:16]
            card_dir = FUSED_ROOT / sha16
            try:
                card_dir.mkdir(parents=True, exist_ok=True)
                card_path = str(card_dir / "FUSED.md")
                Path(card_path).write_text(
                    build_card(
                        cluster_id,
                        sha,
                        primary["dest_path"],
                        primary["domain"] or "",
                        size,
                        tv,
                        members,
                        body,
                    ),
                    encoding="utf-8",
                )
                wrote += 1
            except OSError as e:
                card_path = f"WRITE_FAIL:{e}"
        elif write_cards and tv == "noise":
            # lightweight index only; optional stub card
            sha16 = sha[:16]
            card_dir = FUSED_ROOT / "_noise" / sha16
            try:
                card_dir.mkdir(parents=True, exist_ok=True)
                card_path = str(card_dir / "FUSED.md")
                Path(card_path).write_text(
                    build_card(
                        cluster_id,
                        sha,
                        primary["dest_path"],
                        primary["domain"] or "",
                        size,
                        tv,
                        members,
                        body,
                    ),
                    encoding="utf-8",
                )
                wrote += 1
            except OSError as e:
                card_path = f"WRITE_FAIL:{e}"

        fdb.execute(
            """
            INSERT INTO fused_exact(
                cluster_id, sha256, primary_path, primary_domain, member_count,
                size, train_value, member_paths_json, domains_json, fused_summary,
                deltas_json, card_path, updated
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(cluster_id) DO UPDATE SET
                primary_path=excluded.primary_path,
                primary_domain=excluded.primary_domain,
                member_count=excluded.member_count,
                size=excluded.size,
                train_value=excluded.train_value,
                member_paths_json=excluded.member_paths_json,
                domains_json=excluded.domains_json,
                fused_summary=excluded.fused_summary,
                deltas_json=excluded.deltas_json,
                card_path=excluded.card_path,
                updated=excluded.updated
            """,
            (
                cluster_id,
                sha,
                primary["dest_path"],
                primary["domain"],
                len(members),
                size,
                tv,
                json.dumps(members, ensure_ascii=False),
                json.dumps(sorted(domains)),
                summary,
                json.dumps(deltas),
                card_path,
                utc(),
            ),
        )
        results.append(
            {
                "cluster_id": cluster_id,
                "sha16": sha[:16],
                "member_count": len(members),
                "size": size,
                "train_value": tv,
                "primary": primary["dest_path"],
                "card_path": card_path,
            }
        )

    fdb.commit()
    total_fused = fdb.execute("SELECT COUNT(*) FROM fused_exact").fetchone()[0]
    by_tv = dict(
        fdb.execute(
            "SELECT train_value, COUNT(*) FROM fused_exact GROUP BY train_value"
        ).fetchall()
    )
    fdb.close()
    reg.close()

    out = {
        "ts": utc(),
        "phase": "exact_hash",
        "clusters_processed": len(results),
        "cards_written": wrote,
        "skipped_noise_filter": skipped_noise,
        "fused_index_total": total_fused,
        "by_train_value": by_tv,
        "sample": results[:15],
        "fused_db": str(FUSED_DB),
        "fused_root": str(FUSED_ROOT),
    }

    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")

    lines = [
        f"# Content fuse exact — {out['ts']}",
        "",
        f"**Clusters processed:** {out['clusters_processed']}",
        f"**Cards written:** {out['cards_written']}",
        f"**Fused index total:** {out['fused_index_total']}",
        f"**By train_value:** {out['by_train_value']}",
        "",
        "## Sample",
        "",
    ]
    for s in out["sample"]:
        lines.append(
            f"- ×{s['member_count']} · {s['train_value']} · `{s['sha16']}` · "
            f"`{Path(s['primary']).name if s['primary'] else '?'}`"
        )
    lines += [
        "",
        "No evidence deleted. Exact-hash content delta is empty; provenance merged.",
        "",
        "[[Operations/Content-Fusion-Layer-CANONICAL-2026-07-12]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    out["receipt"] = str(RECEIPT)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Exact-hash content fusion (Phase 1)")
    ap.add_argument("--min-count", type=int, default=2)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--no-cards", action="store_true")
    ap.add_argument("--skip-noise-cards", action="store_true", help="Still index noise; skip MD cards for noise")
    args = ap.parse_args()
    # include_noise always indexes; write_cards controls MD
    result = fuse(
        min_count=args.min_count,
        limit=args.limit,
        write_cards=not args.no_cards,
        include_noise=True,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
