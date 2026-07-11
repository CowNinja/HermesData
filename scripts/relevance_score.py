#!/usr/bin/env python3
"""Deterministic relevance for K silo POPULATION (lenient). Twin train_gold is a later filter.

Rules first (path/name/ext/class). Optional local AI for borderline only.
Never flips touch class 1/2/3 — only train relevance labels.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RULES = Path(r"D:\HermesData\config\relevance_rules.json")
sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
from touch_policy import classify as touch_classify  # noqa: E402
from content_context import evaluate_bundle  # noqa: E402


def load_rules() -> dict:
    return json.loads(RULES.read_text(encoding="utf-8"))


def score_path(path: str | Path, rules: dict | None = None, use_ai: bool = False) -> dict:
    rules = rules or load_rules()
    p = Path(path)
    s = str(p).replace("/", "\\")
    name = p.name
    ext = p.suffix.lower()
    sc = rules["scores"]
    score = 0
    reasons: list[str] = []

    cls, cls_note = touch_classify(p)
    if cls == 1:
        score += sc["class1"]
        reasons.append("class1_system")
    elif cls == 2:
        score += sc["class2"]
        reasons.append("class2_personal")
    else:
        score += sc["class3"]
        reasons.append("class3_hybrid_or_unknown")

    low = s.lower()
    for sub in rules["path_noise_substrings"]:
        if sub.lower().replace("/", "\\") in low:
            score += sc["noise_path"]
            reasons.append(f"noise_path:{sub}")
            break

    if ext in rules["ext_noise"]:
        score += sc["noise_ext"]
        reasons.append(f"noise_ext:{ext}")

    for pat in rules["name_noise_regex"]:
        if re.search(pat, name):
            score += sc["noise_name"]
            reasons.append(f"noise_name:{pat}")
            break

    gold_hit = False
    for pat in rules["name_gold_regex"]:
        if re.search(pat, name):
            score += sc["gold_name"]
            reasons.append(f"gold_name:{pat}")
            gold_hit = True
            break

    if ext in rules["ext_goldish"]:
        score += sc["gold_ext"]
        reasons.append(f"gold_ext:{ext}")

    for pat in rules["name_weak_regex"]:
        if re.search(pat, name):
            score += sc["weak_name"]
            reasons.append(f"weak_name:{pat}")
            break

    if ext in {".gdoc", ".gsheet", ".gslides"}:
        score += sc.get("google_stub", 5)
        reasons.append("google_stub_silo_include")

    # --- Content + directory/sibling context (robust evaluation) ---
    bundle = evaluate_bundle(p)
    content = bundle.get("content") or {}
    ctx = bundle.get("context") or {}
    content_hits = bundle.get("content_keyword_hits") or []
    context_hits = bundle.get("context_keyword_hits") or []
    is_stub = bool(bundle.get("is_google_stub"))

    if is_stub:
        reasons.append("local_gdoc_is_pointer_only_no_body")
        # Filename + folder/siblings are the only local signals for stubs
        reasons.append("evaluate_via_name_and_folder_context")

    # Google account identity (Jeff's three only)
    ga_id = bundle.get("google_account_id") or content.get("google_account_id")
    ga_role = bundle.get("google_account_role") or content.get("google_account_role")
    ga_mine = bundle.get("google_account_mine")
    if ga_mine is True:
        score += 20
        reasons.append(f"jeff_google_account:{ga_id or ga_role}")
        if ga_role == "old_disabled":
            score += 10
            reasons.append("lost_account_historical_footprint")
    elif ga_mine is False and content.get("email"):
        reasons.append("foreign_or_unknown_google_email")
        # family helper files still silo-include (lenient); do not noise
        reasons.append("family_or_helper_possible_include")

    if content_hits:
        score += 25 * min(2, len(content_hits))
        reasons.append("content_keywords:" + ",".join(content_hits[:4]))
    if context_hits:
        score += 12 * min(2, len(context_hits))
        reasons.append("dir_sibling_keywords:" + ",".join(context_hits[:4]))

    # folder name signals (path parts)
    folder_blob = " ".join(ctx.get("folders") or []).lower()
    for key, pts in [
        ("medical", 20), ("health", 15), ("navy", 20), ("finance", 15),
        ("tax", 15), ("family", 15), ("spiritual", 12), ("career", 12),
        ("backup", 8), ("google", 5), ("scan", 8), ("photo", 5),
    ]:
        if key in folder_blob:
            score += pts
            reasons.append(f"folder_context:{key}")
            break

    text_sample = (content.get("text") or "")[:500]
    if content.get("needs_ocr"):
        reasons.append("pdf_needs_ocr")

    # Lenient silo population: personal/hybrid trees get inclusion bias
    lenient = bool((rules.get("lenient") or {}).get("enabled", True))
    if lenient and cls in (2, 3):
        score += int(sc.get("lenient_personal_boost", 15))
        reasons.append("lenient_silo_population_boost")

    # thresholds — when in doubt INCLUDE (train_ok / train_weak), not noise
    if cls == 1:
        label = "noise"
    elif score <= sc["max_noise"]:
        label = "noise"  # only clear junk
    elif score >= sc["min_train_gold"] and gold_hit:
        label = "train_gold"
    elif score >= sc["min_train_ok"]:
        label = "train_ok"
    else:
        # doubt band → still silo-eligible
        label = "train_weak" if not lenient else str(
            (rules.get("lenient") or {}).get("doubt_label", "train_ok")
        )
        reasons.append("doubt_include_lenient" if lenient else "doubt_weak")

    ai = None
    # Local AI: help promote weak→ok; only demote to noise if high confidence junk
    if use_ai and cls in (2, 3) and label in {"train_weak", "train_ok", "unknown"}:
        ai = _local_ai_relevance(
            name,
            context_blob=(ctx.get("context_blob") or "")[:800],
            content_sample=text_sample if not is_stub else "",
            is_stub=is_stub,
        )
        vote = (ai or {}).get("vote")
        if vote == "train_ok" and label == "train_weak":
            label = "train_ok"
            reasons.append("ai_vote_train_ok")
            score += 10
        elif vote == "noise" and label == "train_weak" and not gold_hit:
            # only demote weak non-gold — never gold
            label = "train_weak"  # keep in silo; flag in reasons
            reasons.append("ai_suggested_noise_kept_lenient")

    return {
        "path": str(p),
        "class": cls,
        "class_note": cls_note,
        "relevance": label,
        "score": score,
        "reasons": reasons,
        "ai": ai,
        "silo_action": _silo_action(label, cls),
        "is_google_stub": is_stub,
        "content_hits": content_hits,
        "context_hits": context_hits,
        "folders": (ctx.get("folders") or [])[-4:],
        "google_account_id": ga_id,
        "google_account_role": ga_role,

    }


def _silo_action(label: str, cls: int) -> str:
    """Lenient population: weak still copies into silo for evaluation."""
    if cls == 1:
        return "leave_alone"
    if label == "noise":
        return "skip_or_quarantine"
    if label == "train_gold":
        return "copy_priority_high"
    if label == "train_ok":
        return "copy_priority_normal"
    if label == "train_weak":
        return "copy_include_silo"  # still populate silo; twin filter later
    return "copy_include_silo"


def _local_ai_relevance(
    name: str,
    context_blob: str = "",
    content_sample: str = "",
    is_stub: bool = False,
) -> dict:
    script = Path(r"D:\HermesData\scripts\grunt_local.py")
    if not script.exists():
        return {"error": "no_grunt"}
    prompt = (
        "Silo population (lenient): is this useful personal life data to KEEP in a "
        "central archive, or clear junk? Reply JSON only: "
        '{"vote":"train_ok"|"noise"|"unsure","why":"..."}. '
        f"Filename: {name}. "
        f"Google_stub_no_body: {is_stub}. "
        f"Folder_and_siblings: {context_blob[:600]}. "
        f"Content_sample: {content_sample[:800]}"
    )
    try:
        r = subprocess.run(
            [sys.executable, str(script), "classify", "--text", prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = (r.stdout or "").strip()
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") and "vote" in line:
                return json.loads(line)
        # fallback: keyword
        low = out.lower()
        if "noise" in low or "junk" in low:
            return {"vote": "noise", "raw": out[:200]}
        if "train" in low or "personal" in low:
            return {"vote": "train_ok", "raw": out[:200]}
        return {"vote": "unsure", "raw": out[:200]}
    except Exception as e:
        return {"error": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--ai", action="store_true")
    ap.add_argument("--jsonl", action="store_true")
    args = ap.parse_args()
    rules = load_rules()
    rows = [score_path(p, rules, use_ai=args.ai) for p in args.paths]
    if args.jsonl:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
    else:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
