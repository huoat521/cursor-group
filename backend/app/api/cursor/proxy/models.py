from datetime import datetime

from sqlalchemy import Column, Integer, SmallInteger, String, TIMESTAMP

from app.core.database import Base
from app.core.models import BaseMixin


class CursorProxyRequestLog(Base, BaseMixin):
    __tablename__ = "cursor_proxy_request_log"

    user_id = Column(Integer, nullable=False, index=True)
    account_id = Column(Integer, nullable=False, index=True)
    model = Column(String(128), nullable=False, default="", server_default="")
    prompt_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    completion_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    total_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    latency_ms = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(SmallInteger, nullable=False, default=1, server_default="1")
    error_code = Column(String(64), nullable=True)
    session_id = Column(String(64), nullable=True)
