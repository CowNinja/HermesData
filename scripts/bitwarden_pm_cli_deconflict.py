#!/usr/bin/env python3
"""Deconflict Bitwarden Password Manager items via `bw` CLI (no password print).

Requires:
  - bw on PATH
  - BW_SESSION env (from: bw unlock --raw) OR --session

Never prints passwords, totp, or notes bodies.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# reuse report path
OUT_REPORT = Path(r"D:\PhronesisVault\Operations\logs\bitwarden-deconflict-report-latest.md")
OUT_JSON = Path(r"D:\HermesData\state\secrets-work\bw-cli-dupe-clusters.json")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def host_of(uri: str) -> str:
    if not uri:
        return ""
    u = uri if "://" in uri else "https://" + uri
    try:
        h = (urlparse(u).hostname or "").lower()
    except Exception:
        return ""
    return h[4:] if h.startswith("www.") else h


def bw(args: list[str], session: str) -> dict | list:
    cmd = [BW_BIN, *args, "--session", session]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "bw failed")[:500])
    return json.loads(r.stdout or "[]")


def _bw_bin() -> str | None:
    try:
        tp = json.loads(Path(r"D:/HermesData/config/tool_paths.json").read_text(encoding="utf-8"))
        b = tp.get("bw")
        if b and Path(b).is_file():
            return b
    except Exception:
        pass
    return shutil.which("bw")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=os.environ.get("BW_SESSION", ""))
    args = ap.parse_args()
    bw_bin = _bw_bin()
    if not bw_bin:
        print(json.dumps({"error": "bw_cli_not_installed", "hint": "npm i -g @bitwarden/cli"}))
        return 2
    global BW_BIN
    BW_BIN = bw_bin
    if not args.session:
        print(
            json.dumps(
                {
                    "error": "no_BW_SESSION",
                    "hint": "Run: bw login && export BW_SESSION=$(bw unlock --raw)  then re-run",
                }
            )
        )
        return 2

    items = bw(["list", "items"], args.session)
    clusters: dict[str, list] = defaultdict(list)
    for it in items:
        login = it.get("login") or {}
        if it.get("type") != 1 and not login:
            continue
        hosts = []
        for u in login.get("uris") or []:
            uri = u.get("uri") if isinstance(u, dict) else u
            h = host_of(uri or "")
            if h:
                hosts.append(h)
        host = sorted(set(hosts))[:1]
        host_s = host[0] if host else ""
        user = (login.get("username") or "").strip().lower()
        fp = f"1|{host_s}|{user}"
        clusters[fp].append(
            {
                "id": it.get("id"),
                "name": it.get("name"),
                "username": user,
                "hosts": sorted(set(hosts)),
                "revisionDate": it.get("revisionDate"),
                "has_password": bool(login.get("password")),
                "has_totp": bool(login.get("totp")),
            }
        )

    dupes = {k: v for k, v in clusters.items() if len(v) > 1}
    multi = sorted(dupes.items(), key=lambda x: -len(x[1]))
    report = {
        "at": utc(),
        "source": "bw_cli",
        "total_items": len(items),
        "duplicate_clusters": len(dupes),
        "top_clusters": [
            {
                "fingerprint": k,
                "count": len(v),
                "hosts": sorted({h for it in v for h in it.get("hosts") or []}),
                "usernames": sorted({it.get("username") or "" for it in v}),
                "ids": [it.get("id") for it in v],
                "names": [it.get("name") for it in v][:8],
                "prefer_id": max(v, key=lambda x: x.get("revisionDate") or "").get("id"),
            }
            for k, v in multi[:50]
        ],
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        f"# Bitwarden PM CLI de-conflict — {report['at']}",
        "",
        f"- Total items: **{report['total_items']}**",
        f"- Duplicate clusters: **{report['duplicate_clusters']}**",
        "",
        "| Count | Host | User | Prefer id |",
        "|------:|------|------|-----------|",
    ]
    for c in report["top_clusters"]:
        lines.append(
            f"| {c['count']} | {', '.join(c['hosts'])[:40]} | {', '.join(c['usernames'])[:30]} | `{(c.get('prefer_id') or '')[:8]}…` |"
        )
    lines += ["", "No secrets printed. Delete candidates only after Jeff OK.", ""]
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": "ok", "duplicate_clusters": report["duplicate_clusters"], "report": str(OUT_REPORT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
