#!/usr/bin/env python3
"""
universal_ingest_monitor.py — config-driven ingestion eyes for all sources.

Reads Operations/ingestion_targets.yaml (or path from INGESTION_TARGETS env).
No hardcoded names, URLs, or parsing rules — all targets are data nodes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

DEFAULT_REGISTRY = Path(r"D:\PhronesisVault\Operations\ingestion_targets.yaml")
HERMES_SCRIPTS = Path(r"D:\HermesData\scripts")
sys.path.insert(0, str(HERMES_SCRIPTS))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_registry(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Registry not found: {path}")
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        if yaml is None:
            raise RuntimeError("PyYAML required for .yaml registry")
        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Registry root must be a mapping")
    return data


def fetch_probe(url: str, user_agent: str, timeout_sec: int = 30) -> Tuple[bool, str, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        return True, body, ""
    except Exception as exc:
        return False, "", str(exc)


def extract_integers(html: str, patterns: List[str]) -> List[int]:
    found: List[int] = []
    for pat in patterns:
        for m in re.finditer(pat, html):
            for g in m.groups():
                if g and str(g).isdigit():
                    found.append(int(g))
    return found


def detect_signal(
    detector: str,
    html: str,
    patterns: List[str],
    baseline: Any,
) -> Tuple[bool, Any, str]:
    """Return (has_new, new_baseline, detail)."""
    if detector == "max_integer":
        values = extract_integers(html, patterns)
        if not values:
            current = baseline if baseline is not None else 0
            return False, current, f"no_matches baseline={baseline}"
        current_max = max(values)
        base = int(baseline or 0)
        has_new = current_max > base
        return has_new, current_max, f"max={current_max} baseline={base}"

    if detector == "content_fingerprint":
        blob = "|".join(sorted(set(re.findall(patterns[0], html)))) if patterns else html[:8000]
        fp = hashlib.sha256(blob.encode("utf-8", errors="ignore")).hexdigest()[:16]
        old = str(baseline or "")
        has_new = bool(fp) and fp != old and old != ""
        if old == "":
            has_new = False  # first run seeds baseline without distill
        return has_new, fp, f"fingerprint={fp} prior={old or '(none)'}"

    return False, baseline, f"unknown_detector={detector}"


def load_target_state(state_dir: Path, target_id: str) -> Dict[str, Any]:
    path = state_dir / f"{target_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_target_state(state_dir: Path, target_id: str, state: Dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"{target_id}.json"
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_log(append_dir: Path, suffix: str, line: str) -> Path:
    append_dir.mkdir(parents=True, exist_ok=True)
    path = append_dir / f"{_today()}-{suffix}.md"
    entry = f"- {_utc_now()} {line}\n"
    if path.exists():
        path.write_text(path.read_text(encoding="utf-8") + entry, encoding="utf-8")
    else:
        path.write_text(f"# Cron append {suffix} {_today()}\n\n{entry}", encoding="utf-8")
    return path


def run_distill(
    distill_cfg: Dict[str, Any],
    defaults: Dict[str, Any],
    source_path: Path,
    context_prefix: str,
) -> int:
    script = Path(distill_cfg.get("script") or defaults.get("script", ""))
    if not script.is_file():
        print(f"FAIL: distill script missing: {script}", file=sys.stderr)
        return 1

    cmd = [
        sys.executable,
        str(script),
        "--input", str(source_path),
        "--mode", str(distill_cfg.get("mode", "wisdom")),
        "--sample-name", str(distill_cfg.get("sample_name", "ingest")),
        "--prefer", str(distill_cfg.get("prefer") or defaults.get("prefer", "vault")),
        "--task-type", str(distill_cfg.get("task_type") or defaults.get("task_type", "synthesis")),
    ]
    if distill_cfg.get("force_local", defaults.get("force_local", True)):
        cmd.append("--force-local")
    if context_prefix.strip():
        cmd.extend(["--context-prefix", context_prefix.strip()])

    print("EXEC:", " ".join(cmd))
    return subprocess.run(cmd, cwd=str(HERMES_SCRIPTS.parent)).returncode


def migrate_legacy_state(state_dir: Path, target: Dict[str, Any]) -> None:
    """One-time import from deprecated per-source state files."""
    tid = target["id"]
    state = load_target_state(state_dir, tid)
    if state:
        return
    legacy_map = {
        "brian-roemmele": Path(r"D:\PhronesisVault\Operations\logs\roemmele-cron-state.json"),
    }
    legacy = legacy_map.get(tid)
    if legacy and legacy.exists():
        try:
            old = json.loads(legacy.read_text(encoding="utf-8"))
            key = target.get("signal", {}).get("baseline_key", "last_max")
            if "last_part" in old:
                state[key] = old["last_part"]
            state["migrated_from"] = str(legacy)
            save_target_state(state_dir, tid, state)
        except Exception:
            pass


def process_target(
    target: Dict[str, Any],
    monitor: Dict[str, Any],
    user_agent: str,
    defaults: Dict[str, Any],
    dry_run: bool,
) -> Dict[str, Any]:
    tid = target["id"]
    display = target.get("display_name", tid)
    result: Dict[str, Any] = {"id": tid, "display_name": display, "status": "skipped"}

    if not target.get("enabled", True):
        result["status"] = "disabled"
        return result

    state_dir = Path(monitor["state_dir"])
    append_dir = Path(monitor["append_dir"])
    migrate_legacy_state(state_dir, target)

    signal_cfg = target.get("signal") or {}
    baseline_key = signal_cfg.get("baseline_key", "last_max")
    state = load_target_state(state_dir, tid)
    if state.get(baseline_key) is not None and not state.get("baseline_established"):
        state["baseline_established"] = True  # migrated legacy state counts as established
    baseline = state.get(baseline_key, signal_cfg.get("initial_baseline", 0))

    probe_cfg = target.get("probe") or {}
    ok, html, err = fetch_probe(
        probe_cfg["url"],
        user_agent,
        int(probe_cfg.get("timeout_sec", 30)),
    )
    if not ok:
        detail = f"probe_error: {err}"
        suffix = (target.get("output") or {}).get("cron_append_suffix", monitor.get("cron_id", "ingest"))
        if not dry_run:
            append_log(append_dir, suffix, f"[{tid}] no-new ({display}); {detail}")
            state["last_check"] = _utc_now()
            state["last_error"] = err
            save_target_state(state_dir, tid, state)
        result.update({"status": "probe_error", "detail": detail})
        return result

    has_new, new_baseline, detail = detect_signal(
        signal_cfg.get("detector", "max_integer"),
        html,
        list(signal_cfg.get("patterns") or []),
        baseline,
    )
    result["detail"] = detail
    result["has_new"] = has_new

    suffix = (target.get("output") or {}).get("cron_append_suffix", monitor.get("cron_id", "ingest"))

    # First observation seeds baseline without distilling (avoids false-positive on new targets)
    if not state.get("baseline_established"):
        if not dry_run:
            append_log(
                append_dir,
                suffix,
                f"[{tid}] baseline_seeded ({display}); {detail}",
            )
            state[baseline_key] = new_baseline
            state["baseline_established"] = True
            state["last_check"] = _utc_now()
            save_target_state(state_dir, tid, state)
        result["status"] = "baseline_seeded"
        result["has_new"] = False
        return result

    if not has_new:
        if not dry_run:
            append_log(append_dir, suffix, f"[{tid}] no-new ({display}); {detail}")
            state[baseline_key] = new_baseline
            state["last_check"] = _utc_now()
            state.pop("last_error", None)
            save_target_state(state_dir, tid, state)
            # Refresh feed snapshot in vector index even when signal unchanged
            vec_cfg = monitor.get("vector_index") or {}
            if vec_cfg.get("enabled", True):
                vr = _index_to_vector_store(
                    target,
                    Path((target.get("distill") or {}).get("source_file", "")),
                    html,
                    vec_cfg,
                    event="no_new",
                )
                if vr:
                    result["vector_index"] = vr
        result["status"] = "no-new"
        return result

    distill_cfg = target.get("distill") or {}
    source_path = Path(distill_cfg.get("source_file", ""))
    if not source_path.is_file():
        result["status"] = "error"
        result["detail"] = f"source_file missing: {source_path}"
        return result

    if dry_run:
        result["status"] = "would-distill"
        return result

    rc = run_distill(
        distill_cfg,
        defaults,
        source_path,
        str(distill_cfg.get("context_prefix", "")),
    )
    if rc != 0:
        result["status"] = "distill_failed"
        result["exit_code"] = rc
        return result

    vector_reports = _index_to_vector_store(
        target, source_path, html, monitor.get("vector_index") or {}
    )
    if vector_reports:
        result["vector_index"] = vector_reports

    append_log(
        append_dir,
        suffix,
        f"[{tid}] NEW ({display}); {detail}; distilled mode={distill_cfg.get('mode')} prefer=vault",
    )
    state[baseline_key] = new_baseline
    state["last_check"] = _utc_now()
    state["last_distill"] = str(source_path)
    state.pop("last_error", None)
    save_target_state(state_dir, tid, state)
    result["status"] = "distilled"
    return result


def _index_to_vector_store(
    target: Dict[str, Any],
    source_path: Path,
    html: str,
    vector_cfg: Dict[str, Any],
    *,
    event: str = "distill_success",
) -> List[Dict[str, Any]]:
    """Push distilled / probed content into sovereign sqlite-vec index."""
    if not vector_cfg.get("enabled", True):
        return []
    try:
        from high_signal_ingestion_pipeline import HighSignalIngestionPipeline

        pipeline = HighSignalIngestionPipeline()
        return pipeline.index_for_target(
            target,
            source_path=source_path,
            html=html,
            vector_cfg=vector_cfg,
            event=event,
        )
    except Exception as exc:
        return [{"status": "vector_error", "error": str(exc), "target_id": target.get("id")}]


def run_preflight(monitor: Dict[str, Any]) -> Tuple[bool, str]:
    pf = monitor.get("preflight") or {}
    if not pf.get("enabled", True):
        return True, "skipped"
    from router_bridge import assess_local_stack
    report = assess_local_stack(task_type=pf.get("task_type", "synthesis"), run_classifier_probe=False)
    status = report.get("status", "RED")
    return status in ("GREEN", "YELLOW"), status


def main() -> int:
    parser = argparse.ArgumentParser(description="Universal config-driven ingestion monitor")
    parser.add_argument("--registry", type=Path, default=None, help="Path to ingestion_targets.yaml/json")
    parser.add_argument("--target", help="Process only this target id")
    parser.add_argument("--dry-run", action="store_true", help="Probe only; no distill or state writes")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    args = parser.parse_args()

    reg_path = args.registry or Path(
        __import__("os").environ.get("INGESTION_TARGETS", str(DEFAULT_REGISTRY))
    )
    registry = load_registry(reg_path)
    monitor = registry.get("monitor") or {}
    defaults = registry.get("monitor", {}).get("distill_defaults") or {}
    user_agent = monitor.get("user_agent", "Mozilla/5.0 (compatible; HermesAgent/1.0)")
    targets = registry.get("targets") or []

    print(f"=== Universal Ingest Monitor ===")
    print(f"Registry: {reg_path}")
    print(f"Targets: {len(targets)}")
    print(f"Time: {_utc_now()}")

    ok, pf_status = run_preflight(monitor)
    print(f"Preflight: {pf_status}")
    if not ok:
        print(f"WARN: preflight {pf_status} — continuing probe-only (ingestion is independent of MoE stack health)", file=sys.stderr)

    results: List[Dict[str, Any]] = []
    exit_code = 0
    for target in targets:
        if args.target and target.get("id") != args.target:
            continue
        if not isinstance(target, dict) or "id" not in target:
            continue
        print(f"\n--- {target.get('id')} ({target.get('display_name', '')}) ---")
        r = process_target(target, monitor, user_agent, defaults, args.dry_run)
        print(f"  status={r.get('status')} detail={r.get('detail', '')}")
        results.append(r)
        if r.get("status") in ("error", "distill_failed", "probe_error"):
            exit_code = max(exit_code, 1)

    summary = {"timestamp": _utc_now(), "preflight": pf_status, "results": results}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("\n=== Summary ===")
        for r in results:
            print(f"  {r['id']}: {r['status']}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())