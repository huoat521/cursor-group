from __future__ import annotations

from fastapi.responses import JSONResponse


def lease_error(status: int, err_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "message": message,
                "type": err_type,
                "code": err_type,
            }
        },
    )
