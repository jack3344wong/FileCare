# -*- coding: utf-8 -*-
"""生成用于验证 /UPDATE 静默更新逻辑的隔离测试安装包。

做的事：
1. 造一个假的 dist/FileCare/FileCare.exe（用系统 cmd.exe 冒充，
   这样它在被"重启"时可以写标记文件并立即退出，不会留下窗口）。
2. 从 packaging/FileCare.iss 派生一份测试脚本，改动仅限：
   - AppId 换成测试专用 GUID（不碰真实安装记录）
   - 输出文件名 / 安装默认目录换成测试专用
   - 两条 [Run] 项的参数改成写标记文件，用来精确验证
     "更新时跳过首批索引" 和 "更新后自动重启程序" 这两个判断
3. 用 Inno Setup 7 编译出测试安装包。
"""
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(r"D:\Project_sync_agent\FileCare文件管家项目开发")
ISS = ROOT / "packaging" / "FileCare.iss"
TEST_ISS = ROOT / "packaging" / "FileCare-updatetest.iss"
DIST = ROOT / "dist" / "FileCare"
OUTDIR = ROOT / "installer-output-updatetest"
ISCC = pathlib.Path(r"C:\Users\JackA\AppData\Local\Programs\Inno Setup 7\ISCC.exe")

MARK_INDEX = r"C:\Users\JackA\AppData\Local\Temp\fcm-index-marker.txt"
MARK_UPDATE = r"C:\Users\JackA\AppData\Local\Temp\fcm-update-marker.txt"

# 1) 假的可执行文件
DIST.mkdir(parents=True, exist_ok=True)
shutil.copy2(r"C:\Windows\System32\cmd.exe", DIST / "FileCare.exe")
print("[1] 假 exe 就绪:", DIST / "FileCare.exe",
      (DIST / "FileCare.exe").stat().st_size, "字节")

# 2) 派生测试版 .iss
src = ISS.read_text(encoding="utf-8")
# 用字面替换而不是正则:模式里含有 {} \ 等字符,正则很容易踩坑
repl = [
    # 测试专用 AppId，避免动到真实安装记录
    ("AppId={{C72DBFB2-81A5-49E4-B32A-BBF7BFE6D9AF}",
     "AppId={{9F9F9F9F-1111-2222-3333-444444444444}"),
    (r"DefaultDirName={autopf}\FileCare",
     r"DefaultDirName=C:\Users\JackA\AppData\Local\Temp\FileCareUpdateTest"),
    (r"OutputDir=..\installer-output", r"OutputDir=..\installer-output-updatetest"),
    ("OutputBaseFilename=FileCare-Setup-{#MyAppVersion}",
     "OutputBaseFilename=FileCare-UpdateTest-Setup"),
    # 首批索引项：改成写"索引标记"，用于验证更新时被跳过
    ('Parameters: "--build-name-index --index-budget-seconds 20"',
     'Parameters: "/c echo ok> ' + MARK_INDEX + '"'),
    # 更新后重启项：改成写"更新标记"，用于验证更新后确实重启了程序
    ('Filename: "{app}\\{#MyAppExeName}"; Flags: nowait; Check: IsUpdateInstall',
     'Filename: "{app}\\{#MyAppExeName}"; Parameters: "/c echo ok> ' + MARK_UPDATE +
     '"; Flags: nowait; Check: IsUpdateInstall'),
]
out = src
for old, new in repl:
    n = out.count(old)
    flag = "OK " if n == 1 else "!! 命中 {0} 次".format(n)
    print("[2] {0} {1}".format(flag, old[:62]))
    if n != 1:
        sys.exit("替换失败，测试脚本未生成")
    out = out.replace(old, new)

TEST_ISS.write_text(out, encoding="utf-8")
print("[2] 测试脚本已写入:", TEST_ISS)

# 3) 编译
if not ISCC.is_file():
    sys.exit(f"找不到 ISCC.exe: {ISCC}")
proc = subprocess.run([str(ISCC), str(TEST_ISS)],
                      capture_output=True, text=True, encoding="utf-8",
                      errors="replace")
print("[3] ISCC 退出码:", proc.returncode)
print("---- ISCC 输出 ----")
print((proc.stdout or "") + (proc.stderr or ""))
built = OUTDIR / "FileCare-UpdateTest-Setup.exe"
print("[3] 产物存在:", built.is_file(), built)
if built.is_file():
    print("[3] 大小:", built.stat().st_size, "字节")