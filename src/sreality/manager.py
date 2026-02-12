# manager.py
# -*- coding: utf-8 -*-
"""
Sreality.cz Bot Manager - Handles Slack commands and watcher lifecycle.
"""
from __future__ import annotations

import os
import re
import json
import threading
import time
import html
from typing import Dict, List, Optional


from slack_sdk.web import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from src.core.config import DEFAULT_INTERVAL_SEC, CONFIG_PATH, STATE_PATH
from src.sreality.watcher import Watcher
from src.utils.slack_utils import (
    slack_post_text,
    invite_users_to_channel,
    safe_rename_with_increment,
    archive_channel,
    send_listing_analysis_dm
)
from src.sreality.parser import scrape_description, parse_title_fields
from src.utils.stats_utils import stats_last, stats_window

# ---------------------------
# Persistence helpers
# ---------------------------
STATS_LAST_CMD   = re.compile(r"(?i)^\s*stats\s+last\s+(\d+)\s*$")
STATS_WINDOW_CMD = re.compile(
    r"(?i)^\s*stats\s+window\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?)\s*(?:to\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?))?\s*$"
)

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
# In-memory state
# ---------------------------

class MemoryStateRepo:
    """
    Jednoduché in-memory "repo" pro seen IDs (per channel_id).
    """
    def __init__(self):
        self._db: Dict[str, set] = {}

    def get_seen(self, channel_id: str) -> List[str]:
        return list(self._db.get(channel_id, set()))

    def save_seen(self, channel_id: str, seen_sorted: List[str]) -> None:
        self._db[channel_id] = set(seen_sorted)

# ---------------------------
# JSON-persistent state
# ---------------------------

class JsonStateRepo(MemoryStateRepo):
    """
    Extends in-memory repo with JSON persistence for seen ids per channel.
    Nově:
      - ukládá last_seen timestamp (epoch seconds)
      - umí promazat staré záznamy podle TTL
    JSON formát (nový):
      {
        "C123456": {
          "3713540940": 1731600000.0,
          "3713540941": 1731686400.0
        },
        ...
      }

    Zpětně kompatibilní se starým formátem:
      { "C123456": ["3713540940", "3713540941"] }
    """

    def __init__(self, path: str = STATE_PATH):
        super().__init__()
        self.path = path
        raw = _load_json(self.path, {})

        # Interně budeme držet dict[channel_id] -> dict[id] -> last_seen_ts
        self._ts_db: Dict[str, Dict[str, float]] = {}

        for ch, val in raw.items():
            if isinstance(val, list):
                # starý formát: jen list id, dáme jim last_seen=0
                self._ts_db[ch] = {lid: 0.0 for lid in val}
            elif isinstance(val, dict):
                # nový formát: id -> last_seen_ts
                # zajistíme, že hodnoty jsou float
                self._ts_db[ch] = {lid: float(ts) for lid, ts in val.items()}
            else:
                self._ts_db[ch] = {}

        # naplníme _db v MemoryStateRepo (jen idčka)
        for ch, id_map in self._ts_db.items():
            self._db[ch] = set(id_map.keys())

    def get_seen(self, channel_id: str) -> List[str]:
        """
        Vrátí seznam id, která jsou aktuálně považována za 'seen'.
        (po případném pročištění pomocí prune_old)
        """
        return list(self._db.get(channel_id, set()))

    def save_seen(self, channel_id: str, seen_sorted: List[str]) -> None:
        """
        Uloží aktuální sadu 'seen' id pro daný channel + aktualizuje jim last_seen na NOW.
        """
        now = time.time()

        # aktualizuj MemoryStateRepo
        super().save_seen(channel_id, seen_sorted)

        # aktualizuj timestampy
        ch_map = self._ts_db.setdefault(channel_id, {})
        for lid in seen_sorted:
            ch_map[lid] = now

        # uložit na disk
        data_to_save = {ch: id_map for ch, id_map in self._ts_db.items()}
        _save_json(self.path, data_to_save)

    def prune_old(self, channel_id: str, max_age_days: int = 14) -> None:
        """
        Smaže z 'seen' idčka, která jsme neviděli déle než max_age_days.
        Díky tomu se po delší době znovu ukážou jako nové.
        """
        max_age_sec = max_age_days * 24 * 3600
        now = time.time()

        id_map = self._ts_db.get(channel_id) or {}
        if not id_map:
            return

        keep_ids = {}
        for lid, ts in id_map.items():
            age = now - float(ts)
            if age <= max_age_sec:
                keep_ids[lid] = ts

        # přepiš mapu i MemoryStateRepo
        self._ts_db[channel_id] = keep_ids
        self._db[channel_id] = set(keep_ids.keys())

        # persist
        data_to_save = {ch: id_map for ch, id_map in self._ts_db.items()}
        _save_json(self.path, data_to_save)


