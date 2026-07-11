#!/usr/bin/env python3
"""Apply Bitwarden de-dupe: keep newest, merge URIs into keep, delete extras.

Requires BW_SESSION env (unlocked).
NEVER prints passwords.

Industry pattern: base64-encode item JSON (same as `bw encode`), then
`bw edit item <id>` with encoded payload; `bw delete item <id>` for clones.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

OUT = Path(r"D:\HermesData\state\secrets-work")
LOG = OUT / "bw-dedupe-apply-log.txt"

# Prefer node entrypoint (reliable on Windows vs .cmd stdin)
BW_JS = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@bitwarden" / "cli" / "build" / "bw.js"
NODE = "node"


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="ascii", errors="replace") as f:
        f.write(line + "\n")
    print(line, flush=True)


def host_of(uri: str) -> str:
    if not uri:
        return ""
    u = uri if "://" in uri else "https://" + uri
    try:
        h = (urlparse(u).hostname or "").lower()
    except Exception:
        return ""
    return h[4:] if h.startswith("www.") else h


def bw_run(args: list[str], session: str, stdin: str | None = None, timeout: int = 180) -> tuple[int, str, str]:
    if not BW_JS.is_file():
        return 127, "", f"missing bw.js at {BW_JS}"
    cmd = [NODE, str(BW_JS), *args, "--session", session]
    try:
        r = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)[:200]


def bw_json(args: list[str], session: str) -> dict | list | None:
    code, out, err = bw_run(args, session)
    if code != 0:
        log(f"bw_fail args={args[:4]} code={code} err={err[:200]}")
        return None
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # sometimes warnings prefix json
        i = out.find("{")
        j = out.find("[")
        start = -1
        if i >= 0 and j >= 0:
            start = min(i, j)
        elif i >= 0:
            start = i
        elif j >= 0:
            start = j
        if start >= 0:
            try:
                return json.loads(out[start:])
            except json.JSONDecodeError:
                pass
        log(f"bw_json_parse_fail args={args[:4]} out={out[:120]}")
        return None


def encode_item(item: dict) -> str:
    """Same as `bw encode` — base64 of JSON."""
    raw = json.dumps(item, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def main() -> int:
    dry = "--apply" not in sys.argv
    session = os.environ.get("BW_SESSION", "").strip()
    if not session:
        sp = OUT / "bw-session.txt"
        if sp.is_file():
            session = sp.read_text(encoding="ascii", errors="replace").strip()
    if not session:
        log("ERROR no BW_SESSION")
        return 2

    st = bw_json(["status"], session)
    if not st or st.get("status") != "unlocked":
        log(f"ERROR not unlocked status={st}")
        return 3

    log(f"mode={'DRY_RUN' if dry else 'APPLY'}")
    log(f"bw_js={BW_JS}")
    log("listing items...")
    items = bw_json(["list", "items"], session)
    if not isinstance(items, list):
        log("ERROR list items failed")
        return 4

    log(f"total_items={len(items)}")

    clusters: dict[str, list] = defaultdict(list)
    for it in items:
        if it.get("type") != 1:
            continue
        login = it.get("login") or {}
        user = (login.get("username") or "").strip().lower()
        hosts = []
        for u in login.get("uris") or []:
            uri = u.get("uri") if isinstance(u, dict) else u
            h = host_of(uri or "")
            if h:
                hosts.append(h)
        hosts = sorted(set(hosts))
        fp = f"{hosts[0] if hosts else ''}|{user}"
        if fp == "|":
            continue
        clusters[fp].append(it)

    multi = {k: v for k, v in clusters.items() if len(v) > 1}
    log(f"dupe_clusters={len(multi)}")

    merged = 0
    deleted = 0
    errors = 0
    plan = []
    t0 = time.time()

    for idx, (fp, group) in enumerate(sorted(multi.items(), key=lambda x: -len(x[1]))):
        group_sorted = sorted(group, key=lambda x: x.get("revisionDate") or "", reverse=True)
        keep = group_sorted[0]
        drop = group_sorted[1:]

        uri_map: dict[str, dict] = {}
        for it in group_sorted:
            login = it.get("login") or {}
            for u in login.get("uris") or []:
                if isinstance(u, dict):
                    uri = u.get("uri") or ""
                    if uri and uri not in uri_map:
                        entry = {"uri": uri}
                        if u.get("match") is not None:
                            entry["match"] = u.get("match")
                        uri_map[uri] = entry
                elif isinstance(u, str) and u and u not in uri_map:
                    uri_map[u] = {"uri": u}

        keep_login = keep.get("login") or {}
        password = keep_login.get("password") or ""
        totp = keep_login.get("totp") or ""
        username = keep_login.get("username") or ""
        if not password:
            for it in group_sorted[1:]:
                p = (it.get("login") or {}).get("password") or ""
                if p:
                    password = p
                    break
        if not totp:
            for it in group_sorted:
                t = (it.get("login") or {}).get("totp") or ""
                if t:
                    totp = t
                    break

        name = keep.get("name") or ""
        for it in group_sorted:
            n = it.get("name") or ""
            if n and not n.lower().startswith("http"):
                name = n
                break

        clean_uris = list(uri_map.values())
        plan.append(
            {
                "fingerprint": fp,
                "keep_id": keep.get("id"),
                "keep_name": name,
                "delete_ids": [d.get("id") for d in drop],
                "uri_count": len(clean_uris),
                "delete_count": len(drop),
            }
        )

        if dry:
            continue

        # progress every cluster start
        if idx % 10 == 0:
            log(
                f"progress {idx}/{len(multi)} merged={merged} deleted={deleted} "
                f"errors={errors} elapsed_s={int(time.time() - t0)}"
            )

        keep_full = bw_json(["get", "item", keep["id"]], session)
        if not keep_full:
            log(f"ERR get keep={str(keep.get('id'))[:8]}")
            errors += 1
            continue

        keep_full["name"] = name
        if not keep_full.get("login"):
            keep_full["login"] = {}
        keep_full["login"]["username"] = username
        keep_full["login"]["password"] = password
        if totp:
            keep_full["login"]["totp"] = totp
        keep_full["login"]["uris"] = clean_uris

        encoded = encode_item(keep_full)
        code_ed, out_ed, err_ed = bw_run(
            ["edit", "item", keep["id"]], session, stdin=encoded, timeout=120
        )
        if code_ed != 0:
            log(f"ERR edit keep={str(keep.get('id'))[:8]} code={code_ed} err={err_ed[:150]}")
            errors += 1
            continue
        merged += 1

        for d in drop:
            did = d.get("id")
            code_d, out_d, err_d = bw_run(["delete", "item", did], session, timeout=60)
            if code_d != 0:
                log(f"ERR delete {str(did)[:8]} err={err_d[:100]}")
                errors += 1
            else:
                deleted += 1

    (OUT / "bw-dedupe-apply-plan.json").write_text(
        json.dumps(plan[:5000], indent=2), encoding="utf-8"
    )
    log(f"clusters_planned={len(plan)}")
    log(f"merged={merged} deleted={deleted} errors={errors}")
    log(f"mode_end={'DRY_RUN' if dry else 'APPLY'}")

    summary = {
        "mode": "DRY_RUN" if dry else "APPLY",
        "total_items_before": len(items),
        "dupe_clusters": len(multi),
        "merged": merged,
        "deleted": deleted,
        "errors": errors,
        "would_delete": sum(p["delete_count"] for p in plan) if dry else deleted,
        "elapsed_s": int(time.time() - t0),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    (OUT / "bw-dedupe-apply-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
