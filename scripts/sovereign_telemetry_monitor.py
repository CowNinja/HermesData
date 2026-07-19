#!/usr/bin/env python3
"""
sovereign_telemetry_monitor.py — Self-aware telemetry, auto-triage, zombie protection.

Tracks TTFT drift, failure clusters, and thread stalls across procurement + routing loops.
Autonomously throttles or blacklists degraded providers; force-releases semaphore pool on zombies.

Usage:
  python sovereign_telemetry_monitor.py --optimize-tick
  python sovereign_telemetry_monitor.py --status
  python sovereign_telemetry_monitor.py --simulate-stall
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

HERMES_SCRIPTS = Path(__file__).resolve().parent
if str(HERMES_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HERMES_SCRIPTS))

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

REGISTRY_PATH = Path(r"D:\HermesData\config\fleet_registry.yaml")
TELEMETRY_LOG = Path(r"D:\PhronesisVault\Operations\logs\fleet-telemetry.jsonl")
OPTIMIZATION_LOG = Path(r"D:\PhronesisVault\Operations\logs\system_optimizations.jsonl")
TELEMETRY_STATE = Path(r"D:\PhronesisVault\Operations\logs\sovereign-telemetry-state.json")
TELEMETRY_REPORT = Path(r"D:\PhronesisVault\Operations\logs\sovereign-telemetry-report.json")

LOCAL_MOE_PROVIDER_PREFIX = "local-moe"
DEFAULT_TELEMETRY_CONFIG = {
    "enabled": True,
    "latency_spike_multiplier": 2.5,
    "consecutive_timeout_threshold": 3,
    "consecutive_failure_threshold": 4,
    "temp_blacklist_sec": 3600,
    "throttle_priority_delta": 5,
    "zombie_multiplier": 1.5,
    "watchdog_interval_sec": 5,
    "sample_window_size": 50,
    "ttft_drift_alert_multiplier": 2.0,
    "auto_tune_governor": True,
    "governor_stress_http_reduction": 2,
    "governor_stress_concurrency_reduction": 1,
    "local_stress_latency_sec": 45.0,
    "local_stress_fail_threshold": 3,
    "procurement_defer_stress_level": 2,
}

# Windows: spawn without console window
_SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    _SUBPROCESS_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

_MONITOR_SINGLETON: Optional["SovereignTelemetryMonitor"] = None
_MONITOR_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, event: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _utc_now(), **event}, default=str) + "\n")
    except Exception:
        pass


def _load_registry() -> Dict[str, Any]:
    try:
        import yaml  # type: ignore

        if REGISTRY_PATH.is_file():
            return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


@dataclass
class TrackedTask:
    task_id: str
    loop: str
    provider_id: Optional[str]
    thread_ident: int
    pid: int
    expected_sec: float
    started_at: float
    release_cb: Optional[Callable[[], None]] = None
    process: Any = None
    zombie: bool = False


class ZombieTaskGuard:
    """Detect stalled background work and force-release held resources."""

    def __init__(self, zombie_multiplier: float = 1.5, watchdog_interval_sec: float = 5.0):
        self.zombie_multiplier = zombie_multiplier
        self.watchdog_interval_sec = watchdog_interval_sec
        self._tasks: Dict[str, TrackedTask] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._watchdog: Optional[threading.Thread] = None
        self._on_zombie: Optional[Callable[[TrackedTask, float], None]] = None

    def set_zombie_handler(self, handler: Callable[[TrackedTask, float], None]) -> None:
        self._on_zombie = handler

    def start(self) -> None:
        if self._watchdog and self._watchdog.is_alive():
            return
        self._stop.clear()
        self._watchdog = threading.Thread(target=self._watchdog_loop, name="sovereign-zombie-guard", daemon=True)
        self._watchdog.start()

    def stop(self) -> None:
        self._stop.set()

    def register(
        self,
        *,
        loop: str,
        expected_sec: float,
        provider_id: Optional[str] = None,
        release_cb: Optional[Callable[[], None]] = None,
        process: Any = None,
    ) -> str:
        task_id = f"{loop}-{uuid.uuid4().hex[:10]}"
        proc_pid = int(process.pid) if process is not None and getattr(process, "pid", None) else os.getpid()
        task = TrackedTask(
            task_id=task_id,
            loop=loop,
            provider_id=provider_id,
            thread_ident=threading.get_ident(),
            pid=proc_pid,
            expected_sec=expected_sec,
            started_at=time.time(),
            release_cb=release_cb,
            process=process,
        )
        with self._lock:
            self._tasks[task_id] = task
        return task_id

    def register_process(
        self,
        proc: Any,
        *,
        loop: str,
        expected_sec: float,
        provider_id: Optional[str] = None,
        release_cb: Optional[Callable[[], None]] = None,
    ) -> str:
        """Track a subprocess.Popen worker for zombie terminate/kill."""
        return self.register(
            loop=loop,
            expected_sec=expected_sec,
            provider_id=provider_id,
            release_cb=release_cb,
            process=proc,
        )

    @staticmethod
    def _terminate_process(proc: Any) -> bool:
        if proc is None:
            return False
        try:
            if getattr(proc, "poll", lambda: None)() is not None:
                return True
            proc.terminate()
            try:
                proc.wait(timeout=3)
                return True
            except Exception:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
                return True
        except Exception:
            return False

    def unregister(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)

    def active_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "task_id": t.task_id,
                    "loop": t.loop,
                    "provider_id": t.provider_id,
                    "elapsed_sec": round(time.time() - t.started_at, 2),
                    "expected_sec": t.expected_sec,
                    "zombie": t.zombie,
                    "thread_ident": t.thread_ident,
                    "pid": t.pid,
                }
                for t in self._tasks.values()
            ]

    def _watchdog_loop(self) -> None:
        while not self._stop.wait(self.watchdog_interval_sec):
            self.scan_zombies()

    def scan_zombies(self) -> List[Dict[str, Any]]:
        """Return triage events for tasks exceeding 1.5x expected window."""
        now = time.time()
        events: List[Dict[str, Any]] = []
        with self._lock:
            for task in list(self._tasks.values()):
                if task.zombie:
                    continue
                elapsed = now - task.started_at
                limit = task.expected_sec * self.zombie_multiplier
                if elapsed <= limit:
                    continue
                task.zombie = True
                proc_killed = self._terminate_process(task.process)
                if task.release_cb:
                    try:
                        task.release_cb()
                    except Exception:
                        pass
                kind = "process" if task.process is not None else "thread"
                evt = {
                    "action": "zombie_terminated",
                    "task_id": task.task_id,
                    "loop": task.loop,
                    "provider_id": task.provider_id,
                    "thread_ident": task.thread_ident,
                    "pid": task.pid,
                    "kind": kind,
                    "process_terminated": proc_killed,
                    "elapsed_sec": round(elapsed, 2),
                    "expected_sec": task.expected_sec,
                    "limit_sec": round(limit, 2),
                    "message": (
                        f"Killed stalled background {kind} PID {task.pid} "
                        f"(thread {task.thread_ident}) after {elapsed:.1f}s "
                        f"(limit {limit:.1f}s)"
                    ),
                }
                events.append(evt)
                if self._on_zombie:
                    try:
                        self._on_zombie(task, elapsed)
                    except Exception:
                        pass
        return events


class ProviderTelemetry:
    """Rolling metrics + triage state per provider."""

    def __init__(self, window_size: int = 50):
        self.window_size = window_size
        self.latency_samples: Deque[float] = deque(maxlen=window_size)
        self.ttft_samples: Deque[float] = deque(maxlen=window_size)
        self.failures: Deque[Dict[str, Any]] = deque(maxlen=window_size)
        self.consecutive_timeouts: int = 0
        self.consecutive_failures: int = 0
        self.ttft_baseline: Optional[float] = None
        self.throttle_penalty: int = 0
        self.blacklisted_until: Optional[float] = None
        self.last_triage: Optional[str] = None
        self.last_triage_reason: Optional[str] = None

    def record_success(self, *, latency_sec: float, ttft_sec: Optional[float] = None) -> None:
        self.latency_samples.append(latency_sec)
        if ttft_sec is not None:
            self.ttft_samples.append(ttft_sec)
            self._update_ttft_baseline(ttft_sec)
        self.consecutive_timeouts = 0
        self.consecutive_failures = 0

    def record_failure(self, *, kind: str, latency_sec: Optional[float] = None, timeout: bool = False) -> None:
        self.failures.append({"kind": kind, "timeout": timeout, "latency_sec": latency_sec, "at": _utc_now()})
        self.consecutive_failures += 1
        if timeout:
            self.consecutive_timeouts += 1
        else:
            self.consecutive_timeouts = 0
        if latency_sec is not None:
            self.latency_samples.append(latency_sec)

    def _update_ttft_baseline(self, ttft: float) -> None:
        if len(self.ttft_samples) < 3:
            self.ttft_baseline = ttft
            return
        try:
            self.ttft_baseline = statistics.median(self.ttft_samples)
        except statistics.StatisticsError:
            self.ttft_baseline = ttft

    def ttft_drift_ratio(self, current_ttft: float) -> Optional[float]:
        if not self.ttft_baseline or self.ttft_baseline <= 0:
            return None
        return current_ttft / self.ttft_baseline

    def latency_p95(self) -> Optional[float]:
        if len(self.latency_samples) < 3:
            return None
        sorted_samples = sorted(self.latency_samples)
        idx = int(len(sorted_samples) * 0.95) - 1
        return sorted_samples[max(0, idx)]

    def is_blacklisted(self) -> bool:
        if not self.blacklisted_until:
            return False
        if time.time() >= self.blacklisted_until:
            self.blacklisted_until = None
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "latency_samples": list(self.latency_samples)[-10:],
            "ttft_samples": list(self.ttft_samples)[-10:],
            "ttft_baseline": self.ttft_baseline,
            "consecutive_timeouts": self.consecutive_timeouts,
            "consecutive_failures": self.consecutive_failures,
            "throttle_penalty": self.throttle_penalty,
            "blacklisted_until": self.blacklisted_until,
            "last_triage": self.last_triage,
            "last_triage_reason": self.last_triage_reason,
            "latency_p95": self.latency_p95(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], window_size: int) -> "ProviderTelemetry":
        pt = cls(window_size=window_size)
        for v in data.get("latency_samples") or []:
            pt.latency_samples.append(float(v))
        for v in data.get("ttft_samples") or []:
            pt.ttft_samples.append(float(v))
        pt.ttft_baseline = data.get("ttft_baseline")
        pt.consecutive_timeouts = int(data.get("consecutive_timeouts") or 0)
        pt.consecutive_failures = int(data.get("consecutive_failures") or 0)
        pt.throttle_penalty = int(data.get("throttle_penalty") or 0)
        pt.blacklisted_until = data.get("blacklisted_until")
        pt.last_triage = data.get("last_triage")
        pt.last_triage_reason = data.get("last_triage_reason")
        return pt


class SovereignTelemetryMonitor:
    """Telemetry profiler + auto-triage + adaptive governor tuning."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        registry = _load_registry()
        reg_cfg = (registry.get("telemetry") or {})
        self.config = {**DEFAULT_TELEMETRY_CONFIG, **reg_cfg, **(config or {})}
        self._providers: Dict[str, ProviderTelemetry] = {}
        self._system_samples: Deque[Dict[str, Any]] = deque(maxlen=100)
        self._lock = threading.Lock()
        self._governor_stress_level: int = 0
        self._local_stress_level: int = 0
        self._local_recent_failures: int = 0
        self.zombie_guard = ZombieTaskGuard(
            zombie_multiplier=float(self.config.get("zombie_multiplier") or 1.5),
            watchdog_interval_sec=float(self.config.get("watchdog_interval_sec") or 5),
        )
        self.zombie_guard.set_zombie_handler(self._on_zombie_task)
        self._load_state()
        if self.config.get("enabled", True) and self.config.get("start_watchdog", True):
            self.zombie_guard.start()

    def _window_size(self) -> int:
        return int(self.config.get("sample_window_size") or 50)

    def _get_provider(self, provider_id: str) -> ProviderTelemetry:
        with self._lock:
            if provider_id not in self._providers:
                self._providers[provider_id] = ProviderTelemetry(self._window_size())
            return self._providers[provider_id]

    @staticmethod
    def local_provider_id(port: int = 8090, backend: str = "vault") -> str:
        return f"{LOCAL_MOE_PROVIDER_PREFIX}-{port}-{backend}"

    def record_local_moe_dispatch(
        self,
        *,
        success: bool,
        latency_sec: float,
        port: int = 8090,
        backend: str = "vault",
        model: Optional[str] = None,
        timeout: bool = False,
        error: Optional[str] = None,
    ) -> None:
        """Unified Tier 1 (8090/ollama) stress signal for procurement deferral."""
        provider_id = self.local_provider_id(port, backend)
        self.record_dispatch(
            loop="routing_local_moe",
            provider_id=provider_id,
            success=success,
            latency_sec=latency_sec,
            ttft_sec=latency_sec,
            timeout=timeout,
            error=error,
        )
        stress_lat = float(self.config.get("local_stress_latency_sec") or 45.0)
        fail_thresh = int(self.config.get("local_stress_fail_threshold") or 3)
        if success and latency_sec < stress_lat:
            self._local_recent_failures = max(0, self._local_recent_failures - 1)
            self._local_stress_level = max(0, self._local_stress_level - 1)
        else:
            if not success or timeout:
                self._local_recent_failures += 1
            if latency_sec >= stress_lat:
                self._local_stress_level = min(5, self._local_stress_level + 1)
            if self._local_recent_failures >= fail_thresh:
                self._local_stress_level = min(5, self._local_stress_level + 2)
        _append_jsonl(
            TELEMETRY_LOG,
            {
                "event": "local_moe_stress",
                "provider_id": provider_id,
                "model": model,
                "local_stress_level": self._local_stress_level,
                "local_recent_failures": self._local_recent_failures,
                "latency_sec": latency_sec,
                "success": success,
            },
        )
        self._auto_tune_governor()

    def should_defer_procurement(self) -> Tuple[bool, str]:
        """Defer heavy procurement benchmarks when local hardware is stressed."""
        defer_at = int(self.config.get("procurement_defer_stress_level") or 2)
        combined = self._local_stress_level + self._governor_stress_level
        if combined >= defer_at:
            return True, f"stress_local_{self._local_stress_level}_gov_{self._governor_stress_level}"
        return False, "ok"

    def combined_stress_level(self) -> int:
        return self._local_stress_level + self._governor_stress_level

    def record_dispatch(
        self,
        *,
        loop: str,
        provider_id: str,
        success: bool,
        latency_sec: float,
        ttft_sec: Optional[float] = None,
        timeout: bool = False,
        error: Optional[str] = None,
    ) -> None:
        """Record routing/procurement execution metrics."""
        pt = self._get_provider(provider_id)
        if success:
            pt.record_success(latency_sec=latency_sec, ttft_sec=ttft_sec)
        else:
            pt.record_failure(kind=error or "dispatch_fail", latency_sec=latency_sec, timeout=timeout)

        _append_jsonl(
            TELEMETRY_LOG,
            {
                "event": "dispatch_metric",
                "loop": loop,
                "provider_id": provider_id,
                "success": success,
                "latency_sec": latency_sec,
                "ttft_sec": ttft_sec,
                "timeout": timeout,
                "error": error,
            },
        )
        self._maybe_triage_provider(provider_id, pt, loop=loop, latest_latency=latency_sec, latest_ttft=ttft_sec)

    def record_loop_summary(
        self,
        *,
        loop: str,
        duration_sec: float,
        tasks: int = 1,
        failures: int = 0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        sample = {
            "loop": loop,
            "duration_sec": duration_sec,
            "tasks": tasks,
            "failures": failures,
            **(extra or {}),
        }
        self._system_samples.append(sample)
        _append_jsonl(TELEMETRY_LOG, {"event": "loop_summary", **sample})
        self._auto_tune_governor()

    def is_blacklisted(self, provider_id: str) -> bool:
        return self._get_provider(provider_id).is_blacklisted()

    def effective_priority(self, provider_id: str, base_priority: int) -> int:
        pt = self._get_provider(provider_id)
        if pt.is_blacklisted():
            return -999
        return max(0, base_priority - pt.throttle_penalty)

    def wrap_governor_http(
        self,
        governor: Any,
        *,
        loop: str,
        expected_sec: float,
        provider_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Acquire HTTP slot with zombie task registration + force-release callback."""
        released = {"done": False}

        def _force_release() -> None:
            if released["done"]:
                return
            released["done"] = True
            try:
                if hasattr(governor, "force_release_http"):
                    governor.force_release_http()
                else:
                    governor.release_http()
            except Exception:
                pass

        task_id = self.zombie_guard.register(
            loop=loop,
            expected_sec=expected_sec,
            provider_id=provider_id,
            release_cb=_force_release,
        )
        acquired = governor.acquire_http()
        if not acquired:
            self.zombie_guard.unregister(task_id)
            return False, None
        return True, task_id

    def release_governor_http(self, governor: Any, task_id: Optional[str]) -> None:
        try:
            governor.release_http()
        finally:
            if task_id:
                self.zombie_guard.unregister(task_id)

    def _maybe_triage_provider(
        self,
        provider_id: str,
        pt: ProviderTelemetry,
        *,
        loop: str,
        latest_latency: float,
        latest_ttft: Optional[float],
    ) -> Optional[Dict[str, Any]]:
        if not self.config.get("enabled", True):
            return None

        cfg = self.config
        actions: List[Dict[str, Any]] = []

        # Consecutive timeout cluster
        if pt.consecutive_timeouts >= int(cfg.get("consecutive_timeout_threshold") or 3):
            act = self._blacklist_provider(
                provider_id,
                pt,
                reason=f"consecutive_timeouts_{pt.consecutive_timeouts}",
                loop=loop,
                message=f"Blacklisted {provider_id} due to {pt.consecutive_timeouts} consecutive timeouts",
            )
            actions.append(act)

        # Latency spike vs p95 baseline
        p95 = pt.latency_p95()
        spike_mult = float(cfg.get("latency_spike_multiplier") or 2.5)
        if p95 and latest_latency > p95 * spike_mult:
            act = self._throttle_provider(
                provider_id,
                pt,
                reason=f"latency_spike_{latest_latency:.2f}s_vs_p95_{p95:.2f}s",
                loop=loop,
                message=f"Throttled {provider_id} due to latency spike ({latest_latency:.2f}s vs p95 {p95:.2f}s)",
            )
            actions.append(act)

        # TTFT drift
        if latest_ttft is not None:
            drift = pt.ttft_drift_ratio(latest_ttft)
            drift_mult = float(cfg.get("ttft_drift_alert_multiplier") or 2.0)
            if drift and drift >= drift_mult:
                act = self._throttle_provider(
                    provider_id,
                    pt,
                    reason=f"ttft_drift_{drift:.2f}x",
                    loop=loop,
                    message=f"Throttled {provider_id} due to TTFT drift ({drift:.2f}x baseline)",
                )
                actions.append(act)

        # Failure cluster (non-timeout)
        if pt.consecutive_failures >= int(cfg.get("consecutive_failure_threshold") or 4):
            act = self._blacklist_provider(
                provider_id,
                pt,
                reason=f"consecutive_failures_{pt.consecutive_failures}",
                loop=loop,
                message=f"Blacklisted {provider_id} due to failure cluster",
            )
            actions.append(act)

        return actions[-1] if actions else None

    def _throttle_provider(
        self,
        provider_id: str,
        pt: ProviderTelemetry,
        *,
        reason: str,
        loop: str,
        message: str,
    ) -> Dict[str, Any]:
        delta = int(self.config.get("throttle_priority_delta") or 5)
        pt.throttle_penalty = min(50, pt.throttle_penalty + delta)
        pt.last_triage = _utc_now()
        pt.last_triage_reason = reason
        self._apply_registry_priority(provider_id, -delta)
        evt = {
            "action": "throttle_priority",
            "provider_id": provider_id,
            "loop": loop,
            "reason": reason,
            "throttle_penalty": pt.throttle_penalty,
            "message": message,
        }
        _append_jsonl(OPTIMIZATION_LOG, evt)
        self._save_state()
        return evt

    def _blacklist_provider(
        self,
        provider_id: str,
        pt: ProviderTelemetry,
        *,
        reason: str,
        loop: str,
        message: str,
    ) -> Dict[str, Any]:
        ttl = int(self.config.get("temp_blacklist_sec") or 3600)
        pt.blacklisted_until = time.time() + ttl
        pt.consecutive_timeouts = 0
        pt.consecutive_failures = 0
        pt.last_triage = _utc_now()
        pt.last_triage_reason = reason
        evt = {
            "action": "temp_blacklist",
            "provider_id": provider_id,
            "loop": loop,
            "reason": reason,
            "blacklist_sec": ttl,
            "message": message,
        }
        _append_jsonl(OPTIMIZATION_LOG, evt)
        self._save_state()
        return evt

    def _on_zombie_task(self, task: TrackedTask, elapsed: float) -> None:
        evt = {
            "action": "zombie_terminated",
            "task_id": task.task_id,
            "loop": task.loop,
            "provider_id": task.provider_id,
            "thread_ident": task.thread_ident,
            "pid": task.pid,
            "elapsed_sec": round(elapsed, 2),
            "message": (
                f"Killed stalled background thread PID {task.pid} "
                f"(thread {task.thread_ident}) in {task.loop}"
            ),
        }
        _append_jsonl(OPTIMIZATION_LOG, evt)
        if task.provider_id:
            pt = self._get_provider(task.provider_id)
            self._blacklist_provider(
                task.provider_id,
                pt,
                reason="zombie_thread",
                loop=task.loop,
                message=f"Blacklisted {task.provider_id} after zombie thread detection",
            )
        self._governor_stress_level = min(5, self._governor_stress_level + 1)
        self._auto_tune_governor()

    def _apply_registry_priority(self, provider_id: str, delta: int) -> None:
        """Persist priority adjustment to fleet registry."""
        try:
            import yaml  # type: ignore

            if not REGISTRY_PATH.is_file():
                return
            reg = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}
            for section in ("compute_providers", "context_providers"):
                for p in reg.get(section) or []:
                    if p.get("id") == provider_id:
                        current = int(p.get("priority") or 0)
                        p["priority"] = max(0, current + delta)
                        p["telemetry_throttled_at"] = _utc_now()
            body = yaml.safe_dump(reg, sort_keys=False, allow_unicode=True)
            if atomic_write_text is not None:
                atomic_write_text(REGISTRY_PATH, body, min_bytes=20)
            else:
                REGISTRY_PATH.write_text(body, encoding="utf-8")
        except Exception:
            pass

    def _auto_tune_governor(self) -> Dict[str, Any]:
        """Adapt procurement governor limits to real-time stress."""
        if not self.config.get("auto_tune_governor", True):
            return {"tuned": False}

        recent_failures = sum(1 for s in list(self._system_samples)[-10:] if s.get("failures", 0) > 0)
        blacklisted = sum(1 for p in self._providers.values() if p.is_blacklisted())
        stress = self.combined_stress_level() + recent_failures + blacklisted

        try:
            import yaml  # type: ignore

            if not REGISTRY_PATH.is_file():
                return {"tuned": False, "stress": stress}
            reg = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}
            proc = reg.setdefault("procurement", {})
            baseline = proc.setdefault("_telemetry_baseline", {
                "max_http_per_tick": int(proc.get("max_http_per_tick") or 12),
                "max_concurrent_http": int(proc.get("max_concurrent_http") or 2),
                "max_benchmarks_per_tick": int(proc.get("max_benchmarks_per_tick") or 3),
            })
            base_http = int(baseline.get("max_http_per_tick") or 12)
            base_conc = int(baseline.get("max_concurrent_http") or 2)
            base_bench = int(baseline.get("max_benchmarks_per_tick") or 3)

            if stress >= 3:
                proc["max_http_per_tick"] = max(4, base_http - int(self.config.get("governor_stress_http_reduction") or 2))
                proc["max_concurrent_http"] = max(1, base_conc - int(self.config.get("governor_stress_concurrency_reduction") or 1))
                proc["max_benchmarks_per_tick"] = max(1, base_bench - 1)
                proc["telemetry_stress_level"] = stress
                evt = {
                    "action": "governor_auto_tune",
                    "stress_level": stress,
                    "max_http_per_tick": proc["max_http_per_tick"],
                    "max_concurrent_http": proc["max_concurrent_http"],
                    "message": f"Reduced governor limits due to stress level {stress}",
                }
                _append_jsonl(OPTIMIZATION_LOG, evt)
            elif stress == 0 and proc.get("telemetry_stress_level"):
                proc["max_http_per_tick"] = base_http
                proc["max_concurrent_http"] = base_conc
                proc["max_benchmarks_per_tick"] = base_bench
                proc.pop("telemetry_stress_level", None)
                evt = {
                    "action": "governor_recovery",
                    "message": "Governor stress cleared — limits restored to baseline",
                    "max_http_per_tick": base_http,
                    "max_concurrent_http": base_conc,
                }
                _append_jsonl(OPTIMIZATION_LOG, evt)

            body = yaml.safe_dump(reg, sort_keys=False, allow_unicode=True)
            if atomic_write_text is not None:
                atomic_write_text(REGISTRY_PATH, body, min_bytes=20)
            else:
                REGISTRY_PATH.write_text(body, encoding="utf-8")
            return {"tuned": True, "stress": stress, "procurement": proc}
        except Exception as exc:
            return {"tuned": False, "error": str(exc)}

    def optimize_tick(self) -> Dict[str, Any]:
        """Scan zombies, decay throttle penalties, emit dashboard report."""
        zombie_events = self.zombie_guard.scan_zombies()
        decayed = []
        now = time.time()
        with self._lock:
            for pid, pt in self._providers.items():
                if pt.throttle_penalty > 0 and not pt.is_blacklisted():
                    pt.throttle_penalty = max(0, pt.throttle_penalty - 1)
                    if pt.throttle_penalty == 0:
                        decayed.append(pid)

        self._auto_tune_governor()
        report = {
            "timestamp": _utc_now(),
            "zombie_events": zombie_events,
            "throttle_decayed": decayed,
            "active_tasks": self.zombie_guard.active_tasks(),
            "providers": {pid: pt.to_dict() for pid, pt in self._providers.items()},
            "governor_stress": self._governor_stress_level,
        }
        if atomic_write_json is not None:
            atomic_write_json(TELEMETRY_REPORT, report, indent=2)
        else:
            TELEMETRY_REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        self._save_state()
        return report

    def status(self) -> Dict[str, Any]:
        defer, defer_reason = self.should_defer_procurement()
        return {
            "enabled": self.config.get("enabled"),
            "providers_tracked": len(self._providers),
            "blacklisted": [pid for pid, pt in self._providers.items() if pt.is_blacklisted()],
            "active_tasks": self.zombie_guard.active_tasks(),
            "governor_stress": self._governor_stress_level,
            "local_stress": self._local_stress_level,
            "combined_stress": self.combined_stress_level(),
            "procurement_deferred": defer,
            "procurement_defer_reason": defer_reason,
            "config": self.config,
        }

    def _save_state(self) -> None:
        try:
            TELEMETRY_STATE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "providers": {pid: pt.to_dict() for pid, pt in self._providers.items()},
                "governor_stress_level": self._governor_stress_level,
                "local_stress_level": self._local_stress_level,
                "local_recent_failures": self._local_recent_failures,
                "combined_stress_level": self.combined_stress_level(),
                "updated_at": _utc_now(),
            }
            if atomic_write_json is not None:
                atomic_write_json(TELEMETRY_STATE, data, indent=2)
            else:
                TELEMETRY_STATE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass

    def _load_state(self) -> None:
        if not TELEMETRY_STATE.is_file():
            return
        try:
            data = json.loads(TELEMETRY_STATE.read_text(encoding="utf-8"))
            self._governor_stress_level = int(data.get("governor_stress_level") or 0)
            self._local_stress_level = int(data.get("local_stress_level") or 0)
            self._local_recent_failures = int(data.get("local_recent_failures") or 0)
            for pid, pdata in (data.get("providers") or {}).items():
                self._providers[pid] = ProviderTelemetry.from_dict(pdata, self._window_size())
        except Exception:
            pass


def spawn_silent_process(
    args: List[str],
    *,
    cwd: Optional[str] = None,
    timeout_sec: Optional[float] = None,
) -> subprocess.Popen:
    """Launch background worker without console window (Windows-safe)."""
    kw: Dict[str, Any] = {
        "cwd": cwd,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kw["creationflags"] = _SUBPROCESS_FLAGS
    proc = subprocess.Popen(args, **kw)
    if timeout_sec:
        get_telemetry_monitor().zombie_guard.register_process(
            proc,
            loop="silent_subprocess",
            expected_sec=float(timeout_sec),
            provider_id=None,
        )
    return proc


def get_telemetry_monitor(*, reload: bool = False) -> SovereignTelemetryMonitor:
    """Process-wide telemetry singleton."""
    global _MONITOR_SINGLETON
    with _MONITOR_LOCK:
        if _MONITOR_SINGLETON is None or reload:
            _MONITOR_SINGLETON = SovereignTelemetryMonitor()
        return _MONITOR_SINGLETON


def simulate_stalled_process_test() -> Dict[str, Any]:
    """Verify Popen terminate/kill path on zombie detection."""
    monitor = SovereignTelemetryMonitor(
        config={"enabled": True, "start_watchdog": False, "zombie_multiplier": 1.5}
    )
    if sys.platform == "win32":
        cmd = ["cmd", "/c", "timeout", "/t", "30", "/nobreak"]
    else:
        cmd = ["sleep", "30"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_SUBPROCESS_FLAGS if sys.platform == "win32" else 0,
    )
    task_id = monitor.zombie_guard.register_process(
        proc,
        loop="procurement_subprocess",
        expected_sec=0.3,
        provider_id="test-stall-subprocess",
    )
    time.sleep(0.55)
    events = monitor.zombie_guard.scan_zombies()
    monitor.zombie_guard.unregister(task_id)
    terminated = proc.poll() is not None
    return {
        "zombie_events": events,
        "process_terminated": terminated,
        "pass": bool(events) and terminated and events[0].get("kind") == "process",
    }


def simulate_stalled_provider_test() -> Dict[str, Any]:
    """
    End-to-end: register a stalled task, watchdog kills it, auto-triage fires.
    Uses short expected window for fast verification.
    """
    monitor = SovereignTelemetryMonitor(
        config={
            "enabled": True,
            "start_watchdog": False,
            "zombie_multiplier": 1.5,
            "watchdog_interval_sec": 0.3,
            "temp_blacklist_sec": 60,
            "consecutive_timeout_threshold": 2,
        }
    )
    provider_id = "test-stall-openrouter-free"
    semaphore = threading.Semaphore(1)
    semaphore.acquire(timeout=1)
    released = {"ok": False}

    def _force_release() -> None:
        try:
            semaphore.release()
            released["ok"] = True
        except ValueError:
            released["ok"] = False

    task_id = monitor.zombie_guard.register(
        loop="procurement_benchmark",
        expected_sec=0.4,
        provider_id=provider_id,
        release_cb=_force_release,
    )

    # Simulate stall — sleep past 1.5x window (0.6s)
    time.sleep(0.75)
    zombie_events = monitor.zombie_guard.scan_zombies()

    # Record timeout cluster to trigger blacklist triage
    pt = monitor._get_provider(provider_id)
    pt.record_failure(kind="timeout", timeout=True)
    pt.record_failure(kind="timeout", timeout=True)
    triage = monitor._maybe_triage_provider(
        provider_id, pt, loop="procurement_benchmark", latest_latency=30.0, latest_ttft=25.0
    )

    monitor.zombie_guard.unregister(task_id)

    # Read optimization log tail
    opt_tail: List[Dict[str, Any]] = []
    if OPTIMIZATION_LOG.is_file():
        lines = OPTIMIZATION_LOG.read_text(encoding="utf-8").strip().splitlines()
        for line in lines[-5:]:
            try:
                opt_tail.append(json.loads(line))
            except Exception:
                pass

    return {
        "zombie_events": zombie_events,
        "semaphore_force_released": released["ok"],
        "triage": triage,
        "provider_blacklisted": monitor.is_blacklisted(provider_id),
        "optimization_log_tail": opt_tail,
        "pass": bool(zombie_events) and released.get("ok") and monitor.is_blacklisted(provider_id),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sovereign Telemetry Monitor")
    parser.add_argument("--optimize-tick", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--simulate-stall", action="store_true")
    parser.add_argument("--simulate-process", action="store_true")
    args = parser.parse_args()

    if args.simulate_process:
        print(json.dumps(simulate_stalled_process_test(), indent=2))
    elif args.simulate_stall:
        print(json.dumps(simulate_stalled_provider_test(), indent=2))
    elif args.optimize_tick:
        print(json.dumps(get_telemetry_monitor().optimize_tick(), indent=2))
    else:
        print(json.dumps(get_telemetry_monitor().status(), indent=2))
