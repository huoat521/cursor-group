from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from .log import logger
from .response import fail
from .status import StatusCode


def _error_map(errors: dict) -> str:
    error_type = errors.get("type") or ""
    field = errors.get("loc")[-1]
    msg = errors.get("msg")
    if "missing" in error_type:
        _msg = f"缺少参数: {field}"
    elif "params" in error_type:
        _msg = f"{field} {'不规范' if msg is None else msg}"
    elif "not_allowed" in error_type:
        _msg = f"{field}类型不正确."
    elif "type_error" in error_type:
        _msg = f"{field}类型不合法."
    elif "value_error" in error_type:
        _msg = f"{field} 值不合法"
    else:
        _msg = f"{field} {msg}"
    return _msg


async def all_exception_handler(request: Request, exception: Exception) -> Response:
    if isinstance(exception, HTTPException):
        return await http_exception_handler(request, exception)

    status_code = getattr(exception, "status_code", None)
    exception_name = type(exception).__name__

    if status_code is None:
        match exception_name:
            case "ValidationError" | "TypeError" | "AssertionError":
                status_code = StatusCode.PARAMETER_VALIDATE_ERROR
            case "IntegrityError":
                status_code = StatusCode.INTEGRITY_ERROR
            case "AttributeError":
                status_code = StatusCode.ATTRIBUTE_ERROR
            case _:
                status_code = StatusCode.ERROR

    if status_code == StatusCode.ERROR:
        logger.error(
            "uncaught exception type=%s message=%s",
            exception_name,
            str(exception),
        )
    else:
        logger.error(
            "%s %s exception type=%s message=%s",
            request.method,
            request.url,
            exception_name,
            str(exception),
        )

    if hasattr(exception, "errors") and callable(exception.errors):
        errors = exception.errors()[0]
        msg = f'{errors.get("loc")[-1]} {errors.get("msg")}'
    else:
        if isinstance(exception, DBAPIError):
            msg = "数据处理异常."
        else:
            msg = str(exception) or getattr(exception, "error_info", "") or "错误"
    return fail(status=status_code, msg=msg)


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    if exc.status_code == 401:
        return fail(status=StatusCode.UNAUTHORIZED_ERROR, msg=str(exc.detail))
    if exc.status_code == 403:
        return fail(status=StatusCode.PermissionDenied, msg=str(exc.detail))
    return fail(status=StatusCode.ERROR, msg=str(exc.detail))


async def validate_exception_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    return fail(
        status=StatusCode.PARAMETER_VALIDATE_ERROR,
        msg=_error_map(exc.errors()[0]) if len(exc.errors()) > 0 else "参数解析失败",
    )


error_handlers = {
    Exception: all_exception_handler,
    HTTPException: http_exception_handler,
    ValidationError: validate_exception_handler,
    RequestValidationError: validate_exception_handler,
}
