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
sys.path.append(os.path.abspath("../../rhelpers/"))

import re
from datetime import datetime
from PyQt4.QtCore import QTimer
from rserial.serial import Serial
from rhelpers.utils import bytesToString

DEBUG = True

STRICT, LEGACY = 0, 1

ENQ = chr(05)
ACK = chr(06)
NAK = chr(21)
STX = chr(02)
ETX = chr(03)
EOT = chr(04)

# for debug purposes
CODE_SYMBOL = {4: "EOT", 5: "ENQ", 6: "ACK", 21: "NAK"}

STATE_IDLE = 0
STATE_TX_STARTED = 1
STATE_TX_FINISHED = 2
STATE_RX_STARTED = 3
STATE_RX_FINISHED = 4

# for debug purposes
CODE_STATE = {0: "IDLE", 1: "TX_STARTED", 2: "TX_FINISHED", 3: "RX_STARTED", 4: "RX_FINISHED"}

ATTEMPT_TIMEOUT = {1: 2000, 2: 2000, 3: 2000}
MAX_ATTEMPT = len(ATTEMPT_TIMEOUT)


# for debug purposes
def PRINT(string):
    now = datetime.now()
    now = now.strftime("%H:%M:%S.%f")
    print("%s | %s" % (now, string))

MODE = LEGACY

