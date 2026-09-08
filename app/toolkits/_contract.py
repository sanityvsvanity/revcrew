"""Tool contract: every tool the crew holds returns a truthful envelope.

Adopted from the Chief-of-Staff copilot's hardening pass (its LESSONS P15 and
P30): two production incidents there came from tools that either raised (the
model saw a raw exception) or returned a failure with no signal that it was
*permanent*, so the model re-called the same tool with the same arguments until
the tool-call limit ended the turn.

The rules this module enforces:

1. A tool never raises into the model. Failures become
   ``{"ok": false, "error": ..., "error_class": "terminal"|"transient",
   "do_not_retry": bool}``.
2. Failures are classified once, by code. ``classify_error`` is exported so the
   pipeline can obey the classification instead of asking a model to
   re-adjudicate it.
3. An identical failure repeated ``FAIL_THRESHOLD`` times inside
   ``FAIL_WINDOW_S`` trips a breaker: the wrapper short-circuits with
   ``do_not_retry`` instead of making the same doomed call again.
4. A tool that already returned an envelope is passed through untouched, so a
   tool can refuse (budget exhausted, domain denied) with its own precise reason.

Usage::

    @wrap_tool(toolkit="research")
    async def fetch_page(url: str) -> dict: ...

    ResearchTools registers the wrapped function; the agent sees the original
    name, signature and docstring (functools.wraps), so agno builds the same
    schema it would for the bare function.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

FAIL_THRESHOLD = 3
FAIL_WINDOW_S = 120.0

_failures: dict[str, list[float]] = {}

# Terminal hints are checked FIRST. A definite not-found or validation error is
# permanent even when the message also contains a transient-looking word
# ("Could not find page ... shared with your integration connection" once
# matched "connection" and retried forever).
_TERMINAL_HINTS = (
    "validation",
    "invalid",
    "not found",
    "could not find",
    "no such",
    "does not exist",
    "permission",
    "unauthorized",
    "forbidden",
    "insufficient",
    "payment required",
    "400",
    "401",
    "402",
    "403",
    "404",
    "409",
    "422",
    "bad request",
    "malformed",
    "unprocessable",
    "denied",
    "not allowed",
    "budget",
)
_TRANSIENT_HINTS = (
    "timeout",
    "timed out",
    "temporarily",
    "rate limit",
    "ratelimit",
    "too many requests",
    "429",
    "500",
    "502",
    "503",
    "504",
    "connection",
    "reset by peer",
    "unavailable",
    "try again",
)
_TERMINAL_EXC = (ValueError, TypeError, KeyError, AttributeError, LookupError)


def classify_error(text: str, exc: BaseException | None = None) -> str:
    """Return ``"terminal"`` or ``"transient"`` for a failure message.

    Unknown errors default to transient (one retry is allowed); the breaker
    still stops a sustained storm.
    """
    t = (text or "").lower()
    for hint in _TERMINAL_HINTS:
        if hint in t:
            return "terminal"
    for hint in _TRANSIENT_HINTS:
        if hint in t:
            return "transient"
    if exc is not None and isinstance(exc, _TERMINAL_EXC):
        return "terminal"
    return "transient"


def envelope(
    error: str, error_class: str | None = None, **extra: Any
) -> dict[str, Any]:
    """Build a failure envelope. ``do_not_retry`` follows the class unless overridden."""
    cls = error_class or classify_error(error)
    payload: dict[str, Any] = {
        "ok": False,
        "error": error,
        "error_class": cls,
        "do_not_retry": cls == "terminal",
    }
    payload.update(extra)
    return payload


def is_envelope(value: Any) -> bool:
    return isinstance(value, dict) and "ok" in value


def _signature(name: str, kwargs: dict[str, Any]) -> str:
    raw = f"{name}|{sorted((k, repr(v)) for k, v in kwargs.items())!r}"
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


def _recent_failures(sig: str) -> int:
    now = time.monotonic()
    hits = [t for t in _failures.get(sig, []) if now - t < FAIL_WINDOW_S]
    if hits:
        _failures[sig] = hits
    else:
        _failures.pop(sig, None)
    return len(hits)


def _record_failure(sig: str) -> int:
    now = time.monotonic()
    hits = [t for t in _failures.get(sig, []) if now - t < FAIL_WINDOW_S]
    hits.append(now)
    _failures[sig] = hits
    return len(hits)


def reset_breaker() -> None:
    """Forget every recorded failure (tests)."""
    _failures.clear()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def wrap_tool(
    fn: Callable[..., Any] | None = None,
    *,
    toolkit: str = "",
    timeout_s: float | None = None,
) -> Callable[..., Any]:
    """Wrap a tool body in the contract. Works as ``@wrap_tool`` or ``@wrap_tool(...)``.

    The wrapped function is always ``async`` and always returns a JSON string:
    agno feeds tool results to the model as text, and a JSON string keeps the
    ``ok`` flag machine-readable for the model *and* for tests. Sync bodies run
    in a worker thread so a slow HTTP call cannot block the event loop.
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        name = getattr(func, "__name__", "tool")
        is_async = asyncio.iscoroutinefunction(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            sig = _signature(name, kwargs)
            if _recent_failures(sig) >= FAIL_THRESHOLD:
                return _dumps(
                    envelope(
                        f"{name} failed {FAIL_THRESHOLD} times with these arguments in the last "
                        f"{int(FAIL_WINDOW_S)}s; not retrying. Change the arguments or note a research gap.",
                        "terminal",
                        breaker=True,
                        toolkit=toolkit,
                    )
                )
            try:
                if is_async:
                    coro = func(*args, **kwargs)
                else:
                    coro = asyncio.to_thread(func, *args, **kwargs)
                result = await (
                    asyncio.wait_for(coro, timeout_s) if timeout_s else coro
                )
            except asyncio.TimeoutError:
                _record_failure(sig)
                return _dumps(
                    envelope(
                        f"{name} timed out after {timeout_s}s",
                        "transient",
                        toolkit=toolkit,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - the contract is exactly to catch everything
                cls = classify_error(str(exc), exc)
                count = _record_failure(sig)
                logger.warning(
                    "tool %s failed (%s, %s/%s): %s",
                    name,
                    cls,
                    count,
                    FAIL_THRESHOLD,
                    exc,
                )
                return _dumps(envelope(f"{name} failed: {exc}", cls, toolkit=toolkit))

            if is_envelope(result):
                if not result.get("ok"):
                    _record_failure(sig)
                else:
                    _failures.pop(sig, None)
                return _dumps(result)
            if isinstance(result, str):
                # Already-rendered text (or an envelope rendered by the tool itself).
                try:
                    parsed = json.loads(result)
                    if is_envelope(parsed) and not parsed.get("ok"):
                        _record_failure(sig)
                except (ValueError, TypeError):
                    pass
                return result
            _failures.pop(sig, None)
            return _dumps({"ok": True, "result": result})

        wrapper.__wrapped_tool__ = True  # type: ignore[attr-defined]
        return wrapper

    if fn is not None:
        return decorate(fn)
    return decorate
