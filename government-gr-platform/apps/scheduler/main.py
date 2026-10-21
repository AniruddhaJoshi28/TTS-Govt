"""APScheduler process: schedules incremental crawls per source using ``schedule_cron`` from sources.yaml.

Crawl jobs are pushed onto RQ when Redis is configured (so workers do the heavy lifting);
otherwise they run in this process. ``max_instances=1`` prevents overlapping runs of a source.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from core.config.settings import get_settings
from core.config.sources import load_sources
from core.observability import log, setup_logging

logger = logging.getLogger(__name__)


def _trigger(source_key: str) -> None:
    from services.discovery.pipeline import run_crawl

    settings = get_settings()
    if settings.redis_url:
        from redis import Redis
        from rq import Queue

        Queue(settings.queue_name, connection=Redis.from_url(settings.redis_url)).enqueue(
            run_crawl, source_key, mode="incremental", job_timeout=6 * 3600)
    else:
        run_crawl(source_key, "incremental")


def build_scheduler() -> BlockingScheduler:
    sched = BlockingScheduler(timezone="Asia/Kolkata")
    for src in load_sources():
        if src.active and src.adapter and src.schedule_cron:
            sched.add_job(_trigger, CronTrigger.from_crontab(src.schedule_cron, timezone="Asia/Kolkata"), args=[src.key],
                          id=f"crawl:{src.key}", max_instances=1, coalesce=True, misfire_grace_time=3600)
            log(logger, logging.INFO, "scheduled", source=src.key, cron=src.schedule_cron)
    return sched


def main() -> None:
    setup_logging()
    build_scheduler().start()


if __name__ == "__main__":
    main()
