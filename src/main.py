# -*- coding: utf-8 -*-
"""文件管家 / FileCare 主程序入口。"""
import os
import sys
from pathlib import Path

import PyQt5


# Qt 5.15.2 在 Windows 上无法正确解析含中文字符的默认插件路径，
# 必须在导入 QtWidgets 之前显式传入真实的 Unicode 路径。
_qt_plugins = Path(PyQt5.__file__).resolve().parent / "Qt5" / "plugins"
if _qt_plugins.is_dir():
    os.environ["QT_PLUGIN_PATH"] = str(_qt_plugins)
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(_qt_plugins / "platforms")

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QIcon
from PyQt5.QtNetwork import QLocalServer, QLocalSocket


APP_NAME_ZH = "文件管家"
APP_ID = "FileCare.FileManager"
LOCAL_SERVER_NAME = "FileCareSingleInstance"


def _notify_existing_instance():
    """通知已运行的实例，让其激活窗口。"""
    socket = QLocalSocket()
    socket.connectToServer(LOCAL_SERVER_NAME)
    if socket.waitForConnected(500):
        socket.write(b"activate")
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return True
    return False


def _start_local_server(app):
    """启动本地服务器，监听来自新实例的激活请求或卸载关闭请求。"""
    from PyQt5.QtWidgets import QApplication as QA
    
    server = QLocalServer()
    QLocalServer.removeServer(LOCAL_SERVER_NAME)
    
    if not server.listen(LOCAL_SERVER_NAME):
        return None
    
    def on_new_connection():
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn.waitForReadyRead(1000):
                data = conn.readAll().data()
                if data == b"activate":
                    # 激活主窗口
                    for widget in QA.topLevelWidgets():
                        if widget.objectName() == "DiskMonitorMainWindow":
                            widget.show()
                            widget.raise_()
                            widget.activateWindow()
                            break
                elif data == b"shutdown":
                    # 优雅关闭（用于卸载前）
                    for widget in QA.topLevelWidgets():
                        if widget.objectName() == "DiskMonitorMainWindow":
                            widget.close()
                            break
                    QA.quit()
            conn.disconnectFromServer()
    
    server.newConnection.connect(on_new_connection)
    return server


def _handle_admin_delete_on_startup():
    """启动时检查是否有待删除的文件（管理员权限模式）"""
    temp_file = Path(os.environ.get('TEMP', '')) / 'filecare_admin_delete.txt'
    if not temp_file.exists():
        return
    
    try:
        with open(temp_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if len(lines) < 2:
                temp_file.unlink(missing_ok=True)
                return
            
            mode = lines[0].strip()
            target_path = lines[1].strip()
        
        # 删除临时文件
        temp_file.unlink(missing_ok=True)
        
        # 检查文件是否存在
        if not os.path.exists(target_path):
            return
        
        # 执行删除操作
        import shutil
        if mode == 'recycle':
            # 移入回收站
            from file_operations import FileOperations
            recycle_bin = Path.home() / ".diskwise" / "recycle_bin"
            file_ops = FileOperations(str(recycle_bin))
            success, message = file_ops.move_to_recycle_bin(target_path)
            if success:
                QMessageBox.information(None, "删除成功", f"已将文件移入回收站:\n{target_path}")
            else:
                QMessageBox.warning(None, "删除失败", message)
        elif mode == 'permanent':
            # 永久删除
            if os.path.isdir(target_path):
                shutil.rmtree(target_path)
            else:
                os.remove(target_path)
            QMessageBox.information(None, "删除成功", f"已永久删除:\n{target_path}")
    except Exception as e:
        QMessageBox.critical(None, "管理员删除失败", f"执行管理员删除操作时出错:\n{e}")
        temp_file.unlink(missing_ok=True)


def main():
    if "--build-name-index" in sys.argv:
        # 安装器以当前登录用户身份运行，索引会正确写入该用户目录。
        from PyQt5.QtCore import QCoreApplication
        from quick_search import build_name_index_sync
        index_app = QCoreApplication.instance() or QCoreApplication(sys.argv)
        budget = None
        if "--index-budget-seconds" in sys.argv:
            try:
                value_index = sys.argv.index("--index-budget-seconds") + 1
                budget = max(1.0, float(sys.argv[value_index]))
            except (ValueError, IndexError):
                return 2
        total, elapsed, errors = build_name_index_sync(
            time_budget_seconds=budget)
        print(f"Indexed {total} entries in {elapsed:.1f}s; errors={len(errors)}")
        return 0 if total > 0 else 2

    # 检查是否以管理员权限启动，并处理待删除文件
    _handle_admin_delete_on_startup()
    
    # 检查是否已有实例在运行
    socket = QLocalSocket()
    socket.connectToServer(LOCAL_SERVER_NAME)
    if socket.waitForConnected(500):
        # 已有实例在运行，通知它激活窗口然后退出
        socket.write(b"activate")
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        sys.exit(0)
    socket.close()
    
    try:
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
            except Exception:
                pass
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME_ZH)
        app.setApplicationDisplayName(APP_NAME_ZH)
        resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        icon_path = resource_root / "assets" / "filecare.ico"
        if icon_path.is_file():
            icon = QIcon(str(icon_path))
            app.setWindowIcon(icon)
        app.setStyle("Fusion")  # 统一跨平台基础样式，QSS 在此基础上叠加

        # 启动本地服务器，监听新实例的激活请求
        server = _start_local_server(app)

        from main_window import DiskMonitor
        window = DiskMonitor()
        window.setObjectName("DiskMonitorMainWindow")
        
        # 读取启动时最小化设置
        from settings import get_settings
        settings = get_settings()
        if settings.get("general", "start_minimized", False):
            window.hide()  # 启动时隐藏窗口
        else:
            window.show()

        if "--smoke-test" in sys.argv:
            # 发布构建自检：验证真实窗口和所有延迟加载的文档解析模块。
            import docx  # noqa: F401
            import openpyxl  # noqa: F401
            import pptx  # noqa: F401
            import pypdf  # noqa: F401
            from PIL import Image  # noqa: F401
            from lxml import etree  # noqa: F401
            from striprtf.striprtf import rtf_to_text  # noqa: F401
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(750, app.quit)
            return app.exec_()
        
        # 显示索引提醒弹窗
        _show_index_reminder(window)
        
        return app.exec_()
    except ImportError as e:
        QMessageBox.critical(None, "启动失败", f"缺少依赖模块:\n{e}\n\n请确保所有代码文件在同一目录下。")
        sys.exit(1)
    except Exception as e:
        QMessageBox.critical(None, "致命错误", f"程序启动失败:\n{str(e)}")
        sys.exit(1)


