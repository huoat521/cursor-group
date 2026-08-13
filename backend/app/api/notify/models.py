from pydantic import BaseModel


class NotificationCreateSchema(BaseModel):
    msg_type: int = 3
    msg_title: str
    msg_content: str
    msg_link: str = "/me"
    msg_status: int = 1
    sender: int | None = 0
    receiver: int | None = None
