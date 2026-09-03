#!/usr/bin/env python3
"""Pre-pass entity injector. Hot path <2ms after first load.

Match the last user turn against D:\\PhronesisVault\\Entities\\ dossiers and
return a system block for [RELEVANT ENTITY CONTEXT]. Also extracts vault
narration queries for the proxy / conversation_loop transmuter.

  python D:\\HermesData\\scripts\\entity_pre_inject.py --selftest
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

ENTITIES = Path(r"D:\PhronesisVault\Entities")
TOOLS = Path(r"D:\HermesData\scripts\tools")
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Explicit cores (aliases never invented). Extra ENTITY-*.md files still load.
CORE_ALIASES: dict[str, tuple[str, ...]] = {
    "Gary": ("gary",),
    "Sara": ("sara",),
    "Jan": ("jan bloom", "jan l", "jan"),
    "Jodi": ("jodi",),
    "Jenni": ("jenni", "bloom-harris"),
    "Anthony": ("anthony",),
    "Spencer": ("spencer",),
    "Blaizen": ("blaizen",),
    "Booksbloom": ("booksbloom", "books bloom"),
    "FLL-SPIKE-Prime": ("spike prime", "first lego", "fll"),
    "Albion-Online": ("albion online", "albion"),
    "OptiPlex-Sovereign-AI": (
        "optiplex",
        "qwythos",
        "7090",
        "sovereign ai",
        "sovereign architecture",
    ),
}

NARRATION_VAULT_RE = re.compile(
    r"(?:i(?:'m| am)?\s+)?"
    r"(?:searching|checking|looking up|look up|search(?:ing)?|i'll search|let me (?:search|check|look up))\s+"
    r"(?:the\s+)?(?:vault|notes|files|vault_search)\s+"
    r"(?:for\s+)?[\"']?([^\"'\n\.]{2,80})[\"']?",
    re.IGNORECASE,
)
NARRATION_VAULT_RE2 = re.compile(
    r"(searching|checking|looking up)\s+(the\s+)?(vault|notes|files)\s+for\s+[\"']?([^\"'\n\.]+)[\"']?",
    re.IGNORECASE,
)
EXPLICIT_TOOL_RE = re.compile(
    r"\b(vault_search|tool only|<tool_call>|service_manager|system_telemetry)\b",
    re.IGNORECASE,
)
VAULT_QUERY_RE = re.compile(
    r"vault_search(?:\s+query)?\s+(?P<q>.+?)(?:\s+roots\s+(?P<roots>\w+))?(?:\s+max_hits\s+(?P<hits>\d+))?(?:\.\s*tool only\.?)?\s*$",
    re.IGNORECASE,
)

_CACHE: dict[str, Any] = {"sig": None, "items": []}


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")


def _word_re(alias: str) -> re.Pattern[str]:
    parts = [re.escape(p) for p in alias.split() if p]
    if len(parts) == 1:
        return re.compile(r"(?<![A-Za-z])" + parts[0] + r"(?![A-Za-z])", re.IGNORECASE)
    return re.compile(r"(?<![A-Za-z])" + r"\s+".join(parts) + r"(?![A-Za-z])", re.IGNORECASE)


def _sig() -> tuple:
    if not ENTITIES.is_dir():
        return ()
    rows = []
    for p in ENTITIES.glob("ENTITY-*.md"):
        try:
            st = p.stat()
            rows.append((p.name, int(st.st_mtime), st.st_size))
        except OSError:
            continue
    rows.sort()
    return tuple(rows)


def load_items() -> list[dict]:
    sig = _sig()
    if _CACHE["sig"] == sig and _CACHE["items"]:
        return _CACHE["items"]
    items: list[dict] = []
    seen: set[str] = set()
    if ENTITIES.is_dir():
        for p in sorted(ENTITIES.glob("ENTITY-*.md")):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            stem = p.stem.replace("ENTITY-", "")
            title = stem.replace("-", " ")
            m = re.search(r"^#\s+(.+)$", text, re.M)
            if m:
                title = m.group(1).strip()
            aliases = list(CORE_ALIASES.get(stem, ()))
            aliases.append(stem.replace("-", " ").lower())
            aliases.append(stem.lower())
            aliases.append(title.lower())
            uniq = []
            for a in aliases:
                a = a.strip().lower()
                if a and a not in uniq:
                    uniq.append(a)
            items.append(
                {
                    "id": stem,
                    "title": title,
                    "path": str(p),
                    "aliases": tuple(uniq),
                    "patterns": tuple(_word_re(a) for a in uniq),
                    "text": text.strip()[:2400],
                }
            )
            seen.add(stem)
    for name, aliases in CORE_ALIASES.items():
        if name in seen:
            continue
        items.append(
            {
                "id": name,
                "title": name,
                "path": "",
                "aliases": aliases,
                "patterns": tuple(_word_re(a) for a in aliases),
                "text": f"# {name}\n\n_No dossier file. Do not invent._\n",
            }
        )
    items.sort(key=lambda it: -max(len(a) for a in it["aliases"]))
    _CACHE["sig"] = sig
    _CACHE["items"] = items
    return items


def last_user_text(messages: list | str | None) -> str:
    if isinstance(messages, str):
        return messages
    for msg in reversed(messages or []):
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").lower() != "user":
            continue
        c = msg.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            parts = []
            for p in c:
                if isinstance(p, str):
                    parts.append(p)
                elif isinstance(p, dict):
                    parts.append(str(p.get("text") or ""))
            return "\n".join(parts)
        return str(c or "")
    return ""


def explicit_tool_intent(text: str) -> bool:
    return bool(EXPLICIT_TOOL_RE.search(text or ""))


def _alias_in(blob_l: str, alias: str) -> bool:
    if not alias:
        return False
    if " " in alias:
        return alias in blob_l
    i = 0
    n = len(alias)
    while True:
        i = blob_l.find(alias, i)
        if i < 0:
            return False
        left_ok = i == 0 or not blob_l[i - 1].isalpha()
        right_ok = i + n >= len(blob_l) or not blob_l[i + n].isalpha()
        if left_ok and right_ok:
            return True
        i += 1


def match(text: str, cap: int = 3) -> list[dict]:
    blob = (text or "").lower()
    if len(blob.strip()) < 2:
        return []
    hits: list[dict] = []
    used: set[str] = set()
    for it in load_items():
        if it["id"] in used:
            continue
        if any(_alias_in(blob, a) for a in it["aliases"]):
            hits.append(it)
            used.add(it["id"])
            if len(hits) >= cap:
                break
    return hits


def render(hits: list[dict], limit: int = 2400) -> str:
    if not hits:
        return ""
    parts = ["[RELEVANT ENTITY CONTEXT]", "Pre-baked dossiers. Answer from this. Do not vault_search these entities."]
    n = 0
    for it in hits:
        block = it.get("text") or ""
        remain = limit - n
        if remain < 80:
            break
        chunk = block[:remain]
        parts.append(chunk)
        n += len(chunk)
    return "\n\n".join(parts)[: limit + 80]


def inject_messages(messages: list, routing: dict | None = None) -> tuple[list, dict]:
    routing = routing or {}
    if routing.get("narrative_fast") or routing.get("roleplay") or routing.get("is_roleplay"):
        return list(messages or []), {}
    user = last_user_text(messages)
    t0 = time.perf_counter()
    hits = match(user)
    ms = (time.perf_counter() - t0) * 1000.0
    if not hits:
        return list(messages or []), {"ms": round(ms, 3), "injected": []}
    block = render(hits)
    out = []
    for msg in messages or []:
        if (
            isinstance(msg, dict)
            and str(msg.get("role") or "") == "system"
            and "[RELEVANT ENTITY CONTEXT]" in str(msg.get("content") or "")
        ):
            continue
        out.append(msg)
    out.insert(0, {"role": "system", "content": block})
    skip = not explicit_tool_intent(user)
    return out, {
        "ms": round(ms, 3),
        "injected": [h["id"] for h in hits],
        "skip_vault": skip,
        "explicit_tool": not skip,
    }


def narration_query(content: str) -> Optional[str]:
    blob = (content or "").strip()
    if not blob:
        return None
    m = NARRATION_VAULT_RE2.search(blob)
    if m:
        q = (m.group(4) or "").strip().strip("\"'")
        if 1 < len(q) < 80:
            return q
    m = NARRATION_VAULT_RE.search(blob)
    if m:
        q = (m.group(1) or "").strip().strip("\"'")
        q = re.sub(r"\b(now|quickly|real quick)\b", "", q, flags=re.I).strip()
        if 1 < len(q) < 80:
            return q
    return None


def user_vault_query(text: str) -> Optional[dict]:
    blob = (text or "").strip()
    if not blob:
        return None
    m = VAULT_QUERY_RE.search(blob)
    if not m:
        if "vault_search" in blob.lower():
            rest = re.sub(r"(?i)vault_search(?:\s+query)?", "", blob).strip()
            rest = re.sub(r"(?i)\.?\s*tool only\.?\s*$", "", rest).strip()
            if rest:
                return {"query": rest[:80], "roots": "vault"}
        return None
    q = (m.group("q") or "").strip()
    q = re.sub(r"(?i)\.?\s*tool only\.?\s*$", "", q).strip()
    q = re.sub(r"(?i)\s+roots\s+\w+", "", q).strip()
    q = re.sub(r"(?i)\s+max_hits\s+\d+", "", q).strip()
    if not q:
        return None
    return {
        "query": q[:80],
        "roots": (m.group("roots") or "vault"),
        "max_hits": int(m.group("hits") or 8),
    }


def run_vault_search(query: str, roots: str = "vault", max_hits: int = 8) -> dict:
    q = (query or "").strip()
    if len(q) < 2:
        return {"ok": False, "error": "query_too_short", "markdown": ""}
    # Load by path — a different `tools` package is often already on sys.path.
    import importlib.util

    path = TOOLS / "tool_vault_search.py"
    spec = importlib.util.spec_from_file_location("_sovereign_tool_vault_search", path)
    if spec is None or spec.loader is None:
        return {"ok": False, "error": "vault_search_missing", "markdown": ""}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run(
        {
            "query": q,
            "roots": roots or "vault",
            "max_hits": int(max_hits or 8),
            "format": "markdown",
        }
    )


def patch_assistant_message(assistant_message: Any) -> Any:
    """conversation_loop hook: turn vault narration into a real tool_calls array."""
    if assistant_message is None:
        return assistant_message
    tcs = None
    content = ""
    if isinstance(assistant_message, dict):
        tcs = assistant_message.get("tool_calls")
        content = str(assistant_message.get("content") or "")
    else:
        tcs = getattr(assistant_message, "tool_calls", None)
        content = str(getattr(assistant_message, "content", "") or "")
    if tcs:
        return assistant_message
    q = narration_query(content)
    if not q:
        return assistant_message
    call = {
        "id": "call_narration_vault",
        "type": "function",
        "function": {"name": "vault_search", "arguments": json.dumps({"query": q, "roots": "vault"})},
    }
    if isinstance(assistant_message, dict):
        assistant_message = dict(assistant_message)
        assistant_message["tool_calls"] = [call]
        assistant_message["content"] = None
        return assistant_message
    try:
        assistant_message.tool_calls = [call]
        assistant_message.content = None
        if hasattr(assistant_message, "finish_reason"):
            assistant_message.finish_reason = "tool_calls"
    except Exception:
        pass
    return assistant_message


def selftest() -> int:
    load_items()
    samples = (
        "Tell me about Jan and Booksbloom.",
        "FLL SPIKE Prime gyro drive?",
        "Albion crafting focus",
        "OptiPlex 7090 VRAM",
        "Gary and Sara",
        "weather in norfolk",
    )
    t0 = time.perf_counter()
    for s in samples:
        match(s)
    ms = (time.perf_counter() - t0) * 1000.0 / max(len(samples), 1)
    jan = match("Where does Jan live?")
    none = match("weather in norfolk")
    nq = narration_query('Searching the vault for "Booksbloom catalog".')
    uq = user_vault_query("vault_search query Booksbloom roots vault max_hits 3. Tool only.")
    print(
        json.dumps(
            {
                "items": len(load_items()),
                "avg_match_ms": round(ms, 3),
                "jan": [h["id"] for h in jan],
                "none": [h["id"] for h in none],
                "narration_q": nq,
                "user_vault": uq,
                "ok": bool(jan) and not none and bool(nq) and bool(uq),
            }
        )
    )
    return 0 if jan and not none and nq and uq and ms < 2.0 else 1


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else selftest())
