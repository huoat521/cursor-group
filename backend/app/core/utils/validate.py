#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# *********************************************************************
# Software : PyCharm
#
# validate.py
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
#       - 2023/5/19 15:01  add by yanwh
#
# *********************************************************************
"""
module doc string
"""
import socket


def is_valid_ipv4(addr):
    try:
        socket.inet_pton(socket.AF_INET, addr)
        return True
    except (socket.error, TypeError):
        return False


def is_valid_ipv6(addr):
    try:
        socket.inet_pton(socket.AF_INET6, addr)
        return True
    except (socket.error, TypeError):
        return False


def is_ip(value):
    """Determine if the given string is an IP address.
    :param value: value to check
    :type value: str
    :return: True if string is an IP address
    :rtype: bool
    """
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(family, value)
        except OSError:
            pass
        else:
            return True

    return False


def is_ipv6(value):
    try:
        socket.inet_pton(socket.AF_INET6, value)
    except OSError:
        return False
    else:
        return True
