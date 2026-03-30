from PyQt6.QtCore import QObject, pyqtSignal

class HotkeySignal(QObject):
    triggered = pyqtSignal()

class AISignal(QObject):
    responded   = pyqtSignal(str)
    chunk       = pyqtSignal(str)
    stream_done = pyqtSignal()

class FileSignal(QObject):
    results = pyqtSignal(list)

class InfoSignal(QObject):
    info = pyqtSignal(str)

class GitLabSignal(QObject):
    data = pyqtSignal(list)

class BranchResultSignal(QObject):
    result = pyqtSignal(str, object)  # url, list[str] | str
