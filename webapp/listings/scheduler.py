"""
APScheduler background jobs for periodic scraping.

Started from ListingsConfig.ready() so it runs once when Django boots.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Europe/Prague")
    return _scheduler


def _scrape_job(config_id: int) -> None:
    """APScheduler calls this with the config primary key."""
    from listings.models import SearchConfig
    from listings.services.scraper import run_scrape

    try:
        config = SearchConfig.objects.get(pk=config_id, is_active=True)
    except SearchConfig.DoesNotExist:
        logger.warning("SearchConfig %d not found or inactive, skipping scrape.", config_id)
        return

    logger.info("Running scrape for config '%s' (id=%d).", config.name, config_id)
    run_scrape(config)


def schedule_config(config) -> None:
    """Add or replace the job for a SearchConfig."""
    scheduler = get_scheduler()
    job_id = f"scrape_{config.pk}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(
        _scrape_job,
        trigger=IntervalTrigger(seconds=config.interval_sec),
        id=job_id,
        args=[config.pk],
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    logger.info(
        "Scheduled config '%s' every %ds.", config.name, config.interval_sec
    )


def unschedule_config(config_id: int) -> None:
    """Remove the job for a SearchConfig."""
    scheduler = get_scheduler()
    job_id = f"scrape_{config_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Unscheduled config id=%d.", config_id)


def start_scheduler() -> None:
    """
    Load all active SearchConfigs and start the scheduler.
    Called once from ListingsConfig.ready().
    """
    from listings.models import SearchConfig

    scheduler = get_scheduler()

    configs = SearchConfig.objects.filter(is_active=True)
    for config in configs:
        schedule_config(config)

    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler started with %d jobs.", len(configs))
