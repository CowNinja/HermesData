#!/usr/bin/env python3
"""Talk-to-Jan: Hermes curator of Jan Bloom's writing (RAG + SOUL + groundedness).

Research-backed improvements (2026-07-14):
- Answer ONLY from retrieved context; refuse when unsupported
- Citation list always matches retrieve hits (not invented)
- Simple groundedness score: overlap of answer tokens with context
- Lower temperature for faithfulness; heuristic fallback if LLM down
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jan_author_chunk_index import retrieve  # noqa: E402

SOUL = Path(r"D:\PhronesisVault\Operations\SOUL-Jan-Library-Agent-2026-07-14.md")
PUBLIC = Path(r"D:\PhronesisVault\Operations\Jan-Bloom-Public-Context-2026-07-14.md")
FAMILY = Path(r"D:\PhronesisVault\Operations\Jan-Bloom-Family-Living-Facts-2026-07-14.md")
WORKSHOPS = Path(r"D:\PhronesisVault\Operations\Jan-Bloom-Workshop-Catalog-2026-07-18.md")
OUT_LAST = Path(r"D:\PhronesisVault\Operations\logs\talk-to-jan-last.md")
OUT_AUDIT = Path(r"D:\PhronesisVault\Operations\logs\talk-to-jan-audit.jsonl")
PROXY = "http://127.0.0.1:8091/v1/chat/completions"


def load_soul() -> str:
    if SOUL.exists():
        return SOUL.read_text(encoding="utf-8", errors="ignore")[:6000]
    return "You are Hermes curating Jan Bloom's writing. Never be Jan or Jeff."


def load_public() -> str:
    # Thin labeled packs only (vault CNS). Raised caps carefully for faithfulness.
    bits = []
    if PUBLIC.exists():
        bits.append(PUBLIC.read_text(encoding="utf-8", errors="ignore")[:4500])
    if FAMILY.exists():
        bits.append(
            "FAMILY LIVING FACTS (label as family update, never as manuscript quote):\n"
            + FAMILY.read_text(encoding="utf-8", errors="ignore")[:3000]
        )
    if WORKSHOPS.exists():
        bits.append(
            "WORKSHOP CATALOG (from K gold extracts; label as business/workshop docs, not novel prose):\n"
            + WORKSHOPS.read_text(encoding="utf-8", errors="ignore")[:3500]
        )
    conv = Path(r"D:\PhronesisVault\Operations\BooksBloom-Convention-Master-Table-2026-07-19.md")
    if conv.exists():
        bits.append(
            "CONVENTION MASTER TABLE (public + contract anchors; do not invent stops):\n"
            + conv.read_text(encoding="utf-8", errors="ignore")[:4000]
        )
    authors = Path(r"D:\PhronesisVault\Operations\WSWTR-Author-List-Extract-2026-07-19.md")
    if authors.exists():
        bits.append(
            "WSWTR AUTHOR LIST EXTRACT (gold only, PARTIAL — not full 157; never invent missing names):\n"
            + authors.read_text(encoding="utf-8", errors="ignore")[:5000]
        )
    edition = Path(
        r"D:\PhronesisVault\Operations\WSWTR-Author-Edition-Table-2026-07-21.md"
    )
    if edition.exists():
        # Prefer policy + edition facts + counts; full A–Z lives in author_list lane chunks
        ed_txt = edition.read_text(encoding="utf-8", errors="ignore")
        bits.append(
            "WSWTR AUTHOR→EDITION TABLE (gold only, PARTIAL — edition labels from source files; never pad to 157):\n"
            + ed_txt[:6500]
        )
    return "\n\n".join(bits)


def pack_context(hits: list[dict]) -> str:
    parts = []
    for i, h in enumerate(hits, 1):
        src = h.get("source") or h.get("file") or "?"
        lane = h.get("lane") or ""
        text = (h.get("text") or "").strip()
        parts.append(f"[{i}] SOURCE: {src}\nLANE: {lane}\n{text}")
    return "\n\n".join(parts)


def groundedness(answer: str, hits: list[dict]) -> dict:
    """Token-overlap groundedness vs retrieved context (cheap faithfulness proxy)."""
    ctx = " ".join((h.get("text") or "") for h in hits).lower()
    # also allow labeled vault packs (family / workshops / public / conventions / authors)
    pack_bits = []
    pack_paths = [
        FAMILY,
        PUBLIC,
        WORKSHOPS,
        Path(r"D:\PhronesisVault\Operations\BooksBloom-Convention-Master-Table-2026-07-19.md"),
        Path(r"D:\PhronesisVault\Operations\WSWTR-Author-List-Extract-2026-07-19.md"),
        Path(r"D:\PhronesisVault\Operations\WSWTR-Author-Edition-Table-2026-07-21.md"),
    ]
    for p in pack_paths:
        if p.exists():
            pack_bits.append(p.read_text(encoding="utf-8", errors="ignore").lower())
    ctx_words = set(re.findall(r"[a-z0-9']{4,}", ctx + " " + " ".join(pack_bits)))
    ans_words = set(re.findall(r"[a-z0-9']{4,}", answer.lower()))
    # drop stop-ish
    stop = {
        "that",
        "this",
        "with",
        "from",
        "have",
        "been",
        "were",
        "will",
        "your",
        "about",
        "would",
        "could",
        "their",
        "there",
        "which",
        "when",
        "what",
        "hermes",
        "source",
        "family",
    }
    ans_words -= stop
    if not ans_words:
        return {"score": 0.0, "overlap": 0, "ans_terms": 0}
    overlap = ans_words & ctx_words
    score = len(overlap) / max(len(ans_words), 1)
    return {
        "score": round(score, 3),
        "overlap": len(overlap),
        "ans_terms": len(ans_words),
    }


def llm_answer(query: str, hits: list[dict]) -> str | None:
    soul = load_soul()
    public = load_public()
    ctx = pack_context(hits)
    system = (
        soul
        + "\n\n## Public + family living context (secondary; label clearly)\n"
        + public
        + "\n\n## Grounding rules (mandatory)\n"
        "1. Answer ONLY from retrieved SOURCE blocks + clearly labeled family living facts.\n"
        "2. If the sources do not support an answer, say you do not have it on the shelf yet.\n"
        "3. Cite as (Source N — filename). Do not invent source numbers or titles.\n"
        "4. Warm librarian tone. First person Hermes. Never claim to be Jan or Jeff.\n"
        "5. Gary in corpus; Daddy only when reflecting family voice.\n"
        "6. Prefer short quotes from sources over paraphrased invention.\n"
    )
    user = (
        f"Family question:\n{query}\n\n"
        f"Retrieved corpus passages:\n{ctx}\n\n"
        "Write a delightful, citable curator reply (2–5 short paragraphs). "
        "If unsupported, refuse honestly."
    )
    body = {
        "model": "phronesis-sovereign",
        "temperature": 0.35,  # lower for faithfulness
        "max_tokens": 900,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        req = urllib.request.Request(
            PROXY,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def heuristic_answer(query: str, hits: list[dict]) -> str:
    if not hits:
        return (
            "I don’t have strong hits in Jan’s extracted shelves for that yet. "
            "Try WSWTR, Keepers, thrift stores, dedications, road/bookstores, or living books. "
            "(Hermes, curator — not Jan.)"
        )
    qwords = set(re.findall(r"[a-z']{3,}", query.lower()))
    bullets = []
    for i, h in enumerate(hits[:5], 1):
        t = h.get("text") or ""
        sents = re.split(r"(?<=[.!?])\s+", t)
        best = ""
        best_sc = -1
        for s in sents:
            ws = set(re.findall(r"[a-z']{3,}", s.lower()))
            sc = len(qwords & ws)
            if sc > best_sc and len(s) > 40:
                best_sc = sc
                best = s.strip()
        if not best:
            best = t[:280].strip()
        src = Path(h.get("source") or h.get("file") or f"chunk{i}").name
        bullets.append(f"- (Source {i} — {src}) {best}")

    return (
        "From Jan Bloom’s pages on the family shelf, here’s what I can hold up for you:\n\n"
        + "\n".join(bullets)
        + "\n\nI’m Hermes, keeping her library lights on—not speaking *as* her, but *from* her work. "
        "Ask another question and we’ll walk more shelves."
    )


def format_reply(
    query: str, hits: list[dict], answer: str, mode: str, ground: dict
) -> str:
    cites = []
    for i, h in enumerate(hits, 1):
        src = h.get("source") or h.get("file")
        lane = h.get("lane") or ""
        cites.append(f"{i}. `{src}`" + (f" · _{lane}_" if lane else ""))
    warn = ""
    if ground.get("score", 1) < 0.12 and hits:
        warn = (
            "\n\n_Groundedness check low — treat claims carefully; prefer the citations below._"
        )
    return "\n".join(
        [
            "# Jan’s Library — Hermes curator",
            "",
            f"**Question:** {query}",
            f"**Mode:** {mode}",
            f"**Groundedness:** {ground.get('score', 0)} "
            f"(overlap {ground.get('overlap')}/{ground.get('ans_terms')} terms)",
            "",
            "## Answer",
            answer + warn,
            "",
            "## Citations",
            *(cites if cites else ["_No retrieval hits._"]),
            "",
            f"_SOUL: {SOUL}_",
            "",
        ]
    )


def audit(query: str, mode: str, ground: dict, n_hits: int) -> None:
    OUT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "at": datetime.now(timezone.utc).isoformat(),
        "query": query[:200],
        "mode": mode,
        "hits": n_hits,
        "groundedness": ground,
    }
    with OUT_AUDIT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default="What is Who Should We Then Read about?")
    ap.add_argument("-k", type=int, default=8)
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    hits = retrieve(args.query, k=args.k)
    mode = "heuristic"
    answer = heuristic_answer(args.query, hits)
    if not args.no_llm:
        llm = llm_answer(args.query, hits)
        if llm:
            answer = llm
            mode = "llm+rag"
    ground = groundedness(answer, hits)
    out = format_reply(args.query, hits, answer, mode, ground)
    print(out)
    OUT_LAST.parent.mkdir(parents=True, exist_ok=True)
    OUT_LAST.write_text(out, encoding="utf-8")
    audit(args.query, mode, ground, len(hits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
