#!/usr/bin/env python3
"""Silo orchestrator tick — Grok plans once; this script runs the swarm.

Layers (Jeff target perpetual state):
  1) Grok/Hermes  = orchestrator (chat, judgment, rare green lights)
  2) This script  = worker supervisor (script "sub-agents")
  3) Qwythos :8091/:8090 = grunt classify/summarize when UP
  4) Rules/entity = always-on free path when local LLM down

Usage:
  python D:\\HermesData\\scripts\\silo_orchestrator_tick.py
  python D:\\HermesData\\scripts\\silo_orchestrator_tick.py --drain-limit 300 --no-grunt
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPTS = Path(r"D:\HermesData\scripts")
VAULT_LOG = Path(r"D:\PhronesisVault\Operations\logs")
STATE = Path(r"D:\HermesData\state\silo_orchestrator_last.json")


def run(cmd: List[str], timeout: int = 600) -> Tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(SCRIPTS),
        )
        out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
        return p.returncode, out[-4000:]
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def port_up(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2) as r:
                return True
        except Exception:
            return False


def grunt_health() -> Dict[str, Any]:
    code, out = run([sys.executable, str(SCRIPTS / "grunt_local.py"), "health"], 30)
    try:
        return json.loads(out.strip().splitlines()[-1] if out.strip().startswith("{") else out)
    except Exception:
        try:
            return json.loads(out[out.find("{") : out.rfind("}") + 1])
        except Exception:
            return {"ok": False, "raw": out[:500], "exit": code}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drain-limit", type=int, default=800)
    ap.add_argument("--enrich-limit", type=int, default=40)
    ap.add_argument("--train-limit", type=int, default=20)
    ap.add_argument("--reroute-limit", type=int, default=20)
    ap.add_argument("--no-grunt", action="store_true")
    ap.add_argument("--no-drain", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    report: Dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "role": "silo_orchestrator_tick",
        "ports": {
            "8090_qwythos": port_up(8090),
            "8091_proxy": port_up(8091),
        },
        "steps": [],
    }

    # 0) stack probe
    gh = grunt_health() if not args.no_grunt else {"ok": False, "skipped": True}
    report["grunt_health"] = {
        "ok": gh.get("ok"),
        "proxy_status": (gh.get("proxy") or {}).get("status") if isinstance(gh.get("proxy"), dict) else None,
        "llama_error": gh.get("llama_error"),
    }
    local_llm = bool(gh.get("ok")) and report["ports"]["8090_qwythos"]

    # Worker swarm (script sub-agents) — sequential for GPU/disk safety on one machine
    workers: List[Tuple[str, List[str], int]] = []
    if not args.no_drain:
            # Focus land: only top incomplete priority folder (self-improve efficiency)
            workers.append(
                (
                    "focus_land",
                    [
                        sys.executable,
                        str(SCRIPTS / "silo_focus_land.py"),
                        "--limit",
                        str(args.drain_limit),
                    ],
                    1800,
                )
            )
    workers.extend(
        [
            (
                # Fast recursive origin-folder sort (Amazon/CPAP/…) — no LLM
                "rehome_bulk_origin",
                [
                    sys.executable,
                    str(SCRIPTS / "inbox_bulk_origin_rehome.py"),
                    "--apply",
                    "--limit",
                    "2500",
                    "--name-fallback",
                ],
                900,
            ),
            (
                "rehome",
                [sys.executable, str(SCRIPTS / "k_inbox_rehome.py"), "--apply", "--limit", "50"],
                300,
            ),
            (
                "enrich",
                [
                    sys.executable,
                    str(SCRIPTS / "batch_context_enrich.py"),
                    "--limit",
                    str(args.enrich_limit),
                    "--per-shelf",
                    "15",
                ],
                400,
            ),
            (
                "process_status",
                [sys.executable, str(SCRIPTS / "process_status_batch.py"), "--limit", "800"],
                180,
            ),
            (
                "reroute",
                [
                    sys.executable,
                    str(SCRIPTS / "content_domain_reroute.py"),
                    "--limit",
                    str(args.reroute_limit),
                    "--apply",
                ],
                300,
            ),
            (
                # Leftovers only; grunt off by default so tick never 400s-timeouts
                "inbox_process",
                [
                    sys.executable,
                    str(SCRIPTS / "inbox_process.py"),
                    "--apply",
                    "--limit",
                    "80",
                    "--no-grunt",
                ],
                600,
            ),
            (
                "train",
                [
                    sys.executable,
                    str(SCRIPTS / "batch_train_derivatives.py"),
                    "--limit",
                    str(args.train_limit),
                ],
                400,
            ),
            (
                "bw_check",
                [sys.executable, str(SCRIPTS / "bw_dedupe_resume_check.py")],
                30,
            ),
            (
                "registry_stats",
                [sys.executable, str(SCRIPTS / "ingest_registry.py"), "stats"],
                60,
            ),
        ]
    )

    # Optional Qwythos grunt sample (only if up)
    if local_llm and not args.no_grunt:
        workers.append(
            (
                "grunt_sample",
                [
                    sys.executable,
                    str(SCRIPTS / "silo_grunt_batch.py"),
                    "--text",
                    "VA CNP Compensation and Pension appointment Norfolk medical claim",
                    "--limit",
                    "1",
                ],
                180,
            )
        )

    
    workers.append(
        (
            "domain_indexes",
            [sys.executable, str(SCRIPTS / "silo_domain_indexes.py")],
            180,
        )
    )
    workers.append(
        (
            "layout_health",
            [sys.executable, str(SCRIPTS / "silo_layout_health.py")],
            180,
        )
    )
    workers.append(
        (
            "fuse_exact",
            [sys.executable, str(SCRIPTS / "content_fuse_exact.py"), "--limit", "200"],
            300,
        )
    )
    workers.append(
        (
            # superseded by ocr_backlog_worker (process-only); keep lightweight discover every tick noop
            "ocr_discover_light",
            [sys.executable, str(SCRIPTS / "silo_ocr_backlog_worker.py"), "--discover-only"],
            120,
        )
    )

    
    workers.append(
        (
            "folder_dossiers",
            [sys.executable, str(SCRIPTS / "silo_folder_dossiers.py"), "--limit", "80"],
            180,
        )
    )
    workers.append(
        (
            "person_file_graph",
            [sys.executable, str(SCRIPTS / "silo_person_file_graph.py"), "--limit-files", "8000"],
            240,
        )
    )
    workers.append(
        (
            "timeline_harvest",
            [sys.executable, str(SCRIPTS / "silo_timeline_harvest.py"), "--limit", "3000", "--ocr-limit", "80"],
            180,
        )
    )

    
    workers.append(
        (
            "gray_entities_queue",
            [sys.executable, str(SCRIPTS / "silo_gray_entities_queue.py")],
            60,
        )
    )

    
    workers.append(
        (
            "ocr_backlog_worker",
            [sys.executable, str(SCRIPTS / "silo_ocr_backlog_worker.py"), "--process-only", "--limit", "28"],
            600,
        )
    )

    
    workers.append(
        (
            "pko_entity_cards",
            [sys.executable, str(SCRIPTS / "silo_pko_entity_cards.py")],
            180,
        )
    )

    
    workers.append(
        (
            "multi_provenance",
            [sys.executable, str(SCRIPTS / "silo_multi_provenance.py"), "--limit", "50"],
            180,
        )
    )

    
    workers.append(
        (
            "self_heal_monitor",
            [sys.executable, str(SCRIPTS / "silo_self_heal_monitor.py")],
            90,
        )
    )

    
    workers.append(
        (
            "coverage_holistic",
            [sys.executable, str(SCRIPTS / "silo_coverage_holistic.py")],
            200,
        )
    )

    
    workers.append(
        (
            "harvest_small_bulk",
            [sys.executable, str(SCRIPTS / "silo_harvest_small_from_bulk_trees.py"), "--limit", "40", "--apply"],
            120,
        )
    )

    
    workers.append(
        (
            "archive_secrets_encrypted",
            [sys.executable, str(SCRIPTS / "silo_archive_secrets_encrypted_pipeline.py"), "--limit", "30", "--harvest"],
            180,
        )
    )

    
    
    workers.append(
        (
            "encrypted_unlock_assist",
            [sys.executable, str(SCRIPTS / "silo_encrypted_unlock_assist.py"), "--limit", "25"],
            120,
        )
    )

    workers.append(
        (
            "autonomy_control_plane",
            [sys.executable, str(SCRIPTS / "silo_autonomy_control_plane.py")],
            60,
        )
    )

    workers.append(
        (
            "scoreboard_v2",
            [sys.executable, str(SCRIPTS / "silo_scoreboard_v2.py")],
            180,
        )
    )

    workers.append(
        (
            "medical_navy_index",
            [sys.executable, str(SCRIPTS / "silo_medical_navy_text_index.py"), "--limit", "40"],
            180,
        )
    )

    workers.append(
        (
            "post_ingest_qa",
            [sys.executable, str(SCRIPTS / "silo_post_ingest_qa.py")],
            240,
        )
    )

    if not any(w[0]=='ocr_text_clean' for w in workers):
        workers.append(
            (
                'ocr_text_clean',
                [sys.executable, str(SCRIPTS / 'silo_ocr_text_clean.py'), '--limit', '30', '--domain', 'Medical'],
                180,
            )
        )
    if not any(w[0]=='repair_repull' for w in workers):
        workers.append(
            (
                'repair_repull',
                [sys.executable, str(SCRIPTS / 'silo_repair_re_pull.py'), '--apply', '--domain', 'Medical', '--limit', '12'],
                240,
            )
        )
    if not any(w[0]=='repair_repull_navy' for w in workers):
        workers.append(
            (
                'repair_repull_navy',
                [sys.executable, str(SCRIPTS / 'silo_repair_re_pull.py'), '--apply', '--domain', 'Navy', '--limit', '8'],
                180,
            )
        )

    # --- streamline cadence: odd ticks skip heavy secondary cooks ---
    cadence_path = Path(r"D:/HermesData/state/silo_orchestrator_cadence.json")
    try:
        import json as _json
        cad = _json.loads(cadence_path.read_text(encoding="utf-8")) if cadence_path.is_file() else {"n": 0}
    except Exception:
        cad = {"n": 0}
    cad["n"] = int(cad.get("n") or 0) + 1
    n = cad["n"]
    try:
        cadence_path.write_text(_json.dumps(cad), encoding="utf-8")
    except Exception:
        pass
    heavy_even_only = {
        "layout_health", "fuse_exact", "folder_dossiers", "person_file_graph",
        "timeline_harvest", "pko_entity_cards", "multi_provenance",
        "harvest_small_bulk", "archive_secrets_encrypted", "encrypted_unlock_assist",
        "grunt_sample", "ocr_discover_light",
    }
    if n % 2 == 1:
        workers = [w for w in workers if w[0] not in heavy_even_only]
        report["cadence"] = {"n": n, "mode": "core_fast"}
    else:
        report["cadence"] = {"n": n, "mode": "full"}

    workers.append(
        (
            "process_holistic",
            [sys.executable, str(SCRIPTS / "silo_process_holistic_tick.py"), "--ocr-limit", "15", "--status-limit", "300", "--clean-limit", "25"],
            600,
        )
    )


    if not any(w[0]=='inbox_ghost_repoint' for w in workers):
        workers.append(
            (
                'inbox_ghost_repoint',
                [sys.executable, str(SCRIPTS / 'silo_inbox_ghost_repoint.py'), '--batch', '3000', '--rounds', '2'],
                240,
            )
        )


    if not any(w[0]=='local_cook' for w in workers):
        workers.append(
            (
                'local_cook',
                [sys.executable, str(SCRIPTS / 'silo_local_cook_loop.py'), '--once', '--ocr-limit', '16'],
                520,
            )
        )
    if not any(w[0]=='scoreboard_pulse' for w in workers):
        workers.append(
            (
                'scoreboard_pulse',
                [sys.executable, str(SCRIPTS / 'silo_scoreboard_pulse.py')],
                60,
            )
        )

    for name, cmd, timeout in workers:
        code, out = run(cmd, timeout=timeout)
        # try parse last json object
        snippet = out.strip()[-800:]
        ok = code == 0
        # Soft-ok: rehome/bulk may exit nonzero on partial move errors but still progress
        if not ok and name in ("rehome_bulk_origin", "rehome", "inbox_ghost_repoint"):
            if '"applied"' in out or '"planned"' in out or code in (0, 2):
                # exit 2 flake / partial I/O — not a factory red
                ok = True
        report["steps"].append(
            {
                "worker": name,
                "exit": code,
                "ok": ok,
                "out_tail": snippet,
            }
        )

    report["elapsed_s"] = round(time.time() - t0, 1)
    report["local_llm_used"] = local_llm
    report["mode"] = "full_grunt" if local_llm else "scripts_only_rules"

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    VAULT_LOG.mkdir(parents=True, exist_ok=True)
    md = VAULT_LOG / "silo-orchestrator-tick-latest.md"
    lines = [
        f"# Silo orchestrator tick — {report['at']}",
        "",
        f"**Mode:** `{report['mode']}` · elapsed **{report['elapsed_s']}s**",
        f"**Ports:** 8090={report['ports']['8090_qwythos']} · 8091={report['ports']['8091_proxy']}",
        "",
        "| Worker | OK | Exit |",
        "|--------|----|------|",
    ]
    for s in report["steps"]:
        lines.append(f"| {s['worker']} | {s['ok']} | {s['exit']} |")
    lines.append("")
    lines.append("State: `D:\\\\HermesData\\\\state\\\\silo_orchestrator_last.json`")
    lines.append("[[Operations/Orchestrator-Subagent-Qwythos-Perpetual-CANONICAL-2026-07-11]]")
    md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(
        {
            "mode": report["mode"],
            "elapsed_s": report["elapsed_s"],
            "ports": report["ports"],
            "workers_ok": sum(1 for s in report["steps"] if s["ok"]),
            "workers_total": len(report["steps"]),
            "receipt": str(md),
        },
        indent=2,
    ))
    return 0 if all(s["ok"] or s["worker"] in ("grunt_sample", "bw_check") for s in report["steps"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
