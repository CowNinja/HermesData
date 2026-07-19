#!/usr/bin/env python3
"""Lightweight ComfyUI queue client - submit, poll, metrics."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

# Production: Comfy inference :8188, gallery SPA :8189.
# Gallery returns 200 HTML for /system_stats — must JSON-validate, prefer 8188.
# COMFY_URL env still wins; otherwise probe 8188 then 8189 once at import.
def _detect_comfy_url() -> str:
    env = (os.environ.get("COMFY_URL") or "").strip()
    if env:
        return env.rstrip("/")
    for port in (8188, 8189):
        url = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(f"{url}/system_stats", timeout=1.5) as resp:
                if getattr(resp, "status", 200) != 200:
                    continue
                raw = resp.read(2048)
                text = raw.decode("utf-8", errors="replace").lstrip()
                if not text.startswith("{"):
                    continue
                data = json.loads(text)
                if isinstance(data, dict) and ("system" in data or "devices" in data):
                    return url
        except Exception:
            continue
    return "http://127.0.0.1:8188"


COMFY_URL = _detect_comfy_url()
COMFY_OUT = Path(os.environ.get("COMFY_OUTPUT", r"D:\ComfyUI\output"))
METRICS_FILE = Path(r"D:\HermesData\state\comfy-pipeline-metrics.json")


def merge_metrics(update: dict[str, Any]) -> None:
    prior: dict[str, Any] = {}
    if METRICS_FILE.is_file():
        try:
            raw = json.loads(METRICS_FILE.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                prior = raw
        except Exception:
            pass
    prior.update(update)
    write_metrics(prior)


def api_get(path: str, *, timeout: float = 10.0) -> dict[str, Any]:
    with urllib.request.urlopen(f"{COMFY_URL}{path}", timeout=timeout) as resp:
        return json.loads(resp.read())


def api_post(path: str, data: dict | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        f"{COMFY_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def comfy_up(*, timeout: float = 3.0) -> bool:
    try:
        api_get("/system_stats", timeout=timeout)
        return True
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False


def queue_prompt(workflow: dict) -> str:
    resp = api_post("/prompt", {"prompt": workflow})
    return str(resp["prompt_id"])


def queue_status() -> dict[str, Any]:
    try:
        return api_get("/queue")
    except Exception as exc:
        return {"error": str(exc)}


def interrupt_render() -> bool:
    """Stop the currently running Comfy job (POST required)."""
    try:
        api_post("/interrupt", {})
        return True
    except Exception:
        return False


def clear_queue() -> bool:
    """Drain pending queue jobs before a new batch (prevents cross-run contamination)."""
    interrupt_render()
    try:
        api_post("/queue", {"clear": True})
        return True
    except Exception:
        return False


def history_for(prompt_id: str) -> dict[str, Any] | None:
    try:
        hist = api_get(f"/history/{prompt_id}")
    except Exception:
        return None
    entry = hist.get(prompt_id) if isinstance(hist, dict) else None
    if isinstance(entry, dict) and entry.get("outputs"):
        return entry
    return None


def wait_for_prompt(
    prompt_id: str,
    *,
    timeout: float = 900.0,
    poll_sec: float = 1.0,
    since_ts: float | None = None,
) -> dict[str, Any]:
    started = since_ts or time.time()
    deadline = started + timeout
    while time.time() < deadline:
        entry = history_for(prompt_id)
        if entry:
            return entry
        time.sleep(poll_sec)
    recovered = recover_recent_output(since_ts=started)
    if recovered:
        return {"outputs": {"_recovered_": {"images": [recovered]}}, "recovered": True}
    raise TimeoutError(f"Prompt {prompt_id} did not complete in {timeout:.0f}s")


def wait_for_prompts(
    prompt_ids: list[str],
    *,
    timeout: float = 3600.0,
    poll_sec: float = 1.5,
    since_ts: float | None = None,
    on_complete: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, dict[str, Any]]:
    started = since_ts or time.time()
    pending = {pid: pid for pid in prompt_ids}
    results: dict[str, dict[str, Any]] = {}
    deadline = started + timeout
    while pending and time.time() < deadline:
        done: list[str] = []
        for pid in list(pending):
            entry = history_for(pid)
            if entry:
                results[pid] = entry
                done.append(pid)
        for pid in done:
            pending.pop(pid, None)
            if on_complete is not None:
                on_complete(pid, results[pid])
        if pending:
            time.sleep(poll_sec)
    if pending:
        raise TimeoutError(f"Timed out waiting for {len(pending)} prompt(s): {list(pending)[:3]}")
    return results


def recover_recent_output(
    *,
    since_ts: float,
    min_bytes: int = 800_000,
    pattern: str = "standard__*.png",
) -> dict[str, str] | None:
    best_path: Path | None = None
    best_mtime = 0.0
    globs = [pattern]
    if pattern == "standard__*.png":
        globs.append("regional__*.png")
    paths: list[Path] = []
    for pat in globs:
        paths.extend(COMFY_OUT.glob(pat))
    for path in paths:
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_mtime < since_ts - 2.0 or st.st_size < min_bytes:
            continue
        if st.st_mtime > best_mtime:
            best_mtime = st.st_mtime
            best_path = path
    if best_path and best_path.is_file():
        return {"filename": best_path.name, "subfolder": ""}
    return None


def extract_image_info(outputs: dict[str, Any]) -> dict[str, str] | None:
    for node_output in (outputs.get("outputs") or outputs).values():
        if not isinstance(node_output, dict):
            continue
        images = node_output.get("images")
        if not images:
            continue
        for img in images:
            if isinstance(img, dict) and img.get("filename"):
                return {"filename": str(img["filename"]), "subfolder": str(img.get("subfolder") or "")}
    return None


def image_path_from_info(info: dict[str, str]) -> Path:
    sub = info.get("subfolder") or ""
    name = info["filename"]
    if sub:
        return COMFY_OUT / sub / name
    return COMFY_OUT / name


def write_metrics(payload: dict[str, Any]) -> None:
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    METRICS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")