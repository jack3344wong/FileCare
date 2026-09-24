# -*- coding: utf-8 -*-
"""真实 GitHub 端到端验证：下载真实安装包并用 GitHub 提供的 SHA256 校验。

这一步会真的从 GitHub 拉取 FileCare-Setup-1.1.0.exe（约 37.8MB），
用于证明"检查 -> 下载 -> 校验 -> 构造安装命令"整条链路在真实网络下可用。
仅下载到临时目录，不会执行安装。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

import updater
from updater import (ReleaseAsset, UpdateInfo, check_for_update,
                     download_installer, installer_command, launch_installer,
                     UpdateError, format_size)

print("=" * 62)
print("真实 GitHub 端到端验证")
print("=" * 62)

# ---------------------------------------------------------------- 1. 检查更新
print("\n[1] check_for_update()  当前版本 =", updater.APP_VERSION)
t0 = time.time()
try:
    info = check_for_update()          # 真实网络请求
    print("    请求成功，用时 %.2fs" % (time.time() - t0))
    if info is None:
        print("    => 本机版本已是最新（GitHub 最新为已发布的 v1.1.0，程序为 %s）"
              % updater.APP_VERSION)
    else:
        print("    => 发现新版本", info.version)
except UpdateError as exc:
    print("    => UpdateError:", exc)

# ---------------------------------------------------------------- 2. 构造待下载项
print("\n[2] 直接向 GitHub 取 v1.1.0 的真实 Release JSON 并解析")
import json
import urllib.request
req = urllib.request.Request(
    "https://api.github.com/repos/jack3344wong/FileCare/releases/latest",
    headers={"User-Agent": updater.USER_AGENT,
             "Accept": "application/vnd.github+json"})
with urllib.request.urlopen(req, timeout=20) as resp:
    payload = json.loads(resp.read().decode("utf-8"))

real = updater._parse_release(payload, "1.0.0")   # 假装自己是 1.0.0
if real is None:
    print("    !! 解析失败，无法继续")
    sys.exit(1)
print("    版本     :", real.version)
print("    附件     :", real.asset.name)
print("    大小     :", real.size_display, "(%d 字节)" % real.asset.size)
print("    digest   :", real.asset.digest[:32], "...")
print("    下载通道 :", len(updater.download_candidates(real.asset)), "条")
print("    预发布过滤: is_newer('1.1.0','1.3.0') =",
      updater.is_newer("1.1.0", "1.3.0"), "(应为 False)")

# ---------------------------------------------------------------- 3. 真实下载
print("\n[3] download_installer()  真实下载中（约 37.8MB，请稍候）...")
ticks = []


def on_progress(done, total):
    ticks.append((done, total))
    if len(ticks) % 40 == 0:
        pct = (done * 100.0 / total) if total else 0
        print("    进度 %6.2f%%  %s / %s" % (pct, format_size(done), format_size(total)))


t0 = time.time()
try:
    path = download_installer(real, progress=on_progress)
except UpdateError as exc:
    print("    !! 下载失败:", exc)
    sys.exit(1)

elapsed = time.time() - t0
actual_size = path.stat().st_size
print("    下载完成，用时 %.1fs" % elapsed)
print("    本地路径:", path)
print("    实际大小: %d 字节" % actual_size)
print("    进度回调: %d 次" % len(ticks))
print("    大小一致:", actual_size == real.asset.size)

# 独立复算 SHA256，与 GitHub digest 对比
import hashlib
h = hashlib.sha256()
with open(path, "rb") as fh:
    for block in iter(lambda: fh.read(1024 * 1024), b""):
        h.update(block)
local_sha = h.hexdigest()
gh_sha = updater._digest_sha256(real.asset.digest)
print("    本地SHA256:", local_sha)
print("    GitHub    :", gh_sha)
print("    校验通过  :", local_sha == gh_sha)

# 文件头确认是真正的 Windows 可执行文件
with open(path, "rb") as fh:
    magic = fh.read(2)
print("    文件头    :", magic, "(应为 b'MZ')")

# ---------------------------------------------------------------- 4. 安装命令
print("\n[4] 安装命令构造")
cmd = installer_command(path)
print("    ", " ".join('"%s"' % c if " " in c else c for c in cmd))
ok_flags = all(f in cmd for f in ("/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS", "/UPDATE"))
print("    静默参数齐全:", ok_flags)

# 不存在的安装包应报错而不是静默失败
try:
    launch_installer(Path("C:/definitely/not/here.exe"))
    print("    不存在文件的处理: !! 未报错（异常）")
except UpdateError as exc:
    print("    不存在文件的处理: 正确报错 ->", exc)

# ---------------------------------------------------------------- 结论
print("\n" + "=" * 62)
ok = (actual_size == real.asset.size and local_sha == gh_sha
      and magic == b"MZ" and ok_flags)
print("结论:", "真实下载与校验全部通过" if ok else "存在失败项")
print("=" * 62)
sys.exit(0 if ok else 1)