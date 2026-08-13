#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# *********************************************************************
# Software : PyCharm
#
# status.py
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
#       - 2023/4/12 9:38  add by yanwh
#
# *********************************************************************
"""
module doc string
"""
from enum import Enum

from fastapi import status


class StatusCode(Enum):
    """状态码枚举类"""

    # base
    OK = (0, "成功", status.HTTP_200_OK)
    VALIDATE_ERROR = (
        422,
        "校验失败",
        status.HTTP_400_BAD_REQUEST,
    )
    ERROR = (-1, "发生错误", status.HTTP_400_BAD_REQUEST)
    DEFAULT_ERROR = (-2, "", status.HTTP_400_BAD_REQUEST)
    TOO_MANY_REQUESTS_ERROR = (
        9997,
        "请求次数过快",
        status.HTTP_429_TOO_MANY_REQUESTS,
    )
    INVALID_CSRF_ERROR = (9998, "CSRF验证失败", status.HTTP_400_BAD_REQUEST)
    PermissionDenied = (9999, "无权限访问", status.HTTP_403_FORBIDDEN)
    # ORM相关
    INTEGRITY_ERROR = (10001, "数据库异常", status.HTTP_422_UNPROCESSABLE_ENTITY)
    NOT_EXIST_ERROR = (10002, "数据不存在", status.HTTP_404_NOT_FOUND)
    OPERATIONAL_ERROR = (10003, "数据库操作失败", status.HTTP_400_BAD_REQUEST)
    EXIST_ERROR = (10002, "数据已存在", status.HTTP_404_NOT_FOUND)
    # 程序相关
    ATTRIBUTE_ERROR = (20001, "属性错误", status.HTTP_422_UNPROCESSABLE_ENTITY)
    PARAMETER_VALIDATE_ERROR = (
        20002,
        "参数校验失败",
        status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    INVALID_USAGE_ERROR = (20003, "未验证的参数", status.HTTP_400_BAD_REQUEST)
    NOT_FOUND_ERROR = (20004, "URL路径不存在", status.HTTP_404_NOT_FOUND)
    REDIS_OPERATE_ERROR = (20005, "redis操作异常", status.HTTP_400_BAD_REQUEST)
    AUTHENTICATION_FAILED_ERROR = (
        20006,
        "认证失败",
        status.HTTP_403_FORBIDDEN,
    )
    TOKEN_EXPIRED_ERROR = (20007, "token过期", status.HTTP_403_FORBIDDEN)
    UNAUTHORIZED_ERROR = (
        20008,
        "未登录或未验证的用户名密码",
        status.HTTP_401_UNAUTHORIZED,
    )
    TOKEN_TIMEOUT_ERROR = (20009, "登录超时", status.HTTP_403_FORBIDDEN)
    SSH_ERROR = (20010, "SSH连接异常", status.HTTP_400_BAD_REQUEST)
    CMD_EXECUTE_ERROR = (20011, "命令执行异常", status.HTTP_400_BAD_REQUEST)
    GIT_OPERATE_ERROR = (20012, "git操作异常", status.HTTP_400_BAD_REQUEST)
    BUILD_OPERATE_ERROR = (20012, "代码编译异常", status.HTTP_400_BAD_REQUEST)
    DOCKER_OPERATE_ERROR = (
        20013,
        "docker操作异常",
        status.HTTP_400_BAD_REQUEST,
    )
    HELM_OPERATE_ERROR = (20014, "helm操作异常", status.HTTP_400_BAD_REQUEST)
    SQL_EXECUTE_ERROR = (20015, "SQL执行异常", status.HTTP_400_BAD_REQUEST)
    CONFIGURE_ERROR = (20016, "配置中心配置异常", status.HTTP_400_BAD_REQUEST)
    WEBHOOK_ERROR = (20017, "webhook推送异常", status.HTTP_400_BAD_REQUEST)

    FILE_NOT_FOUND_ERROR = (20018, "文件不存在", status.HTTP_404_NOT_FOUND)
    FILE_CREATE_ERROR = (20019, "文件生成失败", status.HTTP_400_BAD_REQUEST)
    # 服务器
    SERVER_CONNECT_TIMEOUT_ERROR = (
        20020,
        "服务器连接超时",
        status.HTTP_400_BAD_REQUEST,
    )
    SERVER_OFFLINE_ERROR = (
        20021,
        "服务器离线",
        status.HTTP_400_BAD_REQUEST,
    )
    # 用户
    USER_IS_NOT_ACTIVE_ERROR = (21000, "用户未激活", status.HTTP_400_BAD_REQUEST)
    USER_EXIST_ERROR = (21001, "用户已存在", status.HTTP_400_BAD_REQUEST)
    USER_NOT_EXIST_ERROR = (21002, "用户不存在", status.HTTP_404_NOT_FOUND)
    ROLE_EXIST_ERROR = (21003, "角色已存在", status.HTTP_400_BAD_REQUEST)
    ROLE_NOT_EXIST_ERROR = (21004, "角色不存在", status.HTTP_404_NOT_FOUND)
    MENU_EXIST_ERROR = (21005, "菜单已存在", status.HTTP_400_BAD_REQUEST)
    MENU_NOT_EXIST_ERROR = (21006, "菜单不存在", status.HTTP_404_NOT_FOUND)
    QYWX_NOTIFY_ERROR = (
        21007,
        "企业微信通知异常",
        status.HTTP_400_BAD_REQUEST,
    )
    # 系统运行相关
    SERVICE_UNAVAILABLE_ERROR = (
        30001,
        "服务不可用",
        status.HTTP_400_BAD_REQUEST,
    )
    CANCELLED_ERROR = (30002, "异步任务被动取消", status.HTTP_400_BAD_REQUEST)
    TIMEOUT_ERROR = (30003, "系统超时", status.HTTP_400_BAD_REQUEST)

    @property
    def code(self) -> int:
        """获取状态码"""
        return self.value[0]

    @property
    def message(self) -> str:
        """获取状态码信息"""
        return self.value[1]

    @property
    def status(self) -> int:
        """获取http响应码信息"""
        return self.value[2]
