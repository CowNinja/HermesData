#!/usr/bin/env python3
"""Grok↔Hermes joint data-silo truth test (2026-07-17).

1) Grok side measures six numbers via silo_discord_six_numbers.py
2) Hermes API session runs the same command via terminal tool
3) Compares numbers; writes vault receipt; optional Discord post

Usage:
  python D:\\HermesData\\scripts\\grok_hermes_joint_silo_test.py
  python D:\\HermesData\\scripts\\grok_hermes_joint_silo_test.py --post-discord
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
ENV = Path(r"D:\HermesData\.env")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\grok-hermes-joint-silo-test-latest.md")
MASTER = Path(r"D:\PhronesisVault\docs\agent-coordination\GROK-HERMES-MASTER-PLAN.md")
SILO_CHANNEL = "1524529242019336434"
GROK_CHANNEL = "1524846849360531456"
API_BASE = "http://127.0.0.1:8642"
SESSION_KEY = "agent:main:api:grok-collab:silo-truth-v2"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV.is_file():
        return out
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def grok_measure() -> dict:
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "silo_discord_six_numbers.py")],
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
        cwd=str(SCRIPTS),
    )
    text = (r.stdout or "") + (r.stderr or "")
    nums: dict[str, int] = {}
    for line in text.splitlines():
        m = re.match(
            r"(\d)\s+(registry_total|unique_hashes|status_copied|status_landed|ocr_ok_text|ocr_open)=(\d+)",
            line.strip(),
        )
        if m:
            nums[m.group(2)] = int(m.group(3))
    if "JSON " in text:
        try:
            j = json.loads(text.split("JSON ", 1)[1].strip().splitlines()[0])
            for k, v in j.items():
                if isinstance(v, int) and k.startswith(("1_", "2_", "3_", "4_", "5_", "6_")):
                    # map 1_registry_total -> registry_total
                    short = k.split("_", 1)[1] if "_" in k else k
                    nums[short] = v
        except Exception:
            pass
    return {"ok": r.returncode == 0, "raw": text[-2000:], "nums": nums}


def hermes_chat(api_key: str, prompt: str, timeout: int = 300) -> dict:
    body = {
        "model": "hermes-agent",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Hermes coordinating with Grok. "
                    "For metrics you MUST run terminal tool. "
                    "Never invent numbers. If tools fail say TOOL_FAILED."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/v1/chat/completions",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Hermes-Session-Key": SESSION_KEY,
            "User-Agent": "GrokHermesJointTest/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:800]
        return {"ok": False, "error": f"HTTP {e.code}", "body": err}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    content = ""
    try:
        content = (
            ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        )
    except Exception:
        content = json.dumps(payload)[:1500]
    # extract ints that look like our six
    found = _extract_metric_nums(content)
    return {"ok": True, "content": content, "nums": found, "raw_keys": list(payload.keys())}


def _extract_metric_nums(content: str) -> dict:
    """Parse metrics from SILO_SIX block, key=value, or markdown tables (commas OK)."""
    found: dict = {}
    keys = (
        "registry_total",
        "unique_hashes",
        "status_copied",
        "status_landed",
        "ocr_ok_text",
        "ocr_open",
    )
    # key=123 or key: 123 or key | 123,456
    for key in keys:
        m = re.search(
            rf"{key}\s*[=:|*]*\s*\**\s*([\d,]+)",
            content,
            re.I,
        )
        if m:
            found[key] = int(m.group(1).replace(",", ""))
    # markdown table rows: | 1 | **registry_total** | 408,589 |
    for line in content.splitlines():
        m = re.search(
            r"\b(registry_total|unique_hashes|status_copied|status_landed|ocr_ok_text|ocr_open)\b[^\d]*([\d,]+)",
            line,
            re.I,
        )
        if m:
            found[m.group(1).lower()] = int(m.group(2).replace(",", ""))
    return found


def compare(g: dict, h: dict) -> dict:
    g_n = g.get("nums") or {}
    h_n = h.get("nums") or {}
    keys = [
        "registry_total",
        "unique_hashes",
        "status_copied",
        "status_landed",
        "ocr_ok_text",
        "ocr_open",
    ]
    matches = {}
    for k in keys:
        if k in g_n and k in h_n:
            matches[k] = g_n[k] == h_n[k]
        else:
            matches[k] = False
    all_ok = all(matches.values()) and bool(g_n) and bool(h_n)
    return {"all_match": all_ok, "per_key": matches, "grok": g_n, "hermes": h_n}


def write_receipt(result: dict) -> None:
    lines = [
        f"# Grok↔Hermes joint silo test — {result.get('at')}",
        "",
        f"**PASS:** **{result.get('pass')}**",
        f"**API:** `{API_BASE}` session `{SESSION_KEY}`",
        "",
        "## Grok measure (local script)",
        "```",
        (result.get("grok") or {}).get("raw", "")[:1500],
        "```",
        "",
        "## Hermes API reply",
        "```",
        ((result.get("hermes") or {}).get("content") or (result.get("hermes") or {}).get("error") or "")[:2000],
        "```",
        "",
        "## Compare",
        "```json",
        json.dumps(result.get("compare") or {}, indent=2),
        "```",
        "",
        "## Standing agreement",
        "1. Silo metrics only from `silo_discord_six_numbers.py` or `silo_scoreboard_pulse.py`.",
        "2. Discord data-silo lane = local grunt + tools; never invent KPIs.",
        "3. Hard judgment → Grok via `prepare_grok_escalation_brief.py`.",
        "4. Hybrid policy: [[Operations/Hybrid-Local-Grok-Token-Policy-CANONICAL-2026-07-17]]",
        "",
        "[[docs/agent-coordination/GROK-HERMES-MASTER-PLAN]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")


def append_master_round(result: dict) -> None:
    if not MASTER.is_file():
        return
    block = f"""
