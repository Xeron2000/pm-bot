from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger()


async def send_discord(webhook_url: str, content: str) -> bool:
    if not webhook_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={"content": content, "username": "PM-Bot"})
            resp.raise_for_status()
            return True
    except httpx.HTTPError as e:
        log.error("discord_notify_failed", error=str(e))
        return False


async def send_telegram(bot_token: str, chat_id: str, text: str) -> bool:
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
            resp.raise_for_status()
            return True
    except httpx.HTTPError as e:
        log.error("telegram_notify_failed", error=str(e))
        return False


def format_order_message(
    action: str,
    strategy: str,
    direction: str,
    city: str,
    temp_label: str,
    price: float,
    edge: float,
    order_id: str = "",
) -> str:
    emoji = {"created": "🟢", "filled": "✅", "cancelled": "🔴"}.get(action, "⚪")
    return (
        f"{emoji} <b>{action.upper()}</b> | {strategy} | {city}\n"
        f"  {direction} {temp_label} @ {price:.2f}\n"
        f"  Edge: {edge:.1%}"
        f"{f' | Order: {order_id[:12]}' if order_id else ''}"
    )


async def notify(
    config: dict,
    action: str,
    strategy: str,
    direction: str,
    city: str,
    temp_label: str,
    price: float,
    edge: float,
    order_id: str = "",
) -> None:
    msg = format_order_message(action, strategy, direction, city, temp_label, price, edge, order_id)

    notifications = config.get("notifications", {})
    discord = notifications.get("discord", {})
    telegram = notifications.get("telegram", {})

    await send_discord(discord.get("webhook_url", ""), msg)
    await send_telegram(telegram.get("bot_token", ""), str(telegram.get("chat_id", "")), msg)
