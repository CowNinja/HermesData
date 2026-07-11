#!/usr/bin/env python3
"""Context detective: origin path + siblings + content hints -> tags + train notes.

Codifies the workflow used on William Wilhelm genealogy / multi-signal classify:
  1) source relative path + parent folders
  2) sibling filenames in same directory
  3) light content peek (text-like files)
  4) entity hits
  5) write .context.json + optional .context.train.md next to file on K
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
from domain_route import domain_for  # noqa: E402

try:
    from entity_resolve import resolve_person  # noqa: E402
except Exception:
    def resolve_person(s: str):  # type: ignore
        return None

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
ENTITY = Path(r"D:\HermesData\config\entity_context.json")
TEXT_EXT = {".txt", ".md", ".csv", ".log", ".bak", ".rtf", ".json", ".xml", ".html", ".htm"}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_entity_tokens() -> list[tuple[str, str, str]]:
    """Return list of (token, domain, kind)."""
    if not ENTITY.is_file():
        return []
    data = json.loads(ENTITY.read_text(encoding="utf-8"))
    out = []
    for pe in data.get("people") or []:
        dom = pe.get("domain") or ""
        for n in pe.get("names") or []:
            if n and len(n) >= 5:
                out.append((n.lower(), dom, "person"))
    for org in data.get("orgs") or []:
        dom = org.get("domain") or ""
        for n in org.get("names") or []:
            if n and len(n) >= 5:
                out.append((n.lower(), dom, "org"))
    out.sort(key=lambda x: -len(x[0]))
    return out


def parent_chain(path: Path, root: Path) -> list[str]:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return list(rel.parts[:-1])


def siblings(path: Path, limit: int = 40) -> list[str]:
    parent = path.parent
    if not parent.is_dir():
        return []
    names = []
    try:
        for p in parent.iterdir():
            if p.is_file() and p.name != path.name:
                names.append(p.name)
            if len(names) >= limit:
                break
    except OSError:
        pass
    return names


def peek_text(path: Path, max_chars: int = 4000) -> str:
    if path.suffix.lower() not in TEXT_EXT and not path.name.endswith(".bak"):
        # allow .bak text
        if ".bak" not in path.name.lower():
            return ""
    try:
        raw = path.read_bytes()[: max_chars * 2]
        return raw.decode("utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def keyword_tags(blob: str) -> list[str]:
    b = blob.lower()
    tags = []
    checks = [
        ("genealogy", r"gedmatch|descendant|family tree|line of descent"),
        ("medical", r"lab|labs|prescription|diagnosis|va rating|pharmacy|adrenal|tbi|healthevet|healthvault|clinvar|mirtazapine|medical"),
        ("navy", r"navy|navpers|dd-?214|fitrep|navadmin"),
        ("gaming", r"albion|guild|miststanding|warz|lewz|clickmate|nomads of the mist"),
        ("education", r"transcript|homeschool|lego league|fll|ecpi|course"),
        ("finance", r"paypal|transaction_download|mortgage|receipt|bank statement"),
        ("home_automation", r"hubitat|landroid|iotawatt|skynet"),
    ]
    for tag, patt in checks:
        if re.search(patt, b, re.I):
            tags.append(tag)
    if "medical" in tags and "finance" in tags:
        tags = [x for x in tags if x != "finance"]
    return tags



def enrich_one(path: Path, write: bool = True) -> dict:
    # find silo-relative domain shelf
    try:
        rel = path.relative_to(SILO)
        shelf = rel.parts[0]
        if shelf == "Core-Personal" and len(rel.parts) > 1:
            shelf = f"Core-Personal/{rel.parts[1]}"
    except ValueError:
        rel = Path(path.name)
        shelf = "unknown"

    parents = parent_chain(path, SILO if SILO in path.parents or path.is_relative_to(SILO) else path.parent)
    sibs = siblings(path)
    text = peek_text(path)
    blob = " ".join(
        [
            path.name,
            " ".join(parents),
            " ".join(sibs[:20]),
            text[:2000],
        ]
    )
    dom_guess = domain_for(path.name, str(path))
    tags = keyword_tags(blob)
    # entity hits
    hits = []
    low = blob.lower()
    for token, dom, kind in load_entity_tokens()[:500]:
        if token in low:
            hits.append({"token": token, "domain": dom, "kind": kind})
            if len(hits) >= 12:
                break
    # person resolve on name-like
    for m in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b", path.name + " " + text[:500]):
        r = resolve_person(m)
        if r:
            hits.append({"token": m, "resolve": r, "kind": "resolved_person"})

    # gdoc stub detect
    is_gdoc_stub = path.suffix.lower() == ".gdoc" and path.stat().st_size < 500 if path.is_file() else False

    ctx = {
        "file": str(path),
        "relative": str(rel).replace("\\", "/"),
        "shelf": shelf,
        "parents": parents,
        "siblings_sample": sibs[:25],
        "domain_route": dom_guess,
        "tags": sorted(set(tags)),
        "entity_hits": hits[:15],
        "content_peek_chars": len(text),
        "is_gdoc_stub": is_gdoc_stub,
        "needs_export": is_gdoc_stub,
        "enriched_at": utc(),
        "method": "path+siblings+peek+entity",
    }

    # training surface
    train_lines = [
        f"# Context package: {path.name}",
        "",
        f"- Shelf: {shelf}",
        f"- Domain route: {dom_guess}",
        f"- Tags: {', '.join(ctx['tags']) or 'none'}",
        f"- Parents: {' / '.join(parents)}",
        f"- Siblings (sample): {', '.join(sibs[:12])}",
        f"- Entity hits: {json.dumps(hits[:8], ensure_ascii=True)}",
        f"- gdoc_stub: {is_gdoc_stub}",
        "",
        "## Content peek",
        "",
        "```",
        (text[:1500] if text else "(no text peek)"),
        "```",
        "",
    ]

    if write:
        ctx_path = Path(str(path) + ".context.json")
        train_path = Path(str(path) + ".context.train.md")
        ctx_path.write_text(json.dumps(ctx, indent=2), encoding="utf-8")
        train_path.write_text("\n".join(train_lines), encoding="utf-8")
        ctx["wrote"] = [str(ctx_path), str(train_path)]
    return ctx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="Files to enrich")
    ap.add_argument("--glob", default="", help="Glob under silo e.g. **/William*")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    targets: list[Path] = []
    for p in args.paths:
        targets.append(Path(p))
    if args.glob:
        targets.extend(list(SILO.glob(args.glob))[: args.limit * 3])

    # default demo: wilhelm + a few medical
    if not targets:
        targets = list(SILO.rglob("*Wilhelm*"))[:5]
        targets += list(SILO.rglob("*Mirtazapine*"))[:3]
        targets += list(SILO.rglob("*Albion*"))[:3]
        targets += list(SILO.rglob("*GHW*"))[:3]

    # files only
    files = []
    for t in targets:
        if t.is_file() and not t.name.endswith(
            (".context.json", ".context.train.md", ".meta.json", ".train.md")
        ):
            files.append(t)
        if len(files) >= args.limit:
            break

    results = []
    for f in files[: args.limit]:
        try:
            results.append(enrich_one(f, write=not args.dry_run))
        except Exception as e:
            results.append({"file": str(f), "error": str(e)[:200]})

    print(
        json.dumps(
            {
                "enriched": len([r for r in results if "error" not in r]),
                "errors": len([r for r in results if "error" in r]),
                "sample": results[:5],
            },
            indent=2,
        )[:4000]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
