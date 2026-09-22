# -*- coding: utf-8 -*-
"""文件管家 / FileCare 完整主窗口。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAction, QAbstractSpinBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from disk_scanner import DiskScannerThread
from file_association import FileAssociation
from file_operations import FileOperations
from web_search import WebSearch
from quick_search import QuickSearchEngine
from fulltext_search import FullTextSearchEngine
from content_extractor import ContentExtractor
from treemap_widget import TreemapWidget
from settings import get_settings
from settings_page import SettingsPage


APP_NAME_ZH = "文件管家"
APP_NAME_EN = "FileCare"
ASSET_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "assets"
APP_ICON_PATH = ASSET_DIR / "filecare.ico"


class _TriangleSpinMixin:
    """Paint unambiguous triangular increment/decrement affordances over Qt's spin buttons."""
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        right = self.rect().right()
        left = max(0, right - 24)
        mid = self.rect().center().y()
        painter.fillRect(left, self.rect().top() + 1, right - left, self.rect().height() - 2,
                         self.palette().base())
        painter.setPen(QtGui.QPen(QtGui.QColor("#d7dce2")))
        painter.drawLine(left, self.rect().top() + 3, left, self.rect().bottom() - 3)
        painter.setPen(Qt.NoPen)
        color = self.palette().color(QtGui.QPalette.ButtonText)
        painter.setBrush(color)
        painter.drawPolygon(QtGui.QPolygon([
            QtCore.QPoint(right - 15, mid - 2), QtCore.QPoint(right - 5, mid - 2),
            QtCore.QPoint(right - 10, mid - 8)
        ]))
        painter.drawPolygon(QtGui.QPolygon([
            QtCore.QPoint(right - 15, mid + 2), QtCore.QPoint(right - 5, mid + 2),
            QtCore.QPoint(right - 10, mid + 8)
        ]))


class TriangleDoubleSpinBox(_TriangleSpinMixin, QDoubleSpinBox):
    pass


class TriangleSpinBox(_TriangleSpinMixin, QSpinBox):
    pass


class SearchModeTabs(QWidget):
    """文件名搜索 / 内容搜索 — 下划线式标签（Minimalism 风格，绿色激活）。

    提供 currentIndex() / setCurrentIndex() / setTabText() / currentChanged 信号，
    与旧 QTabWidget 调用点保持兼容。
    """
    currentChanged = QtCore.pyqtSignal(int)

    def __init__(self, labels):
        super().__init__()
        self._index = 0
        self._buttons = []
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setObjectName("searchModeTab")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self.setCurrentIndex(idx))
            self._buttons.append(b)
            h.addWidget(b)
        h.addStretch()
        self._refresh_styles()

    def _refresh_styles(self):
        for i, b in enumerate(self._buttons):
            b.setProperty("class", "active" if i == self._index else "")
            b.style().unpolish(b)
            b.style().polish(b)

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, i):
        if i == self._index:
            return
        self._index = i
        self._refresh_styles()
        self.currentChanged.emit(i)

    def setTabText(self, i, text):
        if 0 <= i < len(self._buttons):
            self._buttons[i].setText(text)

TRANSLATIONS = {
    "zh": {
        "app_name": APP_NAME_ZH, "refresh": "刷新", "space_scan": "大文件清理", "recycle_bin": "回收站管理",
        "home": "首页", "file_browse": "文件管理",
        "nav_home": "🏠 首页", "nav_browse": "📂 文件管理", "nav_scan": "🧹 大文件清理",
        "nav_visualization": "📊 空间可视化", "nav_search": "🔍 快速搜索", "nav_recycle": "🗑️ 回收站管理",
        "nav_settings": "⚙️ 设置",
        "search": "搜索当前目录...", "language": "语言", "language_zh": "中文", "language_en": "English", "back": "返回上一位置", "up": "返回上级目录", "root": "返回磁盘根目录",
        "file_details": "文件详情", "scan_tab": "空间扫描", "detail_title": "文件与软件详情", "disk_usage": "磁盘使用情况",
        "name": "名称", "full_path": "完整路径", "size": "大小", "mtime": "修改时间", "item_type": "项目类型",
        "source": "来源/同步软件", "relation": "与软件的关系", "default_app": "默认打开程序", "confidence": "识别可信度",
        "evidence": "判断依据", "delete_advice": "删除建议", "identify": "识别关联软件", "online": "在线核验软件",
        "open_location": "打开所在目录", "move_recycle": "移至回收站", "current_dir": "当前目录", "current_drive": "当前磁盘",
        "choose_dir": "选择目录", "min_size": "最小文件大小(MB)", "max_results": "最多显示", "start_scan": "开始扫描",
        "cancel_scan": "取消扫描", "scan_intro": "选择范围后开始扫描；程序不会自动删除任何文件。请特别留意云盘同步风险。",
        "large_files": "大文件", "large_folders": "大文件夹", "cleanup_advice": "清理建议", "junk_files": "垃圾/临时文件", "clean_selected": "清理选中垃圾", "copy_path": "复制路径",
        "visualization_title": "空间可视化", "visualization_intro": "显示目录下所有文件和文件夹的占用情况，点击色块可逐级下钻。",
        "quick_search": "快速搜索", "search_mode_name": "文件名搜索", "search_mode_content": "内容搜索",
        "search_placeholder": "输入关键词搜索...", "search_hint_name": "支持通配符 * 和 ?，如 *.pdf、report*、ext:xlsx",
        "search_hint_content": "搜索文档内容，支持 PDF、Word、Excel、PPT、TXT 等格式",
        "index_status": "索引状态", "index_build": "构建索引", "index_cancel": "取消索引",
        "index_rebuild": "重建索引", "index_none": "尚未构建索引，点击「构建索引」开始",
        "index_building": "正在构建索引...", "index_complete": "索引完成", "index_count": "已索引",
        "preview_title": "文档预览", "preview_hint": "点击搜索结果预览内容", "preview_no_support": "该文件类型不支持预览",
        "search_results": "搜索结果", "no_results": "未找到匹配结果", "result_count": "共 {count} 条结果",
        "open_file": "打开文件", "open_folder": "打开所在目录",
        "open_item": "打开", "open_with": "选择打开方式…", "copy_item": "复制", "cut_item": "剪切",
        # ── 首页 ──
        "home_greeting": "你好，欢迎回来 👋",
        "home_greeting_sub": "上次扫描：{time} · 磁盘健康状态良好",
        "home_quick_actions": "快捷操作",
        "home_action_scan_sub": "分析大文件和文件夹占用",
        "home_action_visualization_sub": "可视化查看空间占用分布",
        "home_action_search_sub": "按文件名或内容查找",
        "home_action_recycle_sub": "查看和清理已删除文件",
        "home_system_drive": "系统盘", "home_data_drive": "数据盘",
        "home_used": "已用 {size}", "home_total": "总共 {size}",
        "status_ready": "就绪",
        # ── 回收站页面 ──
        "rb_files_count": "文件数量", "rb_space_used": "占用空间", "rb_oldest": "最早删除", "rb_new_this_week": "本周新增",
        "rb_select_all": "全选", "rb_delete_selected": "永久删除选中", "rb_restore_selected": "恢复选中", "rb_empty": "清空回收站",
        "rb_col_name": "文件名", "rb_col_origin": "原路径", "rb_col_size": "大小", "rb_col_deleted": "删除时间", "rb_col_actions": "操作",
        "rb_restore": "恢复", "rb_permanent": "永久删除", "rb_selected_n": "已选择 {n} 项",
        "rb_days_ago": "{n} 天前", "rb_empty_bin": "回收站为空",
    },
    "en": {
        "app_name": APP_NAME_EN, "refresh": "Refresh", "space_scan": "Large File Cleanup", "recycle_bin": "Recycle Bin",
        "home": "Home", "file_browse": "File Browser",
        "nav_home": "🏠 Home", "nav_browse": "📂 Files", "nav_scan": "🧹 Large File Cleanup",
        "nav_visualization": "📊 Space Visualization", "nav_search": "🔍 Quick Search", "nav_recycle": "🗑️ Recycle Bin",
        "nav_settings": "⚙️ Settings",
        "search": "Search current folder...", "language": "Language", "language_zh": "Chinese", "language_en": "English", "back": "Previous Location", "up": "Parent Folder", "root": "Drive Root",
        "file_details": "File Details", "scan_tab": "Space Scan", "detail_title": "File & Software Details", "disk_usage": "Disk Usage",
        "name": "Name", "full_path": "Full Path", "size": "Size", "mtime": "Modified", "item_type": "Item Type",
        "source": "Source / Sync Software", "relation": "Software Relationship", "default_app": "Default App", "confidence": "Confidence",
        "evidence": "Evidence", "delete_advice": "Deletion Advice", "identify": "Identify Software", "online": "Verify Online",
        "open_location": "Open Location", "move_recycle": "Move to Recycle Bin", "current_dir": "Current Folder", "current_drive": "Current Drive",
        "choose_dir": "Choose Folder", "min_size": "Minimum Size (MB)", "max_results": "Max Results", "start_scan": "Start Scan",
        "cancel_scan": "Cancel Scan", "scan_intro": "Choose a location to scan. No files are deleted automatically. Review cloud-sync risks carefully.",
        "large_files": "Large Files", "large_folders": "Large Folders", "cleanup_advice": "Cleanup Advice", "junk_files": "Junk / Temp Files", "clean_selected": "Clean Selected Junk", "copy_path": "Copy Path",
        "visualization_title": "Space Visualization", "visualization_intro": "Shows all files and folders in a directory. Click blocks to drill down.",
        "quick_search": "Quick Search", "search_mode_name": "Name Search", "search_mode_content": "Content Search",
        "search_placeholder": "Type to search...", "search_hint_name": "Wildcards * and ? supported, e.g. *.pdf, report*, ext:xlsx",
        "search_hint_content": "Search inside documents: PDF, Word, Excel, PPT, TXT and more",
        "index_status": "Index Status", "index_build": "Build Index", "index_cancel": "Cancel Indexing",
        "index_rebuild": "Rebuild Index", "index_none": "No index yet. Click 'Build Index' to start.",
        "index_building": "Building index...", "index_complete": "Index complete", "index_count": "Indexed",
        "preview_title": "Document Preview", "preview_hint": "Click a result to preview content", "preview_no_support": "This file type is not previewable",
        "search_results": "Search Results", "no_results": "No matching results", "result_count": "{count} results",
        "open_file": "Open File", "open_folder": "Open Location",
        "open_item": "Open", "open_with": "Open with…", "copy_item": "Copy", "cut_item": "Cut",
        # ── Home ──
        "home_greeting": "Welcome back 👋",
        "home_greeting_sub": "Last scan: {time} · Disk health is good",
        "home_quick_actions": "Quick Actions",
        "home_action_scan_sub": "Analyze large files and folders",
        "home_action_visualization_sub": "Visualize space usage distribution",
        "home_action_search_sub": "Find files by name or content",
        "home_action_recycle_sub": "Review and clean deleted files",
        "home_system_drive": "System Drive", "home_data_drive": "Data Drive",
        "home_used": "Used {size}", "home_total": "Total {size}",
        "status_ready": "Ready",
        # ── Recycle page ──
        "rb_files_count": "Files", "rb_space_used": "Space Used", "rb_oldest": "Oldest Item", "rb_new_this_week": "New This Week",
        "rb_select_all": "Select All", "rb_delete_selected": "Delete Selected", "rb_restore_selected": "Restore Selected", "rb_empty": "Empty Recycle Bin",
        "rb_col_name": "File Name", "rb_col_origin": "Original Path", "rb_col_size": "Size", "rb_col_deleted": "Deleted", "rb_col_actions": "Actions",
        "rb_restore": "Restore", "rb_permanent": "Delete Forever", "rb_selected_n": "{n} selected",
        "rb_days_ago": "{n} days ago", "rb_empty_bin": "Recycle bin is empty",
    },
}


