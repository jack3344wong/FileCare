# -*- coding: utf-8 -*-
"""检查更新相关界面：发现新版本提示框、下载进度框、后台工作线程。

界面层不直接做网络操作，全部交给 updater 模块，
这样「设置页手动检查」和「启动时自动检查」可以共用同一套流程。
"""
from __future__ import annotations

import time

from PyQt5.QtCore import QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel,
                             QMessageBox, QProgressBar, QPushButton,
                             QTextBrowser, QVBoxLayout)

import updater
from updater import UpdateError, is_installed_build
from version import APP_NAME_ZH, APP_VERSION

# 与 main_window 的 Minimalism 配色保持一致（不直接 import 以免循环依赖）
C_TEXT = "#2c3e50"
C_TEXT_2 = "#8e99a4"
C_TEXT_3 = "#a0aab4"
C_ACCENT = "#4a90d9"
C_BORDER = "#eef0f3"
C_CARD = "#ffffff"
C_RED = "#e74c3c"


def _font_rules() -> str:
    """对话框局部样式。

    用 %(name)s 而不是 str.format：QSS 里全是花括号，
    format 会把 CSS 块当成占位符，一漏转义就 KeyError。
    """
    return (
        "QLabel#updTitle { font-size:16px; font-weight:600; color:%(text)s; }"
        "QLabel#updMuted { font-size:12px; color:%(muted)s; }"
        "QLabel#updVersion { font-size:14px; color:%(text)s; }"
        "QLabel#updVersionNew { font-size:14px; font-weight:600; color:%(accent)s; }"
        "QTextBrowser#updNotes { background:%(card)s; border:1px solid %(border)s;"
        " border-radius:8px; padding:8px; font-size:12px; color:%(text)s; }"
        "QLabel#updBig { font-size:20px; font-weight:600; color:%(accent)s; }"
    ) % {
        "text": C_TEXT, "muted": C_TEXT_2, "accent": C_ACCENT,
        "border": C_BORDER, "card": C_CARD,
    }


# ---------------------------------------------------------------- 后台线程

class UpdateCheckWorker(QThread):
    """后台检查更新，避免网络请求冻结界面。"""

    finished_ok = pyqtSignal(object)   # UpdateInfo；None 表示已是最新
    failed = pyqtSignal(str)

    def __init__(self, current_version: str = APP_VERSION, parent=None):
        super().__init__(parent)
        self._current_version = current_version

    def run(self):
        try:
            info = updater.check_for_update(self._current_version)
        except UpdateError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:      # noqa: BLE001 - 线程里绝不能抛异常
            self.failed.emit("检查更新失败：{0}".format(exc))
            return
        self.finished_ok.emit(info)


class DownloadWorker(QThread):
    """后台下载安装包，支持取消。"""

    progress = pyqtSignal(int, int)    # 已下载字节, 总字节（0 表示未知）
    finished_ok = pyqtSignal(str)      # 本地安装包路径
    failed = pyqtSignal(str)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self._info = info
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            path = updater.download_installer(
                self._info,
                progress=lambda done, total: self.progress.emit(done, total),
                should_cancel=lambda: self._cancelled,
            )
        except UpdateError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:      # noqa: BLE001
            self.failed.emit("下载失败：{0}".format(exc))
            return
        self.finished_ok.emit(str(path))


# ---------------------------------------------------------------- 提示对话框

