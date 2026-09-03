#!/usr/bin/env python3
"""OpenAI function schemas + safe terminal rewrite for atomic 9B tools.

9B emits key-value tool_calls (vault_search / service_manager / system_telemetry)
instead of raw PowerShell. The proxy merges these schemas into the llama tools
list. If the gateway has not registered the name yet, outbound calls rewrite to
a known-safe python CLI via the existing terminal tool.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

TOOLS_DIR = Path(__file__).resolve().parent
VENV_PY = Path(r"D:\HermesData\hermes-agent\venv\Scripts\python.exe")
SYS_PY = Path(sys.executable)

ATOMIC_NAMES = ("vault_search", "service_manager", "system_telemetry")

_SCRIPT = {
    "vault_search": TOOLS_DIR / "tool_vault_search.py",
    "service_manager": TOOLS_DIR / "tool_service_manager.py",
    "system_telemetry": TOOLS_DIR / "tool_system_telemetry.py",
}

OPENAI_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "vault_search",
            "description": (
                "Search D:\\PhronesisVault and K:\\Phronesis-Sovereign with ripgrep/FTS. "
                "Returns JSON hits. Banned silos (Navy/Medical/Patient-BLOOM/RP sandbox) "
                "are skipped. Prefer this over raw PowerShell or recursive dir walks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Literal or regex needle. Keep short.",
                    },
                    "roots": {
                        "type": "string",
                        "enum": ["both", "vault", "attic"],
                        "description": "both (default), vault=D:\\PhronesisVault, attic=K:\\Phronesis-Sovereign.",
                    },
                    "max_hits": {
                        "type": "integer",
                        "description": "Cap hits (default 24, max 80).",
                    },
                    "glob": {
                        "type": "string",
                        "description": "Optional rg glob, e.g. *.md",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "service_manager",
            "description": (
                "Safe query/restart of local daemons: gateway :8642, proxy :8091, "
                "optional hybrid :8092, Ollama :11434. Default action=status. "
                "Never restarts llama-server :8090. Restart requires confirm=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "restart"],
                        "description": "status (default) or restart.",
                    },
                    "target": {
                        "type": "string",
                        "enum": [
                            "all",
                            "gateway",
                            "proxy",
                            "ollama",
                            "8092",
                            "8642",
                            "8091",
                            "11434",
                        ],
                        "description": "Which daemon. all=status only.",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to restart. :8090 is never restarted.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_telemetry",
            "description": (
                "Clean JSON snapshot: CPU, 128GB RAM, RTX 3060 VRAM, C:/D:/K: drive "
                "capacities. Prefer this over Get-PSDrive / nvidia-smi PowerShell."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "include_top_procs": {
                        "type": "boolean",
                        "description": "If true, include top 5 RSS processes.",
                    }
                },
                "required": [],
            },
        },
    },
]


def openai_tool_schemas() -> List[Dict[str, Any]]:
    return [dict(s) for s in OPENAI_SCHEMAS]


def tool_names_from_schemas(tools: Optional[Iterable[Any]]) -> set[str]:
    names: set[str] = set()
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if isinstance(t.get("function"), dict) else t
        n = fn.get("name") if isinstance(fn, dict) else None
        if n:
            names.add(str(n))
    return names


def merge_atomic_schemas(tools: Optional[List[Any]]) -> List[Dict[str, Any]]:
    existing: List[Dict[str, Any]] = [t for t in (tools or []) if isinstance(t, dict)]
    have = tool_names_from_schemas(existing)
    for schema in OPENAI_SCHEMAS:
        name = (schema.get("function") or {}).get("name")
        if name and name not in have:
            existing.append(dict(schema))
    return existing


def _python_exe() -> str:
    if VENV_PY.is_file():
        return str(VENV_PY)
    return str(SYS_PY)


def terminal_command_for(name: str, arguments: Dict[str, Any]) -> str:
    script = _SCRIPT.get(name)
    if not script or not script.is_file():
        raise ValueError(f"unknown atomic tool {name}")
    payload = json.dumps(arguments or {}, separators=(",", ":"))
    # PowerShell-safe: python -c is worse; pass --json with single-quoted blob via python.
    return f"{_python_exe()} {script} --json {json.dumps(payload)}"


def rewrite_tool_call_if_unregistered(
    tc: Dict[str, Any],
    gateway_names: set[str],
) -> Dict[str, Any]:
    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    name = str(fn.get("name") or "")
    if name not in ATOMIC_NAMES:
        return tc
    if name in gateway_names:
        return tc
    raw_args = fn.get("arguments") or "{}"
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except Exception:
            args = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}
    if not isinstance(args, dict):
        args = {}
    cmd = terminal_command_for(name, args)
    out = dict(tc)
    out["type"] = "function"
    out["function"] = {
        "name": "terminal",
        "arguments": json.dumps({"command": cmd}, separators=(",", ":")),
    }
    return out


def rewrite_tool_calls(
    tool_calls: Optional[List[Dict[str, Any]]],
    gateway_names: set[str],
) -> Optional[List[Dict[str, Any]]]:
    if not tool_calls:
        return tool_calls
    return [rewrite_tool_call_if_unregistered(tc, gateway_names) for tc in tool_calls]


if __name__ == "__main__":
    print(json.dumps({"tools": ATOMIC_NAMES, "n_schemas": len(OPENAI_SCHEMAS)}))
