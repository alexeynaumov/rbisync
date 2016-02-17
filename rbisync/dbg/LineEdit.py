from PyQt4.QtCore import Qt, SIGNAL
from PyQt4.QtGui import QLineEdit


class LineEdit(QLineEdit):
    def __init__(self, parent=None):
        QLineEdit.__init__(self, parent)

    def keyPressEvent(self, event):
        key = event.key()

        if key in [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Up, Qt.Key_Down]:
            self.emit(SIGNAL("keyPressed"), key)

        QLineEdit.keyPressEvent(self, event)