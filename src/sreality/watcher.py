"""
Sreality.cz Watcher - Background polling thread for monitoring search results.
"""
from __future__ import annotations

import threading
import time
from typing import Set, Any

from src.utils.stats_utils import log_append
from src.core.config import DEFAULT_INTERVAL_SEC
from slack_sdk.web import WebClient

from src.utils.slack_utils import (
    slack_post_blocks,
    build_listing_blocks_single,  # nově – jeden listing per message
)
from src.sreality.parser import (
    extract_new_listings,  # (url, seen_ids, scan_limit, take) -> (new_items, total)
)


class Watcher(threading.Thread):
    """
    Background worker that polls a Sreality search URL and posts NEW listings to Slack.

    Args:
        channel_id: Slack channel to post to (e.g. C0123456789)
        url: Sreality search URL
        interval_sec: polling interval (seconds)
        slack_client: initialized WebClient with bot token
        state_repo: object providing get_seen(key) -> list[str] and save_seen(key, list[str])
                    If None, an in-memory set is used (not persisted).
        scan_limit: how many anchor links to scan on the page
        burst_take: max number of NEW items to send in one pass
        state_key: klíč pro state_repo (např. short z watchers.json). Pokud None, použije se channel_id.
    """

    @staticmethod
    def normalize_search_url(url: str, force_first_page: bool = True, cache_bust: bool = True) -> str:
        # Nepoužíváme parse_qs/urlencode, ať nezničíme klíče typu 'plocha-do'
        sep = "&" if "?" in url else "?"
        out = url
        if force_first_page and "page=" not in url:
            out = f"{out}{sep}page=1"
            sep = "&"
        if cache_bust:
            import time as _t
            out = f"{out}{sep}_ts={int(_t.time())}"
        return out

    def __init__(
        self,
        channel_id: str,
        url: str,
        slack_client: WebClient,
        interval_sec: int | None = None,
        state_repo: Any | None = None,
        scan_limit: int = 300,
        burst_take: int = 20,
        announce: bool = True,
        stop_event: threading.Event | None = None,
        state_key: str | None = None,
    ):
        super().__init__(daemon=True)
        self.channel_id = channel_id
        self.url = url
        self.client = slack_client
        self.state_key = state_key or channel_id
        self.interval_sec = int(interval_sec or DEFAULT_INTERVAL_SEC)
        self.scan_limit = int(scan_limit)
        self.burst_take = int(burst_take)
        self.announce = bool(announce)
        self.stop = stop_event or threading.Event()

        self.state_repo = state_repo
        if state_repo:
            try:
                self.seen_ids: Set[str] = set(state_repo.get_seen(self.state_key) or [])
            except Exception:
                self.seen_ids = set()
        else:
            self.seen_ids = set()  # in-memory only

    def _save_seen(self):
        if not self.state_repo:
            return
        try:
            self.state_repo.save_seen(self.state_key, sorted(list(self.seen_ids)))
        except Exception:
            pass

    def _announce_start(self):
        try:
            slack_post_blocks(
                self.client,
                self.channel_id,
                [],
                fallback=f"👋 Watcher started. Interval {self.interval_sec}s\nFilter: {self.url}",
            )
        except Exception:
            pass

    def run(self):
        if self.announce:
            self._announce_start()

        while not self.stop.is_set():
            # před každým během případně promaž staré záznamy a znovu načti seen_ids
            if self.state_repo:
                try:
                    prune = getattr(self.state_repo, "prune_old", None)
                    if callable(prune):
                        # 3 dny TTL
                        prune(self.state_key, max_age_days=3)
                    self.seen_ids = set(self.state_repo.get_seen(self.state_key) or [])
                except Exception:
                    pass

            try:
                new_items, _total = extract_new_listings(
                    self.url,
                    self.seen_ids,
                    scan_limit=self.scan_limit,
                    take=self.burst_take,
                )
                if new_items:
                    # 👉 KAŽDÝ LISTING POŠLI JAKO SAMOSTATNOU ZPRÁVU
                    for it in new_items:
                        try:
                            blocks = build_listing_blocks_single(it)
                            slack_post_blocks(
                                self.client,
                                self.channel_id,
                                blocks,
                                fallback="New listing",
                            )
                        except Exception:
                            # nechceme, aby pád jednoho postu zabil celý watcher
                            pass

                    # zaloguj celou batch jako doposud
                    try:
                        log_append(self.channel_id, new_items)
                    except Exception:
                        pass

                    self._save_seen()

            except Exception as e:
                try:
                    slack_post_blocks(
                        self.client,
                        self.channel_id,
                        [],
                        fallback=f"⚠️ Watcher error: {e}",
                    )
                except Exception:
                    pass

            # sleep with early exit check
            for _ in range(self.interval_sec):
                if self.stop.is_set():
                    break
                time.sleep(1)

