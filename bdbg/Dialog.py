# -*- coding: utf-8 -*-

# Copyright (C) 2015,2016 Alexey Naumov <rocketbuzzz@gmail.com>
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
sys.path.append(os.path.abspath("../"))
sys.path.append(os.path.abspath("../../rhelpers/"))
sys.path.append(os.path.abspath("../../rserial/"))

import termios
from PyQt4.QtCore import QTime, QStringList, QString, QSettings, QByteArray, Qt, QObject, SIGNAL
from PyQt4.QtGui import QDialog, QIcon
from rhelpers.utils import stringToBytes, bytesToString, History
from rserial.io import IO
from rbisync.bisync import Bisync
from bdbg.ui_Dialog import Ui_Dialog

ICON_ROCKET = os.path.dirname(__file__) + "/icons/rocket.svg"


class Dialog(QDialog, Ui_Dialog):
    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        
        self.setupUi(self)
        self.__initialize()

    def __del__(self):
        if self.__bisync.isOpen:
            try:
                self.__bisync.close()
            except Exception as error:
                self.__postText("E[?]: Error closing port.")

    def __initialize(self):
        self.setWindowIcon(QIcon(ICON_ROCKET))

        # Find out all supported baud rates
        attrs = dir(termios)
        baudRates = sorted([int(attr[1:]) for attr in attrs if (("B" == attr[0].upper()) and attr[1:].isdigit())])
        if 0 in baudRates:
            baudRates.remove(0)
        
        baudRateList = QStringList()
        for rate in baudRates:
            baudRateList.append(QString(str(rate)))

        self.comboBoxBaudRate.addItems(baudRateList)

        self.__history = History()

        self.__loadSettings()

        self.pushButtonSend.clicked.connect(self.onPushButtonSendClicked)
        self.pushButtonOpenClose.clicked.connect(self.onPushButtonOpenCloseClicked)
        self.checkBoxRawText.stateChanged.connect(self.onCheckBoxRawTextStateChanged)

        # self.lineEditData is a custom widget so slignal-slot connection is made this ways
        # when recompiling Dialog.ui do not forget to change
        # self.lineEdit = QtGui.QLineEdit(...) for self.lineEdit = LineEdit(...)
        QObject.connect(self.lineEditData, SIGNAL("keyPressed"), self.__keyPressed)

        self.pushButtonSend.setEnabled(False)
        self.lineEditData.setEnabled(False)

        self.__bisync = Bisync()

        self.__bisyncWidgets = list()
        self.__bisyncWidgets.append(self.lineEditDevice)
        self.__bisyncWidgets.append(self.comboBoxBaudRate)
        self.__bisyncWidgets.append(self.comboBoxDataBits)
        self.__bisyncWidgets.append(self.comboBoxParity)
        self.__bisyncWidgets.append(self.comboBoxStopBits)
        
    def __keyPressed(self, key):
        if key in [Qt.Key_Enter, Qt.Key_Return]:
            self.pushButtonSend.click()

        if Qt.Key_Up == key:
            previous = self.__history.previous()
            if previous:
                self.lineEditData.setText(previous)

        if Qt.Key_Down == key:
            next = self.__history.next()
            if next:
                self.lineEditData.setText(next)

    def __enablePortSettings(self):
        for widget in self.__bisyncWidgets:
            widget.setEnabled(True)

    def __disablePortSettings(self):
        for widget in self.__bisyncWidgets:
            widget.setEnabled(False)

    def __postText(self, text):
        if self.checkBoxTimestamp.isChecked():
            time = QTime.currentTime().toString()
            self.textEditTraffic.append("%s - %s" % (time, text))
        else:
            self.textEditTraffic.append(text)

    def __saveSettings(self):
        settings = QSettings("Rocket Labs", "bdbg")
        settings.setValue("device", self.lineEditDevice.text())
        settings.setValue("baudRate", self.comboBoxBaudRate.currentIndex())
        settings.setValue("dataBits", self.comboBoxDataBits.currentIndex())
        settings.setValue("parity", self.comboBoxParity.currentIndex())
        settings.setValue("stopBits", self.comboBoxStopBits.currentIndex())
        settings.setValue("format", self.comboBoxFormat.currentIndex())
        settings.setValue("leadingZeroes", self.checkBoxLeadingZeroes.isChecked())
        settings.setValue("timestamp", self.checkBoxTimestamp.isChecked())
        settings.setValue("rawText", self.checkBoxRawText.checkState())

    def __loadSettings(self):
        settings = QSettings("Rocket Labs", "bdbg")
        self.lineEditDevice.setText(settings.value("device", "/dev/ttyS0").toString())
        self.comboBoxBaudRate.setCurrentIndex(settings.value("baudRate", 0).toInt()[0])
        self.comboBoxDataBits.setCurrentIndex(settings.value("dataBits", 0).toInt()[0])
        self.comboBoxParity.setCurrentIndex(settings.value("parity", 0).toInt()[0])
        self.comboBoxStopBits.setCurrentIndex(settings.value("stopBits", 0).toInt()[0])
        self.comboBoxFormat.setCurrentIndex(settings.value("format", 0).toInt()[0])
        self.checkBoxLeadingZeroes.setChecked(settings.value("leadingZeroes", False).toBool())
        self.checkBoxTimestamp.setChecked(settings.value("timestamp", False).toBool())

        checkBoxState = settings.value("rawText", False).toInt()[0]
        self.checkBoxRawText.setCheckState(checkBoxState)  # setting checkBox "checked" doesn't produce the event "stateChanged"
        self.onCheckBoxRawTextStateChanged(checkBoxState)  # so we call self.onCheckBoxRawTextStateChanged implicitly

    def closeEvent(self, event):
        self.__saveSettings()
        if self.__bisync.isOpen:
            try:
                self.__bisync.close()
            except Exception as error:
                self.__postText("E[?]: Error closing port.")
        super(Dialog, self).closeEvent(event)
        
    def onCheckBoxRawTextStateChanged(self, state):
        if state == Qt.Checked:
            self.labelFormat.setEnabled(False)
            self.comboBoxFormat.setEnabled(False)
            self.checkBoxLeadingZeroes.setEnabled(False)
        else:
            self.labelFormat.setEnabled(True)
            self.comboBoxFormat.setEnabled(True)
            self.checkBoxLeadingZeroes.setEnabled(True)

    def onRead(self, data):
        if self.checkBoxRawText.isChecked():
            dataFormat = "S"
            text = str(data)

        else:
            INDEX_BASE = {0: 2, 1: 8, 2: 10, 3: 16}
            index = self.comboBoxFormat.currentIndex()
            base = INDEX_BASE.get(index, None)
            if not base:
                self.__postText("E[?]: Invalid base of a number.")

            data = [ord(item) for item in data]
            text = bytesToString(data, base, self.checkBoxLeadingZeroes.isChecked())

            INDEX_FORMAT = {0: "B", 1: "O", 2: "D", 3: "H"}
            dataFormat = INDEX_FORMAT.get(index, None)
            if not dataFormat:
                self.__postText("E[?]: Invalid data format.")

        self.__postText("R[%s:%s]: %s" % (dataFormat, len(data), text))

    def onPushButtonSendClicked(self):
        if not self.__bisync.isOpen:
            self.__postText("E[?]: Port is not open.")
            return

        text = self.lineEditData.text().simplified()
        if text.isEmpty():
            self.__postText("E[?]: No input provided.")
            return

        self.__history.add(self.lineEditData.text())
        
        data = QByteArray()

        if self.checkBoxRawText.isChecked():
            dataFormat = "S"
            data = text.toLocal8Bit()

        else:
            INDEX_BASE = {0: 2, 1: 8, 2: 10, 3: 16}
            index = self.comboBoxFormat.currentIndex()
            base = INDEX_BASE.get(index, None)
            if not base:
                self.__postText("E[?]: Invalid base of a number.")

            try:
                values = stringToBytes(str(text), base)
            except ValueError as error:
                self.__postText("E[?]: Incorrect input: <%s>." % str(error).capitalize())

            for value in values:
                data.append(chr(value))

            text = bytesToString(values, base, self.checkBoxLeadingZeroes.isChecked())

            INDEX_FORMAT = {0: "B", 1: "O", 2: "D", 3: "H"}
            dataFormat = INDEX_FORMAT.get(index, None)
            if not dataFormat:
                self.__postText("E[?]: Invalid data format.")

        self.lineEditData.clear()
        self.__postText("T[%s:%s]: %s" % (dataFormat, len(data), text))
        self.__bisync.write(data.data())


    def onPushButtonOpenCloseClicked(self):
        if self.__bisync.isOpen:
            try:
                self.__bisync.close()
                self.__enablePortSettings()
                self.pushButtonOpenClose.setText("Open")
                self.pushButtonSend.setEnabled(False)
                self.lineEditData.setEnabled(False)
            except Exception as error:
                self.__postText("E[?]: Error closing port. %s" % str(error).capitalize())
        else:
            try:
                self.__bisync.port = self.lineEditDevice.text()
                self.__bisync.baudRate = int(self.comboBoxBaudRate.currentText())
                self.__bisync.byteSize = int(self.comboBoxDataBits.currentText())
                self.__bisync.parity = [IO.PARITY_NONE, IO.PARITY_EVEN, IO.PARITY_ODD, IO.PARITY_MARK, IO.PARITY_SPACE][self.comboBoxParity.currentIndex()]
                self.__bisync.stopBits = [IO.STOPBITS_ONE, IO.STOPBITS_ONE_POINT_FIVE, IO.STOPBITS_TWO][self.comboBoxStopBits.currentIndex()]
                self.__bisync.onRead = self.onRead
                self.__bisync.open()
                self.__disablePortSettings()
                self.pushButtonOpenClose.setText("Close")
                self.pushButtonSend.setEnabled(True)
                self.lineEditData.setEnabled(True)
            except Exception as error:
                self.__postText("E[?]: Error opening port. %s Try 'sudo chmod o=rw %s'" % (str(error).capitalize(), self.lineEditDevice.text()))
