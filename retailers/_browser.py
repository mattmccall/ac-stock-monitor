"""Helper for using Playwright's sync API across multiple adapters.

Playwright's sync API runs its driver on a per-thread event loop and does not
reliably allow a second `sync_playwright()` in the same thread after the first
has closed (raising e.g. "PlaywrightContextManager object has no attribute
'_playwright'"). When the full pipeline runs both Hornbach and HiFi (each using
Playwright) in one process, the second would fail.

Running each Playwright session in its own short-lived thread gives it a fresh
event loop, so any number of adapters can use Playwright sequentially.
"""

from __future__ import annotations

import threading
from typing import Callable, TypeVar

T = TypeVar("T")


def run_in_thread(fn: Callable[[], T]) -> T:
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # re-raised on the caller's thread
            box["error"] = exc

    t = threading.Thread(target=target)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["value"]
