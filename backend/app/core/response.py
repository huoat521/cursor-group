#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# *********************************************************************
# Software : PyCharm
#
# response.py
#
# Author    :yanwh(yanwh@digitalchina.com)
#
# Version 1.0.0
#
# Copyright (c) 2004-9999 Digital China Networks Co. Ltd
#
#
# *********************************************************************
# Change log:
#       - 2023/4/12 10:26  add by yanwh
#
# *********************************************************************
"""
module doc string
"""
import datetime
from typing import Any

from fastapi import status as st
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.schema import ResponseSchema
from .status import StatusCode


def ok(
    status_enum: StatusCode = StatusCode.OK,
    *,
    data: list | dict | str | BaseModel | None = None,
    status_code: int | None = None,
    msg: str | None = None,
) -> JSONResponse:
    _status = st.HTTP_200_OK
    if status_code:
        _status = status_code
    else:
        _status = status_enum.status
    return JSONResponse(
        status_code=_status,
        content=jsonable_encoder(
            ResponseSchema(
                status=status_enum.code,
                msg=msg or status_enum.message,
                data=data,
            ),
            custom_encoder={
                datetime.datetime: lambda date_obj: date_obj.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            },
        ),
    )


def fail(
    *,
    status: StatusCode = StatusCode.DEFAULT_ERROR,
    msg: str = "",
    errors: Any = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.status,
        content=jsonable_encoder(
            ResponseSchema(
                status=status.code,
                msg=msg or status.message,
                data=None,
                errors=errors,
            )
        ),
    )
