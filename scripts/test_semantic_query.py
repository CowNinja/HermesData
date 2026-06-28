#!/usr/bin/env python3
"""Milestone 1 validation — hierarchical chunking, sqlite-vec, 8090 tier routing."""
from __future__ import annotations

import hashlib
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
    """Keyword-overlap pseudo-embedding for offline ANN tests."""
    vals = [0.0] * dim
    for word in text.lower().split():
        digest = hashlib.md5(word.encode("utf-8")).digest()
        for i in range(8):
            idx = (digest[i] + i * 31) % dim
            vals[idx] += 1.0
    norm = sum(v * v for v in vals) ** 0.5 or 1.0
    return [v / norm for v in vals]


def test_hierarchical_chunker() -> None:
    print("\n--- Hierarchical Chunker ---")
    from hierarchical_chunker import HierarchicalChunker, estimate_tokens

    sample = (
        "# Sovereign Semantic Index\n\n"
        + "Hierarchical chunking preserves parent-child context for retrieval. " * 40
        + "\n\n## Architecture\n\n"
        + "SQLite-vec stores paragraph and section embeddings locally. " * 30
        + "\n\n## Routing\n\n"
        + "The 8090 LRU router selects Llama or Qwen tiers by query complexity. " * 25
    )
    chunker = HierarchicalChunker(parent_max_tokens=200, child_max_tokens=80, overlap_tokens=10)
    nodes = chunker.chunk_text(sample, source_path="test://semantic-doc")
    levels = {n.level for n in nodes}
    check("chunk_levels", {"document", "section", "paragraph"}.issubset(levels), str(levels))
    check("chunk_count", len(nodes) >= 5, f"got {len(nodes)}")
    parents = {n.parent_id for n in nodes if n.level == "paragraph"}
    section_ids = {n.chunk_id for n in nodes if n.level == "section"}
    check("parent_child_graph", parents.issubset(section_ids | {nodes[0].chunk_id}), "orphan paragraphs")
    check("token_estimate", estimate_tokens(sample) > 100)


def test_vector_store_roundtrip() -> None:
    print("\n--- SQLite-Vec Store ---")
    from sovereign_vector_store import SovereignVectorStore

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test-semantic.sqlite"
        store = SovereignVectorStore(db, embed_fn=lambda t: _mock_embed(t))
        try:
            _vector_store_checks(store)
        finally:
            store.close()


def _vector_store_checks(store) -> None:
    doc_a = (
        "# Fleet Procurement\n\n"
        "The opportunistic fleet discovers free API providers and benchmarks them. "
        * 8
    )
    doc_b = (
        "# Telemetry Monitor\n\n"
        "Sovereign telemetry tracks TTFT drift and auto-tunes governor limits. "
        * 8
    )
    r1 = store.index_document(doc_a, source_path="vault://fleet")
    r2 = store.index_document(doc_b, source_path="vault://telemetry")
    check("index_inserted", r1.get("inserted", 0) > 0 and r2.get("inserted", 0) > 0)
    check("index_embedded", r1.get("embedded", 0) > 0 and r2.get("embedded", 0) > 0)

    stats = store.stats()
    check("stats_vectors", stats.get("vectors", 0) > 0, str(stats))

    fleet_hits = store.search("opportunistic fleet procurement sandbox", k=3)
    check("search_fleet", len(fleet_hits) > 0, "no hits")
    if fleet_hits:
        check(
            "search_fleet_relevance",
            "fleet" in fleet_hits[0].text.lower() or "procurement" in fleet_hits[0].text.lower(),
            fleet_hits[0].text[:80],
        )
        check("parent_context", fleet_hits[0].parent_text is not None or fleet_hits[0].level == "section")

    tel_hits = store.search("TTFT drift governor telemetry", k=3)
    check("search_telemetry", len(tel_hits) > 0)
    if tel_hits and fleet_hits:
        check(
            "search_discrimination",
            fleet_hits[0].chunk_id != tel_hits[0].chunk_id or fleet_hits[0].source_path != tel_hits[0].source_path,
            "same top hit for different queries",
        )


