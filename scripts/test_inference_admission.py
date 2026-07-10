#!/usr/bin/env python3
"""Unit tests for FIFO admission helpers."""
from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from inference_queue import (  # noqa: E402
    COMFY_YIELD_FIFO_DEPTH,
    LANE_NORMAL,
    LANE_ROLEPLAY,
    MAX_INTERACTIVE_FIFO_DEPTH,
    PRIORITY_BACKGROUND,
    PRIORITY_INTERACTIVE,
    PRIORITY_NORMAL,
    QueueAdmissionRejected,
    QueueEntry,
    _comfy_yield_fields,
    _insert_by_priority,
    _is_background_caller,
    _is_interactive_caller,
    admission_snapshot,
    fifo_pressure_tier,
    resolve_priority_class,
)


def test_background_caller_markers() -> None:
    assert _is_background_caller("grok-inbox-consumer")
    assert _is_background_caller("fleet_procurement_tick")
    assert not _is_background_caller("discord-api-session")


def test_interactive_vs_background_lane() -> None:
    assert _is_interactive_caller("cron", LANE_NORMAL) is False
    assert _is_interactive_caller("discord", LANE_NORMAL) is True
    assert _is_interactive_caller("cron", LANE_ROLEPLAY) is True


def test_resolve_priority_class() -> None:
    assert resolve_priority_class("discord", LANE_NORMAL) == PRIORITY_INTERACTIVE
    assert resolve_priority_class("cron", LANE_NORMAL) == PRIORITY_BACKGROUND
    assert resolve_priority_class("agent-auto", LANE_NORMAL) == PRIORITY_INTERACTIVE
    assert resolve_priority_class("rp", LANE_ROLEPLAY) == PRIORITY_INTERACTIVE


def test_insert_by_priority_order() -> None:
    lane = deque()
    entries = [
        QueueEntry(id="bg1", model="m", caller="cron", lane=LANE_NORMAL, priority_class=PRIORITY_BACKGROUND),
        QueueEntry(id="in1", model="m", caller="discord", lane=LANE_NORMAL, priority_class=PRIORITY_INTERACTIVE),
        QueueEntry(id="nm1", model="m", caller="agent", lane=LANE_NORMAL, priority_class=PRIORITY_NORMAL),
        QueueEntry(id="bg2", model="m", caller="inbox", lane=LANE_NORMAL, priority_class=PRIORITY_BACKGROUND),
    ]
    for entry in entries:
        _insert_by_priority(lane, entry)
    assert [e.id for e in lane] == ["in1", "nm1", "bg1", "bg2"]


def test_admission_snapshot_shape() -> None:
    snap = admission_snapshot()
    assert "waiting_count" in snap
    assert "total_pressure" in snap
    assert snap["max_interactive_depth"] == MAX_INTERACTIVE_FIFO_DEPTH
    assert "interactive_waiting" in snap
    assert "normal_waiting" in snap
    assert "background_waiting" in snap
    assert "priority_classes" in snap


def test_fifo_pressure_tier() -> None:
    assert fifo_pressure_tier(0) == "cool"
    assert fifo_pressure_tier(2) == "warm"
    assert fifo_pressure_tier(COMFY_YIELD_FIFO_DEPTH) == "hot"


def test_comfy_yield_fields_depth_gate() -> None:
    hot = _comfy_yield_fields(
        waiting_count=COMFY_YIELD_FIFO_DEPTH,
        interactive_waiting=0,
        active=False,
        rp_waiting=0,
    )
    assert hot["defer_comfy"] is True
    assert hot["reason"].startswith("fifo_depth_")
    cool = _comfy_yield_fields(
        waiting_count=0,
        interactive_waiting=0,
        active=False,
        rp_waiting=0,
    )
    assert cool["defer_comfy"] is False


def test_queue_admission_rejected_attrs() -> None:
    exc = QueueAdmissionRejected("fifo_depth_12", waiting_count=12, retry_after_sec=60)
    assert exc.waiting_count == 12
    assert exc.retry_after_sec == 60


def main() -> int:
    tests = [
        test_background_caller_markers,
        test_interactive_vs_background_lane,
        test_resolve_priority_class,
        test_insert_by_priority_order,
        test_admission_snapshot_shape,
        test_fifo_pressure_tier,
        test_comfy_yield_fields_depth_gate,
        test_queue_admission_rejected_attrs,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"ERROR {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())