def format_size(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "未知"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "未知"


def format_time(timestamp):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    except Exception:
        return "未知"


# ── Minimalism 风格配色（与 ui_previews/*.html 预览图一致） ──
M_BG = "#f5f6f8"          # 页面背景
M_CARD = "#ffffff"        # 卡片背景
M_CARD_SOFT = "#f8f9fb"   # 次级卡片背景
M_BORDER = "#eef0f3"      # 卡片/分隔线边框
M_BORDER_2 = "#e2e6ea"    # 输入框边框
M_TEXT = "#2c3e50"        # 主文字
M_TEXT_2 = "#8e99a4"      # 次级文字
M_TEXT_3 = "#a0aab4"      # 弱化文字
M_ACCENT = "#4a90d9"      # 主色（蓝）
M_ACCENT_HOVER = "#3a7bc8"
M_GREEN = "#27ae60"
M_ORANGE = "#e67e22"
M_RED = "#e74c3c"

# 补充浅色主题细粒度颜色（供 StyleSheet 模板使用）
M_TOOLBAR = "#fafbfc"          # 顶部工具栏背景
M_HOVER_BG = "#eef3ff"         # 悬停/选中背景
M_HOVER_BORDER = "#b8d4f0"     # 悬停边框
M_DISABLED_TEXT = "#c0c8d0"    # 禁用文字
M_PRIMARY_DISABLED = "#a8c8e8" # 主按钮禁用背景
M_DANGER_BORDER = "#f5c6c6"    # 危险按钮边框
M_DANGER_HOVER = "#fdf0f0"     # 危险按钮悬停背景
M_RED_HOVER = "#c0392b"        # 危险实心按钮悬停
M_CHIP_ACTIVE = "#e8f4fd"      # 筛选 chip 激活背景
M_ACTIONCARD_HOVER = "#c5d8f5" # 快捷卡片悬停边框
M_HEADING = "#1a2332"          # 首页大标题
M_PATH_BAR_TEXT = "#52606d"    # 路径栏文字
M_INPUT_FOCUS = "#ffffff"      # 输入框聚焦背景
M_DROPDOWN_BG = "#ffffff"      # 下拉列表背景
M_DROPDOWN_SEL = "rgba(74,144,217,0.18)"  # 下拉选中背景
M_DROPDOWN_SEL_TEXT = "#163a59"           # 下拉选中文字
M_ALT_ROW = "#fafbfc"          # 表格交替行
M_MENU_SEL_TEXT = "#163a59"    # 菜单选中文字
M_PROGRESS_END = "#6cb4f0"     # 进度条渐变终点
M_SCROLLBAR = "#d5dae0"        # 滚动条滑块
M_SCROLLBAR_HOVER = "#b8c0c9"  # 滚动条滑块悬停
M_CHECKBOX_BORDER = "#d0d5db"  # 复选框边框

STYLESHEET = """
* { font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; }
QMainWindow { background:%(bg)s; color:%(text)s; }
QWidget#page { background:%(bg)s; }
QFrame#toolbar { background:%(toolbar)s; border-bottom:1px solid %(border)s; min-height:52px; max-height:52px; }
QLabel#title { font-size:15px; font-weight:700; color:%(text)s; padding:8px; }
QLabel#sectionTitle { font-size:15px; font-weight:600; color:%(text)s; padding:4px 0 8px 0; }
QLabel#key { color:%(text3)s; font-size:12px; }
QLabel#value { color:%(text)s; font-size:12px; }
QLabel#pathBar { background:%(cardoft)s; border:1px solid %(border2)s; border-radius:6px; padding:7px 9px; color:%(pathbartext)s; }
QFrame#sidebar, QFrame#card { background:%(card)s; border:1px solid %(border)s; border-radius:12px; }
QFrame#statusBar { background:%(cardoft)s; border-top:1px solid %(border)s; }

/* ── 顶部导航标签（下划线式，Minimalism） ── */
QPushButton#navTab {
    background:transparent; border:none; border-bottom:2.5px solid transparent;
    color:%(text2)s; font-size:14px; padding:13px 24px 11px 24px; border-radius:0; min-height:0;
    margin:0 2px;
}
QPushButton#navTab:hover { color:%(accent)s; background:%(navtabs_hover)s; }
QPushButton#navTab[class="active"] { color:%(accent)s; border-bottom:2.5px solid %(accent)s; font-weight:600; background:transparent; }

/* ── 按钮 ── */
QPushButton {
    min-height:30px; padding:6px 14px; border-radius:8px;
    border:1px solid %(border2)s; background:%(card)s; color:%(text)s; font-size:13px;
}
QPushButton:hover { border-color:%(hoverborder)s; background:%(hoverbg)s; }
QPushButton:disabled { color:%(disabledtext)s; background:%(cardoft)s; border-color:%(border)s; }
QPushButton#primary { background:%(accent)s; color:white; border:1px solid %(accent)s; font-weight:500; }
QPushButton#primary:hover { background:%(accenthover)s; border-color:%(accenthover)s; }
QPushButton#primary:disabled { background:%(primarydisabled)s; border-color:%(primarydisabled)s; color:white; }
QPushButton#danger { color:%(red)s; border-color:%(dangerborder)s; background:%(card)s; }
QPushButton#danger:hover { background:%(dangerhover)s; border-color:%(red)s; }
QPushButton#dangerSolid { background:%(red)s; color:white; border:1px solid %(red)s; }
QPushButton#dangerSolid:hover { background:%(redhover)s; }
QPushButton#success { color:%(accent)s; border-color:%(hoverborder)s; background:%(card)s; }
QPushButton#success:hover { background:%(hoverbg)s; }
QPushButton#action, QPushButton#deleteAction { min-height:40px; padding:9px 14px; text-align:left; }
QPushButton#deleteAction { color:%(red)s; border-color:%(dangerborder)s; }
QPushButton#deleteAction:hover { background:%(dangerhover)s; border-color:%(red)s; color:%(red)s; }
QPushButton#chip {
    border:1px solid %(border2)s; color:%(text2)s; background:%(toolbar)s;
    border-radius:20px; padding:5px 14px; min-height:0; font-size:12px;
}
QPushButton#chip:hover { border-color:%(hoverborder)s; color:%(accent)s; }
QPushButton#chip[class="active"] { background:%(chipactive)s; border-color:%(hoverborder)s; color:%(accent)s; }
QPushButton#navBack { padding:6px 14px; font-size:12px; color:%(text2)s; background:%(cardoft)s; }
QPushButton#navBack:hover { background:%(hoverbg)s; border-color:%(hoverborder)s; color:%(accent)s; }

/* ── 首页快捷操作卡片 ── */
QPushButton#actionCard {
    background:%(cardoft)s; border:1px solid %(border)s; border-radius:12px;
    text-align:left; min-height:86px; padding:0px;
}
QPushButton#actionCard:hover { background:%(hoverbg)s; border-color:%(actioncardhover)s; }
QLabel#actionTitle { font-size:13px; font-weight:600; color:%(text)s; }
QLabel#actionSub { font-size:11px; color:%(text3)s; }
QLabel#homeGreeting { font-size:24px; font-weight:700; color:%(heading)s; }
QLabel#homeGreetingSub { font-size:13px; color:%(text3)s; }
QLabel#diskPct { font-size:26px; font-weight:700; }
QLabel#diskName { font-size:14px; font-weight:600; color:%(text)s; }
QLabel#diskDetail { font-size:12px; color:%(text3)s; }
QLabel#summaryLabel { font-size:11px; color:%(text3)s; letter-spacing:0.5px; }
QLabel#summaryValue { font-size:24px; font-weight:700; color:%(text)s; }

/* ── 搜索模式标签（下划线式，绿色激活） ── */
QPushButton#searchModeTab {
    background:transparent; border:none; border-bottom:2px solid transparent;
    color:%(text2)s; font-size:13px; padding:8px 20px 7px 20px; border-radius:0; min-height:0;
}
QPushButton#searchModeTab:hover { color:%(green)s; }
QPushButton#searchModeTab[class="active"] { color:%(green)s; border-bottom:2px solid %(green)s; font-weight:600; background:transparent; }

/* ── 搜索结果索引状态 ── */
QLabel#indexDot { background:%(green)s; border-radius:3px; min-width:6px; max-width:6px; min-height:6px; max-height:6px; }

/* ── 输入控件 ── */
QLineEdit {
    min-height:34px; border:1.5px solid %(border2)s; border-radius:10px;
    padding:2px 12px; background:%(cardoft)s; font-size:13px; color:%(text)s;
}
QLineEdit:focus { border-color:%(accent)s; background:%(inputfocus)s; }
QComboBox {
    min-height:32px; border:1px solid %(border2)s; border-radius:8px;
    padding:2px 10px; background:%(card)s; font-size:13px; color:%(text)s;
}
QComboBox:hover { border-color:%(hoverborder)s; }
QComboBox::drop-down { border:none; width:22px; }
QSpinBox, QDoubleSpinBox { min-height:30px; border:1px solid %(border2)s; border-radius:8px; padding:2px 8px; background:%(card)s; }
QComboBox QAbstractItemView {
    background:%(dropdownbg)s; color:%(text)s; border:1px solid %(border2)s; outline:0;
    selection-background-color:%(dropdownsel)s; selection-color:%(dropdownseltext)s;
}
QComboBox QAbstractItemView::item { min-height:30px; padding:4px 10px; }
QComboBox QAbstractItemView::item:hover { background:%(hoverbg)s; }

/* ── 列表/树 ── */
QTreeWidget {
    background:%(card)s; border:1px solid %(border)s; border-radius:10px;
    alternate-background-color:%(altrow)s; font-size:13px;
}
QTreeWidget::item { min-height:30px; padding:4px 6px; border-bottom:1px solid %(bg)s; }
QTreeWidget::item:hover { background:%(cardoft)s; }
QTreeWidget::item:selected { background:%(hoverbg)s; color:%(text)s; }
QHeaderView::section {
    background:%(cardoft)s; border:none; border-bottom:1px solid %(border)s;
    padding:8px; font-weight:500; color:%(text2)s; font-size:12px;
}
QListWidget {
    background:%(card)s; border:1px solid %(border)s; border-radius:10px; font-size:13px;
}
QListWidget::item { min-height:32px; padding:6px 10px; border-bottom:1px solid %(bg)s; }
QListWidget::item:hover { background:%(cardoft)s; }
QListWidget::item:selected { background:%(hoverbg)s; color:%(text)s; }

/* ── 菜单 ── */
QMenu { background:%(dropdownbg)s; color:%(text)s; border:1px solid %(border)s; border-radius:10px; padding:6px; }
QMenu::item { padding:8px 28px 8px 12px; border-radius:6px; font-size:13px; }
QMenu::item:selected { background:%(hoverbg)s; color:%(menuseltext)s; }
QMenu::separator { height:1px; background:%(border)s; margin:4px 8px; }

/* ── 标签页（扫描结果区） ── */
QTabWidget::pane { border:1px solid %(border)s; border-radius:10px; background:%(card)s; top:-1px; }
QTabBar { background:transparent; }
QTabBar::tab {
    padding:9px 40px; color:%(text2)s; font-size:13px; min-width:80px;
    border:none; border-bottom:2px solid transparent; margin-right:4px; background:transparent;
}
QTabBar::tab:hover { color:%(accent)s; }
QTabBar::tab:selected { color:%(accent)s; border-bottom:2px solid %(accent)s; font-weight:600; }

/* ── 进度条 ── */
QProgressBar { border:0; background:%(border)s; border-radius:4px; min-height:8px; max-height:8px; text-align:center; }
QProgressBar::chunk { background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 %(accent)s, stop:1 %(progressend)s); border-radius:4px; }

/* ── 滚动条（细线风格） ── */
QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
QScrollBar::handle:vertical { background:%(scrollbar)s; border-radius:4px; min-height:30px; }
QScrollBar::handle:vertical:hover { background:%(scrollbarhover)s; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { background:transparent; height:10px; margin:2px; }
QScrollBar::handle:horizontal { background:%(scrollbar)s; border-radius:4px; min-width:30px; }
QScrollBar::handle:horizontal:hover { background:%(scrollbarhover)s; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }

/* ── 文本编辑区 ── */
QPlainTextEdit, QTextEdit {
    background:%(cardoft)s; border:1px solid %(border)s; border-radius:8px;
    font-family:Consolas,'Microsoft YaHei',monospace; font-size:13px; color:%(text)s;
}

/* ── 复选框 ── */
QCheckBox { spacing:8px; font-size:13px; color:%(text)s; }
QCheckBox::indicator { width:17px; height:17px; border:1.5px solid %(checkboxborder)s; border-radius:4px; background:%(dropdownbg)s; }
QCheckBox::indicator:hover { border-color:%(accent)s; }
QCheckBox::indicator:checked { background:white; border-color:%(accent)s; image:url(data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><path d='M3 8l3 3 7-7' stroke='%(accent)s' stroke-width='2' fill='none'/></svg>); }

/* ── 工具提示 ── */
QToolTip { background:%(dropdownbg)s; color:%(text)s; border:1px solid %(border2)s; border-radius:6px; padding:6px 10px; font-size:12px; }

QDialog { background:%(bg)s; }
"""

# 浅色主题颜色字典（供 STYLESHEET 模板填充）
_LIGHT_COLORS = {
    "bg": M_BG, "card": M_CARD, "cardoft": M_CARD_SOFT, "border": M_BORDER, "border2": M_BORDER_2,
    "text": M_TEXT, "text2": M_TEXT_2, "text3": M_TEXT_3,
    "accent": M_ACCENT, "accenthover": M_ACCENT_HOVER, "green": M_GREEN, "red": M_RED,
    "toolbar": M_TOOLBAR, "hoverbg": M_HOVER_BG, "hoverborder": M_HOVER_BORDER,
    "disabledtext": M_DISABLED_TEXT, "primarydisabled": M_PRIMARY_DISABLED,
    "dangerborder": M_DANGER_BORDER, "dangerhover": M_DANGER_HOVER, "redhover": M_RED_HOVER,
    "chipactive": M_CHIP_ACTIVE, "actioncardhover": M_ACTIONCARD_HOVER,
    "heading": M_HEADING, "pathbartext": M_PATH_BAR_TEXT,
    "navtabs_hover": "rgba(74,144,217,0.06)",
    "inputfocus": M_INPUT_FOCUS, "dropdownbg": M_DROPDOWN_BG,
    "dropdownsel": M_DROPDOWN_SEL, "dropdownseltext": M_DROPDOWN_SEL_TEXT,
    "altrow": M_ALT_ROW, "menuseltext": M_MENU_SEL_TEXT,
    "progressend": M_PROGRESS_END, "scrollbar": M_SCROLLBAR,
    "scrollbarhover": M_SCROLLBAR_HOVER, "checkboxborder": M_CHECKBOX_BORDER,
}

# 初始样式表（浅色，供模块加载时使用；_apply_theme() 会覆盖）
STYLESHEET_DEFAULT = STYLESHEET % _LIGHT_COLORS


class DiskMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.language = "zh"
        self._i18n_widgets = {}
        self.setWindowTitle(APP_NAME_ZH)
        if APP_ICON_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(APP_ICON_PATH)))
        self.setMinimumSize(1100, 700)
        self.resize(1280, 800)
        self.setStyleSheet(STYLESHEET_DEFAULT)
        self.current_path = os.path.abspath(os.sep)
        self._full_path = self.current_path
        self._nav_history = []
        self._scanner_thread = None
        self._scan_path = self.current_path
        self._viz_path = self.current_path
        self._last_identity = None
        self._detail_path = None
        self.web_search = WebSearch("bing")
        self.file_operations = FileOperations(os.path.join(os.path.expanduser("~"), ".diskwise", "recycle_bin"))
        self.quick_search_engine = QuickSearchEngine()
        self.fulltext_search_engine = FullTextSearchEngine()
        self.content_extractor = ContentExtractor()
        self._app_settings = QtCore.QSettings("FileCare", "FileCare")
        self._search_timer = None
        self._build_ui()
        # 启动时应用已保存的字体设置
        self._apply_font_size()
        self._apply_language()
        self._update_home_disks()
        self._navigate_to(self.current_path, add_history=False)
        self._update_disk_usage()
        # 首次建库提示与后台增量更新分开进行，避免阻塞主界面。
        QtCore.QTimer.singleShot(350, self._show_first_index_notice)
        QtCore.QTimer.singleShot(1000, self._auto_rebuild_index_on_startup)
        
        # 启动时自动扫描索引（如果设置开启）
        if self._settings.get("general", "auto_scan_on_start", False):
            QtCore.QTimer.singleShot(2000, self._auto_start_scan)
        
        # 设置自动扫描定时器
        self._setup_auto_scan_timer()

    def _icon(self, enum):
        return self.style().standardIcon(enum)

    def _tr(self, key):
        return TRANSLATIONS[self.language].get(key, key)

    def _register_text(self, key, widget):
        self._i18n_widgets.setdefault(key, []).append(widget)
        return widget

    def _apply_font_size(self):
        """应用字体大小设置"""
        size = self._settings.get("ui", "font_size", "medium")
        
        # 定义字体大小映射
        size_map = {
            "small": 12,
            "medium": 14,
            "large": 16,
        }
        
        base_size = size_map.get(size, 14)
        
        # 创建字体大小样式
        font_stylesheet = f"""
            * {{ font-size: {base_size}px; }}
            QLabel#title {{ font-size: {base_size + 1}px; }}
            QLabel#sectionTitle {{ font-size: {base_size + 1}px; }}
            QPushButton#navTab {{ font-size: {base_size}px; }}
            QPushButton {{ font-size: {base_size - 1}px; }}
        """
        
        # 应用字体样式（追加到现有样式表）
        current_stylesheet = self.styleSheet()
        # 移除旧的字体样式（如果存在）
        if "/* FONT_SIZE_STYLE */" in current_stylesheet:
            start = current_stylesheet.find("/* FONT_SIZE_STYLE */")
            end = current_stylesheet.find("/* END_FONT_SIZE_STYLE */") + len("/* END_FONT_SIZE_STYLE */")
            current_stylesheet = current_stylesheet[:start] + current_stylesheet[end:]
        
        # 添加新的字体样式
        new_stylesheet = current_stylesheet + f"\n/* FONT_SIZE_STYLE */\n{font_stylesheet}\n/* END_FONT_SIZE_STYLE */"
        self.setStyleSheet(new_stylesheet)

    def _apply_language(self):
        for key, widgets in self._i18n_widgets.items():
            for widget in widgets:
                widget.setText(self._tr(key))
        self.setWindowTitle(self._tr("app_name"))
        QtWidgets.QApplication.setApplicationDisplayName(self._tr("app_name"))
        # 扫描结果标签页（index 0 大文件 / 1 大文件夹 / 2 清理建议 / 3 垃圾文件）
        self._scan_result_tabs.setTabText(0, self._tr("large_files"))
        self._scan_result_tabs.setTabText(1, self._tr("large_folders"))
        self._scan_result_tabs.setTabText(2, self._tr("cleanup_advice"))
        self._scan_result_tabs.setTabText(3, self._tr("junk_files"))
        # 回收站页面表头与工具栏
        self._rb_tree.setHeaderLabels([
            "", self._tr("rb_col_name"), self._tr("rb_col_origin"),
            self._tr("rb_col_size"), self._tr("rb_col_deleted"), self._tr("rb_col_actions"),
        ])
        if hasattr(self, "_rb_btn_deselect"):
            self._rb_btn_deselect.setText("全不选" if self.language == "zh" else "Deselect All")
        if hasattr(self, "_home_greeting_sub"):
            self._home_greeting_sub.setText(
                self._tr("home_greeting_sub").replace("{time}", self._last_scan_time() or "—"))
        if self.language == "zh":
            self.tree.setHeaderLabels(["名称", "大小"])
            self._large_files.setHeaderLabels(["名称", "实际占用", "逻辑大小", "修改时间", "来源软件", "完整路径"])
            self._large_folders.setHeaderLabels(["文件夹", "实际占用", "逻辑大小", "文件数", "子文件夹数", "来源软件", "完整路径"])
            self._suggestions.setHeaderLabels(["建议等级", "名称", "可释放空间", "原因", "风险", "完整路径"])
            self._garbage_files.setHeaderLabels(["类别", "名称", "实际占用", "修改时间", "建议", "风险", "完整路径"])
        else:
            self.tree.setHeaderLabels(["Name", "Size"])
            self._large_files.setHeaderLabels(["Name", "Allocated", "Logical Size", "Modified", "Source Software", "Full Path"])
            self._large_folders.setHeaderLabels(["Folder", "Allocated", "Logical Size", "Files", "Subfolders", "Source Software", "Full Path"])
            self._suggestions.setHeaderLabels(["Level", "Name", "Reclaimable", "Reason", "Risk", "Full Path"])
            self._garbage_files.setHeaderLabels(["Category", "Name", "Allocated", "Modified", "Advice", "Risk", "Full Path"])
        for index in range(self._drive_combo.count()):
            root = self._drive_combo.itemData(index)
            self._drive_combo.setItemText(index, (f"Drive {root}" if self.language == "en" else f"磁盘 {root}"))
        count = self.tree.topLevelItemCount()
        self._status_label.setText((f"Current folder: {self.current_path}    Items: {count}" if self.language == "en" else f"当前目录：{self.current_path}    项目数：{count}"))
        if self._detail_path and os.path.exists(self._detail_path):
            self._show_detail(self._detail_path, os.path.isdir(self._detail_path))

    def _button(self, text, icon, slot, object_name=""):
        button = QPushButton(text)
        if object_name:
            button.setObjectName(object_name)
        button.setIcon(self._icon(icon))
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.clicked.connect(slot)
        return button

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("page")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 顶栏：logo + 标题 + 下划线式导航标签 + 搜索框 + 语言 ──
        toolbar = QFrame(); toolbar.setObjectName("toolbar")
        tb = QHBoxLayout(toolbar); tb.setContentsMargins(18, 0, 18, 0); tb.setSpacing(0)
        logo = QLabel()
        if APP_ICON_PATH.is_file(): logo.setPixmap(QtGui.QIcon(str(APP_ICON_PATH)).pixmap(26, 26))
        tb.addWidget(logo)
        title = self._register_text("app_name", QLabel()); title.setObjectName("title"); tb.addWidget(title)
        tb.addSpacing(16)

        # 导航标签（首页 / 文件管理 / 大文件清理 / 空间可视化 / 快速搜索 / 回收站管理 / 设置）
        self._nav_tabs = []
        nav_defs = [
            ("nav_home", self._show_home_view),
            ("nav_browse", self._show_browse_view),
            ("nav_scan", self._show_scan_view),
            ("nav_visualization", self._show_visualization_view),
            ("nav_search", self._show_search_view),
            ("nav_recycle", self._show_recycle_view),
            ("nav_settings", self._show_settings_view),
        ]
        for key, slot in nav_defs:
            btn = QPushButton()
            btn.setObjectName("navTab")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            self._register_text(key, btn)
            self._nav_tabs.append(btn)
            tb.addWidget(btn)
        tb.addStretch()
        root.addWidget(toolbar)

        # ── 侧边栏（属于"文件管理"页面） ──
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setMinimumWidth(260); sidebar.setMaximumWidth(320)
        side = QVBoxLayout(sidebar); side.setContentsMargins(12, 12, 12, 12); side.setSpacing(7)
        self._btn_back = self._button("返回上一位置", QtWidgets.QStyle.SP_ArrowBack, self._go_back_history)
        self._btn_up = self._button("返回上级目录", QtWidgets.QStyle.SP_ArrowUp, self._go_up)
        self._btn_root = self._button("返回磁盘根目录", QtWidgets.QStyle.SP_ComputerIcon, self._go_root)
        for btn in (self._btn_back, self._btn_up, self._btn_root):
            btn.setObjectName("navBack")
        self._register_text("back", self._btn_back); self._register_text("up", self._btn_up); self._register_text("root", self._btn_root)
        side.addWidget(self._btn_back); side.addWidget(self._btn_up); side.addWidget(self._btn_root)
        self._drive_combo = QComboBox(); self._drive_combo.setToolTip("选择磁盘")
        self._populate_drives(); self._drive_combo.currentIndexChanged.connect(self._on_drive_selected); side.addWidget(self._drive_combo)
        self._path_bar = QLabel(self.current_path); self._path_bar.setObjectName("pathBar"); self._path_bar.setToolTip(self.current_path); side.addWidget(self._path_bar)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["名称", "大小"]); self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(False); self.tree.setAlternatingRowColors(True); self.tree.setTextElideMode(Qt.ElideRight)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        header = self.tree.header(); header.setStretchLastSection(False); header.setSectionResizeMode(0, QHeaderView.Stretch); header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemClicked.connect(self._on_item_clicked); self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu); self.tree.customContextMenuRequested.connect(self._on_context_menu)
        side.addWidget(self.tree, 1)

        # ── 页面栈：0 首页 / 1 文件管理 / 2 大文件清理 / 3 空间可视化 / 4 快速搜索 / 5 回收站管理 / 6 设置 ──
        self._detail_page = self._build_detail_page()
        self._home_page = self._build_home_page()
        self._scan_page = self._build_scan_page()
        self._visualization_page = self._build_visualization_page()
        self._search_page = self._build_search_page()
        self._recycle_page = self._build_recycle_page()
        
        # 设置页面
        self._settings = get_settings()
        self._settings_page = SettingsPage(self._settings)
        self._settings_page.settings_saved.connect(self._on_settings_saved)
        self._settings_page.settings_closed.connect(self._show_home_view)

        browse_container = QWidget()
        browse_container.setObjectName("page")
        browse_h = QHBoxLayout(browse_container)
        browse_h.setContentsMargins(0, 0, 0, 0)
        browse_h.setSpacing(16)
        browse_h.addWidget(sidebar)
        browse_h.addWidget(self._detail_page, 1)
        self._browse_page = browse_container

        self._main_stack = QtWidgets.QStackedWidget()
        self._main_stack.addWidget(self._home_page)     # index 0
        self._main_stack.addWidget(self._browse_page)   # index 1
        self._main_stack.addWidget(self._scan_page)     # index 2
        self._main_stack.addWidget(self._visualization_page)  # index 3
        self._main_stack.addWidget(self._search_page)   # index 4
        self._main_stack.addWidget(self._recycle_page)  # index 5
        self._main_stack.addWidget(self._settings_page) # index 6
        self._main_stack.setCurrentIndex(0)
        self._set_active_tab(0)

        body_wrap = QHBoxLayout()
        body_wrap.setContentsMargins(16, 14, 16, 10)
        body_wrap.addWidget(self._main_stack, 1)
        root.addLayout(body_wrap, 1)

        # ── 底部状态栏：状态文字 + 磁盘迷你进度条 ──
        self._statusbar = QFrame()
        self._statusbar.setObjectName("statusBar")
        self._statusbar.setFixedHeight(34)
        sb = QHBoxLayout(self._statusbar)
        sb.setContentsMargins(20, 0, 20, 0)
        self._status_label = QLabel(self._tr("status_ready"))
        self._status_label.setStyleSheet(f"color:{M_TEXT_3}; font-size:11px;")
        sb.addWidget(self._status_label)
        sb.addStretch()
        self._disk_bars_layout = QHBoxLayout()
        self._disk_bars_layout.setSpacing(6)
        sb.addLayout(self._disk_bars_layout)
        root.addWidget(self._statusbar)

    # ══════════════ 首页（Minimalism 预览图 01） ══════════════

    def _build_home_page(self):
        page = QWidget()
        page.setObjectName("page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 8, 8, 0)
        outer.setSpacing(24)

        self._home_greeting = self._register_text("home_greeting", QLabel())
        self._home_greeting.setObjectName("homeGreeting")
        outer.addWidget(self._home_greeting)
        self._home_greeting_sub = QLabel()
        self._home_greeting_sub.setObjectName("homeGreetingSub")
        outer.addWidget(self._home_greeting_sub)

        self._home_disks_row = QHBoxLayout()
        self._home_disks_row.setSpacing(18)
        outer.addLayout(self._home_disks_row)

        actions_title = self._register_text("home_quick_actions", QLabel())
        actions_title.setStyleSheet(f"font-size:15px; font-weight:600; color:{M_TEXT};")
        outer.addWidget(actions_title)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(14)
        for icon, title_key, sub_key, slot, bg, fg in [
            ("🧹", "space_scan", "home_action_scan_sub", self._show_scan_view, "#e8f4fd", M_ACCENT),
            ("📊", "visualization_title", "home_action_visualization_sub", self._show_visualization_view, "#f0e8fd", "#8B5CF6"),
            ("🔍", "quick_search", "home_action_search_sub", self._show_search_view, "#e8fdf0", M_GREEN),
            ("🗑️", "recycle_bin", "home_action_recycle_sub", self._show_recycle_view, "#fde8e8", M_RED),
        ]:
            card = QPushButton()
            card.setObjectName("actionCard")
            card.setCursor(Qt.PointingHandCursor)
            card.setMinimumHeight(86)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            card.clicked.connect(slot)
            cl = QHBoxLayout(card)
            cl.setContentsMargins(20, 18, 20, 18)
            cl.setSpacing(14)
            icon_lbl = QLabel(icon)
            icon_lbl.setFixedSize(42, 42)
            icon_lbl.setAlignment(Qt.AlignCenter)
            icon_lbl.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:10px; font-size:20px;")
            cl.addWidget(icon_lbl)
            txt = QVBoxLayout()
            txt.setContentsMargins(0, 0, 0, 0)
            txt.setSpacing(4)
            t = self._register_text(title_key, QLabel())
            t.setObjectName("actionTitle")
            t.setFixedHeight(20)
            s = self._register_text(sub_key, QLabel())
            s.setObjectName("actionSub")
            s.setFixedHeight(16)
            txt.addWidget(t)
            txt.addWidget(s)
            cl.addLayout(txt, 1)
            actions_row.addWidget(card)
        outer.addLayout(actions_row)
        outer.addStretch()
        return page

    def _disk_pct_color(self, percent):
        if percent >= 90:
            return M_RED
        if percent >= 75:
            return M_ORANGE
        return M_ACCENT

    def _update_home_disks(self):
        """首页磁盘卡片（预览图 01 的磁盘卡片区）。"""
        while self._home_disks_row.count():
            item = self._home_disks_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        last_scan = self._last_scan_time()
        self._home_greeting_sub.setText(
            self._tr("home_greeting_sub").replace("{time}", last_scan or "—"))
        system_drive = os.environ.get("SystemDrive", "C:").upper()
        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                except OSError:
                    continue
                drive, _ = os.path.splitdrive(part.mountpoint)
                letter = drive.upper() if drive else part.mountpoint.rstrip("\\/")
                is_system = letter.upper().startswith(system_drive.rstrip(":"))
                card = QFrame()
                card.setObjectName("card")
                v = QVBoxLayout(card)
                v.setContentsMargins(22, 20, 22, 20)
                v.setSpacing(12)
                head = QHBoxLayout()
                name = QLabel(
                    f"{'💻' if is_system else '📦'}  {letter} {self._tr('home_system_drive' if is_system else 'home_data_drive')}")
                name.setObjectName("diskName")
                pct = QLabel(f"{usage.percent:.0f}%")
                pct.setObjectName("diskPct")
                color = self._disk_pct_color(usage.percent)
                pct.setStyleSheet(f"color:{color};")
                head.addWidget(name)
                head.addStretch()
                head.addWidget(pct)
                v.addLayout(head)
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(min(100, int(usage.percent)))
                bar.setTextVisible(False)
                bar.setFixedHeight(6)
                bar.setStyleSheet(
                    f"QProgressBar {{ border:0; background:{M_BORDER}; border-radius:3px; min-height:6px; max-height:6px; }}"
                    f"QProgressBar::chunk {{ background:{color}; border-radius:3px; }}")
                v.addWidget(bar)
                detail = QHBoxLayout()
                used_lbl = QLabel(self._tr("home_used").replace("{size}", format_size(usage.used)))
                used_lbl.setObjectName("diskDetail")
                total_lbl = QLabel(self._tr("home_total").replace("{size}", format_size(usage.total)))
                total_lbl.setObjectName("diskDetail")
                detail.addWidget(used_lbl)
                detail.addStretch()
                detail.addWidget(total_lbl)
                v.addLayout(detail)
                self._home_disks_row.addWidget(card)
        except Exception:
            pass

    def _last_scan_time(self):
        try:
            p = Path.home() / ".diskwise" / "last_scan.txt"
            if p.exists():
                return p.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        return ""

    def _record_scan_time(self):
        try:
            p = Path.home() / ".diskwise" / "last_scan.txt"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(time.strftime("%Y年%m月%d日 %H:%M", time.localtime()), encoding="utf-8")
        except OSError:
            pass

    # ══════════════ 回收站管理页面（Minimalism 预览图 04） ══════════════

    def _build_recycle_page(self):
        page = QWidget()
        page.setObjectName("page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 8, 8, 0)
        outer.setSpacing(16)

        # 汇总卡片
        summary_row = QHBoxLayout()
        summary_row.setSpacing(14)
        self._rb_summary_labels = {}
        for key in ("rb_files_count", "rb_space_used", "rb_oldest", "rb_new_this_week"):
            card = QFrame()
            card.setObjectName("card")
            v = QVBoxLayout(card)
            v.setContentsMargins(20, 14, 20, 14)
            v.setSpacing(6)
            lbl = self._register_text(key, QLabel())
            lbl.setObjectName("summaryLabel")
            val = QLabel("—")
            val.setObjectName("summaryValue")
            v.addWidget(lbl)
            v.addWidget(val)
            self._rb_summary_labels[key] = val
            summary_row.addWidget(card)
        outer.addLayout(summary_row)

        # 工具栏
        toolbar_row = QHBoxLayout()
        self._rb_select_all_cb = QtWidgets.QCheckBox()
        self._rb_select_all_cb.stateChanged.connect(self._rb_toggle_select_all)
        toolbar_row.addWidget(self._rb_select_all_cb)
        self._rb_selected_label = QLabel("")
        self._rb_selected_label.setStyleSheet(f"color:{M_TEXT_2}; font-size:12px;")
        toolbar_row.addWidget(self._rb_selected_label)
        toolbar_row.addStretch()
        btn_select_all = QPushButton(); self._register_text("rb_select_all", btn_select_all)
        btn_select_all.clicked.connect(lambda: self._rb_set_all(True))
        btn_deselect = QPushButton("全不选")
        btn_deselect.clicked.connect(lambda: self._rb_set_all(False))
        self._rb_btn_deselect = btn_deselect
        btn_del = QPushButton(); self._register_text("rb_delete_selected", btn_del)
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(self._rb_delete_selected)
        btn_restore = QPushButton(); self._register_text("rb_restore_selected", btn_restore)
        btn_restore.setObjectName("primary")
        btn_restore.clicked.connect(self._rb_restore_selected)
        btn_empty = QPushButton(); self._register_text("rb_empty", btn_empty)
        btn_empty.setObjectName("dangerSolid")
        btn_empty.clicked.connect(self._rb_empty_bin)
        for b in (btn_select_all, btn_deselect, btn_del, btn_restore, btn_empty):
            toolbar_row.addWidget(b)
        outer.addLayout(toolbar_row)

        # 回收站表格
        self._rb_tree = QTreeWidget()
        self._rb_tree.setColumnCount(6)
        self._rb_tree.setRootIsDecorated(False)
        self._rb_tree.setAlternatingRowColors(True)
        self._rb_tree.setUniformRowHeights(False)
        self._rb_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        h = self._rb_tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(QHeaderView.Interactive)
        self._rb_tree.setColumnWidth(0, 36)
        self._rb_tree.setColumnWidth(1, 320)
        self._rb_tree.setColumnWidth(2, 300)
        self._rb_tree.setColumnWidth(3, 90)
        self._rb_tree.setColumnWidth(4, 140)
        h.setSectionResizeMode(5, QHeaderView.Stretch)
        outer.addWidget(self._rb_tree, 1)
        return page

    def _rb_load_items(self):
        """读取回收站目录 + 元数据，填充表格和汇总卡片。"""
        self._rb_tree.clear()
        recycle_path = self.file_operations.recycle_bin_path
        entries = []
        if os.path.isdir(recycle_path):
            for name in sorted(os.listdir(recycle_path)):
                if name.endswith(".meta.json"):
                    continue
                full = os.path.join(recycle_path, name)
                try:
                    if os.path.isdir(full):
                        size = self._folder_size(full)
                    else:
                        size = os.path.getsize(full)
                    mtime = os.path.getmtime(full)
                except OSError:
                    continue
                origin = ""
                deleted_at = mtime
                meta_path = full + ".meta.json"
                if os.path.isfile(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as fh:
                            meta = json.load(fh)
                        origin = meta.get("origin_path", "")
                        deleted_at = float(meta.get("deleted_at", mtime))
                    except (OSError, ValueError):
                        pass
                entries.append({
                    "name": name, "path": full, "origin": origin,
                    "size": size, "mtime": mtime, "deleted_at": deleted_at,
                })

        now = time.time()
        total_size = sum(e["size"] for e in entries)
        oldest_days = int((now - min((e["deleted_at"] for e in entries), default=now)) / 86400) if entries else 0
        new_week = sum(1 for e in entries if now - e["deleted_at"] <= 7 * 86400)
        self._rb_summary_labels["rb_files_count"].setText(f"{len(entries):,}")
        self._rb_summary_labels["rb_space_used"].setText(format_size(total_size))
        self._rb_summary_labels["rb_oldest"].setText(
            self._tr("rb_days_ago").replace("{n}", str(oldest_days)) if entries else "—")
        self._rb_summary_labels["rb_new_this_week"].setText(str(new_week))
        self._rb_summary_labels["rb_new_this_week"].setStyleSheet(
            f"font-size:24px; font-weight:700; color:{M_RED if new_week else M_TEXT};")

        for e in entries:
            item = QTreeWidgetItem(["", e["name"], e["origin"] or "—",
                                    format_size(e["size"]), format_time(e["deleted_at"]), ""])
            item.setData(0, Qt.UserRole, e["path"])
            item.setData(1, Qt.UserRole, e["origin"])
            item.setToolTip(2, e["origin"] or "")
            self._rb_tree.addTopLevelItem(item)

            cb = QtWidgets.QCheckBox()
            cb.stateChanged.connect(lambda *_: self._rb_update_selected_label())
            self._rb_tree.setItemWidget(item, 0, cb)

            actions = QWidget()
            al = QHBoxLayout(actions)
            al.setContentsMargins(4, 2, 4, 2)
            al.setSpacing(6)
            restore_btn = QPushButton(self._tr("rb_restore"))
            restore_btn.setObjectName("success")
            restore_btn.setFixedHeight(26)
            restore_btn.clicked.connect(lambda *_u, it=item: self._rb_restore_one(it))
            delete_btn = QPushButton(self._tr("rb_permanent"))
            delete_btn.setObjectName("danger")
            delete_btn.setFixedHeight(26)
            delete_btn.clicked.connect(lambda *_u, it=item: self._rb_delete_one(it))
            al.addWidget(restore_btn)
            al.addWidget(delete_btn)
            al.addStretch()
            self._rb_tree.setItemWidget(item, 5, actions)

        self._rb_select_all_cb.blockSignals(True)
        self._rb_select_all_cb.setChecked(False)
        self._rb_select_all_cb.blockSignals(False)
        self._rb_update_selected_label()

    def _rb_checkbox(self, item):
        w = self._rb_tree.itemWidget(item, 0)
        return w if isinstance(w, QtWidgets.QCheckBox) else None

    def _rb_checked_items(self):
        return [self._rb_tree.topLevelItem(i) for i in range(self._rb_tree.topLevelItemCount())
                if (cb := self._rb_checkbox(self._rb_tree.topLevelItem(i))) and cb.isChecked()]

    def _rb_update_selected_label(self):
        n = len(self._rb_checked_items())
        self._rb_selected_label.setText(self._tr("rb_selected_n").replace("{n}", str(n)))

    def _rb_toggle_select_all(self, state):
        self._rb_set_all(state == Qt.Checked)

    def _rb_set_all(self, checked):
        for i in range(self._rb_tree.topLevelItemCount()):
            cb = self._rb_checkbox(self._rb_tree.topLevelItem(i))
            if cb:
                cb.blockSignals(True)
                cb.setChecked(checked)
                cb.blockSignals(False)
        self._rb_update_selected_label()

    def _rb_restore_one(self, item):
        path = item.data(0, Qt.UserRole)
        origin = item.data(1, Qt.UserRole) or ""
        if not path or not os.path.lexists(path):
            QMessageBox.warning(self, "恢复失败", "该项目已不存在。")
            return
        name = os.path.basename(path.rstrip(os.sep))
        if origin:
            target_dir = os.path.dirname(origin)
            target = origin
        else:
            target_dir = os.path.join(os.path.expanduser("~"), "Desktop")
            target = os.path.join(target_dir, name)
        if os.path.exists(target) and QMessageBox.question(
                self, "恢复确认", f"目标位置已存在同名文件：\n{target}\n\n覆盖它吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        ok, msg = self.file_ops.restore_from_recycle_bin(path, target)
        if ok:
            # 清理元数据文件
            try:
                os.remove(path + ".meta.json")
            except OSError:
                pass
            self._rb_load_items()
        else:
            QMessageBox.critical(self, "恢复失败", msg)

    def _rb_restore_selected(self):
        items = self._rb_checked_items()
        if not items:
            QMessageBox.information(self, "提示", "请先勾选要恢复的项目")
            return
        for item in items:
            self._rb_restore_one(item)

    def _rb_delete_one(self, item):
        path = item.data(0, Qt.UserRole)
        if not path:
            return
        name = os.path.basename(path.rstrip(os.sep))
        if QMessageBox.question(
                self, "确认永久删除",
                f"永久删除后无法恢复：\n{name}\n\n确定继续吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            try:
                os.remove(path + ".meta.json")
            except OSError:
                pass
            self._rb_load_items()
        except Exception as exc:
            QMessageBox.critical(self, "删除失败", str(exc))

    def _rb_delete_selected(self):
        items = self._rb_checked_items()
        if not items:
            QMessageBox.information(self, "提示", "请先勾选要删除的项目")
            return
        if QMessageBox.question(
                self, "确认永久删除",
                f"将永久删除选中的 {len(items)} 个项目，此操作不可恢复。\n\n确定继续吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        for item in items:
            path = item.data(0, Qt.UserRole)
            try:
                if path and os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                elif path:
                    os.remove(path)
                try:
                    os.remove(path + ".meta.json")
                except OSError:
                    pass
            except Exception:
                continue
        self._rb_load_items()

    def _rb_empty_bin(self):
        if self._rb_tree.topLevelItemCount() == 0:
            QMessageBox.information(self, "提示", self._tr("rb_empty_bin"))
            return
        if QMessageBox.question(
                self, "清空回收站", "确定清空回收站中的全部项目吗？\n此操作不可恢复。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        ok, msg = self.file_ops.empty_recycle_bin()
        (QMessageBox.information if ok else QMessageBox.critical)(self, "清空回收站", msg)
        self._rb_load_items()

    def _build_detail_page(self):
        """构建文件详情页面（左侧元数据 + 右侧预览）"""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        
        # 左侧：文件元数据
        card = QFrame()
        card.setObjectName("card")
        detail = QVBoxLayout(card)
        detail.setContentsMargins(24, 20, 24, 20)
        detail.setSpacing(12)
        
        t = self._register_text("detail_title", QLabel())
        t.setObjectName("sectionTitle")
        detail.addWidget(t)
        
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        self._info_labels = {}
        rows = [
            ("name", "name"), ("full_path", "path"), ("size", "size"), ("mtime", "mtime"),
            ("item_type", "ftype"), ("source", "sync"), ("relation", "relation"),
            ("default_app", "assoc"), ("confidence", "confidence"), ("evidence", "evidence"),
            ("delete_advice", "advice")
        ]
        for row, (label_key, key) in enumerate(rows):
            left = self._register_text(label_key, QLabel())
            left.setObjectName("key")
            value = QLabel("—")
            value.setObjectName("value")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(left, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1)
            self._info_labels[key] = value
        grid.setColumnStretch(1, 1)
        detail.addLayout(grid)
        
        actions = QGridLayout()
        actions.setSpacing(10)
        self._btn_identify = self._register_text("identify", self._button("", QtWidgets.QStyle.SP_FileLinkIcon, self._query_association, "action"))
        self._btn_online = self._register_text("online", self._button("", QtWidgets.QStyle.SP_DriveNetIcon, self._online_verify, "action"))
        self._btn_open = self._register_text("open_location", self._button("", QtWidgets.QStyle.SP_DirOpenIcon, self._open_containing_folder, "action"))
        self._btn_delete = self._register_text("move_recycle", self._button("", QtWidgets.QStyle.SP_TrashIcon, self._delete_selected, "deleteAction"))
        for button in (self._btn_identify, self._btn_online, self._btn_open, self._btn_delete):
            button.setMinimumHeight(42)
        actions.addWidget(self._btn_identify, 0, 0)
        actions.addWidget(self._btn_online, 0, 1)
        actions.addWidget(self._btn_open, 1, 0)
        actions.addWidget(self._btn_delete, 1, 1)
        detail.addLayout(actions)
        detail.addStretch()
        layout.addWidget(card, 1)
        
        # 右侧：文档预览
        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(24, 20, 24, 20)
        preview_layout.setSpacing(12)
        
        preview_title = self._register_text("preview_title", QLabel())
        preview_title.setObjectName("sectionTitle")
        preview_layout.addWidget(preview_title)
        
        self._detail_preview_text = QtWidgets.QPlainTextEdit()
        self._detail_preview_text.setReadOnly(True)
        self._detail_preview_text.setStyleSheet(
            "QPlainTextEdit { background:#fafbfc; border:1px solid #e1e5ea; border-radius:6px; "
            "font-family:Consolas,'Microsoft YaHei',monospace; font-size:13px; }"
        )
        self._detail_preview_text.setPlaceholderText(self._tr("preview_hint"))
        preview_layout.addWidget(self._detail_preview_text, 1)
        
        layout.addWidget(preview_card, 1)
        return page

    def _build_scan_page(self):
        page = QWidget(); outer = QVBoxLayout(page); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(12)
        controls = QFrame(); controls.setObjectName("card"); c = QVBoxLayout(controls); c.setContentsMargins(18, 14, 18, 14)
        row1 = QHBoxLayout(); self._scan_path_label = QLabel(self._scan_path); self._scan_path_label.setObjectName("pathBar"); self._scan_path_label.setToolTip(self._scan_path); row1.addWidget(self._scan_path_label, 1)
        current = self._register_text("current_dir", QPushButton()); current.clicked.connect(self._scan_use_current)
        drive = self._register_text("current_drive", QPushButton()); drive.clicked.connect(self._scan_use_drive)
        choose = self._register_text("choose_dir", QPushButton()); choose.clicked.connect(self._scan_choose_folder)
        row1.addWidget(current); row1.addWidget(drive); row1.addWidget(choose); c.addLayout(row1)
        row2 = QHBoxLayout(); row2.addWidget(self._register_text("min_size", QLabel())); self._threshold = TriangleDoubleSpinBox(); self._threshold.setObjectName("thresholdSpin"); self._threshold.setRange(0, 102400); self._threshold.setValue(100); self._threshold.setDecimals(0); self._threshold.setButtonSymbols(QAbstractSpinBox.UpDownArrows); row2.addWidget(self._threshold)
        row2.addWidget(self._register_text("max_results", QLabel())); self._top_n = TriangleSpinBox(); self._top_n.setObjectName("topNSpin"); self._top_n.setRange(10, 2000); self._top_n.setValue(100); self._top_n.setButtonSymbols(QAbstractSpinBox.UpDownArrows); row2.addWidget(self._top_n)
        self._scan_start = self._register_text("start_scan", self._button("", QtWidgets.QStyle.SP_MediaPlay, self._start_scan, "primary"))
        self._scan_cancel = self._register_text("cancel_scan", self._button("", QtWidgets.QStyle.SP_MediaStop, self._cancel_scan)); self._scan_cancel.setEnabled(False)
        row2.addWidget(self._scan_start); row2.addWidget(self._scan_cancel); row2.addStretch(); c.addLayout(row2)
        self._scan_progress = QProgressBar(); self._scan_progress.setRange(0, 1); self._scan_progress.setValue(0); self._scan_progress.setFixedHeight(10); self._scan_progress.setTextVisible(False); c.addWidget(self._scan_progress)
        self._scan_status = self._register_text("scan_intro", QLabel()); self._scan_status.setWordWrap(True); self._scan_status.setMinimumHeight(40); c.addWidget(self._scan_status); outer.addWidget(controls)

        results = QTabWidget(); self._large_files = self._result_tree(["名称", "实际占用", "逻辑大小", "修改时间", "来源软件", "完整路径"])
        self._large_folders = self._result_tree(["文件夹", "实际占用", "逻辑大小", "文件数", "子文件夹数", "来源软件", "完整路径"])
        self._suggestions = self._result_tree(["建议等级", "名称", "可释放空间", "原因", "风险", "完整路径"])
        self._garbage_files = self._result_tree(["类别", "名称", "实际占用", "修改时间", "建议", "风险", "完整路径"])
        self._scan_result_tabs = results
        
        results.addTab(self._large_files, ""); results.addTab(self._large_folders, ""); results.addTab(self._suggestions, ""); results.addTab(self._garbage_files, "")
        outer.addWidget(results, 1)
        actions = QHBoxLayout(); actions.addStretch()
        open_btn = self._register_text("open_location", QPushButton()); open_btn.clicked.connect(self._open_scan_result)
        copy_btn = self._register_text("copy_path", QPushButton()); copy_btn.clicked.connect(self._copy_scan_result)
        delete_btn = self._register_text("move_recycle", QPushButton()); delete_btn.setObjectName("danger"); delete_btn.clicked.connect(self._delete_scan_result)
        clean_btn = self._register_text("clean_selected", QPushButton()); clean_btn.setObjectName("danger"); clean_btn.clicked.connect(self._clean_junk_selected)
        actions.addWidget(open_btn); actions.addWidget(copy_btn); actions.addWidget(clean_btn); actions.addWidget(delete_btn); outer.addLayout(actions)
        return page

    def _build_visualization_page(self):
        """构建独立的空间可视化页面 - 无大小和数量限制，显示所有文件"""
        page = QWidget()
        page.setObjectName("page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        # 控制面板
        controls = QFrame()
        controls.setObjectName("card")
        c = QVBoxLayout(controls)
        c.setContentsMargins(18, 14, 18, 14)

        # 路径选择行
        row1 = QHBoxLayout()
        self._viz_path_label = QLabel(self._scan_path)
        self._viz_path_label.setObjectName("pathBar")
        self._viz_path_label.setToolTip(self._scan_path)
        row1.addWidget(self._viz_path_label, 1)

        current = QPushButton()
        self._register_text("current_dir", current)
        current.clicked.connect(self._viz_use_current)
        drive = QPushButton()
        self._register_text("current_drive", drive)
        drive.clicked.connect(self._viz_use_drive)
        choose = QPushButton()
        self._register_text("choose_dir", choose)
        choose.clicked.connect(self._viz_choose_folder)

        row1.addWidget(current)
        row1.addWidget(drive)
        row1.addWidget(choose)
        c.addLayout(row1)

        # 操作按钮行（无阈值和数量限制）
        row2 = QHBoxLayout()
        intro = QLabel()
        self._register_text("visualization_intro", intro)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{M_TEXT_2}; font-size:12px;")
        row2.addWidget(intro, 1)

        self._viz_start = QPushButton()
        self._register_text("start_scan", self._viz_start)
        self._viz_start.setObjectName("primary")
        self._viz_start.setCursor(Qt.PointingHandCursor)
        self._viz_start.clicked.connect(self._start_visualization)
        self._viz_cancel = QPushButton()
        self._register_text("cancel_scan", self._viz_cancel)
        self._viz_cancel.setCursor(Qt.PointingHandCursor)
        self._viz_cancel.clicked.connect(self._cancel_visualization)
        self._viz_cancel.setEnabled(False)

        row2.addWidget(self._viz_start)
        row2.addWidget(self._viz_cancel)
        c.addLayout(row2)

        # 进度条
        self._viz_progress = QProgressBar()
        self._viz_progress.setRange(0, 1)
        self._viz_progress.setValue(0)
        self._viz_progress.setFixedHeight(10)
        self._viz_progress.setTextVisible(False)
        c.addWidget(self._viz_progress)

        # 状态文字
        self._viz_status = QLabel()
        self._viz_status.setWordWrap(True)
        self._viz_status.setMinimumHeight(24)
        self._viz_status.setStyleSheet(f"color:{M_TEXT_3}; font-size:11px;")
        c.addWidget(self._viz_status)

        outer.addWidget(controls)

        # Treemap 可视化区域
        viz_container = QWidget()
        viz_layout = QVBoxLayout(viz_container)
        viz_layout.setContentsMargins(0, 0, 0, 0)
        viz_layout.setSpacing(8)
        
        # 面包屑导航栏
        breadcrumb_bar = QHBoxLayout()
        self._viz_back_btn = QPushButton("⬆ 返回上级")
        self._viz_back_btn.setEnabled(False)
        self._viz_back_btn.setCursor(Qt.PointingHandCursor)
        self._viz_back_btn.clicked.connect(self._viz_go_back)
        breadcrumb_bar.addWidget(self._viz_back_btn)
        
        self._viz_breadcrumb = QLabel("📁 根目录")
        self._viz_breadcrumb.setStyleSheet("font-weight: 500; color: #333;")
        breadcrumb_bar.addWidget(self._viz_breadcrumb)
        breadcrumb_bar.addStretch()
        viz_layout.addLayout(breadcrumb_bar)
        
        # Treemap 组件
        self._viz_treemap = TreemapWidget()
        viz_layout.addWidget(self._viz_treemap, 1)
        
        # 图例栏
        legend_frame = QFrame()
        legend_frame.setStyleSheet(
            f"QFrame {{ background:{M_CARD_SOFT}; border-radius:8px; border:1px solid {M_BORDER}; }}")
        legend_bar = QHBoxLayout(legend_frame)
        legend_bar.setContentsMargins(14, 8, 14, 8)
        legend_bar.setSpacing(16)
        legend_title = QLabel("颜色说明：")
        legend_title.setStyleSheet(f"color:{M_TEXT_2}; font-size:12px;")
        legend_bar.addWidget(legend_title)
        for _threshold, color, label in [(">10GB", "#B45078", "> 10 GB"),
                                         ("1-10GB", "#4FACFE", "1–10 GB"),
                                         ("100MB-1GB", "#43E97B", "100 MB–1 GB"),
                                         ("10-100MB", "#FA709A", "10–100 MB"),
                                         ("<10MB", "#A8EDEA", "< 10 MB")]:
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background:{color}; border-radius:3px;")
            legend_bar.addWidget(swatch)
            text_label = QLabel(label)
            text_label.setStyleSheet(f"color:{M_TEXT}; font-size:11px;")
            legend_bar.addWidget(text_label)
        legend_bar.addStretch()
        viz_layout.addWidget(legend_frame)
        
        outer.addWidget(viz_container, 1)
        return page

    def _result_tree(self, headers):
        tree = QTreeWidget(); tree.setHeaderLabels(headers); tree.setAlternatingRowColors(True); tree.setTextElideMode(Qt.ElideMiddle)
        tree.header().setSectionResizeMode(QHeaderView.ResizeToContents); tree.header().setStretchLastSection(True)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(lambda pos, target=tree: self._on_scan_context_menu(target, pos))
        tree.itemDoubleClicked.connect(lambda *_: self._open_scan_result()); return tree

    def _build_search_page(self):
        """构建快速搜索页面（Minimalism 预览图 02：文件名/内容搜索 + 格式 chips + 预览）。"""
        page = QWidget()
        page.setObjectName("page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 8, 8, 0)
        outer.setSpacing(14)

        # ── 搜索控制区 ──
        controls = QFrame(); controls.setObjectName("card")
        c = QVBoxLayout(controls); c.setContentsMargins(20, 16, 20, 16); c.setSpacing(12)

        # 搜索模式标签（下划线式）
        self._search_tabs = SearchModeTabs(["📁 文件名搜索", "📄 内容搜索"])
        self._search_tabs.currentChanged.connect(self._on_search_tab_changed)
        c.addWidget(self._search_tabs)

        # 搜索框（图标 + 输入 + 清除按钮）
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        icon_lbl = QLabel("🔍")
        icon_lbl.setStyleSheet(f"color:{M_TEXT_3}; font-size:16px; padding:0 2px;")
        search_row.addWidget(icon_lbl)
        self._search_input = QtWidgets.QLineEdit()
        self._search_input.setPlaceholderText("输入关键词搜索文件...")
        self._search_input.setMinimumHeight(38)
        self._search_input.textChanged.connect(self._on_search_query_changed)
        search_row.addWidget(self._search_input, 1)
        self._search_clear_btn = QPushButton("✕")
        self._search_clear_btn.setFixedSize(30, 30)
        self._search_clear_btn.setStyleSheet(f"QPushButton {{ border:none; color:{M_TEXT_3}; font-size:15px; background:transparent; }} QPushButton:hover {{ color:{M_TEXT_2}; }}")
        self._search_clear_btn.clicked.connect(lambda: self._search_input.clear())
        search_row.addWidget(self._search_clear_btn)
        c.addLayout(search_row)

        # 文件格式 chips
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        self._format_chips = []
        for text in ["全部格式", "文档", "图片", "视频", "压缩包", "文件夹"]:
            chip = QPushButton(text)
            chip.setObjectName("chip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, t=text: self._on_format_chip_clicked(t))
            self._format_chips.append(chip)
            chip_row.addWidget(chip)
        self._active_format = "全部格式"
        self._format_chips[0].setProperty("class", "active")
        chip_row.addStretch()
        c.addLayout(chip_row)

        # 搜索范围 + 索引状态
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("搜索范围："))
        self._search_scope_combo = QComboBox()
        self._search_scope_combo.addItems(["🌐 全局搜索", "📂 当前目录", "📂 选择目录..."])
        self._search_scope_combo.setFixedWidth(150)
        self._search_scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        filter_row.addWidget(self._search_scope_combo)
        filter_row.addSpacing(16)

        index_dot = QLabel()
        index_dot.setObjectName("indexDot")
        self._index_dot = index_dot
        filter_row.addWidget(index_dot)
        self._index_status_label = QLabel(self._tr("index_none"))
        self._index_status_label.setStyleSheet(f"color:{M_GREEN}; font-size:12px;")
        filter_row.addWidget(self._index_status_label)
        filter_row.addStretch()

        self._refresh_index_btn = QPushButton("🔄 刷新索引")
        self._refresh_index_btn.setFixedHeight(28)
        self._refresh_index_btn.clicked.connect(self._refresh_index)
        self._refresh_index_btn.setEnabled(False)
        filter_row.addWidget(self._refresh_index_btn)
        self._rebuild_index_btn = QPushButton("🔨 重建索引")
        self._rebuild_index_btn.setFixedHeight(28)
        self._rebuild_index_btn.clicked.connect(self._rebuild_index)
        self._rebuild_index_btn.setEnabled(False)
        self._rebuild_index_btn.setStyleSheet(f"QPushButton {{ color:{M_ORANGE}; border:1px solid {M_ORANGE}; }} QPushButton:hover {{ background:#fef5ec; }}")
        filter_row.addWidget(self._rebuild_index_btn)
        self._cancel_index_btn = self._register_text("index_cancel", self._button("", QtWidgets.QStyle.SP_DialogCancelButton, self._cancel_index))
        self._cancel_index_btn.setFixedHeight(28)
        self._cancel_index_btn.setEnabled(False)
        filter_row.addWidget(self._cancel_index_btn)
        c.addLayout(filter_row)

        self._search_progress = QProgressBar()
        self._search_progress.setRange(0, 1)
        self._search_progress.setValue(0)
        self._search_progress.setVisible(False)
        c.addWidget(self._search_progress)

        outer.addWidget(controls)

        # ── 搜索结果 + 预览（左右分栏） ──
        split = QtWidgets.QSplitter(Qt.Horizontal)

        left = QFrame(); left.setObjectName("card")
        left_layout = QVBoxLayout(left); left_layout.setContentsMargins(14, 12, 14, 12)
        self._search_result_count = QLabel("")
        self._search_result_count.setStyleSheet(f"color:{M_TEXT_3}; font-size:12px; padding-bottom:4px;")
        left_layout.addWidget(self._search_result_count)
        self._search_filter_hint_btn = QPushButton("正在仅搜索文件夹；点击查看全部文件和文件夹")
        self._search_filter_hint_btn.setFlat(True)
        self._search_filter_hint_btn.setCursor(Qt.PointingHandCursor)
        self._search_filter_hint_btn.setStyleSheet(
            f"QPushButton {{ color:{M_ACCENT}; text-align:left; padding:0 0 6px 0; }}")
        self._search_filter_hint_btn.clicked.connect(
            lambda: self._on_format_chip_clicked("全部格式"))
        self._search_filter_hint_btn.setVisible(False)
        left_layout.addWidget(self._search_filter_hint_btn)
        self._search_result_tree = QTreeWidget()
        self._search_result_tree.setHeaderLabels([
            self._tr("name"), self._tr("size"), self._tr("mtime"), "文件类型", self._tr("full_path")])
        self._search_result_tree.setAlternatingRowColors(True)
        self._search_result_tree.setTextElideMode(Qt.ElideMiddle)
        self._search_result_tree.header().setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        self._search_result_tree.header().setStretchLastSection(True)
        self._search_result_tree.setSortingEnabled(True)
        self._search_result_tree.header().setSortIndicatorShown(True)
        self._search_result_tree.itemClicked.connect(self._on_search_result_clicked)
        self._search_result_tree.itemDoubleClicked.connect(self._on_search_result_double_clicked)
        self._search_result_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._search_result_tree.customContextMenuRequested.connect(self._on_search_result_context_menu)
        left_layout.addWidget(self._search_result_tree, 1)
        self._search_load_more_btn = QPushButton("加载更多 / Load more")
        self._search_load_more_btn.clicked.connect(self._load_more_name_results)
        self._search_load_more_btn.setVisible(False)
        left_layout.addWidget(self._search_load_more_btn)
        split.addWidget(left)

        right = QFrame(); right.setObjectName("card")
        right.setMinimumWidth(300)
        right_layout = QVBoxLayout(right); right_layout.setContentsMargins(16, 14, 16, 14)
        preview_title = self._register_text("preview_title", QLabel())
        preview_title.setObjectName("sectionTitle")
        right_layout.addWidget(preview_title)
        self._preview_text = QtWidgets.QTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setPlaceholderText(self._tr("preview_hint"))
        right_layout.addWidget(self._preview_text, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        outer.addWidget(split, 1)
        return page

    def _on_format_chip_clicked(self, text):
        """格式 chip 点击：更新激活状态并重新搜索。"""
        self._active_format = text
        for chip in self._format_chips:
            active = chip.text() == text
            chip.setProperty("class", "active" if active else "")
            chip.style().unpolish(chip)
            chip.style().polish(chip)
        if self._search_input.text().strip():
            self._do_search()

    def _get_search_filters(self):
        """获取当前搜索过滤条件。"""
        scope_index = self._search_scope_combo.currentIndex()
        path_filter = ""
        if scope_index == 1:
            path_filter = self.current_path
        elif scope_index == 2:
            text = self._search_scope_combo.itemText(2)
            if text.startswith("📂 "):
                path_filter = text[2:]
        ext_map = {
            "文档": ".pdf,.docx,.xlsx,.pptx,.txt",
            "图片": ".jpg,.jpeg,.png,.gif,.bmp,.webp",
            "视频": ".mp4,.avi,.mkv,.mov,.wmv",
            "压缩包": ".zip,.rar,.7z,.tar,.gz",
        }
        ext_filter = ext_map.get(self._active_format, "")
        is_dir_filter = True if self._active_format == "文件夹" else None
        return path_filter, ext_filter, is_dir_filter

    def _show_search_tab(self):
        """兼容旧引用"""
        self._show_search_view()

    def _on_search_mode_changed(self, index):
        """搜索模式切换（文件名/内容）- 兼容旧调用"""
        self._on_search_tab_changed(index)

    def _on_search_tab_changed(self, index):
        """搜索标签页切换（文件名/内容）"""
        if index == 0:
            self._search_input.setPlaceholderText("输入文件名搜索，支持通配符 * 和 ?")
        else:
            self._search_input.setPlaceholderText("输入文档内容关键词搜索...")
            # 内容提取远比文件名索引耗时，只在用户首次进入该页时启动。
            if ((not self.fulltext_search_engine.is_indexed or
                 self.fulltext_search_engine.needs_full_disk_refresh) and
                    not self.fulltext_search_engine.is_indexing()):
                # 文件内容索引默认覆盖所有可访问磁盘，和文件名搜索一致。
                thread = self.fulltext_search_engine.start_indexing(force_reindex=False)
                thread.progress_signal.connect(self._on_content_index_progress)
                thread.finished_signal.connect(self._on_content_index_finished)
                thread.cancelled_signal.connect(self._on_content_index_cancelled)
                thread.error_signal.connect(
                    lambda msg: QMessageBox.warning(self, "索引错误", msg))
        # 切换后自动重新搜索
        if self._search_input.text().strip():
            self._do_search()

    def _on_scope_changed(self, index):
        """搜索范围变化"""
        if index == 2:  # 选择目录
            folder = QFileDialog.getExistingDirectory(self, "选择搜索目录", self.current_path)
            if folder:
                self._search_scope_combo.setItemText(2, f"📂 {folder}")
            else:
                self._search_scope_combo.setCurrentIndex(0)
        # 范围变化后重新搜索
        if self._search_input.text().strip():
            self._do_search()

    def _on_search_query_changed(self, text):
        """输入变化时启动防抖定时器（300ms）"""
        if self._search_timer:
            self._search_timer.stop()
        self._search_timer = QtCore.QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        self._search_timer.start(300)

    def _do_search(self):
        """执行搜索"""
        if self._search_timer:
            self._search_timer.stop()

        query = self._search_input.text().strip()
        if not query:
            self._search_result_tree.clear()
            self._search_result_count.setText("")
            self._search_filter_hint_btn.setVisible(False)
            self._search_load_more_btn.setVisible(False)
            self._preview_text.clear()
            return

        mode = self._search_tabs.currentIndex()
        if mode == 0:
            self._do_name_search(query)
        else:
            self._do_content_search(query)

    def _do_name_search(self, query):
        """文件名搜索"""
        if not self.quick_search_engine.is_indexed:
            self._search_result_count.setText(self._tr("index_none"))
            self._search_result_tree.clear()
            self._search_load_more_btn.setVisible(False)
            return

        path_filter, ext_filter, is_dir_filter = self._get_search_filters()
        total_count = self.quick_search_engine.count_search_results(
            query, path_filter=path_filter, ext_filter=ext_filter,
            is_dir_filter=is_dir_filter)
        results = self.quick_search_engine.search(
            query, max_results=5000,
            path_filter=path_filter, ext_filter=ext_filter,
            is_dir_filter=is_dir_filter)
        self._populate_search_results(results, total_count=total_count)

    def _load_more_name_results(self):
        """分批追加文件名结果，最终可查看全部命中而不阻塞界面。"""
        query = self._search_input.text().strip()
        if not query or self._search_tabs.currentIndex() != 0:
            return
        path_filter, ext_filter, is_dir_filter = self._get_search_filters()
        offset = self._search_result_tree.topLevelItemCount()
        total_count = self.quick_search_engine.count_search_results(
            query, path_filter=path_filter, ext_filter=ext_filter,
            is_dir_filter=is_dir_filter)
        results = self.quick_search_engine.search(
            query, max_results=5000, offset=offset,
            path_filter=path_filter, ext_filter=ext_filter,
            is_dir_filter=is_dir_filter)
        self._populate_search_results(
            results, total_count=total_count, append=True)

    def _do_content_search(self, query):
        """内容搜索"""
        self._search_load_more_btn.setVisible(False)
        if not self.fulltext_search_engine.is_indexed:
            self._search_result_count.setText(self._tr("index_none"))
            self._search_result_tree.clear()
            return

        path_filter, ext_filter, is_dir_filter = self._get_search_filters()
        if is_dir_filter:
            self._populate_search_results([], is_content=True)
            return
        results = self.fulltext_search_engine.search(query, max_results=200, path_filter=path_filter, ext_filter=ext_filter)
        self._populate_search_results(results, is_content=True)

    def _populate_search_results(self, results, is_content=False,
                                 total_count=None, append=False):
        """填充搜索结果到树控件"""
        if not append:
            self._search_result_tree.clear()

        if not results:
            if not append:
                folder_only = (not is_content and self._active_format == "文件夹")
                self._search_result_count.setText(
                    "未找到匹配的文件夹" if folder_only else self._tr("no_results"))
                self._search_filter_hint_btn.setVisible(folder_only)
            self._search_load_more_btn.setVisible(False)
            return

        self._search_filter_hint_btn.setVisible(False)

        for item_data in results:
            path = item_data.get("path", "")
            name = item_data.get("name", os.path.basename(path))
            size = item_data.get("size", 0)
            mtime = item_data.get("mtime", 0)
            snippet = item_data.get("snippet", "")
            is_dir = bool(item_data.get("is_dir", False))
            ext = item_data.get("ext", "")

            display_name = name
            if is_content and snippet:
                # 内容搜索显示 snippet 作为 tooltip
                display_name = name

            # 格式化修改时间
            mtime_str = format_time(mtime) if mtime else ""
            file_type = "文件夹" if is_dir else (f"{ext.upper().lstrip('.')} 文件" if ext else "文件")

            tree_item = QTreeWidgetItem([
                display_name,
                format_size(size),
                mtime_str,
                file_type,
                path
            ])
            tree_item.setData(0, Qt.UserRole, path)
            tree_item.setData(0, Qt.UserRole + 1, snippet if is_content else "")
            tree_item.setData(2, Qt.UserRole + 2, mtime)  # 存储原始时间戳用于排序
            tree_item.setToolTip(0, snippet if is_content else path)
            tree_item.setToolTip(4, path)
            self._search_result_tree.addTopLevelItem(tree_item)

        displayed = self._search_result_tree.topLevelItemCount()
        if total_count is not None and total_count > displayed:
            count_text = f"找到 {total_count} 项，已显示 {displayed} 项"
        else:
            count_text = self._tr("result_count").replace(
                "{count}", str(total_count if total_count is not None else displayed))
        self._search_result_count.setText(count_text)
        self._search_load_more_btn.setVisible(
            not is_content and total_count is not None and displayed < total_count)

    def _on_search_result_clicked(self, item, column):
        """点击搜索结果时预览内容，并高亮搜索关键词"""
        path = item.data(0, Qt.UserRole)
        snippet = item.data(0, Qt.UserRole + 1)
        if not path:
            return

        # 获取当前搜索关键词
        query = self._search_input.text().strip()

        # 内容搜索模式：优先显示完整文件内容（高亮关键词）
        mode = self._search_tabs.currentIndex()
        if mode == 1:
            # 内容搜索 — 提取完整文件内容并高亮
            if self.content_extractor.can_extract(path):
                try:
                    content = self.content_extractor.extract_preview(path, max_chars=10000)
                    if content:
                        self._preview_text.setHtml(self._highlight_html(content[:10000], query))
                    else:
                        self._preview_text.setPlainText(self._tr("preview_no_support"))
                except Exception as e:
                    self._preview_text.setPlainText(f"预览失败: {e}")
            else:
                self._preview_text.setPlainText(self._tr("preview_no_support"))
            return

        # 文件名搜索模式：提取文件内容预览
        if self.content_extractor.can_extract(path):
            try:
                content = self.content_extractor.extract_preview(path, max_chars=8000)
                if content:
                    self._preview_text.setHtml(self._highlight_html(content[:8000], query))
                else:
                    self._preview_text.setPlainText(self._tr("preview_no_support"))
            except Exception as e:
                self._preview_text.setPlainText(f"预览失败: {e}")
        else:
            self._preview_text.setPlainText(self._tr("preview_no_support"))

    def _highlight_html(self, text: str, keyword: str) -> str:
        """将文本转为 HTML，并用黄色背景高亮关键词。"""
        if not keyword:
            # 无关键词时，转义纯文本返回
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        # 先转义 HTML 特殊字符
        import html as html_mod
        escaped = html_mod.escape(text)
        # 转义关键词中的特殊字符用于正则
        keyword_esc = re.escape(keyword)
        # 大小写不敏感替换，用 <span> 标记高亮
        pattern = re.compile(keyword_esc, re.IGNORECASE)
        escaped = pattern.sub(
            lambda m: f'<span style="background-color:#fff3b0; color:#d44900; font-weight:600;">{m.group(0)}</span>',
            escaped
        )
        # 换行转 <br>
        escaped = escaped.replace("\n", "<br>")
        return escaped

    def _on_search_result_double_clicked(self, item, column):
        """双击后使用系统默认程序打开文件，目录则直接进入。"""
        path = item.data(0, Qt.UserRole)
        if path:
            self._open_search_result(path)

    def _open_search_result(self, path):
        """按 Windows 文件关联打开搜索结果。"""
        if not os.path.exists(path):
            QMessageBox.warning(self, "打开失败", "该项目已不存在，请刷新索引。")
            return
        try:
            os.startfile(path)
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e))

    def _open_search_result_with(self, path):
        """显示 Windows 的“打开方式”选择窗口。"""
        if not os.path.isfile(path):
            QMessageBox.information(self, "打开方式", "只有文件可以选择打开方式。")
            return
        try:
            subprocess.Popen(
                ["rundll32.exe", "shell32.dll,OpenAs_RunDLL", path],
                close_fds=True,
            )
        except Exception as e:
            QMessageBox.warning(self, "打开方式失败", str(e))

    def _set_search_result_clipboard(self, path, cut=False):
        """把项目按资源管理器兼容格式放入剪贴板，支持粘贴复制或移动。"""
        if not os.path.exists(path):
            QMessageBox.warning(self, "操作失败", "该项目已不存在，请刷新索引。")
            return
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(path)])
        mime.setText(path)
        # Windows Shell 的 Preferred DropEffect：1=复制，2=移动（剪切）。
        effect = 2 if cut else 1
        mime.setData(
            'application/x-qt-windows-mime;value="Preferred DropEffect"',
            QtCore.QByteArray(effect.to_bytes(4, byteorder="little")),
        )
        QtWidgets.QApplication.clipboard().setMimeData(mime)
        # Windows 原生剪贴板会延后提交 MIME 数据；立即处理一次事件，确保
        # 随后的资源管理器粘贴或连续复制/剪切能取得正确的 DropEffect。
        QtWidgets.QApplication.processEvents()

    def _on_search_result_context_menu(self, pos):
        """搜索结果右键菜单"""
        item = self._search_result_tree.itemAt(pos)
        if not item:
            return
        path = item.data(0, Qt.UserRole)
        if not path:
            return

        menu = QMenu(self)
        open_action = menu.addAction(self._tr("open_item"))
        open_with_action = menu.addAction(self._tr("open_with"))
        open_with_action.setEnabled(os.path.isfile(path))
        menu.addSeparator()
        copy_item_action = menu.addAction(self._tr("copy_item"))
        cut_item_action = menu.addAction(self._tr("cut_item"))
        menu.addSeparator()
        open_folder_action = menu.addAction(
            self._icon(QtWidgets.QStyle.SP_DirOpenIcon), self._tr("open_folder"))
        copy_path_action = menu.addAction(
            self._icon(QtWidgets.QStyle.SP_DialogSaveButton), self._tr("copy_path"))
        delete_action = menu.addAction(self._icon(QtWidgets.QStyle.SP_TrashIcon), self._tr("move_recycle"))

        chosen = menu.exec_(self._search_result_tree.viewport().mapToGlobal(pos))
        if chosen == open_action:
            self._open_search_result(path)
        elif chosen == open_with_action:
            self._open_search_result_with(path)
        elif chosen == copy_item_action:
            self._set_search_result_clipboard(path, cut=False)
        elif chosen == cut_item_action:
            self._set_search_result_clipboard(path, cut=True)
        elif chosen == open_folder_action:
            try:
                if os.path.isdir(path):
                    os.startfile(path)
                else:
                    os.startfile(os.path.dirname(path))
            except Exception as e:
                QMessageBox.warning(self, "打开失败", str(e))
        elif chosen == copy_path_action:
            QtWidgets.QApplication.clipboard().setText(path)
        elif chosen == delete_action:
            self._delete_path(path)

    def _refresh_index(self):
        """刷新索引（增量更新）"""
        mode = self._search_tabs.currentIndex()

        if mode == 0:
            # 文件名索引
            if self.quick_search_engine.is_indexing():
                return
            self._search_progress.setVisible(True)
            self._search_progress.setRange(0, 0)
            self._index_status_label.setText(self._tr("index_building"))
            self._refresh_index_btn.setEnabled(False)
            self._rebuild_index_btn.setEnabled(False)
            self._cancel_index_btn.setEnabled(True)

            thread = self.quick_search_engine.start_indexing(incremental=True)
            thread.progress_signal.connect(self._on_name_index_progress)
            thread.finished_signal.connect(self._on_name_index_finished)
            thread.cancelled_signal.connect(self._on_name_index_cancelled)
            thread.error_signal.connect(lambda msg: QMessageBox.warning(self, "索引错误", msg))
        else:
            # 内容索引
            if self.fulltext_search_engine.is_indexing():
                return
            self._search_progress.setVisible(True)
            self._search_progress.setRange(0, 0)
            self._index_status_label.setText(self._tr("index_building"))
            self._refresh_index_btn.setEnabled(False)
            self._rebuild_index_btn.setEnabled(False)
            self._cancel_index_btn.setEnabled(True)

            thread = self.fulltext_search_engine.start_indexing(force_reindex=False)
            thread.progress_signal.connect(self._on_content_index_progress)
            thread.finished_signal.connect(self._on_content_index_finished)
            thread.cancelled_signal.connect(self._on_content_index_cancelled)
            thread.error_signal.connect(lambda msg: QMessageBox.warning(self, "索引错误", msg))

    def _rebuild_index(self):
        """重建索引（强制重建）"""
        reply = QMessageBox.question(
            self,
            "确认重建索引",
            "重建索引将删除现有索引并重新扫描所有文件，这可能需要较长时间。\n\n确定要重建索引吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        mode = self._search_tabs.currentIndex()

        if mode == 0:
            # 文件名索引
            if self.quick_search_engine.is_indexing():
                self.quick_search_engine.cancel_indexing()
            self._search_progress.setVisible(True)
            self._search_progress.setRange(0, 0)
            self._index_status_label.setText(self._tr("index_building"))
            self._refresh_index_btn.setEnabled(False)
            self._rebuild_index_btn.setEnabled(False)
            self._cancel_index_btn.setEnabled(True)

            thread = self.quick_search_engine.force_rebuild()
            thread.progress_signal.connect(self._on_name_index_progress)
            thread.finished_signal.connect(self._on_name_index_finished)
            thread.cancelled_signal.connect(self._on_name_index_cancelled)
            thread.error_signal.connect(lambda msg: QMessageBox.warning(self, "索引错误", msg))
        else:
            # 内容索引
            if self.fulltext_search_engine.is_indexing():
                self.fulltext_search_engine.cancel_indexing()
            self._search_progress.setVisible(True)
            self._search_progress.setRange(0, 0)
            self._index_status_label.setText(self._tr("index_building"))
            self._refresh_index_btn.setEnabled(False)
            self._rebuild_index_btn.setEnabled(False)
            self._cancel_index_btn.setEnabled(True)

            thread = self.fulltext_search_engine.force_reindex()
            thread.progress_signal.connect(self._on_content_index_progress)
            thread.finished_signal.connect(self._on_content_index_finished)
            thread.cancelled_signal.connect(self._on_content_index_cancelled)
            thread.error_signal.connect(lambda msg: QMessageBox.warning(self, "索引错误", msg))

    def _auto_rebuild_index_on_startup(self):
        """每次启动均在后台执行增量索引，已有结果可立即使用。"""
        if not self.quick_search_engine.is_indexing():
            name_thread = self.quick_search_engine.start_indexing(incremental=True)
            name_thread.progress_signal.connect(self._on_name_index_progress)
            name_thread.finished_signal.connect(self._on_name_index_finished)
            name_thread.cancelled_signal.connect(self._on_name_index_cancelled)
            name_thread.error_signal.connect(lambda msg: QMessageBox.warning(self, "索引错误", msg))

    def _show_first_index_notice(self):
        """首次没有可用文件名索引时，仅提示一次预计等待时间。"""
        if self.quick_search_engine.is_indexed:
            return
        if self._app_settings.value("first_index_notice_shown", False, type=bool):
            return
        self._app_settings.setValue("first_index_notice_shown", True)
        QMessageBox.information(
            self,
            "正在准备文件搜索",
            "首次使用需要建立文件名索引，文件较多时可能需要几分钟。\n\n"
            "索引会在后台进行，您可以继续使用其他功能；完成后搜索会更快。"
            "以后启动只会自动更新发生变化的内容。\n\n"
            "如需立即更新，可在“快速搜索”页面点击“刷新索引”。",
        )

    def _cancel_index(self):
        """取消索引"""
        mode = self._search_tabs.currentIndex()
        if mode == 0:
            self.quick_search_engine.cancel_indexing()
        else:
            self.fulltext_search_engine.cancel_indexing()
        self._cancel_index_btn.setEnabled(False)

    def _on_name_index_progress(self, count, current_path):
        """文件名索引进度"""
        self._index_status_label.setText(f"{self._tr('index_building')} ({count} 项)")

    def _on_name_index_finished(self, total, elapsed):
        """文件名索引完成"""
        self._search_progress.setVisible(False)
        self._index_status_label.setText(f"{self._tr('index_complete')}: {total} 项 ({elapsed:.1f}s)")
        self._refresh_index_btn.setEnabled(True)
        self._rebuild_index_btn.setEnabled(True)
        self._cancel_index_btn.setEnabled(False)
        # 自动触发搜索
        if self._search_input.text().strip():
            self._do_search()

    def _on_name_index_cancelled(self, total, elapsed):
        """取消扫描时旧索引仍然可用。"""
        self._search_progress.setVisible(False)
        self._index_status_label.setText(f"已取消刷新，保留 {total} 个索引项")
        self._refresh_index_btn.setEnabled(True)
        self._rebuild_index_btn.setEnabled(True)
        self._cancel_index_btn.setEnabled(False)

    def _on_content_index_progress(self, current, total, current_file):
        """内容索引进度"""
        if total > 0:
            self._search_progress.setRange(0, total)
            self._search_progress.setValue(current)
        self._index_status_label.setText(f"{self._tr('index_building')} ({current}/{total})")

    def _on_content_index_finished(self, total, elapsed):
        """内容索引完成"""
        self._search_progress.setVisible(False)
        self._search_progress.setRange(0, 1)
        self._index_status_label.setText(f"{self._tr('index_complete')}: {total} documents ({elapsed:.1f}s)")
        self._refresh_index_btn.setEnabled(True)
        self._rebuild_index_btn.setEnabled(True)
        self._cancel_index_btn.setEnabled(False)
        # 自动触发搜索
        if self._search_input.text().strip():
            self._do_search()

    def _on_content_index_cancelled(self, total, elapsed):
        self._search_progress.setVisible(False)
        self._index_status_label.setText(f"已取消内容索引，保留 {total} 个文档")
        self._refresh_index_btn.setEnabled(True)
        self._rebuild_index_btn.setEnabled(True)
        self._cancel_index_btn.setEnabled(False)

    def _update_search_index_status(self):
        """更新索引状态显示"""
        mode = self._search_tabs.currentIndex()
        if mode == 0:
            if self.quick_search_engine.is_indexed:
                count = self.quick_search_engine.total_files
                last_time = self.quick_search_engine.last_index_time
                time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(last_time)) if last_time else "未知"
                self._index_status_label.setText(f"索引已就绪：{count} 个目录项 · 上次更新 {time_str}")
                self._refresh_index_btn.setEnabled(True)
                self._rebuild_index_btn.setEnabled(True)
            else:
                self._index_status_label.setText(self._tr("index_none"))
                self._refresh_index_btn.setEnabled(False)
                self._rebuild_index_btn.setEnabled(False)
        else:
            if self.fulltext_search_engine.is_indexed:
                count = self.fulltext_search_engine.total_documents
                last_time = self.fulltext_search_engine.last_index_time
                time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(last_time)) if last_time else "未知"
                self._index_status_label.setText(f"索引已就绪：{count} 个文档 · 上次更新 {time_str}")
                self._refresh_index_btn.setEnabled(True)
                self._rebuild_index_btn.setEnabled(True)
            else:
                self._index_status_label.setText(self._tr("index_none"))
                self._refresh_index_btn.setEnabled(False)
                self._rebuild_index_btn.setEnabled(False)

    def _available_drives(self):
        roots = []
        try:
            for part in psutil.disk_partitions(all=False):
                drive, _ = os.path.splitdrive(part.mountpoint)
                root = drive.upper() + os.sep if drive else part.mountpoint
                if os.path.isdir(root) and root not in roots: roots.append(root)
        except Exception: pass
        if os.name == "nt":
            try:
                import ctypes
                mask = ctypes.windll.kernel32.GetLogicalDrives()
                for i in range(26):
                    root = f"{chr(65+i)}:{os.sep}"
                    if mask & (1 << i) and os.path.isdir(root) and root not in roots: roots.append(root)
            except Exception: pass
        return sorted(roots)

    def _populate_drives(self):
        self._drive_combo.blockSignals(True); self._drive_combo.clear()
        for root in self._available_drives(): self._drive_combo.addItem(f"磁盘 {root}", root)
        self._drive_combo.blockSignals(False)

    def _navigate_to(self, path, add_history=True):
        target = os.path.abspath(os.path.normpath(path))
        if not os.path.isdir(target):
            QMessageBox.warning(self, "导航失败", f"目录不存在或无法访问：\n{target}"); return False
        if add_history and os.path.normcase(target) != os.path.normcase(self.current_path):
            self._nav_history.append(self.current_path); self._nav_history = self._nav_history[-100:]
        self.current_path = target; self.refresh_folder(); return True

    def refresh_folder(self):
        self.tree.clear(); count = 0
        try:
            entries = sorted(os.scandir(self.current_path), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False); size = 0 if is_dir else entry.stat(follow_symlinks=False).st_size
                    item = QTreeWidgetItem([entry.name, "—" if is_dir else format_size(size)])
                    item.setIcon(0, self._icon(QtWidgets.QStyle.SP_DirIcon if is_dir else QtWidgets.QStyle.SP_FileIcon))
                    item.setData(0, Qt.UserRole, entry.path); item.setData(1, Qt.UserRole, is_dir); item.setToolTip(0, entry.name); self.tree.addTopLevelItem(item); count += 1
                except OSError: continue
        except (PermissionError, OSError) as exc:
            QMessageBox.warning(self, "读取失败", f"{self.current_path}\n{exc}")
        self._update_nav_state()
        self._status_label.setText((f"Current folder: {self.current_path}    Items: {count}" if self.language == "en" else f"当前目录：{self.current_path}    项目数：{count}"))

    def _update_nav_state(self):
        anchor = Path(self.current_path).anchor; at_root = os.path.normcase(self.current_path.rstrip("\\/")) == os.path.normcase(anchor.rstrip("\\/"))
        self._btn_up.setEnabled(not at_root); self._btn_root.setEnabled(not at_root); self._btn_back.setEnabled(bool(self._nav_history))
        self._full_path = self.current_path; self._path_bar.setToolTip(self._full_path); self._refresh_path_elide()
        drive = os.path.splitdrive(self.current_path)[0]
        self._drive_combo.blockSignals(True)
        for i in range(self._drive_combo.count()):
            if os.path.normcase(os.path.splitdrive(self._drive_combo.itemData(i))[0]) == os.path.normcase(drive): self._drive_combo.setCurrentIndex(i); break
        self._drive_combo.blockSignals(False)

    def _refresh_path_elide(self):
        width = max(40, self._path_bar.width() - 18); self._path_bar.setText(self._path_bar.fontMetrics().elidedText(self._full_path, Qt.ElideMiddle, width))

    def resizeEvent(self, event):
        super().resizeEvent(event); QtCore.QTimer.singleShot(0, self._refresh_path_elide)

    def _go_back_history(self):
        if self._nav_history: self._navigate_to(self._nav_history.pop(), False)

    def _go_up(self):
        parent = str(Path(self.current_path).parent)
        if os.path.normcase(parent) != os.path.normcase(self.current_path): self._navigate_to(parent)

    def _go_root(self):
        root = Path(self.current_path).anchor
        if root: self._navigate_to(root)

    def _on_drive_selected(self, index):
        root = self._drive_combo.itemData(index)
        if root and os.path.normcase(os.path.splitdrive(root)[0]) != os.path.normcase(os.path.splitdrive(self.current_path)[0]): self._navigate_to(root)

    def _on_double_click(self, item, _column):
        if item.data(1, Qt.UserRole): self._navigate_to(item.data(0, Qt.UserRole))

    def _on_item_clicked(self, item, _column): self._show_detail(item.data(0, Qt.UserRole), item.data(1, Qt.UserRole))

    def _deletion_advice(self, path, is_dir, identity):
        norm = os.path.normcase(os.path.abspath(path))
        protected = [os.environ.get("WINDIR", r"C:\Windows"), os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("ProgramData", r"C:\ProgramData")]
        is_protected = any(p and (norm == os.path.normcase(p) or norm.startswith(os.path.normcase(p) + os.sep)) for p in protected)
        cloud = identity.sync_software not in ("普通本地文件或文件夹", "Local file or folder")
        if self.language == "en":
            if is_protected: return "Do not delete: this item is inside a system or installed-program directory and deletion may break Windows or an application."
            if "OneDriveTemp" in path: return "Do not delete manually: this is a OneDrive temporary sync location. Deletion may interrupt synchronization or be recreated automatically."
            if cloud: return "Use caution: this item is managed by sync software. Deletion may also remove it from the cloud and other devices."
            if is_dir: return "Review first: deleting this folder also deletes all files and subfolders inside it."
            ext = os.path.splitext(path)[1].lower()
            if ext in {".tmp", ".temp", ".dmp"}: return "Usually safe after closing related apps, but temporary recovery or diagnostic data may be lost."
            if ext in {".log", ".bak", ".old"}: return "Review first: it may contain troubleshooting information or a backup needed for recovery."
            return "No clear safe-cleanup signature was found. Confirm the file's purpose and backup status before deleting it."
        if is_protected: return "不建议删除：该项目位于系统或已安装程序目录，删除可能导致 Windows 或软件无法正常运行。"
        if "onedrivetemp" in path.lower(): return "不建议手动删除：这是 OneDrive 临时同步位置，删除可能中断同步，也可能被系统自动重新创建。"
        if cloud: return "谨慎处理：该项目由同步软件管理，删除操作可能同步到云端和其他设备。"
        if is_dir: return "请先检查：删除文件夹会同时删除其中的全部文件和子文件夹。"
        ext = os.path.splitext(path)[1].lower()
        if ext in {".tmp", ".temp", ".dmp"}: return "通常可在关闭相关软件后删除，但可能丢失临时恢复或诊断数据。"
        if ext in {".log", ".bak", ".old"}: return "建议先检查：文件可能包含排障记录或恢复所需备份。"
        return "未发现明确的安全清理特征。删除前请确认文件用途、备份状态及是否仍被软件使用。"

    def _localized_identity(self, identity):
        if self.language == "zh":
            return identity.sync_software, identity.relation, identity.default_app, "；".join(identity.evidence) or "无可靠证据"
        sync_map = {
            "普通本地文件或文件夹": "Local file or folder",
            "未识别": "Unknown",
            "Microsoft OneDrive 工作或学校版": "Microsoft OneDrive Work or School",
        }
        sync = sync_map.get(identity.sync_software, identity.sync_software)
        relation_map = {
            "未发现已知软件或同步目录": "No known software or sync location detected",
            "OneDrive 个人版临时同步目录": "OneDrive Personal temporary sync location",
            "OneDrive 临时同步目录": "OneDrive temporary sync location",
            "已安装软件目录或其子目录": "Installed application directory or subdirectory",
        }
        relation = relation_map.get(identity.relation, identity.relation)
        app_map = {
            "不适用": "Not applicable",
            "未识别（文件没有扩展名）": "Unknown (file has no extension)",
        }
        app = app_map.get(identity.default_app, identity.default_app)
        evidence = "; ".join(identity.evidence) if identity.evidence else "No reliable evidence"
        evidence_replacements = {
            "路径位于 OneDriveTemp": "Path is inside OneDriveTemp",
            "检测到 -Personal 账户特征": "Detected the -Personal account marker",
            "Windows Shell 默认应用关联": "Windows Shell default-app association",
            "未匹配本机同步根目录、安装记录或已知软件路径": "No local sync root, installed-app record, or known software path matched",
        }
        for chinese, english in evidence_replacements.items():
            evidence = evidence.replace(chinese, english)
        return sync, relation, app, evidence

    def _folder_size(self, path):
        """Calculate a folder's logical size without following links/reparse points."""
        total = 0
        try:
            for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
                dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(root, name))]
                for name in files:
                    file_path = os.path.join(root, name)
                    try:
                        if not os.path.islink(file_path):
                            total += os.stat(file_path, follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            return 0
        return total

    def _show_detail(self, path, is_dir):
        try:
            self._detail_path = path
            stat = os.stat(path, follow_symlinks=False); identity = FileAssociation(path).get_detailed_identity(); self._last_identity = identity
            sync, relation, default_app, evidence = self._localized_identity(identity)
            ext = os.path.splitext(path)[1].lower()
            item_type = ("Folder" if is_dir else (f"{ext} file" if ext else "File without extension")) if self.language == "en" else ("文件夹" if is_dir else (f"{ext} 文件" if ext else "无扩展名文件"))
            logical_size = self._folder_size(path) if is_dir else stat.st_size
            values = {
                "name": os.path.basename(path), "path": path, "size": format_size(logical_size),
                "mtime": format_time(stat.st_mtime), "ftype": item_type,
                "sync": sync, "relation": relation, "assoc": default_app + (f"\n{identity.app_path}" if identity.app_path else ""),
                "confidence": f"{identity.confidence*100:.0f}%", "evidence": evidence,
                "advice": self._deletion_advice(path, is_dir, identity),
            }
            for key, value in values.items(): self._info_labels[key].setText(value); self._info_labels[key].setToolTip(value)
            
            # 更新预览面板
            if hasattr(self, '_detail_preview_text'):
                if is_dir:
                    self._detail_preview_text.setPlainText("（文件夹无法预览）")
                elif self.content_extractor.can_extract(path):
                    try:
                        content = self.content_extractor.extract_preview(path, max_chars=10000)
                        if content:
                            self._detail_preview_text.setPlainText(content[:10000])
                        else:
                            self._detail_preview_text.setPlainText(self._tr("preview_no_support"))
                    except Exception as e:
                        self._detail_preview_text.setPlainText(f"预览失败: {e}")
                else:
                    self._detail_preview_text.setPlainText(self._tr("preview_no_support"))
        except Exception as exc: self._info_labels["name"].setText(f"读取失败：{exc}")

    def _selected_path(self, show_message=True):
        items = self.tree.selectedItems()
        if items: return items[0].data(0, Qt.UserRole)
        if show_message: QMessageBox.information(self, "提示", "请先选择文件或文件夹")
        return None

    def _query_association(self):
        path = self._selected_path()
        if not path: return
        self._show_association_for(path)

    def _show_association_for(self, path):
        info = FileAssociation(path).get_detailed_identity(); self._show_detail(path, os.path.isdir(path))
        sync, relation, app, evidence = self._localized_identity(info)
        if self.language == "en":
            text = (f"Item: {os.path.basename(path)}\n\nSource / sync software: {sync}\nRelationship: {relation}\n"
                    f"Default app: {app}\nExecutable: {info.app_path or 'Not applicable'}\n"
                    f"Confidence: {info.confidence*100:.0f}%\nEvidence: {evidence}")
            QMessageBox.information(self, "Software Identification", text)
        else:
            text = (f"项目：{os.path.basename(path)}\n\n来源/同步软件：{sync}\n关系：{relation}\n"
                    f"默认打开程序：{app}\n程序路径：{info.app_path or '不适用'}\n"
                    f"可信度：{info.confidence*100:.0f}%\n判断依据：{evidence}")
            QMessageBox.information(self, "关联软件识别结果", text)

    def _online_verify(self):
        path = self._selected_path()
        if not path: return
        self._online_verify_path(path)

    def _online_verify_path(self, path):
        info = FileAssociation(path).get_detailed_identity(); query = info.online_query
        if not query: QMessageBox.information(self, "在线核验", "没有可安全发送的查询词。完整路径和个人信息不会上传。"); return
        if QMessageBox.question(self, "在线核验", f"将只把以下查询词发送给搜索引擎，不发送完整路径或文件内容：\n\n{query}\n\n继续吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            if not self.web_search.search_online(query): QMessageBox.warning(self, "在线核验", "无法打开浏览器")

    def _open_containing_folder(self):
        path = self._selected_path()
        if path:
            try: os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
            except OSError as exc: QMessageBox.warning(self, "打开失败", str(exc))

    def _delete_path(self, path):
        if not path: return False
        # 读取设置：是否删除前确认
        confirm_before_delete = self._settings.get("cleanup", "confirm_before_delete", True)
        if confirm_before_delete:
            if QMessageBox.question(self, "确认移至回收站", f"确定要移动以下项目吗？\n\n{path}", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return False
        
        # 读取设置：是否使用系统回收站
        use_system_recycle = self._settings.get("cleanup", "use_system_recycle", True)
        
        if use_system_recycle:
            # 先尝试普通方式
            ok, message = self.file_operations.move_to_recycle_bin(path)
            
            # 权限不足时使用 Windows Shell API（会弹出 UAC 授权，无需重启）
            if not ok and "没有权限" in message:
                ok = self._windows_shell_delete(path, allow_undo=True)
                if ok:
                    message = "已成功移至回收站"
        else:
            # 直接永久删除
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                ok, message = True, "已永久删除"
            except PermissionError:
                ok = self._windows_shell_delete(path, allow_undo=False)
                message = "已永久删除" if ok else "删除失败"
            except Exception as exc:
                ok, message = False, str(exc)
        
        (QMessageBox.information if ok else QMessageBox.warning)(self, "操作结果", message)
        if ok: self.refresh_folder()
        return ok

    def _permanent_delete_path(self, path):
        if not path or not os.path.lexists(path):
            QMessageBox.warning(self, "永久删除", "所选路径已经不存在。")
            return False
        warning = ("永久删除后无法从回收站恢复。\n"
                   "如果项目位于 OneDrive、Dropbox 等同步目录，也可能从云端和其他设备删除。\n\n"
                   f"确定永久删除以下项目吗？\n\n{path}")
        if QMessageBox.question(self, "确认永久删除", warning, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return False
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            QMessageBox.information(self, "永久删除", "所选项目已永久删除。")
            return True
        except PermissionError:
            # 使用 Windows Shell API 直接删除（会弹出 UAC 授权，无需重启）
            ok = self._windows_shell_delete(path, allow_undo=False)
            if ok:
                QMessageBox.information(self, "永久删除", "所选项目已永久删除。")
            return ok
        except Exception as exc:
            QMessageBox.critical(self, "永久删除失败", str(exc))
            return False

    def _windows_shell_delete(self, path, allow_undo=True):
        """使用 Windows SHFileOperationW 删除文件/文件夹。
        该 API 会自动弹出 UAC 权限提示（如果权限不足），用户点"是"即可，无需重启程序。
        allow_undo=True 表示移入回收站，False 表示永久删除。
        """
        try:
            import ctypes
            from ctypes import wintypes
            
            FO_DELETE = 3
            FOF_ALLOWUNDO = 0x0040      # 允许撤消（移入回收站）
            FOF_NOCONFIRMATION = 0x0010 # 不弹确认对话框（我们已弹过）
            FOF_NOERRORUI = 0x0400      # 不显示错误 UI
            FOF_SILENT = 0x0004         # 不显示进度
            
            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR),
                    ("fFlags", wintypes.USHORT),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", wintypes.LPVOID),
                    ("lpszProgressTitle", wintypes.LPCWSTR),
                ]
            
            flags = FOF_NOCONFIRMATION
            if allow_undo:
                flags |= FOF_ALLOWUNDO
            
            # pFrom 必须以双 NULL 结尾
            pFrom = ctypes.create_unicode_buffer(path + '\0\0')
            
            shf = SHFILEOPSTRUCTW()
            shf.hwnd = int(self.winId())
            shf.wFunc = FO_DELETE
            shf.pFrom = ctypes.cast(pFrom, wintypes.LPCWSTR)
            shf.pTo = None
            shf.fFlags = flags
            shf.fAnyOperationsAborted = False
            shf.hNameMappings = None
            shf.lpszProgressTitle = None
            
            result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(shf))
            return result == 0 and not shf.fAnyOperationsAborted
        except Exception as e:
            QMessageBox.warning(self, "操作失败", f"Shell 删除失败: {e}")
            return False

    def _delete_selected(self): self._delete_path(self._selected_path())

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item: return
        self.tree.setCurrentItem(item); menu = QMenu(self)
        texts = (["Identify Software", "Verify Online", "Copy Full Path", "Open Location", "Move to Recycle Bin"] if self.language == "en" else
                 ["识别关联软件", "在线核验软件", "复制完整路径", "打开所在目录", "移至回收站"])
        identify = menu.addAction(self._icon(QtWidgets.QStyle.SP_FileLinkIcon), texts[0])
        online = menu.addAction(self._icon(QtWidgets.QStyle.SP_DriveNetIcon), texts[1])
        copy = menu.addAction(self._icon(QtWidgets.QStyle.SP_DialogSaveButton), texts[2])
        menu.addSeparator(); open_action = menu.addAction(self._icon(QtWidgets.QStyle.SP_DirOpenIcon), texts[3])
        delete = menu.addAction(self._icon(QtWidgets.QStyle.SP_TrashIcon), texts[4])
        chosen = menu.exec_(self.tree.mapToGlobal(pos))
        if chosen == identify: self._query_association()
        elif chosen == online: self._online_verify()
        elif chosen == copy: QtWidgets.QApplication.clipboard().setText(item.data(0, Qt.UserRole))
        elif chosen == open_action: self._open_containing_folder()
        elif chosen == delete: self._delete_selected()

    def _on_search(self, text):
        text = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()): self.tree.topLevelItem(i).setHidden(bool(text and text not in self.tree.topLevelItem(i).text(0).lower()))

    def _update_disk_usage(self):
        """更新底部状态栏的磁盘迷你条（预览图中的 mini-bar 风格）"""
        while self._disk_bars_layout.count():
            item = self._disk_bars_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                except OSError:
                    continue
                drive, _ = os.path.splitdrive(part.mountpoint)
                letter = drive.upper() if drive else part.mountpoint.rstrip("\\/")
                tip = f"{letter}  {format_size(usage.used)} / {format_size(usage.total)} ({usage.percent:.1f}%)"

                lbl = QLabel(letter)
                lbl.setStyleSheet(f"font-size:11px; color:{M_TEXT_3};")
                self._disk_bars_layout.addWidget(lbl)

                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(min(100, int(usage.percent)))
                bar.setTextVisible(False)
                bar.setFixedWidth(60)
                bar.setFixedHeight(4)
                color = self._disk_pct_color(usage.percent)
                bar.setStyleSheet(
                    f"QProgressBar {{ border:0; background:{M_BORDER}; border-radius:2px; min-height:4px; max-height:4px; }}"
                    f"QProgressBar::chunk {{ background:{color}; border-radius:2px; }}")
                bar.setToolTip(tip)
                self._disk_bars_layout.addWidget(bar)

                pct_lbl = QLabel(f"{usage.percent:.1f}%")
                pct_lbl.setStyleSheet(f"font-size:11px; color:{M_TEXT_3};")
                pct_lbl.setToolTip(tip)
                self._disk_bars_layout.addWidget(pct_lbl)
                self._disk_bars_layout.addSpacing(10)
        except Exception:
            pass

    def _set_active_tab(self, index):
        """高亮当前激活的导航标签"""
        for i, btn in enumerate(self._nav_tabs):
            btn.setProperty("class", "active" if i == index else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _show_home_view(self):
        """切换到首页"""
        self._main_stack.setCurrentIndex(0)
        self._set_active_tab(0)
        self._update_home_disks()

    def _show_browse_view(self):
        """切换到文件管理视图"""
        self._main_stack.setCurrentIndex(1)
        self._set_active_tab(1)

    def _show_scan_view(self):
        """切换到磁盘空间扫描视图"""
        self._main_stack.setCurrentIndex(2)
        self._set_active_tab(2)
        if not getattr(self, "_scan_path_set", False):
            self._scan_use_current()
            self._scan_path_set = True

    def _show_search_view(self):
        """切换到快速搜索视图"""
        self._main_stack.setCurrentIndex(4)
        self._set_active_tab(4)
        self._update_search_index_status()
        self._search_input.setFocus()

    def _show_recycle_view(self):
        """切换到回收站管理视图"""
        self._main_stack.setCurrentIndex(5)
        self._set_active_tab(5)
        self._rb_load_items()

    def _show_settings_view(self):
        """切换到设置视图"""
        self._main_stack.setCurrentIndex(6)
        self._set_active_tab(6)

    def _on_settings_saved(self):
        """设置保存后的回调"""
        # 这里可以添加设置生效后的刷新逻辑
        # 例如：更新界面主题、重新加载配置等
        pass

    def _show_detail_view(self):
        """兼容旧调用：跳转到文件管理视图"""
        self._show_browse_view()

    def _highlight_toolbar_button(self, active_btn):
        """兼容旧调用：已由 _set_active_tab 取代"""

    def _set_scan_path(self, path):
        self._scan_path = os.path.abspath(path); self._scan_path_label.setText(self._scan_path_label.fontMetrics().elidedText(self._scan_path, Qt.ElideMiddle, max(200, self._scan_path_label.width()-20))); self._scan_path_label.setToolTip(self._scan_path)

    def _scan_use_current(self): self._set_scan_path(self.current_path)
    def _scan_use_drive(self): self._set_scan_path(Path(self.current_path).anchor or self.current_path)
    def _scan_choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择扫描目录", self.current_path)
        if path: self._set_scan_path(path)

    def _start_scan(self):
        if self._scanner_thread and self._scanner_thread.isRunning(): return
        # 读取设置：大文件阈值、大文件夹阈值、排除目录、排除文件类型
        threshold_mb = self._settings.get("cleanup", "large_file_threshold_mb", 100)
        folder_threshold_mb = self._settings.get("cleanup", "large_folder_threshold_mb", 1024)
        exclude_dirs = self._settings.get("scan", "exclude_dirs", [])
        exclude_patterns = self._settings.get("scan", "exclude_patterns", [])
        self._scanner_thread = DiskScannerThread(self._scan_path, threshold_mb, folder_threshold_mb, self._top_n.value(), exclude_dirs, exclude_patterns)
        self._scanner_thread.progress_signal.connect(self._scan_progress_update); self._scanner_thread.status_signal.connect(self._scan_status_update)
        self._scanner_thread.finished_signal.connect(self._scan_finished); self._scanner_thread.error_signal.connect(lambda msg: QMessageBox.warning(self, "扫描错误", msg))
        self._scan_start.setEnabled(False); self._scan_cancel.setEnabled(True); self._scan_progress.setRange(0, 0); self._scan_status.setText((f"Scanning: {self._scan_path}" if self.language == "en" else f"正在扫描：{self._scan_path}")); self._scanner_thread.start()

    def _auto_start_scan(self):
        """启动时自动扫描索引"""
        if self._scanner_thread and self._scanner_thread.isRunning():
            return
        # 自动扫描时使用默认路径和设置
        threshold_mb = self._settings.get("cleanup", "large_file_threshold_mb", 100)
        folder_threshold_mb = self._settings.get("cleanup", "large_folder_threshold_mb", 1024)
        exclude_dirs = self._settings.get("scan", "exclude_dirs", [])
        exclude_patterns = self._settings.get("scan", "exclude_patterns", [])
        self._scanner_thread = DiskScannerThread(self.current_path, threshold_mb, folder_threshold_mb, self._top_n.value(), exclude_dirs, exclude_patterns)
        self._scanner_thread.progress_signal.connect(self._scan_progress_update)
        self._scanner_thread.status_signal.connect(self._scan_status_update)
        self._scanner_thread.finished_signal.connect(self._scan_finished)
        self._scanner_thread.error_signal.connect(lambda msg: QMessageBox.warning(self, "扫描错误", msg))
        self._scan_status.setText(f"正在自动扫描：{self.current_path}")
        self._scanner_thread.start()

    def _setup_auto_scan_timer(self):
        """设置自动扫描定时器"""
        interval = self._settings.get("scan", "auto_scan_interval", "off")
        
        # 如果已有定时器，先停止
        if hasattr(self, '_auto_scan_timer') and self._auto_scan_timer:
            self._auto_scan_timer.stop()
            self._auto_scan_timer = None
        
        # 根据设置创建定时器
        if interval == "off":
            return
        
        self._auto_scan_timer = QtCore.QTimer(self)
        self._auto_scan_timer.timeout.connect(self._auto_start_scan)
        
        # 设置间隔时间（毫秒）
        if interval == "daily":
            self._auto_scan_timer.start(24 * 60 * 60 * 1000)  # 24小时
        elif interval == "weekly":
            self._auto_scan_timer.start(7 * 24 * 60 * 60 * 1000)  # 7天
        elif interval == "monthly":
            self._auto_scan_timer.start(30 * 24 * 60 * 60 * 1000)  # 30天

    def _cancel_scan(self):
        if self._scanner_thread and self._scanner_thread.isRunning(): self._scanner_thread.cancel(); self._scan_status.setText("Cancelling scan safely..." if self.language == "en" else "正在安全取消扫描..."); self._scan_cancel.setEnabled(False)

    # ── 空间可视化页面方法 ──
    def _show_visualization_view(self):
        self._main_stack.setCurrentIndex(3)
        self._set_active_tab(3)

    def _viz_use_current(self):
        self._set_viz_path(self.current_path)

    def _viz_use_drive(self):
        self._set_viz_path(Path(self.current_path).anchor or self.current_path)

    def _viz_choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择可视化目录", self.current_path)
        if path:
            self._set_viz_path(path)

    def _set_viz_path(self, path):
        self._viz_path = path
        self._viz_path_label.setText(path)
        self._viz_path_label.setToolTip(path)

    def _start_visualization(self):
        """开始空间可视化扫描 - 无阈值限制，显示所有文件"""
        if hasattr(self, '_viz_scanner_thread') and self._viz_scanner_thread and self._viz_scanner_thread.isRunning():
            return
        # 使用极小阈值（0.001MB ≈ 1KB）来包含几乎所有文件
        self._viz_scanner_thread = DiskScannerThread(self._viz_path, 0.001, 100000)
        self._viz_scanner_thread.progress_signal.connect(self._viz_progress_update)
        self._viz_scanner_thread.status_signal.connect(self._viz_status_update)
        self._viz_scanner_thread.finished_signal.connect(self._viz_finished)
        self._viz_scanner_thread.error_signal.connect(lambda msg: QMessageBox.warning(self, "扫描错误", msg))
        self._viz_start.setEnabled(False)
        self._viz_cancel.setEnabled(True)
        self._viz_progress.setRange(0, 0)
        self._viz_status.setText(f"正在扫描：{self._viz_path}")
        self._viz_scanner_thread.start()

    def _cancel_visualization(self):
        if hasattr(self, '_viz_scanner_thread') and self._viz_scanner_thread and self._viz_scanner_thread.isRunning():
            self._viz_scanner_thread.cancel()
            self._viz_status.setText("正在安全取消扫描...")
            self._viz_cancel.setEnabled(False)

    def _viz_progress_update(self, current, total):
        if total > 0:
            self._viz_progress.setRange(0, total)
            self._viz_progress.setValue(current)
        self._viz_status.setText(f"已扫描 {current} 个文件")

    def _viz_status_update(self, path):
        self._viz_status.setText(f"正在扫描：{path}")

    def _viz_finished(self, result):
        self._viz_start.setEnabled(True)
        self._viz_cancel.setEnabled(False)
        self._viz_progress.setRange(0, 1)
        self._viz_progress.setValue(1)
        if result.get("cancelled"):
            self._viz_status.setText(f"扫描已取消，已处理 {result['total_files']} 个文件")
            return
        # 填充 Treemap
        if "folder_tree" in result:
            self._viz_treemap.set_data(result["folder_tree"])
            # 连接导航信号
            try:
                self._viz_treemap.navigate_signal.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._viz_treemap.navigate_signal.connect(self._viz_on_navigate)
            # 连接右键菜单信号
            try:
                self._viz_treemap.context_menu_signal.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._viz_treemap.context_menu_signal.connect(self._viz_context_menu)
        self._viz_status.setText(f"扫描完成，共 {result['total_files']} 个文件")

    def _viz_go_back(self):
        """可视化 Treemap 返回上一级"""
        if hasattr(self, '_viz_treemap'):
            self._viz_treemap.drill_up()

    def _viz_on_navigate(self, path: str, name: str, can_go_back: bool):
        """可视化导航信号处理"""
        if hasattr(self, '_viz_treemap'):
            self._viz_back_btn.setEnabled(can_go_back)
            self._viz_breadcrumb.setText(f"📁 {name}")

    def _viz_context_menu(self, path, name, has_children, x, y):
        """可视化右键菜单"""
        from PyQt5.QtCore import QPoint
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        open_action = menu.addAction("📂 打开文件夹")
        open_action.triggered.connect(lambda: self._open_folder(path))
        props_action = menu.addAction("ℹ️ 文件夹属性")
        props_action.triggered.connect(lambda: self._show_folder_properties(path, name))
        copy_action = menu.addAction("📋 复制路径")
        copy_action.triggered.connect(lambda: self._copy_to_clipboard(path))
        menu.addSeparator()
        if has_children:
            drill_action = menu.addAction("🔍 查看子文件夹")
            drill_action.triggered.connect(lambda: self._viz_treemap.drill_down_to_path(path))
        menu.exec_(QPoint(x, y))

    def _scan_progress_update(self, current, total):
        if total > 0: self._scan_progress.setRange(0, total); self._scan_progress.setValue(current)
        self._scan_status.setText((f"Scanned {current} files" if self.language == "en" else f"已扫描 {current} 个文件"))

    def _scan_status_update(self, path): self._scan_status.setText((f"Scanning: {path}" if self.language == "en" else f"正在扫描：{path}"))

    def _open_folder(self, path):
        """在资源管理器中打开文件夹"""
        try:
            os.startfile(path)
        except OSError as exc:
            QMessageBox.warning(self, "打开失败", str(exc))

    def _show_folder_properties(self, path, name):
        """显示文件夹属性对话框"""
        import os
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox
        
        dlg = QDialog(self)
        dlg.setWindowTitle(f"文件夹属性 - {name}")
        dlg.setMinimumWidth(400)
        
        layout = QVBoxLayout(dlg)
        
        # 基本信息
        layout.addWidget(QLabel(f"<b>名称:</b> {name}"))
        layout.addWidget(QLabel(f"<b>路径:</b> {path}"))
        
        try:
            stat = os.stat(path)
            layout.addWidget(QLabel(f"<b>创建时间:</b> {time.ctime(stat.st_ctime)}"))
            layout.addWidget(QLabel(f"<b>修改时间:</b> {time.ctime(stat.st_mtime)}"))
        except OSError as e:
            layout.addWidget(QLabel(f"<b>无法获取统计信息:</b> {e}"))
        
        layout.addSpacing(10)
        
        # 关闭按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)
        
        dlg.exec_()

    def _copy_to_clipboard(self, text):
        """复制文本到剪贴板"""
        QtWidgets.QApplication.clipboard().setText(text)
        QMessageBox.information(self, "已复制", f"已复制到剪贴板:\n{text}", QMessageBox.Ok)

    def _scan_finished(self, result):
        self._scan_start.setEnabled(True); self._scan_cancel.setEnabled(False); self._scan_progress.setRange(0, 1); self._scan_progress.setValue(1)
        self._record_scan_time()
        if result.get("cancelled"):
            self._scan_status.setText((f"Scan cancelled after {result['total_files']} files" if self.language == "en" else f"扫描已取消，已处理 {result['total_files']} 个文件")); return
        
        # 填充大文件列表
        for data in result["large_files"]:
            source = FileAssociation(data["path"]).get_detailed_identity().sync_software
            item = QTreeWidgetItem([data["name"], format_size(data["allocated"]), format_size(data["size"]), format_time(data["mtime"]), source, data["path"]]); item.setData(0, Qt.UserRole, data["path"]); self._large_files.addTopLevelItem(item)
        
        # 填充大文件夹列表
        for data in result["large_folders"]:
            source = FileAssociation(data["path"]).get_detailed_identity().sync_software
            item = QTreeWidgetItem([data["name"], format_size(data["allocated"]), format_size(data["size"]), str(data["file_count"]), str(data["folder_count"]), source, data["path"]]); item.setData(0, Qt.UserRole, data["path"]); self._large_folders.addTopLevelItem(item)
        for data in result["suggestions"]:
            item = QTreeWidgetItem([data["level"], data["name"], format_size(data["allocated"]), data["reason"], data["risk"], data["path"]]); item.setData(0, Qt.UserRole, data["path"]); self._suggestions.addTopLevelItem(item)
        for data in result.get("garbage_files", []):
            item = QTreeWidgetItem([data["category"], data["name"], format_size(data["allocated"]), format_time(data["mtime"]), data["level"], data["risk"], data["path"]])
            item.setData(0, Qt.UserRole, data["path"]); item.setData(0, Qt.UserRole + 1, bool(data.get("safe_to_clean"))); self._garbage_files.addTopLevelItem(item)
        if self.language == "en":
            self._scan_status.setText(f"Complete: {result['total_files']} files, {result['total_folders']} folders; allocated {format_size(result['total_allocated'])}; skipped {result['skipped_reparse']} reparse points; {len(result['errors'])} errors")
        else:
            self._scan_status.setText(f"扫描完成：{result['total_files']} 个文件，{result['total_folders']} 个文件夹；实际占用 {format_size(result['total_allocated'])}；跳过重解析点 {result['skipped_reparse']} 个；错误 {len(result['errors'])} 个")

    def _active_scan_tree(self):
        widget = QtWidgets.QApplication.focusWidget()
        if isinstance(widget, QTreeWidget) and widget in (self._large_files, self._large_folders, self._suggestions, self._garbage_files): return widget
        return (self._large_files, self._large_folders, self._suggestions)[self._main_tabs.currentWidget().findChild(QTabWidget).currentIndex()] if False else self._large_files

    def _scan_result_path(self):
        for tree in (self._large_files, self._large_folders, self._suggestions, self._garbage_files):
            if tree.hasFocus() and tree.selectedItems(): return tree.selectedItems()[0].data(0, Qt.UserRole)
        for tree in (self._large_files, self._large_folders, self._suggestions, self._garbage_files):
            if tree.selectedItems(): return tree.selectedItems()[0].data(0, Qt.UserRole)
        QMessageBox.information(self, "提示", "请先选择扫描结果"); return None

    def _open_scan_result(self):
        path = self._scan_result_path()
        if path:
            try: os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
            except OSError as exc: QMessageBox.warning(self, "打开失败", str(exc))
    def _copy_scan_result(self):
        path = self._scan_result_path()
        if path: QtWidgets.QApplication.clipboard().setText(path)
    def _delete_scan_result(self): self._delete_path(self._scan_result_path())

    def _clean_junk_selected(self):
        items = self._garbage_files.selectedItems()
        if not items:
            QMessageBox.information(self, "提示", "请先选择要清理的垃圾文件。")
            return
        paths = [item.data(0, Qt.UserRole) for item in items if item.data(0, Qt.UserRole)]
        if not paths:
            return
        prompt = ("确定将选中的垃圾/临时文件移至回收站吗？\n\n" + "\n".join(paths[:12]) +
                  (f"\n……共 {len(paths)} 项" if len(paths) > 12 else ""))
        if QMessageBox.question(self, "确认清理", prompt, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        moved = 0
        for path in paths:
            ok, _ = self.file_operations.move_to_recycle_bin(path)
            if ok:
                moved += 1
                item = next((i for i in items if i.data(0, Qt.UserRole) == path), None)
                if item:
                    self._garbage_files.takeTopLevelItem(self._garbage_files.indexOfTopLevelItem(item))
        QMessageBox.information(self, "清理结果", f"已将 {moved} 项移至回收站。")

    def _on_scan_context_menu(self, tree, pos):
        item = tree.itemAt(pos)
        if not item:
            return
        tree.setCurrentItem(item)
        item.setSelected(True)
        path = item.data(0, Qt.UserRole)
        if not path:
            return
        menu = QMenu(self)
        texts = (["Search Associated Software", "Show Associated Software", "Move to Recycle Bin", "Delete Permanently", "Open Path", "Copy Path"] if self.language == "en" else
                 ["搜索关联程序", "显示关联程序", "选择删除（移至回收站）", "永久删除", "打开路径", "复制路径"])
        search_action = menu.addAction(self._icon(QtWidgets.QStyle.SP_DriveNetIcon), texts[0])
        show_action = menu.addAction(self._icon(QtWidgets.QStyle.SP_FileLinkIcon), texts[1])
        menu.addSeparator()
        recycle_action = menu.addAction(self._icon(QtWidgets.QStyle.SP_TrashIcon), texts[2])
        permanent_action = menu.addAction(self._icon(QtWidgets.QStyle.SP_MessageBoxCritical), texts[3])
        menu.addSeparator()
        open_action = menu.addAction(self._icon(QtWidgets.QStyle.SP_DirOpenIcon), texts[4])
        copy_action = menu.addAction(self._icon(QtWidgets.QStyle.SP_DialogSaveButton), texts[5])
        chosen = menu.exec_(tree.viewport().mapToGlobal(pos))
        if chosen == search_action:
            self._online_verify_path(path)
        elif chosen == show_action:
            self._show_association_for(path)
        elif chosen == recycle_action:
            if self._delete_path(path):
                tree.takeTopLevelItem(tree.indexOfTopLevelItem(item))
        elif chosen == permanent_action:
            if self._permanent_delete_path(path):
                tree.takeTopLevelItem(tree.indexOfTopLevelItem(item))
        elif chosen == open_action:
            try:
                os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
            except OSError as exc:
                QMessageBox.warning(self, "打开失败", str(exc))
        elif chosen == copy_action:
            QtWidgets.QApplication.clipboard().setText(path)

    def _open_recycle_bin(self):
        """兼容旧调用：切换到回收站管理页面"""
        self._show_recycle_view()

    def closeEvent(self, event):
        if self._scanner_thread and self._scanner_thread.isRunning():
            self._scanner_thread.cancel()
            self._scanner_thread.wait()
        if (hasattr(self, '_viz_scanner_thread') and self._viz_scanner_thread and
                self._viz_scanner_thread.isRunning()):
            self._viz_scanner_thread.cancel()
            self._viz_scanner_thread.wait()
        self.quick_search_engine.close()
        self.fulltext_search_engine.close()
        super().closeEvent(event)


# 保留新旧入口名称兼容性。
FileTreeWindow = DiskMonitor
