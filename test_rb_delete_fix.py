# -*- coding: utf-8 -*-
"""验证回收站「永久删除」不再因确认对话框而阻塞。

背景：旧实现用 $item.Verbs() 里的「删除」动词，会弹出标题为“删除文件”的
确认框，无人点击时 PowerShell 一直挂着，30 秒超时后报错。

本测试只操作自己产生的 _filecare_test_* 残留，不会碰用户的其他回收站项目。
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import tempfile
import time
import pathlib
import shutil

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))
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


def find_index(name):
    """在回收站中按名称定位条目（「名称」列可能隐藏已知类型的扩展名）。"""
    stem = os.path.splitext(name)[0]
    for entry in WindowsRecycleBin.get_items():
        if entry["name"] in (name, stem):
            return entry["index"]
    return None

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print("  {0} {1}{2}".format("通过" if cond else "失败", name,
                                "  [" + str(extra) + "]" if extra else ""))


user32 = ctypes.windll.user32


def dialog_titles():
    """当前可见的 Windows 对话框标题（#32770 是对话框窗口类）。"""
    found = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value != "#32770":
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        t = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, t, n + 1)
        if t.value:
            found.append(t.value)
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(cb), 0)
    return found


print("=" * 72)
print("永久删除：不再弹确认框、不再阻塞")
print("=" * 72)

targets = [it for it in WindowsRecycleBin.get_items()
           if "_filecare_test" in it.get("name", "")]
print("待清理的测试残留: {0} 个".format(len(targets)))
for it in targets:
    print("   index={0}  {1}".format(it["index"], it["name"]))

if not targets:
    print("没有测试残留可删（可能上次已清理干净）")

def delete_and_verify(idx, name):
    """执行一次永久删除，并核对耗时、确认框与耗时上限。"""
    t0 = time.time()
    ok, msg = WindowsRecycleBin.delete_item(idx)
    dt = time.time() - t0
    print("\n删除 index={0} ({1}) -> ok={2} msg={3}  耗时={4:.1f}s".format(
        idx, name, ok, msg, dt))
    check("删除 {0} 成功".format(name), ok, msg)
    check("删除 {0} 未超时（远小于 30 秒上限）".format(name), dt < 10,
          "{0:.1f}s".format(dt))

    dlg = dialog_titles()
    check("删除 {0} 没有弹出对话框".format(name),
          not any("删除文件" in t for t in dlg), dlg or "无")
    check("删除 {0} 的元数据文件也一并清理".format(name), msg == "已永久删除", msg)


# 索引会随删除变化，因此按降序处理
for it in sorted(targets, key=lambda x: x["index"], reverse=True):
    delete_and_verify(it["index"], it["name"])

# 其他测试都会自清理，回收站里往往没有残留可删，那样就验证不到真正的删除路径。
# 这里自建一个测试项送入回收站再删除，保证每次运行都真的走一遍永久删除。
WORK = os.path.join(tempfile.gettempdir(), "_filecare_delete_fix_{0}".format(os.getpid()))
os.makedirs(WORK, exist_ok=True)
OWN_PATH = os.path.join(WORK, "_filecare_test_delete_fix.txt")
with open(OWN_PATH, "w", encoding="utf-8") as f:
    f.write("永久删除回归测试文件\n")
OWN_NAME = os.path.basename(OWN_PATH)

out = recycle(OWN_PATH)
check("自建测试项已送入回收站", "OK" in out and not os.path.exists(OWN_PATH),
      out.strip() or "无输出")
own_idx = find_index(OWN_NAME)
if own_idx is None:
    check("能在回收站中找到自建测试项", False, "index=None")
else:
    check("能在回收站中找到自建测试项", True, "index={0}".format(own_idx))
    delete_and_verify(own_idx, OWN_NAME)

shutil.rmtree(WORK, ignore_errors=True)
if os.path.exists(OWN_PATH):
    os.remove(OWN_PATH)

print()
print("=" * 72)
after = [it for it in WindowsRecycleBin.get_items()
         if "_filecare_test" in it.get("name", "")]
check("回收站中已无测试残留", not after,
      [x["name"] for x in after] if after else "已清空")
remaining = WindowsRecycleBin.get_items()
print("剩余项目（应为用户自己的项目，未被触碰）: {0} 个".format(len(remaining)))
for it in remaining:
    print("   {0}".format(it.get("name")))

print()
print("=" * 72)
failed = [n for n, ok in results if not ok]
print("合计 {0} 项，通过 {1} 项，失败 {2} 项".format(
    len(results), len(results) - len(failed), len(failed)))
for n in failed:
    print("  失败:", n)
print("=" * 72)
sys.exit(1 if failed else 0)