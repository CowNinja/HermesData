#!/usr/bin/env python3
"""Rock-solid pipeline health: registry, layers, disk, recent errors.

No LLM. Exit 0 if core gates pass.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\pipeline-health-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    checks = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail[:300]})

    # disk
    for letter in ("K", "G", "D"):
        try:
            u = shutil.disk_usage(f"{letter}:/")
            free_gb = u.free / (1024**3)
            add(f"disk_{letter}_gt_20gb", free_gb > 20, f"{free_gb:.1f} GB free")
        except Exception as e:
            add(f"disk_{letter}", False, str(e))

    # registry
    if DB.exists():
        con = sqlite3.connect(str(DB))
        n = con.execute("select count(*) from ingest").fetchone()[0]
        h = con.execute("select count(distinct sha256) from hash_seen").fetchone()[0]
        add("registry_rows", n > 0, f"rows={n}")
        add("registry_hashes", h > 0, f"unique={h}")
        con.close()
    else:
        add("registry_exists", False, str(DB))

    # critical scripts
    for name in (
        "g_to_k_safe_drain.py",
        "domain_route.py",
        "relevance_score.py",
        "ingest_registry.py",
        "entity_mine.py",
        "touch_policy.py",
    ):
        add(f"script_{name}", (SCRIPTS / name).exists())

    # configs
    for name in (
        r"D:\HermesData\config\entity_context.json",
        r"D:\HermesData\config\touch_policy_registry.json",
        r"D:\HermesData\config\relevance_rules.json",
        r"D:\HermesData\config\google_account_identity.json",
    ):
        add(f"cfg_{Path(name).name}", Path(name).exists())

    # domain_route smoke
    try:
        sys.path.insert(0, str(SCRIPTS))
        from domain_route import domain_for

        d = domain_for("NAVADMIN 100.gdoc")
        add("domain_navy", d == "Navy-Service", d)
        d2 = domain_for("Dr Richardson labs.pdf")
        add("domain_richardson", "Medical" in d2, d2)
    except Exception as e:
        add("domain_route_import", False, str(e))

    # local proxy optional
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "grunt_local.py"), "health"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        ok = r.returncode == 0 and "GREEN" in ((r.stdout or "") + (r.stderr or ""))
        add("local_ai_proxy", ok, (r.stdout or "")[:200])
    except Exception as e:
        add("local_ai_proxy", False, str(e))

    failed = sum(1 for c in checks if not c["ok"])
    lines = [
        f"# Pipeline health — {utc()}",
        "",
        f"**Overall:** {'PASS' if failed == 0 else 'FAIL'} ({failed} failed / {len(checks)})",
        "",
        "| Check | Result | Detail |",
        "|-------|--------|--------|",
    ]
    for c in checks:
        lines.append(
            f"| {c['name']} | {'PASS' if c['ok'] else 'FAIL'} | {c['detail'].replace('|', '/')} |"
        )
    lines += [
        "",
        "[[Operations/AI-at-Every-Layer-Silo-Pipeline-CANONICAL-2026-07-11]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"failed": failed, "total": len(checks), "receipt": str(RECEIPT)}, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
