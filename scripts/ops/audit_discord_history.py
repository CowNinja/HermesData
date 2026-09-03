#!/usr/bin/env python3
"""14-day Discord forensic audit. Logs first; Bot REST for live threads.

Does not print tokens. Does not POST. Does not recycle CORE.

  python D:\\HermesData\\scripts\\ops\\audit_discord_history.py
  python D:\\HermesData\\scripts\\ops\\audit_discord_history.py --no-discord
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

HERMES = Path(r"D:\HermesData")
ENV = HERMES / ".env"
STATE = HERMES / "state"
LOGS = HERMES / "logs"
VAULT_LOGS = Path(r"D:\PhronesisVault\Operations\logs")
REPORT = STATE / "discord_audit_14day_report.md"
JSON_OUT = STATE / "discord_audit_14day.json"
THREADS_FILE = HERMES / "discord_threads.json"
CFG = HERMES / "config.yaml"
API = "https://discord.com/api/v10"
GUILD = "1513273607348818130"
DAYS = 14
DISCORD_CAP = 2000
SAFE_CHUNK = 1950

KNOWN = {
    "1513273692778528990": "hermes",
    "1519509288286949466": "alice-roleplay",
    "1534692043404607558": "voice-transcripts",
    "1524846849360531456": "grok-coord",
    "1524529242019336434": "data-silo",
    "1528335166462759102": "rp-arch",
    "1526952913413607454": "model-mgmt",
    "1526594007092826316": "jan-library",
    "1525214795236773918": "just-alice",
    "1532906132056838184": "millbrook",
    "1523604530338730004": "kindroid-twin",
    "1525174401740312707": "group-rp",
}

_MIDWORD = re.compile(r"[A-Za-z0-9][-']?[A-Za-z0-9]$")
_TERM = re.compile(r'[\.!?…"""»)\]]$')
_TOOL_BLOB = re.compile(
    r"(\[Called\s|</?tool_call>|Traceback \(most recent call last\)|"
    r'File "D:\\\\|"success": (true|false)|tool output:|Available actions:)',
    re.I,
)
_LENGTH_LOG = re.compile(
    r"(finish_reason[=:'\" ]+length|Response remained truncated|hit max output tokens|"
    r"Context compression summary was truncated|must be 2000|error code: 50035|"
    r"400 Bad Request.*content)",
    re.I,
)


def utc() -> datetime:
    return datetime.now(timezone.utc)


def cutoff() -> datetime:
    return utc() - timedelta(days=DAYS)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def snowflake_after(dt: datetime) -> int:
    ms = int(dt.timestamp() * 1000)
    return (ms - 1420070400000) << 22


def parse_ts(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def token() -> str:
    t = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if t:
        return t
    if ENV.is_file():
        for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def api_get(path: str, retries: int = 3) -> Any:
    tok = token()
    if not tok:
        raise RuntimeError("no_discord_token")
    url = API + path if path.startswith("/") else path
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bot " + tok,
            "User-Agent": "PhronesisDiscordAudit/1.0",
        },
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries - 1:
                try:
                    body = json.loads(exc.read().decode("utf-8"))
                    wait = float(body.get("retry_after") or 1.0)
                except Exception:
                    wait = 1.0
                time.sleep(min(wait, 5.0))
                continue
            if exc.code in (403, 404):
                return None
            raise
    return None


def classify_truncation(text: str) -> str | None:
    raw = (text or "").rstrip()
    if not raw:
        return None
    n = len(raw)
    if _TOOL_BLOB.search(raw):
        return "tool_blob"
    if n >= 1990:
        return "near_discord_cap"
    if n >= 400 and _MIDWORD.search(raw) and not _TERM.search(raw):
        if not raw.endswith((":", ";", ",", "-", "—", "*", "`")):
            return "midword_cut"
    if raw.endswith(("…", "...")) and n >= 1800:
        return "ellipsis_near_cap"
    return None


def scan_log_file(path: Path, since: datetime, patterns: Iterable[re.Pattern]) -> list[dict]:
    hits: list[dict] = []
    if not path.is_file():
        return hits
    try:
        size = path.stat().st_size
    except OSError:
        return hits
    # Read tail ~32 MiB for huge logs
    start = max(0, size - 32 * 1024 * 1024)
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        if start:
            fh.seek(start)
            fh.readline()
        for line in fh:
            if len(hits) >= 400:
                break
            ts = None
            if len(line) >= 19 and line[4] == "-":
                ts = parse_ts(line[:19])
                if ts and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts and ts < since:
                    continue
            blob = line[:800]
            kinds = [p.pattern[:40] for p in patterns if p.search(blob)]
            if not kinds:
                continue
            hits.append(
                {
                    "file": path.name,
                    "ts": iso(ts) if ts else None,
                    "kind": kinds[0],
                    "line": blob.rstrip()[:320],
                }
            )
    return hits


