# -*- coding: utf-8 -*-
"""真实运行安装包，验证应用内更新（/SILENT /UPDATE）的两条关键逻辑。

前置：先运行 make_update_test_installer.py 生成测试安装包。
需要本机安装 Inno Setup 7。

验证目标（对应 FileCare.iss 中 Check: IsUpdateInstall / not IsUpdateInstall）：
  场景 A：/SILENT /UPDATE ——应用内「检查更新」触发的静默安装
     期望：程序文件被安装；安装结束后自动重新打开程序；
           跳过阻塞式的首批索引。
  场景 B：/SILENT（无 /UPDATE）——与改动前的行为完全一致
     期望：程序文件被安装；首批索引照旧执行；
           postinstall 启动程序被 skipifsilent 跳过。

注意：重启项带 nowait，被启动的进程是异步写标记的，
所以场景 A 必须轮询等待标记出现，否则会误判失败。

安装目标、AppId 均为测试专用，不会影响任何真实安装。
"""
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(r"D:\Project_sync_agent\FileCare文件管家项目开发")
SETUP = ROOT / "installer-output-updatetest" / "FileCare-UpdateTest-Setup.exe"
TMP = pathlib.Path(r"C:\Users\JackA\AppData\Local\Temp")
TESTDIR = TMP / "FileCareUpdateTest"
MARK_INDEX = TMP / "fcm-index-marker.txt"
MARK_UPDATE = TMP / "fcm-update-marker.txt"
TEST_KEY = ("HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
            "{9F9F9F9F-1111-2222-3333-444444444444}_is1")

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    print("  {0} {1}{2}".format("通过" if cond else "失败", name,
                                "  [" + str(extra) + "]" if extra else ""))


def cleanup():
    for m in (MARK_INDEX, MARK_UPDATE):
        m.unlink(missing_ok=True)
    shutil.rmtree(TESTDIR, ignore_errors=True)


def wait_for(path, timeout=10.0):
    """轮询等待 nowait 启动的子进程把标记写出来。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.is_file():
            return True
        time.sleep(0.2)
    return False


def run_setup(extra_args):
    args = [str(SETUP), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            "/MERGETASKS=!desktopicon,!startmenuicon",
            "/DIR=" + str(TESTDIR)] + extra_args
    p = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    return p.returncode


if not SETUP.is_file():
    sys.exit("请先运行 make_update_test_installer.py 生成测试安装包：{0}".format(SETUP))

print("=" * 72)
print("场景 A：/SILENT /UPDATE  （应用内检查更新触发的静默安装）")
print("=" * 72)
cleanup()
rc = run_setup(["/UPDATE"])
check("安装程序正常结束", rc == 0, "rc={0}".format(rc))
check("程序文件已安装", (TESTDIR / "FileCare.exe").is_file())
check("更新后自动重新打开程序（IsUpdateInstall 分支生效）",
      wait_for(MARK_UPDATE), "等待 nowait 子进程写标记")
check("更新时跳过首批索引（not IsUpdateInstall 分支被正确排除）",
      not MARK_INDEX.is_file())

print()
print("=" * 72)
print("场景 B：/SILENT（无 /UPDATE）  ——应与改动前完全一致")
print("=" * 72)
cleanup()
rc = run_setup([])
check("安装程序正常结束", rc == 0, "rc={0}".format(rc))
check("程序文件已安装", (TESTDIR / "FileCare.exe").is_file())
check("首批索引照旧执行（原有行为未被破坏）", MARK_INDEX.is_file())
# 给可能出现的异步写入留足时间，再断言"没有启动程序"
time.sleep(3.0)
check("静默安装不自动启动程序（skipifsilent 行为未变）",
      not MARK_UPDATE.is_file())

print()
print("=" * 72)
failed = [n for n, ok, _ in results if not ok]
print("合计 {0} 项，通过 {1} 项，失败 {2} 项".format(
    len(results), len(results) - len(failed), len(failed)))
for n in failed:
    print("  失败:", n)
print("=" * 72)

cleanup()
subprocess.run(["reg", "delete", TEST_KEY, "/f"], capture_output=True)
print("测试痕迹已清理（标记文件、安装目录、测试注册表项）")
sys.exit(1 if failed else 0)