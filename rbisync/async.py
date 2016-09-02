from abc import abstractmethod
from PyQt4.QtCore import QTimer, QObject


def singleton(cls):
    instances = {}

    def getinstance():
        if cls not in instances:
            instances[cls] = cls()
        return instances[cls]

    return getinstance


@singleton
class Dispatcher:
    def __init__(self):
        self.__handles = []

    def attachHandle(self, handle):
        self.__handles.append(handle)

    def detachHandle(self, handle):
        if handle in self.__handles:
            self.__handles.remove(handle)

    def detachAll(self):
        for handle in self.handles():
            handle.detach()

    def handles(self):
        return self.__items

    def broadcastData(self, data):
        for handle in self.__handles:
            handle.onNewData(data)

DISPATCHER = Dispatcher()


class AbstractHandle(QObject):
    def __init__(self):
        QObject.__init__(self)
        self.__timer = QTimer(self)
        self.__timer.setSingleShot(True)
        self.__timer.timeout.connect(self.onTimeout)
        self.__timeout = None

    def attach(self):
        Dispatcher().attachHandle(self)
        if self.__timeout:
            self.__timer.setInterval(self.__timeout)
            self.__timer.start()

    def detach(self):
        # self.__timeout = None
        self.__timer.stop()
        Dispatcher().detachHandle(self)

    @abstractmethod
    def onNewData(self, data):
        pass

    @abstractmethod
    def onTimeout(self):
        self.detach()
        code = 1
        description = "Timeout %ss expired." % self.timeout
        error = (code, description)
        self.onError(error)

    @abstractmethod
    def onError(self, error):
        raise RuntimeError(error)
        # print "Error happened: ", error

    @property
    def timeout(self):
        return self.__timeout

    @timeout.setter
    def timeout(self, timeout):
        self.__timeout = timeout


class AbstractDeferredAction(QObject):
    def __init__(self, parent):
        QObject.__init__(self)
        self.__parent = parent
        self.__timer = QTimer(self)
        self.__timer.setSingleShot(True)

    def defer(self, timeout):
        print "Defer started"
        if self.__timer.isActive():
            self.__timer.stop()

        self.__timer.start(timeout)

    def cancel(self):
        self.__timer.stop()

    @abstractmethod
    def onTimeout(self):
        pass