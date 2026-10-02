"""Messaging bot connectors (Prompt-1 sections 4-5).

Lightweight, dependency-free (apart from httpx) connectors for Telegram and
WhatsApp. Both parse inbound payloads and send replies over plain HTTPS;
there is deliberately no aiogram / python-telegram-bot / twilio SDK here.
"""

from app.bots import telegram, whatsapp

__all__ = ["telegram", "whatsapp"]
