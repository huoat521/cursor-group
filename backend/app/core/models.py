#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# *********************************************************************
# Software : PyCharm
#
# models.py
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
#       - 2023/4/26 15:34  add by yanwh
#
# *********************************************************************
"""
module doc string
"""

from sqlalchemy import Column, Integer, TIMESTAMP, func


class PrimaryKeyMixin:
    id = Column(Integer, primary_key=True)


default_datetime = func.now()


class TimeStampMixin:
    """Timestamping mixin"""

    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=default_datetime,
        comment="创建时间",
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=default_datetime,
        onupdate=default_datetime,
        comment="更新时间",
    )

    deleted_at = Column(
        TIMESTAMP(timezone=True),
        nullable=True,
        default=None,
        comment="删除时间",
    )


class BaseMixin(PrimaryKeyMixin, TimeStampMixin):
    ...


class StatusMixin(BaseMixin):
    status = Column(
        Integer, nullable=False, default=1, comment="状态 1有效 9 删除 5选中"
    )


class RoleRelationMixin:
    rid = Column(Integer, comment="角色id", index=True)