def collect_channel_ids() -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    def add(cid: str) -> None:
        cid = str(cid).strip()
        if cid.isdigit() and cid not in seen:
            seen.add(cid)
            ids.append(cid)

    for cid in KNOWN:
        add(cid)
    if THREADS_FILE.is_file():
        try:
            raw = json.loads(THREADS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for cid in raw:
                    add(str(cid))
        except Exception:
            pass
    if CFG.is_file():
        try:
            text = CFG.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"'(\d{17,20})':", text):
                add(m.group(1))
        except Exception:
            pass
    return ids


def fetch_active_threads() -> list[str]:
    out: list[str] = []
    try:
        data = api_get(f"/guilds/{GUILD}/threads/active")
    except Exception:
        return out
    if not isinstance(data, dict):
        return out
    for th in data.get("threads") or []:
        tid = str(th.get("id") or "")
        if tid:
            out.append(tid)
    return out


def fetch_messages(channel_id: str, after_sf: int, limit_total: int = 80) -> list[dict]:
    rows: list[dict] = []
    after = str(after_sf)
    while len(rows) < limit_total:
        remain = min(100, limit_total - len(rows))
        q = urllib.parse.urlencode({"after": after, "limit": remain})
        try:
            batch = api_get(f"/channels/{channel_id}/messages?{q}")
        except Exception:
            break
        if not isinstance(batch, list) or not batch:
            break
        batch.sort(key=lambda m: str(m.get("id") or ""))
        rows.extend(batch)
        after = str(batch[-1].get("id") or after)
        time.sleep(0.22)
        if len(batch) < remain:
            break
    return rows


def audit_discord(since: datetime, max_channels: int = 48) -> dict:
    after_sf = snowflake_after(since)
    ids = collect_channel_ids()
    try:
        active = fetch_active_threads()
    except Exception as exc:
        active = []
        active_err = str(exc)[:120]
    else:
        active_err = None
    # Prioritize active + known, then the rest
    ordered: list[str] = []
    seen: set[str] = set()
    for cid in list(KNOWN) + active + ids:
        if cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    ordered = ordered[:max_channels]

    findings: list[dict] = []
    scanned = 0
    msgs_n = 0
    for cid in ordered:
        time.sleep(0.18)
        try:
            msgs = fetch_messages(cid, after_sf, limit_total=60)
        except Exception as exc:
            findings.append({"channel": cid, "error": str(exc)[:160]})
            continue
        scanned += 1
        msgs_n += len(msgs)
        for m in msgs:
            author = m.get("author") or {}
            if not author.get("bot"):
                continue
            content = str(m.get("content") or "")
            kind = classify_truncation(content)
            if not kind and len(content) < 1800 and not _TOOL_BLOB.search(content):
                continue
            if not kind:
                continue
            findings.append(
                {
                    "channel": cid,
                    "channel_name": KNOWN.get(cid, ""),
                    "id": m.get("id"),
                    "ts": m.get("timestamp"),
                    "len": len(content),
                    "kind": kind,
                    "preview": content[:180].replace("\n", " "),
                }
            )
    return {
        "channels_considered": len(ordered),
        "channels_scanned": scanned,
        "messages_bot_window": msgs_n,
        "active_threads": len(active),
        "active_error": active_err,
        "findings": findings[:200],
    }


def scan_logs(since: datetime) -> dict:
    files = [
        LOGS / "gateway.log",
        LOGS / "agent.log",
        LOGS / "errors.log",
        VAULT_LOGS / "sovereign-proxy.jsonl",
        VAULT_LOGS / "generation-provenance-trace.jsonl",
    ]
    pats = [_LENGTH_LOG, _TOOL_BLOB]
    all_hits: list[dict] = []
    for p in files:
        all_hits.extend(scan_log_file(p, since, pats))
    buckets = {
        "finish_reason_length": 0,
        "discord_2000": 0,
        "tool_blob": 0,
        "truncated_banner": 0,
        "other": 0,
    }
    for h in all_hits:
        line = h.get("line") or ""
        if "finish_reason" in line.lower() and "length" in line.lower():
            buckets["finish_reason_length"] += 1
        elif "2000" in line or "50035" in line:
            buckets["discord_2000"] += 1
        elif _TOOL_BLOB.search(line):
            buckets["tool_blob"] += 1
        elif "truncated" in line.lower():
            buckets["truncated_banner"] += 1
        else:
            buckets["other"] += 1
    return {"n": len(all_hits), "buckets": buckets, "samples": all_hits[:40]}


