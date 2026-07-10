#!/usr/bin/env python3
"""E2E image pipeline audit — structural health."""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

issues: list[tuple[str, str, str]] = []
ok: list[tuple[str, str]] = []


def add(sev: str, area: str, detail: str) -> None:
    issues.append((sev, area, detail))


def good(area: str, detail: str) -> None:
    ok.append((area, detail))


FILES = {
    "generate.py": Path(
        r"D:/HermesData/skills/creative/uncensored-image-generation/scripts/generate.py"
    ),
    "gallery.py": Path(
        r"D:/HermesData/skills/creative/uncensored-image-generation/scripts/gallery.py"
    ),
    "gallery_server.py": Path(
        r"D:/HermesData/skills/creative/uncensored-image-generation/scripts/gallery_server.py"
    ),
    "render": Path(r"D:/PhronesisVault/Roleplay-Sandbox/sandbox/render-roleplay-image.py"),
    "visual_registry": Path(
        r"D:/PhronesisVault/Roleplay-Sandbox/sandbox/lib/visual_registry.py"
    ),
    "prompt_compose": Path(
        r"D:/PhronesisVault/Roleplay-Sandbox/sandbox/lib/prompt_compose.py"
    ),
    "inventory_registry": Path(
        r"D:/PhronesisVault/Roleplay-Sandbox/sandbox/lib/inventory_registry.py"
    ),
    "comfyui_local": Path(r"D:/HermesData/plugins/image_gen/comfyui_local/__init__.py"),
    "delivery_daemon": Path(r"D:/HermesData/scripts/comfy_delivery_daemon.py"),
    "watch_delivery": Path(r"D:/HermesData/scripts/ops/watch_comfy_delivery.py"),
    "batch_spec": Path(r"D:/HermesData/scripts/ops/rp_batch_spec.py"),
    "batch_orch": Path(r"D:/HermesData/scripts/ops/rp_batch_orchestrator.py"),
    "batch_session": Path(r"D:/HermesData/scripts/ops/rp_batch_session.py"),
    "batch_jobs": Path(r"D:/HermesData/scripts/ops/rp_batch_jobs.py"),
    "visual_tags": Path(r"D:/PhronesisVault/Roleplay-Sandbox/runtime/visual-tags.yaml"),
    "batch_series": Path(r"D:/PhronesisVault/Roleplay-Sandbox/sandbox/batch-rp-series.py"),
}


