#!/usr/bin/env python3
"""Bitwarden export de-conflict: find Chrome/Edge import duplicates.

NEVER prints passwords, TOTP, cards, notes bodies, or security answers.
Input: Bitwarden unencrypted export JSON (items[]).
Output: cluster report + merge plan (hosts, usernames, counts only).
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_EXPORT = Path(r"D:\HermesData\state\secrets-work\bw-export.json")
OUT_CLUSTERS = Path(r"D:\HermesData\state\secrets-work\bw-dupe-clusters.json")
OUT_REPORT = Path(r"D:\PhronesisVault\Operations\logs\bitwarden-deconflict-report-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def host_of(uri: str) -> str:
    if not uri:
        return ""
    u = uri.strip()
    if "://" not in u:
        u = "https://" + u
    try:
        h = urlparse(u).hostname or ""
    except Exception:
        h = ""
    h = h.lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def username_norm(s: str | None) -> str:
    return (s or "").strip().lower()


def item_fingerprint(item: dict) -> str:
    login = item.get("login") or {}
    uris = login.get("uris") or []
    hosts = []
    for u in uris:
        if isinstance(u, dict):
            hosts.append(host_of(u.get("uri") or ""))
        elif isinstance(u, str):
            hosts.append(host_of(u))
    host = sorted([h for h in hosts if h])[:1]
    host_s = host[0] if host else ""
    user = username_norm(login.get("username"))
    itype = item.get("type", 1)
    return f"{itype}|{host_s}|{user}"


def safe_item_summary(item: dict) -> dict:
    login = item.get("login") or {}
    uris = []
    for u in login.get("uris") or []:
        uri = u.get("uri") if isinstance(u, dict) else u
        h = host_of(uri or "")
        if h:
            uris.append(h)
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "username": username_norm(login.get("username")),
        "hosts": sorted(set(uris)),
        "folderId": item.get("folderId"),
        "revisionDate": item.get("revisionDate"),
        "has_password": bool(login.get("password")),
        "has_totp": bool(login.get("totp")),
        # NEVER include password/totp/notes
    }


def analyze(export_path: Path) -> dict:
    data = json.loads(export_path.read_text(encoding="utf-8"))
    items = data.get("items") or data.get("Items") or []
    if not items and isinstance(data, list):
        items = data
    clusters: dict[str, list] = defaultdict(list)
    type_counts = defaultdict(int)
    for it in items:
        if not isinstance(it, dict):
            continue
        type_counts[str(it.get("type"))] += 1
        # type 1 = login in BW
        if it.get("type") not in (1, "1", None) and it.get("login") is None:
            continue
        if it.get("login") is None and it.get("type") != 1:
            continue
        fp = item_fingerprint(it)
        clusters[fp].append(safe_item_summary(it))

    dupe_clusters = {k: v for k, v in clusters.items() if len(v) > 1 and not k.endswith("||")}
    # empty user+host noise
    multi = sorted(dupe_clusters.items(), key=lambda x: -len(x[1]))

    report = {
        "at": utc(),
        "export": str(export_path),
        "total_items": len(items),
        "login_fingerprints": len(clusters),
        "duplicate_clusters": len(dupe_clusters),
        "type_counts": dict(type_counts),
        "top_clusters": [
            {
                "fingerprint": k,
                "count": len(v),
                "hosts": sorted({h for it in v for h in (it.get("hosts") or [])}),
                "usernames": sorted({it.get("username") or "" for it in v}),
                "names": [it.get("name") for it in v][:8],
                "prefer_revision": max((it.get("revisionDate") or "" for it in v), default=""),
            }
            for k, v in multi[:50]
        ],
    }
    return report


def write_report(report: dict) -> None:
    OUT_CLUSTERS.parent.mkdir(parents=True, exist_ok=True)
    OUT_CLUSTERS.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        f"# Bitwarden de-conflict report — {report.get('at')}",
        "",
        "**No secrets in this report** (hosts/usernames/names/counts only).",
        "",
        f"- Export: `{report.get('export')}`",
        f"- Total items: **{report.get('total_items')}**",
        f"- Login fingerprints: **{report.get('login_fingerprints')}**",
        f"- **Duplicate clusters: {report.get('duplicate_clusters')}**",
        f"- Types: `{report.get('type_counts')}`",
        "",
        "## Top duplicate clusters (Chrome/Edge import residue)",
        "",
        "| Count | Host(s) | Username | Item names (sample) | Prefer rev |",
        "|------:|---------|----------|---------------------|------------|",
    ]
    for c in report.get("top_clusters") or []:
        hosts = ", ".join(c.get("hosts") or [])[:40]
        users = ", ".join(c.get("usernames") or [])[:40]
        names = "; ".join((c.get("names") or [])[:3])[:50]
        lines.append(
            f"| {c.get('count')} | {hosts} | {users} | {names} | {(c.get('prefer_revision') or '')[:10]} |"
        )
    lines += [
        "",
        "## Merge plan (human + optional bw CLI later)",
        "",
        "1. For each cluster count≥2: keep newest `revisionDate` as canonical",
        "2. Confirm password still works (Jeff-gated test)",
        "3. Archive/delete older dupes in Bitwarden UI or `bw delete`",
        "4. Re-export and re-run this script until duplicate_clusters near 0",
        "",
        "## Safety",
        "",
        "- Export file lives only under `D:/HermesData/state/secrets-work/` (gitignored)",
        "- Never paste export into Discord/chat",
        "",
    ]
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", default=str(DEFAULT_EXPORT))
    args = ap.parse_args()
    path = Path(args.export)
    if not path.is_file():
        # scaffold secrets-work + instructions
        path.parent.mkdir(parents=True, exist_ok=True)
        gitignore = path.parent / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")
        readme = path.parent / "README.md"
        readme.write_text(
            """# secrets-work (LOCAL ONLY)

1. In Bitwarden: File → Export vault → **.json** (unencrypted) — use carefully
2. Save as `bw-export.json` in this folder
3. Run: `python D:/HermesData/scripts/bitwarden_deconflict.py`
4. Read report in PhronesisVault Operations/logs/bitwarden-deconflict-report-latest.md
5. Delete export when done

NEVER commit this folder. Machine secrets stay in Bitwarden Secrets Manager (bws).
""",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": "awaiting_export",
                    "place_export_at": str(path),
                    "instructions": str(readme),
                },
                indent=2,
            )
        )
        return 2
    report = analyze(path)
    write_report(report)
    print(
        json.dumps(
            {
                "status": "ok",
                "duplicate_clusters": report["duplicate_clusters"],
                "total_items": report["total_items"],
                "report": str(OUT_REPORT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
