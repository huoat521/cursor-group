from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

async_engine = create_async_engine(
    settings.ASYNC_MYSQL_URI,
    pool_recycle=1500,
    echo=settings.SQL_ECHO,
    max_overflow=0,
    pool_size=20,
)

async_session = sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