def main() -> int:
    print("=== FILE INTEGRITY ===")
    for name, p in FILES.items():
        if not p.exists():
            add("HIGH", name, f"MISSING {p}")
            print(f"MISSING {name}")
            continue
        raw = p.read_bytes()
        nl = raw.count(b"\n")
        lines = raw.splitlines()
        l0 = len(lines[0]) if lines else 0
        mangled = l0 > 2000 or (len(raw) > 8000 and nl < 40)
        if mangled:
            add("CRITICAL", name, f"mangled oneline nl={nl} L0={l0} size={len(raw)}")
            print(f"MANGLED {name} nl={nl} L0={l0}")
            continue
        if p.suffix == ".py":
            try:
                tree = ast.parse(raw.decode("utf-8"))
                defs = sum(
                    1
                    for n in tree.body
                    if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                )
                good(name, f"AST ok defs={defs} nl={nl}")
                print(f"OK {name:20} defs={defs:3} nl={nl:4} size={len(raw)}")
            except SyntaxError as e:
                add("CRITICAL", name, f"SyntaxError {e}")
                print(f"SYNTAX {name} {e}")
        else:
            good(name, f"present size={len(raw)}")
            print(f"OK {name:20} size={len(raw)}")

    print("\n=== IMPORT GRAPH ===")
    sys.path.insert(0, r"D:/HermesData/scripts/ops")
    sys.path.insert(0, r"D:/HermesData/scripts")
    sys.path.insert(0, r"D:/PhronesisVault/Roleplay-Sandbox/sandbox/lib")

    try:
        from rp_batch_spec import (  # noqa: F401
            batch_intent_signature,
            detect_recipe,
            resolve_series_plan,
            slice_plan,
        )
        from rp_batch_orchestrator import launch  # noqa: F401

        good("batch", "orchestrator+spec import OK")
        print("batch import OK")
        r = launch(
            "OOC: series of 3 test portraits freeform",
            {"batch_count": 3},
            dry_run=True,
        )
        if not r.get("ok"):
            add("HIGH", "batch", f"dry_run not ok: {r}")
        else:
            good("batch", f"dry_run ok series={r.get('series')}")
            print("batch dry_run OK", r.get("series"), r.get("cmd", [])[:4])
    except Exception as e:
        add("CRITICAL", "batch", f"import/launch fail: {e}")
        print("batch FAIL", e)

    try:
        from prompt_compose import compose_character_prompt  # noqa: F401
        from visual_registry import get_cast_entry, load_visual_tags  # noqa: F401

        alice = get_cast_entry("alice")
        p, d = compose_character_prompt("alice", mode="portrait", scene="surprised")
        if not alice.get("locked_seed"):
            add("MED", "sandbox_libs", "alice missing locked_seed")
        if not alice.get("identity_lock"):
            add("MED", "sandbox_libs", "alice missing identity_lock")
        if "surpris" not in p.lower() and "wide eyes" not in p.lower():
            add("MED", "sandbox_libs", "expression not injected for surprise scene")
        good(
            "sandbox_libs",
            f"alice seed={alice.get('locked_seed')} prompt_len={len(p)}",
        )
        print(
            "sandbox libs OK",
            "seed",
            alice.get("locked_seed"),
            "id_lock",
            bool(alice.get("identity_lock")),
        )
    except Exception as e:
        add("HIGH", "sandbox_libs", str(e))
        print("sandbox FAIL", e)

    try:
        import os

        os.environ["HERMES_PYTHONW_REEXEC"] = "1"
        import comfy_delivery_daemon as d

        if not hasattr(d, "_caption_from_sidecar"):
            add("HIGH", "delivery", "missing _caption_from_sidecar")
        else:
            good("delivery", "sidecar caption path present")
            print("delivery caption OK")
    except Exception as e:
        add("HIGH", "delivery", str(e))
        print("delivery FAIL", e)

    gsrc = FILES["generate.py"].read_text(encoding="utf-8")
    for sym in ["build_display_caption", "locked_seed", "def main", "gallery_log"]:
        if sym not in gsrc:
            add("HIGH", "generate.py", f"missing symbol/text: {sym}")
        else:
            good("generate.py", f"has {sym}")
    print("generate symbols checked")

    ps = FILES["comfyui_local"].read_text(encoding="utf-8")
    bad = (
        'if spec.get("fresh"):\n'
        '        cmd.append("--fresh")\n'
        '        cmd.append("--new-seed")'
    )
    if bad in ps:
        add("HIGH", "comfyui_local", "still forces --new-seed on every fresh")
    elif 'if spec.get("new_seed")' in ps:
        good("comfyui_local", "new_seed gated correctly")
        print("plugin seed gating OK")
    else:
        add("MED", "comfyui_local", "new_seed gate pattern unclear")

    print("\n=== COMFY ===")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=5) as resp:
            stats = json.loads(resp.read().decode())
        good("comfy", f"up {stats.get('system', {}).get('comfyui_version')}")
        print("Comfy UP", stats.get("system", {}).get("comfyui_version"))
    except Exception as e:
        add("CRITICAL", "comfy", f"down: {e}")
        print("Comfy DOWN", e)

    print("\n=== DELIVERY PROCS ===")
    r = subprocess.run(
        [
            "wmic",
            "process",
            "where",
            "name='python.exe' or name='pythonw.exe'",
            "get",
            "ProcessId,CommandLine",
            "/FORMAT:CSV",
        ],
        capture_output=True,
        text=True,
        errors="ignore",
    )
    procs = []
    for ln in (r.stdout or "").splitlines()[1:]:
        if not ln.strip():
            continue
        m = re.search(r",(\d+)\s*$", ln)
        if not m:
            continue
        pid = int(m.group(1))
        rest = re.sub(r",\d+\s*$", "", ln.split(",", 1)[-1])
        cl = rest.strip().strip('"')
        if "comfy_delivery" in cl or "watch_comfy_delivery" in cl:
            procs.append((pid, cl[:140]))
    print("delivery-related", len(procs))
    for item in procs:
        print(" ", item[0], item[1][:120])
    if not procs:
        add("MED", "delivery", "no delivery daemon/watcher process running")
    else:
        good("delivery", f"{len(procs)} process(es) live")

    print("\n=== CAST COVERAGE ===")
    try:
        import yaml

        cast = (
            yaml.safe_load(FILES["visual_tags"].read_text(encoding="utf-8")) or {}
        ).get("cast") or {}
        n = len(cast)
        seeds = sum(
            1
            for e in cast.values()
            if isinstance(e, dict) and e.get("locked_seed") not in (None, "", 0, "0")
        )
        ids = sum(1 for e in cast.values() if isinstance(e, dict) and e.get("identity_lock"))
        root = Path(r"D:/PhronesisVault/Roleplay-Sandbox/gallery/cast")
        ports = sum(
            1 for name in cast if (root / name / "canonical" / "portrait.png").is_file()
        )
        print(f"cast={n} seeds={seeds} identity_lock={ids} portraits={ports}")
        if seeds < 10:
            add("MED", "consistency", f"only {seeds}/{n} locked seeds")
        else:
            good("consistency", f"locked seeds {seeds}/{n}")
        if ports < 10:
            add("MED", "consistency", f"only {ports}/{n} canonical portraits")
        else:
            good("consistency", f"portraits {ports}/{n}")
        if ids < n:
            add("LOW", "consistency", f"identity_lock {ids}/{n}")
        else:
            good("consistency", f"identity_lock {ids}/{n}")
    except Exception as e:
        add("MED", "cast", str(e))

    print("\n=== BATCH SERIES SCRIPT ===")
    bs = FILES["batch_series"]
    if bs.exists():
        try:
            ast.parse(bs.read_text(encoding="utf-8"))
            good("batch_series", "AST OK")
            print("batch-rp-series.py AST OK")
        except SyntaxError as e:
            add("HIGH", "batch_series", f"SyntaxError {e}")
    else:
        add("HIGH", "batch_series", "missing sandbox/batch-rp-series.py")

    print("\n=== SECONDARY MANGLED (comfy skill helpers) ===")
    comfy_scripts = Path(r"D:/HermesData/skills/creative/comfyui/scripts")
    mang = 0
    if comfy_scripts.is_dir():
        for p in comfy_scripts.glob("*.py"):
            raw = p.read_bytes()
            nl = raw.count(b"\n")
            l0 = len(raw.splitlines()[0]) if raw.splitlines() else 0
            if l0 > 2000 or (len(raw) > 5000 and nl < 30):
                mang += 1
                print(" MANGLED", p.name)
    if mang:
        add("LOW", "comfyui_skill", f"{mang} helper scripts still mangled (not hot path)")
    else:
        good("comfyui_skill", "no mangled helpers or dir missing")

    print("\n=== ORCH DEPS ===")
    for mod in [
        "rp_batch_launch_lock",
        "rp_batch_session",
        "rp_sandbox_paths",
        "rp_batch_canon",
    ]:
        try:
            __import__(mod)
            good(mod, "import OK")
            print(mod, "OK")
        except Exception as e:
            add("HIGH", mod, str(e))
            print(mod, "FAIL", e)

    # group compose identity
    print("\n=== GROUP COMPOSE ===")
    try:
        from prompt_compose import compose_group_prompt

        src = Path(
            r"D:/PhronesisVault/Roleplay-Sandbox/sandbox/lib/prompt_compose.py"
        ).read_text(encoding="utf-8")
        # crude: does group path call identity_body_layers?
        gstart = src.find("def compose_group_prompt")
        gend = src.find("\ndef ", gstart + 10)
        gbody = src[gstart:gend if gend > 0 else gstart + 5000]
        if "identity_body_layers" not in gbody:
            add(
                "MED",
                "group_compose",
                "compose_group_prompt does not use identity_body_layers (3+ faces weaker)",
            )
            print("group compose missing identity_body_layers")
        else:
            good("group_compose", "uses identity_body_layers")
            print("group compose OK")
    except Exception as e:
        add("MED", "group_compose", str(e))

    print("\n========== ISSUES ==========")
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MED": 2, "LOW": 3}
    for sev, area, detail in sorted(issues, key=lambda x: sev_order.get(x[0], 9)):
        print(f"[{sev:8}] {area}: {detail}")
    print(f"\nOK checks: {len(ok)}  Issues: {len(issues)}")

    rep = Path(r"D:/PhronesisVault/Roleplay-Sandbox/logs/pipeline-e2e-audit.md")
    rep.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Image pipeline E2E audit\n\n",
        f"Issues: {len(issues)}  OK: {len(ok)}\n\n",
        "## Issues\n\n",
    ]
    for sev, area, detail in sorted(issues, key=lambda x: sev_order.get(x[0], 9)):
        lines.append(f"- **{sev}** `{area}`: {detail}\n")
    lines.append("\n## Passing\n\n")
    for area, detail in ok:
        lines.append(f"- `{area}`: {detail}\n")
    rep.write_text("".join(lines), encoding="utf-8")
    print("report", rep)
    return 0 if not any(s == "CRITICAL" for s, _, _ in issues) else 1


if __name__ == "__main__":
    raise SystemExit(main())
