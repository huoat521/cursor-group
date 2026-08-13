#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# *********************************************************************
# Software : PyCharm
#
# service.py
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
#       - 2023/5/8 17:40  add by yanwh
#
# *********************************************************************
"""
module doc string
"""
from typing import List, Tuple, Type

from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Query
from sqlalchemy.sql import Select

from app.core.database import Base
from app.core.expection import ExistError, NotExistError
from app.core.log import logger
from app.core.response import fail, ok
from app.core.session import async_session
from app.core.status import StatusCode


def _schema_to_dict(schema, **kwargs):
    if hasattr(schema, "model_dump"):
        return schema.model_dump(**kwargs)
    if hasattr(schema, "dict"):
        return schema.dict(**kwargs)
    return dict(schema)

Model = Type[Base]

# 批量插入大小
BATCH_SIZE = 800


class Service:
    filter_del: dict = {"status__not": 9}
    # 排序字段, 第一个字符只能为+/-, +表示正序，-为倒序, 剩下字符为要排序的字段
    ordering = "-updated_at"

    def __init__(self, model: Model, not_exist: str = "", exist: str = ""):
        self.model: Model = model
        self.not_exist: str = not_exist
        self.exist: str = exist

    async def count(self, **kwargs) -> int:
        async with async_session() as db:
            # 获取 stmt
            _stmt = select(self.model)
            if kwargs:
                for k, v in kwargs.items():
                    _stmt = _stmt.filter(getattr(self.model, k) == v)
            stmt = select(func.count("*")).select_from(_stmt)
            # 执行查询
            return await db.scalar(stmt)

    async def options(self, option: str) -> List:
        # 获取self.model对象中的option属性
        option = getattr(self.model, option)
        # 如果option属性为None，则抛出异常
        if option is None:
            raise NotExistError(error_info=f"{option}属性错误.")
        # 调用query方法查询数据，并返回一个列表
        return await self.query(
            # 查询option属性去重后的结果，并且只查询option不为None的数据
            select(option.distinct()).where(option.isnot(None)),
            # 禁用排序功能
            disable_order_by=True,
        )

    @property
    def _pk(self) -> str:
        return self.model.__table__.primary_key.columns.keys()[0]

    async def max_primary_id(self) -> int:
        async with async_session() as db:
            # 获取 stmt
            return await db.scalar(select(func.max(self.model.id)))

    async def _get_one(self, db: AsyncSession, item_id: int):
        """通过主键获取数据"""
        if result := await db.get(self.model, ident=item_id):
            return result
        raise NotExistError(error_info=self.not_exist)

    def _get_order_by(
        self,
        kwargs: dict,
        order_by: str | None = None,
    ) -> tuple[str, dict]:
        """
        获取order by string
        Args:
            kwargs:
            order_by:

        Returns:

        """
        order_ = kwargs.pop("orderBy") if "orderBy" in kwargs else None
        direction = kwargs.pop("orderDir") if "orderDir" in kwargs else None
        if order_by is not None:  # 手动传入的order by优先级最高
            by = getattr(self.model, order_by)
        else:
            if order_:  # 浏览器通过query字段传入orderBy优先级次之
                by = getattr(self.model, order_)
                if direction:
                    by = getattr(by, direction)()
            else:
                try:
                    direction, order_ = self.ordering[0], self.ordering[1:]
                    by = getattr(self.model, order_)
                    if direction == "-":
                        by = by.desc()
                    elif direction == "+":
                        by = by.asc()
                    else:
                        raise ValueError("ordering参数错误,应该为[+name]/[-id]")
                except AttributeError:
                    by = getattr(self.model, self._pk)
        return by, kwargs

    def _get_filters(
        self, like: bool, or_query: bool, between: bool, **kwargs
    ) -> list | None:
        """
        获取查询过滤器
        Args:
            like: 是否进行like查询
            or_query: 是否使用or查询
            **kwargs: 查询参数

        Returns:
            list | None: 返回过滤器列表或None
        """
        filters = []
        for k, v in kwargs.items():
            if not hasattr(self.model, k):
                continue
            if isinstance(v, list):
                if between and len(v) == 2:  # 支持between查询
                    filters.append(
                        getattr(self.model, k).between(v[0], v[1])
                    )
                else:
                    # 支持in查询
                    filters.append(getattr(self.model, k).in_(v))
            else:
                if like:  # 支持like模糊查询,并且忽略大小写
                    filters.append(
                        func.lower(getattr(self.model, k)).like(f"%{v}%")
                    )
                else:
                    filters.append(getattr(self.model, k) == v)

        return [or_(*filters)] if or_query else filters

    async def select_one(
        self, pk: int | None = None, **kwargs
    ) -> Model | None:
        if pk is not None:
            async with async_session() as db:
                return await self._get_one(db=db, item_id=pk)
        return await self.query(one=True, **kwargs)

    async def query(
        self,
        stmt: Query | Select | None = None,
        skip: int = 0,
        limit: int | None = None,
        order_by: str | None = None,
        disable_order_by: bool = False,
        like: bool = False,
        one: bool = False,
        or_query: bool = False,
        between: bool = False,
        return_total_count: bool = False,
        return_all: bool = False,
        **kwargs,
    ) -> Model | List[Model] | Tuple[int, List[Model]] | None:
        async with async_session() as db:
            # 获取 stmt
            if stmt is None:
                stmt = select(self.model)
            # 获取order by信息
            by, _kwargs = self._get_order_by(
                order_by=order_by, kwargs=kwargs
            )
            # 获取过滤条件
            _filters = self._get_filters(
                like=like, or_query=or_query, between=between, **_kwargs
            )
            if _filters:
                stmt = stmt.filter(*_filters)

            if one:
                return await db.scalar(stmt)
            if disable_order_by is False:
                stmt = stmt.order_by(by)
            result = await db.execute(stmt.limit(limit).offset(skip))
            result = result.all() if return_all else result.scalars().all()

            if return_total_count:
                total = await db.scalar(
                    select(func.count()).select_from(stmt)
                )
                return total, result
            return result

    async def get_many(
        self, skip: int | None = None, limit: int | None = None, **kwargs
    ):
        return await self.query(
            skip=skip,
            limit=limit,
            like=True,
            return_total_count=True,
            **kwargs,
        )

    async def delete(self, pk: int | None = None) -> Response:
        """
         删除数据
        :param pk:主键
        :return:
        """
        async with async_session() as session:
            async with session.begin():
                if pk is None:
                    for _ in await session.scalars(select(self.model)):
                        await session.delete(_)
                else:
                    one: Model = await self._get_one(session, pk)
                    await session.delete(one)
                return ok(msg="删除成功")

    async def updates(
        self, schemas: list[BaseModel] | list[dict]
    ) -> Response:
        """
        更新多条数据
        :param schemas: pydantic model
        :return:
        """
        async with async_session() as session:
            async with session.begin():
                await session.execute(
                    update(self.model),
                    [
                        _schema_to_dict(schema)
                        if isinstance(schema, BaseModel)
                        else schema
                        for schema in schemas
                    ],
                )
                return ok(msg="更新成功")

    async def update(self, schema: BaseModel | dict, pk: int):
        """
        更新数据,不通用，可重写
        :param pk: 主键
        :param schema: pydantic model
        :return:
        """
        try:
            async with async_session() as session:
                async with session.begin():
                    one: Model = await self._get_one(session, pk)
                    if isinstance(schema, BaseModel):
                        schema = _schema_to_dict(schema, 
                            exclude={self._pk}, exclude_none=True
                        )
                    for key, value in schema.items():
                        if hasattr(one, key):
                            setattr(one, key, value)
            return ok(msg="更新成功")
        except IntegrityError:
            return fail(status=StatusCode.INTEGRITY_ERROR, msg="更新失败")

    async def batch_create(
        self,
        schema: list[dict],
    ) -> Response:
        """
        批量创建数据
        :param schema: pydantic model
        :return:
        """
        logger.info(f"批量创建数据: {len(schema)}")
        for i in range(0, len(schema), BATCH_SIZE):
            async with async_session(
                autoflush=False, expire_on_commit=False
            ) as session:
                try:
                    async with session.begin():
                        await session.run_sync(
                            lambda ses: ses.bulk_insert_mappings(
                                self.model,
                                schema[i : i + BATCH_SIZE],
                            )
                        )
                        await session.commit()
                except IntegrityError:
                    raise ExistError(self.exist)
        return ok(msg="批量创建成功")

    async def create(
        self,
        schema: BaseModel | dict | list[BaseModel] | list[dict],
    ) -> Response:
        """

        Args:
            schema:
        Returns:

        """
        if not isinstance(schema, (tuple, list)):
            schema = [schema]

        schemas = []
        if len(schema) > BATCH_SIZE:  # 大于BATCH_SIZE自动开启批量创建
            for item in schema:
                if isinstance(item, BaseModel):
                    schemas.append(_schema_to_dict(item))
                elif isinstance(item, dict):
                    schemas.append(item)
                else:
                    raise ValueError("批量插入的数据结构不正确.")
            return await self.batch_create(schema)

        for item in schema:
            if isinstance(item, BaseModel):
                schemas.append(self.model(**_schema_to_dict(item)))
            else:
                schemas.append(self.model(**item))
        async with async_session() as session:
            try:
                async with session.begin():
                    if len(schemas) == 1:
                        session.add(schemas[0])
                    else:
                        session.add_all(schemas)
                return ok(msg="创建成功")
            except IntegrityError:
                raise ExistError(self.exist)

    async def is_exist(self, column: str, value_to_check: str) -> bool:
        """

        Args:
            column: 表字段
            value_to_check: 内容
        Returns:

        """
        async with async_session() as session:
            sql = select(self.model).where(
                exists().where(
                    getattr(self.model, column) == value_to_check
                )
            )
            result = await session.execute(sql)
            return bool(result.scalar())


class DiffService(Service):
    """只更新修改数据,而非全量更新"""

    async def updates(self, schemas: list[BaseModel]) -> Response:
        async with async_session() as session:
            try:
                async with session.begin():
                    for schema in schemas:
                        if hasattr(schema, "id"):
                            one = await self._get_one(session, schema.id)
                            schema = _schema_to_dict(schema, 
                                exclude={self._pk}, exclude_none=True
                            )
                            for key, value in schema.items():
                                if hasattr(one, key):
                                    setattr(one, key, value)
                        else:
                            raise ValueError("待更新数据中不存在主键id")
            except IntegrityError:
                return fail(msg="更新失败,请检查要修改的数据是否已重复")
        return ok(msg="更新成功")
