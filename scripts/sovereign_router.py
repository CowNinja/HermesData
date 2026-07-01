#!/usr/bin/env python3
"""
Sovereign Router - Local-first dispatch to minimize Grok / cloud token usage.

Core principle: Route as much work as possible to local models (Ollama live).
Tiers (simple start):
- fast: lightweight local for simple tasks
- strong: capable local (14B class) for reasoning / code
- escalate: only for tasks that truly require cloud (manual flag or future classifier)

Usage:
    from sovereign_router import dispatch
    result = dispatch("Write a Python function to...", task_type="code")
    print(result["model"], result["response"][:200])

Provenance included on every dispatch.
"""

import os
import json
import time
import requests
import datetime as dt

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
OLLAMA_API = f"{OLLAMA_BASE}/api/generate"
OLLAMA_OPENAI = f"{OLLAMA_BASE}/v1/chat/completions"

# Local model preferences (tuned to what's actually available and strong)
FAST_MODEL = "phi3:mini"          # very fast, good for simple
STRONG_MODEL = "qwen2.5:14b"      # excellent reasoning/coding from inventory
FALLBACK_MODELS = ["qwen3:8b", "llama3.1:8b", "dolphin-llama3:8b"]

def _classify_task(prompt: str, task_type: str = None) -> str:
    """Very lightweight heuristic classifier. Returns 'fast' or 'strong'."""
    if task_type:
        t = task_type.lower()
        if t in ("code", "reason", "complex", "analysis", "debug"):
            return "strong"
        if t in ("simple", "chat", "fast", "lookup"):
            return "fast"

    p = prompt.lower()
    strong_keywords = ["code", "function", "class", "debug", "implement", "architecture", 
                       "analyze", "reason", "explain why", "compare", "optimize", "refactor"]
    if any(kw in p for kw in strong_keywords):
        return "strong"
    return "fast"

def _pick_model(tier: str) -> str:
    if tier == "strong":
        return STRONG_MODEL
    # fast or default
    return FAST_MODEL

def _call_ollama(prompt: str, model: str, timeout: int = 120, stream: bool = False) -> dict:
    """Call Ollama. Stream=False for sync, stream=True yields tokens as they arrive (lower perceived latency)."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "options": {
            "num_predict": 1024,
            "temperature": 0.2,
        }
    }
    try:
        if stream:
            # Streaming path: assemble tokens as they arrive
            resp = requests.post(OLLAMA_API, json=payload, timeout=timeout, stream=True)
            resp.raise_for_status()
            chunks = []
            for line in resp.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line)
                        if chunk.get("done"):
                            duration = chunk.get("total_duration")
                        if "response" in chunk:
                            chunks.append(chunk["response"])
                    except json.JSONDecodeError:
                        continue
            return {
                "success": True,
                "response": "".join(chunks).strip(),
                "model": model,
                "done": True,
                "streamed": True,
            }
        resp = requests.post(OLLAMA_API, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return {
            "success": True,
            "response": data.get("response", "").strip(),
            "model": model,
            "done": data.get("done", True),
            "total_duration": data.get("total_duration"),
            "streamed": False,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "model": model}

def dispatch(prompt: str, task_type: str = None, force_local: bool = True, stream: bool = False) -> dict:
    """
    Main Sovereign Router entrypoint.
    Returns structured dict with full provenance for token/cost tracking.
    """
    started = time.time()
    tt = (task_type or "").lower().replace("-", "_")
    if tt in ("roleplay", "narrative", "dnd", "d_and_d", "immersive_roleplay", "uncensored_roleplay"):
        return {
            "response": "[SYSTEM BLOCK] Roleplay requested, but uncensored backend is offline.",
            "model": None,
            "tier": "local_roleplay",
            "success": False,
            "provenance": {
                "source": "ollama_router_blocked",
                "reason": "aligned_ollama_fallback_forbidden_for_roleplay",
                "task_type": task_type,
            },
            "latency_sec": round(time.time() - started, 2),
        }
    try:
        from roleplay_subsystem import detect_roleplay_intent

        if detect_roleplay_intent(prompt, task_type=task_type).get("should_route"):
            return {
                "response": "[SYSTEM BLOCK] Roleplay requested, but uncensored backend is offline.",
                "model": None,
                "tier": "local_roleplay",
                "success": False,
                "provenance": {
                    "source": "ollama_router_blocked",
                    "reason": "prompt_roleplay_signal_forbidden_on_ollama",
                },
                "latency_sec": round(time.time() - started, 2),
            }
    except Exception:
        pass
    tier = _classify_task(prompt, task_type)
    model = _pick_model(tier)

    provenance = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tier": tier,
        "chosen_model": model,
        "classifier": "heuristic_v1",
        "force_local": force_local,
        "reason": f"Local-first policy. Tier={tier} based on keywords/task_type.",
    }

    # Always try local first (core of the token-saving mission)
    # Use streaming for fast tier (lower perceived latency on simple tasks)
    use_stream = stream or (tier == "fast")
    result = _call_ollama(prompt, model, stream=use_stream)

    # Record dispatch to nanoDB for auto-pick learning
    if result.get("success"):
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from scripts.nanodb import record_dispatch as _ndb_record
            resp_text = str(result.get("response") or "")
            tokens = max(1, len(resp_text) // 4)
            latency_sec = time.time() - started
            tps = tokens / latency_sec if latency_sec > 0 else 0
            _ndb_record(task_type=tt or "auto", model=model,
                        latency_ms=round(latency_sec * 1000, 1), tps=round(tps, 1))
        except Exception:
            pass  # Never block dispatch on metrics

    if result.get("success"):
        provenance["source"] = "local_ollama"
        provenance["tokens_saved_estimate"] = "high (avoided Grok/cloud call)"
        provenance["streamed"] = result.get("streamed", False)
        provenance["latency_sec"] = round(time.time() - started, 2)
        return {
            "response": result["response"],
            "model": model,
            "tier": tier,
            "provenance": provenance,
            "success": True,
        }

    # If local failed and we are forced local, return error (do not auto-escalate to Grok)
    if force_local:
        provenance["source"] = "local_failed"
        provenance["error"] = result.get("error")
        return {
            "response": f"[SOVEREIGN ROUTER] Local model {model} failed. No escalation to cloud performed (token-saving policy).",
            "model": model,
            "tier": tier,
            "provenance": provenance,
            "success": False,
        }

    # Future: add Grok / cloud escalation path here only when explicitly allowed
    provenance["source"] = "local_failed_escalation_not_implemented"
    return {
        "response": "[SOVEREIGN ROUTER] Local dispatch failed and escalation path not yet enabled.",
        "model": "none",
        "tier": tier,
        "provenance": provenance,
        "success": False,
    }

def test_router():
    """Quick self-test using live Ollama."""
    print("=== Sovereign Router Self-Test (local-first) ===")
    test_prompt = "Write a one-line Python list comprehension that squares numbers 1-5."
    res = dispatch(test_prompt, task_type="code")
    print("Tier:", res["tier"])
    print("Model:", res["model"])
    print("Success:", res["success"])
    print("Provenance reason:", res["provenance"]["reason"])
    print("Response preview:", res["response"][:200] if res.get("response") else "N/A")
    print("=== Test complete ===")
    return res

if __name__ == "__main__":
    test_router()
