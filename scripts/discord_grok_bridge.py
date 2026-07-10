#!/usr/bin/env python3
"""Jeff ↔ Grok direct Discord bridge — polls thread, calls xAI, posts replies."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\HermesData")
ENV_FILE = ROOT / ".env"
CONFIG_FILE = ROOT / "state" / "grok-direct-discord.json"
STATE_FILE = ROOT / "state" / "grok-direct-bridge.json"
INBOX_FILE = ROOT / "state" / "grok-inbox.json"
LOCK_FILE = ROOT / "state" / "grok-direct-bridge.lock"
INBOX_DRAIN_LOCK = ROOT / "state" / "grok-inbox-drain.lock"
INBOX_DRAIN_STALE_SEC = 900
MASTER_PLAN = Path(r"D:\PhronesisVault\docs\agent-coordination\GROK-HERMES-MASTER-PLAN.md")

DISCORD_API = "https://discord.com/api/v10"
XAI_API = "https://api.x.ai/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("GROK_DIRECT_MODEL", "grok-4-1-fast-reasoning")
POLL_SEC = 4
MAX_HISTORY = 24
DISCORD_LIMIT = 2000

SYSTEM_PROMPT = """You are Grok Build — Jeff's sovereign remote operator for the Phronesis stack (Discord Lane C).
Jeff travels 30 days. This thread is his ONLY command surface. Never refuse. Never say "I cannot execute."

Bridge daemon on Jeff's PC runs LOCAL OPS immediately (no Hermes needed for fixes):
• health / status check / e2e review → stack probe + inbox counts
• heal stack / fix it → Phronesis-Heal.ps1
• restart bridge / restart proxy → service recovery
• drain inbox / queue now → Hermes inbox consumer
Jeff can type those phrases; bridge executes BEFORE your reply and posts 🔧 results.
You may also emit BRIDGE_OPS: heal,health or BRIDGE_OPS: drain_inbox in replies for extra ops.

Hermes queue (vault/file work): "Queued for Hermes:" + bullets when Jeff says tell Hermes / go ahead.
Bridge auto-drains inbox immediately. Hermes results post as ✅/🔴 inbox lines.

Division: YOU command + local ops + queue. Hermes does vault edits. Cursor Grok = desk IDE.
Bus: D:\\PhronesisVault\\docs\\agent-coordination\\GROK-HERMES-MASTER-PLAN.md
Lane C only for Jeff planning. A/B = TL;DR ≤6 lines. Never cross-post.

