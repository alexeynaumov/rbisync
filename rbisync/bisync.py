# -*- coding: utf-8 -*-

# Copyright (C) 2015-2016 Alexey Naumov <rocketbuzzz@gmail.com>
#
# This file is part of rbisync.
#
# rbisync is free software: you can redistribute it and/or modify
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

import sys
import os

sys.path.append(os.path.abspath("../../rserial/"))

import re
import logging
from async import Dispatcher, AbstractHandle, AbstractDeferredAction
from rserial.serial import Serial


DEBUG = False  # if set True, debug messages are sent to stdout
IGNORE_CHECKSUM_ERRORS = True

ENQ = chr(05)
ACK = chr(06)
NAK = chr(21)
STX = chr(02)
ETX = chr(03)
EOT = chr(04)

STATE_IDLE = 0
STATE_ABOUT_TO_TX = 1
STATE_TX_STARTED = 2
STATE_TX_FINISHED = 3
STATE_RX_STARTED = 4
STATE_RX_FINISHED = 5

RETRY_TIMEOUT = {1: 1500, 2: 1500}  # key=retry number, value=delay(milliseconds)
MAX_RETRY = len(RETRY_TIMEOUT)

TX_ENQ_WAIT_FOR_ACK = 250  # (мс) отправили ENQ, ждем ACK не дольше указанного интервала
TX_MESSAGE_WAIT_FOR_ACK = 500  # (мс) отправили MESSAGE, ждем ACK не дольше указанного интервала
TX_ACK_WAIT_FOR_MESSAGE = 100  # (мс) отправили ACK, ждем MESSAGE не дольше указанного интервала
TX_ACK_WAIT_FOR_EOT = 125  # (мс) отправили ACK, ждем EOT не дольше указанного интервала

# errors
CODE_DESCRIPTION = {
   -1: "Unknown error",
    1: "No ACK too long after several attempt(s) BEFORE sending message",
    2: "Remote peer not responding",
    3: "No ACK too long AFTER sending message",
    4: "No message too long",
    5: "No EOT too long",
    6: "Remote peer not acknowledge transmission",
    7: "Checksum error",
    8: "Collision detected"
}

# for debug purposes
CODE_SYMBOL = {ord(EOT): "EOT",
               ord(ENQ): "ENQ",
               ord(ACK): "ACK",
               ord(NAK): "NAK"}

CODE_STATE = {STATE_IDLE: "IDLE",
              STATE_ABOUT_TO_TX: "ABOUT_TO_TX",
              STATE_TX_STARTED: "TX_STARTED",
              STATE_TX_FINISHED: "TX_FINISHED",
              STATE_RX_STARTED: "RX_STARTED",
              STATE_RX_FINISHED: "RX_FINISHED"}

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s: %(lineno)4d %(module)s.%(funcName)-12s >>> %(message)s')
handler.setFormatter(formatter)

logger.addHandler(handler)

if DEBUG:
    logging.disable(logging.NOTSET)
else:
    logging.disable(logging.INFO)


class ENQ_For_ACK_Handle(AbstractHandle):
    def __init__(self, serial):
        AbstractHandle.__init__(self)
        self.serial = serial
        self.retryCount = 0
        self.timeout = TX_ENQ_WAIT_FOR_ACK

    def __del__(self):
        self.detach()

    def onNewData(self, data):
        if data == ACK:
            if DEBUG:
                logger.info("RX ACK")

            self.detach()
            self.serial.state = STATE_TX_STARTED
            self.serial.writeMessage()

        if data == ENQ:
            if DEBUG:
                logger.info("RX ENQ")

            self.detach()
            self.serial.state = STATE_IDLE

            # "Collision detected"
            errorCode = 8
            errorDescription = self.serial.errorString(errorCode)
            error = (errorCode, errorDescription)
            self.serial._Bisync__onError(error)

        if data == NAK:
            if DEBUG:
                logger.info("RX NAK")

            self.detach()
            self.serial.state = STATE_IDLE

    def onTimeout(self):
        self.retryCount += 1
        self.detach()
        self.serial.state = STATE_IDLE

        if self.retryCount <= MAX_RETRY:
            self.timeout = RETRY_TIMEOUT[self.retryCount]

            # "No ACK too long after several attempt(s) before sending message"
            errorCode = 1
            errorDescription = self.serial.errorString(errorCode)
            error = (errorCode, errorDescription)
            self.serial._Bisync__onError(error)

            self.serial.writeENQ()

        else:
            self.retryCount = 0
            self.timeout = TX_ENQ_WAIT_FOR_ACK

            # "Remote peer not responding"
            errorCode = 2
            errorDescription = self.serial.errorString(errorCode)
            error = (errorCode, errorDescription)
            self.serial._Bisync__onError(error)

            self.serial.messages = self.serial.messages[1:]
            if self.serial.messages:
                self.serial.writeENQ()


