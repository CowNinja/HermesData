#!/usr/bin/env python3
"""Process Core-Personal/_Inbox with ORIGIN-AWARE multi-signal classify.

Contextual awareness (Jeff mandate):
  - originating G: source path from .meta.json
  - parent folders on G: (and K under Inbox)
  - sibling filenames on G: when still online
  - file body/OCR peek when real
  - entity lexicon
  - capped Qwythos grunt

Signals order:
  entity+origin → name_rule → origin_path/siblings → k_path → content → grunt → stay

Default dry-run. --apply moves on K only (never touches G:).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
from domain_route import domain_for  # noqa: E402

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
INBOX = SILO / "Core-Personal" / "_Inbox"
ENTITY = Path(r"D:\HermesData\config\entity_context.json")
DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
LOG = Path(r"D:\PhronesisVault\Operations\logs\inbox-process-latest.md")
TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def load_entities() -> List[Dict[str, Any]]:
    if not ENTITY.is_file():
        return []
    d = json.loads(ENTITY.read_text(encoding="utf-8"))
    return list(d.get("people") or []) + list(d.get("orgs") or [])


def entity_domain(blob: str, entities: List[Dict[str, Any]]) -> Optional[str]:
    low = blob.lower()
    best = None
    best_len = 0
    for pe in entities:
        cands = [str(pe.get("canonical") or "")] + list(pe.get("aliases") or [])
        for a in cands:
            a = (a or "").strip()
            if len(a) < 4:
                continue
            if a.lower() in low and len(a) > best_len:
                dom = pe.get("domain")
                if dom and "Inbox" not in str(dom):
                    best = str(dom)
                    if best == "Life-Archive":
                        best = "Core-Personal/Life-Archive"
                    best_len = len(a)
    return best


def peek_text(path: Path, limit: int = 2500) -> str:
    try:
        if path.suffix.lower() in {
            ".txt",
            ".md",
            ".csv",
            ".log",
            ".json",
            ".xml",
            ".html",
            ".htm",
        }:
            return path.read_text(encoding="utf-8", errors="replace")[:limit]
        meta = Path(str(path) + ".meta.json")
        if meta.is_file():
            return meta.read_text(encoding="utf-8", errors="replace")[:limit]
        if path.suffix.lower() in {".gdoc", ".gsheet", ".gslides"}:
            return path.read_text(encoding="utf-8", errors="replace")[:800]
    except Exception:
        pass
    return ""


def load_meta(path: Path) -> Dict[str, Any]:
    cand = Path(str(path) + ".meta.json")
    if cand.is_file():
        try:
            return json.loads(cand.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return {}
    return {}


def origin_context(path: Path, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Originating G: path + parents + siblings (if source still on disk)."""
    source = str(meta.get("source") or meta.get("source_path") or "")
    source_root = str(meta.get("source_root") or "")
    parents: List[str] = []
    sibs: List[str] = []
    if source:
        src_p = Path(source)
        try:
            if source_root:
                try:
                    rel = src_p.relative_to(Path(source_root))
                    parents = list(rel.parts[:-1])
                except Exception:
                    parents = list(src_p.parts[-8:-1])
            else:
                parents = list(src_p.parts[-8:-1])
        except Exception:
            parents = []
        try:
            if src_p.parent.is_dir():
                for i, sib in enumerate(src_p.parent.iterdir()):
                    if i >= 30:
                        break
                    if sib.name != src_p.name:
                        sibs.append(sib.name)
        except Exception:
            pass
    # K Inbox relative parents
    try:
        rel_k = path.relative_to(INBOX)
        parents = list(rel_k.parts[:-1]) + parents
    except Exception:
        pass
    return {
        "source": source,
        "source_root": source_root,
        "origin_parents": parents,
        "origin_siblings": sibs[:25],
    }


