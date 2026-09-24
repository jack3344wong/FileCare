"""
系统托盘管理模块
负责创建和管理系统托盘图标、菜单和交互
"""

from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction, QApplication
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import pyqtSignal, QObject
import os


class TrayManager(QObject):
    """系统托盘管理器"""
    
    # 信号
    show_window_requested = pyqtSignal()  # 请求显示主窗口
    hide_window_requested = pyqtSignal()  # 请求隐藏主窗口
    quit_requested = pyqtSignal()  # 请求退出程序
    scan_requested = pyqtSignal(str)  # 请求扫描（参数：扫描类型）
    settings_requested = pyqtSignal()  # 请求打开设置
    update_requested = pyqtSignal()  # 请求检查更新
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tray_icon = None
        self.tray_menu = None
        self._visible = False  # 主窗口是否可见
        
    def setup(self, icon_path, window_title="文件管家"):
        """
        初始化系统托盘
        
        Args:
            icon_path: 图标文件路径
            window_title: 窗口标题（用于托盘提示）
        """
        # 检查是否支持系统托盘
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("警告：系统不支持系统托盘")
            return False
            
        # 创建托盘图标
        self.tray_icon = QSystemTrayIcon(self.parent())
        
        # 设置图标
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            self.tray_icon.setIcon(icon)
            QApplication.setWindowIcon(icon)
        else:
            print(f"警告：图标文件不存在 {icon_path}")
            
        # 设置提示文本
        self.tray_icon.setToolTip(window_title)
        
        # 创建托盘菜单
        self._create_tray_menu()
        
        # 连接信号
        self.tray_icon.activated.connect(self._on_tray_activated)
        
        return True
        
    def _create_tray_menu(self):
        """创建托盘右键菜单"""
        self.tray_menu = QMenu()
        
        # 打开主界面
        action_show = QAction("打开主界面", self)
        action_show.triggered.connect(self._on_show_window)
        self.tray_menu.addAction(action_show)
        
        self.tray_menu.addSeparator()
        
        # 快速扫描（子菜单）
        scan_menu = self.tray_menu.addMenu("快速扫描")
        
        action_scan_all = QAction("扫描全盘", self)
        action_scan_all.triggered.connect(lambda: self.scan_requested.emit("all"))
        scan_menu.addAction(action_scan_all)
        
        action_scan_user = QAction("扫描用户目录", self)
        action_scan_user.triggered.connect(lambda: self.scan_requested.emit("user"))
        scan_menu.addAction(action_scan_user)
        
        self.tray_menu.addSeparator()
        
        # 设置
        action_settings = QAction("设置", self)
        action_settings.triggered.connect(self._on_settings)
        self.tray_menu.addAction(action_settings)
        
        # 检查更新
        action_update = QAction("检查更新", self)
        action_update.triggered.connect(self.update_requested.emit)
        self.tray_menu.addAction(action_update)
        
        self.tray_menu.addSeparator()
        
        # 退出
        action_quit = QAction("退出", self)
        action_quit.triggered.connect(self._on_quit)
        self.tray_menu.addAction(action_quit)
        
        # 设置菜单
        self.tray_icon.setContextMenu(self.tray_menu)
        
    def _on_tray_activated(self, reason):
        """托盘图标被激活"""
        if reason == QSystemTrayIcon.Trigger:  # 左键单击
            self._on_show_window()
            
    def _on_show_window(self):
        """显示主窗口"""
        self.show_window_requested.emit()
        
    def _on_settings(self):
        """打开设置"""
        self.settings_requested.emit()
        
    def _on_quit(self):
        """退出程序"""
        self.quit_requested.emit()
        
    def show(self):
        """显示托盘图标"""
        if self.tray_icon:
            self.tray_icon.show()
            self._visible = True
            
    def hide(self):
        """隐藏托盘图标"""
        if self.tray_icon:
            self.tray_icon.hide()
            self._visible = False
            
    def show_message(self, title, message, icon=QSystemTrayIcon.Information, duration=5000):
        """
        显示托盘消息气泡
        
        Args:
            title: 消息标题
            message: 消息内容
            icon: 图标类型（Information/Warning/Critical）
            duration: 显示时长（毫秒）
        """
        if self.tray_icon and self.tray_icon.isVisible():
            self.tray_icon.showMessage(title, message, icon, duration)
            
    def update_tooltip(self, text):
        """更新托盘提示文本"""
        if self.tray_icon:
            self.tray_icon.setToolTip(text)
            
    def is_visible(self):
        """托盘图标是否可见"""
        return self._visible

    def is_available(self):
        """系统托盘是否已成功初始化。"""
        return self.tray_icon is not None
        
    def cleanup(self):
        """清理资源"""
        if self.tray_icon:
            self.tray_icon.hide()
            self.tray_icon.deleteLater()
            self.tray_icon = None
        self._visible = False
