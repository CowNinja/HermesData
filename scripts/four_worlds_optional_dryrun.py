#!/usr/bin/env python3
"""Dry-run optional Four Worlds tidy for RP sandbox.

Items from placement audit (optional only):
  A) Hermes profiles/alice-roleplay vs Roleplay-Sandbox/profile
  B) HermesData/logs/harem-series.log vs sandbox logs
  C) Divine missing unique content into sandbox (report)
  D) Propose archive/purge ONLY for true duplicates of RP content

NO MOVES. Writes report under Operations/logs.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

HERMES_PROF = Path(r"D:\HermesData\profiles\alice-roleplay")
SANDBOX_PROF = Path(r"D:\PhronesisVault\Roleplay-Sandbox\profile")
SANDBOX = Path(r"D:\PhronesisVault\Roleplay-Sandbox")
HAREM_LOG = Path(r"D:\HermesData\logs\harem-series.log")
VAULT_ALICE = Path(r"D:\PhronesisVault\Alice")
OUT_MD = Path(r"D:\PhronesisVault\Operations\logs\four-worlds-optional-dryrun-latest.md")
OUT_JSON = Path(r"D:\HermesData\logs\four-worlds-optional-dryrun-latest.json")


def sha16(p: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            while True:
                b = f.read(1 << 20)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()[:16]
    except OSError:
        return None


def file_map(root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not root.exists():
        return out
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        try:
            st = f.stat()
            out[rel] = {"size": st.st_size, "sha": sha16(f), "path": str(f)}
        except OSError:
            continue
    return out


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    same_resolve = False
    try:
        same_resolve = HERMES_PROF.resolve() == SANDBOX_PROF.resolve()
    except OSError:
        pass

    mh = file_map(HERMES_PROF)
    ms = file_map(SANDBOX_PROF)
    only_h = sorted(set(mh) - set(ms))
    only_s = sorted(set(ms) - set(mh))
    same_hash = []
    size_diff = []
    for k in sorted(set(mh) & set(ms)):
        if mh[k]["sha"] and mh[k]["sha"] == ms[k]["sha"]:
            same_hash.append(k)
        elif mh[k]["size"] != ms[k]["size"] or mh[k]["sha"] != ms[k]["sha"]:
            size_diff.append(k)

    soul_h = HERMES_PROF / "SOUL.md"
    soul_s = SANDBOX_PROF / "SOUL.md"
    soul_same = (
        soul_h.exists()
        and soul_s.exists()
        and sha16(soul_h) == sha16(soul_s)
        and soul_h.stat().st_size == soul_s.stat().st_size
    )

    log_dest = SANDBOX / "logs" / "harem-series.log"
    log_plan = {
        "source": str(HAREM_LOG),
        "dest": str(log_dest),
        "source_exists": HAREM_LOG.exists(),
        "dest_exists": log_dest.exists(),
        "action_if_live": "COPY then leave Hermes log OR pointer-only (prefer copy into sandbox logs + keep Hermes log as optional runtime)",
        "size": HAREM_LOG.stat().st_size if HAREM_LOG.exists() else 0,
    }

    # Divine: unique under Hermes profile not in sandbox
    divine_into_sandbox = []
    for rel in only_h:
        # skip pure index noise and bak
        if rel.endswith("00-INDEX.md"):
            continue
        divine_into_sandbox.append(
            {
                "rel": rel,
                "size": mh[rel]["size"],
                "reason": "present only under Hermes profile; missing from sandbox profile",
                "live_action": f"COPY -> {SANDBOX_PROF / rel}",
            }
        )

    # Propose purge/archive for true duplicate non-config runtime? NEVER delete active Hermes profile —
    # Hermes profiles/alice-roleplay is a Hermes profile SSOT for gateway channel, not pure content dump.
    # If identical resolve or full mirror: recommend POINTER doc, not delete profile.
    archive_purge = []
    if same_resolve:
        archive_purge.append(
            {
                "item": str(HERMES_PROF),
                "action": "NONE — same resolved path as sandbox (junction/link). Do not delete.",
            }
        )
    elif not only_h and not size_diff and soul_same and len(same_hash) >= max(1, len(ms) - 5):
        archive_purge.append(
            {
                "item": str(HERMES_PROF),
                "action": "DO NOT PURGE profile tree — Hermes channel profile required. "
                "Optional: replace bulk duplicate skill refs with pointer README to sandbox after live verify. "
                "Keep SOUL/config/memories if Hermes still loads this path.",
            }
        )
    else:
        archive_purge.append(
            {
                "item": str(HERMES_PROF),
                "action": "MERGE missing into sandbox first; keep Hermes profile as runtime profile.",
            }
        )

    # vault Alice is large twin/avatar — not auto purge; note only
    vault_alice_note = {
        "path": str(VAULT_ALICE),
        "exists": VAULT_ALICE.exists(),
        "note": "Large twin/avatar/dashboard tree under vault (World 2). Not pure RP heat dump. "
        "Do NOT purge. Optional later: link from sandbox README to vault Alice for non-explicit twin assets.",
    }

    actions_live = []
    if HAREM_LOG.exists() and not log_dest.exists():
        actions_live.append(
            {
                "id": "copy_harem_log",
                "op": "copy",
                "src": str(HAREM_LOG),
                "dst": str(log_dest),
                "why": "RP series log missing from sandbox logs",
            }
        )
    for item in divine_into_sandbox:
        actions_live.append(
            {
                "id": f"copy_{item['rel']}",
                "op": "copy",
                "src": str(HERMES_PROF / item["rel"]),
                "dst": str(SANDBOX_PROF / item["rel"]),
                "why": item["reason"],
            }
        )
    # pointer note to create in hermes profile if fully mirrored
    if soul_same and not only_h:
        actions_live.append(
            {
                "id": "write_pointer_note",
                "op": "write",
                "dst": str(HERMES_PROF / "SANDBOX-CONTENT-SSOT.md"),
                "why": "Document sandbox as content SSOT; Hermes profile remains runtime profile",
                "content_preview": "Roleplay content SSOT: D:\\PhronesisVault\\Roleplay-Sandbox",
            }
        )

    payload = {
        "ts": ts,
        "mode": "DRY_RUN",
        "same_resolve": same_resolve,
        "profile_counts": {"hermes": len(mh), "sandbox": len(ms)},
        "only_hermes": only_h,
        "only_sandbox": only_s,
        "same_hash_count": len(same_hash),
        "size_diff": size_diff,
        "soul_identical": soul_same,
        "harem_log": log_plan,
        "divine_into_sandbox": divine_into_sandbox,
        "archive_purge_proposals": archive_purge,
        "vault_alice": vault_alice_note,
        "live_actions_if_greenlit": actions_live,
        "recommendation": (
            "LIVE safe batch: (1) copy harem-series.log into sandbox/logs; "
            "(2) copy any only-on-Hermes unique profile files into sandbox profile; "
            "(3) write SANDBOX-CONTENT-SSOT pointer under Hermes profile; "
            "(4) NEVER delete Hermes profiles/alice-roleplay (channel runtime); "
            "(5) NEVER purge D:\\PhronesisVault\\Alice without separate review."
        ),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Four Worlds Optional Dry-Run — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "**Mode: DRY-RUN ONLY — no files moved, purged, or archived.**",
        "",
        "## Scope (confirmed optional)",
        "1. Alice profile mirror: `D:\\HermesData\\profiles\\alice-roleplay` vs `Roleplay-Sandbox/profile`",
        "2. `harem-series.log` location",
        "3. Divine missing → sandbox; archive/purge only if applicable",
        "",
        "## Findings",
        f"- Same resolved path (junction/link): **{same_resolve}**",
        f"- File counts: Hermes **{len(mh)}** · Sandbox **{len(ms)}**",
        f"- Identical hashes (shared rel paths): **{len(same_hash)}**",
        f"- Only on Hermes: **{len(only_h)}**",
        f"- Only on Sandbox: **{len(only_s)}**",
        f"- Size/hash mismatches: **{len(size_diff)}**",
        f"- SOUL.md identical: **{soul_same}**",
        "",
        "### Only-on-Hermes (would copy into sandbox if unique content)",
    ]
    if only_h:
        for rel in only_h[:40]:
            lines.append(f"- `{rel}` ({mh[rel]['size']}b)")
        if len(only_h) > 40:
            lines.append(f"- … +{len(only_h)-40}")
    else:
        lines.append("- _None — trees already content-mirrored (or linked)._")

    lines += [
        "",
        "### Harem log",
        f"- Source exists: **{log_plan['source_exists']}** (`{log_plan['source']}`)",
        f"- Dest exists: **{log_plan['dest_exists']}** (`{log_plan['dest']}`)",
        f"- Live action: **COPY into sandbox logs** (keep Hermes log unless you prefer single location later)",
        "",
        "### Archive / purge",
    ]
    for a in archive_purge:
        lines.append(f"- `{a['item']}` → {a['action']}")

    lines += [
        "",
        "### Vault Alice (out of optional purge)",
        f"- `{vault_alice_note['path']}` exists={vault_alice_note['exists']}",
        f"- {vault_alice_note['note']}",
        "",
        "## Divine / recommendation",
        payload["recommendation"],
        "",
        "## Live actions if green-lit (ordered)",
    ]
    if actions_live:
        for i, a in enumerate(actions_live, 1):
            lines.append(f"{i}. **{a['op']}** `{a.get('src','')}` → `{a.get('dst')}` — {a['why']}")
    else:
        lines.append("- _No copy actions needed beyond optional pointer note._")

    lines += [
        "",
        "## Not doing without green light",
        "- Deleting Hermes `profiles/alice-roleplay`",
        "- Purging `D:\\PhronesisVault\\Alice`",
        "- Moving Hermes skills/roleplay machinery into sandbox",
        "",
        "## Vault links",
        "- [[Operations/logs/four-worlds-placement-audit-latest]]",
        "- [[Operations/Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10]]",
        "- [[Roleplay-Sandbox/README]]",
        "",
        f"JSON: `{OUT_JSON}`",
        "",
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "same_resolve": same_resolve,
        "only_h": len(only_h),
        "only_s": len(only_s),
        "soul_same": soul_same,
        "live_actions": len(actions_live),
        "md": str(OUT_MD),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
