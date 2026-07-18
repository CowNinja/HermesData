#!/usr/bin/env python3
"""
sovereign_memory_manager.py — Virtualized session/workspace memory (Milestone 3).

SQLite-backed checkpointing for working memory + procedural state.
Auto-hydrates last active session on boot; archives episodic summaries to sqlite-vec.

Usage:
  from sovereign_memory_manager import get_memory_manager, hydrate_boot_state
  hydrate_boot_state()
  mgr = get_memory_manager()
  mgr.checkpoint(session_id=sid, working_memory=[...], procedural_state={...})
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DB = Path(r"D:\PhronesisVault\Operations\session_state.sqlite")
MEMORY_LOG = Path(r"D:\PhronesisVault\Operations\logs\sovereign-memory.jsonl")

_MANAGER: Optional["SovereignMemoryManager"] = None
_BOOT_HYDRATION: Optional[Dict[str, Any]] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(event: Dict[str, Any]) -> None:
    try:
        try:
            from jsonl_log_rotator import append_jsonl as _rot_append

            _rot_append(MEMORY_LOG, event, mode="rename", stamp=True)
            return
        except Exception:
            pass
        MEMORY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(MEMORY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")
    except Exception:
        pass


@dataclass
class SessionState:
    session_id: str
    platform: str
    status: str
    working_memory: List[Dict[str, Any]] = field(default_factory=list)
    procedural_state: Dict[str, Any] = field(default_factory=dict)
    checkpoint_seq: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "platform": self.platform,
            "status": self.status,
            "working_memory": self.working_memory,
            "procedural_state": self.procedural_state,
            "checkpoint_seq": self.checkpoint_seq,
            "metadata": self.metadata,
            "updated_at": self.updated_at,
        }


class SovereignMemoryManager:
    """Persistent agent session state across crashes and restarts."""

    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                concluded_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                working_memory TEXT NOT NULL,
                procedural_state TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ckpt_session ON checkpoints(session_id, seq)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def _get_meta(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def ensure_active_session(
        self,
        platform: str = "hermes",
        *,
        session_id: Optional[str] = None,
    ) -> str:
        active = self._get_meta("active_session_id")
        if active and not session_id:
            row = self._conn.execute(
                "SELECT status FROM sessions WHERE session_id = ?",
                (active,),
            ).fetchone()
            if row and row["status"] == "active":
                return active

        sid = session_id or f"sess-{uuid.uuid4().hex[:16]}"
        now = _utc_now()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO sessions (session_id, platform, status, created_at, updated_at)
            VALUES (?, ?, 'active', COALESCE((SELECT created_at FROM sessions WHERE session_id = ?), ?), ?)
            """,
            (sid, platform, sid, now, now),
        )
        self._conn.commit()
        self._set_meta("active_session_id", sid)
        _log({"event": "session_active", "session_id": sid, "platform": platform})
        return sid

    def checkpoint(
        self,
        *,
        session_id: str,
        working_memory: List[Dict[str, Any]],
        procedural_state: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        seq_row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS m FROM checkpoints WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        seq = int(seq_row["m"]) + 1
        ckpt_id = f"ckpt-{session_id}-{seq}"
        now = _utc_now()
        wm = json.dumps(working_memory or [], ensure_ascii=False)
        ps = json.dumps(procedural_state or {}, ensure_ascii=False)
        md = json.dumps(metadata or {}, ensure_ascii=False)

        self._conn.execute(
            """
            INSERT INTO checkpoints
            (checkpoint_id, session_id, seq, working_memory, procedural_state, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ckpt_id, session_id, seq, wm, ps, md, now),
        )
        self._conn.execute(
            "UPDATE sessions SET updated_at = ?, status = 'active' WHERE session_id = ?",
            (now, session_id),
        )
        self._conn.commit()
        self._set_meta("active_session_id", session_id)
        self._set_meta("last_checkpoint_at", now)

        report = {
            "checkpoint_id": ckpt_id,
            "session_id": session_id,
            "seq": seq,
            "working_turns": len(working_memory or []),
            "at": now,
        }
        _log({"event": "checkpoint", **report})
        return report

    def hydrate_last_active(self) -> Optional[SessionState]:
        sid = self._get_meta("active_session_id")
        if not sid:
            row = self._conn.execute(
                """
                SELECT session_id FROM sessions
                WHERE status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ).fetchone()
            sid = row["session_id"] if row else None
        if not sid:
            return None

        ckpt = self._conn.execute(
            """
            SELECT * FROM checkpoints
            WHERE session_id = ?
            ORDER BY seq DESC
            LIMIT 1
            """,
            (sid,),
        ).fetchone()
        if not ckpt:
            sess = self._conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (sid,),
            ).fetchone()
            if not sess:
                return None
            return SessionState(
                session_id=sid,
                platform=sess["platform"],
                status=sess["status"],
                updated_at=sess["updated_at"],
            )

        sess = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (sid,),
        ).fetchone()
        state = SessionState(
            session_id=sid,
            platform=sess["platform"] if sess else "hermes",
            status=sess["status"] if sess else "active",
            working_memory=json.loads(ckpt["working_memory"]),
            procedural_state=json.loads(ckpt["procedural_state"]),
            checkpoint_seq=int(ckpt["seq"]),
            metadata=json.loads(ckpt["metadata"] or "{}"),
            updated_at=ckpt["created_at"],
        )
        _log({"event": "hydrate", "session_id": sid, "seq": state.checkpoint_seq})
        return state

    def append_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        procedural_patch: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = self.hydrate_last_active()
        working = list(state.working_memory if state and state.session_id == session_id else [])
        procedural = dict(state.procedural_state if state and state.session_id == session_id else {})
        working.append({"role": role, "content": content, "ts": _utc_now()})
        if procedural_patch:
            procedural.update(procedural_patch)
        return self.checkpoint(
            session_id=session_id,
            working_memory=working,
            procedural_state=procedural,
            metadata=metadata,
        )

    def _build_episodic_summary(
        self,
        working_memory: List[Dict[str, Any]],
        procedural_state: Dict[str, Any],
    ) -> tuple[str, List[str]]:
        turns = []
        for msg in working_memory[-12:]:
            role = msg.get("role", "user")
            content = str(msg.get("content", ""))[:400].strip()
            if content:
                turns.append(f"{role}: {content}")
        narrative = " | ".join(turns) if turns else "Empty session."
        if len(narrative) > 2000:
            narrative = narrative[:2000] + "..."

        triples: List[str] = []
        task = procedural_state.get("active_task") or procedural_state.get("last_model")
        if task:
            triples.append(f"(session, active_task, {task})")
        tier = procedural_state.get("last_tier")
        if tier:
            triples.append(f"(session, routed_tier, {tier})")
        platform = procedural_state.get("platform")
        if platform:
            triples.append(f"(session, platform, {platform})")
        for i, msg in enumerate(working_memory[-3:]):
            snippet = str(msg.get("content", ""))[:80].replace("\n", " ")
            if snippet:
                triples.append(f"(turn_{i}, {msg.get('role', 'user')}, {snippet})")
        return narrative, triples

    def conclude_session(
        self,
        session_id: str,
        *,
        archive_to_vector: bool = True,
    ) -> Dict[str, Any]:
        state = self.hydrate_last_active()
        if not state or state.session_id != session_id:
            ckpt = self._conn.execute(
                "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY seq DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if not ckpt:
                return {"status": "not_found", "session_id": session_id}
            working = json.loads(ckpt["working_memory"])
            procedural = json.loads(ckpt["procedural_state"])
        else:
            working = state.working_memory
            procedural = state.procedural_state

        narrative, triples = self._build_episodic_summary(working, procedural)
        archive_report: Dict[str, Any] = {"status": "skipped"}
        if archive_to_vector and (narrative or triples):
            try:
                from high_signal_ingestion_pipeline import HighSignalIngestionPipeline

                text = (
                    f"# Episodic Session Archive\n\n"
                    f"**Session:** {session_id}\n\n"
                    f"## Narrative\n{narrative}\n\n"
                    f"## Semantic Triples\n" + "\n".join(f"- {t}" for t in triples)
                )
                pipeline = HighSignalIngestionPipeline()
                archive_report = pipeline.index_text_if_new(
                    text,
                    source_path=f"session://{session_id}",
                    target_id="episodic-memory",
                    category="session-archive",
                    trigger="session_conclude",
                    min_chars=50,
                )
            except Exception as exc:
                archive_report = {"status": "archive_error", "error": str(exc)}

        now = _utc_now()
        self._conn.execute(
            "UPDATE sessions SET status = 'concluded', concluded_at = ?, updated_at = ? WHERE session_id = ?",
            (now, now, session_id),
        )
        self._conn.commit()
        active = self._get_meta("active_session_id")
        if active == session_id:
            self._set_meta("active_session_id", "")

        report = {
            "status": "concluded",
            "session_id": session_id,
            "archive": archive_report,
            "triples_count": len(triples),
            "at": now,
        }
        _log({"event": "session_conclude", **report})
        return report

    def find_active_session_for_platform(self, platform: str) -> Optional[str]:
        """Return latest active session_id for a platform/scope string."""
        row = self._conn.execute(
            """
            SELECT session_id FROM sessions
            WHERE platform = ? AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (platform,),
        ).fetchone()
        return str(row["session_id"]) if row else None

    def hydrate_for_platform(self, platform: str) -> Optional[SessionState]:
        """Hydrate the latest checkpoint for a scoped platform key."""
        sid = self.find_active_session_for_platform(platform)
        if not sid:
            return None
        ckpt = self._conn.execute(
            """
            SELECT * FROM checkpoints
            WHERE session_id = ?
            ORDER BY seq DESC
            LIMIT 1
            """,
            (sid,),
        ).fetchone()
        sess = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (sid,),
        ).fetchone()
        if not ckpt:
            if not sess:
                return None
            return SessionState(
                session_id=sid,
                platform=sess["platform"],
                status=sess["status"],
                updated_at=sess["updated_at"],
            )
        return SessionState(
            session_id=sid,
            platform=sess["platform"] if sess else platform,
            status=sess["status"] if sess else "active",
            working_memory=json.loads(ckpt["working_memory"]),
            procedural_state=json.loads(ckpt["procedural_state"]),
            checkpoint_seq=int(ckpt["seq"]),
            metadata=json.loads(ckpt["metadata"] or "{}"),
            updated_at=ckpt["created_at"],
        )

    def wipe_working_memory(
        self,
        *,
        platform: str,
        session_id: Optional[str] = None,
        preserve_procedural: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Truncate working history for a scoped session — poisoned-context purge."""
        scope = (platform or "roleplay").strip()
        sid = session_id or self.find_active_session_for_platform(scope) or self.ensure_active_session(scope)
        state = self.hydrate_for_platform(scope)
        prior_turns = len(state.working_memory) if state and state.session_id == sid else 0
        procedural = dict(state.procedural_state if state and state.session_id == sid else {})
        if not preserve_procedural:
            procedural = {
                k: v
                for k, v in procedural.items()
                if k in ("platform", "mode")
            }
        procedural["platform"] = scope
        procedural["mode"] = procedural.get("mode") or "uncensored_roleplay"
        procedural["wiped_at"] = _utc_now()
        procedural.pop("active_scene", None)
        procedural.pop("active_task", None)
        report = self.checkpoint(
            session_id=sid,
            working_memory=[],
            procedural_state=procedural,
            metadata={
                **(metadata or {}),
                "wipe": True,
                "turns_removed": prior_turns,
                "scope": scope,
            },
        )
        report.update({
            "status": "wiped",
            "scope": scope,
            "turns_removed": prior_turns,
        })
        _log({"event": "wipe_working_memory", **report})
        return report

    def stats(self) -> Dict[str, Any]:
        sessions = self._conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
        active = self._conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE status = 'active'"
        ).fetchone()["c"]
        ckpts = self._conn.execute("SELECT COUNT(*) AS c FROM checkpoints").fetchone()["c"]
        return {
            "db_path": str(self.db_path),
            "sessions": sessions,
            "active_sessions": active,
            "checkpoints": ckpts,
            "active_session_id": self._get_meta("active_session_id"),
            "last_checkpoint_at": self._get_meta("last_checkpoint_at"),
        }

    def purge_stale_sessions(self, max_age_hours: int = 24) -> int:
        """Archive + remove concluded sessions older than max_age_hours. Returns count purged."""
        cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        stale = self._conn.execute(
            "SELECT session_id FROM sessions WHERE status = 'concluded' AND updated_at < ?",
            (cutoff_iso,),
        ).fetchall()
        purged = 0
        for row in stale:
            sid = row["session_id"]
            self._conn.execute("DELETE FROM checkpoints WHERE session_id = ?", (sid,))
            self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
            purged += 1
        if purged:
            self._conn.commit()
            _log({"event": "purge_stale_sessions", "purged": purged, "max_age_hours": max_age_hours})
        return purged


def make_memory_scope(
    platform: str = "roleplay",
    *,
    chat_id: str = "",
    thread_id: str = "",
    parent_channel_id: str = "",
) -> str:
    """Stable per-channel/thread scope for Discord roleplay isolation."""
    if thread_id:
        return f"discord:thread:{thread_id}"
    if chat_id:
        return f"discord:channel:{chat_id}"
    if parent_channel_id:
        return f"discord:parent:{parent_channel_id}"
    return (platform or "roleplay").strip()


def wipe_discord_roleplay_context(
    *,
    chat_id: str = "",
    thread_id: str = "",
    parent_channel_id: str = "",
    platform: str = "alice-roleplay",
) -> Dict[str, Any]:
    """Purge poisoned roleplay working memory for active Discord channel/thread."""
    scope = make_memory_scope(
        platform,
        chat_id=chat_id,
        thread_id=thread_id,
        parent_channel_id=parent_channel_id,
    )
    mgr = get_memory_manager()
    report = mgr.wipe_working_memory(
        platform=scope,
        metadata={
            "trigger": "discord_context_wipe",
            "chat_id": chat_id,
            "thread_id": thread_id,
            "parent_channel_id": parent_channel_id,
        },
    )
    # Legacy global roleplay bucket — wipe if no scoped session existed
    if platform and platform != scope:
        legacy = mgr.wipe_working_memory(
            platform=platform,
            metadata={"trigger": "discord_context_wipe_legacy", "scope": scope},
        )
        report["legacy_wipe"] = legacy
    return report


def get_memory_manager(db_path: Optional[Path] = None) -> SovereignMemoryManager:
    global _MANAGER
    if _MANAGER is None or (db_path and _MANAGER.db_path != db_path):
        _MANAGER = SovereignMemoryManager(db_path or DEFAULT_DB)
    return _MANAGER


def hydrate_boot_state(*, platform: str = "hermes") -> Optional[Dict[str, Any]]:
    """Query last active session and return hydrated state for gateway/bridge boot."""
    global _BOOT_HYDRATION
    try:
        mgr = get_memory_manager()
        state = mgr.hydrate_last_active()
        if not state:
            sid = mgr.ensure_active_session(platform)
            _BOOT_HYDRATION = {"session_id": sid, "hydrated": False, "new_session": True}
            _log({"event": "boot_new_session", "session_id": sid})
            return _BOOT_HYDRATION

        payload = state.to_dict()
        payload["hydrated"] = True
        payload["new_session"] = False
        _BOOT_HYDRATION = payload
        _log(
            {
                "event": "boot_hydrate",
                "session_id": state.session_id,
                "seq": state.checkpoint_seq,
                "turns": len(state.working_memory),
            }
        )
        return payload
    except Exception as exc:
        _log({"event": "boot_hydrate_error", "error": str(exc)})
        return None


def checkpoint_roleplay_turn(
    *,
    platform: str,
    user_content: str,
    assistant_content: str = "",
    active_scene: str = "",
    campaign: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    chat_id: str = "",
    thread_id: str = "",
    parent_channel_id: str = "",
    memory_scope: str = "",
) -> Optional[Dict[str, Any]]:
    """Unfiltered roleplay checkpoint — preserves full working memory for D&D sessions."""
    try:
        mgr = get_memory_manager()
        scope = memory_scope or make_memory_scope(
            platform or "roleplay",
            chat_id=chat_id,
            thread_id=thread_id,
            parent_channel_id=parent_channel_id,
        )
        sid = mgr.ensure_active_session(scope)
        state = mgr.hydrate_for_platform(scope)
        working = list(state.working_memory if state and state.session_id == sid else [])
        if user_content:
            working.append({"role": "user", "content": user_content})
        if assistant_content:
            working.append({"role": "assistant", "content": assistant_content})
        procedural = dict(state.procedural_state if state and state.session_id == sid else {})
        procedural.update(
            {
                "platform": scope,
                "mode": "uncensored_roleplay",
                "active_scene": active_scene or procedural.get("active_scene", ""),
                "active_task": campaign or procedural.get("active_task", ""),
                "last_checkpoint_trigger": "roleplay_turn",
                "chat_id": chat_id,
                "thread_id": thread_id,
                "parent_channel_id": parent_channel_id,
            }
        )
        return mgr.checkpoint(
            session_id=sid,
            working_memory=working,
            procedural_state=procedural,
            metadata={
                **(metadata or {}),
                "unfiltered": True,
                "memory_scope": scope,
                "chat_id": chat_id,
                "thread_id": thread_id,
            },
        )
    except Exception as exc:
        _log({"event": "roleplay_checkpoint_error", "error": str(exc)})
        return None


def checkpoint_gateway_turn(
    *,
    platform: str,
    messages: List[Dict[str, Any]],
    assistant_content: str = "",
    procedural_state: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Checkpoint after a gateway chat turn (working + procedural memory)."""
    try:
        mgr = get_memory_manager()
        sid = mgr.ensure_active_session(platform)
        working = []
        for msg in messages or []:
            role = str(msg.get("role", "user"))
            content = msg.get("content")
            if isinstance(content, list):
                content = json.dumps(content, ensure_ascii=False)[:8000]
            working.append({"role": role, "content": str(content or "")[:8000]})
        if assistant_content:
            working.append({"role": "assistant", "content": assistant_content[:8000]})
        proc = dict(procedural_state or {})
        proc["platform"] = platform
        proc["last_checkpoint_trigger"] = "gateway_turn"
        return mgr.checkpoint(
            session_id=sid,
            working_memory=working,
            procedural_state=proc,
            metadata=metadata,
        )
    except Exception as exc:
        _log({"event": "checkpoint_error", "error": str(exc)})
        return None


def get_boot_hydration() -> Optional[Dict[str, Any]]:
    return _BOOT_HYDRATION


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sovereign memory manager")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--hydrate", action="store_true")
    parser.add_argument("--conclude", metavar="SESSION_ID")
    parser.add_argument("--wipe-scope", metavar="PLATFORM_SCOPE", help="Truncate working memory for scope")
    parser.add_argument("--wipe-discord", nargs="?", const="", help="chat_id[:thread_id] wipe")
    args = parser.parse_args()

    mgr = get_memory_manager()
    if args.hydrate:
        print(json.dumps(hydrate_boot_state(), indent=2))
    elif args.conclude:
        print(json.dumps(mgr.conclude_session(args.conclude), indent=2))
    elif args.wipe_scope:
        print(json.dumps(mgr.wipe_working_memory(platform=args.wipe_scope), indent=2))
    elif args.wipe_discord is not None:
        parts = (args.wipe_discord or "").split(":")
        chat_id = parts[0] if parts else ""
        thread_id = parts[1] if len(parts) > 1 else ""
        print(json.dumps(wipe_discord_roleplay_context(chat_id=chat_id, thread_id=thread_id), indent=2))
    else:
        print(json.dumps(mgr.stats(), indent=2))
    mgr.close()
