#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# *********************************************************************
# Software : PyCharm
#
# expection.py
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
#       - 2022/5/27 15:10  add by yanwh
#
# *********************************************************************
"""
module doc string
"""
from .status import StatusCode


class APIException(Exception):
    status_code: StatusCode = StatusCode.ERROR

    def __init__(self, error_info: str = ""):
        super().__init__(self)
        self.error_info = error_info

    def __str__(self) -> str:
        return self.error_info


class TooManyRequestsError(APIException):
    status_code: StatusCode = StatusCode.TOO_MANY_REQUESTS_ERROR


class ExistError(APIException):
    status_code: StatusCode = StatusCode.EXIST_ERROR


class ValidateError(APIException):
    status_code: StatusCode = StatusCode.VALIDATE_ERROR


class NotExistError(APIException):
    status_code: StatusCode = StatusCode.NOT_EXIST_ERROR


class UserIsNotActiveError(APIException):
    status_code: StatusCode = StatusCode.USER_IS_NOT_ACTIVE_ERROR


class UserExistError(APIException):
    status_code: StatusCode = StatusCode.USER_EXIST_ERROR


class UserNotExistError(APIException):
    status_code: StatusCode = StatusCode.USER_NOT_EXIST_ERROR


class RoleNotExistError(APIException):
    status_code: StatusCode = StatusCode.ROLE_NOT_EXIST_ERROR


class RoleExistError(APIException):
    status_code: StatusCode = StatusCode.ROLE_EXIST_ERROR


class MenuExistError(APIException):
    status_code: StatusCode = StatusCode.MENU_EXIST_ERROR


class MenuNotExistError(APIException):
    status_code: StatusCode = StatusCode.MENU_NOT_EXIST_ERROR


class PermissionDenied(APIException):
    status_code: StatusCode = StatusCode.PermissionDenied


class RedisException(APIException):
    status_code = StatusCode.REDIS_OPERATE_ERROR


class TokenTimeoutException(APIException):
    status_code = StatusCode.TOKEN_TIMEOUT_ERROR


class UnauthorisedException(APIException):
    status_code = StatusCode.UNAUTHORIZED_ERROR


class AuthenticationFailedException(APIException):
    status_code = StatusCode.AUTHENTICATION_FAILED_ERROR


class SSHOperatorException(APIException):
    status_code = StatusCode.SSH_ERROR


class CmdExecuteException(APIException):
    status_code = StatusCode.CMD_EXECUTE_ERROR


class GitOperateException(APIException):
    status_code = StatusCode.GIT_OPERATE_ERROR


class BuildOperateException(APIException):
    status_code = StatusCode.BUILD_OPERATE_ERROR


class DockerOperateException(APIException):
    status_code = StatusCode.DOCKER_OPERATE_ERROR


class HelmOperateException(APIException):
    status_code = StatusCode.HELM_OPERATE_ERROR


class SqlExecuteException(APIException):
    status_code = StatusCode.SQL_EXECUTE_ERROR


class ConfigureException(APIException):
    status_code = StatusCode.CONFIGURE_ERROR


class WebhookException(APIException):
    status_code = StatusCode.WEBHOOK_ERROR
