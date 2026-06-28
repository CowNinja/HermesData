#!/usr/bin/env python3
"""
E2E diagnostic — Discord ingest → proxy roleplay routing.

Simulates raw Discord user text through discord_roleplay_connector and
sovereign_openai_proxy.resolve_roleplay_routing. Logs match the live trace
file at D:\\PhronesisVault\\Operations\\logs\\discord-proxy-ingest-trace.jsonl

Usage:
    python D:\\HermesData\\scripts\\test_discord_roleplay_routing.py
    python D:\\HermesData\\scripts\\test_discord_roleplay_routing.py --live-proxy
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

ERRORS: list[str] = []
TRACE_LOG = Path(r"D:\PhronesisVault\Operations\logs\discord-proxy-ingest-trace.jsonl")

ALICE_CHANNEL = "1519509288286949466"
ALICE_THREAD = "1519512763863666810"


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS {name}")
    else:
        ERRORS.append(f"{name}: {detail}")
        print(f"  FAIL {name} — {detail}")


def _port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def simulate_discord_to_proxy(
    raw_text: str,
    *,
    chat_name: str = "",
    channel_id: str = "",
    parent_channel_id: str = "",
    thread_id: str = "",
    label: str = "",
) -> dict:
    from discord_roleplay_connector import (
        log_discord_ingest_trace,
        normalize_discord_inbound_text,
    )
    from sovereign_openai_proxy import resolve_roleplay_routing

    normalized, meta = normalize_discord_inbound_text(
        raw_text,
        chat_name=chat_name,
        channel_id=channel_id,
        parent_channel_id=parent_channel_id,
        thread_id=thread_id,
    )
    if meta.get("force_roleplay_model") and meta.get("resolved_platform"):
        plat = str(meta["resolved_platform"])
        if plat == "alice-roleplay" and "[platform:" not in normalized.lower():
            normalized = f"[platform: {plat}]\n{normalized}".strip()
            meta["injected_platform_tag"] = plat

    log_discord_ingest_trace(
        stage="test_discord_e2e",
        raw_text=raw_text,
        normalized_text=normalized,
        meta=meta,
        extra={"label": label or raw_text[:40]},
    )

    messages = [
        {"role": "system", "content": f"channel: {chat_name or channel_id}"},
        {"role": "user", "content": normalized},
    ]
    routing = resolve_roleplay_routing(messages, "phronesis-sovereign-auto", {})
    trace = {
        "label": label,
        "raw_text": raw_text,
        "normalized_text": normalized,
        "meta": meta,
        "routing_model": routing.get("model"),
        "routing_platform": routing.get("platform"),
        "force_roleplay": routing.get("force_roleplay"),
        "reasons": routing.get("reasons"),
    }
    print(json.dumps(trace, indent=2, ensure_ascii=False))
    return trace


def run_connector_cases() -> None:
    print("\n--- Discord Connector → Proxy Routing ---")
    cases = [
        {
            "label": "slash_roleplay_with_prompt",
            "raw": "/roleplay The party enters the dim tavern",
            "chat_name": "Phronesis / #general",
        },
        {
            "label": "slash_rp_bare",
            "raw": "/rp",
            "chat_name": "Phronesis / #general",
        },
        {
            "label": "colon_trigger",
            "raw": "ROLEPLAY_MODE: Describe the throne room",
            "chat_name": "Phronesis / #general",
        },
        {
            "label": "uncensored_colon",
            "raw": "UNCENSORED_ROLEPLAY: Combat round — roll initiative",
            "chat_name": "Phronesis / #general",
        },
        {
            "label": "platform_tag_inline",
            "raw": "[platform: alice-roleplay] Continue the campaign",
            "chat_name": "Phronesis / #misc",
        },
        {
            "label": "alice_roleplay_channel_id",
            "raw": "The rogue picks the lock",
            "channel_id": ALICE_CHANNEL,
            "chat_name": "Phronesis / #alice-roleplay",
        },
        {
            "label": "alice_roleplay_thread_id",
            "raw": "What do I see in the corridor?",
            "channel_id": ALICE_THREAD,
            "parent_channel_id": ALICE_CHANNEL,
            "thread_id": ALICE_THREAD,
            "chat_name": "Phronesis / #alice-roleplay / session-1",
        },
        {
            "label": "plain_chat_no_signal",
            "raw": "Summarize the Q3 growth blueprint",
            "chat_name": "Phronesis / #planning",
        },
        {
            "label": "skill_evolution_discusses_roleplay",
            "raw": (
                "Please verify Hermes is up to date with the latest patches. "
                "The roleplay routing bug is still returning SYSTEM BLOCK."
            ),
            "chat_name": "Phronesis / #skill-evolution",
            "thread_id": "1520237581848285436",
        },
    ]
    for case in cases:
        trace = simulate_discord_to_proxy(
            case["raw"],
            chat_name=case.get("chat_name", ""),
            channel_id=case.get("channel_id", ""),
            parent_channel_id=case.get("parent_channel_id", ""),
            thread_id=case.get("thread_id", ""),
            label=case["label"],
        )
        expect_rp = case["label"] not in (
            "plain_chat_no_signal",
            "skill_evolution_discusses_roleplay",
        )
        got_rp = (
            trace.get("routing_model") == "phronesis-sovereign-roleplay"
            and bool(trace.get("force_roleplay"))
        )
        check(
            f"{case['label']}_routing",
            got_rp == expect_rp,
            str(trace),
        )


def test_ollama_roleplay_block() -> None:
    print("\n--- Ollama Fallback Block (roleplay isolation) ---")
    import importlib.util

    ollama_path = SCRIPTS / "sovereign_router.py"
    spec = importlib.util.spec_from_file_location("hermes_ollama_router", ollama_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    ollama_dispatch = mod.dispatch

    res = ollama_dispatch("ROLEPLAY_MODE: Describe the scene", task_type="roleplay")
    check("ollama_blocks_roleplay_task_type", not res.get("success"), str(res))
    check("ollama_block_message", "SYSTEM BLOCK" in str(res.get("response") or ""), str(res.get("response")))


def test_bridge_roleplay_isolation() -> None:
    print("\n--- Bridge Strict Tier Isolation ---")
    from router_bridge import bridge_dispatch

    res = bridge_dispatch(
        "ROLEPLAY_MODE: The party enters the tavern",
        task_type="roleplay",
        platform="alice-roleplay",
        prefer="vault",
    )
    backend = str((res.get("provenance") or {}).get("selected_backend") or "")
    check("no_ollama_backend", backend != "ollama", backend)
    ok_path = (
        (res.get("success") and str(res.get("tier")) == "local_roleplay")
        or res.get("roleplay_blocked")
        or "SYSTEM BLOCK" in str(res.get("response") or "")
    )
    check("roleplay_vault_or_block", ok_path, str(res)[:300])


def test_vram_pin_policy() -> None:
    print("\n--- VRAM Pin Policy ---")
    from lru_router_manager import (
        get_pinned_logical_models,
        load_pin_config,
        recommended_ctx_size,
        recommended_models_max,
        vram_pin_telemetry,
    )

    cfg = load_pin_config()
    pinned = get_pinned_logical_models()
    check("pin_config_loaded", bool(pinned), str(cfg.get("pinned_logical_models")))
    check("rocinante_pinned", "rocinante-12b" in pinned, str(pinned))
    check("qwen7b_pinned", "qwen2-5-7b" in pinned, str(pinned))
    check("models_max_floor", recommended_models_max() >= len(pinned), str(recommended_models_max()))
    check("ctx_size_12gb", recommended_ctx_size() == 12288, str(recommended_ctx_size()))
    tel = vram_pin_telemetry()
    check("telemetry_has_pins", "pinned_logical_models" in tel, str(list(tel.keys())[:8]))


def test_system_prompt_severance() -> None:
    print("\n--- System Prompt Severance ---")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hermes-agent"))
    from types import SimpleNamespace

    from agent.chat_completion_helpers import (
        _is_hermes_corporate_system,
        probe_phronesis_roleplay,
        resolve_roleplay_clean_system_prompt,
        sever_hermes_system_prompt,
    )
    from agent.prompt_builder import DEFAULT_AGENT_IDENTITY

    hermes_system = DEFAULT_AGENT_IDENTITY + "\n\nTool guidance here."
    check(
        "hermes_marker_detected",
        _is_hermes_corporate_system(hermes_system),
        "DEFAULT_AGENT_IDENTITY not flagged",
    )

    clean = resolve_roleplay_clean_system_prompt()
    check(
        "clean_prompt_no_hermes",
        not _is_hermes_corporate_system(clean),
        clean[:120],
    )

    api_messages = [
        {"role": "system", "content": hermes_system},
        {"role": "user", "content": "ROLEPLAY_MODE: The torch flickers in the crypt"},
    ]
    agent = SimpleNamespace(
        model="phronesis-sovereign-auto",
        request_overrides={},
        session_id="test-severance",
        base_url="http://127.0.0.1:8091/v1",
        provider="openai",
    )
    probe = probe_phronesis_roleplay(agent, api_messages)
    check("roleplay_probe_active", probe.get("active"), str(probe))

    severed = sever_hermes_system_prompt(agent, api_messages)
    check("severance_applied", severed, "sever_hermes_system_prompt returned False")
    sys_msgs = [m for m in api_messages if m.get("role") == "system"]
    check("single_system_message", len(sys_msgs) == 1, f"count={len(sys_msgs)}")
    sys_text = str(sys_msgs[0].get("content") or "")
    check(
        "payload_hermes_free",
        not _is_hermes_corporate_system(sys_text),
        sys_text[:200],
    )
    check(
        "payload_has_immersion_rules",
        "in character" in sys_text.lower() or "uncensored" in sys_text.lower(),
        sys_text[:200],
    )


def run_live_proxy_probe() -> None:
    print("\n--- Live Proxy Probe (8091) ---")
    if not _port_open("127.0.0.1", 8091):
        print("  SKIP live proxy — port 8091 not reachable")
        return

    import urllib.request

    payload = {
        "model": "phronesis-sovereign-auto",
        "messages": [
            {"role": "system", "content": "channel: Phronesis / #alice-roleplay"},
            {"role": "user", "content": "ROLEPLAY_MODE: A torch flickers in the crypt"},
        ],
        "max_tokens": 32,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8091/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        model = body.get("model")
        prov = body.get("phronesis_provenance") or {}
        check("live_proxy_model_alias", model == "phronesis-sovereign-roleplay", model)
        check("live_proxy_tier", "local_roleplay" in str(prov).lower() or "rocinante" in str(prov).lower(), str(prov)[:200])
        print(json.dumps({"model": model, "provenance_keys": list(prov.keys())}, indent=2))
    except Exception as exc:
        check("live_proxy_request", False, str(exc))


def print_trace_tail(n: int = 8) -> None:
    print(f"\n--- Trace log tail ({TRACE_LOG}) ---")
    if not TRACE_LOG.is_file():
        print("  (no trace file yet)")
        return
    lines = TRACE_LOG.read_text(encoding="utf-8").strip().splitlines()
    for line in lines[-n:]:
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description="Discord roleplay routing E2E diagnostic")
    parser.add_argument("--live-proxy", action="store_true", help="POST to live 8091 proxy")
    args = parser.parse_args()

    run_connector_cases()
    test_vram_pin_policy()
    test_system_prompt_severance()
    test_ollama_roleplay_block()
    test_bridge_roleplay_isolation()
    if args.live_proxy:
        run_live_proxy_probe()
    print_trace_tail()

    print("\n=== SUMMARY ===")
    if ERRORS:
        for e in ERRORS:
            print(f"  FAIL {e}")
        return 1
    print("  ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
