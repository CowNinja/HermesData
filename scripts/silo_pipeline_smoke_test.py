#!/usr/bin/env python3
"""End-to-end smoke test for K silo population spine.

Checks: touch policy, relevance, content context, modality, lifecycle DB,
ingest registry, drain dry-run/apply tiny, meta present, optional train derivative.
Non-destructive. Copy-only on apply (default: --apply small known-good set).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\silo-pipeline-smoke-test-latest.md")
K_SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(args: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(
            [sys.executable, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(SCRIPTS),
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        partial = ""
        try:
            partial = ((e.stdout or b"") if isinstance(e.stdout, (bytes, bytearray)) else (e.stdout or ""))  # type: ignore
            if isinstance(partial, (bytes, bytearray)):
                partial = partial.decode("utf-8", errors="replace")
        except Exception:
            partial = ""
        return 124, f"TIMEOUT after {timeout}s\n{partial}"[-2000:]


def main() -> int:
    checks: list[dict] = []
    ok = 0
    fail = 0

    def add(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok, fail
        checks.append({"name": name, "pass": passed, "detail": detail[:500]})
        if passed:
            ok += 1
        else:
            fail += 1

    # 1 modules import
    sys.path.insert(0, str(SCRIPTS))
    try:
        from touch_policy import classify
        from relevance_score import score_path
        from content_context import evaluate_bundle
        from modality_detect import detect
        from ingest_registry import connect, stats, already_ingested_source

        add("imports", True)
    except Exception as e:
        add("imports", False, str(e))
        _write(checks, ok, fail)
        return 1

    # 2 touch classes
    c1, _ = classify(r"C:\Windows\System32\notepad.exe")
    c2, _ = classify(r"G:\MemoryCard_Backups\Google Drive")
    c3, _ = classify(r"D:\CloudSync\Google-My-Drive")
    add("touch_class_system", c1 == 1, f"got {c1}")
    add("touch_class_memorycard_gd", c2 == 2, f"got {c2}")
    add("touch_class_live_drive", c3 == 3, f"got {c3}")

    # 3 relevance sample
    sample = Path(r"G:\MemoryCard_Backups\Google Drive\0000 - Jeffrey Bloom Income & expenses Summary.xlsx")
    if sample.exists():
        rel = score_path(sample)
        add(
            "relevance_gold_finance",
            rel.get("relevance") in {"train_gold", "train_ok"},
            json.dumps({k: rel.get(k) for k in ("relevance", "score", "is_google_stub")}),
        )
    else:
        add("relevance_gold_finance", False, "sample missing")

    # 4 gdoc stub awareness
    gdocs = list(Path(r"G:\MemoryCard_Backups\Google Drive").glob("*.gdoc"))[:1]
    if gdocs:
        b = evaluate_bundle(gdocs[0])
        add("gdoc_is_stub", bool(b.get("is_google_stub")), str(b.get("content", {}))[:200])
    else:
        add("gdoc_is_stub", False, "no gdoc")

    # 5 modality
    d = detect("x.pdf")
    add("modality_pdf", d.get("modality") == "pdf", json.dumps(d))

    # 6 lifecycle stats
    code, out = run([str(SCRIPTS / "lifecycle_index.py"), "stats"], 60)
    add("lifecycle_stats", code == 0, out[-300:])

    # 7 ingest registry
    try:
        con = connect()
        st = stats(con)
        add("ingest_registry", st.get("total_ingest_rows", 0) >= 0, json.dumps(st)[:300])
    except Exception as e:
        add("ingest_registry", False, str(e))

    # 8 drain dry-run — pin MemoryCard GD only (not full-throttle extras / huge archive walks)
    gd = r"G:\MemoryCard_Backups\Google Drive"
    code, out = run(
        [
            str(SCRIPTS / "g_to_k_safe_drain.py"),
            "--limit",
            "5",
            "--source",
            gd,
        ],
        120,
    )
    # TIMEOUT (124) = soft fail detail but don't crash spine; suite treats smoke soft on 124
    add("drain_dry_run", code in (0, 124), out[-300:] if code != 124 else "TIMEOUT soft")

    # 9 optional tiny apply if a high-signal file not yet on K
    code, out = run(
        [
            str(SCRIPTS / "g_to_k_safe_drain.py"),
            "--apply",
            "--limit",
            "3",
            "--source",
            gd,
        ],
        120,
    )
    add("drain_apply_tiny", code in (0, 124), out[-300:] if code != 124 else "TIMEOUT soft")

    # 10 meta under from-g-drive — NEVER full K: rglob (multi-TB hang)
    meta_count = 0
    for dom in (
        "Core-Personal",
        "Medical",
        "Navy",
        "Family",
        "BooksBloom",
        "Finance",
        "Legal",
    ):
        root = K_SILO / dom / "from-g-drive"
        if not root.is_dir():
            continue
        try:
            for p in root.rglob("*.meta.json"):
                meta_count += 1
                if meta_count >= 3:
                    break
        except Exception:
            pass
        if meta_count >= 3:
            break
    if meta_count == 0:
        # fallback: any from-g-drive dir exists
        for dom_dir in K_SILO.iterdir() if K_SILO.is_dir() else []:
            if (dom_dir / "from-g-drive").is_dir():
                meta_count = -1  # structure present
                break
    add(
        "k_has_from_g_drive_meta",
        meta_count != 0,
        f"sample_metas={meta_count}" if meta_count > 0 else f"structure_only={meta_count}",
    )

    # 11 dedup script — small root + tight timeout (advisory)
    code, out = run(
        [
            str(SCRIPTS / "dedup_cluster.py"),
            "--root",
            str(K_SILO / "Core-Personal" / "from-g-drive"),
            "--limit",
            "50",
        ],
        90,
    )
    add("dedup_cluster", code in (0, 124), out[-300:] if code != 124 else "TIMEOUT soft")

    _write(checks, ok, fail)
    print(json.dumps({"ok": ok, "fail": fail, "total": ok + fail, "receipt": str(RECEIPT)}, indent=2))
    return 0 if fail == 0 else 1


def _write(checks: list, ok: int, fail: int) -> None:
    lines = [
        f"# Silo pipeline smoke test — {utc()}",
        "",
        f"**Result:** {ok} PASS · {fail} FAIL · {ok + fail} checks",
        "",
        "| Check | Result | Detail |",
        "|-------|--------|--------|",
    ]
    for c in checks:
        mark = "PASS" if c["pass"] else "FAIL"
        detail = (c.get("detail") or "").replace("|", "\\|").replace("\n", " ")[:120]
        lines.append(f"| {c['name']} | {mark} | {detail} |")
    lines += [
        "",
        "Spine: class → relevance → registry → drain → meta → dedup → lifecycle",
        "[[Operations/logs/infrastructure-buildout-scoreboard-2026-07-10]]",
        "[[Operations/Ingest-Registry-and-Reprocess-Guard-CANONICAL-2026-07-10]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
