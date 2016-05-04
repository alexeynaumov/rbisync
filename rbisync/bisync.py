# -*- coding: utf-8 -*-

# Copyright (C) 2015-2016 Alexey Naumov <rocketbuzzz@gmail.com>
#
# This file is part of rbisync.
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

import sys, os
sys.path.append(os.path.abspath("../../rserial/"))

import re
from PyQt4.QtCore import QTimer
from rserial.serial import Serial

STRICT, LEGACY = 0, 1

ENQ = chr(05)
ACK = chr(06)
NAK = chr(21)
STX = chr(02)
ETX = chr(03)
EOT = chr(04)

STATE_IDLE = 0
STATE_TX_STARTED = 1
STATE_TX_FINISHED = 2
STATE_RX_STARTED = 3
STATE_RX_FINISHED = 4

STATE = ["IDLE", "TX_STARTED", "TX_FINISHED", "RX_STARTED", "RX_FINISHED"]

ATTEMPT_TIMEOUT = {1: 2000, 2: 2000, 3: 2000}
MAX_ATTEMPT = len(ATTEMPT_TIMEOUT)

MODE = LEGACY


class Bisync(Serial):

    PARITY_NONE, PARITY_EVEN, PARITY_ODD, PARITY_MARK, PARITY_SPACE = (Serial.PARITY_NONE, Serial.PARITY_EVEN, Serial.PARITY_ODD, Serial.PARITY_MARK, Serial.PARITY_SPACE)
    STOPBITS_ONE, STOPBITS_ONE_POINT_FIVE, STOPBITS_TWO = (Serial.STOPBITS_ONE, Serial.STOPBITS_ONE_POINT_FIVE, Serial.STOPBITS_TWO)
    FIVEBITS, SIXBITS, SEVENBITS, EIGHTBITS = (Serial.FIVEBITS, Serial.SIXBITS, Serial.SEVENBITS, Serial.EIGHTBITS)

    def __init__(self, parent=None):
        Serial.__init__(self, parent)

        self._Serial__on_read = self.__read

        self.__state = STATE_IDLE  # initial state
        self.__traffic = ""  # no data received yet
        self.__txData = ""  # no data to transmit yet
        self.__wait_for = None  # waiting for nothing in received data
        self.__on_read = None  # on-read callback
        self.__on_error = None  # on-error callback

        self.__attempt = 0
        self.__stateTimer = QTimer(self)
        self.__stateTimer.timeout.connect(self.__onTimeout)
        self.__stateTimer.setSingleShot(True)

    def __onTimeout(self):
        if self.__state != STATE_IDLE:
            if self.__attempt < MAX_ATTEMPT:
                self.__attempt += 1
                self.__stateTimer.start(ATTEMPT_TIMEOUT[self.__attempt])
                self.__ENQ()
            else:
                self.__attempt = 0
                self.__state = STATE_IDLE
                self.__txData = ""
                self.__wait_for = None

    def __ENQ(self):
        self.__state = STATE_TX_STARTED
        Serial.write(self, ENQ)
        self.__wait(ACK)

    def __ON_ENQ(self):

        if MODE == LEGACY:
            #=== LEGACY ================================================================================================
            if self.__state in [STATE_IDLE, STATE_RX_STARTED, STATE_RX_FINISHED]:
                self.__state = STATE_RX_STARTED
                self.__ACK()
            else:
                self.__NAK()
            #===========================================================================================================

        elif MODE == STRICT:
            #=== STRICT ================================================================================================
            if self.__state == STATE_IDLE:
                self.__state = STATE_RX_STARTED
                self.__ACK()
            else:
                self.__NAK()
            #===========================================================================================================

        else:
            raise Exception("Unknown operational mode.")

    def __ACK(self):
        if self.__state == STATE_RX_STARTED:
            Serial.write(self, ACK)
            self.__wait(r"%s(?P<message>[0-9]+)%s(?P<checksum>.{1})" % (STX, ETX))
            return

        if self.__state == STATE_RX_FINISHED:
            Serial.write(self, ACK)
            self.__wait(EOT)

    def __ON_ACK(self):
        if self.__state == STATE_TX_STARTED:
            Serial.write(self, self.__txData)
            self.__state = STATE_TX_FINISHED
            self.__wait(ACK)
            return

        if self.__state == STATE_TX_FINISHED:
            self.__EOT()
            return

    def __NAK(self):
        Serial.write(self, NAK)

    def __ON_NAK(self):
        self.__txData = ""
        self.__wait_for = None
        self.__state = STATE_IDLE

    def __EOT(self):
        self.__attempt = 0
        self.__state = STATE_IDLE
        self.__txData = ""
        self.__wait_for = None
        Serial.write(self, EOT)

    def __ON_EOT(self):
        self.__state = STATE_IDLE
        self.__txData = ""
        self.__wait_for = None

    def __wait(self, re_pattern):
        if not re_pattern:
            raise Exception("Have no idea what to wait for!")

        self.__wait_for = re.compile(re_pattern)

    def __read(self, data):
        if len(data) > 1:
            for byte in data:
                self.__read(byte)
            return

        if MODE == LEGACY:
            #=== LEGACY ================================================================================================
            if re.match(ENQ, data):
                if self.__state in [STATE_IDLE, STATE_RX_STARTED, STATE_RX_FINISHED]:
                    self.__ON_ENQ()
                    return

            if re.match(ACK, data):
                if self.__state in [STATE_TX_STARTED, STATE_TX_FINISHED]:
                    self.__ON_ACK()
                    return

            if re.match(NAK, data):
                self.__ON_NAK()
                return

            if self.__state == STATE_RX_STARTED:
                self.__traffic += data
                match = re.match(self.__wait_for, self.__traffic)
                if match:
                    message = match.group('message')

                    checksum_before = ord(match.group('checksum'))
                    checksum_after = 0
                    for char in message + ETX:
                        checksum_after ^= ord(char)

                    if checksum_after != checksum_before:
                        if self.__on_error:
                            self.__on_error(255, "Checksum error in %s. Expected value: %s, received value: %s !" % (message, checksum_after, checksum_before))

                    # elapsed time check
                    self.__onReadyRead(message)

                    self.__traffic = ""
                    self.__state = STATE_RX_FINISHED
                    self.__ACK()
            #===========================================================================================================

        elif MODE == STRICT:
            #=== STRICT ================================================================================================
            if self.__state == STATE_IDLE:
                if re.match(ENQ, data):
                    self.__ON_ENQ()
                    return

                raise Exception("Received unknown symbol %s (not ENQ) while in state STATE_IDLE!" % ord(data))

            if self.__state in [STATE_TX_STARTED, STATE_TX_FINISHED]:
                if re.match(ACK, data):
                    self.__ON_ACK()
                    return

                if re.match(NAK, data):
                    self.__ON_NAK()
                    return

                raise Exception("Received unknown symbol (neither ACK nor NAK): %s !" % ord(data))

            if self.__state == STATE_RX_STARTED:
                self.__traffic += data
                match = re.match(self.__wait_for, self.__traffic)
                if match:
                    message = match.group('message')

                    checksum_before = ord(match.group('checksum'))
                    checksum_after = 0
                    for char in message + ETX:
                        checksum_after ^= ord(char)

                    if checksum_after != checksum_before:
                        self.__on_error(255, "Checksum error in %s. Expected value: %s, received value: %s !" % (message, checksum_after, checksum_before))

                    # elapsed time check
                    self.__onReadyRead(message)

                    self.__traffic = ""
                    self.__state = STATE_RX_FINISHED
                    self.__ACK()
            #===========================================================================================================

        else:
            raise Exception("Unknown operational mode.")


    def __onReadyRead(self, message):
        if self.__on_read:
            self.__on_read(message)

    def __onError(self, code, description):
        if self.__on_error:
            self.__on_error(code, description)

    def write(self, message):
        # if re.search(r'\s+', message):
        #     for submessage in re.split(r'\s+', message):
        #         self.write(submessage)
        #     return

        self.__attempt += 1
        self.__stateTimer.start(ATTEMPT_TIMEOUT[self.__attempt])

        checksum = 0
        for char in message + ETX:
            checksum ^= ord(char)

        self.__txData = STX + message + ETX + chr(checksum)
        self.__ENQ()

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