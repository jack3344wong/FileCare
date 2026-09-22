# -*- coding: utf-8 -*-
"""设置页面 UI"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from settings import Settings


class SettingsPage(QWidget):
    """设置页面"""
    
    # 信号
    settings_saved = QtCore.pyqtSignal()  # 设置保存后发出
    settings_closed = QtCore.pyqtSignal()  # 设置关闭后发出
    
    def __init__(self, settings: Settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings = settings
        self._init_ui()
        self._load_settings()
    
    def _init_ui(self):
        """初始化界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 标题栏
        header = self._create_header()
        main_layout.addWidget(header)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #e0e0e0; max-height: 1px;")
        self._line = line
        main_layout.addWidget(line)
        
        # 内容区：左侧导航 + 右侧设置项
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 右侧内容区（必须先创建，因为导航列表的 setCurrentRow(0) 会同步触发回调）
        self._content_stack = QStackedWidget()
        self._create_settings_pages()
        
        # 左侧导航
        self._nav_list = self._create_nav_list()
        content_layout.addWidget(self._nav_list, 0)
        content_layout.addWidget(self._content_stack, 1)
        
        main_layout.addLayout(content_layout, 1)
        
        # 底部按钮区
        button_bar = self._create_button_bar()
        main_layout.addWidget(button_bar)
    
    def _create_header(self) -> QWidget:
        """创建标题栏"""
        header = QWidget()
        header.setFixedHeight(60)
        header.setStyleSheet("background-color: #ffffff;")
        self._header = header
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)
        
        title = QLabel("⚙️ 设置")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #333;")
        self._title = title
        layout.addWidget(title)
        
        layout.addStretch()
        
        return header
    
    def _create_nav_list(self) -> QListWidget:
        """创建左侧导航列表"""
        nav = QListWidget()
        nav.setFixedWidth(180)
        nav.setStyleSheet("""
            QListWidget {
                background-color: #f5f5f5;
                border: none;
                border-right: 1px solid #e0e0e0;
                padding: 12px 0;
            }
            QListWidget::item {
                padding: 12px 20px;
                border: none;
                color: #666;
                font-size: 14px;
            }
            QListWidget::item:selected {
                background-color: #e8f5e9;
                color: #2e7d32;
                font-weight: 500;
                border-left: 3px solid #4caf50;
            }
            QListWidget::item:hover:!selected {
                background-color: #eeeeee;
            }
        """)
        
        # 添加导航项
        nav_items = [
            ("🔧 常规设置", 0),
            ("🔍 扫描与索引", 1),
            ("🧹 清理设置", 2),
            ("⚡ 高级设置", 3),
        ]
        
        for text, index in nav_items:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, index)
            nav.addItem(item)
        
        nav.currentRowChanged.connect(self._on_nav_changed)
        nav.setCurrentRow(0)
        self._nav_list = nav
        
        return nav
    
    def _create_settings_pages(self):
        """创建各设置页面"""
        # 常规设置
        general_page = self._create_general_page()
        self._content_stack.addWidget(general_page)
        
        # 扫描与索引设置
        scan_page = self._create_scan_page()
        self._content_stack.addWidget(scan_page)
        
        # 清理设置
        cleanup_page = self._create_cleanup_page()
        self._content_stack.addWidget(cleanup_page)
        
        # 高级设置
        advanced_page = self._create_advanced_page()
        self._content_stack.addWidget(advanced_page)
    
    def _create_general_page(self) -> QWidget:
        """创建常规设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(20)
        
        # 启动行为
        startup_group = QGroupBox("启动行为")
        startup_layout = QVBoxLayout(startup_group)
        
        self._auto_start_check = QCheckBox("开机时自动启动")
        self._auto_start_check.setToolTip("系统启动时自动运行文件管家")
        startup_layout.addWidget(self._auto_start_check)
        
        self._start_minimized_check = QCheckBox("启动时最小化到系统托盘")
        self._start_minimized_check.setToolTip("启动后不显示主窗口，直接在托盘运行")
        startup_layout.addWidget(self._start_minimized_check)
        
        self._auto_scan_check = QCheckBox("启动时自动扫描索引")
        self._auto_scan_check.setToolTip("启动后自动开始构建文件索引")
        startup_layout.addWidget(self._auto_scan_check)
        
        layout.addWidget(startup_group)
        layout.addStretch()
        
        return page
    
    def _create_scan_page(self) -> QWidget:
        """创建扫描与索引设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(20)
        
        # 索引存储路径
        path_group = QGroupBox("索引存储")
        path_layout = QGridLayout(path_group)
        
        path_layout.addWidget(QLabel("索引数据库路径："), 0, 0)
        self._index_path_edit = QLineEdit()
        self._index_path_edit.setPlaceholderText("默认：~/.diskwise/")
        self._index_path_edit.setToolTip("索引数据库文件的存储位置")
        path_layout.addWidget(self._index_path_edit, 0, 1)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_index_path)
        path_layout.addWidget(browse_btn, 0, 2)
        
        layout.addWidget(path_group)
        
        # 自动扫描间隔
        interval_group = QGroupBox("自动扫描")
        interval_layout = QHBoxLayout(interval_group)
        
        interval_layout.addWidget(QLabel("自动扫描间隔："))
        self._scan_interval_combo = QComboBox()
        self._scan_interval_combo.addItem("关闭", "off")
        self._scan_interval_combo.addItem("每天", "daily")
        self._scan_interval_combo.addItem("每周", "weekly")
        self._scan_interval_combo.addItem("每月", "monthly")
        interval_layout.addWidget(self._scan_interval_combo)
        interval_layout.addStretch()
        
        layout.addWidget(interval_group)
        
        # 排除目录
        exclude_dir_group = QGroupBox("排除目录")
        exclude_dir_layout = QVBoxLayout(exclude_dir_group)
        
        self._exclude_dir_list = QListWidget()
        self._exclude_dir_list.setMaximumHeight(120)
        exclude_dir_layout.addWidget(self._exclude_dir_list)
        
        exclude_dir_btn_layout = QHBoxLayout()
        add_dir_btn = QPushButton("添加目录")
        add_dir_btn.clicked.connect(self._add_exclude_dir)
        exclude_dir_btn_layout.addWidget(add_dir_btn)
        
        remove_dir_btn = QPushButton("移除选中")
        remove_dir_btn.clicked.connect(self._remove_exclude_dir)
        exclude_dir_btn_layout.addWidget(remove_dir_btn)
        
        exclude_dir_btn_layout.addStretch()
        exclude_dir_layout.addLayout(exclude_dir_btn_layout)
        
        layout.addWidget(exclude_dir_group)
        
        # 排除文件类型
        exclude_pattern_group = QGroupBox("排除文件类型")
        exclude_pattern_layout = QVBoxLayout(exclude_pattern_group)
        
        hint_label = QLabel("使用通配符格式，如 *.tmp, *.log")
        hint_label.setStyleSheet("color: #999; font-size: 12px;")
        if not hasattr(self, "_hint_labels"):
            self._hint_labels = []
        self._hint_labels.append(hint_label)
        exclude_pattern_layout.addWidget(hint_label)
        
        self._exclude_pattern_edit = QLineEdit()
        self._exclude_pattern_edit.setPlaceholderText("多个模式用逗号分隔，如：*.tmp, *.log, *.bak")
        exclude_pattern_layout.addWidget(self._exclude_pattern_edit)
        
        layout.addWidget(exclude_pattern_group)
        layout.addStretch()
        
        return page
    
    def _create_cleanup_page(self) -> QWidget:
        """创建清理设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(20)
        
        # 删除行为
        delete_group = QGroupBox("删除行为")
        delete_layout = QVBoxLayout(delete_group)
        
        self._confirm_delete_check = QCheckBox("删除文件前先确认")
        self._confirm_delete_check.setToolTip("删除文件前弹出确认对话框")
        delete_layout.addWidget(self._confirm_delete_check)
        
        self._use_recycle_check = QCheckBox("使用系统回收站")
        self._use_recycle_check.setToolTip("删除文件时移至回收站而非直接删除")
        delete_layout.addWidget(self._use_recycle_check)
        
        layout.addWidget(delete_group)
        
        # 大文件阈值
        threshold_group = QGroupBox("大文件/文件夹阈值")
        threshold_layout = QGridLayout(threshold_group)
        
        threshold_layout.addWidget(QLabel("大文件阈值："), 0, 0)
        self._large_file_spin = QSpinBox()
        self._large_file_spin.setRange(10, 10000)
        self._large_file_spin.setSuffix(" MB")
        self._large_file_spin.setToolTip("超过此大小的文件视为大文件")
        threshold_layout.addWidget(self._large_file_spin, 0, 1)
        
        threshold_layout.addWidget(QLabel("大文件夹阈值："), 1, 0)
        self._large_folder_spin = QSpinBox()
        self._large_folder_spin.setRange(100, 100000)
        self._large_folder_spin.setSuffix(" MB")
        self._large_folder_spin.setToolTip("超过此大小的文件夹视为大文件夹")
        threshold_layout.addWidget(self._large_folder_spin, 1, 1)
        
        layout.addWidget(threshold_group)
        layout.addStretch()
        
        return page
    
    def _create_advanced_page(self) -> QWidget:
        """创建高级设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(20)
        
        # 更新设置
        update_group = QGroupBox("软件更新")
        update_layout = QGridLayout(update_group)
        
        update_layout.addWidget(QLabel("检查更新："), 0, 0)
        self._check_update_combo = QComboBox()
        self._check_update_combo.addItem("自动检查", "auto")
        self._check_update_combo.addItem("手动检查", "manual")
        self._check_update_combo.addItem("关闭", "off")
        update_layout.addWidget(self._check_update_combo, 0, 1)
        
        update_layout.addWidget(QLabel("更新服务器："), 1, 0)
        self._update_server_edit = QLineEdit()
        self._update_server_edit.setPlaceholderText("https://filecare.cn/api/version/latest")
        update_layout.addWidget(self._update_server_edit, 1, 1)
        
        layout.addWidget(update_group)
        
        # 日志设置
        log_group = QGroupBox("日志")
        log_layout = QHBoxLayout(log_group)
        
        log_layout.addWidget(QLabel("日志级别："))
        self._log_level_combo = QComboBox()
        self._log_level_combo.addItem("错误", "error")
        self._log_level_combo.addItem("警告", "warning")
        self._log_level_combo.addItem("信息", "info")
        self._log_level_combo.addItem("调试", "debug")
        log_layout.addWidget(self._log_level_combo)
        log_layout.addStretch()
        
        layout.addWidget(log_group)
        
        # 配置管理
        config_group = QGroupBox("配置管理")
        config_layout = QVBoxLayout(config_group)
        
        btn_layout = QHBoxLayout()
        
        export_btn = QPushButton("导出配置")
        export_btn.clicked.connect(self._export_config)
        btn_layout.addWidget(export_btn)
        
        import_btn = QPushButton("导入配置")
        import_btn.clicked.connect(self._import_config)
        btn_layout.addWidget(import_btn)
        
        btn_layout.addStretch()
        config_layout.addLayout(btn_layout)
        
        # 配置文件路径
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("配置文件位置："))
        path_label = QLabel(str(self._settings.get_config_path()))
        path_label.setStyleSheet("color: #666; font-size: 12px;")
        if not hasattr(self, "_hint_labels"):
            self._hint_labels = []
        self._hint_labels.append(path_label)
        path_label.setWordWrap(True)
        path_layout.addWidget(path_label, 1)
        config_layout.addLayout(path_layout)
        
        layout.addWidget(config_group)
        layout.addStretch()
        
        return page
    
    def _create_button_bar(self) -> QWidget:
        """创建底部按钮栏"""
        bar = QWidget()
        bar.setFixedHeight(70)
        bar.setStyleSheet("background-color: #fafafa; border-top: 1px solid #e0e0e0;")
        self._button_bar = bar
        
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 0, 24, 0)
        
        # 左侧：恢复默认按钮
        reset_btn = QPushButton("恢复默认")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #fff;
                border: 1px solid #ddd;
                color: #666;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #f5f5f5;
                border-color: #ccc;
            }
        """)
        reset_btn.clicked.connect(self._reset_to_default)
        self._reset_btn = reset_btn
        layout.addWidget(reset_btn)
        
        layout.addStretch()
        
        # 右侧：取消和保存按钮
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #fff;
                border: 1px solid #ddd;
                color: #666;
                padding: 8px 20px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #f5f5f5;
            }
        """)
        cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn = cancel_btn
        layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                border: none;
                color: white;
                padding: 8px 24px;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        save_btn.clicked.connect(self._on_save)
        self._save_btn = save_btn
        layout.addWidget(save_btn)
        
        return bar
    
    def _on_nav_changed(self, index: int):
        """导航切换"""
        if 0 <= index < self._content_stack.count():
            self._content_stack.setCurrentIndex(index)
    
    def _load_settings(self):
        """从配置加载到界面"""
        # 常规设置
        self._auto_start_check.setChecked(self._settings.get("general", "auto_start", False))
        self._start_minimized_check.setChecked(self._settings.get("general", "start_minimized", False))
        self._auto_scan_check.setChecked(self._settings.get("general", "auto_scan_on_start", False))
        
        # 扫描与索引设置
        self._index_path_edit.setText(self._settings.get("scan", "index_db_path", ""))
        
        interval = self._settings.get("scan", "auto_scan_interval", "off")
        interval_index = self._scan_interval_combo.findData(interval)
        if interval_index >= 0:
            self._scan_interval_combo.setCurrentIndex(interval_index)
        
        # 排除目录
        self._exclude_dir_list.clear()
        exclude_dirs = self._settings.get("scan", "exclude_dirs", [])
        for dir_path in exclude_dirs:
            self._exclude_dir_list.addItem(dir_path)
        
        # 排除文件类型
        patterns = self._settings.get("scan", "exclude_patterns", [])
        self._exclude_pattern_edit.setText(", ".join(patterns))
        
        # 清理设置
        self._confirm_delete_check.setChecked(self._settings.get("cleanup", "confirm_before_delete", True))
        self._use_recycle_check.setChecked(self._settings.get("cleanup", "use_system_recycle", True))
        self._large_file_spin.setValue(self._settings.get("cleanup", "large_file_threshold_mb", 100))
        self._large_folder_spin.setValue(self._settings.get("cleanup", "large_folder_threshold_mb", 1024))
        
        # 高级设置
        check_update = self._settings.get("advanced", "check_update", "auto")
        update_index = self._check_update_combo.findData(check_update)
        if update_index >= 0:
            self._check_update_combo.setCurrentIndex(update_index)
        
        self._update_server_edit.setText(self._settings.get("advanced", "update_server", ""))
        
        log_level = self._settings.get("advanced", "log_level", "info")
        log_index = self._log_level_combo.findData(log_level)
        if log_index >= 0:
            self._log_level_combo.setCurrentIndex(log_index)
    
    def _on_save(self):
        """保存按钮"""
        # 常规设置
        auto_start = self._auto_start_check.isChecked()
        self._settings.set("general", "auto_start", auto_start)
        self._settings.set("general", "start_minimized", self._start_minimized_check.isChecked())
        self._settings.set("general", "auto_scan_on_start", self._auto_scan_check.isChecked())
        
        # 应用开机自启动设置
        from auto_start import set_auto_start
        set_auto_start(auto_start)
        
        # 扫描与索引设置
        self._settings.set("scan", "index_db_path", self._index_path_edit.text())
        self._settings.set("scan", "auto_scan_interval", self._scan_interval_combo.currentData())
        
        # 排除目录
        exclude_dirs = []
        for i in range(self._exclude_dir_list.count()):
            exclude_dirs.append(self._exclude_dir_list.item(i).text())
        self._settings.set("scan", "exclude_dirs", exclude_dirs)
        
        # 排除文件类型
        patterns_text = self._exclude_pattern_edit.text()
        patterns = [p.strip() for p in patterns_text.split(",") if p.strip()]
        self._settings.set("scan", "exclude_patterns", patterns)
        
        # 清理设置
        self._settings.set("cleanup", "confirm_before_delete", self._confirm_delete_check.isChecked())
        self._settings.set("cleanup", "use_system_recycle", self._use_recycle_check.isChecked())
        self._settings.set("cleanup", "large_file_threshold_mb", self._large_file_spin.value())
        self._settings.set("cleanup", "large_folder_threshold_mb", self._large_folder_spin.value())
        
        # 高级设置
        self._settings.set("advanced", "check_update", self._check_update_combo.currentData())
        self._settings.set("advanced", "update_server", self._update_server_edit.text())
        self._settings.set("advanced", "log_level", self._log_level_combo.currentData())
        
        self._settings.save()
        self.settings_saved.emit()
        QMessageBox.information(self, "成功", "设置已保存")
    
    def _browse_index_path(self):
        """浏览选择索引路径"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择索引存储目录")
        if dir_path:
            self._index_path_edit.setText(dir_path)
    
    def _add_exclude_dir(self):
        """添加排除目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择要排除的目录")
        if dir_path:
            # 检查是否已存在
            for i in range(self._exclude_dir_list.count()):
                if self._exclude_dir_list.item(i).text() == dir_path:
                    return
            self._exclude_dir_list.addItem(dir_path)
    
    def _remove_exclude_dir(self):
        """移除选中的排除目录"""
        current_item = self._exclude_dir_list.currentItem()
        if current_item:
            row = self._exclude_dir_list.row(current_item)
            self._exclude_dir_list.takeItem(row)
    
    def _export_config(self):
        """导出配置"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", "filecare_config.json", "JSON 文件 (*.json)"
        )
        if file_path:
            if self._settings.export_config(file_path):
                QMessageBox.information(self, "成功", "配置已导出")
            else:
                QMessageBox.warning(self, "失败", "导出配置失败")
    
    def _import_config(self):
        """导入配置"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", "", "JSON 文件 (*.json)"
        )
        if file_path:
            if self._settings.import_config(file_path):
                QMessageBox.information(self, "成功", "配置已导入，请重新打开设置页面查看")
                self._load_settings()
            else:
                QMessageBox.warning(self, "失败", "导入配置失败")
    
    def _reset_to_default(self):
        """恢复默认配置"""
        reply = QMessageBox.question(
            self, "确认", "确定要恢复所有设置为默认值吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._settings.reset_to_default()
            self._load_settings()
            QMessageBox.information(self, "成功", "已恢复默认设置")
    
    def _on_cancel(self):
        """取消按钮"""
        self.settings_closed.emit()
