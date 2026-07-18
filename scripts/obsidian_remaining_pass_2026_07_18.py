#!/usr/bin/env python3
"""Remaining Obsidian/vault pass after Jeff reload (2026-07-18).

- Re-strip Juggl leaves from workspace.json
- Disable Juggl + Agent Client (keep Copilot quiet but available)
- Tag 2 missing domain notes
- Archive .smart-env/multi → backups (force lighter SC rebuild on next open)
- Dual-verify + print report
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
OBS = VAULT / ".obsidian"
TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
BAK = OBS / "backups" / f"remaining-pass-{TS}"
REPORT: list[str] = []


def log(msg: str) -> None:
    print(msg)
    REPORT.append(msg)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def backup(path: Path) -> None:
    if not path.exists():
        return
    BAK.mkdir(parents=True, exist_ok=True)
    rel = path.relative_to(VAULT) if path.is_relative_to(VAULT) else Path(path.name)
    dest = BAK / str(rel).replace("\\", "__").replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(path, dest)
    else:
        shutil.copy2(path, dest)


def strip_juggl(node):
    """Remove juggl_* leaves; prune empty tabs containers."""
    if isinstance(node, dict):
        t = str(node.get("type") or "")
        st = node.get("state") or {}
        stt = str(st.get("type") or "") if isinstance(st, dict) else ""
        if "juggl" in t.lower() or "juggl" in stt.lower():
            return None
        out = {}
        for k, v in node.items():
            if k == "children" and isinstance(v, list):
                kids = []
                for c in v:
                    sc = strip_juggl(c)
                    if sc is not None:
                        kids.append(sc)
                out[k] = kids
            else:
                sv = strip_juggl(v)
                out[k] = sv
        # drop empty tabs
        if out.get("type") == "tabs" and not out.get("children"):
            return None
        return out
    if isinstance(node, list):
        return [x for x in (strip_juggl(i) for i in node) if x is not None]
    return node


def ensure_yaml_tags(path: Path, tags: list[str]) -> bool:
    text = path.read_text(encoding="utf-8")
    # already has domain?
    if re.search(r"(?m)^tags:\s*$|(?m)^\s*-\s*domain/|#[\w/-]*domain/", text):
        if any(f"domain/{t.split('/')[-1]}" in text or t in text for t in tags):
            # still check specifically
            pass
    if all(
        (t in text) or (t.replace("domain/", "#domain/") in text)
        for t in tags
        if t.startswith("domain/")
    ):
        # weaker: if any domain/ present skip only when that domain present
        present = set(re.findall(r"domain/[\w-]+", text, flags=re.I))
        need = [t for t in tags if t not in present and t.startswith("domain/")]
        if not need and any(t.startswith("domain/") for t in tags):
            # may still need type tags
            need = [t for t in tags if t not in present]
            if not need:
                return False
        tags = need or tags

    fm = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, flags=re.S)
    if fm:
        body = text[fm.end() :]
        front = fm.group(1)
        if re.search(r"(?m)^tags:\s*$", front) or re.search(r"(?m)^tags:\s*\[", front):
            # list form tags:
            if re.search(r"(?m)^tags:\s*\[", front):
                # inline array — convert gently by appending YAML list after
                front = re.sub(r"(?m)^tags:\s*\[.*?\]\s*$", "tags:", front)
            # ensure list items
            existing = set(re.findall(r"(?m)^\s*-\s*([^\n#]+)", front))
            add_lines = []
            for t in tags:
                if t not in existing and not any(t == e.strip() for e in existing):
                    add_lines.append(f"  - {t}")
            if not add_lines and re.search(r"(?m)^tags:", front):
                # tags key exists maybe empty
                if not re.search(r"(?m)^tags:\s*\n(\s*-\s+)", front):
                    # insert after tags:
                    front = re.sub(
                        r"(?m)^tags:\s*$",
                        "tags:\n" + "\n".join(f"  - {t}" for t in tags),
                        front,
                        count=1,
                    )
                else:
                    return False
            else:
                # append after tags block start
                def inject(m):
                    return m.group(0) + "\n" + "\n".join(add_lines)

                if add_lines:
                    if re.search(r"(?m)^tags:\s*$", front):
                        front = re.sub(
                            r"(?m)^tags:\s*$",
                            "tags:\n" + "\n".join(add_lines),
                            front,
                            count=1,
                        )
                    else:
                        # find last tag list item under tags — simple append before next top key
                        lines = front.splitlines()
                        out = []
                        in_tags = False
                        inserted = False
                        for i, line in enumerate(lines):
                            out.append(line)
                            if re.match(r"^tags:\s*$", line):
                                in_tags = True
                                continue
                            if in_tags:
                                if re.match(r"^\s+-\s+", line):
                                    continue
                                if re.match(r"^[A-Za-z0-9_]+:", line):
                                    # insert before this line
                                    out.pop()
                                    out.extend(add_lines)
                                    out.append(line)
                                    inserted = True
                                    in_tags = False
                                else:
                                    in_tags = False
                        if in_tags and not inserted:
                            out.extend(add_lines)
                            inserted = True
                        if not inserted and add_lines:
                            out.extend(add_lines)
                        front = "\n".join(out)
        else:
            front = front.rstrip() + "\n tags:\n".replace(" tags:", "tags:") + "\n".join(
                f"  - {t}" for t in tags
            )
        new = f"---\n{front}\n---\n{body}"
    else:
        block = "---\ntags:\n" + "\n".join(f"  - {t}" for t in tags) + "\n---\n\n"
        new = block + text
    if new != text:
        path.write_text(new, encoding="utf-8")
        return True
    return False


def simple_ensure_tags(path: Path, tags: list[str]) -> bool:
    """Robust small helper for index files."""
    text = path.read_text(encoding="utf-8")
    present = set(re.findall(r"domain/[\w-]+|type/[\w-]+|status/[\w-]+", text, flags=re.I))
    need = [t for t in tags if t not in present]
    if not need:
        return False
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, flags=re.S)
    if m:
        front = m.group(1)
        body = text[m.end() :]
        if re.search(r"(?m)^tags:\s*$", front):
            front = re.sub(
                r"(?m)^tags:\s*$",
                "tags:\n" + "\n".join(f"  - {t}" for t in need),
                front,
                count=1,
            )
        elif re.search(r"(?m)^tags:", front):
            # append items after tags key line / existing items
            lines = front.splitlines()
            out = []
            inserted = False
            i = 0
            while i < len(lines):
                line = lines[i]
                out.append(line)
                if re.match(r"^tags:\s*$", line) or re.match(r"^tags:\s*\[", line):
                    if "[" in line:
                        out[-1] = "tags:"
                    # copy existing list items
                    i += 1
                    while i < len(lines) and re.match(r"^\s+-\s+", lines[i]):
                        out.append(lines[i])
                        i += 1
                    for t in need:
                        out.append(f"  - {t}")
                    inserted = True
                    continue
                i += 1
            if not inserted:
                out.append("tags:")
                out.extend(f"  - {t}" for t in need)
            front = "\n".join(out)
        else:
            front = front.rstrip() + "\ntags:\n" + "\n".join(f"  - {t}" for t in need)
        path.write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")
        return True
    block = "---\ntags:\n" + "\n".join(f"  - {t}" for t in need) + "\n---\n\n"
    path.write_text(block + text, encoding="utf-8")
    return True


def main() -> int:
    BAK.mkdir(parents=True, exist_ok=True)
    log(f"TS={TS}")
    log(f"backup_dir={BAK}")

    # 1) community-plugins: disable juggl + agent-client
    cp_path = OBS / "community-plugins.json"
    backup(cp_path)
    enabled = load_json(cp_path)
    before = list(enabled)
    disable = {"juggl", "agent-client"}
    enabled2 = [p for p in enabled if p not in disable]
    removed = [p for p in before if p not in enabled2]
    dump_json(cp_path, enabled2)
    log(f"disabled_plugins={removed} remaining={len(enabled2)}")

    # 2) workspace strip juggl
    ws_path = OBS / "workspace.json"
    backup(ws_path)
    raw = ws_path.read_text(encoding="utf-8")
    juggl_before = len(re.findall(r"juggl", raw, flags=re.I))
    ws = json.loads(raw)
    ws2 = strip_juggl(ws)
    # also scrub lastOpenFiles / active if needed
    if isinstance(ws2, dict):
        for key in ("lastOpenFiles",):
            if key in ws2 and isinstance(ws2[key], list):
                ws2[key] = [x for x in ws2[key] if "juggl" not in str(x).lower()]
    dump_json(ws_path, ws2)
    juggl_after = len(re.findall(r"juggl", ws_path.read_text(encoding="utf-8"), flags=re.I))
    log(f"workspace_juggl_mentions {juggl_before} -> {juggl_after}")

    # 3) tag missing two
    missing = [
        (VAULT / "Digital-Twin/receipts/INDEX.md", ["domain/twin", "type/index", "status/live"]),
        (VAULT / "Research/Silo-Entities/00-INDEX.md", ["domain/silo", "domain/twin", "type/index", "status/live"]),
    ]
    for path, tags in missing:
        if not path.exists():
            log(f"tag_skip_missing_file={path}")
            continue
        backup(path)
        ok = simple_ensure_tags(path, tags)
        log(f"tag_{'updated' if ok else 'unchanged'}={path.relative_to(VAULT)} tags={tags}")

    # 4) archive smart-env multi (large ajson thrash) — move, don't delete
    multi = VAULT / ".smart-env" / "multi"
    arch_root = VAULT / "Operations" / "backups" / f"smart-env-multi-{TS}"
    if multi.exists():
        # size estimate
        try:
            total = sum(f.stat().st_size for f in multi.rglob("*") if f.is_file())
        except OSError:
            total = -1
        arch_root.parent.mkdir(parents=True, exist_ok=True)
        if arch_root.exists():
            shutil.rmtree(arch_root)
        shutil.move(str(multi), str(arch_root))
        multi.mkdir(parents=True, exist_ok=True)  # empty placeholder
        # marker
        (multi / "00-ARCHIVED.md").write_text(
            f"# smart-env multi archived\n\nMoved to `{arch_root}` at {TS} UTC.\n"
            "Smart Connections will rebuild a lighter index using folder_exclusions.\n",
            encoding="utf-8",
        )
        log(f"smart_env_multi_archived_bytes={total} -> {arch_root}")
    else:
        log("smart_env_multi_absent")

    # 5) reinforce smart_env exclusions
    se_path = VAULT / ".smart-env" / "smart_env.json"
    if se_path.exists():
        backup(se_path)
        se = load_json(se_path)
        excl = (
            "Operations/logs, Operations/backups, Archive, Alice, Roleplay-Sandbox, "
            ".smart-env, node_modules, copilot, temp, temp_sources, scripts, references, "
            "AI-Zone/Drafts, AI-Zone/exports, Excalidraw, AI-Computer-Management/Current-State, "
            "Past-Attempts-Distilled, Backups, tests"
        )
        ss = se.setdefault("smart_sources", {})
        ss["folder_exclusions"] = excl
        ss["file_exclusions"] = "Untitled, 00-INDEX"
        se["new_user"] = False
        se["re_import_wait_time"] = 45
        dump_json(se_path, se)
        log("smart_env_exclusions_reinforced")

    # 6) dual-verify
    plugins = load_json(cp_path)
    log(f"verify_enabled_count={len(plugins)}")
    missing_main = []
    for pid in plugins:
        main = OBS / "plugins" / pid / "main.js"
        man = OBS / "plugins" / pid / "manifest.json"
        if not main.exists() or not man.exists():
            missing_main.append(pid)
    log(f"verify_missing_main_or_manifest={missing_main}")

    lra = OBS / "plugins" / "obsidian-local-rest-api" / "manifest.json"
    if lra.exists():
        log(f"verify_lra_version={load_json(lra).get('version')}")

    cp = load_json(OBS / "plugins" / "copilot" / "data.json")
    log(f"verify_copilot_model={cp.get('defaultModelKey')}")
    log(f"verify_copilot_index={cp.get('indexVaultToVectorStore')}")

    se = load_json(se_path) if se_path.exists() else {}
    fe = (se.get("smart_sources") or {}).get("folder_exclusions", "")
    log(f"verify_smart_excl_len={len(fe)} nonempty={bool(fe.strip())}")

    ws_txt = ws_path.read_text(encoding="utf-8")
    log(f"verify_workspace_juggl={len(re.findall(r'juggl', ws_txt, flags=re.I))}")
    log(f"verify_juggl_enabled={'juggl' in plugins}")
    log(f"verify_agent_client_enabled={'agent-client' in plugins}")

    multi_files = list((VAULT / ".smart-env" / "multi").rglob("*")) if (VAULT / ".smart-env" / "multi").exists() else []
    multi_files = [p for p in multi_files if p.is_file()]
    log(f"verify_smart_multi_files={len(multi_files)}")

    # write report
    rep = VAULT / "Operations" / "logs" / f"obsidian-remaining-pass-{TS}.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- {line}" for line in REPORT)
    rep.write_text(
        f"---\ntags:\n  - domain/ops\n  - domain/setup\n  - type/receipt\n  - status/live\ndate: 2026-07-18\n---\n\n"
        f"# Obsidian remaining pass — {TS}\n\n{body}\n",
        encoding="utf-8",
    )
    latest = VAULT / "Operations" / "logs" / "obsidian-remaining-pass-latest.md"
    shutil.copy2(rep, latest)
    log(f"report={rep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
