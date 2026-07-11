#!/usr/bin/env python3
"""Preflight before MemoryCard GD ingestion trial."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\memorycard-trial-preflight-latest.md")
K = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
G1 = Path(r"G:\MemoryCard_Backups\Google Drive")
G2 = Path(r"G:\MemoryCard_Backups\Google Drive(archive)")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def free_gb(path: Path) -> float:
    u = shutil.disk_usage(path)
    return u.free / (1024**3)


def run(args: list[str], timeout: int = 300) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, timeout=timeout
    )
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-800:]


def main() -> int:
    checks = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail[:400]})

    add("G_primary_exists", G1.is_dir(), str(G1))
    add("G_archive_exists", G2.is_dir(), str(G2))
    add("K_silo_exists", K.is_dir(), str(K))
    kf = free_gb(Path("K:/"))
    gf = free_gb(Path("G:/"))
    add("K_free_gt_50GB", kf > 50, f"{kf:.1f} GB")
    add("G_readable", gf >= 0, f"{gf:.1f} GB free")

    code, out = run([str(SCRIPTS / "silo_pipeline_smoke_test.py")], 400)
    add("smoke_test", code == 0, out)

    code, out = run([str(SCRIPTS / "g_to_k_safe_drain.py"), "--limit", "10"], 180)
    add("drain_dry_run", code == 0, out)

    code, out = run([str(SCRIPTS / "ingest_registry.py"), "stats"], 60)
    add("ingest_registry_stats", code == 0, out)

    failed = sum(1 for c in checks if not c["ok"])
    lines = [
        f"# MemoryCard trial preflight — {utc()}",
        "",
        f"**Overall:** {'PASS' if failed == 0 else 'FAIL'} ({failed} failed)",
        "",
        "| Check | Result | Detail |",
        "|-------|--------|--------|",
    ]
    for c in checks:
        lines.append(
            f"| {c['name']} | {'PASS' if c['ok'] else 'FAIL'} | {c['detail'].replace('|', '/').replace(chr(10), ' ')[:100]} |"
        )
    lines += [
        "",
        "Next: census · domain audit · `run memorycard trial` when ready",
        "[[Operations/G-MemoryCard-Ingestion-Trial-Five-Actions-2026-07-10]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"failed": failed, "checks": len(checks), "receipt": str(RECEIPT)}, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
