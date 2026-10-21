"""Job dispatch: RQ (Redis) when configured, inline execution otherwise."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from core.config.settings import get_settings

logger = logging.getLogger(__name__)

_inline_override: bool | None = None


def set_inline(value: bool | None) -> None:
    global _inline_override
    _inline_override = value


def enqueue(func: Callable[..., Any], *args: Any, job_timeout: int = 1800, **kwargs: Any) -> Any:
    settings = get_settings()
    inline = _inline_override if _inline_override is not None else not settings.redis_url
    if inline:
        return func(*args, **kwargs)
    from redis import Redis
    from rq import Queue, Retry

    queue = Queue(settings.queue_name, connection=Redis.from_url(settings.redis_url))
    return queue.enqueue(func, *args, job_timeout=job_timeout, retry=Retry(max=3, interval=[60, 300, 900]), **kwargs)
