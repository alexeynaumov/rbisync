# -*- coding: utf-8 -*-

# Copyright (C) 2015 Alexey Naumov <rocketbuzzz@gmail.com>
#
# This file is part of rserial.
#
# rserial is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or (at
# your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from PyQt4.QtCore import QString
from collections import deque


def bytesToString(intList, base=10, pad=False):
    '''
    Convert list of integers into string of integers.

    :param intList, list of int: list of integers to be converted into string of integers
    :param base, int (2, 8, 10, 16): base of integers in the output string
    :param pad, bool: whether use padding(zfill) or not
    :return: string, string of integers

    >>> bytesToString([0,1,254,255], 16, True)
    00 01 FE FF

    >>> bytesToString([0,1,254,255], 2, False)
    0 1 11111110 11111111

    '''

    # key: base, value: padding depth
    # base 2  (bin) -> values from 00000000 to 11111111: XXXXXXXX = padding 8 characters
    # base 3  (oct) -> values from 000 to 377: XXX = padding 3 characters
    # base 10 (dec) -> values from 000 to 255: XXX = padding 3 characters
    # base 16 (hex) -> values from 00 to FF: XX = padding 2 characters
    FORMAT = {2: 8, 8: 3, 10: 3, 16: 2}

    if list != type(intList):
        raise TypeError("object %s must be of type 'list' " % intList)

    if base not in FORMAT.keys():
        raise ValueError("base %s not in %s" % (base, FORMAT.keys()))

    intStr = ""
    for value in intList:
        if int != type(value):
            raise TypeError("object %s must be of type 'int' " % intList)

        value = str(QString.number(value, base).toUpper())
        if pad:
            value = value.zfill(FORMAT[base])

        intStr += value + " "

    return intStr.strip()


def stringToBytes(intStr, base=10, delimiter=" "):
    '''
    Convert string of integers into list of integers.

    :param intStr, str: string of integers to be converted into list of integers
    :param base, int (2, 8, 10, 16): base of integers in the string
    :param delimiter, str: delimiter of integers in the string
    :return: list of int: list of integers

    >>> stringToBytes("00 01 FE FF", 16, " ")
    [0, 1, 254, 255]

    >>> stringToBytes("0 1 11111110 11111111", 2, " ")
    [0, 1, 254, 255]

    '''

    if str != type(intStr):
        raise TypeError("object %s must be of type 'str' " % intStr)

    intList = []

    items = intStr.strip().split(delimiter)
    for item in items:
        if not item:
            continue  # skip empty elements like ''

        value = int(item, base)
        if value < 0 or value > 255:
            raise ValueError("input out of bound: %s" % value)

        intList.append(value)

    return intList


class History(object):
    def __init__(self):
        self.__previous = deque()
        self.__next = deque()

    def __str__(self):
        values = []
        for value in self.__previous:
            values.append(value)

        for value in self.__next:
            values.append(value)

        return " ".join([str(value) for value in values])

    def add(self, value):
        self.__previous.extend(self.__next)
        self.__previous.append(value)
        self.__next.clear()

    def previous(self):

        if self.__previous:
            value = self.__previous.pop()
            self.__next.appendleft(value)
            return value
        else:
            return None

    def next(self):
        if self.__next:
            value = self.__next.popleft()
            self.__previous.append(value)
            return value
        else:
            return None