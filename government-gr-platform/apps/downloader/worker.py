"""RQ worker for crawl, download and extraction jobs: ``python -m apps.downloader.worker``.

The processor app reuses this worker (``apps.processor.worker``); separate deployments can listen
on different queues by setting ``GR_QUEUE_NAME``.
"""

from __future__ import annotations

from redis import Redis
from rq import Queue, Worker

from core.config.settings import get_settings
from core.observability import setup_logging


def main() -> None:
    setup_logging()
    settings = get_settings()
    if not settings.redis_url:
        raise SystemExit("GR_REDIS_URL is not set; jobs run inline without a worker")
    conn = Redis.from_url(settings.redis_url)
    Worker([Queue(settings.queue_name, connection=conn)], connection=conn).work(with_scheduler=True)


if __name__ == "__main__":
    main()