# ---------------------------
# Bot manager
# ---------------------------

class BotManager:
    def __init__(self, client: WebClient, state_repo: Optional[JsonStateRepo] = None):
        self.client = client
        self.state_repo = state_repo or JsonStateRepo()

        # active watchers & config
        self.watchers_cfg: Dict[str, dict] = _load_json(CONFIG_PATH, {})
        self.threads: Dict[str, threading.Thread] = {}     # channel_id -> thread
        self.stops: Dict[str, threading.Event] = {}        # channel_id -> stop event

        # restore from config on start (nesnaží se oživit archivované kanály)
        for short, cfg in list(self.watchers_cfg.items()):
            cid = cfg.get("channel_id")
            url = cfg.get("url")
            interval = int(cfg.get("interval", DEFAULT_INTERVAL_SEC))
            if not cid or not url:
                continue
            if cid in self.threads:
                continue
            # přeskoč archivované/odstraněné kanály
            try:
                info = self.client.conversations_info(channel=cid)
                if info.get("channel", {}).get("is_archived"):
                    continue
            except Exception:
                continue

            stop = threading.Event()
            self.stops[cid] = stop
            th = Watcher(
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
        return sorted(ids)

    def _parse_interval(self, tail: str, default_val: int) -> int:
        """
        Allow '--interval 60' or 'interval=60' in tail.
        """
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
        Rozbalí URL poslané Slackem:
          - <https://...|title>  → strip <>, split '|'
          - HTML-unescape (&amp; → &), zásadní pro numerické filtry!

        Imunita vůči:
          - uvozovkám: "https://..." nebo 'https://...'
          - backtickům: `https://...`
        """
        s = (url_token or "").strip()

        # strip backticks
        if s.startswith("`") and s.endswith("`"):
            s = s[1:-1].strip()

        # strip quotes
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()

        # strip angle brackets
        if s.startswith("<") and s.endswith(">"):
            s = s[1:-1].strip()

        # split on '|' if present, Slack-style <url|title>
        if "|" in s:
            s = s.split("|", 1)[0].strip()

        # HTML-unescape
        s = html.unescape(s)
        return s

    # -----------------------
    # commands
    # -----------------------
    def handle_command(self, channel_id: str, user_id: str, text: str) -> None:
        """
        text: raw text from Slack "app_mention" event, e.g.:
          "<@U123> add mywatch https://... --interval 90"
        """
        text = text or ""
        # Remove the bot mention at the start if present
        text_wo_mention = re.sub(r"^<@[^>]+>\s*", "", text).strip()
        if not text_wo_mention:
            slack_post_text(self.client, channel_id, "Ahoj, napiš `help` pro nápovědu.")
            return

        # dispatch by first word
        parts = text_wo_mention.split(None, 1)
        cmd = parts[0].lower()
        tail = parts[1] if len(parts) > 1 else ""

        if cmd in ("help", "nápověda"):
            self._cmd_help(channel_id)
            return
        if cmd == "add":
            self._cmd_add(channel_id, tail, add_here=False)
            return
        if cmd == "add_here":
            self._cmd_add(channel_id, tail, add_here=True)
            return
        if cmd == "remove":
            self._cmd_remove(channel_id, tail)
            return
        if cmd == "interval":
            self._cmd_interval(channel_id, tail)
            return
        if cmd == "list":
            self._cmd_list(channel_id)
            return
        if cmd == "stats":
            self._cmd_stats(channel_id, tail)
            return
        if cmd == "rename":
            self._cmd_rename(channel_id, tail)
            return
        if cmd == "archive":
            self._cmd_archive(channel_id, tail)
            return
        if cmd == "analyze":
            self._cmd_analyze(channel_id, tail, user_id)
            return

        slack_post_text(
            self.client,
            channel_id,
            f"Neznámý příkaz `{cmd}`. Zkus `help`.",
        )

    # -----------------------
    # individual commands
    # -----------------------
    def _cmd_help(self, channel_id: str):
        help_text = (
            "*Dostupné příkazy:*\n"
            "• `add <name> <URL> [--interval 60] [@user ...]` – založí nový kanál a watcher\n"
            "• `add_here <name> <URL> [--interval 60] [@user ...]` – pustí watcher do *tohoto* kanálu\n"
            "• `remove <name>` – zastaví watcher a smaže z konfigurace (kanál ponechá)\n"
            "• `interval <name> <seconds>` – změní interval watchera\n"
            "• `list` – vypíše aktivní watchery\n"
            "• `stats last <N>` – statistika posledních N inzerátů\n"
            "• `stats window <from> [to <to>]` – statistika v čase\n"
            "• `rename <name> <new_name>` – přejmenuje watcher (včetně kanálu)\n"
            "• `archive <name>` – archivuje kanál watchera a odstraní ho z konfigurace\n"
            "• `analyze <URL>` – stáhne detail inzerátu, udělá AI analýzu a pošle ti do DM\n"
        )
        slack_post_text(self.client, channel_id, help_text)

    def _cmd_add(self, channel_id: str, tail: str, add_here: bool):
        """
        add <name> <URL> [--interval 60] [@user ...]
        """
        tail = tail.strip()
        if not tail:
            slack_post_text(self.client, channel_id, "Použití: `add <name> <URL> [--interval 60] [@user ...]`")
            return

        parts = tail.split()
        name = parts[0]
        if len(parts) < 2:
            slack_post_text(self.client, channel_id, "Chybí URL. Použití: `add <name> <URL> [--interval 60]`")
            return

        # jméno už nesmí existovat
        if name in self.watchers_cfg:
            slack_post_text(self.client, channel_id, f"Watcher s názvem `{name}` už existuje.")
            return

        # zbytek reconcat, protože URL může obsahovat mezery, uvozovky atd.
        rest = tail[len(name):].strip()

        # hledáme první token, který vypadá jako URL (obsahuje "://")
        m = re.search(r"(\S+://\S+)", rest)
        if not m:
            slack_post_text(self.client, channel_id, "Nenašel jsem URL. Zkus to ve tvaru: `add <name> <URL> ...`")
            return

        url_token = m.group(1)
        url = self._unwrap_url(url_token)

        # interval
        interval = self._parse_interval(rest, DEFAULT_INTERVAL_SEC)

        # Kanál – bud nový, nebo current
        if add_here:
            new_channel_id = channel_id
        else:
            # založíme nový Slack channel
            base_name = f"sreality-{name.lower()}"
            try:
                resp = self.client.conversations_create(name=base_name)
                new_channel_id = resp["channel"]["id"]
            except Exception as e:
                slack_post_text(self.client, channel_id, f"Nepodařilo se vytvořit kanál: {e}")
                return

        # pozvi zmíněné uživatele
        invitees = self._parse_invitees(rest)
        if invitees:
            try:
                invite_users_to_channel(self.client, new_channel_id, invitees)
            except Exception as e:
                slack_post_text(self.client, channel_id, f"Upozornění: nepodařilo se pozvat některé uživatele: {e}")

        # vytvoř watcher thread
        stop = threading.Event()
        self.stops[new_channel_id] = stop
        th = Watcher(
            channel_id=new_channel_id,
            url=url,
            slack_client=self.client,
            interval_sec=interval,
            state_repo=self.state_repo,
            burst_take=20,
            stop_event=stop,
        )
        self.threads[new_channel_id] = th
        th.start()

        # uložit do configu
        self.watchers_cfg[name] = {
            "channel_id": new_channel_id,
            "url": url,
            "interval": interval,
        }
        _save_json(CONFIG_PATH, self.watchers_cfg)

        slack_post_text(
            self.client,
            channel_id,
            f"Watcher `{name}` založen. Sleduje {url} každých {interval} s v kanálu <#{new_channel_id}>.",
        )

    def _cmd_remove(self, channel_id: str, tail: str):
        """
        remove <name>
        """
        name = (tail or "").strip().split()[0] if tail.strip() else ""
        if not name:
            slack_post_text(self.client, channel_id, "Použití: `remove <name>`")
            return

        cfg = self.watchers_cfg.get(name)
        if not cfg:
            slack_post_text(self.client, channel_id, f"Watcher `{name}` neexistuje.")
            return

        cid = cfg.get("channel_id")
        if cid in self.stops:
            self.stops[cid].set()
        if cid in self.threads:
            self.threads[cid].join(timeout=5)
            del self.threads[cid]
        if cid in self.stops:
            del self.stops[cid]

        del self.watchers_cfg[name]
        _save_json(CONFIG_PATH, self.watchers_cfg)

        slack_post_text(self.client, channel_id, f"Watcher `{name}` byl odstraněn (kanál zůstal).")

    def _cmd_interval(self, channel_id: str, tail: str):
        """
        interval <name> <seconds>
        """
        parts = (tail or "").split()
        if len(parts) < 2:
            slack_post_text(self.client, channel_id, "Použití: `interval <name> <seconds>`")
            return
        name, sec_str = parts[0], parts[1]

        cfg = self.watchers_cfg.get(name)
        if not cfg:
            slack_post_text(self.client, channel_id, f"Watcher `{name}` neexistuje.")
            return

        try:
            sec = int(sec_str)
        except ValueError:
            slack_post_text(self.client, channel_id, f"`{sec_str}` není číslo.")
            return

        cid = cfg.get("channel_id")
        if cid not in self.threads:
            slack_post_text(self.client, channel_id, f"Watcher `{name}` aktuálně neběží.")
            return

        # upravíme interval přímo ve watcheru
        th = self.threads[cid]
        try:
            th.interval_sec = sec
        except Exception:
            pass

        cfg["interval"] = sec
        _save_json(CONFIG_PATH, self.watchers_cfg)

        slack_post_text(self.client, channel_id, f"Interval watchera `{name}` byl změněn na {sec} s.")

    def _cmd_list(self, channel_id: str):
        if not self.watchers_cfg:
            slack_post_text(self.client, channel_id, "Žádné watchery nejsou konfigurované.")
            return

        lines = []
        for name, cfg in self.watchers_cfg.items():
            cid = cfg.get("channel_id")
            url = cfg.get("url")
            interval = cfg.get("interval", DEFAULT_INTERVAL_SEC)
            running = "running" if cid in self.threads else "stopped"
            lines.append(f"- `{name}`: <#{cid}> – {url} – interval {interval}s – {running}")

        slack_post_text(self.client, channel_id, "*Watchery:*\n" + "\n".join(lines))

    def _cmd_stats(self, channel_id: str, tail: str):
        tail = (tail or "").strip()
        if not tail:
            slack_post_text(self.client, channel_id, "Použití: `stats last <N>` nebo `stats window <from> [to <to>]`")
            return

        # stats last N
        m_last = STATS_LAST_CMD.match(tail)
        if m_last:
            n = int(m_last.group(1))
            text = stats_last(n)
            slack_post_text(self.client, channel_id, text)
            return

        # stats window from [to]
        m_win = STATS_WINDOW_CMD.match(tail)
        if m_win:
            from_str = m_win.group(1)
            to_str = m_win.group(2)
            text = stats_window(from_str, to_str)
            slack_post_text(self.client, channel_id, text)
            return

        slack_post_text(self.client, channel_id, "Nerozumím. Použití: `stats last <N>` nebo `stats window <from> [to <to>]`")

    def _cmd_rename(self, channel_id: str, tail: str):
        """
        rename <name> <new_name>
        """
        parts = (tail or "").split()
        if len(parts) < 2:
            slack_post_text(self.client, channel_id,
                            "Použití: `rename <name> <new_name>` (přejmenuje watcher i Slack kanál).")
            return
        old_name, new_name = parts[0], parts[1]
        if old_name not in self.watchers_cfg:
            slack_post_text(self.client, channel_id, f"Watcher `{old_name}` neexistuje.")
            return
        if new_name in self.watchers_cfg:
            slack_post_text(self.client, channel_id, f"Watcher `{new_name}` už existuje.")
            return

        cfg = self.watchers_cfg[old_name]
        cid = cfg.get("channel_id")

        # přejmenuj Slack channel
        try:
            new_slack_name = f"sreality-{new_name.lower()}"
            new_slack_name = safe_rename_with_increment(self.client, cid, new_slack_name)
        except Exception as e:
            slack_post_text(self.client, channel_id, f"Nepodařilo se přejmenovat Slack channel: {e}")
            return

        # přepiš config
        cfg["channel_id"] = cid
        self.watchers_cfg[new_name] = cfg
        del self.watchers_cfg[old_name]
        _save_json(CONFIG_PATH, self.watchers_cfg)

        slack_post_text(
            self.client,
            channel_id,
            f"Watcher `{old_name}` byl přejmenován na `{new_name}`, Slack channel nyní #{new_slack_name}.",
        )

    def _cmd_archive(self, channel_id: str, tail: str):
        """
        archive <name>
        """
        name = (tail or "").strip().split()[0] if tail.strip() else ""
        if not name:
            slack_post_text(self.client, channel_id, "Použití: `archive <name>`")
            return

        cfg = self.watchers_cfg.get(name)
        if not cfg:
            slack_post_text(self.client, channel_id, f"Watcher `{name}` neexistuje.")
            return

        cid = cfg.get("channel_id")
        # kill watcher
        if cid in self.stops:
            self.stops[cid].set()
        if cid in self.threads:
            self.threads[cid].join(timeout=5)
            del self.threads[cid]
        if cid in self.stops:
            del self.stops[cid]

        # archivuj kanál
        try:
            archive_channel(self.client, cid)
        except Exception as e:
            slack_post_text(self.client, channel_id, f"Upozornění: nepodařilo se archivovat kanál: {e}")

        # smaž z configu
        del self.watchers_cfg[name]
        _save_json(CONFIG_PATH, self.watchers_cfg)

        slack_post_text(self.client, channel_id, f"Watcher `{name}` byl odstraněn a kanál archivován.")

    def _cmd_analyze(self, channel_id: str, tail: str, user_id: str):
        """
        analyze <URL>
        """
        tail = (tail or "").strip()
        if not tail:
            slack_post_text(self.client, channel_id, "Použití: `analyze <URL>`")
            return

        # najít URL v tailu
        m = re.search(r"(\S+://\S+)", tail)
        if not m:
            slack_post_text(self.client, channel_id, "Nenašel jsem URL. Zkus to ve tvaru: `analyze <URL>`")
            return

        url_token = m.group(1)
        url = self._unwrap_url(url_token)

        try:
            # Získat popis z detail stránky
            description = scrape_description(url)
            
            # Vytvořit základní strukturu listingu
            listing = {
                "url": url,
                "title": url,  # fallback
                "description": description,
                "raw_text": description,  # pro AI analýzu
                "price_czk": None,
                "area_m2": None,
                "dispo": None,
                "locality": None,
                "price_per_m2": None,
            }
            
            # Pokusit se extrahovat více detailů z popisu
            if description:
                # Parsovat základní pole z popisu pokud jsou v textu
                parsed = parse_title_fields(description)
                listing.update(parsed)
                
        except Exception as e:
            slack_post_text(self.client, channel_id, f"Chyba při načítání inzerátu: {e}")
            return

        try:
            # poslat AI analýzu uživateli do DM
            send_listing_analysis_dm(self.client, user_id, listing)
            slack_post_text(
                self.client,
                channel_id,
                f"Analýza inzerátu byla odeslána do tvých DM, <@{user_id}>.",
            )
        except Exception as e:
            slack_post_text(self.client, channel_id, f"Chyba při odesílání analýzy do DM: {e}")

# ---------------------------
# Socket mode handler
# ---------------------------

def socket_mode_handler(bot: BotManager):
    """
    Factory, vrací callback pro SocketModeClient.
    """
    def _handler(client: SocketModeClient, req: SocketModeRequest):
        # acknowledgements
        if req.type == "events_api":
            response = SocketModeResponse(envelope_id=req.envelope_id)
            client.send_socket_mode_response(response)

            event = req.payload.get("event", {}) or {}
            et = event.get("type")
            ch = event.get("channel")

            # 1) PING (plain message "ping") – echo pro test
            if et == "message" and not event.get("bot_id") and (event.get("text") or "").strip().lower() == "ping":
                try:
                    slack_post_text(client.web_client, ch, "pong")
                except Exception:
                    pass
                return

            # 2) Standard: handle @mention
            if et == "app_mention":
                try:
                    bot.handle_command(ch, event.get("user"), event.get("text") or "")
                except Exception as e:
                    try:
                        slack_post_text(client.web_client, ch, f"⚠️ Error: {e}")
                    except Exception:
                        pass

    return _handler