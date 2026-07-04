#!/usr/bin/env python3
"""
external_fleet_manager.py — Tier 1.5 Opportunistic Fleet manager.

Configuration-driven dispatch to free compute (LLM APIs) and context (search APIs).
Registry: D:\\HermesData\\config\\fleet_registry.yaml

Usage:
  from external_fleet_manager import FleetManager
  fm = FleetManager()
  fm.dispatch_compute("Explain X", capabilities=["reasoning"])
  fm.dispatch_context("latest AI news", capabilities=["real-time-search"])
  fm.run_health_cycle()
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore

REGISTRY_PATH = Path(r"D:\HermesData\config\fleet_registry.yaml")
HEALTH_LOG = Path(r"D:\PhronesisVault\Operations\logs\fleet-health.jsonl")
DISPATCH_LOG = Path(r"D:\PhronesisVault\Operations\logs\fleet-dispatch.jsonl")
HEALTH_STATE = Path(r"D:\PhronesisVault\Operations\logs\fleet-health-state.json")

try:
    from phronesis_env import bootstrap_env as _bootstrap_env
except ImportError:
    def _bootstrap_env() -> None:
        pass

_bootstrap_env()

TIER_NAME = "opportunistic_fleet"


def _telemetry_monitor():
    try:
        from sovereign_telemetry_monitor import get_telemetry_monitor
        return get_telemetry_monitor()
    except Exception:
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(path: Path, event: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")
    except Exception:
        pass


def _resolve_api_key(provider: Dict[str, Any]) -> Optional[str]:
    env_name = str(provider.get("api_key_env") or "").strip()
    if env_name:
        val = os.environ.get(env_name, "").strip()
        if val:
            return val
    direct = str(provider.get("api_key") or "").strip()
    return direct or None


class FleetManager:
    """Universal Opportunistic Fleet — compute + context from YAML registry."""

    def __init__(self, registry_path: Path = REGISTRY_PATH):
        self.registry_path = registry_path
        self._registry: Dict[str, Any] = {}
        self._health_state: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        self._registry = self._load_registry()
        self._health_state = self._load_health_state()

    def _load_registry(self) -> Dict[str, Any]:
        if not self.registry_path.is_file():
            return {"policy": {"enabled": False}, "compute_providers": [], "context_providers": []}
        text = self.registry_path.read_text(encoding="utf-8")
        if yaml is not None:
            data = yaml.safe_load(text) or {}
            return data if isinstance(data, dict) else {}
        return json.loads(text) if text.strip().startswith("{") else {}

    def _load_health_state(self) -> Dict[str, Any]:
        if HEALTH_STATE.is_file():
            try:
                return json.loads(HEALTH_STATE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"providers": {}}

    def _save_health_state(self) -> None:
        HEALTH_STATE.parent.mkdir(parents=True, exist_ok=True)
        HEALTH_STATE.write_text(json.dumps(self._health_state, indent=2), encoding="utf-8")

    def save_registry(self) -> None:
        """Persist in-memory registry to YAML."""
        if yaml is None:
            raise RuntimeError("pyyaml_required")
        self.registry_path.write_text(
            yaml.safe_dump(self._registry, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    @staticmethod
    def _provider_lifecycle(provider: Dict[str, Any]) -> str:
        lc = str(provider.get("lifecycle") or "").strip().lower()
        if lc:
            return lc
        if provider.get("enabled", True):
            return "enabled"
        return "disabled"

    @staticmethod
    def _is_routable(provider: Dict[str, Any]) -> bool:
        """Production routing: enabled lifecycle only (never sandbox/disabled)."""
        return (
            provider.get("enabled", True)
            and FleetManager._provider_lifecycle(provider) in ("enabled", "")
        )

    @property
    def enabled(self) -> bool:
        return bool((self._registry.get("policy") or {}).get("enabled", True))

    def list_providers(
        self,
        kind: Optional[str] = None,
        capability: Optional[str] = None,
        *,
        healthy_only: bool = False,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        kinds = []
        if kind in (None, "compute"):
            kinds.append(("compute", self._registry.get("compute_providers") or []))
        if kind in (None, "context"):
            kinds.append(("context", self._registry.get("context_providers") or []))
        for pkind, providers in kinds:
            for p in providers:
                if not isinstance(p, dict) or not self._is_routable(p):
                    continue
                caps = [str(c).lower() for c in (p.get("capabilities") or [])]
                if capability and capability.lower() not in caps:
                    continue
                pid = str(p.get("id") or "")
                health = (self._health_state.get("providers") or {}).get(pid, {})
                if healthy_only and health.get("status") == "down":
                    continue
                if p.get("api_key_env") and not _resolve_api_key(p):
                    continue
                tel = _telemetry_monitor()
                if tel and pid and tel.is_blacklisted(pid):
                    continue
                eff_priority = int(p.get("priority") or 0)
                if tel and pid:
                    eff_priority = tel.effective_priority(pid, eff_priority)
                out.append({**p, "_kind": pkind, "_health": health, "_effective_priority": eff_priority})
        out.sort(key=lambda x: (-int(x.get("_effective_priority") or x.get("priority") or 0), str(x.get("id"))))
        return out

    def list_shadow_providers(
        self,
        kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Phase B0: all enabled registry providers for health probes (no routing)."""
        out: List[Dict[str, Any]] = []
        kinds: List[Tuple[str, str]] = []
        if kind in (None, "compute"):
            kinds.append(("compute", "compute_providers"))
        if kind in (None, "context"):
            kinds.append(("context", "context_providers"))
        for pkind, section in kinds:
            for p in self._registry.get(section) or []:
                if not isinstance(p, dict) or not p.get("enabled", True):
                    continue
                pid = str(p.get("id") or "")
                health = (self._health_state.get("providers") or {}).get(pid, {})
                missing_key = bool(p.get("api_key_env") and not _resolve_api_key(p))
                out.append(
                    {
                        **p,
                        "_kind": pkind,
                        "_health": health,
                        "_missing_key": missing_key,
                    }
                )
        out.sort(key=lambda x: (-int(x.get("priority") or 0), str(x.get("id"))))
        return out

    def select_provider(
        self,
        kind: str,
        capabilities: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        ranked = self.select_provider_candidates(kind, capabilities)
        return ranked[0] if ranked else None

    def select_provider_candidates(
        self,
        kind: str,
        capabilities: Optional[List[str]] = None,
        *,
        healthy_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Ranked provider list for failover — highest score first."""
        caps = [str(c).lower() for c in (capabilities or [])]
        candidates = self.list_providers(kind=kind, healthy_only=healthy_only)
        if not candidates and healthy_only:
            candidates = self.list_providers(kind=kind, healthy_only=False)
        if not caps:
            return candidates
        scored: List[Tuple[int, Dict[str, Any]]] = []
        for p in candidates:
            pcaps = {str(c).lower() for c in (p.get("capabilities") or [])}
            score = sum(2 for c in caps if c in pcaps) + int(p.get("_effective_priority") or p.get("priority") or 0)
            if any(c in pcaps for c in caps):
                scored.append((score, p))
        if not scored:
            return candidates
        scored.sort(key=lambda x: (-x[0], str(x[1].get("id"))))
        return [p for _, p in scored]

    def _max_provider_retries(self) -> int:
        try:
            return max(1, int((self._registry.get("policy") or {}).get("max_retries_per_provider") or 2))
        except Exception:
            return 2

    def infer_capabilities(
        self,
        prompt: str,
        task_type: Optional[str] = None,
        triggers: Optional[List[str]] = None,
    ) -> List[str]:
        caps: List[str] = []
        triggers = triggers or []
        p = (prompt or "").lower()
        tt = (task_type or "").lower()

        if any(t in triggers for t in ("latest_external_knowledge", "real-time-search")):
            caps.append("real-time-search")
        if any(k in p for k in ("search", "latest", "current", "today", "news", "real-time")):
            caps.append("real-time-search")
        if any(t in triggers for t in ("massive_context_window", "heavy_tool_chaining")):
            caps.extend(["reasoning", "70b-reasoning"])
        if any(k in p for k in ("architect", "design", "prove", "multi-step")):
            caps.append("reasoning")
        if tt in ("code", "coding"):
            caps.append("code")
        if tt in ("synthesis", "summarize", "distill", "research"):
            caps.append("synthesis")
        if not caps:
            caps.append("synthesis")
        return list(dict.fromkeys(caps))

    def health_check(self, provider_id: str) -> Dict[str, Any]:
        provider = self._find_provider_any(provider_id)
        if not provider:
            return {"ok": False, "error": "provider_not_found", "id": provider_id}
        kind = provider.get("_kind") or "compute"
        started = time.time()
        try:
            if kind == "compute":
                result = self._probe_compute(provider)
            else:
                result = self._probe_context(provider)
            elapsed = round(time.time() - started, 2)
            status = "up" if result.get("ok") else "down"
            entry = {
                "status": status,
                "last_check": _utc_now(),
                "latency_sec": elapsed,
                "detail": result,
            }
            self._health_state.setdefault("providers", {})[provider_id] = entry
            self._save_health_state()
            _log(HEALTH_LOG, {"event": "health_check", "id": provider_id, **entry})
            return {"ok": result.get("ok", False), "id": provider_id, **entry}
        except Exception as exc:
            entry = {"status": "down", "last_check": _utc_now(), "error": str(exc)}
            self._health_state.setdefault("providers", {})[provider_id] = entry
            self._save_health_state()
            return {"ok": False, "id": provider_id, **entry}

    def _infer_provider_kind(self, provider: Dict[str, Any]) -> str:
        api_mode = str(provider.get("api_mode") or "")
        if api_mode in (
            "duckduckgo_instant",
            "brave_search",
            "serper_search",
            "generic_search",
            "searxng",
        ):
            return "context"
        url = str(provider.get("base_url") or "").lower()
        if any(h in url for h in ("search", "duckduckgo", "brave", "serper", "searx")):
            return "context"
        return "compute"

    def _find_provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        found = self._find_provider_any(provider_id)
        if found and self._is_routable(found):
            return found
        return None

    def _find_provider_any(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """Lookup in production + sandbox sections (procurement lifecycle)."""
        for section, default_kind in (
            ("compute_providers", "compute"),
            ("context_providers", "context"),
            ("sandbox_providers", None),
        ):
            for p in self._registry.get(section) or []:
                if p.get("id") == provider_id:
                    kind = default_kind or self._infer_provider_kind(p)
                    return {**p, "_kind": kind, "_section": section}
        return None

    def list_sandbox_providers(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for p in self._registry.get("sandbox_providers") or []:
            if isinstance(p, dict) and self._provider_lifecycle(p) == "sandbox":
                out.append({**p, "_kind": self._infer_provider_kind(p), "_section": "sandbox_providers"})
        return out

    def _probe_compute(self, provider: Dict[str, Any]) -> Dict[str, Any]:
        api_key = _resolve_api_key(provider)
        if not api_key and provider.get("api_key_env"):
            return {"ok": False, "reason": "missing_api_key"}
        base = str(provider.get("base_url") or "").rstrip("/")
        model = str(provider.get("model") or "default")
        url = f"{base}/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "max_tokens": 8,
            "temperature": 0,
        }
        headers = {"Content-Type": "application/json", "User-Agent": "Phronesis-Opportunistic-Fleet/1.0"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if "openrouter" in base:
            headers["HTTP-Referer"] = "https://phronesis.local"
            headers["X-Title"] = "Phronesis Opportunistic Fleet"
        status, body = self._http_post(url, payload, headers=headers, timeout=45)
        ok = status == 200 and bool(body)
        return {"ok": ok, "http_status": status, "preview": str(body)[:200]}

    def _probe_context(self, provider: Dict[str, Any]) -> Dict[str, Any]:
        mode = str(provider.get("api_mode") or "")
        if mode == "duckduckgo_instant":
            url = f"{provider.get('base_url')}?q=test&format=json&no_html=1"
            status, body = self._http_get(url, timeout=15)
            return {"ok": status in (200, 202), "http_status": status}
        api_key = _resolve_api_key(provider)
        if not api_key and provider.get("api_key_env"):
            return {"ok": False, "reason": "missing_api_key"}
        base = str(provider.get("base_url") or "")
        qparam = str(provider.get("query_param") or "q")
        url = f"{base}?{urllib.parse.urlencode({qparam: 'test'})}"
        headers = dict(provider.get("headers") or {})
        if api_key:
            headers["X-Subscription-Token"] = api_key
        status, body = self._http_get(url, headers=headers, timeout=20)
        return {"ok": status in (200, 401, 403) or status == 200, "http_status": status}

    def _http_post(
        self,
        url: str,
        payload: dict,
        headers: Optional[dict] = None,
        timeout: float = 120,
    ) -> Tuple[int, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers=headers or {"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    return resp.status, json.loads(body)
                except Exception:
                    return resp.status, body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(body)
            except Exception:
                return exc.code, {"error": body[:500]}

    def _http_get(
        self,
        url: str,
        headers: Optional[dict] = None,
        timeout: float = 30,
    ) -> Tuple[int, Any]:
        req = urllib.request.Request(url, headers=headers or {}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    return resp.status, json.loads(body)
                except Exception:
                    return resp.status, body
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")[:500]

    def _dispatch_compute_one(
        self,
        provider: Dict[str, Any],
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 1024,
    ) -> Dict[str, Any]:
        api_key = _resolve_api_key(provider)
        if not api_key and provider.get("api_key_env"):
            return {
                "success": False,
                "error": f"missing_env:{provider.get('api_key_env')}",
                "provider_id": provider.get("id"),
            }

        base = str(provider.get("base_url") or "").rstrip("/")
        model = str(provider.get("model") or "default")
        url = f"{base}/chat/completions"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        max_out = min(max_tokens, int(provider.get("max_output_tokens") or 12288))
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_out,
            "temperature": 0.3,
        }
        headers = {"Content-Type": "application/json", "User-Agent": "Phronesis-Opportunistic-Fleet/1.0"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if "openrouter" in base:
            headers["HTTP-Referer"] = "https://phronesis.local"
            headers["X-Title"] = "Phronesis Opportunistic Fleet"

        started = time.time()
        status, body = self._http_post(url, payload, headers=headers, timeout=120)
        elapsed = round(time.time() - started, 2)
        text = ""
        if isinstance(body, dict):
            choices = body.get("choices") or []
            if choices:
                text = (choices[0].get("message") or {}).get("content", "")
        ok = status == 200 and bool(str(text).strip())
        result = {
            "success": ok,
            "response": str(text).strip(),
            "model": model,
            "provider_id": provider.get("id"),
            "provider_name": provider.get("name"),
            "latency_sec": elapsed,
            "http_status": status,
        }
        if not ok:
            result["error"] = body if isinstance(body, dict) else str(body)[:500]
        tel = _telemetry_monitor()
        if tel and provider.get("id"):
            tel.record_dispatch(
                loop="routing_compute",
                provider_id=str(provider.get("id")),
                success=ok,
                latency_sec=elapsed,
                timeout=status == 0 or elapsed >= 115,
                error=result.get("error") if not ok else None,
            )
        return result

    def dispatch_compute(
        self,
        prompt: str,
        *,
        capabilities: Optional[List[str]] = None,
        system: str = "",
        max_tokens: int = 1024,
        task_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"success": False, "tier": TIER_NAME, "error": "fleet_disabled"}
        caps = capabilities or self.infer_capabilities(prompt, task_type=task_type)
        candidates = self.select_provider_candidates("compute", caps, healthy_only=True)
        if not candidates:
            candidates = self.select_provider_candidates("compute", caps, healthy_only=False)
        if not candidates:
            return {"success": False, "tier": TIER_NAME, "error": "no_compute_provider", "capabilities": caps}

        max_tries = min(len(candidates), self._max_provider_retries() * 2)
        attempts: List[Dict[str, Any]] = []
        for provider in candidates[:max_tries]:
            one = self._dispatch_compute_one(
                provider, prompt, system=system, max_tokens=max_tokens,
            )
            attempts.append({
                "provider_id": provider.get("id"),
                "http_status": one.get("http_status"),
                "success": one.get("success"),
                "error": one.get("error"),
            })
            if one.get("success"):
                result = {
                    "success": True,
                    "tier": TIER_NAME,
                    "response": one.get("response"),
                    "model": one.get("model"),
                    "provider_id": one.get("provider_id"),
                    "provider_name": one.get("provider_name"),
                    "capabilities": caps,
                    "latency_sec": one.get("latency_sec"),
                    "http_status": one.get("http_status"),
                    "failover_attempts": len(attempts),
                }
                _log(DISPATCH_LOG, {"event": "compute_dispatch", **{k: result.get(k) for k in result}})
                return result
            pid = str(provider.get("id") or "")
            if pid:
                self._health_state.setdefault("providers", {})[pid] = {
                    "status": "down",
                    "last_check": _utc_now(),
                    "detail": {"dispatch_fail": one.get("error"), "http_status": one.get("http_status")},
                }
        self._save_health_state()
        last = attempts[-1] if attempts else {}
        result = {
            "success": False,
            "tier": TIER_NAME,
            "error": last.get("error") or "all_compute_providers_failed",
            "capabilities": caps,
            "attempts": attempts,
        }
        _log(DISPATCH_LOG, {"event": "compute_dispatch_fail", **result})
        return result

    def dispatch_context(
        self,
        query: str,
        *,
        capabilities: Optional[List[str]] = None,
        provider_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"success": False, "tier": TIER_NAME, "error": "fleet_disabled"}
        caps = capabilities or ["real-time-search"]
        if provider_id:
            provider = self._find_provider_any(provider_id)
            if not provider:
                return {"success": False, "tier": TIER_NAME, "error": "provider_not_found", "provider_id": provider_id}
        else:
            provider = self.select_provider("context", caps)
        if not provider:
            return {"success": False, "tier": TIER_NAME, "error": "no_context_provider"}

        mode = str(provider.get("api_mode") or "")
        started = time.time()

        if mode == "duckduckgo_instant":
            url = (
                f"{provider.get('base_url')}"
                f"?{urllib.parse.urlencode({'q': query, 'format': 'json', 'no_html': '1'})}"
            )
            status, body = self._http_get(url, timeout=20)
            snippets = []
            if isinstance(body, dict):
                if body.get("AbstractText"):
                    snippets.append(body["AbstractText"])
                for topic in body.get("RelatedTopics") or []:
                    if isinstance(topic, dict) and topic.get("Text"):
                        snippets.append(topic["Text"])
            text = "\n".join(snippets[:8]) or json.dumps(body)[:2000]
            ok = bool(text.strip())
        elif mode == "searxng":
            base = str(provider.get("base_url") or "").rstrip("/")
            url = f"{base}/search?{urllib.parse.urlencode({'q': query, 'format': 'json'})}"
            status, body = self._http_get(url, timeout=25)
            text = self._extract_search_snippets(body)
            ok = status == 200 and bool(text.strip())
        else:
            api_key = _resolve_api_key(provider)
            if not api_key and provider.get("api_key_env"):
                return {
                    "success": False,
                    "tier": TIER_NAME,
                    "error": f"missing_env:{provider.get('api_key_env')}",
                    "provider_id": provider.get("id"),
                }
            base = str(provider.get("base_url") or "")
            qparam = str(provider.get("query_param") or "q")
            url = f"{base}?{urllib.parse.urlencode({qparam: query})}"
            headers = dict(provider.get("headers") or {})
            if api_key:
                headers["X-Subscription-Token"] = api_key
            status, body = self._http_get(url, headers=headers, timeout=25)
            text = self._extract_search_snippets(body)
            ok = status == 200 and bool(text.strip())

        elapsed = round(time.time() - started, 2)
        result = {
            "success": ok,
            "tier": TIER_NAME,
            "response": text,
            "provider_id": provider.get("id"),
            "provider_name": provider.get("name"),
            "query": query,
            "latency_sec": elapsed,
        }
        _log(DISPATCH_LOG, {"event": "context_dispatch", **{k: result.get(k) for k in result}})
        tel = _telemetry_monitor()
        if tel and provider.get("id"):
            tel.record_dispatch(
                loop="routing_context",
                provider_id=str(provider.get("id")),
                success=ok,
                latency_sec=elapsed,
                timeout=elapsed >= 24,
                error=result.get("error") if not ok else None,
            )
        return result

    def _extract_search_snippets(self, body: Any) -> str:
        if not isinstance(body, dict):
            return str(body)[:3000]
        lines: List[str] = []
        for key in ("web", "news", "results", "organic"):
            block = body.get(key)
            if isinstance(block, list):
                for item in block[:6]:
                    if isinstance(item, dict):
                        title = item.get("title") or item.get("name") or ""
                        desc = item.get("description") or item.get("snippet") or ""
                        url = item.get("url") or item.get("link") or ""
                        if title or desc:
                            lines.append(f"- {title}: {desc} ({url})".strip())
        return "\n".join(lines) if lines else json.dumps(body)[:3000]

    def dispatch_opportunistic(
        self,
        prompt: str,
        *,
        task_type: Optional[str] = None,
        triggers: Optional[List[str]] = None,
        include_context: bool = False,
    ) -> Dict[str, Any]:
        """Unified Tier 1.5 dispatch — context enrichment then compute."""
        caps = self.infer_capabilities(prompt, task_type=task_type, triggers=triggers)
        context_block = ""
        if include_context or "real-time-search" in caps:
            ctx = self.dispatch_context(prompt[:500], capabilities=["real-time-search"])
            if ctx.get("success"):
                context_block = f"\n\n[REAL-TIME CONTEXT]\n{ctx.get('response', '')}"

        enriched = prompt + context_block
        compute = self.dispatch_compute(
            enriched,
            capabilities=caps,
            task_type=task_type,
        )
        compute["context_prefetch"] = bool(context_block)
        compute["triggers"] = triggers
        if not compute.get("success") and context_block.strip():
            snippet = context_block.strip()[:6000]
            compute = {
                "success": True,
                "tier": TIER_NAME,
                "response": (
                    "[T2 CONTEXT-ONLY — compute providers unavailable; synthesize from prefetch]\n"
                    + snippet
                ),
                "model": "context-only-fallback",
                "provider_id": "context-prefetch-fallback",
                "context_prefetch": True,
                "context_only": True,
                "compute_error": compute.get("error"),
                "triggers": triggers,
            }
        return compute

    def run_health_cycle(
        self,
        *,
        kinds: Optional[List[str]] = None,
        shadow: bool = False,
    ) -> Dict[str, Any]:
        kinds = kinds or ["compute", "context"]
        results: List[Dict[str, Any]] = []
        for kind in kinds:
            providers = (
                self.list_shadow_providers(kind=kind)
                if shadow
                else self.list_providers(kind=kind, healthy_only=False)
            )
            for p in providers:
                pid = str(p.get("id") or "")
                if not pid:
                    continue
                if p.get("_missing_key"):
                    entry = {
                        "ok": False,
                        "id": pid,
                        "status": "missing_env",
                        "last_check": _utc_now(),
                        "detail": {"reason": "missing_api_key", "env": p.get("api_key_env")},
                    }
                    self._health_state.setdefault("providers", {})[pid] = entry
                    results.append(entry)
                    continue
                results.append(self.health_check(pid))
        self._save_health_state()
        up = sum(1 for r in results if r.get("ok"))
        summary = {
            "timestamp": _utc_now(),
            "mode": "shadow" if shadow else "production",
            "checked": len(results),
            "up": up,
            "down": len(results) - up,
            "missing_env": sum(1 for r in results if r.get("status") == "missing_env"),
            "results": results,
        }
        _log(HEALTH_LOG, {"event": "health_cycle", **summary})
        return summary

    def status(self) -> Dict[str, Any]:
        compute = self.list_providers("compute")
        context = self.list_providers("context")
        sandbox = self.list_sandbox_providers()
        return {
            "enabled": self.enabled,
            "tier": TIER_NAME,
            "registry": str(self.registry_path),
            "compute_available": len(compute),
            "context_available": len(context),
            "sandbox_count": len(sandbox),
            "compute_providers": [
                {"id": p.get("id"), "name": p.get("name"), "health": p.get("_health", {})}
                for p in compute
            ],
            "context_providers": [
                {"id": p.get("id"), "name": p.get("name"), "health": p.get("_health", {})}
                for p in context
            ],
        }

    def add_pending_provider(self, provider: Dict[str, Any], kind: str = "compute") -> Dict[str, Any]:
        """Deprecated: route discoveries through fleet_procurement_engine sandbox inject."""
        sandbox = self._registry.setdefault("sandbox_providers", [])
        entry = {
            **provider,
            "id": provider.get("id") or f"legacy-pending-{len(sandbox)}",
            "enabled": False,
            "lifecycle": "sandbox",
            "discovered_at": _utc_now(),
            "_kind": kind,
        }
        sandbox.append(entry)
        self.save_registry()
        self.reload()
        return {"ok": True, "sandbox_count": len(sandbox), "deprecated": "use_procurement_engine"}


def _config_fleet_enabled() -> bool:
    """Operator gate in config.yaml — registry alone is not enough."""
    try:
        cfg_path = Path(r"D:\HermesData\config.yaml")
        if not cfg_path.is_file():
            return False
        if yaml is None:
            return False
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        fleet = (raw.get("local_sovereign") or {}).get("opportunistic_fleet") or {}
        return bool(fleet.get("enabled"))
    except Exception:
        return False


def fleet_available() -> bool:
    try:
        if not _config_fleet_enabled():
            return False
        fm = FleetManager()
        return fm.enabled and (
            bool(fm.list_providers("compute")) or bool(fm.list_providers("context"))
        )
    except Exception:
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Opportunistic Fleet Manager")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--health", action="store_true")
    parser.add_argument(
        "--shadow",
        action="store_true",
        help="Probe all enabled registry providers without routing (Phase B0)",
    )
    parser.add_argument("--compute", metavar="PROMPT")
    parser.add_argument("--context", metavar="QUERY")
    args = parser.parse_args()

    fm = FleetManager()
    if args.health:
        print(json.dumps(fm.run_health_cycle(shadow=args.shadow), indent=2))
    elif args.compute:
        print(json.dumps(fm.dispatch_compute(args.compute), indent=2))
    elif args.context:
        print(json.dumps(fm.dispatch_context(args.context), indent=2))
    else:
        print(json.dumps(fm.status(), indent=2))
