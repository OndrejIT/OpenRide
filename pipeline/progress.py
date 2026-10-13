"""Progress of long pipeline steps; the caller (the worker task) installs a callback, e.g. writing to the DB."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

_callback: Callable[[str, float], None] | None = None


@contextmanager
def reporting(callback: Callable[[str, float], None]) -> Iterator[None]:
    """Route report() calls to `callback(step, percent)`; it may raise to abort the processing."""
    global _callback
    _callback = callback
    try:
        yield
    finally:
        _callback = None


def report(step: str, done: float = 0.0, total: float = 1.0) -> None:
    """`step` is shown to the admin as is (Czech); done/total is the progress within the step."""
    if _callback is not None:
        _callback(step, 100.0 * min(max(done / total, 0.0), 1.0) if total > 0 else 0.0)
