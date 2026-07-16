#!/usr/bin/env python3
"""Twin readiness Swiss-watch smoke — one local command, no cloud tokens.

Runs: compile core · OCR open · scoreboard · twin stamp sample · retrieval demos ·
parking readiness · purge gates · next-sources probe · Qwythos/proxy health.

Receipt: Operations/logs/silo-twin-readiness-smoke-latest.md
"""
from __future__ import annotations

import json
import py_compile
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:/HermesData/scripts")
PY = sys.executable
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-twin-readiness-smoke-latest.md")
STATE = Path(r"D:/HermesData/state/silo_twin_readiness_smoke.json")

CORE = [
    "silo_local_cook_loop.py",
    "silo_twin_meta_stamp.py",
    "silo_twin_retrieval_demo.py",
    "batch_train_derivatives.py",
    "silo_scoreboard_pulse.py",
    "silo_future_projects_parking.py",
    "silo_purge_plan_report.py",
    "silo_relevance_heuristics.py",
    "silo_overnight_cook.py",
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(args: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-2000:]
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def port_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    checks: list[dict] = []
    # 1 compile
    compile_ok = 0
    for name in CORE:
        p = SCRIPTS / name
        try:
            py_compile.compile(str(p), doraise=True)
            compile_ok += 1
        except Exception as e:
            checks.append({"step": f"compile:{name}", "ok": False, "detail": str(e)[:120]})
    checks.append({"step": "compile_core", "ok": compile_ok == len(CORE), "detail": f"{compile_ok}/{len(CORE)}"})

    # 2 health ports
    q = port_ok("http://127.0.0.1:8090/health")
    px = port_ok("http://127.0.0.1:8091/health")
    checks.append({"step": "qwythos_8090", "ok": q, "detail": "health"})
    checks.append({"step": "proxy_8091", "ok": px, "detail": "health"})

    # 3 scoreboard
    code, out = run([PY, str(SCRIPTS / "silo_scoreboard_pulse.py")], 60)
    ocr_open = None
    twin = {}
    try:
        snap = json.loads(out[out.find("{") :])
        ocr_open = snap.get("ocr_open")
        twin = snap.get("twin") or {}
    except Exception:
        snap = {}
    checks.append(
        {
            "step": "scoreboard",
            "ok": code == 0 and ocr_open == 0,
            "detail": f"ocr_open={ocr_open} era={twin.get('era')} k_light={twin.get('k_light_index')}",
        }
    )

    # 4 stamp sample
    code, out = run(
        [
            PY,
            str(SCRIPTS / "silo_twin_meta_stamp.py"),
            "--root",
            r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Navy-Service",
            "--limit",
            "15",
            "--max-scan",
            "200",
        ],
        90,
    )
    checks.append({"step": "stamp_navy_sample", "ok": code == 0, "detail": out.strip()[-200:]})

    # 5 retrieval
    code, out = run([PY, str(SCRIPTS / "silo_twin_retrieval_demo.py")], 120)
    checks.append({"step": "retrieval_demo", "ok": code == 0, "detail": out.strip()[-300:]})

    # 6 parking readiness
    code, out = run([PY, str(SCRIPTS / "silo_future_projects_parking.py"), "readiness"], 180)
    checks.append({"step": "parking_readiness", "ok": code == 0, "detail": "receipt written" if code == 0 else out[:200]})

    # 7 purge report
    code, out = run([PY, str(SCRIPTS / "silo_purge_plan_report.py")], 60)
    ready = "ready_for_phrase" in out and "true" in out
    checks.append({"step": "purge_gates", "ok": code == 0, "detail": out.strip()[-200:], "ready_for_phrase": ready})

    # 8 next sources probe (paths only)
    roots = {
        "Takeout": [r"D:/Takeout", r"D:/GoogleTakeout"],
        "CloudSync": [r"D:/CloudSync", r"D:/Documents"],
        "USB": [r"E:/", r"F:/"],
    }
    present = {k: any(Path(p).exists() for p in v) for k, v in roots.items()}
    checks.append({"step": "next_sources_probe", "ok": True, "detail": json.dumps(present)})

    passed = sum(1 for c in checks if c.get("ok"))
    total = len(checks)
    report = {
        "at": utc(),
        "passed": passed,
        "total": total,
        "checks": checks,
        "era": twin.get("era"),
        "ocr_open": ocr_open,
    }
    STATE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        f"# Twin readiness smoke — {report['at']}",
        "",
        f"**{passed}/{total}** checks passed · era `{twin.get('era')}` · ocr_open `{ocr_open}`",
        "",
        "| Step | OK | Detail |",
        "|------|:--:|--------|",
    ]
    for c in checks:
        lines.append(
            f"| {c['step']} | {'✅' if c.get('ok') else '❌'} | `{str(c.get('detail',''))[:80]}` |"
        )
    lines += [
        "",
        "Purge remains **NOT ARMED** without Jeff phrase `purge drive OK`.",
        "Canon: [[Operations/Twin-Readiness-Post-OCR-CANONICAL-2026-07-14]]",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"passed": passed, "total": total, "receipt": str(RECEIPT), "ocr_open": ocr_open}, indent=2))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
