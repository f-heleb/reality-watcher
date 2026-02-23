from __future__ import annotations
from typing import List, Dict, Any
import re
from datetime import datetime

from slack_sdk.web import WebClient

from src.core.ai_analysis import call_chatgpt_for_listing, format_analysis_for_slack

NBSP = "\u00A0"

def slack_post_text(client: WebClient, channel_id: str, text: str):
    """Post plain text into a Slack channel."""
    resp = client.chat_postMessage(channel=channel_id, text=text)
    if not resp.get("ok"):
        raise RuntimeError(f"Slack text post failed: {resp}")


def slack_post_blocks(client: WebClient, channel_id: str, blocks: list, fallback: str = "Update"):
    """
    Send Block Kit message to Slack.
    If blocks=[], Slack still requires a fallback text.
    """
    payload = {"channel": channel_id, "text": fallback}
    if blocks:
        payload["blocks"] = blocks
    resp = client.chat_postMessage(**payload)
    if not resp.get("ok"):
        raise RuntimeError(f"Slack blocks post failed: {resp}")

def _format_listing_to_text(it: Dict[str, Any]) -> str:
    """
    Interní helper – vrátí mrkdwn text pro jeden listing.
    Používá se jak v batch, tak v single variantě.
    """
    title = it.get("title", "Unknown")
    url = it.get("url", "")
    price = it.get("price_czk")
    area = it.get("area_m2")
    ppm2 = it.get("price_per_m2")
    locality = it.get("locality") or ""
    dispo = it.get("dispo") or ""

    # Line 1: title + price
    line1 = f"*{title}*"
    if price:
        line1 += f" — {price:,} Kč".replace(",", NBSP)

    # Line 2: locality + dispo
    parts2 = []
    if locality:
        parts2.append(f"📍 {locality}")
    if dispo:
        parts2.append(f"🛋 {dispo}")
    line2 = " · ".join(parts2) if parts2 else ""

    # Line 3: area + price per m²
    parts3 = []
    if area:
        parts3.append(f"📐 {area} m²")
    if ppm2:
        parts3.append(f"{int(ppm2):,} Kč/m²".replace(",", NBSP))
    line3 = " | ".join(parts3) if parts3 else ""

    # Link line
    link_line = f"🔗 <{url}|Open on Sreality>"

    # Combine
    text = line1
    if line2:
        text += f"\n{line2}"
    if line3:
        text += f"\n{line3}"
    text += f"\n{link_line}"

    return text


def build_listing_blocks(items: List[dict], header_text: str = "New listings") -> list:
    """
    Formats a list of listings into Slack's Block Kit.
    → POUŽÍVEJ PRO BATCH (více inzerátů v jedné zprávě)

    Každý item má:
        title, url, a případně price_czk, area_m2, price_per_m2, locality, dispo
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    blocks: list = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{header_text} – {ts}"}},
        {"type": "divider"},
    ]

    for it in items:
        text = _format_listing_to_text(it)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
        blocks.append({"type": "divider"})

    return blocks


def build_listing_blocks_single(it: Dict[str, Any], header_text: str = "New listing") -> list:
    """
    Bloky pro JEDEN listing – aby šel poslat jako samostatná Slack zpráva
    a šlo na něj reagovat odděleně (např. :mag:).
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    blocks: list = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{header_text} – {ts}"}},
        {"type": "divider"},
    ]

    text = _format_listing_to_text(it)
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
    blocks.append({"type": "divider"})

    return blocks

def invite_users_to_channel(client: WebClient, channel_id: str, users: List[str]):
    """
    Invite up to 30 users at a time. Slack hard limit: 30 per request.
    Ignores already_in_channel / cant_invite_self errors.
    """
    if not users:
        return

    BATCH = 30
    batch: list[str] = []

    def _flush():
        if not batch:
            return
        try:
            resp = client.conversations_invite(channel=channel_id, users=",".join(batch))
            if not resp.get("ok") and resp.get("error") not in ("already_in_channel", "cant_invite_self"):
                raise RuntimeError(f"Slack invite failed: {resp}")
        except Exception:
            # Swallow typical invite errors to keep UX smooth
            pass

    for u in users:
        if not u:
            continue
        batch.append(u)
        if len(batch) == BATCH:
            _flush()
            batch = []

    _flush()

def _channel_name_exists(client: WebClient, name: str) -> bool:
    cursor = None
    while True:
        resp = client.conversations_list(limit=1000, cursor=cursor, types="public_channel,private_channel")
        for ch in resp.get("channels", []):
            if ch["name"] == name:
                return True
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return False


def safe_rename_with_increment(client: WebClient, channel_id: str, base_name: str) -> str:
    """
    Rename a channel to `<base>-archN`, with the smallest available N.
    Returns the new name.
    """
    safe_base = re.sub(r"[^a-z0-9_-]+", "-", base_name.lower())

    n = 1
    while True:
        candidate = f"{safe_base}-arch{n}"
        if not _channel_name_exists(client, candidate):
            resp = client.conversations_rename(channel=channel_id, name=candidate)
            if not resp.get("ok"):
                raise RuntimeError(f"Failed to rename channel to {candidate}: {resp}")
            return candidate
        n += 1


def archive_channel(client: WebClient, channel_id: str):
    """Archive a channel (usually after rename)."""
    resp = client.conversations_archive(channel=channel_id)
    if not resp.get("ok"):
        raise RuntimeError(f"Archiving failed: {resp}")
        

def send_listing_analysis_dm(
    client: WebClient,
    user_id: str,
    listing: Dict[str, Any],
) -> None:
    """
    Zavolá AI analýzu pro daný listing a pošle ji uživateli jako DM.
    """
    # 1) zavolat AI
    analysis = call_chatgpt_for_listing(listing)
    text = format_analysis_for_slack(analysis, listing)

    # 2) otevřít / získat DM kanál s uživatelem
    dm_resp = client.conversations_open(users=[user_id])
    dm_channel = dm_resp["channel"]["id"]

    # 3) poslat zprávu do DM kanálu
    client.chat_postMessage(
        channel=dm_channel,
        text=text,
    )