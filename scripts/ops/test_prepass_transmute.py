#!/usr/bin/env python3
"""Live proof: entity pre-inject + narration-to-vault transmutation (turns 4/10)."""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import entity_pre_inject as epi

PROXY = "http://127.0.0.1:8091/v1/chat/completions"
OUT = Path(r"D:\HermesData\state\prepass_transmute_latest.json")


def post(user: str, tools: bool = True, timeout: int = 120) -> dict:
    body = {
        "model": "phronesis-sovereign-auto",
        "messages": [
            {"role": "system", "content": "Do NOT describe tool use in prose. Short answers."},
            {"role": "user", "content": user},
        ],
        "max_tokens": 192 if tools else 96,
        "temperature": 0.2,
        "stream": False,
    }
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "vault_search",
                    "description": "Search vault",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}, "roots": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ]
        body["tool_choice"] = "auto"
    t0 = time.perf_counter()
    req = urllib.request.Request(
        PROXY,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        dt = time.perf_counter() - t0
        msg = ((data.get("choices") or [{}])[0].get("message") or {})
        prov = data.get("phronesis_provenance") or {}
        content = str(msg.get("content") or "")
        names = [(tc.get("function") or {}).get("name") for tc in (msg.get("tool_calls") or [])]
        return {
            "ok": True,
            "sec": round(dt, 3),
            "finish": ((data.get("choices") or [{}])[0].get("finish_reason")),
            "names": names,
            "content_prefix": content[:180],
            "entity": prov.get("entity_preinjected"),
            "entity_ms": prov.get("entity_inject_ms"),
            "transmute": prov.get("narration_transmute"),
            "vault_query": prov.get("vault_query"),
            "vault_hits": prov.get("vault_hits"),
            "has_entity_context": "RELEVANT ENTITY CONTEXT" in json.dumps(data)[:200] or bool(prov.get("entity_preinjected")),
        }
    except Exception as exc:
        return {"ok": False, "sec": round(time.perf_counter() - t0, 3), "error": str(exc)[:200]}


def main() -> int:
    t0 = time.perf_counter()
    st = 0 if epi.selftest() == 0 else 1
    # Re-run selftest captured via print already; call internals for the receipt.
    jan = [h["id"] for h in epi.match("Where does Jan live?")]
    none = [h["id"] for h in epi.match("weather in norfolk")]
    nq = epi.narration_query('Searching the vault for "Booksbloom catalog".')
    vs = epi.run_vault_search(nq or "Booksbloom", "vault", 5) if nq else {}
    canned = {
        "narration_q": nq,
        "vault_ok": bool(vs.get("ok")),
        "vault_hits": vs.get("hit_count"),
        "vault_engine": vs.get("engine"),
        "first": (vs.get("hits") or [{}])[0].get("path") if vs.get("hits") else None,
    }
    inject_ms = (time.perf_counter() - t0) * 1000.0
    rows = {
        "selftest_jan": jan,
        "selftest_none": none,
        "canned_narration": canned,
        "prepass_booksbloom": post("Tell me about Booksbloom intake grading in one short paragraph.", tools=True),
        "turn4": post("vault_search query Booksbloom roots vault max_hits 3. Tool only.", tools=True),
        "turn10": post("vault_search query FLL roots vault. Tool only.", tools=True),
    }
    t4 = rows["turn4"]
    t10 = rows["turn10"]
    pre = rows["prepass_booksbloom"]
    t4_ok = bool(t4.get("ok") and (t4.get("transmute") or t4.get("names") or t4.get("vault_hits") or "ENTITY-Booksbloom" in str(t4.get("content_prefix") or "")))
    t10_ok = bool(t10.get("ok") and (t10.get("transmute") or t10.get("names") or t10.get("vault_hits") or "ENTITY-FLL" in str(t10.get("content_prefix") or "")))
    pre_ok = bool(pre.get("ok") and pre.get("entity"))
    doc = {
        "canned": canned,
        "rows": rows,
        "pass": {
            "selftest": bool(jan) and not none and bool(nq),
            "prepass": pre_ok,
            "turn4": t4_ok,
            "turn10": t10_ok,
            "canned_exec": bool(vs.get("ok")),
        },
        "inject_local_ms": round(inject_ms, 3),
    }
    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), "pass": doc["pass"], "t4": {k: t4.get(k) for k in ("ok", "sec", "transmute", "vault_query", "vault_hits", "names", "entity")}, "t10": {k: t10.get(k) for k in ("ok", "sec", "transmute", "vault_query", "vault_hits", "names", "entity")}, "pre": {k: pre.get(k) for k in ("ok", "sec", "entity", "entity_ms", "names")}}, indent=2))
    ok = all(doc["pass"].values())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