class MESSAGE_For_ACK_Handle(AbstractHandle):
    def __init__(self, serial):
        AbstractHandle.__init__(self)
        self.serial = serial
        self.retryCount = 0
        self.timeout = TX_MESSAGE_WAIT_FOR_ACK

    def __del__(self):
        self.detach()

    def __call__(self, message):
        self.__message = message

        return self

    def onNewData(self, data):
        if data == ACK:
            self.detach()
            self.serial.state = STATE_TX_FINISHED

            if DEBUG:
                logger.info("RX ACK")

            self.serial.state = STATE_IDLE
            self.serial.writeEOT()

            if self.serial.messages:
                self.serial.writeENQ()

        if data == NAK:
            self.detach()
            self.serial.state = STATE_IDLE

            if DEBUG:
                logger.info("RX NAK")

    def onTimeout(self):
        self.detach()
        self.serial.state = STATE_IDLE

        # "No ACK too long AFTER sending message"
        errorCode = 3
        errorDescription = self.serial.errorString(errorCode)
        error = (errorCode, errorDescription)
        self.serial._Bisync__onError(error)

        # если есть сообщения в очереди, пробеум отправить следующее сообщение
        self.serial.messages = self.serial.messages[1:]
        if self.serial.messages:
            self.serial.writeENQ()


class ACK_For_MESSAGE_Handle(AbstractHandle):
    def __init__(self, serial):
        AbstractHandle.__init__(self)
        self.serial = serial
        self.timeout = TX_ACK_WAIT_FOR_MESSAGE
        self.__rxData = ""

        messagePattern = r"%s(?P<message>.+)%s(?P<checksum>.{1})" % (STX, ETX)  # allow any character
        self.__wait_for = re.compile(messagePattern)

    def __del__(self):
        self.detach()

    def onNewData(self, data):
        self.__rxData += data

        match = re.match(self.__wait_for, self.__rxData)
        if match:
            self.detach()
            self.__rxData = ""

            message = match.group('message')

            checksum_remote = ord(match.group('checksum'))  # the sum in the message, the peer calculated it
            checksum_local = 0  # the sum we calculate based upon data received from the peer
            for char in message + ETX:
                checksum_local ^= ord(char)

            checksum_ok = True if checksum_local == checksum_remote else False

            if DEBUG:
                logger.info("RX {} CHECKSUM={}({})".format(message, checksum_local, "ok" if checksum_ok else "not ok"))

            if IGNORE_CHECKSUM_ERRORS:
                checksum_ok = True

            if checksum_ok:
                self.serial._Bisync__onReadyRead(message)
                self.serial.state = STATE_RX_FINISHED
                self.serial.writeACK()
            else:
                errorCode = 7
                errorDescription = "Checksum error in %s. Expected: %s, received: %s" % (message, checksum_local, checksum_remote)
                error = (errorCode, errorDescription)
                self.serial._Bisync__onError(error)

                self.serial.state = STATE_RX_FINISHED
                self.serial.state = STATE_IDLE
                self.serial.writeNAK()

    def onTimeout(self):
        self.detach()
        self.serial.state = STATE_IDLE
        self.__rxData = ""

        # "No message too long"
        errorCode = 4
        errorDescription = self.serial.errorString(errorCode)
        error = (errorCode, errorDescription)
        self.serial._Bisync__onError(error)

        if self.serial.messages:
            self.serial.writeENQ()

    def onError(self, error):
        self.detach()


class ACK_For_EOT_Handle(AbstractHandle):
    def __init__(self, serial):
        AbstractHandle.__init__(self)
        self.serial = serial
        self.timeout = TX_ACK_WAIT_FOR_EOT

    def __del__(self):
        self.detach()

    def onNewData(self, data):
        if data == EOT:
            self.detach()
            self.serial.state = STATE_IDLE

            if DEBUG:
                logger.info("RX EOT")

    def onTimeout(self):
        self.detach()
        self.serial.state = STATE_IDLE

        # "No EOT too long"
        errorCode = 5
        errorDescription = self.serial.errorString(errorCode)
        error = (errorCode, errorDescription)
        self.serial._Bisync__onError(error)

        if self.serial.messages:
            self.serial.writeENQ()


