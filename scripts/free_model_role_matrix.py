#!/usr/bin/env python3
"""W2-P3 -- Bind Free-Model Creative Role Matrix into live fleet pick.

Loads Free-Model-Registry-v0.2.json (or path override) and maps
task_type / prompt signals -> preferred provider ids + ordered failover.
RP / adult-image remain hard-blocked (never free cloud).

Usage:
  from free_model_role_matrix import RoleMatrix
  rm = RoleMatrix.load()
  if rm.blocked(task_type=\"roleplay\"): ...
  preferred = rm.preferred_provider_ids(task_type=\"code\", prompt=...)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_REGISTRY = Path(r"D:\PhronesisVault\Operations\Free-Model-Registry-v0.2.json")
DEFAULT_MATRIX_MD = Path(
    r"D:\PhronesisVault\Operations\Free-Model-Creative-Role-Matrix-CANONICAL-2026-07-21.md"
)

# Hard defaults if registry missing/corrupt (keep aligned with Wave-1 matrix)
# 2026-08-03: aligned to live OpenRouter free smoke winners + local-first hop.
# 2026-08-06 smoke + failover pass: openrouter/free, gemma-4-26b, nemotron nano/omni/super,
# laguna-s, nano-9b, gpt-oss-20b OK; groq 403 disabled; gemma-31 429 disabled.
# 2026-09-03 tool-call smoke (3 q × 3 models): router 2/3, nemotron-omni 1/3, super 0/3.
_DEFAULT_ROLES: Dict[str, Dict[str, Any]] = {
    "classify": {
        "primary": ["openrouter-free-router", "openrouter-free-nemotron-omni", "openrouter-free-nemotron-super"],
        "failover": ["openrouter-free-laguna-s", "openrouter-free-gemma", "openrouter-free-nemotron-nano"],
        "signals": ["classify", "label", "triage", "route", "intent"],
    },
    "long_context": {
        "primary": ["openrouter-free-nemotron-super", "openrouter-free-nemotron-nano", "openrouter-free-gemma"],
        "failover": ["openrouter-free-router", "openrouter-free-gpt-oss-20b", "openrouter-free-nemotron-omni"],
        "signals": ["long", "summarize", "document", "context", "transcript", "book"],
    },
    "code": {
        "primary": ["openrouter-free-router", "openrouter-free-laguna-s", "openrouter-free-nemotron-omni"],
        "failover": ["openrouter-free-nemotron-super", "openrouter-free-gemma", "openrouter-free-gpt-oss-20b"],
        "signals": ["code", "python", "patch", "debug", "refactor", "typescript", "sql"],
    },
    "creative_prose": {
        "primary": ["openrouter-free-gemma", "openrouter-free-router", "openrouter-free-nemotron-omni"],
        "failover": ["openrouter-free-nemotron-super", "openrouter-free-nemotron-nano", "openrouter-free-gpt-oss-20b"],
        "signals": ["story", "prose", "narrative", "scene", "dialogue"],
    },
    "fast_chat": {
        "primary": ["openrouter-free-router", "openrouter-free-nemotron-omni", "openrouter-free-laguna-s"],
        "failover": ["openrouter-free-nemotron-super", "openrouter-free-gemma", "openrouter-free-nemotron-nano"],
        "signals": ["chat", "quick", "ping", "status"],
    },
    # Capability-aware depth layer: public research / structural survey
    "research": {
        "primary": [
            "openrouter-free-nemotron-omni",
            "openrouter-free-nemotron-super",
            "openrouter-free-gemma",
        ],
        "failover": [
            "openrouter-free-router",
            "openrouter-free-nemotron-nano",
            "openrouter-free-gpt-oss-20b",
        ],
        "signals": ["research", "survey", "literature", "open source", "benchmark", "compare models"],
    },
}

_BLOCKED_TASK_TYPES = frozenset(
    {
        "roleplay",
        "rp",
        "adult_image",
        "nsfw_image",
        "image_gen",
        "forge",
        "comfy",
        # Privacy / regulated / secrets / explicit -> local Qwythos only (never free/Grok body)
        "pii",
        "hipaa",
        "phi",
        "healthcare",
        "medical",
        "explicit",
        "nsfw",
        "adult",
        "sensitive",
        "local_only",
        "secret",
        "secrets",
        "credential",
        "credentials",
        "api_key",
        "auth",
    }
)

_BLOCKED_PROMPT_RE = re.compile(
    r"\b(roleplay|erp|nsfw\s*image|adult\s*image|generate\s*(a\s*)?(nude|porn)|"
    r"hipaa|phi\b|patient\s+chart|ssn|social\s+security)\b",
    re.I,
)


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def _uniq(seq: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in seq:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


@dataclass
class RoleMatrix:
    roles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    forbid_ids: List[str] = field(default_factory=list)
    source: str = "defaults"
    path: Optional[str] = None

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "RoleMatrix":
        p = Path(path) if path else DEFAULT_REGISTRY
        roles = {k: dict(v) for k, v in _DEFAULT_ROLES.items()}
        forbid: List[str] = [
            "groq-free-mixtral",
            "groq-free-llama",
            "openrouter-free-deepseek-v2",
            "openrouter-free-llama",
            "openrouter-free-gemma31",
        ]
        source = "defaults"
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                source = "registry_v0.2"
                # roles may live under roles / creative_roles / matrix.roles
                blob = (
                    raw.get("roles")
                    or raw.get("creative_roles")
                    or (raw.get("matrix") or {}).get("roles")
                    or {}
                )
                if isinstance(blob, dict) and blob:
                    for k, v in blob.items():
                        if not isinstance(v, dict):
                            continue
                        key = str(k).strip().lower().replace("-", "_").replace(" ", "_")
                        primary = _as_list(
                            v.get("primary") or v.get("primary_ids") or v.get("providers")
                        )
                        failover = _as_list(v.get("failover") or v.get("failover_ids"))
                        signals = _as_list(v.get("signals") or v.get("keywords"))
                        entry = roles.get(key, {})
                        if primary:
                            entry["primary"] = primary
                        if failover:
                            entry["failover"] = failover
                        if signals:
                            entry["signals"] = signals
                        # alias map: registry role name -> canonical
                        roles[key] = entry
                # common aliases
                alias = {
                    "classification": "classify",
                    "long": "long_context",
                    "longcontext": "long_context",
                    "coding": "code",
                    "coder": "code",
                    "creative": "creative_prose",
                    "prose": "creative_prose",
                    "fast": "fast_chat",
                    "chat": "fast_chat",
                }
                for a, canon in alias.items():
                    if a in roles and canon in roles:
                        # merge primary preference from alias if canon empty-ish
                        pass
                    elif a in roles and canon not in roles:
                        roles[canon] = roles[a]

                forb = (
                    raw.get("forbid_ids")
                    or raw.get("forbidden_ids")
                    or (raw.get("policy") or {}).get("forbid_ids")
                    or []
                )
                if isinstance(forb, list) and forb:
                    forbid = [str(x) for x in forb if x]
                # models list may mark disabled
                for m in raw.get("models") or raw.get("providers") or []:
                    if isinstance(m, dict) and m.get("enabled") is False and m.get("id"):
                        fid = str(m["id"])
                        if fid not in forbid:
                            forbid.append(fid)
            except Exception:
                source = "defaults_after_parse_error"
        overlay = Path(r"D:\HermesData\state\mma_free_roster.json")
        if overlay.is_file():
            try:
                ov = json.loads(overlay.read_text(encoding="utf-8"))
                ids = [str(x) for x in (ov.get("healthy_provider_ids") or []) if x]
                ids = [i for i in ids if i not in forbid]
                if ids:
                    fc = roles.setdefault(
                        "fast_chat",
                        {"primary": [], "failover": [], "signals": ["chat", "quick", "ping", "status"]},
                    )
                    # Keep existing primary; refresh failover with live free slots.
                    fc["failover"] = ids[:8]
                    source = str(source) + "+mma_overlay"
            except Exception:
                pass
        smoke_p = Path(r"D:\HermesData\state\free_toolcall_smoke_latest.json")
        if smoke_p.is_file():
            try:
                sm = json.loads(smoke_p.read_text(encoding="utf-8"))
                ranked = [str(x) for x in (sm.get("ranked_slots") or []) if x and x not in forbid]
                if ranked:
                    for role in ("fast_chat", "classify", "code"):
                        entry = roles.setdefault(
                            role, {"primary": [], "failover": [], "signals": []}
                        )
                        old = _as_list(entry.get("primary")) + _as_list(entry.get("failover"))
                        entry["primary"] = _uniq(ranked[:3])
                        rest = [x for x in old if x not in ranked[:3] and x not in forbid]
                        entry["failover"] = _uniq(rest)[:6]
                    source = str(source) + "+toolcall_smoke"
            except Exception:
                pass
        return cls(roles=roles, forbid_ids=forbid, source=source, path=str(p))

    def blocked(
        self,
        *,
        task_type: Optional[str] = None,
        prompt: str = "",
        routing: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """True when free/cloud body generation is forbidden (local Qwythos only).

        SSOT for content signals: proactive_routing_policy.contains_sensitive_content
        (PII / HIPAA / explicit / secrets). Roleplay + image lanes stay blocked here too.
        """
        tt = (task_type or "").strip().lower().replace("-", "_")
        if tt in _BLOCKED_TASK_TYPES:
            return f"blocked_task_type:{tt}"
        routing = routing or {}
        for k in ("task_type", "lane", "mode", "intent", "privacy"):
            v = str(routing.get(k) or "").strip().lower().replace("-", "_")
            if v in _BLOCKED_TASK_TYPES:
                return f"blocked_routing:{k}={v}"
        if routing.get("roleplay") or routing.get("is_roleplay") or routing.get("force_roleplay"):
            return "blocked_routing:roleplay_flag"
        if routing.get("local_only") or routing.get("force_local") or routing.get("pii"):
            return "blocked_routing:local_only_flag"
        # Shared sensitive gate (PII/HIPAA/explicit) -- do not reimplement elsewhere
        try:
            from proactive_routing_policy import contains_sensitive_content

            hit, reason = contains_sensitive_content(prompt or "")
            if hit:
                return f"blocked_sensitive:{reason}"
        except Exception:
            if prompt and _BLOCKED_PROMPT_RE.search(prompt[:2000]):
                return "blocked_prompt_signal"
        if prompt and _BLOCKED_PROMPT_RE.search(prompt[:2000]):
            return "blocked_prompt_signal"
        return None

    def classify_role(
        self,
        *,
        task_type: Optional[str] = None,
        prompt: str = "",
        capabilities: Optional[Sequence[str]] = None,
    ) -> str:
        tt = (task_type or "").strip().lower().replace("-", "_").replace(" ", "_")
        alias = {
            "classification": "classify",
            "label": "classify",
            "triage": "classify",
            "long": "long_context",
            "longcontext": "long_context",
            "summarize": "long_context",
            "summary": "long_context",
            "coding": "code",
            "coder": "code",
            "debug": "code",
            "creative": "creative_prose",
            "prose": "creative_prose",
            "story": "creative_prose",
            "fast": "fast_chat",
            "chat": "fast_chat",
            "research": "research",
            "survey": "research",
        }
        if tt in self.roles:
            return tt
        if tt in alias and alias[tt] in self.roles:
            return alias[tt]

        caps = {str(c).lower() for c in (capabilities or [])}
        if caps & {"code", "coding", "python"}:
            return "code"
        if caps & {"long-context", "long_context", "summarize"}:
            return "long_context"
        if caps & {"classify", "classification"}:
            return "classify"
        if caps & {"research", "survey"}:
            return "research"

        text = (prompt or "")[:4000].lower()
        best = "fast_chat"
        best_hits = 0
        for role, meta in self.roles.items():
            hits = 0
            for sig in meta.get("signals") or []:
                s = str(sig).lower()
                if s and s in text:
                    hits += 1
            # light heuristics
            if role == "code" and re.search(
                r"\b(def |class |import |```|traceback|typescript|refactor)\b", text
            ):
                hits += 2
            if role == "long_context" and len(text) > 2500:
                hits += 1
            if role == "classify" and re.search(
                r"\b(classify|label|category|triage|intent)\b", text
            ):
                hits += 2
            if role == "research" and re.search(
                r"\b(research|survey|literature|open source|benchmark)\b", text
            ):
                hits += 2
            if hits > best_hits:
                best_hits = hits
                best = role
        return best if best in self.roles else "fast_chat"

    def preferred_provider_ids(
        self,
        *,
        task_type: Optional[str] = None,
        prompt: str = "",
        capabilities: Optional[Sequence[str]] = None,
        role: Optional[str] = None,
    ) -> List[str]:
        # Local-only / RP / sensitive: never surface free cloud prefs
        if self.blocked(task_type=task_type, prompt=prompt):
            return []
        role_name = role or self.classify_role(
            task_type=task_type, prompt=prompt, capabilities=capabilities
        )
        meta = self.roles.get(role_name) or self.roles.get("fast_chat") or {}
        ordered: List[str] = []
        for pid in _as_list(meta.get("primary")) + _as_list(meta.get("failover")):
            if pid in self.forbid_ids:
                continue
            if pid not in ordered:
                ordered.append(pid)
        # Living ranks + capability fitness (depth layer; consumes Phase 1-2, no second plane)
        # Role membership still gates the set; fitness only sorts within it + appends usable
        return _reorder_by_living_rankings(
            ordered, forbid=self.forbid_ids, role=role_name
        )

    def rank_candidates(
        self,
        candidates: Sequence[Dict[str, Any]],
        *,
        task_type: Optional[str] = None,
        prompt: str = "",
        capabilities: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Re-order fleet candidate provider dicts by role preference."""
        preferred = self.preferred_provider_ids(
            task_type=task_type, prompt=prompt, capabilities=capabilities
        )
        role = self.classify_role(
            task_type=task_type, prompt=prompt, capabilities=capabilities
        )
        if not candidates:
            return []
        by_id = {str(c.get("id") or ""): c for c in candidates}
        out: List[Dict[str, Any]] = []
        seen = set()
        for pid in preferred:
            if pid in by_id and pid not in seen:
                c = dict(by_id[pid])
                c["_role"] = role
                c["_role_rank"] = len(out)
                out.append(c)
                seen.add(pid)
        for c in candidates:
            pid = str(c.get("id") or "")
            if pid in self.forbid_ids:
                continue
            if pid not in seen:
                cc = dict(c)
                cc["_role"] = role
                cc["_role_rank"] = len(out)
                out.append(cc)
                seen.add(pid)
        return out

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "path": self.path,
            "roles": {
                k: {
                    "primary": _as_list(v.get("primary")),
                    "failover": _as_list(v.get("failover")),
                }
                for k, v in self.roles.items()
            },
            "forbid_ids": list(self.forbid_ids),
        }


