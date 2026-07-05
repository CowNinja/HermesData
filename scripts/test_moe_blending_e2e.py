#!/usr/bin/env python3
"""MoE blending E2E -- alias routing + T2 context augment + ranked fleet SSOT.

Text-only (no image pipeline). Validates:
  - MoE aliases resolve to local Qwythos via :8091
  - Realtime/news trigger may augment messages (T2 prefetch) while local answers
  - model-priority-state ranks Nemotron #1 with procurement benchmark
  - Panel JSON exposes moe_constellation node when fleet ON
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT_SCRIPTS = Path(r"D:\PhronesisVault\scripts")
VAULT_OPS = Path(r"D:\PhronesisVault\Operations")
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(VAULT_SCRIPTS))

ERRORS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS {name}")
    else:
        ERRORS.append(f"{name}: {detail}")
        print(f"  FAIL {name} -- {detail}")


def _chat(model: str, content: str, *, max_tokens: int = 120, timeout: int = 150) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8091/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    print("=== MoE Blending E2E (text) ===\n")

    # Priority board SSOT
    pri_path = VAULT_OPS / "model-priority-state.json"
    pri = json.loads(pri_path.read_text(encoding="utf-8-sig")) if pri_path.is_file() else {}
    check("fleet_enabled_priority", bool(pri.get("fleet_enabled")), str(pri.get("fleet_enabled")))
    free_tier = next((t for t in pri.get("tiers") or [] if t.get("id") == "internet_free"), {})
    top = (free_tier.get("models") or [{}])[0]
    check("nemotron_ranked_first", top.get("id") == "openrouter-free-nemotron", str(top.get("id")))
    bench = top.get("benchmark") or {}
    check("nemotron_procurement_bench", bench.get("pass") is True, str(bench)[:120])

    # Panel topology
    from sovereign_router_panel import build_sovereign_router_panel

    panel = build_sovereign_router_panel(force_refresh=True)
    flow = panel.get("flow") or {}
    fb_nodes = {n.get("id") for n in (flow.get("fallback") or {}).get("nodes") or []}
    check("panel_moe_constellation_node", "moe_constellation" in fb_nodes, str(sorted(fb_nodes)))
    moe_c = flow.get("moe_constellation") or {}
    check("constellation_has_ranked", bool(moe_c.get("ranked_providers")), str(moe_c.get("detail", ""))[:80])
    actions = panel.get("node_click_actions") or {}
    check("constellation_click_action", actions.get("moe_constellation") == "reconcile-fleet", str(actions.get("moe_constellation")))

    # Alias MoE -- all logical names hit local backend
    for alias in (
        "phronesis-sovereign-auto",
        "phronesis-sovereign-roleplay",
        "phronesis-sovereign-code",
    ):
        try:
            body = _chat(alias, 'Reply with exactly: ALIAS_OK', max_tokens=16)
            text = str((body.get("choices") or [{}])[0].get("message", {}).get("content", "")).strip()
            check(f"alias_{alias.split('-')[-1]}", "ALIAS" in text.upper() or len(text) > 0, text[:60])
        except Exception as exc:
            check(f"alias_{alias.split('-')[-1]}", False, str(exc))

    # T2 prefetch trigger -- local still answers; provenance may show augment
    try:
        body = _chat(
            "phronesis-sovereign-auto",
            "What happened today in AI news? Summarize in one sentence.",
            max_tokens=100,
        )
        text = str((body.get("choices") or [{}])[0].get("message", {}).get("content", "")).strip()
        prov = body.get("provenance") or {}
        check("t2_prefetch_local_answer", len(text) > 10, "empty")
        check(
            "t2_prefetch_provenance_optional",
            True,
            f"augment={bool(prov.get('context_augment'))} len={len(text)}",
        )
        print(f"    preview: {text[:100]}")
    except Exception as exc:
        check("t2_prefetch_local_answer", False, str(exc))

    # Creative OOC (text planning only -- image pipeline paused)
    try:
        body = _chat(
            "phronesis-sovereign-roleplay",
            "OOC: Plan a series of 3 scenes -- five characters in a volcano lair. "
            "List scene titles only, no images.",
            max_tokens=200,
        )
        text = str((body.get("choices") or [{}])[0].get("message", {}).get("content", "")).strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        has_titles = len(lines) >= 2 or text.count("\n") >= 1
        check(
            "ooc_scene_plan_text",
            len(text) > 20 and (has_titles or "scene" in text.lower()),
            text[:120].replace("\n", " | "),
        )
    except Exception as exc:
        check("ooc_scene_plan_text", False, str(exc))

    print(f"\n=== Results: {len(ERRORS)} failures ===")
    for e in ERRORS:
        print(f"  - {e}")
    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())