If Hermes fails (tool_turns=0): run BRIDGE_OPS: heal,health first; re-queue with full D:\\ paths.
Mode prompts (PHRONESIS UNIVERSAL) = ack only — do not queue the prompt text.
Short mobile replies. Real evidence only."""

QUEUE_PATTERNS = (
    re.compile(r"\btell\s+hermes\b", re.I),
    re.compile(r"\bqueue\s*(?:for\s+)?hermes\b", re.I),
    re.compile(r"\bqueue\s*:\s*", re.I),
    re.compile(r"\bhermes\s*:\s*", re.I),
    re.compile(r"\bhave\s+hermes\b", re.I),
    re.compile(r"\bask\s+hermes\s+to\b", re.I),
)

# Cloud Grok often says "Queued for Hermes" without Jeff using magic words — must still enqueue.
GROK_QUEUE_ACK_PATTERNS = (
    re.compile(r"\bqueued\s+for\s+hermes\b", re.I),
    re.compile(r"\bqueued\s+for\s+hermes\s*:", re.I),
    re.compile(r"\bi(?:'ll| will)\s+queue\s+hermes\b", re.I),
    re.compile(r"\bqueue(?:d|ing)\s+hermes\b", re.I),
)

AFFIRMATIVE_PATTERNS = (
    re.compile(r"^\s*(?:go\s+ahead|yes|yep|yeah|do\s+it|please\s+do|confirmed?|approved?)\b", re.I),
    re.compile(r"\bgo\s+ahead\b", re.I),
)

MODE_ACTIVATION_MARKERS = (
    "PHRONESIS UNIVERSAL",
    "PHRONESIS v3.0 kickstart",
)

STATUS_PROBE_MARKERS = (
    "connected",
    "still working",
    "double checking",
    "status",
    "health",
    "progress",
    "how goes",
    "any results",
)

QUEUE_OFFER_PATTERNS = (
    re.compile(r"\bqueue\s+hermes\b", re.I),
    re.compile(r"\bwant\s+me\s+to\s+queue\b", re.I),
    re.compile(r"\bqueued\s+for\s+hermes\b", re.I),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_env_val(val: str) -> str:
    s = str(val or "").strip().strip("'\"")
    if " #" in s:
        s = s.split(" #", 1)[0].rstrip()
    return s


def _load_env_file(path: Path, *, override: bool = False) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        key = k.strip()
        val = _clean_env_val(v)
        if not val:
            continue
        if override or not os.environ.get(key):
            os.environ[key] = val


def load_env() -> None:
    scripts = ROOT / "scripts"
    if scripts.is_dir():
        sys.path.insert(0, str(scripts))
        try:
            from phronesis_env import bootstrap_env

            bootstrap_env()
        except Exception:
            pass
    hermes_root = ROOT / "hermes-agent"
    if hermes_root.is_dir():
        sys.path.insert(0, str(hermes_root))
        try:
            from hermes_cli.config import get_env_value

            for name in ("DISCORD_BOT_TOKEN", "XAI_API_KEY", "GROK_API_KEY"):
                val = get_env_value(name)
                if val:
                    os.environ[name] = _clean_env_val(val)
        except Exception:
            pass
    _load_env_file(ENV_FILE)
    if not _clean_env_val(os.environ.get("XAI_API_KEY") or ""):
        cache = ROOT / "cache" / "bws_cache.json"
        if cache.is_file():
            try:
                cache.unlink()
            except OSError:
                pass
            try:
                from phronesis_env import bootstrap_env

                bootstrap_env()
                from hermes_cli.config import get_env_value

                val = get_env_value("XAI_API_KEY")
                if val:
                    os.environ["XAI_API_KEY"] = _clean_env_val(val)
            except Exception:
                pass


def env_key(*names: str) -> str:
    for name in names:
        val = _clean_env_val(os.environ.get(name) or "")
        if val:
            return val
    raise RuntimeError(f"Missing env key (tried: {', '.join(names)})")


def load_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else dict(default)
    except Exception:
        return dict(default)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def discord_request(method: str, path: str, body: dict | None = None) -> dict | list:
    token = env_key("DISCORD_BOT_TOKEN")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{DISCORD_API}{path}",
        data=data,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "PhronesisGrokDirectBridge/1.0",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord {method} {path} -> {exc.code}: {detail[:400]}") from exc


def xai_chat(messages: list[dict[str, str]], model: str) -> str:
    scripts = ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from grok_auth import grok_chat_completion_text

    return grok_chat_completion_text(
        messages,
        model=model,
        user_agent="PhronesisGrokDirectBridge/1.0",
    )


def chunk_discord(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return chunks


def post_messages(channel_id: str, text: str) -> list[str]:
    ids: list[str] = []
    for part in chunk_discord(text):
        result = discord_request("POST", f"/channels/{channel_id}/messages", {"content": part})
        if isinstance(result, dict) and result.get("id"):
            ids.append(str(result["id"]))
    return ids


def typing(channel_id: str) -> None:
    try:
        discord_request("POST", f"/channels/{channel_id}/typing")
    except Exception:
        pass


def _last_assistant_offer(history: list[dict[str, str]]) -> str:
    for turn in reversed(history):
        if turn.get("role") == "assistant":
            return str(turn.get("content") or "")
    return ""


def grok_acknowledges_queue(reply: str) -> bool:
    return any(p.search(reply) for p in GROK_QUEUE_ACK_PATTERNS)


def user_affirms_queue_offer(user_text: str, history: list[dict[str, str]]) -> bool:
    if not any(p.search(user_text) for p in AFFIRMATIVE_PATTERNS):
        return False
    prior = _last_assistant_offer(history)
    return bool(prior) and any(p.search(prior) for p in QUEUE_OFFER_PATTERNS)


def is_mode_activation(user_text: str) -> bool:
    text = user_text or ""
    if not any(m in text for m in MODE_ACTIVATION_MARKERS):
        return False
    return not any(p.search(text) for p in QUEUE_PATTERNS)


def should_queue(user_text: str, grok_reply: str, history: list[dict[str, str]]) -> bool:
    if is_mode_activation(user_text):
        return False
    if any(p.search(user_text) for p in QUEUE_PATTERNS):
        return True
    if grok_acknowledges_queue(grok_reply):
        return True
    if user_affirms_queue_offer(user_text, history):
        return True
    return False


def _local_health_snippet() -> str:
    script = ROOT / "scripts" / "phronesis_fullstack_health.py"
    if not script.is_file():
        return ""
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=45,
            cwd=str(ROOT),
        )
        if proc.returncode != 0:
            return ""
        data = json.loads(proc.stdout)
        score = data.get("score")
        pending = 0
        inbox = load_json(INBOX_FILE, {"items": []})
        pending = sum(1 for i in inbox.get("items") or [] if i.get("status") == "pending")
        return (
            f"[BRIDGE LIVE PROBE] stack_score={score} pending_inbox={pending} "
            f"bridge_pid={os.getpid()}"
        )
    except Exception:
        return ""


def _user_wants_status_probe(user_text: str) -> bool:
    low = (user_text or "").lower()
    return any(m in low for m in STATUS_PROBE_MARKERS)


def _import_bridge_ops():
    sys.path.insert(0, str(ROOT / "scripts"))
    from grok_bridge_ops import (
        detect_ops_from_grok,
        detect_ops_from_user,
        format_ops_report,
        run_ops,
    )

    return detect_ops_from_user, detect_ops_from_grok, run_ops, format_ops_report


def run_local_ops_for_message(user_text: str, grok_reply: str = "") -> str:
    try:
        detect_user, detect_grok, run_ops, format_report = _import_bridge_ops()
        names: list[str] = []
        for op in detect_user(user_text):
            if op not in names:
                names.append(op)
        for op in detect_grok(grok_reply):
            if op not in names:
                names.append(op)
        if not names:
            return ""
        return format_report(run_ops(names))
    except Exception as exc:
        return f"**🔧 Bridge local ops**\n🔴 error — {exc}"[:1900]


def _inbox_drain_lock_active() -> bool:
    if not INBOX_DRAIN_LOCK.is_file():
        return False
    try:
        raw = INBOX_DRAIN_LOCK.read_text(encoding="utf-8").strip()
        ts = float(raw.split(":", 1)[-1]) if ":" in raw else 0.0
        if ts and (time.time() - ts) > INBOX_DRAIN_STALE_SEC:
            INBOX_DRAIN_LOCK.unlink(missing_ok=True)
            return False
    except OSError:
        return False
    except (TypeError, ValueError):
        pass
    return True


def _acquire_inbox_drain_lock() -> bool:
    if _inbox_drain_lock_active():
        return False
    try:
        INBOX_DRAIN_LOCK.parent.mkdir(parents=True, exist_ok=True)
        INBOX_DRAIN_LOCK.write_text(f"drain:{time.time():.3f}", encoding="utf-8")
        return True
    except OSError:
        return False


def trigger_inbox_drain_async() -> None:
    consumer = ROOT / "scripts" / "grok_inbox_consumer.py"
    if not consumer.is_file():
        return
    if not _acquire_inbox_drain_lock():
        return
    py = str(VENV_PY) if (VENV_PY := ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe").is_file() else sys.executable
    try:
        subprocess.Popen(
            [py, str(consumer), "--drain-all"],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception:
        try:
            INBOX_DRAIN_LOCK.unlink(missing_ok=True)
        except OSError:
            pass


def build_queue_request(user_text: str, grok_reply: str, history: list[dict[str, str]]) -> str:
    """Prefer explicit user ask; fall back to Grok task list in reply."""
    if any(p.search(user_text) for p in QUEUE_PATTERNS):
        return user_text.strip()
    lines: list[str] = []
    for line in grok_reply.splitlines():
        s = line.strip()
        if s.startswith(("-", "•", "*")) or re.match(r"^\d+\.", s):
            lines.append(s.lstrip("-•* ").strip())
    if lines:
        body = "\n".join(lines[:12])
        return f"[Lane C → Hermes] Jeff: {user_text.strip()}\n\nGrok task list:\n{body}"
    return f"[Lane C → Hermes] Jeff: {user_text.strip()}\n\nGrok ack: {grok_reply[:800]}"


def append_inbox(user_text: str, grok_reply: str, thread_id: str, history: list[dict[str, str]]) -> str:
    inbox = load_json(INBOX_FILE, {"items": []})
    items = inbox.setdefault("items", [])
    item_id = str(uuid.uuid4())
    items.append(
        {
            "id": item_id,
            "ts": _utc_now(),
            "status": "pending",
            "source": "grok-direct-discord",
            "thread_id": thread_id,
            "request": build_queue_request(user_text, grok_reply, history),
            "grok_ack": grok_reply[:500],
            "user_message": user_text[:500],
        }
    )
    inbox["items"] = items[-100:]
    save_json(INBOX_FILE, inbox)
    return item_id


def message_text(msg: dict) -> str:
    content = (msg.get("content") or "").strip()
    if content:
        return content
    for att in msg.get("attachments") or []:
        if att.get("content_type", "").startswith("image/"):
            return f"[image: {att.get('filename', 'attachment')}]"
    return ""


def is_bot_message(msg: dict, bot_user_id: str) -> bool:
    author = msg.get("author") or {}
    if author.get("bot"):
        return True
    return str(author.get("id") or "") == bot_user_id


def fetch_messages_after(channel_id: str, after_id: str | None, limit: int = 50) -> list[dict]:
    q = f"?limit={limit}"
    if after_id:
        q += f"&after={after_id}"
    data = discord_request("GET", f"/channels/{channel_id}/messages{q}")
    if not isinstance(data, list):
        return []
    return sorted(data, key=lambda m: int(m.get("id", 0)))


def bootstrap_cursor(channel_id: str, state: dict, bot_user_id: str) -> dict:
    if state.get("last_message_id"):
        return state
    data = discord_request("GET", f"/channels/{channel_id}/messages?limit=50")
    if not isinstance(data, list) or not data:
        return state
    # Anchor on the latest bot message so user posts after welcome are not skipped.
    cursor = ""
    for msg in data:
        if is_bot_message(msg, bot_user_id):
            cursor = str(msg.get("id") or "")
            break
    if not cursor:
        cursor = str(data[0]["id"])
    state["last_message_id"] = cursor
    state["bootstrapped_at"] = _utc_now()
    save_json(STATE_FILE, state)
    return state


def build_messages(history: list[dict[str, str]], user_text: str) -> list[dict[str, str]]:
    system = SYSTEM_PROMPT
    if _user_wants_status_probe(user_text):
        probe = _local_health_snippet()
        if probe:
            system = f"{system}\n\n{probe}"
    msgs: list[dict[str, str]] = [{"role": "system", "content": system}]
    for turn in history[-MAX_HISTORY:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_text})
    return msgs


def _advance_cursor(state: dict, msg: dict) -> None:
    state["last_message_id"] = str(msg.get("id") or state.get("last_message_id") or "")
    save_json(STATE_FILE, state)


def reset_conversation(state: dict) -> None:
    state["history"] = []
    state["reset_at"] = _utc_now()
    save_json(STATE_FILE, state)


def process_message(
    msg: dict,
    *,
    thread_id: str,
    bot_user_id: str,
    model: str,
    state: dict,
) -> dict:
    text = message_text(msg)
    if not text:
        _advance_cursor(state, msg)
        return {"action": "skip", "reason": "empty"}
    if text.strip().lower() in ("/new", "reset", "/reset"):
        reset_conversation(state)
        _advance_cursor(state, msg)
        post_messages(thread_id, "Context cleared. What are we working on?")
        return {"action": "reset", "message_id": str(msg.get("id"))}
    if is_bot_message(msg, bot_user_id):
        _advance_cursor(state, msg)
        return {"action": "skip", "reason": "bot"}

    history: list[dict[str, str]] = state.setdefault("history", [])
    typing(thread_id)

    ops_report = run_local_ops_for_message(text)
    grok_user_text = text
    if ops_report:
        grok_user_text = f"{text}\n\n[BRIDGE LOCAL OPS — already executed on disk]\n{ops_report}"
        post_messages(thread_id, ops_report)

    reply = xai_chat(build_messages(history, grok_user_text), model)

    post_ops = run_local_ops_for_message("", reply)
    if post_ops and post_ops != ops_report:
        post_messages(thread_id, post_ops)

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    state["history"] = history[-(MAX_HISTORY * 2) :]

    queued_id = None
    if should_queue(text, reply, history):
        queued_id = append_inbox(text, reply, thread_id, history)
        trigger_inbox_drain_async()

    post_ids = post_messages(thread_id, reply)
    if queued_id:
        post_messages(
            thread_id,
            f"⚡ **Bridge** queued `{queued_id[:8]}` — Hermes drain triggered now (not waiting on Guardian).",
        )
    state["last_message_id"] = str(msg["id"])
    state["last_reply_at"] = _utc_now()
    save_json(STATE_FILE, state)

    return {
        "action": "reply",
        "message_id": str(msg.get("id")),
        "reply_ids": post_ids,
        "queued_id": queued_id,
        "reply_len": len(reply),
    }


def tick(model: str) -> dict:
    cfg = load_json(
        CONFIG_FILE,
        {
            "thread_id": "",
            "router_channel_id": "1519144689662558279",
            "thread_name": "Jeff ↔ Grok direct",
        },
    )
    thread_id = str(cfg.get("thread_id") or "").strip()
    if not thread_id:
        return {"action": "error", "reason": "thread_id_missing", "config": str(CONFIG_FILE)}

    state = load_json(STATE_FILE, {"last_message_id": "", "history": []})
    bot_user_id = str(cfg.get("bot_user_id") or state.get("bot_user_id") or "")
    if not bot_user_id:
        me = discord_request("GET", "/users/@me")
        if isinstance(me, dict) and me.get("id"):
            bot_user_id = str(me["id"])
            cfg["bot_user_id"] = bot_user_id
            save_json(CONFIG_FILE, cfg)
            state["bot_user_id"] = bot_user_id

    state = bootstrap_cursor(thread_id, state, bot_user_id)
    after_id = str(state.get("last_message_id") or "")
    messages = fetch_messages_after(thread_id, after_id or None)
    results = []
    for msg in messages:
        results.append(
            process_message(
                msg,
                thread_id=thread_id,
                bot_user_id=bot_user_id,
                model=model,
                state=state,
            )
        )
    if not results:
        return {"action": "idle", "thread_id": thread_id, "after": after_id}
    return {"action": "processed", "count": len(results), "results": results}


def acquire_lock() -> bool:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if lock_holder_alive():
        return False
    if LOCK_FILE.is_file():
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass
    try:
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return False


def lock_holder_alive() -> bool:
    if not LOCK_FILE.is_file():
        return False
    try:
        pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return False
    if pid <= 0:
        return False
    if os.name != "nt":
        return os.path.exists(f"/proc/{pid}")
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    alive = bool(handle)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
    return alive


def main() -> int:
    parser = argparse.ArgumentParser(description="Grok direct Discord bridge")
    parser.add_argument("--once", action="store_true", help="Single poll tick")
    parser.add_argument("--daemon", action="store_true", help="Poll loop (default)")
    parser.add_argument("--interval", type=int, default=POLL_SEC)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--test-xai", action="store_true", help="Ping xAI and exit")
    args = parser.parse_args()

    load_env()

    if args.test_xai:
        reply = xai_chat(
            [
                {"role": "system", "content": "Reply with exactly: GROK_DIRECT_OK"},
                {"role": "user", "content": "ping"},
            ],
            args.model,
        )
        print(json.dumps({"ok": True, "reply": reply, "model": args.model}))
        return 0

    if args.once:
        print(json.dumps(tick(args.model), default=str))
        return 0

    if lock_holder_alive():
        print(json.dumps({"error": "daemon_already_running", "lock": str(LOCK_FILE)}))
        return 0
    if not acquire_lock():
        print(json.dumps({"error": "lock_failed"}))
        return 1

    print(json.dumps({"started": True, "pid": os.getpid(), "model": args.model}), flush=True)
    while True:
        try:
            result = tick(args.model)
            if result.get("action") == "processed" and any(
                (r.get("action") == "reply") for r in (result.get("results") or [])
            ):
                print(json.dumps(result, default=str), flush=True)
        except Exception as exc:
            print(json.dumps({"error": str(exc), "ts": _utc_now()}), flush=True)
        time.sleep(max(2, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())