## Round 39 — Grok+Hermes joint — 2026-07-17 — Silo truth test
**PASS:** {result.get('pass')}
**Grok nums:** {json.dumps((result.get('compare') or {}).get('grok') or {})}
**Hermes nums:** {json.dumps((result.get('compare') or {}).get('hermes') or {})}
**Receipt:** [[Operations/logs/grok-hermes-joint-silo-test-latest]]
**Ack Hermes:** Discord silo metrics only from silo_discord_six_numbers.py; ESCALATE_GROK for architecture.

"""
    cur = MASTER.read_text(encoding="utf-8")
    if cur.startswith("\ufeff"):
        cur = cur[1:]
    MASTER.write_text(block.lstrip() + "\n" + cur.lstrip(), encoding="utf-8")


def post_discord(token: str, channel: str, content: str) -> str:
    payload = json.dumps({"content": content[:1900]}).encode("utf-8")
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel}/messages",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "GrokHermesJointTest/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return str(json.loads(resp.read().decode()).get("id") or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--post-discord", action="store_true")
    ap.add_argument("--skip-hermes-api", action="store_true")
    args = ap.parse_args()
    env = load_env()
    api_key = env.get("API_SERVER_KEY") or env.get("HERMES_API_TOKEN") or ""
    if not api_key and not args.skip_hermes_api:
        print(json.dumps({"ok": False, "error": "no API_SERVER_KEY/HERMES_API_TOKEN"}))
        return 2

    grok = grok_measure()
    prompt = (
        "JOINT TEST WITH GROK (data silo truth). "
        "Run EXACTLY this terminal command and paste the full SILO_SIX_NUMBERS block:\n"
        "python D:/HermesData/scripts/silo_discord_six_numbers.py\n"
        "Do not invent numbers. If command fails, say TOOL_FAILED with error."
    )
    if args.skip_hermes_api:
        hermes = {"ok": False, "error": "skipped", "content": "", "nums": {}}
    else:
        hermes = hermes_chat(api_key, prompt, timeout=420)

    cmp_ = compare(grok, hermes)
    passed = bool(grok.get("ok") and hermes.get("ok") and cmp_.get("all_match"))
    result = {
        "at": utc(),
        "pass": passed,
        "grok": grok,
        "hermes": hermes,
        "compare": cmp_,
    }
    write_receipt(result)
    append_master_round(result)
    print(json.dumps({"pass": passed, "compare": cmp_, "receipt": str(RECEIPT)}, indent=2))
    if hermes.get("content"):
        print("--- HERMES ---")
        print(hermes["content"][:1500])

    if args.post_discord and env.get("DISCORD_BOT_TOKEN"):
        tok = env["DISCORD_BOT_TOKEN"]
        g_n = cmp_.get("grok") or {}
        h_n = cmp_.get("hermes") or {}
        msg = (
            f"**Grok↔Hermes joint silo test** PASS=**{passed}**\n"
            f"Grok: `{json.dumps(g_n)}`\n"
            f"Hermes: `{json.dumps(h_n)}`\n"
            f"Receipt: `Operations/logs/grok-hermes-joint-silo-test-latest.md`\n"
            f"Agreement: metrics only via `silo_discord_six_numbers.py`."
        )
        try:
            mid1 = post_discord(tok, SILO_CHANNEL, msg)
            mid2 = post_discord(
                tok,
                GROK_CHANNEL,
                f"Joint test with data-silo lane PASS={passed}. See Round 39 master plan.",
            )
            print(json.dumps({"discord_silo": mid1, "discord_grok": mid2}))
        except Exception as e:
            print(json.dumps({"discord_err": str(e)}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