class Bisync(Serial):
    '''
    Simple binary synchronous communications class.
    NOTICE! RXD and TXD are the only pins used.
    '''

    PARITY_NONE, PARITY_EVEN, PARITY_ODD, PARITY_MARK, PARITY_SPACE = (Serial.PARITY_NONE, Serial.PARITY_EVEN, Serial.PARITY_ODD, Serial.PARITY_MARK, Serial.PARITY_SPACE)
    STOPBITS_ONE, STOPBITS_ONE_POINT_FIVE, STOPBITS_TWO = (Serial.STOPBITS_ONE, Serial.STOPBITS_ONE_POINT_FIVE, Serial.STOPBITS_TWO)
    DATABITS_FIVE, DATABITS_SIX, DATABITS_SEVEN, DATABITS_EIGHT = (Serial.DATABITS_FIVE, Serial.DATABITS_SIX, Serial.DATABITS_SEVEN, Serial.DATABITS_EIGHT)

    def __init__(self, parent=None):
        Serial.__init__(self, parent)

        self._Serial__on_read = self.__read  # watch out! self.__read set as the parent's callback
        self.__state = STATE_IDLE
        self.__on_read = None
        self.__on_error = None
        self.messages = []

        self.ENQ_For_ACK_Handle = ENQ_For_ACK_Handle(self)
        self.MESSAGE_For_ACK_Handle = MESSAGE_For_ACK_Handle(self)
        self.ACK_For_MESSAGE_Handle = ACK_For_MESSAGE_Handle(self)
        self.ACK_For_EOT_Handle = ACK_For_EOT_Handle(self)

        self.__dispatcher = Dispatcher()

    def setHandlerForMessageResponse(self, data, handle):
        self.__write(data)
        handle.attach()

    def writeENQ(self):
        self.state = STATE_ABOUT_TO_TX
        if DEBUG:
                logger.info("ТX ENQ")

        self.setHandlerForMessageResponse(ENQ, self.ENQ_For_ACK_Handle)

    def writeMessage(self):
        if self.messages:
            message = self.messages[0]
            self.messages = self.messages[1:]
            if DEBUG:
                logger.info("ТX {} CHECKSUM={}".format(message[1:-2], ord(message[-1])))

            self.setHandlerForMessageResponse(message, self.MESSAGE_For_ACK_Handle(message))

    def writeACK(self):
        if self.state == STATE_IDLE:
            self.state = STATE_RX_STARTED
            if DEBUG:
                logger.info("ТX ACK")

            self.setHandlerForMessageResponse(ACK, self.ACK_For_MESSAGE_Handle)
            return

        if self.state == STATE_RX_FINISHED:
            self.state = STATE_IDLE
            if DEBUG:
                logger.info("ТX ACK")

            self.setHandlerForMessageResponse(ACK, self.ACK_For_EOT_Handle)
            return

    def writeEOT(self):
        if DEBUG:
                logger.info("ТX EOT")

        self.__write(EOT)

    def writeNAK(self):
        if DEBUG:
                logger.info("ТX NAK")

        self.__write(NAK)

    def __read(self, data):
        if len(data) > 1:
            for byte in data:
                self.__read(byte)
            return

        self.__dispatcher.broadcastData(data)

        if data == ENQ:
            if DEBUG:
                logger.info("RX ENQ")

            if self.state == STATE_IDLE:
                self.writeACK()
                return

        if data == NAK:
            # решаем NAK
            if DEBUG:
                logger.info("RX NAK")

            return

    def __write(self, message):
        Serial.write(self, message)

    def __onReadyRead(self, message):
        if self.__on_read:
            self.__on_read(message)

    def __onError(self, error):
        if self.__on_error:
            self.__on_error(error)

    def errorString(self, errorCode):
        description = CODE_DESCRIPTION.get(errorCode, None)
        if None:
            description = CODE_DESCRIPTION[-1]

        return description

    def write(self, message):
        messages = []
        if isinstance(message, str):
            messages = str(message).split()  # in case we're trying to send something like "msg1 msg2     msg3"

        elif isinstance(message, list):
            for item in message:
                messages.append(item)
        else:
            raise TypeError("argument must be a string or a list of strings not {}".format(type(message).__name__))

        if not messages:
            return

        for message in messages:
            checksum = 0
            for char in message + ETX:
                checksum ^= ord(char)
            message = STX + message + ETX + chr(checksum)

            self.messages.append(message)

        if self.state == STATE_IDLE:
            self.writeENQ()

    @property
    def onRead(self):
        return self.__on_read

    @onRead.setter
    def onRead(self, callback):
        self.__on_read = callback

    @property
    def onError(self):
        return self.__on_error

    @onError.setter
    def onError(self, callback):
        self.__on_error = callback

    @property
    def state(self):
        return self.__state

    @state.setter
    def state(self, newSate):
        if DEBUG:
                logger.info("FROM {} -> TO {}".format(Bisync.verboseState(self.state), Bisync.verboseState(newSate)))

        self.__state = newSate

    @staticmethod
    def verboseState(state):
        if state == STATE_IDLE:        return "IDLE"
        if state == STATE_ABOUT_TO_TX: return "ABOUT_TO_TX"
        if state == STATE_TX_STARTED:  return "TX_STARTED"
        if state == STATE_TX_FINISHED: return "TX_FINISHED"
        if state == STATE_RX_STARTED:  return "RX_STARTED"
        if state == STATE_RX_FINISHED: return "RX_FINISHED"