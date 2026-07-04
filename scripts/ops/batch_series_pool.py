"""Expand finite portrait/variation pools to arbitrary batch sizes."""
from __future__ import annotations

from typing import Callable, Sequence, TypeVar

T = TypeVar("T")


def expand_pool(
    base: Sequence[T],
    total: int,
    *,
    rounds: Sequence[Sequence[T]] | None = None,
    decorate: Callable[[T, int], T] | None = None,
) -> list[T]:
    """Cycle base (+ optional alternate rounds) until *total* items exist.

    *rounds* - extra pools used on successive passes (round 2, 3, ...).
    *decorate* - ``(item, round_index) -> item`` applied from round 1 onward.
    """
    if total <= 0:
        return list(base)
    if not base:
        return []

    pools: list[Sequence[T]] = [base]
    if rounds:
        pools.extend(rounds)

    out: list[T] = []
    round_idx = 0
    while len(out) < total:
        pool = pools[round_idx % len(pools)]
        for item in pool:
            if len(out) >= total:
                break
            if round_idx == 0 or decorate is None:
                out.append(item)
            else:
                out.append(decorate(item, round_idx))
        round_idx += 1
    return out


def slice_pool(pool: Sequence[T], *, offset: int = 0, limit: int = 0) -> list[T]:
    """Return ``pool[offset:]`` capped by *limit* when limit > 0."""
    sliced = list(pool[offset:])
    if limit and limit > 0:
        return sliced[:limit]
    return sliced