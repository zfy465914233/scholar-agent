"""Retry utility with exponential backoff for external API calls."""

from __future__ import annotations

import random
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds


def retry_with_backoff(
    fn: Callable[..., T],
    *args: Any,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    jitter: bool = True,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[int, Exception, float], None] | None = None,
    **kwargs: Any,
) -> T:
    """Call fn with exponential backoff on failure.

    Args:
        fn: The function to call.
        *args: Positional arguments for fn.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds (doubled each retry).
        max_delay: Maximum delay cap in seconds.
        jitter: Add random jitter to avoid thundering herd.
        retry_on: Exception types to retry on.
        on_retry: Optional callback(retry_number, exception, delay) called before each retry.
        **kwargs: Keyword arguments for fn.

    Returns:
        The return value of fn.

    Raises:
        The last exception if all retries exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except retry_on as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            if jitter:
                delay *= (0.5 + random.random())
            if on_retry:
                on_retry(attempt + 1, exc, delay)
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]
