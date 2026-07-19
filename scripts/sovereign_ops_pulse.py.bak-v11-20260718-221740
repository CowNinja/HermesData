#!/usr/bin/env python3
"""Sovereign Ops Pulse — registry-driven receipt + probe aggregator ($0 LLM).

Reads D:/HermesData/config/sovereign_ops_pulse_registry.yaml
Writes JSON + MD cliff notes + optional JSONL history.

Exit policy (soft-fail default):
  0  always when the pulse *ran* and wrote a receipt
  2  registry missing / unreadable (hard misconfig)
  --strict: exit 1 on rollup red

Expand forever: add a receipts: or live_probes: block in the YAML.
Unregistered *-latest.json paths are listed under discovery.unregistered.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore

REGISTRY_DEFAULT = Path(r"D:\HermesData\config\sovereign_ops_pulse_registry.yaml")
SEAL = "sovereign-ops-pulse-v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    return utc_now().isoformat()


def load_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"registry missing: {path}")
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        doc = yaml.safe_load(text)
        if not isinstance(doc, dict):
            raise ValueError("registry root must be mapping")
        return doc
    # Minimal fallback: refuse without pyyaml rather than silent bad parse
    raise RuntimeError("PyYAML required for sovereign_ops_pulse registry")


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "missing"
    try:
        raw = path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None, "not_object"
        return data, None
    except Exception as e:
        return None, f"parse:{type(e).__name__}"


def _age_hours(path: Path) -> float | None:
    try:
        mtime = path.stat().st_mtime
        return max(0.0, (utc_now().timestamp() - mtime) / 3600.0)
    except OSError:
        return None


def _as_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "ok", "pass", "green", "yes", "1"):
            return True
        if s in ("false", "fail", "red", "no", "0", "error"):
            return False
    return None


def interpret_receipt(
    doc: dict[str, Any] | None,
    expect: str,
    defaults: dict[str, Any],
) -> dict[str, Any]:
    """Normalize heterogeneous soft-fail schemas into one verdict."""
    score_green = float(defaults.get("score_green", 90))
    score_amber = float(defaults.get("score_amber", 70))
    out: dict[str, Any] = {
        "ok": None,
        "partial": False,
        "score": None,
        "level": "unknown",  # green|amber|red|unknown|missing
        "signals": [],
    }
    if doc is None:
        out["level"] = "missing"
        out["ok"] = False
        return out

    score = doc.get("score")
    if isinstance(score, (int, float)):
        out["score"] = float(score)

    partial = doc.get("partial")
    if isinstance(partial, bool):
        out["partial"] = partial

    soft = doc.get("soft_fail")
    measure_ok = _as_bool(doc.get("measure_ok"))
    ok_field = _as_bool(doc.get("ok"))
    status = doc.get("status")
    status_ok = _as_bool(status) if status is not None else None

    # Pipeline notes
    if doc.get("pipeline_ok") is True:
        out["signals"].append("pipeline_ok")
    if soft in (True, 1, "1"):
        out["signals"].append("soft_fail")

    if expect == "measure_ok":
        if measure_ok is True:
            out["ok"] = True
            out["level"] = "green"
            out["signals"].append("measure_ok")
        elif measure_ok is False:
            out["ok"] = False
            out["level"] = "amber" if soft else "red"
            out["signals"].append("measure_fail")
        elif ok_field is not None:
            out["ok"] = ok_field
            out["level"] = "green" if ok_field else "amber"
        else:
            # steps present → ran
            steps = doc.get("steps")
            out["ok"] = True if steps else None
            out["level"] = "green" if steps else "unknown"
            out["signals"].append("steps_present" if steps else "no_signal")

    elif expect == "soft_partial_ok":
        # Citadel style: partial OK is amber/green, not red
        if out["partial"] and (ok_field is False or ok_field is None):
            out["ok"] = True
            out["level"] = "amber"
            out["signals"].append("partial_ok")
        elif ok_field is True and not out["partial"]:
            out["ok"] = True
            out["level"] = "green"
        elif ok_field is True and out["partial"]:
            out["ok"] = True
            out["level"] = "amber"
            out["signals"].append("ok_partial")
        elif ok_field is False and not out["partial"]:
            out["ok"] = False
            out["level"] = "red" if not soft else "amber"
        else:
            # channel_count / audit_summary fallback
            if doc.get("channel_count") or doc.get("audit_summary"):
                out["ok"] = True
                out["level"] = "amber"
                out["signals"].append("audit_present")
            else:
                out["level"] = "unknown"

    elif expect == "score_or_checks":
        sc = out["score"]
        if sc is not None:
            out["ok"] = sc >= score_amber
            if sc >= score_green:
                out["level"] = "green"
            elif sc >= score_amber:
                out["level"] = "amber"
            else:
                out["level"] = "red"
            out["signals"].append(f"score={sc}")
        elif ok_field is not None:
            out["ok"] = ok_field
            out["level"] = "green" if ok_field else "red"
        elif status_ok is not None:
            out["ok"] = status_ok
            out["level"] = "green" if status_ok else "amber"
        elif isinstance(doc.get("checks"), (list, dict)):
            out["ok"] = True
            out["level"] = "green"
            out["signals"].append("checks_present")
        elif doc.get("pipeline_ok") is True:
            out["ok"] = True
            out["level"] = "green"
        else:
            out["level"] = "unknown"

    else:  # soft_ok_or_score (default)
        sc = out["score"]
        if sc is not None:
            out["ok"] = sc >= score_amber
            if sc >= score_green and not out["partial"]:
                out["level"] = "green"
            elif sc >= score_amber or out["partial"]:
                out["level"] = "amber"
            else:
                out["level"] = "red"
            out["signals"].append(f"score={sc}")
        elif ok_field is True:
            out["ok"] = True
            out["level"] = "amber" if out["partial"] else "green"
        elif ok_field is False:
            out["ok"] = False
            out["level"] = "amber" if (soft or out["partial"]) else "red"
        elif status_ok is not None:
            out["ok"] = status_ok
            out["level"] = "green" if status_ok else "amber"
        else:
            out["level"] = "unknown"

    return out


def probe_http(url: str, timeout: float = 3.0) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SovereignOpsPulse/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(160).decode("utf-8", errors="replace")
            ok = 200 <= int(resp.status) < 400
            return {
                "ok": ok,
                "status": int(resp.status),
                "snippet": body[:120],
                "error": None,
            }
    except Exception as e:
        # fallback: TCP open?
        try:
            from urllib.parse import urlparse

            u = urlparse(url)
            host = u.hostname or "127.0.0.1"
            port = u.port or (443 if u.scheme == "https" else 80)
            with socket.create_connection((host, port), timeout=min(timeout, 1.5)):
                return {
                    "ok": False,
                    "status": None,
                    "snippet": "",
                    "error": f"tcp_open_http_fail:{type(e).__name__}",
                    "tcp_open": True,
                }
        except OSError:
            return {
                "ok": False,
                "status": None,
                "snippet": "",
                "error": f"{type(e).__name__}:{str(e)[:80]}",
                "tcp_open": False,
            }


def disk_free_gb(path: str) -> float | None:
    try:
        u = shutil.disk_usage(path)
        return round(u.free / (1024**3), 2)
    except OSError:
        return None


def gpu_snapshot() -> dict[str, Any]:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        ).strip()
        # take first GPU
        line = out.splitlines()[0] if out else ""
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 5:
            used, total = float(parts[1]), float(parts[2])
            pct = round(100.0 * used / total, 1) if total else None
            return {
                "ok": True,
                "name": parts[0],
                "mem_used_mb": used,
                "mem_total_mb": total,
                "mem_pct": pct,
                "util_pct": float(parts[3]),
                "temp_c": float(parts[4]),
                "raw": line,
            }
        return {"ok": True, "raw": out}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}:{str(e)[:80]}"}


def discover_unregistered(
    globs: list[str], registered_paths: set[str]
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern in globs:
        for p in sorted(Path().glob(pattern) if False else Path(pattern).parent.glob(Path(pattern).name)):
            # Path.glob needs parent + name from pattern
            pass
    # proper glob
    import glob as _glob

    for pattern in globs:
        for match in _glob.glob(pattern):
            ap = str(Path(match).resolve()) if Path(match).exists() else match
            norm = str(Path(match))
            key = os.path.normcase(os.path.normpath(norm))
            if key in seen:
                continue
            seen.add(key)
            reg_hit = False
            for rp in registered_paths:
                if os.path.normcase(os.path.normpath(rp)) == key:
                    reg_hit = True
                    break
            if reg_hit:
                continue
            age = _age_hours(Path(match))
            found.append(
                {
                    "path": norm,
                    "age_h": round(age, 2) if age is not None else None,
                    "hint": "add under receipts: in sovereign_ops_pulse_registry.yaml",
                }
            )
    # newest first
    found.sort(key=lambda x: (x.get("age_h") is None, x.get("age_h") or 0))
    return found[:40]


def rollup_level(levels: list[str], critical_down: bool) -> str:
    if critical_down:
        return "red"
    if "red" in levels:
        return "red"
    if "missing" in levels:
        # missing core handled by caller weights; treat any missing as amber floor
        pass
    if "amber" in levels or "missing" in levels or "unknown" in levels:
        return "amber"
    if levels and all(l == "green" for l in levels):
        return "green"
    return "amber"


def render_md(report: dict[str, Any]) -> str:
    lines = [
        f"# Sovereign Ops Pulse — {report.get('at', '')}",
        "",
        f"**Rollup:** `{report.get('level')}` · score **{report.get('score')}** · seal `{report.get('seal')}`",
        "",
        "## Live probes",
        "",
        "| ID | OK | Detail |",
        "|----|----|--------|",
    ]
    for p in report.get("probes") or []:
        detail = p.get("status") or p.get("error") or ""
        lines.append(f"| {p.get('id')} | {p.get('ok')} | {detail} |")
    lines += ["", "## Receipts", "", "| ID | Level | OK | Score | Age_h | Notes |", "|----|-------|----|-------|-------|-------|"]
    for r in report.get("receipts") or []:
        notes = ",".join(r.get("signals") or []) or r.get("error") or ""
        if r.get("stale"):
            notes = (notes + " stale").strip()
        lines.append(
            f"| {r.get('id')} | {r.get('level')} | {r.get('ok')} | {r.get('score')} | {r.get('age_h')} | {notes} |"
        )
    dsk = report.get("disk") or []
    if dsk:
        lines += ["", "## Disk", ""]
        for d in dsk:
            lines.append(f"- **{d.get('id')}**: {d.get('free_gb')} GB free · level `{d.get('level')}`")
    gpu = report.get("gpu") or {}
    if gpu:
        lines += ["", "## GPU", "", f"```\n{gpu.get('raw') or gpu}\n```"]
    unreg = (report.get("discovery") or {}).get("unregistered") or []
    if unreg:
        lines += ["", "## Unregistered receipts (expand here)", ""]
        for u in unreg[:15]:
            lines.append(f"- `{u.get('path')}` age_h={u.get('age_h')}")
    issues = report.get("issues") or []
    if issues:
        lines += ["", "## Issues", ""]
        for i in issues:
            lines.append(f"- {i}")
    lines += ["", "---", "_$0 LLM · registry-driven · soft-fail_", ""]
    return "\n".join(lines)


def run_pulse(registry_path: Path) -> dict[str, Any]:
    reg = load_registry(registry_path)
    defaults = reg.get("defaults") or {}
    outputs = reg.get("outputs") or {}
    issues: list[str] = []
    probes_out: list[dict[str, Any]] = []
    receipts_out: list[dict[str, Any]] = []
    levels: list[str] = []
    critical_down = False
    weighted_ok = 0.0
    weighted_total = 0.0

    for p in reg.get("live_probes") or []:
        url = p.get("url") or ""
        timeout = float(p.get("timeout_sec") or 3)
        res = probe_http(url, timeout=timeout)
        row = {
            "id": p.get("id"),
            "label": p.get("label"),
            "tier": p.get("tier"),
            "critical": bool(p.get("critical")),
            "url": url,
            **res,
            "level": "green" if res.get("ok") else ("red" if p.get("critical") else "amber"),
        }
        probes_out.append(row)
        levels.append(row["level"])
        if p.get("critical") and not res.get("ok"):
            critical_down = True
            issues.append(f"critical probe down: {p.get('id')} ({res.get('error') or res.get('status')})")

    registered_paths: set[str] = set()
    for r in reg.get("receipts") or []:
        path_s = r.get("path") or ""
        registered_paths.add(path_s)
        path = Path(path_s)
        max_age = float(r.get("max_age_hours") or defaults.get("max_age_hours") or 30)
        weight = float(r.get("weight") or 1)
        tier = r.get("tier") or "optional"
        doc, err = _read_json(path)
        age = _age_hours(path)
        stale = bool(age is not None and age > max_age)
        interp = interpret_receipt(doc, r.get("expect") or "soft_ok_or_score", defaults)
        level = interp["level"]
        if err == "missing":
            level = "missing"
            if tier in ("core", "hygiene", "rp"):
                issues.append(f"receipt missing: {r.get('id')}")
        elif stale and level == "green":
            level = "amber"
            issues.append(f"stale receipt: {r.get('id')} age_h={age:.1f}>{max_age}")
        elif stale and level not in ("red", "missing"):
            issues.append(f"stale receipt: {r.get('id')} age_h={round(age or 0, 1)}")

        # optional tier never reds the rollup alone
        if tier == "optional" and level == "red":
            level = "amber"

        row = {
            "id": r.get("id"),
            "label": r.get("label"),
            "path": path_s,
            "tier": tier,
            "weight": weight,
            "expect": r.get("expect"),
            "age_h": round(age, 2) if age is not None else None,
            "max_age_hours": max_age,
            "stale": stale,
            "error": err,
            "ok": interp.get("ok"),
            "partial": interp.get("partial"),
            "score": interp.get("score"),
            "level": level,
            "signals": interp.get("signals") or [],
        }
        receipts_out.append(row)
        if tier != "optional":
            levels.append(level)
            weighted_total += weight
            if level == "green":
                weighted_ok += weight
            elif level == "amber":
                weighted_ok += weight * 0.6
            elif level == "unknown":
                weighted_ok += weight * 0.4
            # red/missing add 0

    disk_out: list[dict[str, Any]] = []
    for d in reg.get("disk") or []:
        free = disk_free_gb(d.get("path") or "")
        warn = float(d.get("warn_free_gb") or 40)
        crit = float(d.get("critical_free_gb") or 10)
        if free is None:
            lvl = "unknown"
        elif free < crit:
            lvl = "red"
            issues.append(f"disk critical: {d.get('id')} {free}GB")
            critical_down = True
        elif free < warn:
            lvl = "amber"
            issues.append(f"disk low: {d.get('id')} {free}GB")
        else:
            lvl = "green"
        disk_out.append(
            {
                "id": d.get("id"),
                "label": d.get("label"),
                "path": d.get("path"),
                "free_gb": free,
                "level": lvl,
            }
        )
        levels.append(lvl)

    gpu = gpu_snapshot() if reg.get("gpu") else {}
    if gpu and gpu.get("ok") and isinstance(gpu.get("mem_pct"), (int, float)):
        if gpu["mem_pct"] >= 98:
            issues.append(f"GPU VRAM {gpu['mem_pct']}%")
            levels.append("amber")

    unreg = discover_unregistered(list(reg.get("discovery_globs") or []), registered_paths)

    level = rollup_level(levels, critical_down)
    # composite score 0-100
    if weighted_total > 0:
        base = 100.0 * (weighted_ok / weighted_total)
    else:
        base = 100.0
    probe_pen = sum(15 for p in probes_out if p.get("critical") and not p.get("ok"))
    probe_pen += sum(5 for p in probes_out if not p.get("critical") and not p.get("ok"))
    score = max(0, min(100, round(base - probe_pen, 1)))

    report: dict[str, Any] = {
        "at": utc_iso(),
        "seal": reg.get("seal") or SEAL,
        "version": reg.get("version"),
        "registry": str(registry_path),
        "ok": level in ("green", "amber"),
        "level": level,
        "score": score,
        "soft_fail": bool(defaults.get("soft_fail", True)),
        "issues": issues,
        "probes": probes_out,
        "receipts": receipts_out,
        "disk": disk_out,
        "gpu": gpu,
        "discovery": {
            "unregistered_count": len(unreg),
            "unregistered": unreg,
        },
        "counts": {
            "probes": len(probes_out),
            "probes_ok": sum(1 for p in probes_out if p.get("ok")),
            "receipts": len(receipts_out),
            "receipts_green": sum(1 for r in receipts_out if r.get("level") == "green"),
            "receipts_amber": sum(1 for r in receipts_out if r.get("level") == "amber"),
            "receipts_red": sum(1 for r in receipts_out if r.get("level") == "red"),
            "receipts_missing": sum(1 for r in receipts_out if r.get("level") == "missing"),
        },
    }

    # writes
    json_path = Path(outputs.get("json") or r"D:/PhronesisVault/Operations/logs/sovereign-ops-pulse-latest.json")
    md_path = Path(outputs.get("md") or r"D:/PhronesisVault/Operations/logs/sovereign-ops-pulse-latest.md")
    state_path = Path(outputs.get("state") or r"D:/HermesData/state/sovereign_ops_pulse.json")
    jsonl_path = Path(outputs.get("jsonl") or r"D:/PhronesisVault/Operations/logs/sovereign-ops-pulse.jsonl")

    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    md = render_md(report)
    for pth, content in (
        (json_path, payload),
        (md_path, md),
        (state_path, payload),
    ):
        pth.parent.mkdir(parents=True, exist_ok=True)
        pth.write_text(content, encoding="utf-8")

    try:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        slim = {
            "at": report["at"],
            "level": report["level"],
            "score": report["score"],
            "issues_n": len(issues),
            "probes_ok": report["counts"]["probes_ok"],
            "receipts_green": report["counts"]["receipts_green"],
        }
        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(slim, ensure_ascii=False) + "\n")
    except OSError:
        pass

    report["_wrote"] = {
        "json": str(json_path),
        "md": str(md_path),
        "state": str(state_path),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sovereign Ops Pulse")
    ap.add_argument("--registry", type=Path, default=REGISTRY_DEFAULT)
    ap.add_argument("--strict", action="store_true", help="exit 1 on red rollup")
    ap.add_argument("--json-stdout", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    try:
        report = run_pulse(args.registry)
    except FileNotFoundError as e:
        print(f"SovereignOpsPulse HARD_FAIL {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"SovereignOpsPulse HARD_FAIL {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    line = (
        f"SovereignOpsPulse level={report.get('level')} score={report.get('score')} "
        f"ok={report.get('ok')} issues={len(report.get('issues') or [])} "
        f"probes={report['counts']['probes_ok']}/{report['counts']['probes']} "
        f"receipts_g/a/r/m="
        f"{report['counts']['receipts_green']}/"
        f"{report['counts']['receipts_amber']}/"
        f"{report['counts']['receipts_red']}/"
        f"{report['counts']['receipts_missing']} "
        f"unreg={report['discovery']['unregistered_count']} "
        f"receipt={report.get('_wrote', {}).get('json')}"
    )
    if args.json_stdout:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif not args.quiet:
        print(line)
        for i in (report.get("issues") or [])[:8]:
            print(f"  - {i}")

    if args.strict and report.get("level") == "red":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
