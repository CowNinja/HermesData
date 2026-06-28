#!/usr/bin/env python3
"""Milestone 2 validation — high-signal feed → sqlite-vec pipeline."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

ERRORS: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS {name}")
    else:
        ERRORS.append(f"{name}: {detail}")
        print(f"  FAIL {name} — {detail}")


def _mock_embed(text: str, dim: int = 768):
    vals = [0.0] * dim
    for word in text.lower().split():
        digest = hashlib.md5(word.encode("utf-8")).digest()
        for i in range(8):
            idx = (digest[i] + i * 31) % dim
            vals[idx] += 1.0
    norm = sum(v * v for v in vals) ** 0.5 or 1.0
    return [v / norm for v in vals]


def test_html_extractor() -> None:
    print("\n--- HTML Extractor ---")
    from high_signal_ingestion_pipeline import html_to_text

    html = "<html><head><style>body{}</style></head><body><h1>Title</h1><p>Fleet procurement sandbox.</p></body></html>"
    text = html_to_text(html)
    check("strip_tags", "Fleet procurement" in text and "<" not in text)
    check("min_length", len(text) > 10)


def test_pipeline_dedup_and_index() -> None:
    print("\n--- Pipeline Index + Dedup ---")
    from high_signal_ingestion_pipeline import HighSignalIngestionPipeline
    from semantic_query_engine import SovereignSemanticEngine

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "ingest-test.sqlite"
        engine = SovereignSemanticEngine(db_path=db, embed_fn=lambda t: _mock_embed(t), enable_rerank=False)
        pipeline = HighSignalIngestionPipeline(engine=engine)
        target = {"id": "test-target", "category": "test", "probe": {"url": "https://example.com/feed"}}

        sample = "# High Signal Feed\n\nUniversal ingestion pushes web feeds into sqlite-vec automatically. " * 5
        r1 = pipeline.index_text_if_new(sample, source_path="feed://test-target/https://example.com/feed", target_id="test-target")
        check("first_index", r1.get("status") == "indexed", str(r1))
        r2 = pipeline.index_text_if_new(sample, source_path="feed://test-target/https://example.com/feed", target_id="test-target")
        check("dedup_skip", r2.get("status") == "skipped_duplicate", str(r2))

        src = Path(tmp) / "vault-source.md"
        src.write_text("# Vault Doc\n\nSovereign semantic index receives distilled vault sources.\n" * 4, encoding="utf-8")
        target["distill"] = {"context_prefix": "Source: test vault."}
        r3 = pipeline.index_source_file(src, target=target, trigger="distill_success")
        check("source_index", r3.get("status") == "indexed", str(r3))

        hits = engine.retrieve("universal ingestion sqlite-vec", k=3)
        check("search_hits", len(hits.hits) > 0, str(len(hits.hits)))
        engine.store.close()


def test_monitor_vector_hook() -> None:
    print("\n--- Universal Monitor Vector Hook ---")
    canonical = Path(r"D:\HermesData\.hermes\scripts\universal_ingest_monitor.py")
    check("canonical_exists", canonical.is_file())
    text = canonical.read_text(encoding="utf-8")
    check("vector_hook_fn", "_index_to_vector_store" in text)
    check("no_new_feed_refresh", 'event="no_new"' in text)
    check("distill_vector_hook", "vector_reports = _index_to_vector_store" in text)


def test_registry_vector_config() -> None:
    print("\n--- Ingestion Registry ---")
    reg = Path(r"D:\PhronesisVault\Operations\ingestion_targets.yaml")
    check("registry_exists", reg.is_file())
    try:
        import yaml

        data = yaml.safe_load(reg.read_text(encoding="utf-8"))
        vec = (data.get("monitor") or {}).get("vector_index") or {}
        check("vector_enabled", vec.get("enabled") is True)
        check("vector_index_on", "feed_probe" in (vec.get("index_on") or []))
        check("targets_count", len(data.get("targets") or []) >= 2)
    except Exception as exc:
        check("registry_parse", False, str(exc))


def test_monitor_dry_run() -> None:
    print("\n--- Monitor Dry Run ---")
    canonical = Path(r"D:\HermesData\.hermes\scripts\universal_ingest_monitor.py")
    if not canonical.is_file():
        check("dry_run", False, "monitor missing")
        return
    import subprocess

    env = {**os.environ, "INGESTION_TARGETS": r"D:\PhronesisVault\Operations\ingestion_targets.yaml"}
    proc = subprocess.run(
        [sys.executable, str(canonical), "--dry-run", "--json"],
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
        cwd=str(SCRIPTS.parent),
    )
    check("dry_run_exit", proc.returncode in (0, 1), proc.stderr[:300])
    marker = '{"timestamp"'
    idx = proc.stdout.rfind(marker)
    if idx >= 0:
        try:
            summary = json.loads(proc.stdout[idx:])
            check("dry_run_json", "results" in summary)
            check("dry_run_preflight", summary.get("preflight") in ("GREEN", "YELLOW", "RED", "skipped"))
            check("dry_run_targets", len(summary.get("results") or []) >= 1)
        except json.JSONDecodeError:
            check("dry_run_json", False, proc.stdout[-400:])
    else:
        check("dry_run_output", "Summary" in proc.stdout or "status=" in proc.stdout, proc.stdout[:200])


def main() -> int:
    print("=== Milestone 2: Universal Ingestion Automation Validation ===")
    test_html_extractor()
    test_pipeline_dedup_and_index()
    test_monitor_vector_hook()
    test_registry_vector_config()
    test_monitor_dry_run()

    print(f"\n=== Results: {len(ERRORS)} failures ===")
    if ERRORS:
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    print("ALL PASS — Milestone 2 universal ingestion automation GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
