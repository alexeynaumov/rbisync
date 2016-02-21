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

from PyQt4.QtCore import QObject
from PyQt4.QtCore import QThread
from PyQt4.QtCore import SIGNAL
from rbisync.rserial.io import IO


class Serial(QObject):

    def __init__(self, parent=None):
        QObject.__init__(self, parent)

        self.__io = IO()

        class Reader(QObject):
            '''
            Synchronous data reader.
            '''

            def __init__(self, io):
                QObject.__init__(self)
                self.io = io

            def read(self):
                '''
                Infinitely wait for incoming data in an infinite loop. All the incoming data is passed outside with the
                signal.

                :return data: str, incoming data
                '''

                while True:
                    data = self.io.read()
                    self.emit(SIGNAL("read"), data)

        class Writer(QObject):
            '''
            Synchronous data writer.
            '''

            def __init__(self, io):
                QObject.__init__(self)
                self.io = io
                self.__dataToWrite = ""

            def write(self, data):
                '''
                Write all the characters of <data> one by one.

                :param data: str, outgoing data
                :return: None
                '''

                self.__dataToWrite += data

                while self.__dataToWrite:
                    char = self.__dataToWrite[0]

                    self.__dataToWrite = self.__dataToWrite[1:]

                    self.io.write(char)

        self.__on_read = None # on-read callback

        self.__readingThread = QThread(self)
        self.__writingThread = QThread(self)

        self.__reader = Reader(self.__io)
        self.__writer = Writer(self.__io)

        # READER AND WRITER LIVE IN THEIR OWN THREADS !!
        self.__reader.moveToThread(self.__readingThread)
        self.__writer.moveToThread(self.__writingThread)

        result = True
        # TOUCH READER AND WRITER ONLY WITH SIGNALS !!
        result &= QObject.connect(self.__reader, SIGNAL("read"), self.__onReadyRead)
        result &= QObject.connect(self, SIGNAL("write"), self.__writer.write)
        # START THE READING THREAD WITH THE SIGNAL TOO !!
        result &= QObject.connect(self.__readingThread, SIGNAL("started()"), self.__reader.read)

        if not result:
            raise Exception("Error connecting signals to slots.")

    def __del__(self):
        self.__io.close()

        self.__readingThread.wait()
        self.__readingThread.quit()

        self.__writingThread.wait()
        self.__writingThread.quit()

    def open(self):
        self.__io.open()
        self.__readingThread.start()
        self.__writingThread.start()

    def close(self):
        self.__io.close()

    def __onReadyRead(self, data):
        if self.__on_read:
            self.__on_read(data)

    def write(self, data):
        self.emit(SIGNAL("write"), data)

    @property
    def port(self):
        return self.__io.port

    @port.setter
    def port(self, port):
        self.__io.port = port

    @property
    def baudRate(self):
        return self.__io.baudRate

    @baudRate.setter
    def baudRate(self, baudRate):
        self.__io.baudRate = baudRate

    @property
    def byteSize(self):
        return self.__io.byteSize

    @byteSize.setter
    def byteSize(self, byteSize):
        self.__io.byteSize = byteSize

    @property
    def parity(self):
        return self.__io.parity

    @parity.setter
    def parity(self, parity):
        self.__io.parity = parity

    @property
    def stopBits(self):
        return self.__io.stopBits

    @stopBits.setter
    def stopBits(self, stopBits):
        self.__io.stopBits = stopBits

    @property
    def onRead(self):
        return self.__on_read

    @onRead.setter
    def onRead(self, callback):
        self.__on_read = callback

    @property
    def isOpen(self):
        return self.__io.isOpen