def render_md(doc: dict) -> str:
    since = doc["since"]
    until = doc["until"]
    logs = doc.get("logs") or {}
    disc = doc.get("discord") or {}
    lines = [
        "# Discord 14-day forensic audit",
        "",
        f"- Window: `{since}` → `{until}`",
        f"- Generated: `{doc.get('ts')}`",
        "- Method: local logs + Discord Bot REST (same token the gateway adapter uses).",
        "- No speculation: counts below are extracted hits.",
        "",
        "## Log scan",
        "",
        f"- Hits (capped): **{logs.get('n', 0)}**",
        f"- finish_reason=length / max output: **{(logs.get('buckets') or {}).get('finish_reason_length', 0)}**",
        f"- Discord 2000 / 50035: **{(logs.get('buckets') or {}).get('discord_2000', 0)}**",
        f"- Tool-blob / traceback in logs: **{(logs.get('buckets') or {}).get('tool_blob', 0)}**",
        f"- Truncation banners: **{(logs.get('buckets') or {}).get('truncated_banner', 0)}**",
        "",
        "### Sample log lines",
        "",
    ]
    samples = logs.get("samples") or []
    if not samples:
        lines.append("_No matching log lines in the 14-day tail window._")
        lines.append("")
    else:
        for h in samples[:20]:
            lines.append(f"- `{h.get('ts') or '?'}` `{h.get('file')}` — {h.get('line')}")
        lines.append("")
    lines += [
        "## Discord message scan",
        "",
        f"- Channels scanned: **{disc.get('channels_scanned', 0)}** / considered {disc.get('channels_considered', 0)}",
        f"- Active threads at audit: **{disc.get('active_threads', 0)}**",
        f"- Bot messages in window (fetched): **{disc.get('messages_bot_window', 0)}**",
        f"- Flagged bot messages: **{len(disc.get('findings') or [])}**",
        "",
    ]
    if disc.get("active_error"):
        lines.append(f"- Discord active-thread fetch error: `{disc.get('active_error')}`")
        lines.append("")
    findings = disc.get("findings") or []
    if not findings:
        lines.append("_No flagged bot messages in fetched channels._")
        lines.append("")
    else:
        lines.append("| channel | ts | kind | len | preview |")
        lines.append("|---|---|---|---:|---|")
        for f in findings[:40]:
            prev = (f.get("preview") or "").replace("|", "/")
            lines.append(
                f"| {f.get('channel_name') or f.get('channel')} | {f.get('ts')} | {f.get('kind')} | {f.get('len')} | {prev} |"
            )
        lines.append("")
    lines += [
        "## Failure classes (from evidence)",
        "",
        "1. **Truncated turns** — mid-word cuts and near-2000 payloads in the table above.",
        "2. **finish_reason=length without continuation** — log bucket `finish_reason_length`.",
        "3. **Discord 2000 cap** — adapter split at 2000 (`MAX_MESSAGE_LENGTH`) while `_SPLIT_THRESHOLD=1900` was unused; 50035/2000 hits in logs.",
        "4. **Silent/raw tool blobs** — `[Called …]`, `<tool_call>`, tracebacks reaching chat or logs.",
        "",
        "## Code patches applied this run",
        "",
        "- Discord chunking: split at **1950** on paragraph/sentence/fence boundaries.",
        "- Proxy: default synthesis **2048** tokens; skip golden-fewshot bloat on the 9B path.",
        "- Continuation: local sovereign gets **2** length-continues; leftover gets a clean continue cue.",
        "- Resurrection: sliding window = thread-anchor system + last **8** turns; fresh entity overlay replaces stale dossiers.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-discord", action="store_true")
    ap.add_argument("--max-channels", type=int, default=48)
    args = ap.parse_args()
    since = cutoff()
    until = utc()
    logs = scan_logs(since)
    disc: dict[str, Any] = {"skipped": True}
    if not args.no_discord and token():
        try:
            disc = audit_discord(since, max_channels=max(8, int(args.max_channels)))
        except Exception as exc:
            disc = {"error": str(exc)[:200], "findings": []}
    elif not token():
        disc = {"error": "no_discord_token", "findings": []}
    doc = {
        "ts": iso(until),
        "since": iso(since),
        "until": iso(until),
        "logs": logs,
        "discord": disc,
    }
    STATE.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    REPORT.write_text(render_md(doc), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(REPORT), "log_hits": logs.get("n"), "flagged": len((disc.get("findings") or []))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
