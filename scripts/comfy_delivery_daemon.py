#!/usr/bin/env python3
"""Poll Comfy output and auto-post new PNGs to the Alice roleplay Discord thread."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from windows_subprocess import prefer_pythonw, run_hidden  # noqa: E402

COMFY_OUTPUT = Path(r"D:\ComfyUI\output")
STATE_FILE = Path(r"D:\HermesData\state\comfy-delivery-daemon.json")
POSTED_REGISTRY = Path(r"D:\HermesData\state\comfy-discord-posted.json")
BATCH_SESSION_FILE = Path(r"D:\HermesData\state\comfy-batch-session.json")
LOCK_FILE = Path(r"D:\HermesData\state\comfy-delivery-daemon.lock")
TICK_LOCK_FILE = Path(r"D:\HermesData\state\comfy-delivery-tick.lock")
DEFAULT_CHANNEL = "1521146755985576116"
POST_SCRIPT = SCRIPTS.parent / "temp" / "post_discord_image.py"
POLL_SEC = 3
MAX_LEDGER = 200
HERMES_GATEWAY_MARKER = "hermes-gateway"


def _hermes_grace_sec() -> float:
    if _load_batch_session().get("active"):
        return float(os.environ.get("COMFY_BATCH_DELIVERY_GRACE_SEC", "8"))
    return float(os.environ.get("HERMES_COMFY_DELIVERY_GRACE_SEC", "90"))


def _registry_entry(name: str) -> dict:
    reg = _load_posted_registry()
    entry = (reg.get("names") or {}).get(name)
    return entry if isinstance(entry, dict) else {}


def _discord_id(name: str) -> str:
    return str(_registry_entry(name).get("discord_id") or "").strip()


def _hermes_delivered(name: str, digest: str) -> bool:
    """True when Hermes gateway or any poster already delivered this PNG."""
    reg = _load_posted_registry()
    if digest and digest in (reg.get("sha256") or []):
        entry = _registry_entry(name)
        did = str(entry.get("discord_id") or "")
        if did.isdigit() and len(did) > 10:
            return True
        if did == HERMES_GATEWAY_MARKER:
            return True
    did = _discord_id(name)
    if did.isdigit() and len(did) > 10:
        return True
    return did == HERMES_GATEWAY_MARKER


def _ready_for_daemon_delivery(name: str, digest: str, mtime: float) -> bool:
    """Daemon posts only after Hermes grace expires without a gateway delivery."""
    if _hermes_delivered(name, digest):
        return False
    age = max(0.0, time.time() - float(mtime or 0))
    return age >= _hermes_grace_sec()


def _default_state() -> dict:
    return {"last_name": "", "last_mtime": 0.0, "delivered": [], "delivered_sha256": []}


def _load_state() -> dict:
    if not STATE_FILE.is_file():
        return _default_state()
    for path in (STATE_FILE, STATE_FILE.with_suffix(".json.bak")):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return _default_state()


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    if STATE_FILE.is_file():
        backup = STATE_FILE.with_suffix(".json.bak")
        try:
            backup.write_text(STATE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass
    tmp.replace(STATE_FILE)


def _load_posted_registry() -> dict:
    if not POSTED_REGISTRY.is_file():
        return {"sha256": [], "names": {}}
    try:
        data = json.loads(POSTED_REGISTRY.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            data.setdefault("sha256", [])
            data.setdefault("names", {})
            return data
    except Exception:
        pass
    return {"sha256": [], "names": {}}


def _save_posted_registry(reg: dict) -> None:
    POSTED_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    reg["sha256"] = list(reg.get("sha256") or [])[-MAX_LEDGER:]
    names = dict(reg.get("names") or {})
    if len(names) > MAX_LEDGER:
        keep = sorted(names.items(), key=lambda kv: kv[1].get("at", ""))[-MAX_LEDGER:]
        names = dict(keep)
    reg["names"] = names
    POSTED_REGISTRY.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def _posted_to_discord(name: str, digest: str) -> bool:
    return _hermes_delivered(name, digest)


def _record_discord_post(name: str, digest: str, discord_id: str) -> None:
    reg = _load_posted_registry()
    sha = list(reg.get("sha256") or [])
    if digest and digest not in sha:
        sha.append(digest)
    reg["sha256"] = sha
    names = dict(reg.get("names") or {})
    names[name] = {
        "sha256": digest,
        "discord_id": discord_id,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    reg["names"] = names
    _save_posted_registry(reg)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_batch_session() -> dict:
    if not BATCH_SESSION_FILE.is_file():
        return {}
    try:
        data = json.loads(BATCH_SESSION_FILE.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_batch_session(session: dict) -> None:
    BATCH_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    BATCH_SESSION_FILE.write_text(json.dumps(session, indent=2), encoding="utf-8")


def _png_series_index(png_name: str, session: dict) -> int | None:
    m = re.match(r"standard__(\d+)_\.png$", png_name)
    if not m:
        return None
    num = int(m.group(1))
    start = int(session.get("series_start_png") or 0)
    if start > 0:
        return num - start + 1
    return None


def _batch_caption(png_name: str) -> str | None:
    session = _load_batch_session()
    if not session.get("active"):
        return None
    total = int(session.get("total") or 7)
    labels = list(session.get("labels") or [])
    series = str(session.get("series") or "Kitchen crawl").strip()
    index = _png_series_index(png_name, session)
    if index is None or index < 1 or index > total:
        posted = int(session.get("delivered_count") or 0) + 1
        index = min(posted, total)
    label = labels[index - 1] if index - 1 < len(labels) else ""
    if label:
        return f"{series} {index}/{total} — {label} — {png_name}"
    return f"{series} {index}/{total} — {png_name}"


def _sync_batch_delivered_count(png_name: str) -> None:
    session = _load_batch_session()
    if not session.get("active"):
        return
    index = _png_series_index(png_name, session)
    if index is None:
        return
    session["delivered_count"] = max(int(session.get("delivered_count") or 0), index)
    total = int(session.get("total") or 7)
    if session["delivered_count"] >= total:
        session["active"] = False
        session["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_batch_session(session)


def _deliver(channel: str, png_name: str, *, caption: str | None = None) -> tuple[bool, str]:
    png_path = COMFY_OUTPUT / png_name
    if not png_path.is_file():
        return False, ""
    try:
        mtime = png_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    digest = _sha256_file(png_path)
    if _posted_to_discord(png_name, digest):
        return False, "already_posted"
    if not _ready_for_daemon_delivery(png_name, digest, mtime):
        return False, "hermes_pending"
    text = caption or _batch_caption(png_name) or f"Auto-deliver: {png_name}"
    proc = run_hidden(
        [prefer_pythonw(sys.executable), str(POST_SCRIPT), channel, str(png_path), text],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "")[:200]
    discord_id = ""
    out = (proc.stdout or "").strip()
    if out.startswith("{"):
        try:
            payload = json.loads(out)
            if not payload.get("ok"):
                return False, out[:200]
            discord_id = str(payload.get("id") or "")
        except json.JSONDecodeError:
            pass
    if not discord_id:
        return False, "no_discord_id"
    _record_discord_post(png_name, digest, discord_id)
    _sync_batch_delivered_count(png_name)
    return True, discord_id


def _already_delivered(state: dict, name: str, digest: str) -> bool:
    delivered = list(state.get("delivered") or [])
    delivered_sha = list(state.get("delivered_sha256") or [])
    if _hermes_delivered(name, digest):
        return True
    return name in delivered or bool(digest and digest in delivered_sha)


def _mark_delivered(state: dict, name: str, mtime: float, digest: str = "") -> None:
    delivered = list(state.get("delivered") or [])
    delivered_sha = list(state.get("delivered_sha256") or [])
    if name not in delivered:
        delivered.append(name)
    if digest and digest not in delivered_sha:
        delivered_sha.append(digest)
    state["delivered"] = delivered[-MAX_LEDGER:]
    state["delivered_sha256"] = delivered_sha[-MAX_LEDGER:]
    state["last_name"] = name
    state["last_mtime"] = mtime
    _save_state(state)


def _seal_existing_pngs(state: dict) -> dict:
    delivered = list(state.get("delivered") or [])
    delivered_sha = list(state.get("delivered_sha256") or [])
    last_name = state.get("last_name") or ""
    last_mtime = float(state.get("last_mtime") or 0)
    cursor_mtime = last_mtime
    seal_all = cursor_mtime <= 0
    for path in sorted(COMFY_OUTPUT.glob("standard__*.png"), key=lambda p: p.stat().st_mtime):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if not seal_all and mtime > cursor_mtime:
            continue
        digest = _sha256_file(path)
        if path.name not in delivered:
            delivered.append(path.name)
        if digest and digest not in delivered_sha:
            delivered_sha.append(digest)
        if mtime >= last_mtime:
            last_name = path.name
            last_mtime = mtime
    state["delivered"] = delivered[-MAX_LEDGER:]
    state["delivered_sha256"] = delivered_sha[-MAX_LEDGER:]
    state["last_name"] = last_name
    state["last_mtime"] = last_mtime
    _save_state(state)
    return state


def bootstrap_state() -> dict:
    state = _load_state()
    if float(state.get("last_mtime") or 0) > 0:
        return state
    return _seal_existing_pngs(state)


def _undelivered_pngs(state: dict) -> list[tuple[str, float, str]]:
    cursor_mtime = float(state.get("last_mtime") or 0)
    pending: list[tuple[str, float, str]] = []
    for path in sorted(COMFY_OUTPUT.glob("standard__*.png"), key=lambda p: p.stat().st_mtime):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        digest = _sha256_file(path)
        if _already_delivered(state, path.name, digest):
            continue
        if mtime <= cursor_mtime:
            continue
        if not _ready_for_daemon_delivery(path.name, digest, mtime):
            continue
        pending.append((path.name, mtime, digest))
    return pending


def record_hermes_delivery(image_path: str | Path) -> dict:
    path = Path(image_path)
    if path.name.startswith("standard__") and path.suffix.lower() == ".png":
        png_path = path if path.is_file() else COMFY_OUTPUT / path.name
    else:
        png_path = path
    if not png_path.is_file():
        return {"ok": False, "reason": "missing", "png": path.name}
    try:
        mtime = png_path.stat().st_mtime
    except OSError as exc:
        return {"ok": False, "reason": str(exc), "png": png_path.name}
    digest = _sha256_file(png_path)
    state = _load_state()
    _mark_delivered(state, png_path.name, mtime, digest)
    reg = _load_posted_registry()
    sha = list(reg.get("sha256") or [])
    if digest and digest not in sha:
        sha.append(digest)
    reg["sha256"] = sha
    names = dict(reg.get("names") or {})
    names[png_path.name] = {
        "sha256": digest,
        "discord_id": HERMES_GATEWAY_MARKER,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    reg["names"] = names
    _save_posted_registry(reg)
    return {"ok": True, "action": "record_hermes", "png": png_path.name}


def seal_png_path(image_path: str | Path) -> dict:
    path = Path(image_path)
    if path.name.startswith("standard__") and path.suffix.lower() == ".png":
        png_path = path if path.is_file() else COMFY_OUTPUT / path.name
    else:
        png_path = path
    if not png_path.is_file():
        return {"ok": False, "reason": "missing", "png": path.name}
    try:
        mtime = png_path.stat().st_mtime
    except OSError as exc:
        return {"ok": False, "reason": str(exc), "png": png_path.name}
    digest = _sha256_file(png_path)
    state = _load_state()
    _mark_delivered(state, png_path.name, mtime, digest)
    reg = _load_posted_registry()
    sha = list(reg.get("sha256") or [])
    if digest and digest not in sha:
        sha.append(digest)
    reg["sha256"] = sha
    names = dict(reg.get("names") or {})
    names[png_path.name] = {
        "sha256": digest,
        "discord_id": "gateway-sealed",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    reg["names"] = names
    _save_posted_registry(reg)
    return {"ok": True, "action": "seal", "png": png_path.name}


class _TickLock:
    def __enter__(self):
        TICK_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + 2
        while time.time() < deadline:
            try:
                self._fd = TICK_LOCK_FILE.open("x", encoding="utf-8")
                self._fd.write(str(os.getpid()))
                self._fd.close()
                return self
            except FileExistsError:
                try:
                    raw = TICK_LOCK_FILE.read_text(encoding="utf-8").strip()
                    ts = TICK_LOCK_FILE.stat().st_mtime
                except OSError:
                    ts = 0
                if ts and time.time() - ts > 120:
                    TICK_LOCK_FILE.unlink(missing_ok=True)
                time.sleep(0.1)
        raise TimeoutError("tick_lock_busy")

    def __exit__(self, *exc):
        TICK_LOCK_FILE.unlink(missing_ok=True)


def tick(channel: str = DEFAULT_CHANNEL) -> dict:
    try:
        with _TickLock():
            return _tick_locked(channel)
    except TimeoutError:
        return {"action": "none", "reason": "tick_lock_busy"}


def _tick_locked(channel: str) -> dict:
    state = _load_state()
    pending = _undelivered_pngs(state)
    if not pending:
        waiting = 0
        cursor_mtime = float(state.get("last_mtime") or 0)
        for path in COMFY_OUTPUT.glob("standard__*.png"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime <= cursor_mtime:
                continue
            digest = _sha256_file(path)
            if _already_delivered(state, path.name, digest):
                continue
            if not _ready_for_daemon_delivery(path.name, digest, mtime):
                waiting += 1
        if waiting:
            return {"action": "none", "reason": "hermes_pending", "waiting": waiting}
        return {"action": "none", "reason": "no_pending"}
    delivered = list(state.get("delivered") or [])
    delivered_sha = list(state.get("delivered_sha256") or [])
    posted: list[str] = []
    last_name = state.get("last_name")
    last_mtime = float(state.get("last_mtime") or 0)
    for name, mtime, digest in pending:
        ok, detail = _deliver(channel, name)
        if not ok:
            if detail == "already_posted":
                _mark_delivered(state, name, mtime, digest)
                last_name = name
                last_mtime = max(last_mtime, mtime)
                continue
            if detail == "hermes_pending":
                continue
            return {"action": "deliver", "ok": False, "png": name, "posted": posted, "error": detail}
        delivered.append(name)
        if digest:
            delivered_sha.append(digest)
        posted.append(name)
        last_name = name
        last_mtime = mtime
    state["delivered"] = delivered[-MAX_LEDGER:]
    state["delivered_sha256"] = delivered_sha[-MAX_LEDGER:]
    state["last_name"] = last_name
    state["last_mtime"] = last_mtime
    _save_state(state)
    if not posted:
        return {"action": "none", "reason": "hermes_pending"}
    return {"action": "deliver", "ok": True, "png": posted[-1] if posted else "", "posted": posted, "count": len(posted)}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Comfy output delivery daemon")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--daemon", action="store_true", help="Run poll loop (default when no --once)")
    parser.add_argument("--seal", metavar="PNG", help="Reserve PNG for Hermes gateway delivery (pre-post)")
    parser.add_argument(
        "--record-hermes",
        metavar="PNG",
        help="Record successful Hermes gateway delivery (blocks daemon repost)",
    )
    parser.add_argument("--interval", type=int, default=POLL_SEC)
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    args = parser.parse_args()
    if args.seal:
        print(json.dumps(seal_png_path(args.seal)))
        return 0
    if args.record_hermes:
        print(json.dumps(record_hermes_delivery(args.record_hermes)))
        return 0
    if args.once:
        print(json.dumps(tick(args.channel)))
        return 0
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = LOCK_FILE.open("x", encoding="utf-8")
        lock_fd.write(str(os.getpid()))
        lock_fd.close()
    except FileExistsError:
        try:
            pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
            if pid and not os.path.exists(f"/proc/{pid}") and os.name == "nt":
                import ctypes

                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                alive = bool(handle)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                if not alive:
                    LOCK_FILE.unlink(missing_ok=True)
                    lock_fd = LOCK_FILE.open("x", encoding="utf-8")
                    lock_fd.write(str(os.getpid()))
                    lock_fd.close()
                else:
                    print(json.dumps({"error": "daemon_already_running", "pid": pid}))
                    return 0
            else:
                print(json.dumps({"error": "daemon_already_running"}))
                return 0
        except Exception:
            print(json.dumps({"error": "daemon_already_running"}))
            return 0
    bootstrap_state()
    while True:
        try:
            result = tick(args.channel)
            if result.get("action") == "deliver":
                print(json.dumps(result), flush=True)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), flush=True)
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())