def test_semantic_engine_routing() -> None:
    print("\n--- Semantic Engine + 8090 Router ---")
    from semantic_query_engine import SovereignSemanticEngine

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "route-test.sqlite"
        engine = SovereignSemanticEngine(
            db_path=db,
            embed_fn=lambda t: _mock_embed(t),
            enable_rerank=False,
        )
        try:
            _semantic_engine_checks(engine)
        finally:
            engine.store.close()


def _semantic_engine_checks(engine) -> None:
    from router_bridge import preview_route

    engine.index_text(
        "Growth blueprint synthesis requires deep cross-document reasoning across architecture notes.",
        source_path="vault://synthesis",
    )
    engine.index_text("Simple lookup: what port does the unified router use?", source_path="vault://lookup")

    simple_route = engine.resolve_retrieval_route("what port is the router on")
    check("simple_route_tier", "tier" in simple_route, str(simple_route))
    check("simple_route_port", simple_route.get("port") in (8090, 8081, 8082, 8083, None))

    complex_route = engine.resolve_retrieval_route(
        "Provide a growth blueprint synthesis across " + ("multiple architecture documents " * 60),
        context_tokens=5000,
    )
    check("complex_route_context", complex_route.get("context_tokens_estimate", 0) >= 5000)
    preview = preview_route(task_type="synthesis", prompt="growth blueprint distill synthesis")
    check("preview_route_synthesis", preview.get("task_type") == "synthesis" or preview.get("tier") is not None)

    cold = engine.retrieve(
        "growth blueprint synthesis architecture",
        k=3,
        escalation_tier="local_cold",
    )
    check("cold_tier_k", cold.k_requested >= 3, str(cold.k_requested))
    check("cold_tier_label", cold.tier == "local_cold")

    hot = engine.retrieve(
        "router port lookup",
        k=5,
        escalation_tier="local_hot",
    )
    check("hot_tier_k", hot.k_requested <= 5, str(hot.k_requested))


def test_sovereign_router_hook() -> None:
    print("\n--- Sovereign Router Retrieved Band ---")
    vault_scripts = Path(r"D:\PhronesisVault\scripts")
    if not vault_scripts.is_dir():
        check("vault_scripts", False, "PhronesisVault scripts missing")
        return
    sys.path.insert(0, str(vault_scripts))
    import sovereign_router as sr  # noqa: E402

    sr._SEMANTIC_ENGINE = None
    sr._SEMANTIC_ENGINE_TRIED = False

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "router-semantic.sqlite"
        from semantic_query_engine import SovereignSemanticEngine

        engine = SovereignSemanticEngine(db_path=db, embed_fn=lambda t: _mock_embed(t), enable_rerank=False)
        try:
            engine.index_text(
                "SQLite-vec semantic index enables local retrieval without cloud APIs.",
                source_path="vault://semantic-index",
            )
            sr._SEMANTIC_ENGINE = engine
            sr._SEMANTIC_ENGINE_TRIED = True

            os.environ["TIERED_CONTEXT_BYPASS_DEV"] = "1"
            router = sr.SovereignRouter()
            meta = router.assemble_tiers(
                session=[{"role": "user", "content": "How does sqlite-vec semantic retrieval work?"}],
                context_percent=80.0,
                family_user=None,
                task="sqlite-vec semantic retrieval local index",
                defer_headroom=True,
            )
            retrieved = meta.get("bands_dict", {}).get("retrieved", [])
            check("retrieve_mode", meta.get("mode") == "retrieve", meta.get("mode"))
            check("semantic_in_retrieved", any("semantic:" in r for r in retrieved), str(retrieved)[:200])
        finally:
            engine.store.close()
            sr._SEMANTIC_ENGINE = None
            sr._SEMANTIC_ENGINE_TRIED = False


def main() -> int:
    print("=== Milestone 1: Semantic Query Engine Validation ===")
    test_hierarchical_chunker()
    test_vector_store_roundtrip()
    test_semantic_engine_routing()
    test_sovereign_router_hook()

    print(f"\n=== Results: {len(ERRORS)} failures ===")
    if ERRORS:
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    print("ALL PASS — Milestone 1 semantic query optimization GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
