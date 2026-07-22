#!/usr/bin/env python3
"""
external_fleet_manager.py -- Tier 1.5 Opportunistic Fleet manager.

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
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

_CONTEXT_CACHE: Dict[str, Tuple[float, str]] = {}
_CONTEXT_CACHE_LOCK = threading.Lock()


class _FleetHttpPool:
    """Keep-alive HTTP for fleet provider calls (avoids TCP setup per dispatch)."""

    def __init__(self, max_per_host: int = 4, keep_alive_sec: int = 45):
        self._pool: Dict[str, List[HTTPConnection]] = {}
        self._lock = threading.Lock()
        self._max = max_per_host
        self._keep_alive = keep_alive_sec
        self._last_used: Dict[HTTPConnection, float] = {}

    def _conn_cls(self, scheme: str):
        return HTTPSConnection if scheme == "https" else HTTPConnection

    def request(
        self,
        method: str,
        url: str,
        *,
        body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 120,
    ) -> Tuple[int, bytes]:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        key = f"{parsed.scheme}://{host}:{port}"
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        conn_cls = self._conn_cls(parsed.scheme)
        conn: Optional[HTTPConnection] = None
        try:
            with self._lock:
                bucket = self._pool.get(key, [])
                now = time.time()
                while bucket and (now - self._last_used.get(bucket[-1], 0.0)) > self._keep_alive:
                    stale = bucket.pop()
                    try:
                        stale.close()
                    except Exception:
                        pass
                if bucket:
                    conn = bucket.pop()
                    self._last_used[conn] = now
            if conn is None:
                conn = conn_cls(host, port, timeout=timeout)
                self._last_used[conn] = time.time()
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            status = int(resp.status)
            with self._lock:
                bucket = self._pool.setdefault(key, [])
                if len(bucket) < self._max:
                    bucket.append(conn)
                    conn = None
            return status, data
        except Exception:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            raise
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


_FLEET_HTTP_POOL = _FleetHttpPool()

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
DEFAULT_CONTEXT_CACHE_TTL_SEC = 120.0
DEFAULT_PARALLEL_COMPUTE_PROVIDERS = 3


def _context_cache_ttl_sec(registry: Dict[str, Any]) -> float:
    try:
        return float((registry.get("policy") or {}).get("context_cache_ttl_sec") or DEFAULT_CONTEXT_CACHE_TTL_SEC)
    except Exception:
        return DEFAULT_CONTEXT_CACHE_TTL_SEC


def _context_cache_key(query: str) -> str:
    return (query or "").strip().lower()[:500]


def _context_cache_get(registry: Dict[str, Any], query: str) -> Optional[str]:
    key = _context_cache_key(query)
    if not key:
        return None
    ttl = _context_cache_ttl_sec(registry)
    with _CONTEXT_CACHE_LOCK:
        entry = _CONTEXT_CACHE.get(key)
        if not entry:
            return None
        ts, block = entry
        if (time.time() - ts) > ttl:
            del _CONTEXT_CACHE[key]
            return None
        return block


def _context_cache_put(registry: Dict[str, Any], query: str, block: str) -> None:
    key = _context_cache_key(query)
    text = (block or "").strip()
    if not key or not text:
        return
    with _CONTEXT_CACHE_LOCK:
        _CONTEXT_CACHE[key] = (time.time(), text)


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


_ENV_LOADED = False


def _ensure_hermes_env_loaded() -> None:
    """Load D:/HermesData/.env once so schtasks/CLI fleet dispatch sees GROQ/OR keys.

    Root cause 2026-07-21: list_providers filtered all compute as key-missing when
    process inherited no shell env (matrix smoke no_compute_provider). Proxy path
    often had keys; bare pythonw cron did not.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = Path(r"D:\HermesData\.env")
    if env_path.is_file():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                if not key:
                    continue
                os.environ.setdefault(key, val.strip().strip('"').strip("'"))
        except Exception:
            pass
    _ENV_LOADED = True