def grunt_domain(text: str) -> Optional[str]:
    try:
        r = subprocess.run(
            [
                sys.executable,
                str(Path(r"D:\HermesData\scripts\grunt_local.py")),
                "classify",
                "--text",
                text[:1500],
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        out = (r.stdout or "").strip()
        if not out.startswith("{"):
            return None
        obj = json.loads(out)
        blob = json.dumps(obj).lower()
        for key, dom in [
            ("medical", "Medical-Records"),
            ("navy", "Navy-Service"),
            ("finance", "Core-Personal/Finance"),
            ("family", "Core-Personal/Family"),
            ("education", "Core-Personal/Education"),
            ("career", "Core-Personal/Career"),
            ("project", "Core-Personal/Projects"),
            ("gym", "Core-Personal/Life-Archive"),
            ("fitness", "Core-Personal/Life-Archive"),
            ("spiritual", "Core-Personal/Spiritual"),
        ]:
            if key in blob:
                return dom
        return None
    except Exception:
        return None


def classify_file(
    path: Path, entities: List[Dict[str, Any]], use_grunt: bool
) -> Tuple[str, str, Dict[str, Any]]:
    name = path.name
    meta = load_meta(path)
    octx = origin_context(path, meta)
    parents = octx.get("origin_parents") or []
    sibs = octx.get("origin_siblings") or []
    # compound dossier from state (neighborhood intelligence)
    dossier_blob = ""
    try:
        src = octx.get("source") or ""
        if src:
            parent = str(Path(src).parent)
            key = hashlib.sha256(parent.lower().encode("utf-8")).hexdigest()[:16]
            dp = Path(r"D:/HermesData/state/folder_dossiers") / f"{key}.json"
            if dp.is_file():
                import json as _json
                dd = _json.loads(dp.read_text(encoding="utf-8"))
                dossier_blob = " ".join(dd.get("siblings_sample") or []) + " " + " ".join(dd.get("entity_hits") or [])
                octx["dossier_key"] = key
                octx["dossier_entities"] = dd.get("entity_hits")
    except Exception:
        pass
    origin_blob = " ".join(parents) + " " + " ".join(sibs[:15]) + " " + dossier_blob

    # 0 bulk origin-folder rules (same SSOT as inbox_bulk_origin_rehome)
    try:
        rules_path = Path(r"D:\HermesData\config\inbox_origin_rules.json")
        if rules_path.is_file():
            low = str(path).replace("/", "\\").lower()
            for rule in json.loads(rules_path.read_text(encoding="utf-8")).get("rules") or []:
                if (rule.get("confidence") or "").lower() == "defer" or not rule.get("domain"):
                    continue
                for sub in rule.get("match_any_path_substr") or []:
                    if sub.lower().replace("/", "\\") in low:
                        rid = rule.get("id")
                        return str(rule["domain"]), "origin_rule:" + str(rid), octx
    except Exception:
        pass
    ed = entity_domain(name + " " + origin_blob, entities)
    if ed:
        return ed, "entity+origin", octx
    d = domain_for(name)
    if d and "Inbox" not in d:
        return d, "name_rule", octx
    if origin_blob.strip():
        d2 = domain_for(origin_blob + " " + name)
        if d2 and "Inbox" not in d2:
            return d2, "origin_path", octx
    try:
        rel = path.relative_to(INBOX)
        joined = " ".join(rel.parts[:-1]) + " " + name
        d3 = domain_for(joined)
        if d3 and "Inbox" not in d3:
            return d3, "k_path_rule", octx
    except Exception:
        pass
    body = peek_text(path)
    if body:
        d4 = domain_for(body[:500] + " " + name + " " + origin_blob[:400])
        if d4 and "Inbox" not in d4:
            return d4, "content_rule", octx
        if use_grunt:
            gd = grunt_domain(name + " ORIGIN " + str(parents) + " " + str(sibs[:12]) + " " + body[:500])
            if gd:
                return gd, "grunt+origin", octx
    elif use_grunt:
        gd = grunt_domain(name + " ORIGIN " + str(parents) + " " + str(sibs[:12]))
        if gd:
            return gd, "grunt_name+origin", octx
    return "Core-Personal/_Inbox", "stay", octx


def iter_inbox_files(limit: int) -> List[Path]:
    out: List[Path] = []
    if not INBOX.is_dir():
        return out
    for p in INBOX.rglob("*"):
        if not p.is_file():
            continue
        if p.name.endswith(
            (".meta.json", ".train.md", ".context.json", ".ocr.md", ".context.train.md")
        ):
            continue
        if p.name.startswith("00-INDEX"):
            continue
        out.append(p)
        if len(out) >= limit * 5:
            break
    return out[: limit * 5]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--grunt-cap", type=int, default=15)
    ap.add_argument("--no-grunt", action="store_true")
    args = ap.parse_args()

    entities = load_entities()
    files = iter_inbox_files(args.limit)
    grunt_used = 0
    moves: List[Dict[str, Any]] = []
    stats: Counter = Counter()

    for p in files:
        use_g = (not args.no_grunt) and grunt_used < args.grunt_cap
        dom, why, octx = classify_file(p, entities, use_grunt=use_g)
        if "grunt" in why:
            grunt_used += 1
        stats[why] += 1
        if "Inbox" in dom:
            continue
        # Preserve nested origin tree (anti-flat) — never flatten into _rehome-inbox
        try:
            rel = p.relative_to(INBOX / "from-g-drive")
        except Exception:
            try:
                rel = p.relative_to(INBOX)
            except Exception:
                rel = Path(p.name)
        dest = SILO / dom / "from-g-drive" / rel
        if dest.exists():
            digest = __import__("hashlib").sha256(str(p).encode()).hexdigest()[:8]
            dest = dest.with_name(f"{dest.stem}__{digest}{dest.suffix}")
        moves.append(
            {
                "src": str(p),
                "dest": str(dest),
                "domain": dom,
                "why": why,
                "source": octx.get("source"),
                "origin_parents": octx.get("origin_parents"),
                "origin_siblings": (octx.get("origin_siblings") or [])[:12],
            }
        )
        if len(moves) >= args.limit:
            break

    applied = 0
    if args.apply:
        for m in moves:
            src, dest = Path(m["src"]), Path(m["dest"])
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                ctx = {
                    "rehomed_from_inbox": True,
                    "why": m.get("why"),
                    "domain": m.get("domain"),
                    "source": m.get("source"),
                    "origin_parents": m.get("origin_parents"),
                    "origin_siblings": m.get("origin_siblings"),
                    "enriched_at": datetime.now(timezone.utc).isoformat(),
                    "method": "inbox_process_origin_aware",
                }
                Path(str(dest) + ".context.json").write_text(
                    json.dumps(ctx, indent=2), encoding="utf-8"
                )
                for suf in (
                    ".meta.json",
                    ".train.md",
                    ".context.json",
                    ".ocr.md",
                    ".context.train.md",
                ):
                    cand = Path(str(src) + suf)
                    if cand.is_file() and suf != ".context.json":
                        shutil.move(str(cand), str(dest) + suf)
                try:
                    con = sqlite3.connect(str(DB))
                    con.execute(
                        "UPDATE ingest SET domain=?, dest_path=?, last_seen=? WHERE dest_path=? OR source_path LIKE ?",
                        (
                            m["domain"],
                            str(dest),
                            datetime.now(timezone.utc).isoformat(),
                            str(src),
                            f"%{src.name}",
                        ),
                    )
                    con.commit()
                    con.close()
                except Exception:
                    pass
                applied += 1
            except Exception as e:
                m["error"] = str(e)

    LOG.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Inbox process (origin-aware) — {TS}",
        "",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'} · planned **{len(moves)}** · applied **{applied}** · grunt **{grunt_used}**",
        f"**Signals:** {dict(stats)}",
        "",
        "| Why | Domain | Origin parents | File |",
        "|-----|--------|----------------|------|",
    ]
    for m in moves[:50]:
        op = " / ".join((m.get("origin_parents") or [])[-4:])
        lines.append(
            f"| {m['why']} | {m['domain']} | `{op[:50]}` | `{Path(m['src']).name[:55]}` |"
        )
    LOG.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "apply": args.apply,
                "planned_rehome": len(moves),
                "applied": applied,
                "grunt_used": grunt_used,
                "signals": dict(stats),
                "receipt": str(LOG),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
