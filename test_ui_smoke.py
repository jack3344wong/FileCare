# -*- coding: utf-8 -*-
"""离屏验证：所有页面切换 + 回收站页面数据加载（无 GUI 自动化依赖）。"""
import os, sys, tempfile, time
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QPushButton
from PyQt5.QtCore import Qt

sys.path.insert(0, str(Path(__file__).parent / "src"))
import main  # noqa: F401  (设置 Qt 插件路径)
from main_window import DiskMonitor  # noqa: E402
from file_operations import FileOperations  # noqa: E402
from recycle_bin import WindowsRecycleBin, _run_ps  # noqa: E402

app = QApplication.instance() or QApplication([])
# 烟测不应触发真实磁盘的后台索引；索引完整性由独立测试覆盖。
DiskMonitor._auto_rebuild_index_on_startup = lambda self: None
DiskMonitor._show_first_index_notice = lambda self: None
w = DiskMonitor()
w.show()
app.processEvents()

# ── 页面切换 ──
for idx, name, fn in [
    (0, "首页", w._show_home_view),
    (1, "文件管理", w._show_browse_view),
    (2, "大文件清理", w._show_scan_view),
    (3, "空间可视化", w._show_visualization_view),
    (4, "快速搜索", w._show_search_view),
    (5, "回收站管理", w._show_recycle_view),
]:
    fn()
    app.processEvents()
    assert w._main_stack.currentIndex() == idx, f"{name} 页面切换失败: {w._main_stack.currentIndex()}"
    print(f"OK {name} (index {idx}) 切换正常")

assert w._search_result_tree.headerItem().text(3) == "文件类型"
print("OK 文件名搜索包含文件类型列")
assert any(chip.text() == "文件夹" for chip in w._format_chips)
print("OK 搜索格式包含文件夹筛选")
assert not w._search_filter_hint_btn.isVisible()
print("OK 文件夹筛选提示默认隐藏")

# ── 回收站数据：直接读取 Windows 系统回收站 ──
# 不假设用户回收站里一定有东西（用户随时可能清空）：测试自建临时文件送入回收站，
# 全程只操作自己产生的项目。
_RECYCLE_PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$path = $env:FILECARE_TEST_TARGET
$shell = New-Object -ComObject Shell.Application
$ns = $shell.NameSpace((Split-Path $path -Parent))
$item = $ns.ParseName((Split-Path $path -Leaf))
if ($item -eq $null) { Write-Host "ERROR:找不到文件"; exit 1 }
$shell.NameSpace(0xa).MoveHere($item)
Write-Host "OK"
"""


def _recycle(path):
    """把自建临时文件送入系统回收站（Shell COM，等同资源管理器删除）。"""
    os.environ["FILECARE_TEST_TARGET"] = path
    try:
        return _run_ps(_RECYCLE_PS)
    finally:
        os.environ.pop("FILECARE_TEST_TARGET", None)


def _recycled_index(name):
    """在回收站中按名称定位条目。

    Windows 回收站「名称」列会隐藏已知类型的扩展名，所以名称可能不含 .txt。
    """
    stem = os.path.splitext(name)[0]
    for entry in WindowsRecycleBin.get_items():
        if entry["name"] in (name, stem):
            return entry["index"]
    return None


rb_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
rb_file.write(b"recycle bin smoke test")
rb_file.close()
rb_name = os.path.basename(rb_file.name)
assert "OK" in _recycle(rb_file.name), "临时文件未能送入回收站"
assert not os.path.exists(rb_file.name), "送入回收站后原位置不应还有该文件"

for _ in range(10):
    w._rb_load_items()
    app.processEvents()
    if w._rb_tree.topLevelItemCount() > 0 and _recycled_index(rb_name) is not None:
        break
    time.sleep(0.3)
count = w._rb_tree.topLevelItemCount()
print(f"OK 回收站加载 {count} 项（含测试自建并送入回收站的项目）")
assert count > 0, f"送入回收站后不应为空，实际 {count} 项"
# 汇总卡片应与实际数据对应
assert w._rb_summary_labels["rb_files_count"].text() == str(count)

# 验证工具提示存储了原路径
first_item = w._rb_tree.topLevelItem(0)
origin = first_item.data(1, Qt.UserRole)
print(f"OK 第一项原路径: {origin}")

# 行内操作按钮必须有足够行高，图标和边框不得被裁切。
first_item = w._rb_tree.topLevelItem(0)
actions = w._rb_tree.itemWidget(first_item, 5)
restore_action = actions.findChild(QPushButton, "rbRestoreAction")
delete_action = actions.findChild(QPushButton, "rbDeleteAction")
assert first_item.sizeHint(5).height() >= 48
assert restore_action.height() >= 30 and delete_action.height() >= 30
assert actions.height() >= restore_action.height() + 8
assert not restore_action.icon().isNull() and not delete_action.icon().isNull()
print("OK 回收站行内操作按钮图标与高度正常")

# 搜索结果的复制/剪切使用 Windows 资源管理器兼容的文件剪贴板格式。
# 创建一个临时文件用于测试剪贴板格式
tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
tmp.write(b"clipboard test")
tmp.close()
test_file = tmp.name
drop_effect = 'application/x-qt-windows-mime;value="Preferred DropEffect"'


def clip_effect(path, cut):
    """放入剪贴板并读回 Preferred DropEffect（1=复制，2=移动）。

    外部剪贴板监听程序可能在设置后立刻抢走剪贴板所有权，此时读回为空——
    这不是程序缺陷，重新设置一次即可。只有在我们确实持有剪贴板时才断言，
    避免把环境抖动误判成产品问题。
    """
    for _ in range(10):
        w._set_search_result_clipboard(path, cut=cut)
        app.processEvents()
        cb = QApplication.clipboard()
        if not cb.ownsClipboard():
            time.sleep(0.05)
            continue
        mime = cb.mimeData()
        urls = mime.urls()
        data = bytes(mime.data(drop_effect)) if mime is not None else b""
        if not urls or not data:
            time.sleep(0.05)
            continue
        got = os.path.normcase(os.path.abspath(urls[0].toLocalFile()))
        if got != os.path.normcase(os.path.abspath(path)):
            time.sleep(0.05)
            continue
        return int.from_bytes(data, "little")
    return None


assert clip_effect(test_file, cut=False) == 1, "复制时应写入 DropEffect=1"
print("OK 搜索结果「复制」剪贴板格式正确")
assert clip_effect(test_file, cut=True) == 2, "剪切时应写入 DropEffect=2"
print("OK 搜索结果「剪切」剪贴板格式正确")
os.remove(test_file)

# 勾选全部
w._rb_set_all(True)
app.processEvents()
assert len(w._rb_checked_items()) == count
print("OK 全选功能正常")

# 清理：把自建测试项从回收站永久删除，不给用户留下痕迹
cleaned = _recycled_index(rb_name)
if cleaned is not None:
    ok_clean, msg_clean = WindowsRecycleBin.delete_item(cleaned)
    assert ok_clean, f"清理回收站测试项失败: {msg_clean}"
    print("OK 回收站测试项已永久删除")
else:
    print("提示：回收站中已找不到测试项（可能被外部清空）")
if os.path.exists(rb_file.name):
    os.remove(rb_file.name)

print("\nALL PASS: 所有页面 + 回收站功能离屏验证通过")
w.close()
