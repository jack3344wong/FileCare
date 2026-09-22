# -*- coding: utf-8 -*-
"""SpaceSniffer 风格的 Treemap 可视化组件（支持逐级下钻/返回/滚动）。"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QFontMetrics
)
from PyQt5.QtWidgets import QWidget, QToolTip


# 大小级别颜色 — 高对比度配色（默认方案）
_SIZE_COLORS_DEFAULT = [
    # (min_bytes, fill_color, label)
    (10 * 1024 ** 3, QColor(180, 80, 120), "> 10 GB"),
    (1 * 1024 ** 3,  QColor(79, 172, 254), "1–10 GB"),
    (100 * 1024 ** 2, QColor(67, 233, 123), "100 MB–1 GB"),
    (10 * 1024 ** 2, QColor(250, 112, 154), "10–100 MB"),
    (0,               QColor(168, 237, 234), "< 10 MB"),
]

# 蓝色系配色
_SIZE_COLORS_BLUE = [
    (10 * 1024 ** 3, QColor(41, 98, 255), "> 10 GB"),
    (1 * 1024 ** 3,  QColor(64, 156, 255), "1–10 GB"),
    (100 * 1024 ** 2, QColor(100, 181, 246), "100 MB–1 GB"),
    (10 * 1024 ** 2, QColor(144, 202, 249), "10–100 MB"),
    (0,               QColor(187, 222, 251), "< 10 MB"),
]

# 绿色系配色
_SIZE_COLORS_GREEN = [
    (10 * 1024 ** 3, QColor(46, 125, 50), "> 10 GB"),
    (1 * 1024 ** 3,  QColor(76, 175, 80), "1–10 GB"),
    (100 * 1024 ** 2, QColor(129, 199, 132), "100 MB–1 GB"),
    (10 * 1024 ** 2, QColor(165, 214, 167), "10–100 MB"),
    (0,               QColor(200, 230, 201), "< 10 MB"),
]

# 暖色系配色
_SIZE_COLORS_WARM = [
    (10 * 1024 ** 3, QColor(230, 81, 0), "> 10 GB"),
    (1 * 1024 ** 3,  QColor(245, 124, 0), "1–10 GB"),
    (100 * 1024 ** 2, QColor(255, 167, 38), "100 MB–1 GB"),
    (10 * 1024 ** 2, QColor(255, 183, 77), "10–100 MB"),
    (0,               QColor(255, 213, 79), "< 10 MB"),
]

# 配色方案映射
_COLOR_SCHEMES = {
    "default": _SIZE_COLORS_DEFAULT,
    "blue": _SIZE_COLORS_BLUE,
    "green": _SIZE_COLORS_GREEN,
    "warm": _SIZE_COLORS_WARM,
}


def _color_for_size(size_bytes: int, scheme: str = "default") -> QColor:
    """根据文件大小和配色方案返回颜色"""
    colors = _COLOR_SCHEMES.get(scheme, _SIZE_COLORS_DEFAULT)
    for threshold, color, _ in colors:
        if size_bytes >= threshold:
            return QColor(color)
    return QColor(200, 200, 200)


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / 1024 ** 3:.1f} GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / 1024 ** 2:.0f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


def _minimum_area_weights(items: list, total_area: float) -> list:
    """为极小项分配真正可见的像素面积。

    Treemap 仍然按大小表达比例，但从画布中保留一小部分面积给每个
    目录项。这避免在几十 GB 总量下，空目录的“100 字节虚拟大小”仍然
    小于一个像素。
    """
    if not items or total_area <= 0:
        return items
    count = len(items)
    if count == 1:
        return [{**items[0], "size": 1.0}]

    # 面积不等于可见：80 px² 仍可能被布局成 0.4×200px 的细线。
    # 因此按画布短边保留约 4px 的带宽；子项很多时，最多使用
    # 画布的 35% 作为保底面积，剩余面积仍按真实大小分配。
    short_side = math.sqrt(total_area)
    minimum_area = min(max(80.0, short_side * 4.0),
                       total_area * 0.35 / count)
    reserved = minimum_area * count
    proportional_area = max(0.0, total_area - reserved)
    real_total = sum(max(0.0, float(item.get("size", 0))) for item in items)

    weighted = []
    for item in items:
        real_size = max(0.0, float(item.get("size", 0)))
        share = real_size / real_total if real_total > 0 else 1.0 / count
        weighted.append({**item, "size": minimum_area + proportional_area * share})
    return weighted


def _squarify(items: list, rect: QRectF) -> List[dict]:
    """Squarified treemap 布局算法（迭代实现，避免深递归导致 GUI 线程崩溃）。

    用显式栈替代递归，保证子项数千/万时也能稳定布局（下钻不闪退）。
    """
    if not items or rect.width() <= 0 or rect.height() <= 0:
        return []

    total_size = sum(item["size"] for item in items)
    if total_size <= 0:
        return []

    sorted_items = sorted(items, key=lambda x: x["size"], reverse=True)
    total_area = rect.width() * rect.height()
    result = []

    # 显式栈：(待布局项列表, 剩余矩形)
    stack = [(sorted_items, rect)]
    while stack:
        items_to_layout, r = stack.pop()
        if not items_to_layout or r.width() <= 0 or r.height() <= 0:
            continue
        if len(items_to_layout) == 1:
            result.append({
                "node": items_to_layout[0]["node"],
                "rect": QRectF(r)
            })
            continue

        # 贪心分组：把长宽比最差的一行切出来
        row = [items_to_layout[0]]
        remaining = items_to_layout[1:]
        best_ratio = _worst_ratio(row, r, total_size, total_area)

        for i, item in enumerate(items_to_layout[1:], 1):
            test_row = row + [item]
            test_ratio = _worst_ratio(test_row, r, total_size, total_area)
            if test_ratio <= best_ratio:
                best_ratio = test_ratio
                row.append(item)
                # 修复 off-by-one：row 已包含索引 i 处的元素，
                # 剩余项必须从 i+1 开始，否则最后一项会被重复布局，
                # 导致面积超分配、后续色块被挤出画布（显示不全）。
                remaining = items_to_layout[i + 1:]
            else:
                break

        row_area = sum(item["size"] for item in row) / total_size * total_area
        is_horizontal = r.width() >= r.height()

        if is_horizontal:
            row_width = row_area / r.height() if r.height() > 0 else 0
            y = r.y()
            for item in row:
                item_area = item["size"] / total_size * total_area
                h = item_area / row_width if row_width > 0 else 0
                result.append({
                    "node": item["node"],
                    "rect": QRectF(r.x(), y, row_width, h)
                })
                y += h
            remaining_rect = QRectF(r.x() + row_width, r.y(),
                                    r.width() - row_width, r.height())
        else:
            row_height = row_area / r.width() if r.width() > 0 else 0
            x = r.x()
            for item in row:
                item_area = item["size"] / total_size * total_area
                w = item_area / row_height if row_height > 0 else 0
                result.append({
                    "node": item["node"],
                    "rect": QRectF(x, r.y(), w, row_height)
                })
                x += w
            remaining_rect = QRectF(r.x(), r.y() + row_height,
                                    r.width(), r.height() - row_height)

        if remaining:
            stack.append((remaining, remaining_rect))

    return result


def _worst_ratio(row, rect, total_size, total_area):
    if not row:
        return float('inf')
    row_area = sum(item["size"] for item in row) / total_size * total_area
    is_horizontal = rect.width() >= rect.height()

    if is_horizontal:
        side = rect.height()
        if side <= 0:
            return float('inf')
        row_width = row_area / side
        if row_width <= 0:
            return float('inf')
        worst = 0
        for item in row:
            item_area = item["size"] / total_size * total_area
            h = item_area / row_width
            if h <= 0:
                continue
            ratio = max(row_width / h, h / row_width)
            worst = max(worst, ratio)
    else:
        side = rect.width()
        if side <= 0:
            return float('inf')
        row_height = row_area / side
        if row_height <= 0:
            return float('inf')
        worst = 0
        for item in row:
            item_area = item["size"] / total_size * total_area
            w = item_area / row_height
            if w <= 0:
                continue
            ratio = max(row_height / w, w / row_height)
            worst = max(worst, ratio)
    return worst


class TreemapWidget(QWidget):
    """SpaceSniffer 风格的 Treemap 可视化组件"""

    # 信号：(当前路径, 当前名称, 是否可以返回上级)
    navigate_signal = pyqtSignal(str, str, bool)
    # 右键菜单信号：(文件夹路径, 文件夹名称, 是否有子文件夹, 全局点击坐标x, 全局点击坐标y)
    context_menu_signal = pyqtSignal(str, str, bool, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(400)
        self.setMinimumWidth(300)
        self._root_node: Optional[dict] = None
        self._current_node: Optional[dict] = None
        self._history: List[dict] = []  # 下钻历史栈
        self._layout_result: List[dict] = []
        self._hovered_item: Optional[dict] = None
        self._font = QFont("Microsoft YaHei", 10)
        self._small_font = QFont("Microsoft YaHei", 8)
        self._tiny_font = QFont("Microsoft YaHei", 7)
        self._color_scheme = "default"  # 当前配色方案
        self.setMouseTracking(True)

    def set_color_scheme(self, scheme: str):
        """设置配色方案"""
        self._color_scheme = scheme
        self.update()  # 触发重绘

    def set_data(self, folder_tree: dict):
        """设置文件夹树数据并渲染"""
        self._root_node = folder_tree
        self._current_node = folder_tree
        self._history = []
        self._layout()
        self.update()
        self._emit_navigate()

    def drill_down(self, node: dict):
        """下钻到指定节点"""
        if node and node.get("children"):
            self._history.append(self._current_node)
            self._current_node = node
            self._layout()
            self.update()
            self._emit_navigate()

    def drill_up(self):
        """返回上一级"""
        if self._history:
            self._current_node = self._history.pop()
            self._layout()
            self.update()
            self._emit_navigate()

    def drill_down_to_path(self, target_path: str):
            """下钻到指定路径的节点（迭代查找，避免深目录递归爆栈）"""
            stack = [self._root_node]
            while stack:
                node = stack.pop()
                if node.get("path") == target_path:
                    if node.get("children"):
                        self.drill_down(node)
                    return
                stack.extend(node.get("children", []))

    def can_go_back(self) -> bool:
        return len(self._history) > 0

    def get_current_path(self) -> str:
        if self._current_node:
            return self._current_node.get("path", "")
        return ""

    def get_current_name(self) -> str:
        if self._current_node:
            return self._current_node.get("name", "")
        return ""

    def _emit_navigate(self):
        """发出导航信号"""
        self.navigate_signal.emit(
            self.get_current_path(),
            self.get_current_name(),
            self.can_go_back()
        )

    def _layout(self):
        """执行布局计算 — 所有内容自适应填满视口，不滚动"""
        if not self._current_node:
            self._layout_result = []
            return

        children = self._current_node.get("children", [])
        if not children:
            self._layout_result = [{
                "node": self._current_node,
                "rect": QRectF(0, 0, self.width(), self.height())
            }]
            return

        # 所有子项都显示；真正的最小可见面积在获得画布尺寸后计算。
        # 子项过多时把最小项聚合为"其他 N 项"，防止绘制/布局卡死
        children = sorted(children, key=lambda c: c.get("size", 0), reverse=True)
        items = []
        MAX_ITEMS = 3000
        aggregated = None
        if len(children) > MAX_ITEMS:
            kept, rest = children[:MAX_ITEMS - 1], children[MAX_ITEMS - 1:]
            agg_size = sum(c.get("size", 0) for c in rest)
            agg_count = len(rest)
            is_file_agg = all(c.get("is_file") for c in rest)
            aggregated = {
                "name": f"其他 {agg_count} 项",
                "path": self._current_node.get("path", ""),
                "size": agg_size,
                "allocated": sum(c.get("allocated", 0) for c in rest),
                "file_count": sum(c.get("file_count", 0) for c in rest),
                "folder_count": sum(c.get("folder_count", 0) for c in rest),
                "is_file": is_file_agg,
                "children": [],
                "_aggregated": True,
            }
            children = kept
        for c in children:
            size = c.get("size", 0)
            items.append({"node": c, "size": max(size, 0)})
        if aggregated is not None:
            items.append({"node": aggregated, "size": max(aggregated["size"], 1)})

        if not items:
            self._layout_result = [{
                "node": self._current_node,
                "rect": QRectF(0, 0, self.width(), self.height())
            }]
            return

        # 始终使用视口尺寸，不扩展画布
        margin = 2
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return
        rect = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)
        items = _minimum_area_weights(items, rect.width() * rect.height())
        self._layout_result = _squarify(items, rect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if not self._layout_result:
            painter.setFont(self._font)
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无数据")
            painter.end()
            return

        gap = 2
        pen = QPen(QColor(255, 255, 255, 180), 1)

        for item in self._layout_result:
            node = item["node"]
            rect = item["rect"]

            if rect.width() <= 0 or rect.height() <= 0:
                continue
            # 小色块使用自适应间距，避免固定 2px 间距把整个色块吃掉。
            tile_gap = min(gap, rect.width() / 3, rect.height() / 3)
            draw_rect = rect.adjusted(
                tile_gap / 2, tile_gap / 2, -tile_gap / 2, -tile_gap / 2)

            color = _color_for_size(node.get("size", 0), self._color_scheme)
            is_hovered = (self._hovered_item and
                          self._hovered_item.get("node") is node)
            if is_hovered:
                color = color.lighter(120)

            painter.setPen(pen)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(draw_rect, 3, 3)

            # 根据方块背景亮度决定文字颜色
            brightness = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
            text_color = QColor(30, 30, 30) if brightness > 150 else QColor(255, 255, 255)
            painter.setPen(text_color)

            w = draw_rect.width()
            h = draw_rect.height()

            name = node.get("name", "")
            size_str = _format_size(node.get("size", 0))
            scan_status = node.get("scan_status", "")
            file_count = node.get("file_count", 0)
            is_file = bool(node.get("is_file"))
            icon = "📄" if is_file else "📁"

            if w >= 100 and h >= 60:
                painter.setFont(self._font)
                fm = QFontMetrics(self._font)
                name_elided = fm.elidedText(f"{icon} {name}", Qt.ElideRight, int(w - 12))
                painter.drawText(
                    draw_rect.adjusted(6, 8, -6, 0),
                    Qt.AlignLeft | Qt.AlignTop, name_elided)
                painter.setFont(self._small_font)
                painter.drawText(
                    draw_rect.adjusted(6, 8 + fm.height() + 2, -6, 0),
                    Qt.AlignLeft | Qt.AlignTop, scan_status or size_str)
                sub_color = QColor(30, 30, 30, 200) if brightness > 150 else QColor(255, 255, 255, 200)
                painter.setPen(sub_color)
                painter.setFont(self._tiny_font)
                if is_file:
                    painter.drawText(
                        draw_rect.adjusted(6, 8 + fm.height() * 2 + 4, -6, 0),
                        Qt.AlignLeft | Qt.AlignTop, "单个文件")
                else:
                    painter.drawText(
                        draw_rect.adjusted(6, 8 + fm.height() * 2 + 4, -6, 0),
                        Qt.AlignLeft | Qt.AlignTop,
                        f"📄 {file_count} 个文件")
            elif w >= 60 and h >= 35:
                painter.setFont(self._small_font)
                fm = QFontMetrics(self._small_font)
                name_elided = fm.elidedText(f"{icon} {name}", Qt.ElideRight, int(w - 8))
                painter.drawText(
                    draw_rect.adjusted(4, 4, -4, 0),
                    Qt.AlignLeft | Qt.AlignTop, name_elided)
                painter.setFont(self._tiny_font)
                painter.drawText(
                    draw_rect.adjusted(4, 4 + fm.height() + 1, -4, 0),
                    Qt.AlignLeft | Qt.AlignTop, size_str)
            elif w >= 30 and h >= 20:
                painter.setFont(self._tiny_font)
                fm = QFontMetrics(self._tiny_font)
                name_elided = fm.elidedText(name, Qt.ElideRight, int(w - 4))
                painter.drawText(
                    draw_rect.adjusted(2, 2, -2, 0),
                    Qt.AlignLeft | Qt.AlignTop, name_elided)

        painter.end()

    def mouseMoveEvent(self, event):
        pos = QPointF(event.pos())
        old_hovered = self._hovered_item
        self._hovered_item = None

        for item in self._layout_result:
            if item["rect"].contains(pos):
                self._hovered_item = item
                break

        if self._hovered_item != old_hovered:
            self.update()

        if self._hovered_item:
            node = self._hovered_item["node"]
            tip = (f"📁 {node.get('name', '')}\n"
                   f"大小: {_format_size(node.get('size', 0))}\n"
                   f"文件: {node.get('file_count', 0)} 个\n"
                   f"文件夹: {node.get('folder_count', 0)} 个\n"
                   f"路径: {node.get('path', '')}")
            if node.get("scan_status"):
                tip += f"\n状态: {node['scan_status']}"
            QToolTip.showText(event.globalPos(), tip, self)
            if node.get("children"):
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        else:
            QToolTip.hideText()
            self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._hovered_item:
            node = self._hovered_item["node"]
            if node.get("children"):
                self.drill_down(node)
        elif event.button() == Qt.RightButton and self._hovered_item:
            node = self._hovered_item["node"]
            path = node.get("path", "")
            name = node.get("name", "")
            has_children = bool(node.get("children"))
            # 发出右键信号
            self.context_menu_signal.emit(
                path, name, has_children,
                event.globalPos().x(), event.globalPos().y()
            )

    def leaveEvent(self, event):
        self._hovered_item = None
        self.update()
        super().leaveEvent(event)
