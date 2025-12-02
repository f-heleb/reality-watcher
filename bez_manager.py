# bez_manager.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import json
import threading
import time
import html
from typing import Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

from ai_analysis import call_chatgpt_for_listing, format_analysis_for_slack
from slack_sdk.web import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse


# --- ENV / config ---
BEZ_SLACK_BOT_TOKEN = os.environ.get("BEZ_SLACK_BOT_TOKEN", "").strip()
BEZ_SLACK_APP_TOKEN = os.environ.get("BEZ_SLACK_APP_TOKEN", "").strip()
DEFAULT_INTERVAL_SEC = int(os.environ.get("DEFAULT_INTERVAL_SEC", "60"))

# dedikované soubory, ať se to nemíchá se Sreality
CONFIG_PATH = os.environ.get("BEZ_WATCHERS_JSON", "bez_watchers.json")
STATE_PATH  = os.environ.get("BEZ_SEEN_STATE_JSON", "bez_seen_state.json")

# --- lokální utility (sdílené s Sreality verzí) ---
from slack_utils import (
    slack_post_text,
    slack_post_blocks,
    invite_users_to_channel,
    safe_rename_with_increment,
    archive_channel,
    build_listing_blocks,  # použijeme pro první dávku po add
)

# BezRealitky parser (samostatný, NEROZBIJÍ Sreality)
from bez_parser import fetch_page, extract_new_listings

# Pro běžící smyčku použijeme speciální watcher pro BezRealitky
# Pokud ho ještě nemáš, můžeš dočasně běžet jen na první dávce (viz _send_initial_batch).
try:
    from bez_watcher import Watcher as BezWatcher, MemoryStateRepo as BezMemoryStateRepo
    HAVE_BEZ_WATCHER = True
except Exception:
    HAVE_BEZ_WATCHER = False


