#!/usr/bin/env python3
"""Grand vision alignment check — report-only.

Verifies Four Worlds + segments + twin-scope + kitchen invariants match files on disk.
Writes: D:/PhronesisVault/Operations/logs/grand-vision-align-latest.md

Exit 0 = all required OK; 1 = gaps; 2 = fatal missing SSOT.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

VAULT = Path(r"D:/PhronesisVault/Operations")
HERMES = Path(r"D:/HermesData")
RECEIPT = VAULT / "logs" / "grand-vision-align-latest.md"
STATE = HERMES / "state" / "grand_vision_align_latest.json"

REQUIRED_DOCS = [
    VAULT / "Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10.md",
    VAULT / "Silo-Segment-Infrastructure-CANONICAL-2026-07-18.md",
    VAULT / "Multi-Twin-Silo-Scope-Doctrine-CANONICAL-2026-07-18.md",
    VAULT / "Grand-Vision-Alignment-CANONICAL-2026-07-18.md",
    VAULT / "Autonomous-Silo-Runbook-CANONICAL-2026-07-14.md",
    VAULT / "SOUL-Data-Silo-Agent-2026-07-17.md",
]
REQUIRED_CONFIG = [
    HERMES / "config" / "data_silos.yaml",
    HERMES / "config" / "silo_segments.yaml",
    HERMES / "config" / "future_projects_parking.json",
    HERMES / "config" / "land_priority_queue.json",
]
REQUIRED_SCRIPTS = [
    HERMES / "scripts" / "silo_discord_six_numbers.py",
    HERMES / "scripts" / "silo_segment_cli.py",
    HERMES / "scripts" / "silo_relevance_heuristics.py",
    HERMES / "scripts" / "silo_focus_land.py",
    HERMES / "scripts" / "silo_continuous_loop.py",
    HERMES / "scripts" / "modality_detect.py",
    HERMES / "scripts" / "grand_vision_align_check.py",
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def exists_row(paths: list[Path]) -> list[dict]:
    return [{"path": str(p), "ok": p.is_file()} for p in paths]


def check_code_symbols() -> list[dict]:
    checks = []
    rel = (HERMES / "scripts" / "silo_relevance_heuristics.py").read_text(encoding="utf-8", errors="replace")
    checks.append({"id": "twin_scopes_fn", "ok": "def twin_scopes" in rel})
    checks.append({"id": "train_meta_flags_scopes", "ok": "twin_scopes" in rel and "def train_meta_flags" in rel})
    focus = (HERMES / "scripts" / "silo_focus_land.py").read_text(encoding="utf-8", errors="replace")
    checks.append({"id": "empty_plan_auto_advance", "ok": "empty_plan" in focus and "land_complete" in focus})
    mod = (HERMES / "scripts" / "modality_detect.py").read_text(encoding="utf-8", errors="replace")
    checks.append({"id": "html_text_modality", "ok": '".html"' in mod and "text" in mod})
    fw = (VAULT / "Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10.md").read_text(encoding="utf-8", errors="replace")
    checks.append({"id": "four_worlds_mentions_segments", "ok": "silo_segments" in fw or "Segments inside World 3" in fw})
    idx = (VAULT / "00-INDEX.md").read_text(encoding="utf-8", errors="replace")
    checks.append({"id": "ops_index_grand_vision", "ok": "Grand-Vision-Alignment" in idx})
    soul = (VAULT / "SOUL-Data-Silo-Agent-2026-07-17.md").read_text(encoding="utf-8", errors="replace")
    checks.append({"id": "soul_mentions_segments_or_grand", "ok": "segment" in soul.lower() or "Grand-Vision" in soul})
    runbook = (VAULT / "Autonomous-Silo-Runbook-CANONICAL-2026-07-14.md").read_text(encoding="utf-8", errors="replace")
    checks.append({"id": "runbook_segment_cli", "ok": "silo_segment_cli" in runbook or "silo_segments.yaml" in runbook})
    return checks


def check_segments_yaml() -> dict:
    p = HERMES / "config" / "silo_segments.yaml"
    out = {"ok": False, "jeff_first": False, "count": 0, "ids": []}
    if not p.is_file() or not yaml:
        return out
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    segs = data.get("segments") or {}
    out["count"] = len(segs)
    out["ids"] = list(segs.keys())
    out["ok"] = "jeff_life_twin" in segs and len(segs) >= 4
    jf = segs.get("jeff_life_twin") or {}
    out["jeff_first"] = bool(jf.get("train_default") is True) and all(
        (not s.get("train_default")) or sid == "jeff_life_twin" for sid, s in segs.items()
    )
    return out


def check_data_silos() -> dict:
    p = HERMES / "config" / "data_silos.yaml"
    out = {"ok": False, "worlds": 0, "mentions_segments": False}
    if not p.is_file():
        return out
    text = p.read_text(encoding="utf-8", errors="replace")
    out["mentions_segments"] = "segment" in text.lower()
    if yaml:
        data = yaml.safe_load(text) or {}
        silos = data.get("silos") or {}
        worlds = {int(v.get("world")) for v in silos.values() if isinstance(v, dict) and v.get("world") is not None}
        out["worlds"] = len(worlds)
        out["ok"] = len(worlds) >= 4
        out["world_ids"] = sorted(worlds)
    else:
        out["ok"] = "world: 4" in text or "world: 3" in text
    return out


def land_writers() -> dict:
    try:
        r = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                "name='python.exe' or name='pythonw.exe'",
                "get",
                "CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        t = r.stdout or ""
    except Exception as e:
        return {"error": str(e)}
    c = {
        "continuous": t.count("silo_continuous_loop.py"),
        "orchestrator": t.count("silo_orchestrator_tick.py"),
        "focus": t.count("silo_focus_land.py"),
        "drain": t.count("g_to_k_safe_drain.py"),
        "sprint": t.count("silo_autonomous_sprint.py"),
    }
    c["dual_land"] = c["continuous"] > 1 or c["focus"] > 1 or c["drain"] > 1
    c["ok_single"] = c["continuous"] <= 1 and c["focus"] <= 1 and c["drain"] <= 1
    return c


def six_numbers() -> dict | None:
    try:
        r = subprocess.run(
            [sys.executable, str(HERMES / "scripts" / "silo_discord_six_numbers.py")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        m = re.search(r"JSON (\{.*\})", r.stdout or "")
        if m:
            return json.loads(m.group(1))
    except Exception:
        return None
    return None


def main() -> int:
    at = utc()
    docs = exists_row(REQUIRED_DOCS)
    cfgs = exists_row(REQUIRED_CONFIG)
    scripts = exists_row(REQUIRED_SCRIPTS)
    symbols = check_code_symbols()
    segs = check_segments_yaml()
    worlds = check_data_silos()
    writers = land_writers()
    metrics = six_numbers()

    req_ok = all(x["ok"] for x in docs + cfgs + scripts)
    sym_ok = all(x["ok"] for x in symbols)
    struct_ok = segs.get("ok") and segs.get("jeff_first") and worlds.get("ok")
    # data_silos segments mention is soft (warn)
    soft = []
    if not worlds.get("mentions_segments"):
        soft.append("data_silos.yaml should mention segments pointer")
    if not (VAULT / "00-INDEX.md").read_text(encoding="utf-8", errors="replace").count("Silo-Segment"):
        soft.append("00-INDEX should link Silo-Segment-Infrastructure")

    hard_fail = []
    if not req_ok:
        hard_fail.append("missing required files")
    if not sym_ok:
        hard_fail.append("code/doc symbol gaps: " + ",".join(s["id"] for s in symbols if not s["ok"]))
    if not struct_ok:
        hard_fail.append("segments/worlds structure")
    if writers.get("dual_land"):
        hard_fail.append("dual land writer")

    payload = {
        "at": at,
        "pass": not hard_fail,
        "hard_fail": hard_fail,
        "soft": soft,
        "docs": docs,
        "configs": cfgs,
        "scripts": scripts,
        "symbols": symbols,
        "segments": segs,
        "worlds": worlds,
        "writers": writers,
        "metrics": metrics,
    }

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)

    def yn(b: bool) -> str:
        return "PASS" if b else "FAIL"

    lines = [
        f"# Grand vision align check — {at}",
        "",
        f"**Overall:** **{yn(payload['pass'])}**",
        "",
        "## Hard",
        f"- required files: {yn(req_ok)}",
        f"- symbols/docs wiring: {yn(sym_ok)}",
        f"- segments jeff-first + 4 worlds: {yn(bool(struct_ok))}",
        f"- single land writer: {yn(bool(writers.get('ok_single')))}",
        "",
        "## Soft warnings",
    ]
    if soft:
        for s in soft:
            lines.append(f"- {s}")
    else:
        lines.append("- none")
    lines += [
        "",
        "## Writers",
        f"```json\n{json.dumps(writers, indent=2)}\n```",
        "",
        "## Metrics",
        f"```json\n{json.dumps(metrics, indent=2)}\n```",
        "",
        "## Segments",
        f"```json\n{json.dumps(segs, indent=2)}\n```",
        "",
        "[[Operations/Grand-Vision-Alignment-CANONICAL-2026-07-18]]",
        "",
    ]
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"pass": payload["pass"], "hard_fail": hard_fail, "soft": soft, "receipt": str(RECEIPT)}, indent=2))
    if not req_ok:
        return 2
    return 0 if payload["pass"] and not hard_fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
