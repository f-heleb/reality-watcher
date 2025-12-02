# bez_watcher.py
from __future__ import annotations

import os
import threading
import time
from typing import Set, Dict, Any, List
import datetime as dt
import traceback

from slack_sdk.web import WebClient

from config import DEFAULT_INTERVAL_SEC
from slack_utils import slack_post_blocks, slack_post_text
from bez_parser import extract_new_listings
from bez_formatter import build_listing_blocks_bez

# AI modul
from ai_analysis import call_chatgpt_for_listing, format_analysis_for_slack


class BezWatcher(threading.Thread):
    """
    Background watcher for Bezrealitky filters.
    Exactly the same logic as Sreality watcher, but using:
      - bez_parser.extract_new_listings
      - bez_formatter.build_listing_blocks_bez
    Volitelně umí volat AI analýzu (env BEZ_AI_ANALYSIS_ENABLED=1).
    """

    @staticmethod
    def normalize_search_url(url: str, force_first_page: bool = True, cache_bust: bool = True) -> str:
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
        self.scan_limit = scan_limit
        self.burst_take = burst_take
        self.announce = bool(announce)
        self.stop = stop_event or threading.Event()

        self.state_repo = state_repo
        if state_repo:
            try:
                self.seen_ids: Set[str] = set(state_repo.get_seen(self.state_key) or [])
            except Exception:
                self.seen_ids = set()
        else:
            self.seen_ids = set()

        # AI toggle z env
        self.ai_enabled = os.getenv("BEZ_AI_ANALYSIS_ENABLED", "0").strip() in ("1", "true", "yes")

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
                fallback=f"👋 Bezrealitky watcher started. Interval {self.interval_sec}s\nFilter: {self.url}",
            )
        except Exception:
            pass

    def _run_ai_on_items(self, items: List[Dict[str, Any]]):
        """
        Pro každý listing v items spustí AI analýzu a pošle ji do Slacku
        (jen pokud je BEZ_AI_ANALYSIS_ENABLED=1).
        """
        if not self.ai_enabled:
            return

        for it in items:
            try:
                analysis = call_chatgpt_for_listing(it)
                text = format_analysis_for_slack(analysis, it)

                # pošleme jako samostatnou zprávu (klidně by šlo později změnit na thread)
                slack_post_text(self.client, self.channel_id, text)
                print(f"[{self.channel_id}] AI analysis sent for listing {it.get('id')}")
            except Exception as e:
                print(f"[{self.channel_id}] ERROR in AI analysis: {e!r}")
                traceback.print_exc()

    def run(self):
        # start log
        print(f"[{self.channel_id}] watcher START, url={self.url}, interval={self.interval_sec}s")

        # případně oznámení do Slacku
        if self.announce:
            self._announce_start()

        # log aktuálních seen_ids
        print(f"[{self.channel_id}] initial seen_ids: {len(self.seen_ids)}")
        if self.ai_enabled:
            print(f"[{self.channel_id}] AI analysis is ENABLED for Bezrealitky watcher.")
        else:
            print(f"[{self.channel_id}] AI analysis is DISABLED (set BEZ_AI_ANALYSIS_ENABLED=1 to enable).")

        # hlavní smyčka watcheru
        while not self.stop.is_set():
            try:
                print(f"[{self.channel_id}] tick {dt.datetime.now().isoformat()}, seen={len(self.seen_ids)}")

                # případně promaž staré záznamy a znovu načti seen_ids
                if self.state_repo:
                    try:
                        prune = getattr(self.state_repo, "prune_old", None)
                        if callable(prune):
                            prune(self.state_key, max_age_days=3)
                        self.seen_ids = set(self.state_repo.get_seen(self.state_key) or [])
                    except Exception:
                        pass

                new_items, total = extract_new_listings(
                    self.url,
                    self.seen_ids,
                    scan_limit=self.scan_limit,
                    take=self.burst_take,
                )

                print(f"[{self.channel_id}] scraped total={total}, new={len(new_items)}")

                if new_items:
                    # poslat nové listingy jako bloky
                    blocks = build_listing_blocks_bez(new_items)
                    slack_post_blocks(self.client, self.channel_id, blocks)

                    # uložit stav
                    self._save_seen()
                    print(f"[{self.channel_id}] saved seen_ids={len(self.seen_ids)}")

                    # AI analýza (pokud zapnutá)
                    # self._run_ai_on_items(new_items)

            except Exception as e:
                # aby vlákno nespadlo potichu
                print(f"[{self.channel_id}] ERROR in watcher loop: {e!r}")
                traceback.print_exc()

            # sleep (s možností rychlého ukončení)
            for _ in range(self.interval_sec):
                if self.stop.is_set():
                    print(f"[{self.channel_id}] watcher STOP requested")
                    return
                time.sleep(1)


# simple standalone repo
class BezMemoryStateRepo:
    def __init__(self):
        self._db: Dict[str, Set[str]] = {}

    def get_seen(self, cid: str):
        return list(self._db.get(cid, set()))

    def save_seen(self, cid: str, ids: List[str]):
        self._db[cid] = set(ids)


# --- aliasy pro bez_manager.py ---


class Watcher(BezWatcher):
    """Alias, aby `from bez_watcher import Watcher` fungoval."""
    pass


class MemoryStateRepo(BezMemoryStateRepo):
    """Alias, aby `from bez_watcher import MemoryStateRepo` fungoval."""
    pass