class UpdateAvailableDialog(QDialog):
    """发现新版本：展示版本号、更新说明与安装包大小。"""

    RUN_UPDATE = 1
    OPEN_PAGE = 2
    LATER = 0

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle("发现新版本")
        self.setModal(True)
        self.setMinimumWidth(540)
        self.setStyleSheet(_font_rules())

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("发现新版本")
        title.setObjectName("updTitle")
        root.addWidget(title)

        versions = QHBoxLayout()
        versions.setSpacing(10)
        current = QLabel("当前版本 {0}".format(APP_VERSION))
        current.setObjectName("updVersion")
        arrow = QLabel("→")
        arrow.setObjectName("updMuted")
        newest = QLabel("最新版本 {0}".format(info.version))
        newest.setObjectName("updVersionNew")
        versions.addWidget(current)
        versions.addWidget(arrow)
        versions.addWidget(newest)
        versions.addStretch(1)
        root.addLayout(versions)

        size_row = QHBoxLayout()
        size_row.setSpacing(10)
        if info.has_installer:
            size_text = "安装包大小 {0}".format(info.size_display)
        else:
            size_text = "该版本没有附带安装包，请到发布页手动下载"
        size_label = QLabel(size_text)
        size_label.setObjectName("updMuted")
        size_row.addWidget(size_label)
        size_row.addStretch(1)
        if info.published_at:
            date_label = QLabel("发布于 {0}".format(info.published_at[:10]))
            date_label.setObjectName("updMuted")
            size_row.addWidget(date_label)
        root.addLayout(size_row)

        notes_title = QLabel("更新说明")
        notes_title.setObjectName("updMuted")
        root.addWidget(notes_title)

        self._notes = QTextBrowser()
        self._notes.setObjectName("updNotes")
        self._notes.setOpenExternalLinks(True)
        self._notes.setMinimumHeight(150)
        self._notes.setMaximumHeight(210)
        text = info.notes or "（该版本没有填写更新说明）"
        try:
            self._notes.setMarkdown(text)
        except AttributeError:            # 老版本 Qt 没有 setMarkdown
            self._notes.setPlainText(text)
        root.addWidget(self._notes)

        url_row = QLabel(info.page_url)
        url_row.setObjectName("updMuted")
        url_row.setTextInteractionFlags(url_row.textInteractionFlags()
                                        | 1)   # 允许选中复制
        url_row.setWordWrap(True)
        root.addWidget(url_row)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)

        later = QPushButton("稍后再说")
        later.clicked.connect(lambda: self.done(self.LATER))
        buttons.addWidget(later)

        page = QPushButton("打开发布页")
        page.clicked.connect(lambda: self.done(self.OPEN_PAGE))
        buttons.addWidget(page)

        if info.has_installer:
            run = QPushButton("立即更新")
            run.setObjectName("primary")
            run.setDefault(True)
            run.clicked.connect(lambda: self.done(self.RUN_UPDATE))
            buttons.addWidget(run)
        root.addLayout(buttons)


class UpdateProgressDialog(QDialog):
    """下载安装包进度框。下载完成后 downloaded_path 保存本地路径。"""

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.downloaded_path = ""
        self._cancelled = False
        self._start_time = time.time()

        self.setWindowTitle("正在下载更新")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setStyleSheet(_font_rules())

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)

        title = QLabel("正在下载 {0} {1}".format(APP_NAME_ZH, info.version))
        title.setObjectName("updTitle")
        root.addWidget(title)

        self._status = QLabel("正在连接 GitHub ...")
        self._status.setObjectName("updMuted")
        root.addWidget(self._status)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(10)
        root.addWidget(self._bar)

        root.addWidget(self._make_separator())

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self._on_cancel)
        buttons.addWidget(self._cancel_btn)
        root.addLayout(buttons)

        self.worker = DownloadWorker(info, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _make_separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:{0}; background:{0}; max-height:1px;".format(C_BORDER))
        return line

    # ------------------------------------------------------------ 事件
    def _on_progress(self, done: int, total: int):
        if total > 0:
            percent = int(done * 100 / total)
            self._bar.setRange(0, 100)
            self._bar.setValue(min(100, max(0, percent)))
            speed = self._speed_text(done)
            self._status.setText("已下载 {0} / {1}（{2}%）{3}".format(
                updater.format_size(done), updater.format_size(total),
                percent, speed))
        else:
            # 总大小未知时退化为来回滚动，避免进度条卡在 0%
            self._bar.setRange(0, 0)
            self._status.setText("已下载 {0}（总大小未知）{1}".format(
                updater.format_size(done), self._speed_text(done)))

    def _speed_text(self, done: int) -> str:
        elapsed = time.time() - self._start_time
        if elapsed < 1.0 or done <= 0:
            return ""
        speed = done / elapsed
        if speed <= 0:
            return ""
        return "· {0}/s".format(updater.format_size(speed))

    def _on_finished(self, path: str):
        self.downloaded_path = path
        self._bar.setRange(0, 100)
        self._bar.setValue(100)
        self._status.setText("下载完成，正在启动安装程序 ...")
        self.accept()

    def _on_failed(self, message: str):
        if self._cancelled:
            self.reject()
            return
        self._status.setText("下载失败")
        QMessageBox.warning(self, "下载失败", message)
        self.reject()

    def _on_cancel(self):
        self._cancelled = True
        self._cancel_btn.setEnabled(False)
        self._status.setText("正在取消 ...")
        self.worker.cancel()

    def closeEvent(self, event):
        if self.worker.isRunning():
            self._cancelled = True
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)

    def reject(self):
        if self.worker.isRunning():
            self._cancelled = True
            self.worker.cancel()
            self.worker.wait(3000)
        super().reject()


