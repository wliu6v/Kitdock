import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication
    from photo_organizer.gui import Window, Worker
except ImportError:
    QApplication = None

from photo_organizer.core import Options, Result


@unittest.skipIf(QApplication is None, "Install the gui extra to run GUI tests")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.a = self.root / "iPhone"
        self.b = self.root / "安卓"
        self.a.mkdir()
        self.b.mkdir()
        self.window = Window()
        self.addCleanup(self.window.close)

    def test_drop_multiple_directories(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in (self.a, self.b)])
        event = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.window.sources.dropEvent(event)
        self.assertEqual(self.window.sources.count(), 2)
        self.assertEqual(Path(self.window.output_path.text()), self.root / "iPhone_整理")

    def test_name_and_full_path_editing(self):
        self.window.add_directories([str(self.a)])
        self.window.output_path.setText(str(self.root / "elsewhere" / "custom"))
        self.window.path_edited(self.window.output_path.text())
        self.assertEqual(self.window.output_name.text(), "custom")
        self.window.name_edited("旅行照片")
        self.assertEqual(Path(self.window.output_path.text()), self.root / "旅行照片")
        self.window.reset_output()
        self.assertEqual(Path(self.window.output_path.text()), self.root / "iPhone_整理")
        self.window.name_edited("../bad")
        self.assertEqual(self.window.output_path.text(), "")

    def test_worker_result_and_failure(self):
        worker = Worker(Options((self.a,)))
        results, errors = [], []
        worker.completed.connect(results.append)
        worker.failed.connect(errors.append)
        with patch("photo_organizer.gui.organize", return_value=Result(self.root / "out")):
            worker.run()
        self.assertEqual(len(results), 1)
        with patch("photo_organizer.gui.organize", side_effect=ValueError("bad")):
            worker.run()
        self.assertEqual(errors, ["bad"])