class Bisync(Serial):

    PARITY_NONE, PARITY_EVEN, PARITY_ODD, PARITY_MARK, PARITY_SPACE = (Serial.PARITY_NONE, Serial.PARITY_EVEN, Serial.PARITY_ODD, Serial.PARITY_MARK, Serial.PARITY_SPACE)
    STOPBITS_ONE, STOPBITS_ONE_POINT_FIVE, STOPBITS_TWO = (Serial.STOPBITS_ONE, Serial.STOPBITS_ONE_POINT_FIVE, Serial.STOPBITS_TWO)
    FIVEBITS, SIXBITS, SEVENBITS, EIGHTBITS = (Serial.FIVEBITS, Serial.SIXBITS, Serial.SEVENBITS, Serial.EIGHTBITS)

    def __init__(self, parent=None):
        Serial.__init__(self, parent)

        self._Serial__on_read = self.__read  # watch out! Bisync.__read set as the parent's callback

        self.__state = STATE_IDLE  # initial state
        self.__traffic = ""  # no data received yet (it is incoming data)
        self.__messages = []  # no messages to transmit yet (it is the user messages queue)
        self.__txData = ""  # no data to transmit yet (it is a string of: STX + message + ETX + chr(checksum))
        self.__wait_for = None  # waiting for nothing in received data
        self.__on_read = None  # on-read callback
        self.__on_error = None  # on-error callback

        self.__attempt = 0
        self.__stateTimer = QTimer(self)
        self.__stateTimer.timeout.connect(self.__onTimeout)
        self.__stateTimer.setSingleShot(True)

    def __onTimeout(self):
        if self.__state != STATE_IDLE:

            if self.__attempt < MAX_ATTEMPT:  # we failed, but we are still trying to send the message
                errorCode = -1  # error notification
                data = self.__txData
                data = data[1:-2]  # remove STX, ETX and checksum
                errorDescription = "Failed to write data after %s attempt(s): %s" % (self.__attempt, data)
                error = (errorCode, errorDescription)
                self.__onError(error)

                self.__attempt += 1  # update the state for the next attempt
                self.__stateTimer.start(ATTEMPT_TIMEOUT[self.__attempt])
                self.__ENQ()  # and try again <<<===================NEXT ATTEMPT TO SEND THE CURRENT MESSAGE STARTS HERE

            else:  # we gave up and send the next message
                errorCode = -1  # error notification
                errorDescription = "Remote peer is not responding."
                error = (errorCode, errorDescription)
                self.__onError(error)

                self.__attempt = 0  # initialize the state for the next message
                self.__state = STATE_IDLE
                self.__txData = ""
                self.__wait_for = None

                self.__next()  # send the next message (FAILURE CASE) <<<===TRANSMISSION OF THE NEXT MESSAGE STARTS HERE

    def __next(self):
        if self.__messages:
            self.__message = self.__messages[0]  # store the message being sent in self.__message for the ON_NAK case
            self.__messages = self.__messages[1:]
            self.__write(self.__message)

    def __ENQ(self):
        if DEBUG:
            PRINT("TX: ENQ")

        self.__state = STATE_TX_STARTED
        Serial.write(self, ENQ)
        self.__wait(ACK)


    def __ON_ENQ(self):
        if DEBUG:
            PRINT("RX: ENQ")

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
        if DEBUG:
            PRINT("TX: ACK")

        if self.__state == STATE_RX_STARTED:
            Serial.write(self, ACK)
            #pattern = r"%s(?P<message>[0-9]+)%s(?P<checksum>.{1})" % (STX, ETX)  # only decimals
            pattern = r"%s(?P<message>.+)%s(?P<checksum>.{1})" % (STX, ETX)  # any character
            self.__wait(pattern)
            return

        if self.__state == STATE_RX_FINISHED:
            Serial.write(self, ACK)
            self.__wait(EOT)

    def __ON_ACK(self):
        if DEBUG:
            PRINT("RX: ACK")

        if self.__state == STATE_TX_STARTED:
            if DEBUG:
                data = self.__txData
                PRINT("TX: MESSAGE: %s" % data[1:-2])

            Serial.write(self, self.__txData)
            self.__state = STATE_TX_FINISHED
            self.__wait(ACK)
            return

        if self.__state == STATE_TX_FINISHED:
            self.__EOT()
            return

    def __NAK(self):
        if DEBUG:
            PRINT("TX: NAK")

        Serial.write(self, NAK)

    def __ON_NAK(self):
        if DEBUG:
            PRINT("RX: NAK")

        errorCode = -1  # error notification
        errorDescription = "Remote peer didn't acknowledge transmission."
        error = (errorCode, errorDescription)
        self.__onError(error)

        self.__txData = ""
        self.__wait_for = None
        self.__state = STATE_IDLE
        self.__stateTimer.stop()
        # TO-DO: we're supposed to try to send the message again after timeout expires.

    def __EOT(self):
        if DEBUG:
            PRINT("TX: EOT")

        self.__attempt = 0  # initialize the state
        self.__state = STATE_IDLE
        self.__txData = ""
        self.__wait_for = None
        Serial.write(self, EOT)  # notify the peer we're done
        self.__stateTimer.stop()  # do I really need this? # <<<=======TRANSMISSION OF THE CURRENT MESSAGE FINISHED HERE
        self.__next()  # send the next message (SUCCESS CASE) <<<=========TRANSMISSION OF THE NEXT MESSAGE STARTS HERE

    def __ON_EOT(self):
        if DEBUG:
            PRINT("RX: EOT")

        self.__state = STATE_IDLE
        self.__txData = ""
        self.__wait_for = None

    def __wait(self, re_pattern):
        if DEBUG:
            if len(re_pattern) == 1:
                pattern = CODE_SYMBOL.get(ord(re_pattern))
            else:
                pattern = "MESSAGE"

            PRINT("WAITING: %s" % pattern)

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

            if self.__state == STATE_RX_FINISHED and re.match(EOT, data):
                self.__ON_EOT()

            if re.match(NAK, data):
                self.__ON_NAK()
                return

            if self.__state == STATE_RX_STARTED:
                self.__traffic += data

                # values = []
                # for value in self.__traffic:
                #     values.append(ord(value))
                # print "TRAFFIC: %s " % bytesToString(values, 10)
                # print "WAITFOR: %s " % self.__wait_for

                match = re.match(self.__wait_for, self.__traffic)
                if match:
                    message = match.group('message')

                    checksum_before = ord(match.group('checksum'))
                    checksum_after = 0
                    for char in message + ETX:
                        checksum_after ^= ord(char)

                    print "RX checksum_before: %s " % checksum_before
                    print "RX checksum_after : %s " % checksum_after

                    if checksum_after != checksum_before:
                        errorCode = -1
                        errorDescription = "Checksum error in %s. Expected value: %s, received value: %s" % (message, checksum_after, checksum_before)
                        error = (errorCode, errorDescription)
                        self.__onError(error)

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
        '''
        The slot is called when new data(str) <message> has been received from the peer.
        :param message(str): new data, a complete unit og meaning;
        :return: None
        '''

        if DEBUG:
            PRINT("RX: MESSAGE: %s" % message)

        if self.__on_read:
            self.__on_read(message)

    def __write(self, message):
        '''
        Write the data(str) <message> using the BSC protocol. The data is supposed to be a complete unit of meaning
        (a command, message, etc...) sent to the peer as a whole.
        :param message: the  to write
        :return: None
        '''
        self.__attempt += 1
        self.__stateTimer.start(ATTEMPT_TIMEOUT[self.__attempt])

        checksum = 0
        for char in message + ETX:
            checksum ^= ord(char)

        self.__txData = STX + message + ETX + chr(checksum)  # make a message
        print "TX checksum: %s " % checksum
        self.__ENQ()

    def __onError(self, error):
        '''
        The slot is called when an error(tuple(int, str)) <error> occurs.
        :param error tuple(errorCode(int), errorDescription(str)): the error occurred;
        :return: None
        '''

        if DEBUG:
            PRINT("ERROR: %s" % error[1])

        if self.__on_error:
            self.__on_error(error)

    def write(self, message):
        '''
        Write the data(str) <message> using the BSC protocol. As self.__write, the data is either a complete unit of
        meaning or a series of complete units of meaning(separated by white space: "msg1 msg2 msg3").
        :param message:
        :return: None
        '''
        messages = str(message).split()  # in case we're trying to send something like "msg1 msg2  msg3"
        self.__messages += messages
        self.__next()

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