# ---------------------------------------------------------------- 流程编排

def _resolve_parent(parent):
    if parent is not None:
        return parent
    return QApplication.activeWindow()


def _prepare_to_quit(parent) -> None:
    """让主窗口走"真正退出"的路径（而不是最小化到托盘），再结束程序。"""
    window = None
    if parent is not None:
        window = parent.window()
    if window is not None and hasattr(window, "prepare_for_update"):
        window.prepare_for_update()
        return
    app = QApplication.instance()
    if app is not None:
        app.quit()


def download_and_install(parent, info) -> bool:
    """弹进度框下载并启动安装程序。返回是否已成功启动安装。"""
    parent = _resolve_parent(parent)
    dialog = UpdateProgressDialog(info, parent)
    if dialog.exec_() != QDialog.Accepted or not dialog.downloaded_path:
        return False

    # 安装包安装后的运行环境才需要静默安装并退出自身；
    # 源码运行时改为普通安装，让开发者看到安装向导。
    silent = is_installed_build()
    try:
        updater.launch_installer(dialog.downloaded_path, silent=silent)
    except UpdateError as exc:
        QMessageBox.warning(parent, "无法启动安装程序", str(exc))
        return False

    if silent:
        QMessageBox.information(
            parent, "正在安装更新",
            "{0} 将自动关闭，安装程序会在完成后重新打开。\n\n"
            "若安装程序提示需要关闭 {0}，请选择“是”。".format(APP_NAME_ZH))
        _prepare_to_quit(parent)
    else:
        QMessageBox.information(
            parent, "安装程序已启动",
            "安装包已下载到：\n{0}\n\n"
            "请按安装向导完成安装。".format(dialog.downloaded_path))
    return True


def prompt_update(parent, info) -> None:
    """弹出"发现新版本"对话框，由用户决定是否更新。"""
    parent = _resolve_parent(parent)
    dialog = UpdateAvailableDialog(info, parent)
    choice = dialog.exec_()

    if choice == UpdateAvailableDialog.RUN_UPDATE:
        download_and_install(parent, info)
    elif choice == UpdateAvailableDialog.OPEN_PAGE:
        QDesktopServices.openUrl(QUrl(info.page_url))


def check_and_prompt(parent, notify_when_latest: bool = False,
                     show_errors: bool = True, busy_widgets=()) -> UpdateCheckWorker:
    """检查更新并在有新版时提示。返回后台线程（调用方无需额外保存引用）。

    parent：用于归属对话框，通常传设置页或主窗口。
    notify_when_latest：已是最新时是否弹提示（手动检查用 True，自动检查用 False）。
    show_errors：网络失败时是否弹错误框（启动自动检查用 False，静默处理）。
    busy_widgets：检查期间需要禁用的控件（如"检查更新"按钮）。
    """
    parent = _resolve_parent(parent)
    widgets = [w for w in busy_widgets if w is not None]
    for widget in widgets:
        widget.setEnabled(False)

    def restore_widgets():
        for widget in widgets:
            try:
                widget.setEnabled(True)
            except RuntimeError:
                pass      # 控件已随窗口销毁

    worker = UpdateCheckWorker(parent=parent)

    def on_ok(info):
        restore_widgets()
        if info is None:
            if notify_when_latest:
                QMessageBox.information(
                    parent, "检查更新",
                    "当前版本 {0} 已是最新版本。".format(APP_VERSION))
            return
        prompt_update(parent, info)

    def on_failed(message):
        restore_widgets()
        if show_errors:
            QMessageBox.warning(
                parent, "检查更新失败",
                "{0}\n\n稍后可在设置页手动重试，或到发布页手动下载。".format(message))

    worker.finished_ok.connect(on_ok)
    worker.failed.connect(on_failed)
    worker.start()

    if parent is not None:
        # 保持引用，避免线程对象被垃圾回收导致崩溃
        parent._filecare_update_worker = worker
    return worker