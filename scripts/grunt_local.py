#!/usr/bin/env python3
"""
grunt_local.py — Hybrid grunt CLI for Grok driver / Qwythos worker.

Grok (Hermes primary) should call this via ONE terminal tool instead of
burning tokens on bulk classify/summarize/extract.

Examples:
  python D:\\HermesData\\scripts\\grunt_local.py health
  python D:\\HermesData\\scripts\\grunt_local.py classify --text "invoice PDF about Navy medical"
  python D:\\HermesData\\scripts\\grunt_local.py summarize --text "..." --max-tokens 200
  python D:\\HermesData\\scripts\\grunt_local.py extract --text "..." --schema "json keys: title, date, tags"
  type file.txt | python D:\\HermesData\\scripts\\grunt_local.py summarize --stdin

Env:
  GRUNT_BASE_URL  default http://127.0.0.1:8091/v1
  GRUNT_TIMEOUT   default 120
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_BASE = os.environ.get("GRUNT_BASE_URL", "http://127.0.0.1:8091/v1").rstrip("/")
DEFAULT_TIMEOUT = int(os.environ.get("GRUNT_TIMEOUT", "120"))
DIRECT_8090 = "http://127.0.0.1:8090/v1"

MODEL_MAP = {
    "classify": "phronesis-sovereign-classify",
    "summarize": "phronesis-sovereign-synthesis",
    "extract": "phronesis-sovereign-metadata",
    "code": "phronesis-sovereign-code",
    "auto": "phronesis-sovereign-auto",
}


def _http_json(url: str, payload: Optional[Dict[str, Any]] = None, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw else {}


def health() -> int:
    out: Dict[str, Any] = {"proxy": None, "llama": None, "ok": False}
    try:
        h = _http_json(f"{DEFAULT_BASE.rsplit('/v1', 1)[0]}/health", timeout=5)
        out["proxy"] = h
    except Exception as e:
        out["proxy_error"] = f"{type(e).__name__}: {e}"
    try:
        h2 = _http_json("http://127.0.0.1:8090/health", timeout=5)
        out["llama"] = h2
    except Exception as e:
        out["llama_error"] = f"{type(e).__name__}: {e}"
    out["ok"] = bool(out.get("proxy")) and bool(out.get("llama"))
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


def _chat(model: str, system: str, user: str, max_tokens: int, temperature: float) -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    # Prefer proxy (aliases + trim); fall back to direct 8090
    errors = []
    for base, m in ((DEFAULT_BASE, model), (DIRECT_8090, "DEFAULT")):
        try:
            result = _http_json(f"{base}/chat/completions", payload if base == DEFAULT_BASE else {**payload, "model": m})
            choices = result.get("choices") or []
            if not choices:
                errors.append(f"{base}: empty choices")
                continue
            msg = choices[0].get("message") or {}
            content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
            if content:
                return content
            errors.append(f"{base}: empty content")
        except Exception as e:
            errors.append(f"{base}: {type(e).__name__}: {e}")
    raise RuntimeError("; ".join(errors) or "all backends failed")


def cmd_classify(text: str, max_tokens: int) -> str:
    system = (
        "You are a fast local classifier for Phronesis vault/silo routing. "
        "Reply with compact JSON only: "
        '{"labels":["..."],"domain":"...","priority":"low|med|high","notes":"one line"}'
    )
    return _chat(MODEL_MAP["classify"], system, text[:12000], max_tokens, 0.1)


def cmd_summarize(text: str, max_tokens: int) -> str:
    system = (
        "You are a local summarizer. Produce a tight bullet summary for a human operator. "
        "No preamble. Max ~12 bullets unless content is tiny."
    )
    return _chat(MODEL_MAP["summarize"], system, text[:24000], max_tokens, 0.2)


def cmd_extract(text: str, schema: str, max_tokens: int) -> str:
    system = (
        "You are a local metadata extractor. Output valid JSON only matching the schema request. "
        f"Schema: {schema}"
    )
    return _chat(MODEL_MAP["extract"], system, text[:20000], max_tokens, 0.1)


def cmd_code_hint(text: str, max_tokens: int) -> str:
    system = (
        "You are a local code assistant. Be concise. Prefer patches/steps over essays."
    )
    return _chat(MODEL_MAP["code"], system, text[:20000], max_tokens, 0.2)


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="Local Qwythos grunt CLI for hybrid Grok driver")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health", help="Check :8091 and :8090")

    def add_text(sp):
        sp.add_argument("--text", default="", help="Input text")
        sp.add_argument("--stdin", action="store_true", help="Read text from stdin")
        sp.add_argument("--file", type=Path, help="Read text from file")
        sp.add_argument("--max-tokens", type=int, default=256)

    pc = sub.add_parser("classify")
    add_text(pc)
    ps = sub.add_parser("summarize")
    add_text(ps)
    pe = sub.add_parser("extract")
    add_text(pe)
    pe.add_argument("--schema", default="keys: title, summary, tags", help="JSON schema hint")
    pcode = sub.add_parser("code")
    add_text(pcode)

    args = p.parse_args(argv)
    if args.cmd == "health":
        return health()

    text = args.text or ""
    if getattr(args, "file", None):
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    if getattr(args, "stdin", False) or (not text and not sys.stdin.isatty()):
        if not text:
            text = sys.stdin.read()
    if not text.strip():
        print("ERROR: empty input (use --text, --file, or --stdin)", file=sys.stderr)
        return 2

    try:
        if args.cmd == "classify":
            out = cmd_classify(text, args.max_tokens)
        elif args.cmd == "summarize":
            out = cmd_summarize(text, args.max_tokens)
        elif args.cmd == "extract":
            out = cmd_extract(text, args.schema, args.max_tokens)
        elif args.cmd == "code":
            out = cmd_code_hint(text, args.max_tokens)
        else:
            print("unknown cmd", file=sys.stderr)
            return 2
        print(out)
        return 0
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
