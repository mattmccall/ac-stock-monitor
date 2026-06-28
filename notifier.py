"""Telegram notifier.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the environment (GitHub
Secrets in CI, a local .env for testing). Sends one message per newly in-stock
product with name, price, retailer, rating and a direct link.
"""

from __future__ import annotations

import html
import os

import requests

from retailers.base import Product

API = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 20


class TelegramNotConfigured(RuntimeError):
    pass


def _credentials() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise TelegramNotConfigured(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
            "(env vars or GitHub Secrets)."
        )
    return token, chat_id


def format_message(product: Product) -> str:
    name = html.escape(product.name)
    retailer = html.escape(product.retailer)
    lines = [
        "🟢 <b>En stock !</b>",
        f"<b>{name}</b>",
        f"💶 {product.price_str()}  ·  🏬 {retailer}",
    ]
    if product.rating:
        lines.append(f"⭐ {html.escape(product.rating)}")
    if product.specs:
        lines.append(f"📐 {html.escape(product.specs)}")
    lines.append(f'🔗 <a href="{html.escape(product.url, quote=True)}">Voir le produit</a>')
    return "\n".join(lines)


def send(product: Product) -> None:
    token, chat_id = _credentials()
    resp = requests.post(
        API.format(token=token),
        json={
            "chat_id": chat_id,
            "text": format_message(product),
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()


def is_configured() -> bool:
    try:
        _credentials()
        return True
    except TelegramNotConfigured:
        return False
