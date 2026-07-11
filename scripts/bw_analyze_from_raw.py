#!/usr/bin/env python3
"""Analyze Bitwarden `bw list items` JSON -> safe inventory + de-dupe plan.

No passwords written. Reads raw items (may contain secrets in memory only);
writes ONLY redacted outputs.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

OUT = Path(r"D:\HermesData\state\secrets-work")
REPORT = Path(r"D:\PhronesisVault\Operations\logs\bitwarden-deconflict-report-latest.md")


def host_of(uri: str) -> str:
    if not uri:
        return ""
    u = uri if "://" in uri else "https://" + uri
    try:
        h = (urlparse(u).hostname or "").lower()
    except Exception:
        return ""
    return h[4:] if h.startswith("www.") else h


def main() -> int:
    raw_path = Path(sys.argv[1] if len(sys.argv) > 1 else OUT / "bw-items-raw.json")
    if not raw_path.is_file():
        print(json.dumps({"error": "missing_raw", "path": str(raw_path)}))
        return 2

    text = raw_path.read_text(encoding="utf-8", errors="replace").strip()
    # strip noise before [
    if not text.startswith("["):
        i = text.find("[")
        if i >= 0:
            text = text[i:]
    items = json.loads(text)
    if not isinstance(items, list):
        items = [items]

    safe = []
    clusters: dict[str, list] = defaultdict(list)
    counts = {1: 0, 2: 0, 3: 0, 4: 0}

    for it in items:
        t = it.get("type")
        if t in counts:
            counts[t] += 1
        login = it.get("login") or {}
        user = (login.get("username") or "").strip().lower()
        hosts = []
        for u in login.get("uris") or []:
            uri = u.get("uri") if isinstance(u, dict) else u
            h = host_of(uri or "")
            if h:
                hosts.append(h)
        hosts = sorted(set(hosts))
        rec = {
            "id": it.get("id"),
            "name": it.get("name"),
            "type": t,
            "folderId": it.get("folderId"),
            "revisionDate": it.get("revisionDate") or "",
            "username": user,
            "hosts": hosts,
            "has_password": bool(login.get("password")),
            "has_totp": bool(login.get("totp")),
        }
        safe.append(rec)
        if t == 1:
            fp = f"{hosts[0] if hosts else ''}|{user}"
            clusters[fp].append(rec)

    dupes = []
    delete_list = []
    for fp, group in clusters.items():
        if len(group) <= 1:
            continue
        if fp == "|":
            dupes.append(
                {
                    "fingerprint": fp,
                    "count": len(group),
                    "action": "review_manual",
                    "names": "; ".join((g.get("name") or "") for g in group),
                }
            )
            continue
        group_sorted = sorted(group, key=lambda x: x.get("revisionDate") or "", reverse=True)
        keep = group_sorted[0]
        drop = group_sorted[1:]
        dupes.append(
            {
                "fingerprint": fp,
                "count": len(group),
                "keep_id": keep.get("id"),
                "keep_name": keep.get("name"),
                "keep_revision": keep.get("revisionDate"),
                "delete_ids": [d.get("id") for d in drop],
                "delete_names": "; ".join((d.get("name") or "") for d in drop),
            }
        )
        for d in drop:
            delete_list.append(
                {
                    "id": d.get("id"),
                    "name": d.get("name"),
                    "username": d.get("username"),
                    "host": fp.split("|", 1)[0],
                    "revisionDate": d.get("revisionDate"),
                    "reason": f"duplicate_of_{keep.get('id')}",
                    "fingerprint": fp,
                }
            )

    dupes.sort(key=lambda x: -x["count"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bw-items-safe.json").write_text(json.dumps(safe, indent=2), encoding="utf-8")
    (OUT / "bw-dupe-clusters.json").write_text(json.dumps(dupes, indent=2), encoding="utf-8")
    (OUT / "bw-dedupe-delete-plan.json").write_text(
        json.dumps(delete_list, indent=2), encoding="utf-8"
    )

    after = len(items) - len(delete_list)
    lines = [
        "# Bitwarden full ops report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "Mode: inventory + de-dupe DRY-RUN (no deletes)",
        "",
        f"Total items: **{len(items)}**",
        f"Logins: **{counts.get(1, 0)}**",
        f"Secure notes: **{counts.get(2, 0)}**",
        f"Cards: **{counts.get(3, 0)}**",
        f"Identities: **{counts.get(4, 0)}**",
        f"Duplicate clusters: **{len(dupes)}**",
        f"Delete candidates: **{len(delete_list)}**",
        f"After collapse ~ **{after}**",
        "",
        "## Top duplicate clusters",
        "",
        "| Count | Fingerprint | Keep | Delete sample |",
        "|------:|-------------|------|---------------|",
    ]
    for d in dupes[:40]:
        fp = (d.get("fingerprint") or "").replace("|", "/")[:40]
        kn = (d.get("keep_name") or "").replace("|", "/")[:25]
        dn = (d.get("delete_names") or "").replace("|", "/")[:35]
        lines.append(f"| {d.get('count')} | {fp} | {kn} | {dn} |")
    lines += [
        "",
        "## Files",
        f"- {OUT / 'bw-items-safe.json'}",
        f"- {OUT / 'bw-dupe-clusters.json'}",
        f"- {OUT / 'bw-dedupe-delete-plan.json'}",
        "",
        "No passwords/TOTP/note bodies in these files.",
        "Deletes NOT applied.",
        "",
    ]
    report = "\n".join(lines)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    (OUT / "bw-deconflict-report.md").write_text(report, encoding="utf-8")

    summary = "\n".join(
        [
            "BW_FULL_OPS_OK",
            f"total_items={len(items)}",
            f"logins={counts.get(1, 0)}",
            f"dupe_clusters={len(dupes)}",
            f"delete_candidates={len(delete_list)}",
            f"after_collapse={after}",
            f"generated={datetime.now(timezone.utc).isoformat()}",
        ]
    )
    (OUT / "bw-full-ops-summary.txt").write_text(summary + "\n", encoding="ascii")
    (OUT / "bw-HERMES-READY.txt").write_text(
        f"READY {datetime.now(timezone.utc).isoformat()}\nTell Hermes: bw full ops ready\n",
        encoding="ascii",
    )

    # wipe raw file if it may contain secrets
    try:
        raw_path.unlink(missing_ok=True)
    except Exception:
        pass

    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
