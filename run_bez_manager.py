# run_bez_manager.py
# -*- coding: utf-8 -*-
"""
Main entry point for Bezrealitky.cz watcher bot.
"""
from __future__ import annotations
import time
import logging
from dotenv import load_dotenv

# Load .env first
load_dotenv()

from slack_sdk.web import WebClient
from slack_sdk.socket_mode import SocketModeClient

from src.bezrealitky.manager import (
    BotManager,
    socket_mode_handler,
    JsonStateRepo,
    BEZ_SLACK_BOT_TOKEN,
    BEZ_SLACK_APP_TOKEN,
    CONFIG_PATH,
    STATE_PATH,
    DEFAULT_INTERVAL_SEC,
)

# -----------------------------------------------------
# Boot logging
# -----------------------------------------------------
print("BEZ_BOT=", BEZ_SLACK_BOT_TOKEN)
print("BEZ_APP=", BEZ_SLACK_APP_TOKEN)
print("[boot] Using watchers file:", CONFIG_PATH)
print("[boot] Using seen-state file:", STATE_PATH)

print(
    f"[config] DEFAULT_INTERVAL_SEC = {DEFAULT_INTERVAL_SEC} | "
    f"CONFIG_PATH = {CONFIG_PATH} | STATE_PATH = {STATE_PATH}"
)

# Slack clients
web = WebClient(token=BEZ_SLACK_BOT_TOKEN)
socket = SocketModeClient(app_token=BEZ_SLACK_APP_TOKEN, web_client=web)

# state repo (JSON s TTL logikou)
state_repo = JsonStateRepo(path=STATE_PATH)

# -----------------------------------------------------
# Instantiate manager
# -----------------------------------------------------
bot = BotManager(client=web, state_repo=state_repo)

# -----------------------------------------------------
# Optional: raw event debugging
# -----------------------------------------------------
logging.basicConfig(level=logging.INFO)

def raw_logger(client, req):
    logging.info(
        "SOCKET EVENT type=%s payload_keys=%s",
        getattr(req, "type", "?"),
        list((req.payload or {}).keys()),
    )

socket.socket_mode_request_listeners.append(raw_logger)
socket.socket_mode_request_listeners.append(socket_mode_handler(bot))

# -----------------------------------------------------
# Connect
# -----------------------------------------------------
socket.connect()
print("✅ Bezrealitky Manager running. Type 'ping' in any channel to test events.")

# -----------------------------------------------------
# Keep alive
# -----------------------------------------------------
while True:
    time.sleep(3600)