def _reorder_by_living_rankings(
    ordered: List[str],
    *,
    forbid: Optional[Sequence[str]] = None,
    role: Optional[str] = None,
) -> List[str]:
    """Sort role-preferred free ids via capability_rank on living ranks/envelopes.

    Fail-soft: if capability_rank unavailable, fall back to plain living rank order.
    """
    try:
        from capability_rank import reorder_provider_ids

        return reorder_provider_ids(
            list(ordered),
            role=role,
            forbid=forbid,
            append_usable_extra=True,
        )
    except Exception:
        pass
    # Fallback: plain living rank (pre-capability behavior)
    forbid_set = {str(x) for x in (forbid or [])}
    path = Path(r"D:\HermesData\state\free_model_rankings_latest.json")
    if not path.is_file():
        return ordered
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return ordered
    score_by: Dict[str, float] = {}
    rank_by: Dict[str, int] = {}
    usable_extra: List[str] = []
    for row in raw.get("free_ranked") or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        pid = str(row["id"])
        if pid in forbid_set:
            continue
        if row.get("pool_status") == "cooldown":
            forbid_set.add(pid)
            continue
        if row.get("pool_status") == "usable":
            score_by[pid] = float(row.get("score") or 0.0)
            rank_by[pid] = int(row.get("rank") or 999)
            if pid not in ordered:
                usable_extra.append(pid)
    if not score_by:
        return ordered

    def key(pid: str) -> tuple:
        if pid in rank_by:
            return (0, rank_by[pid], -score_by.get(pid, 0.0), pid)
        return (1, 999, 0.0, pid)

    core = sorted([p for p in ordered if p not in forbid_set], key=key)
    for pid in sorted(usable_extra, key=key):
        if pid not in core:
            core.append(pid)
    return core


def load_role_matrix(path: Optional[Path] = None) -> RoleMatrix:
    return RoleMatrix.load(path)


if __name__ == "__main__":
    rm = RoleMatrix.load()
    print(json.dumps(rm.to_public_dict(), indent=2))
    for tt, prompt in [
        ("classify", "classify this intent"),
        ("code", "fix this python traceback"),
        ("long_context", "summarize the following document " + ("x" * 100)),
        ("roleplay", "you are alice"),
    ]:
        print(
            tt,
            "blocked=",
            rm.blocked(task_type=tt, prompt=prompt),
            "role=",
            rm.classify_role(task_type=tt, prompt=prompt),
            "prefs=",
            rm.preferred_provider_ids(task_type=tt, prompt=prompt),
        )
