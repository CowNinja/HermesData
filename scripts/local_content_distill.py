#!/usr/bin/env python3
"""
local_content_distill.py — Holistic local content distillation pipeline.

Universal adapter for any information: wisdom, research, silo ingest, narratives.
Routes via MoE task_type map (metadata → 8083, synthesis → 8082).

Usage:
  python local_content_distill.py --input path/to/source.md --mode wisdom
  python local_content_distill.py --text "..." --mode research --sample-name my-note
  python local_content_distill.py --input doc.md --mode ingest --steps metadata,summary

Modes (from MoE-Task-Type-Map pipeline_modes): wisdom | research | ingest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERMES_SCRIPTS = Path(r"D:\HermesData\scripts")
VAULT = Path(r"D:\PhronesisVault")
sys.path.insert(0, str(HERMES_SCRIPTS))
sys.path.insert(0, str(VAULT / "scripts"))

from router_bridge import bridge_dispatch

PROMPTS_PATH = HERMES_SCRIPTS / "content_distill_prompt_library.md"
MOE_MAP_PATH = VAULT / "Operations" / "MoE-Task-Type-Map-v0.1.json"
TEMP_DIR = Path(r"D:\HermesData\temp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

STEP_TASK_TYPES = {
    "metadata": "metadata_extraction",
    "summary": "synthesis",
    "artifact": "synthesis",
}

STEP_MODES = {
    "wisdom": "artifact (wisdom / growth blueprint mode)",
    "research": "artifact (research mode)",
}


def load_moe_pipeline_modes() -> Dict[str, Any]:
    if MOE_MAP_PATH.exists():
        try:
            data = json.loads(MOE_MAP_PATH.read_text(encoding="utf-8-sig"))
            return data.get("pipeline_modes") or {}
        except Exception:
            pass
    return {
        "wisdom": {"steps": ["metadata", "summary", "artifact"]},
        "research": {"steps": ["metadata", "summary", "artifact"]},
        "ingest": {"steps": ["metadata", "summary"]},
    }


def load_prompts() -> Dict[str, str]:
    if not PROMPTS_PATH.exists():
        raise FileNotFoundError(f"Prompt library missing: {PROMPTS_PATH}")
    content = PROMPTS_PATH.read_text(encoding="utf-8")
    prompts: Dict[str, str] = {}
    current: Optional[str] = None
    buf: List[str] = []
    in_fence = False
    for line in content.splitlines():
        m = re.match(r"^## Step:\s*(\w+)", line.strip())
        if m:
            if current and buf:
                prompts[current] = "\n".join(buf).strip()
            current = m.group(1).lower()
            buf = []
            in_fence = False
            continue
        if line.strip() == "```prompt":
            in_fence = True
            continue
        if in_fence and line.strip() == "```":
            in_fence = False
            continue
        if in_fence and current:
            buf.append(line)
    if current and buf:
        prompts[current] = "\n".join(buf).strip()
    # Sub-artifact variants
    for mode, header in STEP_MODES.items():
        key = f"artifact_{mode}"
        idx = content.find(f"## Step: {header}")
        if idx >= 0:
            chunk = content[idx:]
            fence = re.search(r"```prompt\n(.*?)```", chunk, re.DOTALL)
            if fence:
                prompts[key] = fence.group(1).strip()
    return prompts


def _routing_meta(res: Dict[str, Any]) -> Dict[str, Any]:
    prov = res.get("provenance") or {}
    return {
        "tier": res.get("tier") or prov.get("escalation_tier"),
        "port_hint": prov.get("port_hint"),
        "model": res.get("model"),
        "success": res.get("success"),
        "quality_warning": res.get("quality_warning") or prov.get("quality_warning"),
        "task_type_map": prov.get("moe_task_type_map") or prov.get("task_type_map"),
    }


def run_pipeline(
    text: str,
    sample_name: str = "content",
    mode: str = "wisdom",
    steps: Optional[List[str]] = None,
    max_chars: int = 8000,
    prefer: str = "vault",
    force_local: bool = True,
    synthesis_task_type: str = "synthesis",
) -> Dict[str, Any]:
    prompts = load_prompts()
    modes = load_moe_pipeline_modes()
    mode_cfg = modes.get(mode) or modes.get("wisdom", {})
    step_list = steps or mode_cfg.get("steps") or ["metadata", "summary", "artifact"]

    excerpt = text[:max_chars]
    results: Dict[str, Any] = {
        "sample": sample_name,
        "mode": mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps_run": step_list,
        "steps": {},
    }

    for step in step_list:
        task_type = STEP_TASK_TYPES.get(step, synthesis_task_type)
        if step in ("summary", "artifact"):
            task_type = synthesis_task_type
        if step == "artifact":
            prompt_key = f"artifact_{mode}" if f"artifact_{mode}" in prompts else "artifact"
        else:
            prompt_key = step
        template = prompts.get(prompt_key, prompts.get(step, f"Process:\n{{TEXT}}"))
        prompt = template.replace("{TEXT}", excerpt).replace("{EXCERPT}", excerpt[:4000])

        print(f"[{sample_name}] step={step} task_type={task_type} prefer={prefer} force_local={force_local} ...")
        res = bridge_dispatch(
            prompt,
            task_type=task_type,
            platform="local_content_distill",
            force_local=force_local,
            prefer=prefer,
            context_tokens_estimate=len(excerpt) // 3 + 2000,
            modality="text",
        )
        meta = _routing_meta(res)
        results["steps"][step] = {
            **meta,
            "response_preview": (res.get("response") or "")[:1500],
            "response_full": res.get("response") or "",
        }
        if meta.get("quality_warning"):
            print(f"  WARN: {meta['quality_warning']}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = TEMP_DIR / f"content-distill-{sample_name}-{mode}-{ts}.md"
    lines = [
        f"# Local Content Distill — {sample_name}",
        f"**Mode:** {mode} | **Time:** {results['timestamp']}",
        "",
    ]
    for step, data in results["steps"].items():
        lines.append(f"## {step.title()} (tier={data.get('tier')} port={data.get('port_hint')})")
        if data.get("quality_warning"):
            lines.append(f"**Quality warning:** {data['quality_warning']}")
        lines.append(data.get("response_full") or data.get("response_preview", ""))
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    results["artifact"] = str(out_path)
    print(f"Saved: {out_path}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Holistic local content distillation")
    parser.add_argument("--input", help="Source file path")
    parser.add_argument("--text", help="Inline text")
    parser.add_argument("--sample-name", default="content")
    parser.add_argument("--mode", default="wisdom", choices=["wisdom", "research", "ingest"])
    parser.add_argument("--steps", help="Comma-separated: metadata,summary,artifact")
    parser.add_argument("--max-chars", type=int, default=8000)
    parser.add_argument("--prefer", default="vault", choices=["auto", "ollama", "vault"],
                        help="Router bridge backend order (cron: vault for MoE 8082)")
    parser.add_argument("--force-local", action="store_true", default=True,
                        help="Fail closed to Grok (default: true)")
    parser.add_argument("--no-force-local", action="store_false", dest="force_local")
    parser.add_argument("--task-type", default="synthesis", dest="synthesis_task_type",
                        help="task_type for synthesis steps (maps to local_warm/8082)")
    parser.add_argument("--context-prefix", default="", help="Prepended framing from ingestion registry")
    args = parser.parse_args()

    if args.input:
        text = Path(args.input).read_text(encoding="utf-8", errors="ignore")
    elif args.text:
        text = args.text
    else:
        text = "Sample content for distillation."

    if args.context_prefix.strip():
        text = f"{args.context_prefix.strip()}\n\n---\n\n{text}"

    steps = [s.strip() for s in args.steps.split(",")] if args.steps else None
    res = run_pipeline(
        text, args.sample_name, args.mode, steps, args.max_chars,
        prefer=args.prefer, force_local=args.force_local,
        synthesis_task_type=args.synthesis_task_type,
    )
    print("\n=== Pipeline Summary ===")
    print(json.dumps({k: v for k, v in res.items() if k != "steps"}, indent=2))
    for step, data in res.get("steps", {}).items():
        print(f"  {step}: tier={data.get('tier')} warn={data.get('quality_warning')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
