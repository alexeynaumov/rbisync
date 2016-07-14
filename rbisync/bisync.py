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
from PyQt4.QtCore import QTimer
from rserial.serial import Serial


DEBUG = True  # if set True, debug messages are sent to stdout
STRICT = False  # if set True, the behaviour is close to BSC protocol spec
IGNORE_CHECKSUM_ERRORS = True

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

RETRY_TIMEOUT = {1: 1500, 2: 1500}  # key=retry number, value=delay(milliseconds)
MAX_RETRY = len(RETRY_TIMEOUT)

ACK_EXPIRATION = 1500  # (milliseconds), the period of time we wait the peer to send ACK
MESSAGE_EXPIRATION = 3000  # (milliseconds), the period of time we wait the peer to send a message
EOT_EXPIRATION = 1500  # (milliseconds), the period of time we wait the peer to send EOT

# errors
CODE_DESCRIPTION = {
   -1: "Unknown error",
    1: "No ACK too long after several attempt(s) before sending message",
    2: "Remote peer not responding.",
    3: "No ACK too long AFTER sending message.",
    4: "No message too long.",
    5: "No EOT too long.",
    6: "Remote peer not acknowledge transmission.",
    7: "Checksum error"
}

# for debug purposes
CODE_SYMBOL = {ord(EOT): "EOT", ord(ENQ): "ENQ", ord(ACK): "ACK", ord(NAK): "NAK"}
CODE_STATE = {STATE_IDLE: "IDLE", STATE_TX_STARTED: "TX_STARTED", STATE_TX_FINISHED: "TX_FINISHED", STATE_RX_STARTED: "RX_STARTED", STATE_RX_FINISHED: "RX_FINISHED"}

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

        self.__state = STATE_IDLE  # default state
        self.__traffic = ""  # no data received yet (it is received data from the peer)
        self.__messages = []  # no messages to transmit yet (it is the user messages queue)
        self.__txData = ""  # no data to transmit yet (it is a string of: STX + message + ETX + chr(checksum))
        self.__retryCount = 0  # number of retries to send __txData (at the 1st attempt retryCount=0, at the 2nd attempt retryCount=1, at the 3rd attempt- retryCount=2,...)
        self.__wait_for = None  # waiting for nothing in received data
        self.__on_read = None  # on-read callback
        self.__on_error = None  # on-error callback

        # makes a data send retry (after a predefined timeout), if the message transmission failed
        self.__timer_retryToSend = QTimer(self)
        self.__timer_retryToSend.setSingleShot(True)
        self.__timer_retryToSend.timeout.connect(self.__onRetry)

        # checks if ACK (from the peer) is late or received at all
        self.__timer_ACK_expires = QTimer(self)
        self.__timer_ACK_expires.timeout.connect(self.__on_ACK_expires)
        self.__timer_ACK_expires.setSingleShot(True)
        self.__timer_ACK_expires.setInterval(ACK_EXPIRATION)

        # checks if a message (from the peer) is late or received at all
        self.__timer_MESSAGE_expires = QTimer(self)
        self.__timer_MESSAGE_expires.timeout.connect(self.__on_MESSAGE_expires)
        self.__timer_MESSAGE_expires.setSingleShot(True)
        self.__timer_MESSAGE_expires.setInterval(MESSAGE_EXPIRATION)

        # checks if EOT (from the peer) is late or received at all
        self.__timer_EOT_expires = QTimer(self)
        self.__timer_EOT_expires.timeout.connect(self.__on_EOT_expires)
        self.__timer_EOT_expires.setSingleShot(True)
        self.__timer_EOT_expires.setInterval(EOT_EXPIRATION)

    def __onRetry(self):
        '''
        Called by self.__timer_retryToSend after timeout expires to make the next attempt to send data to the peer.
        :return: None
        '''
        self.__write(self.__message)

    def __on_ACK_expires(self):
        '''
        Called by self.__timer_ACK_expires when we're not going to wait for ACK from the peer any longer.
        :return: None
        '''
        if self.__state == STATE_TX_STARTED:

            if self.__retryCount < MAX_RETRY:  # we failed, but we are still trying to send the message
                errorCode = 1  # error notification
                data = self.__txData[1:-2]  # remove STX, ETX and checksum
                errorDescription = "No ACK too long after %s attempt(s) before sending message: %s" % (self.__retryCount+1, data)
                error = (errorCode, errorDescription)
                self.__onError(error)

                self.__timer_ACK_expires.stop()
                self.__timer_MESSAGE_expires.stop()
                self.__timer_EOT_expires.stop()

                self.__retryCount += 1
                self.__timer_retryToSend.setInterval(RETRY_TIMEOUT[self.__retryCount])
                self.__timer_retryToSend.start()

            else:  # we gave up and send the next message
                errorCode = 2  # "Remote peer not responding."
                errorDescription = self.__errorString(errorCode)
                error = (errorCode, errorDescription)
                self.__onError(error)

                self.__retryCount = 0  # reset the state to defaults
                self.__state = STATE_IDLE
                self.__txData = ""
                self.__wait_for = None

                self.__next()  # send the next message (FAILURE CASE) <<<===TRANSMISSION OF THE NEXT MESSAGE STARTS HERE

        elif self.__state == STATE_TX_FINISHED:
            errorCode = 3  # "No ACK too long AFTER sending message."
            errorDescription = self.__errorString(errorCode)
            error = (errorCode, errorDescription)
            self.__onError(error)

            if not STRICT:
                self.__ON_ACK(peer=self)  # pretend that we received it

        else:
            pass

    def __on_MESSAGE_expires(self):
        '''
        Called by self.__timer_MESSAGE_expires when we're not going to wait for a message from the peer any longer.
        :return: None
        '''
        errorCode = 4
        errorDescription = "No message too long. Going to IDLE by force."
        error = (errorCode, errorDescription)
        self.__onError(error)

        #TO-DO: gotta send NAK
        self.__traffic = ""
        self.__state = STATE_IDLE

    def __on_EOT_expires(self):
        '''
        Called by self.__timer_EOT_expires when we're not going to wait for EOT from the peer any longer.
        :return: None
        '''
        errorCode = 5
        errorDescription = "No EOT too long. Going to IDLE by force."
        error = (errorCode, errorDescription)
        self.__onError(error)

        if not STRICT:
            self.__ON_EOT(peer=self)  # pretend that we received it

    def __ENQ(self):
        '''
        Send ENQ to the peer.
        :return: None
        '''
        if DEBUG:
            logger.info("TX: ENQ")

        self.__state = STATE_TX_STARTED
        Serial.write(self, ENQ)
        self.__wait(ACK)
        self.__timer_ACK_expires.start()

    def __ON_ENQ(self, peer=None):
        '''
        Called when ENQ is received from the peer.
        :return: None
        '''
        if DEBUG:
            peer = "from SELF" if peer else "from PEER"
            logger.info("RX: ENQ "+peer)

        if STRICT:
            if self.__state != STATE_IDLE:
                self.__NAK()
                return

        if self.__state in [STATE_IDLE, STATE_RX_STARTED, STATE_RX_FINISHED]:  # watch out the list of states!
            self.__state = STATE_RX_STARTED
            self.__ACK()
            self.__timer_MESSAGE_expires.start()
        else:
            self.__NAK()

    def __ACK(self):
        '''
        Send ACK to the peer.
        :return: None
        '''
        if DEBUG:
            logger.info("TX: ACK")

        if self.__state == STATE_RX_STARTED:
            Serial.write(self, ACK)
            #pattern = r"%s(?P<message>[0-9]+)%s(?P<checksum>.{1})" % (STX, ETX)  # allow only decimals
            pattern = r"%s(?P<message>.+)%s(?P<checksum>.{1})" % (STX, ETX)  # allow any character
            self.__wait(pattern)
            return

        if self.__state == STATE_RX_FINISHED:
            Serial.write(self, ACK)
            self.__wait(EOT)

    def __ON_ACK(self, peer=None):
        '''
        Called when ACK is received from the peer.
        :return:
        '''
        if DEBUG:
            peer = "from SELF" if peer else "from PEER"
            logger.info("RX: ACK "+peer)

        if self.__state not in [STATE_TX_STARTED, STATE_TX_FINISHED]:
            return

        self.__timer_ACK_expires.stop()

        if self.__state == STATE_TX_STARTED:
            if DEBUG:
                logger.info("TX: MESSAGE: %s" % self.__txData[1:-2])

            Serial.write(self, self.__txData)
            self.__state = STATE_TX_FINISHED
            self.__wait(ACK)
            self.__timer_ACK_expires.start()
            return

        if self.__state == STATE_TX_FINISHED:
            self.__EOT()
            return

    def __NAK(self):
        '''
        Send NAK to the peer.
        :return: None
        '''
        if DEBUG:
            logger.info("TX: NAK")

        Serial.write(self, NAK)

    def __ON_NAK(self, peer=None):
        '''
        Called when NAK is received from the peer.
        :return: None
        '''
        if DEBUG:
            peer = "from SELF" if peer else "from PEER"
            logger.info("RX: NAK "+peer)

        # "Remote peer didn't acknowledge transmission."
        errorCode = 6  # error notification
        errorDescription = self.__errorString(errorCode)
        error = (errorCode, errorDescription)
        self.__onError(error)

        self.__txData = ""
        self.__wait_for = None
        self.__state = STATE_IDLE
        self.__timer_retryToSend.stop()
        # TO-DO: we're supposed to try to send the message again after timeout expires.

    def __EOT(self):
        '''
        Send EOT to the peer.
        :return: None
        '''
        if DEBUG:
            logger.info("TX: EOT")

        self.__retryCount = 0  # reset the state to defaults
        self.__state = STATE_IDLE
        self.__txData = ""
        self.__wait_for = None
        Serial.write(self, EOT)  # notify the peer we're done
        self.__timer_retryToSend.stop()  # <<<=========================TRANSMISSION OF THE CURRENT MESSAGE FINISHED HERE
        self.__next()  # send the next message (SUCCESS CASE) <<<===========TRANSMISSION OF THE NEXT MESSAGE STARTS HERE

    def __ON_EOT(self, peer=None):
        '''
        Called when EOT is received from the peer.
        :return: None
        '''
        if DEBUG:
            peer = "from SELF" if peer else "from PEER"
            logger.info("RX: EOT "+peer)

        if self.__state != STATE_RX_FINISHED:
            return

        self.__timer_EOT_expires.stop()

        self.__state = STATE_IDLE
        self.__txData = ""
        self.__wait_for = None

    def __wait(self, re_pattern):
        '''
        Set the regex pattern to wait for in incoming data to appear.
        :param re_pattern(str): regex pattern of awaited data
        :return: None
        '''
        if DEBUG:
            if len(re_pattern) == 1:
                pattern = CODE_SYMBOL.get(ord(re_pattern))
            else:
                pattern = "MESSAGE"

            logger.info("WAITING: %s" % pattern)

        if not re_pattern:
            raise ValueError("Wrong argument. Have no idea what to wait for.")

        self.__wait_for = re.compile(re_pattern)

    def __read(self, data):
        '''
        Called every time new data is received from the peer.
        :param data(str): new data received from the peer
        :return: None
        '''
        # The data from the peer might be received in chunks of several bytes, but we want to process it on byte at a
        # time.
        if len(data) > 1:
            for byte in data:
                self.__read(byte)
            return

        # If there's a match we do the appropriate processing.
        if re.match(ENQ, data):
            self.__ON_ENQ()
            return

        if re.match(ACK, data):
            self.__ON_ACK()
            return

        if re.match(EOT, data):
            self.__ON_EOT()
            return

        if re.match(NAK, data):
            self.__ON_NAK()
            return

        if self.__state == STATE_RX_STARTED:
            self.__traffic += data

            match = re.match(self.__wait_for, self.__traffic)
            if match:
                self.__timer_MESSAGE_expires.stop()

                message = match.group('message')
                self.__onReadyRead(message)

                checksum_remote = ord(match.group('checksum'))  # the sum in the message, the peer calculated it
                checksum_local = 0  # the sum we calculate based upon data received from the peer
                for char in message + ETX:
                    checksum_local ^= ord(char)

                checksum_ok = True if checksum_local == checksum_remote else False

                if IGNORE_CHECKSUM_ERRORS:
                    checksum_ok = True

                if checksum_ok:
                    self.__traffic = ""
                    self.__state = STATE_RX_FINISHED
                    self.__ACK()
                    self.__timer_EOT_expires.start()
                else:
                    errorCode = 7
                    errorDescription = "Checksum error in %s. Expected: %s, received: %s" % (message, checksum_local, checksum_remote)
                    error = (errorCode, errorDescription)
                    self.__onError(error)

                    self.__traffic = ""
                    self.__state = STATE_RX_FINISHED
                    self.__NAK()

    def __onReadyRead(self, message):
        '''
        The slot is called when new data(str) <message> has been received from the peer.
        :param message(str): new data, a complete unit og meaning;
        :return: None
        '''

        if DEBUG:
            logger.info("RX: MESSAGE: %s" % message)

        if self.__on_read:
            self.__on_read(message)

    def __onError(self, error):
        '''
        The slot is called when an error(tuple(int, str)) <error> occurs.
        :param error tuple(errorCode(int), errorDescription(str)): the error occurred;
        :return: None
        '''
        if DEBUG:
            logger.error("ERROR: %s" % error[1])

        if self.__on_error:
            self.__on_error(error)

    def __write(self, message):
        '''
        Write the data(str) <message> using the BSC protocol. The data is supposed to be a complete unit of meaning
        (a command, message, etc...) sent to the peer as a whole.
        :param message(str): data to write
        :return: None
        '''
        checksum = 0
        for char in message + ETX:
            checksum ^= ord(char)

        self.__txData = STX + message + ETX + chr(checksum)  # make a message
        self.__ENQ()

    def __next(self):
        '''
        Get the next message(str) to send and store it in self.__message for future use.
        :return: None
        '''
        if self.__messages:
            self.__message = self.__messages[0]
            self.__messages = self.__messages[1:]
            self.__write(self.__message)

    def __errorString(self, errorCode):
        description = CODE_DESCRIPTION.get(errorCode, None)
        if None:
            description = CODE_DESCRIPTION[-1]

        return description

    def write(self, message):
        '''
        Write data(either str or list of str)<message> using the BSC protocol. The data consists of either:
        1. a single unit of meaning (e.g. "msg") of type str or;
        2. a series of complete units of meaning separated by white space (e.g "msg1 msg2 msg3") of type str or;
        3. a list of complete units of meaning (e.g. ["msg1", "msg2", "msg3"]) of type str.
        :param message(either str or list of str): data to write
        :return: None
        '''
        if isinstance(message, str):
            messages = str(message).split()  # in case we're trying to send something like "msg1 msg2     msg3"
            self.__messages += messages
        elif isinstance(message, list):
            for item in message:
                self.__messages.append(item)
        else:
            raise TypeError("argument must be a string or a list of strings not {}".format(type(message).__name__))

        if self.__state == STATE_IDLE:
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