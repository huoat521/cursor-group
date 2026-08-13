from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.auth import auth_router
from app.api.cursor.proxy.view import cursor_proxy_v1_router
from app.api.cursor.view import cursor_router
from app.bootstrap import init_db
from app.config import settings
from app.core.error_handler import (
    error_handlers,
    http_exception_handler,
    validate_exception_handler,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        lifespan=lifespan,
        exception_handlers=error_handlers,
    )
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validate_exception_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list
        or ["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_origin_regex=r"https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router, prefix="/api")
    app.include_router(cursor_router, prefix="/api/cursor", tags=["cursor"])
    app.include_router(
        cursor_proxy_v1_router,
        prefix="/api/cursor/proxy/v1",
        tags=["cursor-lease"],
    )

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "project": settings.PROJECT_NAME}

    ext_candidates = [
        Path(__file__).resolve().parents[2] / "extension",
        Path("/extension"),
    ]

    def _vsix_version_key(path: Path) -> tuple[tuple[int, ...], float]:
        stem = path.stem
        ver = stem.rsplit("-", 1)[-1] if "-" in stem else "0"
        try:
            nums = tuple(int(x) for x in ver.split("."))
        except ValueError:
            nums = (0,)
        return (nums, path.stat().st_mtime)

    def _latest_vsix() -> Path | None:
        found: list[Path] = []
        for d in ext_candidates:
            if d.is_dir():
                found.extend(d.glob("cursor-group-lease-*.vsix"))
                found.extend(d.glob("cursor-group-lease.vsix"))
        if not found:
            return None
        unique = {p.resolve(): p for p in found}
        return max(unique.values(), key=_vsix_version_key)

    def _vsix_version_label(path: Path) -> str:
        stem = path.stem
        if stem.startswith("cursor-group-lease-"):
            return stem.removeprefix("cursor-group-lease-")
        return stem

    @app.get("/api/extension")
    async def extension_info():
        latest = _latest_vsix()
        if latest is None:
            return {"available": False, "version": None, "filename": None}
        return {
            "available": True,
            "version": _vsix_version_label(latest),
            "filename": latest.name,
            "url": "/downloads/cursor-group-lease.vsix",
        }

    @app.get("/downloads/cursor-group-lease.vsix")
    async def download_extension():
        latest = _latest_vsix()
        if latest is None:
            raise HTTPException(status_code=404, detail="extension package not built yet")
        version = _vsix_version_label(latest)
        return FileResponse(
            latest,
            filename=latest.name,
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "X-Extension-Version": version,
            },
        )

    return app


app = create_app()
