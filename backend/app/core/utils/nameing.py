#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# *********************************************************************
# Software : PyCharm
#
# nameing.py
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
#       - 2023/5/15 15:27  add by yanwh
#
# *********************************************************************
"""
module doc string
"""
import re


def convert_class_name(name: str) -> str:
    """
    将BaseTest转换成base_test
    Args:
        name:

    Returns:

    """
    return "_".join([x.lower() for x in re.split("(?=[A-Z])", name) if x])
