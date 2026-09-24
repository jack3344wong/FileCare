# -*- coding: utf-8 -*-
"""闭环验证：临时文件 -> 回收站 -> 还原 -> 再入回收站 -> 永久删除。
全程只操作自己创建的临时文件，不触碰用户回收站中已有的项目。"""
import os, sys, time, shutil, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from recycle_bin import WindowsRecycleBin, _run_ps

TAG = f"_filecare_test_{os.getpid()}_{int(time.time())}"
WORK = os.path.join(tempfile.gettempdir(), TAG)
os.makedirs(WORK, exist_ok=True)
TARGET = os.path.join(WORK, TAG + ".txt")

RECYCLE_PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$path = $env:FILECARE_TEST_TARGET
$shell = New-Object -ComObject Shell.Application
$dir = Split-Path $path -Parent
$leaf = Split-Path $path -Leaf
$rb = $shell.NameSpace(0xa)
$ns = $shell.NameSpace($dir)
if ($ns -eq $null) { Write-Host "ERROR:无法打开目录 $dir"; exit 1 }
$item = $ns.ParseName($leaf)
if ($item -eq $null) { Write-Host "ERROR:找不到文件 $leaf"; exit 1 }
$rb.MoveHere($item)
Write-Host "OK"
"""

ok = True


def check(tag, cond, extra=""):
    global ok
    print(f"  {'PASS' if cond else 'FAIL'}  {tag}{(' | ' + extra) if extra else ''}")
    if not cond:
        ok = False


def to_recycle(path):
    os.environ["FILECARE_TEST_TARGET"] = path
    try:
        return _run_ps(RECYCLE_PS)
    finally:
        os.environ.pop("FILECARE_TEST_TARGET", None)


def find_index(name):
    """按文件名定位回收站条目。

    Windows 回收站「名称」列会隐藏已知类型文件的扩展名（本机开启了
    「隐藏已知文件类型的扩展名」时如此），因此列出的是 `foo` 而不是
    `foo.txt`。这里同时比对完整名与去掉扩展名后的名称。
    """
    stem = os.path.splitext(name)[0]
    for e in WindowsRecycleBin.get_items():
        if e["name"] in (name, stem):
            return e["index"]
    return None


try:
    # ── 准备：创建临时文件 ──
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write("FileCare 回收站功能测试文件\n" * 10)
    print(f"1) 已创建测试文件: {TARGET}")

    # ── 送入回收站 ──
    out = to_recycle(TARGET)
    print(f"2) 送入回收站 -> {out.strip()!r}")
    check("文件已从磁盘移走", not os.path.exists(TARGET))
    idx = find_index(os.path.basename(TARGET))
    check("能在回收站列表中读到该文件", idx is not None, f"index={idx}")

    # ── 测试「恢复」 ──
    if idx is not None:
        succ, msg = WindowsRecycleBin.restore_item(idx)
        print(f"3) 还原 -> {(succ, msg)}")
        check("还原返回成功", succ, msg)
        check("文件已回到原位置", os.path.exists(TARGET))
        check("回收站中已无该文件", find_index(os.path.basename(TARGET)) is None)

    # ── 再次送入回收站，测试「永久删除」 ──
    if os.path.exists(TARGET):
        to_recycle(TARGET)
        idx = find_index(os.path.basename(TARGET))
        check("再次进入回收站", idx is not None, f"index={idx}")
        if idx is not None:
            succ, msg = WindowsRecycleBin.delete_item(idx)
            print(f"4) 永久删除 -> {(succ, msg)}")
            check("永久删除返回成功", succ, msg)
            check("回收站中已无该文件", find_index(os.path.basename(TARGET)) is None)
            check("磁盘上也没有该文件", not os.path.exists(TARGET))
finally:
    shutil.rmtree(WORK, ignore_errors=True)
    # 兜底：若文件被还原出来，确保清理
    if os.path.exists(TARGET):
        os.remove(TARGET)
    print(f"5) 已清理临时目录: {WORK}")

print("RESULT:", "ALL PASS" if ok else "HAS FAILURES")
sys.exit(0 if ok else 1)