def _show_index_reminder(parent):
    """显示索引提醒弹窗，提示用户建立索引需要时间。"""
    from PyQt5.QtWidgets import QMessageBox, QCheckBox, QVBoxLayout, QDialog, QLabel, QPushButton
    from PyQt5.QtCore import Qt
    
    # 检查是否已经显示过（用户选择了"不再显示"）
    reminder_file = Path.home() / ".diskwise" / "hide_index_reminder"
    if reminder_file.exists():
        return
    try:
        from quick_search import FileIndexDB
        index_db = FileIndexDB()
        has_index = index_db.get_total_count() > 0
        index_db.close()
        if has_index:
            return
    except Exception:
        pass
    
    dialog = QDialog(parent)
    dialog.setWindowTitle("索引提示")
    dialog.setMinimumWidth(420)
    
    layout = QVBoxLayout(dialog)
    layout.setSpacing(12)
    layout.setContentsMargins(20, 20, 20, 20)
    
    # 标题
    title_label = QLabel("📊 索引构建提示")
    title_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #26384a;")
    layout.addWidget(title_label)
    
    # 内容
    content = QLabel(
        "程序启动后将自动在后台构建文件索引。\n\n"
        "• 首次索引可能需要几分钟到十几分钟\n"
        "• 后续增量更新会快很多\n"
        "• 索引期间可以正常使用其他功能\n"
        "• 索引完成后搜索功能才能正常使用"
    )
    content.setStyleSheet("font-size: 12px; color: #52606d; line-height: 1.5;")
    content.setWordWrap(True)
    layout.addWidget(content)
    
    layout.addStretch()
    
    # 不再显示复选框
    checkbox = QCheckBox("不再显示此提示")
    checkbox.setStyleSheet("font-size: 11px; color: #73808c;")
    layout.addWidget(checkbox)
    
    # 确定按钮
    btn = QPushButton("我知道了")
    btn.setStyleSheet(
        "QPushButton { background: #4a90e2; color: white; border: none; "
        "border-radius: 6px; padding: 8px 20px; font-weight: 600; min-height: 32px; }"
        "QPushButton:hover { background: #357abd; }"
    )
    btn.setCursor(Qt.PointingHandCursor)
    btn.clicked.connect(dialog.accept)
    layout.addWidget(btn, alignment=Qt.AlignRight)
    
    def on_accept():
        if checkbox.isChecked():
            reminder_file.parent.mkdir(parents=True, exist_ok=True)
            reminder_file.touch()
        dialog.accept()
    
    btn.clicked.disconnect()
    btn.clicked.connect(on_accept)
    
    dialog.exec_()


if __name__ == "__main__":
    sys.exit(main() or 0)
