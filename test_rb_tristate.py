# -*- coding: utf-8 -*-
"""只读验证回收站页面：三态全选复选框 + 恢复/删除按钮启用状态。

不依赖用户回收站里已有的内容（用户随时可能清空）：测试自建两个临时文件
送入回收站，跑完再从回收站永久删除，只操作自己产生的项目。
"""
import os, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

sys.path.insert(0, str(Path(__file__).parent / "src"))
import main  # noqa: F401
from main_window import DiskMonitor
from recycle_bin import WindowsRecycleBin, _run_ps

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


def recycle(path):
    """把自建临时文件送入系统回收站（Shell COM，等同资源管理器删除）。"""
    os.environ["FILECARE_TEST_TARGET"] = path
    try:
        return _run_ps(_RECYCLE_PS)
    finally:
        os.environ.pop("FILECARE_TEST_TARGET", None)


def recycled_index(name):
    """在回收站中按名称定位条目（「名称」列可能隐藏已知类型的扩展名）。"""
    stem = os.path.splitext(name)[0]
    for entry in WindowsRecycleBin.get_items():
        if entry["name"] in (name, stem):
            return entry["index"]
    return None


test_files = []
for i in (1, 2):
    handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    handle.write(("三态全选测试文件 %d\n" % i).encode("utf-8"))
    handle.close()
    if "OK" not in recycle(handle.name):
        raise SystemExit("临时文件未能送入回收站，无法验证三态：%s" % handle.name)
    test_files.append(handle.name)

test_names = [os.path.basename(p) for p in test_files]

app = QApplication.instance() or QApplication([])
DiskMonitor._auto_rebuild_index_on_startup = lambda self: None
DiskMonitor._show_first_index_notice = lambda self: None
w = DiskMonitor()
w.show()
app.processEvents()

w._show_recycle_view()
app.processEvents()
for _ in range(10):
    w._rb_load_items()
    app.processEvents()
    if all(recycled_index(n) is not None for n in test_names):
        break
    time.sleep(0.3)

total = w._rb_tree.topLevelItemCount()
print("回收站项目数 =", total)


def snap(tag):
    st = w._rb_select_all_cb.checkState()
    name = {Qt.Unchecked: "Unchecked(空)", Qt.PartiallyChecked: "PartiallyChecked(半选蓝填充)",
            Qt.Checked: "Checked(全选蓝勾)"}[st]
    print(f"[{tag}] 全选框={name} 已选={w._rb_selected_label.text()} "
          f"恢复按钮={'可用' if w._rb_btn_restore.isEnabled() else '禁用'} "
          f"删除按钮={'可用' if w._rb_btn_delete.isEnabled() else '禁用'}")
    return st


ok = True


def expect(tag, cond):
    global ok
    print(f"    -> {'PASS' if cond else 'FAIL'} {tag}")
    if not cond:
        ok = False


if total == 0:
    expect("自建测试项已出现在回收站中", False)
else:
    st = snap("初始")
    expect("初始为 Unchecked", st == Qt.Unchecked)
    expect("初始按钮禁用", not w._rb_btn_restore.isEnabled() and not w._rb_btn_delete.isEnabled())

    cbs = [w._rb_checkbox(w._rb_tree.topLevelItem(i)) for i in range(total)]
    if total >= 2:
        cbs[0].setChecked(True)
        app.processEvents()
        st = snap("勾1项")
        expect("部分选中 -> PartiallyChecked", st == Qt.PartiallyChecked)
        expect("部分选中 -> 按钮可用",
               w._rb_btn_restore.isEnabled() and w._rb_btn_delete.isEnabled())

        # 半选状态下点击全选框应变为全选
        w._rb_select_all_cb.setCheckState(Qt.Checked)
        app.processEvents()
        st = snap("全选")
        expect("全选 -> Checked", st == Qt.Checked)
        expect("所有行都被勾选", all(c.isChecked() for c in cbs))

        cbs[0].setChecked(False)
        app.processEvents()
        st = snap("取消1项")
        expect("取消一项 -> PartiallyChecked", st == Qt.PartiallyChecked)

        for c in cbs:
            c.setChecked(False)
        app.processEvents()
        st = snap("全不选")
        expect("全不选 -> Unchecked", st == Qt.Unchecked)
        expect("全不选 -> 按钮禁用",
               not w._rb_btn_restore.isEnabled() and not w._rb_btn_delete.isEnabled())
    else:
        cbs[0].setChecked(True)
        app.processEvents()
        st = snap("勾1项")
        expect("全部选中 -> Checked", st == Qt.Checked)

out = Path(__file__).parent / "_cbtest" / "rb_toolbar.png"
out.parent.mkdir(parents=True, exist_ok=True)
if not w.grab().save(str(out), "PNG"):
    raise SystemExit(f"截图保存失败（目录不可写？）: {out}")
print("SAVED:", out)

# 清理：把自建测试项从回收站永久删除，不给用户留下痕迹
for name in test_names:
    idx = recycled_index(name)
    if idx is None:
        expect(f"回收站中仍能找到测试项 {name} 以便清理", False)
        continue
    cleaned, msg = WindowsRecycleBin.delete_item(idx)
    expect(f"清理测试项 {name}", cleaned)
    if not cleaned:
        print("      清理失败原因:", msg)
for path in test_files:
    if os.path.exists(path):
        os.remove(path)

print("RESULT:", "ALL PASS" if ok else "HAS FAILURES")