# ---------------------------
# JSON persist helpers
# ---------------------------
def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path: str, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------
# Channel helpers
# ---------------------------
def _normalize_short_name(short: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", short.lower())[:80]

def _ensure_private_channel(client: WebClient, name: str) -> tuple[str, bool]:
    """
    Ensure PRIVATE channel with given name exists.
    Returns (channel_id, created_now: bool)
    """
    safe = _normalize_short_name(name)
    cursor = None
    while True:
        resp = client.conversations_list(limit=1000, cursor=cursor, types="public_channel,private_channel")
        for ch in resp.get("channels", []):
            if ch["name"] == safe:
                return ch["id"], False
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    # create private channel
    try:
        resp = client.conversations_create(name=safe, is_private=True)
        ch = resp["channel"]
        return ch["id"], True
    except Exception as e:
        err = getattr(getattr(e, "response", None), "data", str(e))
        raise RuntimeError(f"conversations.create failed for #{safe}: {err}")


# ---------------------------
# Minimal state repo (fallback pokud není bez_watcher)
# ---------------------------
class _MemoryStateRepo:
    def __init__(self):
        self._db: Dict[str, set] = {}

    def get_seen(self, channel_id: str):
        return list(self._db.get(channel_id, set()))

    def save_seen(self, channel_id: str, seen_sorted: List[str]):
        self._db[channel_id] = set(seen_sorted)


class JsonStateRepo(_MemoryStateRepo):
    """
    In-memory repo + JSON persistence pro seen IDs (per-channel).
    """
    def __init__(self, path: str = STATE_PATH):
        super().__init__()
        self.path = path
        raw = _load_json(self.path, {})
        for ch, ids in raw.items():
            if isinstance(ids, list):
                self._db[ch] = set(ids)

    def save_seen(self, channel_id: str, seen_sorted: List[str]) -> None:
        super().save_seen(channel_id, seen_sorted)
        data = {k: sorted(list(v)) for k, v in self._db.items()}
        _save_json(self.path, data)


# ---------------------------
# Bot Manager
# ---------------------------
class BotManager:
    """
    Befehly:
      @BezRealitky add <short> <URL> [--interval 60] [@user ...]
      @BezRealitky add_here <short> <URL> [--interval 60] [@user ...]
      @BezRealitky remove <short>
      @BezRealitky interval <short> <seconds>
      @BezRealitky list
    """
    def __init__(self, client: WebClient, state_repo: Optional[JsonStateRepo] = None):
        self.client = client
        self.state_repo = state_repo or JsonStateRepo()

        # aktivní watchery & config
        self.watchers_cfg: Dict[str, dict] = _load_json(CONFIG_PATH, {})
        self.threads: Dict[str, threading.Thread] = {}     # channel_id -> thread
        self.stops: Dict[str, threading.Event] = {}        # channel_id -> stop event

        # obnova po startu (pouze pokud máme bez_watcher)
        if HAVE_BEZ_WATCHER:
            for short, cfg in list(self.watchers_cfg.items()):
                cid = cfg.get("channel_id")
                url = cfg.get("url")
                interval = int(cfg.get("interval", DEFAULT_INTERVAL_SEC))
                if not cid or not url:
                    continue
                if cid in self.threads:
                    continue
                stop = threading.Event()
                self.stops[cid] = stop
                th = BezWatcher(
                    channel_id=cid,
                    url=url,
                    slack_client=self.client,
                    interval_sec=interval,
                    state_repo=self.state_repo,
                    burst_take=20,
                    stop_event=stop,
                )
                self.threads[cid] = th
                th.start()

    # -----------------------
    # util parsing
    # -----------------------
    def _parse_invitees(self, tail: str) -> List[str]:
        tail = (tail or "").strip()
        ids = set()
        for m in re.finditer(r"<@([A-Z0-9]+)>", tail):
            ids.add(m.group(1))
        return list(ids)

    def _parse_interval_from_tail(self, tail: str, default_val: int) -> int:
        if not tail:
            return int(default_val)
        m = re.search(r"--interval\s+(\d+)", tail)
        if m:
            return int(m.group(1))
        m = re.search(r"\binterval\s*=\s*(\d+)\b", tail)
        if m:
            return int(m.group(1))
        return int(default_val)

    def _unwrap_url(self, url_token: str) -> str:
        """
        Z URL tokenu udělá čisté URL:
          - <https://...|Title> → https://...
          - &amp; → &
          - odstraní okolní uvozovky/backticky
        """
        u = (url_token or "").strip()
        if u.startswith("<") and u.endswith(">"):
            u = u[1:-1]
        if "|" in u:
            u = u.split("|", 1)[0]
        u = html.unescape(u)
        if (u.startswith('"') and u.endswith('"')) or (u.startswith("'") and u.endswith("'")):
            u = u[1:-1]
        if u.startswith("`") and u.endswith("`"):
            u = u[1:-1]
        return u

    # -----------------------
    # helper: initial one-shot batch (hned po add)
    # -----------------------
    def _send_initial_batch(self, channel_id: str, url: str, seen_ids: set | None = None, take: int = 10):
        try:
            _ = fetch_page(url, timeout=10)  # reachability
        except Exception as e:
            slack_post_text(self.client, channel_id, f"⛔ URL not reachable: {e}")
            return

        seen = seen_ids or set()
        try:
            new_items, total = extract_new_listings(url, seen, scan_limit=300, take=take)
            if new_items:
                blocks = build_listing_blocks(new_items, header_text=f"New listings ({len(new_items)})")
                slack_post_blocks(self.client, channel_id, blocks, fallback="New listings")
            else:
                slack_post_text(self.client, channel_id, f"ℹ️ No listings found right now (total={total}).")
        except Exception as e:
            slack_post_text(self.client, channel_id, f"⚠️ Initial fetch failed: {e}")
            
    def handle_reaction(self, event: dict):
        """
        Emoji reakce na zprávu v kanálu → AI analýza daného inzerátu.
        Bereme text + bloky zprávy, vytáhneme z nich URL a pošleme to do ai_analysis.
        """
        item = event.get("item") or {}
        channel_id = item.get("channel")
        ts = item.get("ts")
    
        if not channel_id or not ts:
            print("[bez-ai] reaction without channel/ts, skipping")
            return
    
        user_id = event.get("user")
        reaction = event.get("reaction")
        print(f"[bez-ai] reaction_added by {user_id} :{reaction}: on {channel_id} {ts}")
    
        # Reagujeme jen na lupu :mag:
        if reaction != "ai_analysis":
            print("[bez-ai] reaction is not :ai_analysis:, skipping")
            return
    
        # Reagujeme jen v kanálech, kde běží BezRealitky watcher
        watcher_channels = {cfg.get("channel_id") for cfg in self.watchers_cfg.values()}
        if channel_id not in watcher_channels:
            print("[bez-ai] reaction in non-watcher channel, skipping")
            return


        try:
            resp = self.client.conversations_history(
                channel=channel_id,
                latest=ts,
                inclusive=True,
                limit=1,
            )
            messages = resp.get("messages", [])
            if not messages:
                print("[bez-ai] no message found for reaction")
                return
            msg = messages[0]
        except Exception as e:
            print(f"[bez-ai] ERROR fetching message: {e!r}")
            return

        # složíme text z message + section bloků (tam jsou naše inzeráty)
        text_parts = []
        if msg.get("text"):
            text_parts.append(msg["text"])

        for blk in msg.get("blocks") or []:
            if blk.get("type") == "section":
                t = (blk.get("text") or {}).get("text")
                if t:
                    text_parts.append(t)

        full_text = "\n".join(text_parts)

        # vytáhneme první URL z textu
        import re as _re
        m = _re.search(r"<(https?://[^|>]+)", full_text)
        url = m.group(1) if m else None

        if not url:
            print("[bez-ai] no URL found in message, skipping AI")
            return

        # minimalistický "listing" pro AI – GPT si z textu vytáhne cenu / m2 / dispo / lokaci
        listing = {
            "url": url,
            "raw_text": full_text,
        }

        try:
            analysis = call_chatgpt_for_listing(listing)
            formatted = format_analysis_for_slack(analysis, listing)
        except Exception as e:
            print(f"[bez-ai] ERROR calling OpenAI: {e!r}")
            try:
                slack_post_text(self.client, channel_id, f"⚠️ Chyba AI analýzy: {e}")
            except Exception:
                pass
            return

        # --- POSLAT DO SOUKROMÉ ZPRÁVY (DM) UŽIVATELI ---
        try:
            # conversations_open očekává users jako string (jedno nebo více ID oddělených čárkou)
            im = self.client.conversations_open(users=user_id)
            dm_channel = im["channel"]["id"]

            # pošleme AI výsledek do DM
            slack_post_text(self.client, dm_channel, formatted)

            print(f"[bez-ai] DM analysis sent to user {user_id}")

        except Exception as e:
            print(f"[bez-ai] ERROR sending DM: {e!r}")
            # fallback → do veřejného kanálu, aby se analýza úplně neztratila
            try:
                slack_post_text(self.client, channel_id, formatted)
            except Exception:
                pass
        except Exception as e:
            print(f"[bez-ai] ERROR sending AI message: {e!r}")

    # -----------------------
    # commands
    # -----------------------
    def _cmd_list(self, source_channel_id: str):
        if not self.watchers_cfg:
            slack_post_text(self.client, source_channel_id, "No active watchers.")
            return
        lines = []
        for short, cfg in self.watchers_cfg.items():
            cid = cfg.get("channel_id")
            url = cfg.get("url", "")
            interval = int(cfg.get("interval", DEFAULT_INTERVAL_SEC))
            ch_ref = f"<#{cid}>"
            try:
                info = self.client.conversations_info(channel=cid)
                ch_name = info["channel"]["name"]
                ch_ref = f"<#{cid}|#{ch_name}>"
            except Exception:
                pass
            lines.append(f"• `{short}` → {ch_ref} · interval {interval}s\n  {url}")
        slack_post_text(self.client, source_channel_id, "Active watchers:\n" + "\n".join(lines))

    def handle_command(self, source_channel_id: str, user_id: str, text: str):
        txt = re.sub(r"<@[^>]+>\s*", "", text or "").strip()

        # add <short> <url> [--interval X] [mentions...]
        m = re.match(r"(?is)^\s*add\s+([a-z0-9_-]{2,32})\s+(\S.+?)\s*$", txt)
        if m:
            short, rest = m.groups()
            parts = rest.strip().split(None, 1)
            url_token = parts[0]
            tail = parts[1] if len(parts) > 1 else ""
            url = self._unwrap_url(url_token)
            self._cmd_add(source_channel_id, user_id, short, url, tail)
            return

        # add_here <short> <url> [--interval X] [mentions...]
        m = re.match(r"(?is)^\s*add_here\s+([a-z0-9_-]{2,32})\s+(\S.+?)\s*$", txt)
        if m:
            short, rest = m.groups()
            parts = rest.strip().split(None, 1)
            url_token = parts[0]
            tail = parts[1] if len(parts) > 1 else ""
            url = self._unwrap_url(url_token)
            self._cmd_add_here(source_channel_id, user_id, short, url, tail)
            return

        # remove <short>
        m = re.match(r"(?i)^\s*remove\s+([a-z0-9_-]{2,32})\s*$", txt)
        if m:
            self._cmd_remove(source_channel_id, m.group(1))
            return

        # interval <short> <seconds>
        m = re.match(r"(?i)^\s*interval\s+([a-z0-9_-]{2,32})\s+(\d+)\s*$", txt)
        if m:
            self._cmd_interval(source_channel_id, m.group(1), int(m.group(2)))
            return

        # list
        if re.match(r"(?i)^\s*list\s*$", txt):
            self._cmd_list(source_channel_id)
            return

        slack_post_text(self.client, source_channel_id,
                        "I don't understand.\n"
                        "• `add <short> <URL> [--interval 60] [@user ...]`\n"
                        "• `add_here <short> <URL> [--interval 60] [@user ...]`\n"
                        "• `remove <short>`\n"
                        "• `interval <short> <seconds>`\n"
                        "• `list`")

    # ----- command impls -----
    def _cmd_add(self, source_channel_id: str, user_id: str, short: str, url: str, tail: str):
        # reachability
        try:
            _ = fetch_page(url, timeout=10)
        except Exception as e:
            slack_post_text(self.client, source_channel_id, f"⛔ URL not reachable: {e}")
            return

        interval = self._parse_interval_from_tail(tail, DEFAULT_INTERVAL_SEC)
        invitees = self._parse_invitees(tail)

        ch_name = f"bez-{_normalize_short_name(short)}"
        try:
            target_cid, created = _ensure_private_channel(self.client, ch_name)
        except RuntimeError as e:
            slack_post_text(self.client, source_channel_id, f"⛔ Cannot create channel: {e}")
            return

        # join (safety), private create už bota obsahuje
        try:
            self.client.conversations_join(channel=target_cid)
        except Exception:
            pass

        # invite author + extra (bez bota)
        auth = self.client.auth_test()
        bot_uid = auth.get("user_id")
        inv = set(invitees)
        if user_id:
            inv.add(user_id)
        if bot_uid in inv:
            inv.remove(bot_uid)
        invite_users_to_channel(self.client, target_cid, list(inv))

        # persist
        self.watchers_cfg[short] = {"channel_id": target_cid, "url": url, "interval": interval}
        _save_json(CONFIG_PATH, self.watchers_cfg)

        # okamžitě pošleme první dávku (aby bylo něco vidět)
        self._send_initial_batch(target_cid, url, seen_ids=set(), take=10)

        # a pokud máme bez_watcher, spustíme smyčku
        if HAVE_BEZ_WATCHER:
            if target_cid in self.threads:
                self.stops[target_cid].set()
                self.threads[target_cid].join(timeout=5)
            stop = threading.Event()
            self.stops[target_cid] = stop
            th = BezWatcher(
                channel_id=target_cid,
                url=url,
                slack_client=self.client,
                interval_sec=interval,
                state_repo=self.state_repo,
                burst_take=20,
                stop_event=stop,
            )
            self.threads[target_cid] = th
            th.start()

        invited_txt = ", ".join(f"<@{u}>" for u in inv) if inv else "none"
        slack_post_text(self.client, source_channel_id,
                        f"✅ Created <#{target_cid}> (interval {interval}s)\n"
                        f"Filter: {url}\nInvited: {invited_txt}")

    def _cmd_add_here(self, source_channel_id: str, user_id: str, short: str, url: str, tail: str):
        try:
            _ = fetch_page(url, timeout=10)
        except Exception as e:
            slack_post_text(self.client, source_channel_id, f"⛔ URL not reachable: {e}")
            return

        interval = self._parse_interval_from_tail(tail, DEFAULT_INTERVAL_SEC)
        invitees = self._parse_invitees(tail)

        # invite author + extra
        auth = self.client.auth_test()
        bot_uid = auth.get("user_id")
        inv = set(invitees)
        if user_id:
            inv.add(user_id)
        if bot_uid in inv:
            inv.remove(bot_uid)
        invite_users_to_channel(self.client, source_channel_id, list(inv))

        self.watchers_cfg[short] = {"channel_id": source_channel_id, "url": url, "interval": interval}
        _save_json(CONFIG_PATH, self.watchers_cfg)

        # pošli první dávku hned sem
        self._send_initial_batch(source_channel_id, url, seen_ids=set(), take=10)

        # a smyčka, pokud dostupná
        if HAVE_BEZ_WATCHER:
            if source_channel_id in self.threads:
                self.stops[source_channel_id].set()
                self.threads[source_channel_id].join(timeout=5)

            stop = threading.Event()
            self.stops[source_channel_id] = stop
            th = BezWatcher(
                channel_id=source_channel_id,
                url=url,
                slack_client=self.client,
                interval_sec=interval,
                state_repo=self.state_repo,
                burst_take=20,
                stop_event=stop,
            )
            self.threads[source_channel_id] = th
            th.start()

        invited_txt = ", ".join(f"<@{u}>" for u in inv) if inv else "none"
        slack_post_text(self.client, source_channel_id,
                        f"✅ Watcher `{short}` attached **here** (interval {interval}s)\n"
                        f"Filter: {url}\nInvited: {invited_txt}")

    def _cmd_remove(self, source_channel_id: str, short: str):
        cfg = self.watchers_cfg.get(short)
        if not cfg:
            slack_post_text(self.client, source_channel_id, f"ℹ️ Watcher `{short}` does not exist.")
            return

        cid = cfg["channel_id"]
        # stop thread if running
        if cid in self.stops:
            self.stops[cid].set()
        if cid in self.threads:
            self.threads[cid].join(timeout=5)
            self.threads.pop(cid, None)
        self.stops.pop(cid, None)

        # archive with increment suffix
        try:
            info = self.client.conversations_info(channel=cid)
            name = info["channel"]["name"]
            new_name = safe_rename_with_increment(self.client, cid, name)
            archive_channel(self.client, cid)
            suffix = f" → renamed to `#{new_name}` and archived"
        except Exception as e:
            suffix = f"(archive/rename skipped: {e})"

        # purge config
        self.watchers_cfg.pop(short, None)
        _save_json(CONFIG_PATH, self.watchers_cfg)

        slack_post_text(self.client, source_channel_id, f"🛑 Watcher `{short}` removed {suffix}.")

    def _cmd_interval(self, source_channel_id: str, short: str, seconds: int):
        cfg = self.watchers_cfg.get(short)
        if not cfg:
            slack_post_text(self.client, source_channel_id, f"ℹ️ Watcher `{short}` does not exist.")
            return

        cfg["interval"] = int(seconds)
        _save_json(CONFIG_PATH, self.watchers_cfg)

        cid = cfg["channel_id"]
        if HAVE_BEZ_WATCHER:
            # restart watcher to apply new interval
            if cid in self.stops:
                self.stops[cid].set()
            if cid in self.threads:
                self.threads[cid].join(timeout=5)

            stop = threading.Event()
            self.stops[cid] = stop
            th = BezWatcher(
                channel_id=cid,
                url=cfg["url"],
                slack_client=self.client,
                interval_sec=int(seconds),
                state_repo=self.state_repo,
                burst_take=20,
                stop_event=stop,
            )
            self.threads[cid] = th
            th.start()

        slack_post_text(self.client, source_channel_id, f"⏱ Interval for `{short}` set to {seconds}s.")

    # -----------------------
    # graceful shutdown
    # -----------------------
    def shutdown(self):
        for ev in self.stops.values():
            ev.set()
        for th in self.threads.values():
            th.join(timeout=5)


# ---------------------------
# Socket Mode handler
# ---------------------------
def socket_mode_handler(bot: BotManager):
    def _handler(client: SocketModeClient, req: SocketModeRequest):
        if req.type == "events_api":
            event = req.payload.get("event", {})
            et = event.get("type")
            ch = event.get("channel")

            # ACK co nejdřív
            client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

            # 1) REACTION_ADDED → AI analýza BezRealitky
            if et == "reaction_added":
                try:
                    bot.handle_reaction(event)
                except Exception as e:
                    print(f"[socket] ERROR in handle_reaction: {e!r}")
                return

            # 2) DIAGNOSTICS: reply to 'ping' even without mention
            if et == "message" and not event.get("bot_id"):
                txt = (event.get("text") or "").strip()
                if txt.lower() == "ping":
                    try:
                        slack_post_text(client.web_client, ch, "pong ✅ (events OK)")
                    except Exception:
                        pass
                    return

                # allow commands without @mention
                if re.match(r"(?i)^(add|add_here|list|remove|interval)\b", txt):
                    try:
                        bot.handle_command(ch, event.get("user"), txt)
                    except Exception as e:
                        try:
                            slack_post_text(client.web_client, ch, f"⚠️ Error: {e}")
                        except Exception:
                            pass
                    return

            # 3) Standard: handle @mention
            if et == "app_mention":
                try:
                    bot.handle_command(ch, event.get("user"), event.get("text") or "")
                except Exception as e:
                    try:
                        slack_post_text(client.web_client, ch, f"⚠️ Error: {e}")
                    except Exception:
                        pass

    return _handler


# ---------------------------
# Main (runnable)
# ---------------------------
def main():
    if not BEZ_SLACK_BOT_TOKEN or not BEZ_SLACK_APP_TOKEN:
        print("ERROR: set BEZ_SLACK_BOT_TOKEN and BEZ_SLACK_APP_TOKEN")
        raise SystemExit(2)

    web = WebClient(token=BEZ_SLACK_BOT_TOKEN)
    bot = BotManager(client=web, state_repo=JsonStateRepo(STATE_PATH))

    # Socket Mode
    sm = SocketModeClient(app_token=BEZ_SLACK_APP_TOKEN, web_client=web)
    sm.socket_mode_request_listeners.append(socket_mode_handler(bot))
    sm.connect()

    print(f"[boot] BEZ manager running | cfg={CONFIG_PATH} | seen={STATE_PATH} | interval={DEFAULT_INTERVAL_SEC}s")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        bot.shutdown()


if __name__ == "__main__":
    main()