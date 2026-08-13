from __future__ import annotations

from typing import Any

import aiohttp

from app.config import settings
from app.core.log import logger


async def send_webhook_alert(event: str, payload: dict[str, Any]) -> bool:
    url = (settings.WEBHOOK_ALERT_URL or "").strip()
    if not url:
        return False
    body = {"event": event, "source": "cursor_group", **payload}
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=body) as resp:
                ok = 200 <= resp.status < 300
                if not ok:
                    text = await resp.text()
                    logger.warning(
                        "webhook failed status=%s body=%s", resp.status, text[:200]
                    )
                return ok
    except Exception as exc:  # noqa: BLE001
        logger.warning("webhook error: %s", exc)
        return False