class FleetManager:
    """Universal Opportunistic Fleet -- compute + context from YAML registry."""

    def __init__(self, registry_path: Path = REGISTRY_PATH):
        self.registry_path = registry_path
        self._registry: Dict[str, Any] = {}
        self._health_state: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        _ensure_hermes_env_loaded()
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
        preferred_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Ranked provider list for failover - highest score first.

        W2-P3: optional preferred_ids (from free_model_role_matrix) pin order.
        """
        caps = [str(c).lower() for c in (capabilities or [])]
        candidates = self.list_providers(kind=kind, healthy_only=healthy_only)
        if not candidates and healthy_only:
            candidates = self.list_providers(kind=kind, healthy_only=False)
        pref = [str(x) for x in (preferred_ids or []) if str(x).strip()]
        if pref:
            by_id = {str(p.get("id")): p for p in candidates}
            ordered: List[Dict[str, Any]] = []
            seen = set()
            for pid in pref:
                if pid in by_id and pid not in seen:
                    ordered.append(by_id[pid])
                    seen.add(pid)
            for p in candidates:
                pid = str(p.get("id"))
                if pid not in seen:
                    ordered.append(p)
                    seen.add(pid)
            candidates = ordered
        if not caps:
            return candidates
        scored: List[Tuple[int, Dict[str, Any]]] = []
        for p in candidates:
            pcaps = {str(c).lower() for c in (p.get("capabilities") or [])}
            score = sum(2 for c in caps if c in pcaps) + int(
                p.get("_effective_priority") or p.get("priority") or 0
            )
            if pref:
                pid = str(p.get("id"))
                if pid in pref:
                    score += 1000 - pref.index(pid)
            if any(c in pcaps for c in caps) or not caps:
                scored.append((score, p))
        if not scored:
            return candidates
        scored.sort(key=lambda x: (-x[0], str(x[1].get("id"))))
        return [p for _, p in scored]

    def _role_preferred_ids(
        self,
        prompt: str,
        task_type: Optional[str] = None,
    ) -> List[str]:
        """W2-P3 + W3-P2: preferred free ids via central backend policy, then RoleMatrix."""
        # Central policy first (hop-order companion)
        try:
            from router_backend_policy import preferred_free_provider_ids, is_roleplay_or_adult

            if is_roleplay_or_adult(task_type=task_type, prompt=prompt or ""):
                return []
            ids = list(
                preferred_free_provider_ids(task_type=task_type, prompt=prompt or "") or []
            )
            if ids:
                return ids
        except Exception:
            pass
        try:
            from free_model_role_matrix import RoleMatrix

            rm = RoleMatrix.load()
            if rm.blocked(task_type=task_type, prompt=prompt):
                return []
            return list(rm.preferred_provider_ids(task_type=task_type, prompt=prompt) or [])
        except Exception:
            return []

    def _max_provider_retries(self) -> int:
        try:
            return max(1, int((self._registry.get("policy") or {}).get("max_retries_per_provider") or 2))
        except Exception:
            return 2

    def _parallel_dispatch_enabled(self) -> bool:
        return bool((self._registry.get("policy") or {}).get("parallel_dispatch_enabled", True))

    def _parallel_compute_workers(self) -> int:
        try:
            n = int((self._registry.get("policy") or {}).get("parallel_compute_providers") or DEFAULT_PARALLEL_COMPUTE_PROVIDERS)
            return max(1, min(6, n))
        except Exception:
            return DEFAULT_PARALLEL_COMPUTE_PROVIDERS

    def _record_provider_failure(self, provider: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Soft health: require consecutive failures before marking provider down."""
        pid = str(provider.get("id") or "")
        if not pid:
            return
        providers = self._health_state.setdefault("providers", {})
        prev = providers.get(pid) or {}
        streak = int(prev.get("fail_streak") or 0) + 1
        entry = {
            "last_check": _utc_now(),
            "fail_streak": streak,
            "detail": {
                "dispatch_fail": result.get("error"),
                "http_status": result.get("http_status"),
            },
        }
        if streak >= 2:
            entry["status"] = "down"
        else:
            entry["status"] = prev.get("status") or "degraded"
        providers[pid] = entry

    def _record_provider_success(self, provider: Dict[str, Any]) -> None:
        pid = str(provider.get("id") or "")
        if not pid:
            return
        self._health_state.setdefault("providers", {})[pid] = {
            "status": "up",
            "last_check": _utc_now(),
            "fail_streak": 0,
        }

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
        prev = (self._health_state.get("providers") or {}).get(provider_id) or {}
        try:
            if kind == "compute":
                result = self._probe_compute(provider)
            else:
                result = self._probe_context(provider)
            elapsed = round(time.time() - started, 2)
            ok = bool(result.get("ok"))
            if ok:
                entry = {
                    "status": "up",
                    "last_check": _utc_now(),
                    "latency_sec": elapsed,
                    "fail_streak": 0,
                    "consecutive_failures": 0,
                    "detail": result,
                }
            else:
                streak = int(prev.get("fail_streak") or prev.get("consecutive_failures") or 0) + 1
                entry = {
                    "status": "down",
                    "last_check": _utc_now(),
                    "latency_sec": elapsed,
                    "fail_streak": streak,
                    "consecutive_failures": streak,
                    "detail": result,
                }
            self._health_state.setdefault("providers", {})[provider_id] = entry
            self._save_health_state()
            _log(HEALTH_LOG, {"event": "health_check", "id": provider_id, **entry})
            return {"ok": ok, "id": provider_id, **entry}
        except Exception as exc:
            streak = int(prev.get("fail_streak") or prev.get("consecutive_failures") or 0) + 1
            entry = {
                "status": "down",
                "last_check": _utc_now(),
                "fail_streak": streak,
                "consecutive_failures": streak,
                "error": str(exc),
            }
            self._health_state.setdefault("providers", {})[provider_id] = entry
            self._save_health_state()
            return {"ok": False, "id": provider_id, **entry}

    def demote_on_fail_streak(
        self,
        *,
        threshold: int = 3,
        write_receipt: bool = True,
    ) -> Dict[str, Any]:
        """W3-P5: demote-only self-heal. Disable enabled providers with fail_streak>=N.

        Never auto-enables. Operator promote only (procurement / manual).
        """
        threshold = max(1, int(threshold or 3))
        demoted: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        providers_health = (self._health_state.get("providers") or {})
        changed = False
        for section in ("compute_providers", "context_providers"):
            for p in self._registry.get(section) or []:
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("id") or "")
                if not pid:
                    continue
                if not p.get("enabled", True):
                    skipped.append({"id": pid, "reason": "already_disabled"})
                    continue
                if self._provider_lifecycle(p) not in ("enabled", ""):
                    skipped.append({"id": pid, "reason": f"lifecycle={self._provider_lifecycle(p)}"})
                    continue
                h = providers_health.get(pid) or {}
                streak = int(h.get("fail_streak") or h.get("consecutive_failures") or 0)
                status = str(h.get("status") or "")
                if status == "down" and streak >= threshold:
                    reason = f"health_fail_streak_{streak}_ge_{threshold}"
                    p["enabled"] = False
                    p["lifecycle"] = "disabled"
                    p["disabled_at"] = _utc_now()
                    p["disabled_reason"] = reason
                    demoted.append({
                        "id": pid,
                        "section": section,
                        "fail_streak": streak,
                        "reason": reason,
                    })
                    changed = True
                else:
                    skipped.append({
                        "id": pid,
                        "reason": "below_threshold_or_up",
                        "fail_streak": streak,
                        "status": status,
                    })
        receipt: Dict[str, Any] = {
            "event": "fleet_demote_on_fail_streak",
            "ts": _utc_now(),
            "threshold": threshold,
            "demoted": demoted,
            "demoted_n": len(demoted),
            "skipped_n": len(skipped),
            "never_auto_enable": True,
        }
        if changed:
            try:
                self.save_registry()
                self.reload()
            except Exception as exc:
                receipt["save_error"] = f"{type(exc).__name__}:{exc}"[:200]
            _log(HEALTH_LOG, receipt)
            if write_receipt:
                try:
                    path = HEALTH_LOG.parent / "fleet-demote-receipts.jsonl"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(receipt, ensure_ascii=True) + "\n")
                except Exception:
                    pass
        # W4-P3: always refresh latest demote surface (even demoted_n=0) for snapshot
        if write_receipt:
            try:
                latest = HEALTH_LOG.parent / "fleet-demote-latest.json"
                latest.parent.mkdir(parents=True, exist_ok=True)
                with open(latest, "w", encoding="utf-8") as f:
                    f.write(json.dumps(receipt, indent=2, ensure_ascii=True))
                try:
                    state_latest = Path(r"D:\HermesData\state") / "fleet-demote-latest.json"
                    state_latest.parent.mkdir(parents=True, exist_ok=True)
                    state_latest.write_text(
                        json.dumps(receipt, indent=2, ensure_ascii=True), encoding="utf-8"
                    )
                except Exception:
                    pass
            except Exception:
                pass
        return receipt

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

    def _decode_http_body(self, status: int, raw: bytes) -> Tuple[int, Any]:
        body = raw.decode("utf-8", errors="replace")
        try:
            return status, json.loads(body)
        except Exception:
            return status, body if body else {"error": f"http_{status}"}

    def _http_post(
        self,
        url: str,
        payload: dict,
        headers: Optional[dict] = None,
        timeout: float = 120,
    ) -> Tuple[int, Any]:
        data = json.dumps(payload).encode("utf-8")
        hdrs = dict(headers or {})
        hdrs.setdefault("Content-Type", "application/json")
        try:
            status, raw = _FLEET_HTTP_POOL.request(
                "POST",
                url,
                body=data,
                headers=hdrs,
                timeout=timeout,
            )
            return self._decode_http_body(status, raw)
        except Exception:
            req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return self._decode_http_body(resp.status, resp.read())
            except urllib.error.HTTPError as exc:
                return self._decode_http_body(exc.code, exc.read())

    def _http_get(
        self,
        url: str,
        headers: Optional[dict] = None,
        timeout: float = 30,
    ) -> Tuple[int, Any]:
        hdrs = dict(headers or {})
        try:
            status, raw = _FLEET_HTTP_POOL.request(
                "GET",
                url,
                headers=hdrs,
                timeout=timeout,
            )
            return self._decode_http_body(status, raw)
        except Exception:
            req = urllib.request.Request(url, headers=hdrs, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return self._decode_http_body(resp.status, resp.read())
            except urllib.error.HTTPError as exc:
                return self._decode_http_body(exc.code, exc.read())

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

    def _dispatch_compute_parallel(
        self,
        candidates: List[Dict[str, Any]],
        prompt: str,
        *,
        capabilities: List[str],
        system: str = "",
        max_tokens: int = 1024,
    ) -> Dict[str, Any]:
        workers = min(self._parallel_compute_workers(), len(candidates))
        batch = candidates[: max(workers, self._max_provider_retries() * 2)]
        attempts: List[Dict[str, Any]] = []
        winner: Optional[Tuple[Dict[str, Any], Dict[str, Any]]] = None

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fleet-compute") as pool:
            futures = {
                pool.submit(
                    self._dispatch_compute_one,
                    provider,
                    prompt,
                    system=system,
                    max_tokens=max_tokens,
                ): provider
                for provider in batch
            }
            for fut in as_completed(futures):
                provider = futures[fut]
                try:
                    one = fut.result()
                except Exception as exc:
                    one = {
                        "success": False,
                        "error": str(exc),
                        "provider_id": provider.get("id"),
                    }
                attempts.append({
                    "provider_id": provider.get("id"),
                    "http_status": one.get("http_status"),
                    "success": one.get("success"),
                    "error": one.get("error"),
                    "parallel": True,
                })
                if one.get("success") and winner is None:
                    winner = (provider, one)
                    break

        if winner:
            provider, one = winner
            self._record_provider_success(provider)
            self._save_health_state()
            result = {
                "success": True,
                "tier": TIER_NAME,
                "response": one.get("response"),
                "model": one.get("model"),
                "provider_id": one.get("provider_id"),
                "provider_name": one.get("provider_name"),
                "capabilities": capabilities,
                "latency_sec": one.get("latency_sec"),
                "http_status": one.get("http_status"),
                "failover_attempts": len(attempts),
                "parallel_dispatch": True,
            }
            _log(DISPATCH_LOG, {"event": "compute_dispatch_parallel", **{k: result.get(k) for k in result}})
            return result

        last = attempts[-1] if attempts else {}
        result = {
            "success": False,
            "tier": TIER_NAME,
            "error": last.get("error") or "all_compute_providers_failed",
            "capabilities": capabilities,
            "attempts": attempts,
            "parallel_dispatch": True,
        }
        _log(DISPATCH_LOG, {"event": "compute_dispatch_parallel_fail", **result})
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
        preferred = self._role_preferred_ids(prompt, task_type=task_type)
        candidates = self.select_provider_candidates(
            "compute", caps, healthy_only=True, preferred_ids=preferred or None,
        )
        if not candidates:
            candidates = self.select_provider_candidates(
                "compute", caps, healthy_only=False, preferred_ids=preferred or None,
            )
        if not candidates:
            return {"success": False, "tier": TIER_NAME, "error": "no_compute_provider", "capabilities": caps}

        if self._parallel_dispatch_enabled() and len(candidates) > 1:
            return self._dispatch_compute_parallel(
                candidates,
                prompt,
                capabilities=caps,
                system=system,
                max_tokens=max_tokens,
            )

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
                self._record_provider_success(provider)
                self._save_health_state()
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
                    "role_preferred_ids": preferred or [],
                }
                _log(DISPATCH_LOG, {"event": "compute_dispatch", **{k: result.get(k) for k in result}})
                return result
            self._record_provider_failure(provider, one)
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

    def dispatch_context_cached(
        self,
        query: str,
        *,
        capabilities: Optional[List[str]] = None,
        provider_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        cached = _context_cache_get(self._registry, query)
        if cached:
            return {
                "success": True,
                "tier": TIER_NAME,
                "response": cached,
                "provider_id": "context-cache",
                "provider_name": "context-cache",
                "query": query,
                "latency_sec": 0.0,
                "cached": True,
            }
        result = self.dispatch_context(query, capabilities=capabilities, provider_id=provider_id)
        if result.get("success"):
            _context_cache_put(self._registry, query, str(result.get("response") or ""))
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

    def _fetch_context_block(self, prompt: str) -> str:
        ctx = self.dispatch_context_cached(prompt[:500], capabilities=["real-time-search"])
        if ctx.get("success"):
            return f"\n\n[REAL-TIME CONTEXT]\n{ctx.get('response', '')}"
        return ""

    def dispatch_opportunistic(
        self,
        prompt: str,
        *,
        task_type: Optional[str] = None,
        triggers: Optional[List[str]] = None,
        include_context: bool = False,
    ) -> Dict[str, Any]:
        """Unified Tier 1.5 dispatch -- parallel context prefetch + compute race when enabled."""
        caps = self.infer_capabilities(prompt, task_type=task_type, triggers=triggers)
        need_context = bool(include_context or "real-time-search" in caps)
        context_block = ""
        compute: Dict[str, Any]

        if need_context and self._parallel_dispatch_enabled():
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="fleet-opp") as pool:
                ctx_fut = pool.submit(self._fetch_context_block, prompt)
                compute_fut = pool.submit(
                    self.dispatch_compute,
                    prompt,
                    capabilities=caps,
                    task_type=task_type,
                )
                compute = compute_fut.result()
                if not compute.get("success"):
                    context_block = ctx_fut.result()
                    enriched = prompt + context_block
                    compute = self.dispatch_compute(
                        enriched,
                        capabilities=caps,
                        task_type=task_type,
                    )
        else:
            if need_context:
                context_block = self._fetch_context_block(prompt)
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
                    "[T2 CONTEXT-ONLY -- compute providers unavailable; synthesize from prefetch]\n"
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
        # W3-P5: demote-only after consecutive downs (never auto-enable)
        demote = {"demoted_n": 0, "skipped": True if shadow else False}
        if not shadow:
            try:
                demote = self.demote_on_fail_streak(threshold=3, write_receipt=True)
            except Exception as exc:
                demote = {"demoted_n": 0, "error": f"{type(exc).__name__}:{exc}"[:160]}
        summary = {
            "timestamp": _utc_now(),
            "mode": "shadow" if shadow else "production",
            "checked": len(results),
            "up": up,
            "down": len(results) - up,
            "missing_env": sum(1 for r in results if r.get("status") == "missing_env"),
            "results": results,
            "demote": {
                "demoted_n": int(demote.get("demoted_n") or 0),
                "demoted": demote.get("demoted") or [],
                "threshold": demote.get("threshold"),
                "never_auto_enable": True,
                "error": demote.get("error"),
            },
        }
        _log(HEALTH_LOG, {"event": "health_cycle", **{k: v for k, v in summary.items() if k != "results"}})
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
    """Operator gate in config.yaml -- registry alone is not enough."""
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
