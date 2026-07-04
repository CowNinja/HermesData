"""Shared batch session state for any RP series (solo, duo, custom)."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

BATCH_SESSION = Path(r"D:\HermesData\state\comfy-batch-session.json")
COMFY_OUTPUT = Path(r"D:\ComfyUI\output")

_ASCII_REPL = (
    ("\u2014", "-"),
    ("\u2013", "-"),
    ("\u2026", "..."),
)


def _ascii_label(text: str) -> str:
    out = str(text or "")
    for src, dst in _ASCII_REPL:
        out = out.replace(src, dst)
    return out


def next_png_number() -> int:
    ops = Path(__file__).resolve().parent
    if str(ops) not in sys.path:
        sys.path.insert(0, str(ops))
    from comfy_output_patterns import max_png_index  # noqa: WPS433

    return max_png_index(COMFY_OUTPUT) + 1


def load_session() -> dict:
    if not BATCH_SESSION.is_file():
        return {}
    try:
        data = json.loads(BATCH_SESSION.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def start_session(
    *,
    series: str,
    recipe: str,
    total: int,
    labels: list[str],
    render_count: int,
    offset: int = 0,
    canon_audit: dict | None = None,
    intent_signature: str = "",
) -> int:
    start_png = next_png_number()
    delivered = 0
    series_start = start_png
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    if offset > 0:
        prev = load_session()
        if prev.get("series") == series and int(prev.get("total") or 0) == total:
            delivered = int(prev.get("delivered_count") or offset)
            prev_start = int(prev.get("series_start_png") or 0)
            if prev_start > 0:
                series_start = prev_start
            started_at = str(prev.get("started_at") or started_at)
    payload = {
        "active": True,
        "series": series,
        "recipe": recipe,
        "total": total,
        "series_start_png": series_start,
        "delivered_count": delivered,
        "labels": [_ascii_label(lbl) for lbl in labels],
        "started_at": started_at,
        "render_count": render_count,
        "offset": offset,
    }
    if canon_audit:
        payload["canon_audit"] = canon_audit
    if intent_signature:
        payload["intent_signature"] = intent_signature
    payload["batch_health"] = batch_health_summary(payload)
    BATCH_SESSION.parent.mkdir(parents=True, exist_ok=True)
    BATCH_SESSION.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return series_start


def _read_vram_mode() -> str:
    path = BATCH_SESSION.parent / "comfy-vram-mode.json"
    if not path.is_file():
        return "lowvram"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return str(data.get("mode") or "lowvram")
    except Exception:
        return "lowvram"


def _read_vram_profile() -> str:
    path = BATCH_SESSION.parent / "comfy-vram-profile.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return str(data.get("profile") or "")
    except Exception:
        return ""


def batch_health_summary(session: dict | None = None) -> dict:
    """One-line batch health for Hermes in-thread status or dashboard tile."""
    session = dict(session or load_session())
    delivered = int(session.get("delivered_count") or 0)
    total = int(session.get("total") or 0)
    avg = float(session.get("avg_render_sec") or session.get("last_render_sec") or 0)
    remaining = max(0, total - delivered)
    eta = session.get("eta_min")
    if eta is None and avg > 0 and remaining:
        eta = round((remaining * avg) / 60.0, 1)
    return {
        "active": bool(session.get("active")),
        "series": str(session.get("series") or ""),
        "recipe": str(session.get("recipe") or ""),
        "delivered": delivered,
        "total": total,
        "progress": f"{delivered}/{total}" if total else "0/0",
        "eta_min": eta,
        "avg_render_sec": round(avg, 1) if avg else None,
        "quality_profile": str(os.environ.get("RP_BATCH_SPEED", "quality") or "quality"),
        "vram_mode": _read_vram_mode(),
        "vram_profile": _read_vram_profile(),
        "queue_pending": session.get("queue_pending"),
        "latest_png": session.get("latest_png"),
        "latest_label": session.get("latest_label"),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def update_progress(
    *,
    latest_png: str = "",
    render_sec: float = 0,
    queue_pending: int = 0,
    label: str = "",
) -> None:
    """Structured batch progress for WisdomVault / Hermes visibility."""
    session = load_session()
    if not session.get("active") and not session.get("series"):
        return
    session["progress_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if latest_png:
        session["latest_png"] = latest_png
    if label:
        session["latest_label"] = _ascii_label(label)
    if render_sec > 0:
        session["last_render_sec"] = round(render_sec, 1)
        timings = list(session.get("render_timings") or [])
        timings.append(
            {
                "png": latest_png,
                "label": _ascii_label(label),
                "render_sec": round(render_sec, 1),
                "at": session["progress_at"],
            }
        )
        session["render_timings"] = timings[-20:]
        recent = [float(t.get("render_sec") or 0) for t in timings[-5:] if t.get("render_sec")]
        if recent:
            avg = sum(recent) / len(recent)
            delivered = int(session.get("delivered_count") or 0)
            total = int(session.get("total") or 0)
            remaining = max(0, total - delivered)
            session["avg_render_sec"] = round(avg, 1)
            session["eta_min"] = round((remaining * avg) / 60.0, 1) if remaining else 0.0
    if queue_pending >= 0:
        session["queue_pending"] = queue_pending
    session["batch_health"] = batch_health_summary(session)
    BATCH_SESSION.write_text(json.dumps(session, indent=2), encoding="utf-8")


def close_session(*, ok: int, fail: int, offset: int = 0) -> None:
    """Record render results; keep session active until delivery daemon finishes."""
    session = load_session()
    if not session:
        return
    total = int(session.get("total") or 0)
    rendered = offset + ok
    session["render_ok"] = ok
    session["render_fail"] = fail
    session["render_completed"] = max(int(session.get("render_completed") or 0), rendered)
    session["render_closed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if fail == 0 and total and rendered >= total:
        session["render_complete_at"] = session["render_closed_at"]
    # active cleared only by comfy_delivery_daemon when delivered_count >= total
    BATCH_SESSION.write_text(json.dumps(session, indent=2), encoding="utf-8")