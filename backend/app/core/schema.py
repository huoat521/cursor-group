from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class TokenPayload(BaseModel):
    sub: Optional[int] = None


class ResponseSchema(BaseModel, Generic[T]):
    status: int = 0
    msg: str = ""
    data: Optional[T] = None
    errors: Optional[T] = None


class PageSchema(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=200)
