"""Shared text-completeness helpers for LLM-generated long documents.

2026-08-18: extracted from tailor.py so resume/cover/prep can share the same
"did the model output all required sections?" check and retry policy.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable


def has_all_sections(text: str, sections: tuple[str, ...]) -> bool:
    """Return True when every required section heading appears in ``text``."""
    return all(s in (text or "") for s in sections)


async def retry_if_incomplete[T](
    coro_factory: Callable[[], Awaitable[T]],
    *,
    is_complete: Callable[[T], bool],
    max_attempts: int = 2,
) -> T:
    """Run ``coro_factory`` up to ``max_attempts`` times until ``is_complete``.

    Returns the last result even if it never becomes complete, so callers can
    decide whether to keep or discard it.
    """
    last: T | None = None
    for _ in range(max_attempts):
        last = await coro_factory()
        if is_complete(last):
            return last
    assert last is not None
    return last
