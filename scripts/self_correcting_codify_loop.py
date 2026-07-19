#!/usr/bin/env python3
"""Self-correcting codify loop template — safe defaults.

Pattern (CANONICAL):
  PROPOSE → VERIFY (non-LLM) → CRITIQUE (must cite verify) → GATE → COMMIT/ABORT

Guardrails:
  - dry-run default (no commit unless --commit)
  - max 3 iterations
  - critique without verify evidence → ABORT
  - irreversible actions never auto (purge / VW LIVE / gateway)
  - trajectory JSONL always written
  - $0 Grok in loop body; print escalate hint only

Usage:
  python D:/HermesData/scripts/self_correcting_codify_loop.py --demo
  python D:/HermesData/scripts/self_correcting_codify_loop.py --demo --commit
  python D:/HermesData/scripts/self_correcting_codify_loop.py --list-hooks

Canon:
  D:/PhronesisVault/Operations/Self-Correcting-Codify-Loops-Safe-Surfaces-CANONICAL-2026-07-18.md
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
TRAJ_DIR = HERMES / "data" / "self_correcting_loops"
LOG_DIR = VAULT / "Operations" / "logs"
CANON = "Operations/Self-Correcting-Codify-Loops-Safe-Surfaces-CANONICAL-2026-07-18.md"
MAX_ITERS_DEFAULT = 3

GateDecision = Literal["PASS", "RETRY", "ESCALATE", "ABORT"]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Candidate:
    id: str
    kind: str
    payload: dict[str, Any]
    iteration: int = 0


@dataclass
class VerifyResult:
    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    evidence: str = ""

    def all_evidence(self) -> str:
        if self.evidence:
            return self.evidence
        parts = []
        for c in self.checks:
            parts.append(f"{c.get('name')}={'PASS' if c.get('ok') else 'FAIL'}:{c.get('detail', '')}")
        return "; ".join(parts)


@dataclass
class Critique:
    ok: bool
    notes: str
    cites_verify: bool
    raw: str = ""


@dataclass
class GateOutcome:
    decision: GateDecision
    reason: str


@dataclass
class Receipt:
    committed: bool
    path: str | None
    message: str


# ─── Demo hooks (replace per surface) ───────────────────────────────────────


def demo_propose(ctx: dict[str, Any]) -> Candidate:
    n = int(ctx.get("iteration", 0))
    # Intentionally weak on iter 0, stronger later — shows retry path
    text = "entity: Abigail (ambiguous)" if n == 0 else "entity: Abigail Tulis (case party; VA medical context)"
    return Candidate(
        id=f"demo-{n}",
        kind="entity_codify_demo",
        payload={"text": text, "domain_guess": "Family" if n == 0 else "Medical"},
        iteration=n,
    )


def demo_verify(candidate: Candidate) -> VerifyResult:
    """Deterministic ground truth — NEVER an LLM."""
    text = str(candidate.payload.get("text", ""))
    checks = []
    has_full_name = "Tulis" in text
    checks.append(
        {
            "name": "full_name_present",
            "ok": has_full_name,
            "detail": "requires surname evidence before promote",
        }
    )
    domain = candidate.payload.get("domain_guess")
    # Friends≠Family≠Medical disambiguation stub
    domain_ok = domain in {"Medical", "Projects", "Family"} and not (
        domain == "Family" and "case" in text.lower()
    )
    checks.append(
        {
            "name": "domain_plausible",
            "ok": domain_ok,
            "detail": f"domain_guess={domain}",
        }
    )
    ok = all(c["ok"] for c in checks)
    evidence = "; ".join(f"{c['name']}={'PASS' if c['ok'] else 'FAIL'}" for c in checks)
    return VerifyResult(ok=ok, checks=checks, evidence=evidence)


def demo_critique(candidate: Candidate, verify: VerifyResult) -> Critique:
    """
    Critic may be local LLM later — but MUST cite verify.evidence.
    This default is rule-based (safe offline).
    """
    ev = verify.all_evidence()
    if not ev:
        return Critique(ok=False, notes="no verify evidence", cites_verify=False, raw="")
    if verify.ok:
        notes = f"ACCEPT cite=[{ev}] payload looks promote-ready"
        return Critique(ok=True, notes=notes, cites_verify=True, raw=notes)
    notes = f"REJECT cite=[{ev}] strengthen identity before promote"
    return Critique(ok=False, notes=notes, cites_verify=True, raw=notes)


def demo_commit(candidate: Candidate, dry_run: bool) -> Receipt:
    out = TRAJ_DIR / "demo_commits.jsonl"
    TRAJ_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"at": utc(), "candidate": asdict(candidate), "dry_run": dry_run}, ensure_ascii=False)
    if dry_run:
        return Receipt(committed=False, path=str(out), message="dry-run: would append commit line")
    with out.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return Receipt(committed=True, path=str(out), message="appended demo commit")


# ─── Core engine ────────────────────────────────────────────────────────────


def gate(verify: VerifyResult, critique: Critique) -> GateOutcome:
    if not critique.cites_verify:
        return GateOutcome("ABORT", "critique missing verify citation (ungrounded)")
    if verify.ok and critique.ok:
        return GateOutcome("PASS", "verify+critique ok")
    if not verify.ok and critique.cites_verify:
        return GateOutcome("RETRY", "verify failed; retry propose")
    return GateOutcome("ESCALATE", "gray — prepare_grok_escalation_brief")


def run_loop(
    *,
    name: str,
    propose: Callable[[dict[str, Any]], Candidate],
    verify: Callable[[Candidate], VerifyResult],
    critique: Callable[[Candidate, VerifyResult], Critique],
    commit: Callable[[Candidate, bool], Receipt],
    max_iters: int = MAX_ITERS_DEFAULT,
    do_commit: bool = False,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = dict(ctx or {})
    traj: list[dict[str, Any]] = []
    final: dict[str, Any] = {"name": name, "decision": "ABORT", "at": utc()}

    for i in range(max_iters):
        ctx["iteration"] = i
        cand = propose(ctx)
        v = verify(cand)
        c = critique(cand, v)
        g = gate(v, c)
        step = {
            "iteration": i,
            "candidate": asdict(cand),
            "verify": asdict(v),
            "critique": asdict(c),
            "gate": asdict(g),
        }
        traj.append(step)

        if g.decision == "PASS":
            receipt = commit(cand, dry_run=not do_commit)
            step["receipt"] = asdict(receipt)
            final.update(
                {
                    "decision": "PASS",
                    "committed": receipt.committed,
                    "receipt": asdict(receipt),
                    "iterations": i + 1,
                }
            )
            break
        if g.decision == "ABORT":
            final.update({"decision": "ABORT", "reason": g.reason, "iterations": i + 1})
            break
        if g.decision == "ESCALATE":
            final.update(
                {
                    "decision": "ESCALATE",
                    "reason": g.reason,
                    "iterations": i + 1,
                    "hint": (
                        "python D:/HermesData/scripts/prepare_grok_escalation_brief.py "
                        f'--topic "{name} gate gray"'
                    ),
                }
            )
            break
        # RETRY continues
    else:
        final.update({"decision": "ABORT", "reason": f"max_iters={max_iters}", "iterations": max_iters})

    final["trajectory"] = traj
    final["canon"] = CANON
    final["commit_mode"] = "commit" if do_commit else "dry-run"

    TRAJ_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out_jsonl = TRAJ_DIR / f"{name}.jsonl"
    with out_jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(final, ensure_ascii=False) + "\n")
    latest = LOG_DIR / f"self-correcting-loop-{name}-latest.md"
    latest.write_text(
        "\n".join(
            [
                f"# Self-correcting loop — {name}",
                f"",
                f"- **at:** {final['at']}",
                f"- **decision:** {final['decision']}",
                f"- **mode:** {final['commit_mode']}",
                f"- **iterations:** {final.get('iterations')}",
                f"- **trajectory:** `{out_jsonl}`",
                f"- **canon:** [[{CANON.replace('.md', '')}]]",
                f"- **escalate_hint:** {final.get('hint', 'n/a')}",
                f"",
                f"## Vault links",
                f"- [[{CANON.replace('.md', '')}]]",
                f"",
            ]
        ),
        encoding="utf-8",
    )
    final["log_md"] = str(latest)
    final["log_jsonl"] = str(out_jsonl)
    return final


def main() -> int:
    ap = argparse.ArgumentParser(description="Safe self-correcting codify loop template")
    ap.add_argument("--demo", action="store_true", help="Run built-in entity codify demo")
    ap.add_argument("--commit", action="store_true", help="Actually commit (default dry-run)")
    ap.add_argument("--max-iters", type=int, default=MAX_ITERS_DEFAULT)
    ap.add_argument("--list-hooks", action="store_true")
    ap.add_argument("--json", action="store_true", help="Print full result JSON")
    args = ap.parse_args()

    if args.list_hooks:
        print(
            json.dumps(
                {
                    "hooks": ["propose", "verify", "critique", "gate", "commit"],
                    "guardrails": {
                        "dry_run_default": True,
                        "max_iters": MAX_ITERS_DEFAULT,
                        "critique_must_cite_verify": True,
                        "no_grok_in_body": True,
                        "irreversible": ["purge", "vw_live", "gateway_policy"],
                    },
                    "canon": CANON,
                },
                indent=2,
            )
        )
        return 0

    if not args.demo:
        print("Use --demo to exercise template, or import run_loop() from another script.", file=sys.stderr)
        print("Canon:", CANON)
        return 2

    result = run_loop(
        name="demo_entity_codify",
        propose=demo_propose,
        verify=demo_verify,
        critique=demo_critique,
        commit=demo_commit,
        max_iters=args.max_iters,
        do_commit=args.commit,
    )

    # Human-short summary (cron-friendly)
    print(
        f"SELF_CORRECT decision={result['decision']} "
        f"iters={result.get('iterations')} mode={result['commit_mode']} "
        f"log={result.get('log_md')}"
    )
    if result["decision"] == "ESCALATE":
        print(result.get("hint", ""))
    if args.json:
        # trajectory can be large; still ok for demo
        print(json.dumps({k: v for k, v in result.items() if k != "trajectory"}, indent=2))
        print(json.dumps({"trajectory_len": len(result.get("trajectory", []))}))
    return 0 if result["decision"] in {"PASS", "ESCALATE"} else 1


if __name__ == "__main__":
    sys.exit(main())
