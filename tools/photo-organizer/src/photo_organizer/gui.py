"""Qt desktop front end with cancellable background work."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from .core import Options, default_output, organize, validate


class DirectoryList(QListWidget):
    directories_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setMinimumHeight(110)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.directories_dropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()


class Worker(QThread):
    progress_changed = Signal(object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, options):
        super().__init__()
        self.options = options
        self.cancel = threading.Event()

    def run(self):
        try:
            self.completed.emit(organize(self.options, self.progress_changed.emit, self.cancel))
        except Exception as exc:
            self.failed.emit(str(exc))


class Window(QMainWindow):
    def __init__(self, options: Options | None = None):
        super().__init__()
        options = options or Options(())
        self.worker = None
        self.last_output = None
        self.output_custom = False
        self.default_parent = None
        self.setWindowTitle("照片整理 · Kitdock")
        self.resize(820, 800)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel("把两部手机的回忆，整理到一起")
        title.setStyleSheet("font-size: 22px; font-weight: 600; margin: 8px 0;")
        layout.addWidget(title)
        layout.addWidget(QLabel("复制原文件，不转换格式。支持照片、视频及 AAE / XMP 配套文件。"))
        self.settings = QWidget()
        settings = QVBoxLayout(self.settings)
        settings.setContentsMargins(0, 0, 0, 0)
        settings.addWidget(QLabel("输入目录 · 拖入 iPhone / 安卓目录，或点击添加（第一个为目录 A）"))
        self.sources = DirectoryList()
        self.sources.directories_dropped.connect(self.add_directories)
        settings.addWidget(self.sources)
        row = QHBoxLayout()
        for label, callback in (("添加目录…", self.choose_input), ("移除选中", self.remove_selected)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        row.addStretch()
        settings.addLayout(row)
        form = QFormLayout()
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("选择输入目录后自动填入")
        self.output_path.textEdited.connect(self.path_edited)
        row = QHBoxLayout()
        row.addWidget(self.output_path)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self.choose_output)
        row.addWidget(browse)
        form.addRow("完整导出路径", row)
        row = QHBoxLayout()
        self.output_name = QLineEdit()
        self.output_name.textEdited.connect(self.name_edited)
        row.addWidget(self.output_name)
        reset = QPushButton("恢复默认")
        reset.clicked.connect(self.reset_output)
        row.addWidget(reset)
        form.addRow("仅改目录名", row)
        self.parent_hint = QLabel("保留目录 A 的默认父级路径")
        self.parent_hint.setWordWrap(True)
        form.addRow("", self.parent_hint)
        self.missing_time = QComboBox()
        self.missing_time.addItem("使用文件修改时间，并标注「时间待确认」", "mtime")
        self.missing_time.addItem("跳过，并写入处理报告", "skip")
        self.missing_time.setCurrentIndex(1 if options.missing_time == "skip" else 0)
        form.addRow("拍摄时间缺失", self.missing_time)
        self.utc_offset = QLineEdit(options.utc_offset)
        form.addRow("仅 UTC 视频的时区", self.utc_offset)
        self.exiftool = QLineEdit(options.exiftool)
        form.addRow("ExifTool 程序路径", self.exiftool)
        self.geocode = QCheckBox("联网解析 GPS 地点（将坐标发送给下方服务）")
        self.geocode.setChecked(bool(options.geocode_url))
        form.addRow("地点查询", self.geocode)
        self.geocode_url = QLineEdit(options.geocode_url)
        self.geocode_url.setPlaceholderText("自建或允许批量查询的 Nominatim 兼容 HTTPS /reverse 地址")
        self.geocode_url.setEnabled(self.geocode.isChecked())
        self.geocode.toggled.connect(self.geocode_url.setEnabled)
        form.addRow("查询服务地址", self.geocode_url)
        settings.addLayout(form)
        layout.addWidget(self.settings)
        row = QHBoxLayout()
        self.preview = QPushButton("预览命名")
        self.preview.clicked.connect(lambda: self.start(True))
        self.start_button = QPushButton("开始整理")
        self.start_button.clicked.connect(lambda: self.start(False))
        self.stop = QPushButton("取消")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel_run)
        self.open_output = QPushButton("打开导出目录")
        self.open_output.setEnabled(False)
        self.open_output.clicked.connect(self.show_output)
        for button in (self.preview, self.start_button, self.stop, self.open_output):
            row.addWidget(button)
        layout.addLayout(row)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.status = QLabel("准备就绪 · 默认离线读取文件内的地点文字")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        layout.addWidget(self.log, 1)
        layout.addWidget(QLabel("后续计划：HEIC 转 JPG · JPG 压缩。当前版本保留原文件内容。"))
        self.add_directories([str(p) for p in options.inputs])
        if options.output:
            self.output_custom = True
            self.set_output(options.output.expanduser().resolve())

    def set_output(self, path):
        self.output_path.setText(str(path))
        self.output_name.setText(path.name)

    def refresh_default(self):
        if self.sources.count():
            default = default_output(Path(self.sources.item(0).text()))
            self.default_parent = default.parent
            self.parent_hint.setText(f"仅改目录名时使用父级：{default.parent}")
            if not self.output_custom:
                self.set_output(default)

    def add_directories(self, directories):
        invalid = []
        for directory in directories:
            path = Path(directory).expanduser().resolve()
            if not path.is_dir():
                invalid.append(str(path))
            elif str(path) not in [self.sources.item(i).text() for i in range(self.sources.count())]:
                self.sources.addItem(str(path))
        self.refresh_default()
        if invalid:
            QMessageBox.warning(self, "需要目录", "以下项目不是目录：\n" + "\n".join(invalid))

    def choose_input(self):
        directory = QFileDialog.getExistingDirectory(self, "选择照片输入目录")
        if directory:
            self.add_directories([directory])

    def remove_selected(self):
        for item in self.sources.selectedItems():
            self.sources.takeItem(self.sources.row(item))
        self.refresh_default()

    def choose_output(self):
        directory = QFileDialog.getExistingDirectory(self, "选择导出目录", self.output_path.text())
        if directory:
            self.output_custom = True
            self.set_output(Path(directory))

    def reset_output(self):
        self.output_custom = False
        self.refresh_default()

    def path_edited(self, text):
        self.output_custom = True
        self.output_name.setText(Path(text).name)

    def name_edited(self, text):
        self.output_custom = True
        if self.default_parent and text and text not in {".", ".."} and not any(c in text for c in '/\\<>:"|?*'):
            self.output_path.setText(str(self.default_parent / text))
        else:
            self.output_path.clear()

    def start(self, dry_run):
        if self.worker is not None:
            return
        try:
            if not self.output_path.text().strip():
                raise ValueError("请填写有效的导出路径或目录名")
            if self.geocode.isChecked() and not self.geocode_url.text().strip():
                raise ValueError("请填写允许批量查询的服务地址，或关闭联网查询")
            options = Options(
                tuple(Path(self.sources.item(i).text()) for i in range(self.sources.count())),
                Path(self.output_path.text().strip()), dry_run, self.missing_time.currentData(),
                self.exiftool.text().strip(), self.utc_offset.text().strip(),
                self.geocode_url.text().strip() if self.geocode.isChecked() else "")
            validate(options)
        except ValueError as exc:
            QMessageBox.warning(self, "检查设置", str(exc))
            return
        self.log.clear()
        self.set_running(True)
        self.last_output = None
        self.open_output.setEnabled(False)
        self.worker = Worker(options)
        self.worker.progress_changed.connect(self.update_progress)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def set_running(self, running):
        self.settings.setEnabled(not running)
        self.preview.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.stop.setEnabled(running)

    def update_progress(self, event):
        phase = {"scan": "扫描目录", "metadata": "读取信息", "copy": "整理文件", "done": "处理结束"}[event.phase]
        self.progress.setRange(0, event.total if event.total else (1 if event.phase == "done" else 0))
        self.progress.setValue(event.done)
        self.status.setText(f"{phase} · {event.done} / {event.total or '…'}\n{event.message}")
        if event.phase == "copy":
            self.log.appendPlainText(event.message)

    def completed(self, result):
        self.last_output = result.output
        self.open_output.setEnabled(result.output.is_dir())
        summary = (f"{'已取消' if result.cancelled else '处理完成'}：复制 {result.copied}，预览 {result.planned}，"
                   f"相同或跳过 {result.skipped}，失败 {result.errors}，忽略非媒体文件 {result.ignored}")
        self.status.setText(summary)
        for row in result.records:
            if row.get("status") in {"error", "skipped"} or row.get("warnings"):
                self.log.appendPlainText(f"{row['source']}: {row.get('reason') or '; '.join(row.get('warnings', []))}")
        if result.report:
            self.log.appendPlainText(f"完整报告：{result.report}")
        if result.errors:
            QMessageBox.warning(self, "部分文件处理失败", summary + "\n详情见日志和报告，源文件保留。")

    def failed(self, message):
        self.status.setText("处理失败，源文件保留")
        self.log.appendPlainText(message)
        QMessageBox.warning(self, "处理失败", message)

    def worker_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.set_running(False)

    def cancel_run(self):
        if self.worker:
            self.worker.cancel.set()
            self.stop.setEnabled(False)
            self.status.setText("正在取消… 等待当前元数据读取或网络请求结束")

    def show_output(self):
        if self.last_output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output)))

    def closeEvent(self, event):
        if self.worker is not None:
            self.cancel_run()
            event.ignore()
        else:
            event.accept()


def main(options: Options | None = None) -> int:
    app = QApplication.instance() or QApplication([sys.argv[0]])
    window = Window(options)
    window.show()
    return app.exec()
