from __future__ import annotations

from app.api.notify.models import NotificationCreateSchema
from app.api.notify.webhook import send_webhook_alert
from app.core.log import logger


class NotificationService:
    @classmethod
    async def create(cls, schema: NotificationCreateSchema):
        """Persist-less notify: log + optional webhook."""
        logger.info(
            "notify receiver=%s title=%s content=%s link=%s",
            schema.receiver,
            schema.msg_title,
            schema.msg_content,
            schema.msg_link,
        )
        await send_webhook_alert(
            event="notification",
            payload={
                "title": schema.msg_title,
                "content": schema.msg_content,
                "link": schema.msg_link,
                "receiver": schema.receiver,
                "msg_type": schema.msg_type,
            },
        )
        return True
