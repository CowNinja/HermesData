#!/usr/bin/env python3
"""Travel-safe autonomous five: gardener harden, resurface core, dawn hook, cron hygiene, silo proposals."""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
HERMES = Path(r"D:\HermesData")
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d")
log: list[str] = []


def main() -> int:
    # 1) Harden Phase B dual skip
    gp = HERMES / "scripts" / "gardener_phase_b_proposals.py"
    t = gp.read_text(encoding="utf-8")
    if "INTENTIONAL_DUAL_STEMS" not in t:
        needle = "def cluster_stems(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:"
        insert = (
            "INTENTIONAL_DUAL_STEMS = {\n"
            '    "status",\n'
            '    "orchestrator-pilot-run-log",\n'
            "}\n\n"
            "def cluster_stems(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:"
        )
        if needle in t:
            t = t.replace(needle, insert, 1)
            old = (
                '        if stem in {"index", "readme", "log", "notes", "untitled", "date"}:\n'
                "            continue"
            )
            new = (
                '        if stem in {"index", "readme", "log", "notes", "untitled", "date"}:\n'
                "            continue\n"
                "        if stem in INTENTIONAL_DUAL_STEMS:\n"
                "            continue"
            )
            if old in t:
                t = t.replace(old, new, 1)
                ast.parse(t)
                gp.write_text(t, encoding="utf-8", newline="\n")
                log.append("1 gardener skip intentional duals OK")
            else:
                log.append("1 dual skip loop not found")
        else:
            log.append("1 cluster_stems not found")
    else:
        log.append("1 already hardened")

    # 2) Resurface CORE
    items = [
        VAULT / "Research" / "Forensic-Audit-HermesData-BACKUP-2026-06-12.md",
        VAULT / "Research" / "Brian-Roemmele-Part-31-Category-Inventor-2026-06-14.md",
        VAULT / "Research" / "Guardrails-for-Perpetual-Agents.md",
    ]
    lines = [
        f"# Resurfaced Ideas CORE ({TS})",
        "",
        "Distilled from Phase B resurface queue. Originals kept.",
        "",
    ]
    for p in items:
        if not p.exists():
            lines.append(f"- MISSING `{p.name}`")
            continue
        body = p.read_text(encoding="utf-8", errors="ignore")
        paras = [
            x.strip()
            for x in re.split(r"\n\s*\n", body)
            if x.strip() and not x.strip().startswith("#")
        ]
        blurb = re.sub(r"\s+", " ", " ".join(paras[:2]))[:600]
        rel = str(p.relative_to(VAULT)).replace("\\", "/")
        lines.append(f"## [[{rel.replace('.md', '')}]]")
        lines.append(blurb or "(no extract)")
        lines.append("")
    lines += [
        "## Vault links",
        "- [[Operations/Resurface-Queue-Phase-B]]",
        "- [[Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10]]",
        "",
    ]
    core = VAULT / "Research" / "Resurfaced-Ideas-CORE.md"
    core.write_text("\n".join(lines), encoding="utf-8")
    log.append(f"2 resurface core {core.stat().st_size}b")

    # 3) Dawn thin orchestrator line
    dawn = HERMES / "scripts" / "dawn_pulse_script.py"
    if dawn.exists():
        dt = dawn.read_text(encoding="utf-8")
        if "thin_orchestrator_status" not in dt:
            addon = '''
def _thin_orchestrator_line() -> str:
    try:
        import json
        import subprocess
        import sys
        from pathlib import Path
        p = Path(r"D:\\HermesData\\scripts\\thin_orchestrator_status.py")
        if not p.is_file():
            return ""
        r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True, timeout=20)
        d = json.loads(r.stdout or "{}")
        ports = d.get("ports") or {}
        return "Thin orchestrator ports: " + ", ".join(f"{k}={v}" for k, v in ports.items())
    except Exception:
        return ""

'''
            if "def main" in dt:
                dt2 = dt.replace("def main", addon + "def main", 1)
                out_lines = []
                done = False
                for line in dt2.splitlines(True):
                    out_lines.append(line)
                    if (not done) and "print" in line and "Hybrid" in line:
                        out_lines.append("    _tol = _thin_orchestrator_line()\n")
                        out_lines.append("    if _tol:\n")
                        out_lines.append("        print(_tol)\n")
                        done = True
                dt2 = "".join(out_lines)
                try:
                    ast.parse(dt2)
                    dawn.write_text(dt2, encoding="utf-8", newline="\n")
                    log.append("3 dawn thin OK" if done else "3 dawn fn added")
                except SyntaxError as e:
                    log.append(f"3 dawn skip {e}")
            else:
                log.append("3 no main")
        else:
            log.append("3 already thin")
    else:
        log.append("3 no dawn")

    # 4) Cron hygiene
    jobs_path = Path(r"C:/Users/CowNi/.hermes/cron/jobs.json")
    data = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs = data["jobs"]
    agent = []
    fixed = []
    for j in jobs:
        if j.get("enabled") and not j.get("no_agent"):
            agent.append(j.get("name"))
        if j.get("name") in (
            "Gardener-Phase-B-Proposals",
            "Insights-Lessons-Monthly",
            "VaultWalker-Daily-Safe",
        ):
            j["no_agent"] = True
            j["deliver"] = "local"
            fixed.append(j.get("name"))
        if j.get("no_agent") and j.get("script") and j.get("last_error"):
            script = HERMES / "scripts" / Path(j["script"]).name
            if script.exists():
                j["last_error"] = None
                fixed.append("clear:" + str(j.get("name")))
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    jobs_path.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")
    log.append(f"4 agent_enabled={agent}")
    log.append(f"4 fixed={fixed}")

    # 5) K silo proposal-only
    kroot = Path(r"K:/Phronesis-Sovereign/Personal-Digital-Silo")
    candidates = []
    if kroot.exists():
        for p in kroot.rglob("*.md"):
            if len(candidates) > 400:
                break
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size > 500_000:
                continue
            rel = str(p.relative_to(kroot))
            if any(x in rel.lower() for x in ["archive", ".git", "node_modules"]):
                continue
            age = (datetime.now().timestamp() - st.st_mtime) / 86400
            if age > 60 and st.st_size > 500:
                candidates.append({"rel": rel, "age_d": round(age, 1), "size": st.st_size})
        candidates = sorted(candidates, key=lambda x: -x["age_d"])[:25]
        out = VAULT / "Operations" / "logs" / f"silo-phase-b-proposal-{TS}.md"
        body = [
            f"# Silo Phase B Proposal (read-only) {TS}",
            "",
            f"Root: `{kroot}`",
            "**No moves.**",
            "",
            f"Candidates stale>60d (top {len(candidates)}):",
            "",
        ]
        for c in candidates:
            body.append(f"- `{c['rel']}` (~{c['age_d']}d, {c['size']}b)")
        body += [
            "",
            "## Vault links",
            "- [[Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10]]",
            "",
        ]
        out.write_text("\n".join(body), encoding="utf-8")
        log.append(f"5 silo proposals n={len(candidates)}")
    else:
        log.append("5 K not mounted")

    r = subprocess.run(
        [sys.executable, str(HERMES / "scripts" / "gardener_phase_b_proposals.py"), "--stale-days", "21"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    log.append("phaseB " + ((r.stdout or "") + (r.stderr or ""))[-180:])

    rec = VAULT / "Operations" / "logs" / f"autonomous-five-{TS}.md"
    rec.write_text("# Autonomous five " + TS + "\n\n" + "\n".join(f"- {x}" for x in log) + "\n", encoding="utf-8")
    print("\n".join(log))
    print("receipt", rec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
