# -*- coding: utf-8 -*-
"""更新模块核心逻辑测试（不需要真实 GitHub Release 也能完整验证）。

覆盖：版本解析与比较、Release JSON 解析、安装包挑选、
下载/进度/大小校验/SHA256 校验/取消、安装命令行构造。
"""
import functools
import hashlib
import http.server
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from version import APP_VERSION, is_newer, parse_version          # noqa: E402
from updater import (                                              # noqa: E402
    SILENT_INSTALL_FLAGS,
    ReleaseAsset,
    UpdateError,
    UpdateInfo,
    _parse_release,
    _pick_installer_asset,
    check_for_update,
    download_installer,
    format_size,
    installer_command,
)

FAILURES = []


def check(name, condition, extra=""):
    status = "PASS" if condition else "FAIL"
    line = "[{0}] {1}".format(status, name)
    if extra:
        line += "  -> " + str(extra)
    print(line)
    if not condition:
        FAILURES.append(name)


# ------------------------------------------------------------ 1. 版本比较
def test_versions():
    print("\n=== 1. 版本解析与比较 ===")
    cases = [
        ("v1.3.0", (1, 3, 0)),
        ("1.3.0", (1, 3, 0)),
        ("V1.2", (1, 2)),
        ("1.3.0-beta", (1, 3, 0, -1)),
        ("", ()),
        (None, ()),
        ("abc", ()),
    ]
    for raw, expected in cases:
        check("parse_version({0!r}) == {1}".format(raw, expected),
              parse_version(raw) == expected, parse_version(raw))

    newer = [
        ("1.3.0", "1.2.0", True),
        ("v1.3.0", "1.3.0", False),
        ("1.3.1", "1.3.0", True),
        ("1.10.0", "1.9.0", True),      # 字符串比较会出错，这里必须为 True
        ("2.0", "1.9.9", True),
        ("1.2.0", "1.3.0", False),
        ("1.3.0", "1.3.0-beta", True),  # 正式版比预发布版新
        ("1.3.0-beta", "1.3.0", False),
        ("bad", "1.3.0", False),        # 解析失败绝不误报
        ("1.3.0", "bad", False),
    ]
    for remote, local, expected in newer:
        check("is_newer({0!r}, {1!r}) == {2}".format(remote, local, expected),
              is_newer(remote, local) is expected, is_newer(remote, local))


# ------------------------------------------------------------ 2. 附件挑选
def test_asset_pick():
    print("\n=== 2. 安装包挑选 ===")
    assets = [
        {"name": "FileCare-Setup-1.3.0.exe", "browser_download_url": "u1", "size": 100},
        {"name": "FileCare-Setup-1.3.0.sha256", "browser_download_url": "u2"},
        {"name": "source.zip", "browser_download_url": "u3"},
    ]
    picked = _pick_installer_asset(assets, "1.3.0")
    check("优先选中 FileCare-Setup-1.3.0.exe", picked and picked.name == "FileCare-Setup-1.3.0.exe",
          picked.name if picked else None)

    picked = _pick_installer_asset([
        {"name": "FileCare-Setup-1.2.0.exe", "browser_download_url": "u1"},
        {"name": "FileCare-Setup-1.3.0.exe", "browser_download_url": "u2"},
    ], "1.3.0")
    check("多版本时选带当前版本号的那个", picked and picked.name == "FileCare-Setup-1.3.0.exe",
          picked.name if picked else None)

    check("只有 zip 时返回 None（退回手动下载）",
          _pick_installer_asset([{"name": "x.zip", "browser_download_url": "u"}], "1.3.0") is None)
    check("空附件返回 None", _pick_installer_asset([], "1.3.0") is None)
    check("缺少下载地址的附件被跳过",
          _pick_installer_asset([{"name": "FileCare-Setup-1.3.0.exe", "browser_download_url": ""}], "1.3.0") is None)


# ------------------------------------------------------------ 3. Release 解析
def test_parse_release():
    print("\n=== 3. Release JSON 解析 ===")

    def payload(tag, assets=None, body="说明", html="https://example.com/rel",
                current=None):
        return _parse_release(
            {"tag_name": tag, "body": body, "html_url": html,
             "published_at": "2026-09-24T10:00:00Z", "assets": assets or []},
            current or APP_VERSION)

    info = payload("v9.9.9", [
        {"name": "FileCare-Setup-9.9.9.exe", "browser_download_url": "u", "size": 2048,
         "digest": "sha256:deadbeef"}])
    check("更新版本被识别", info is not None and info.version == "9.9.9",
          info.version if info else None)
    check("标志位 has_installer 为真", info is not None and info.has_installer)
    check("附件 digest 被保留",
          info is not None and info.asset.digest == "sha256:deadbeef")
    check("更新说明被读取", info is not None and info.notes == "说明")
    check("大小显示正确", info is not None and info.size_display == "2.0 KB",
          info.size_display if info else None)

    check("同版本不提示更新", payload("v" + APP_VERSION) is None)
    check("旧版本不提示更新", payload("v0.0.1") is None)
    check("缺少 tag 时不提示更新",
          _parse_release({"tag_name": ""}, APP_VERSION) is None)
    info = payload("v9.9.9")
    check("没有安装包时 has_installer 为假", info is not None and not info.has_installer)

    print("    format_size: 0->{0}, 1536->{1}, 5242880->{2}".format(
        format_size(0), format_size(1536), format_size(5242880)))
    check("format_size 处理 1.5MB", format_size(1572864) == "1.5 MB", format_size(1572864))


# ------------------------------------------------------------ 4. 下载闭环
class _Server:
    """临时本地 HTTP 服务器，用来完整验证下载流程（不依赖真实网络）。"""

    def __init__(self, directory):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(directory))
        self._httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def url(self, name):
        return "http://127.0.0.1:{0}/{1}".format(self.port, name)

    def close(self):
        self._httpd.shutdown()
        self._httpd.server_close()


def test_download():
    print("\n=== 4. 下载 / 校验 / 取消 ===")
    work = Path(tempfile.mkdtemp(prefix="fc_upd_test_"))
    # 真实安装包是 PE 文件（以 MZ 开头），夹具也必须带同样的文件头，
    # 否则会被 _verify_file_signature 当成"网络拦截页"拦下
    payload_bytes = b"MZ" + b"FILECARE-INSTALLER-PAYLOAD-" * 20000   # ~560KB，多块传输
    source = work / "FileCare-Setup-9.9.9.exe"
    source.write_bytes(payload_bytes)
    real_sha = hashlib.sha256(payload_bytes).hexdigest()

    server = _Server(work)
    out_dir = work / "out"
    try:
        asset = ReleaseAsset(name="FileCare-Setup-9.9.9.exe",
                             url=server.url("FileCare-Setup-9.9.9.exe"),
                             size=len(payload_bytes))
        info = UpdateInfo(version="9.9.9", tag="v9.9.9", asset=asset)

        progress_calls = []
        path = download_installer(
            info, dest_dir=out_dir,
            progress=lambda done, total: progress_calls.append((done, total)))
        check("安装包下载成功", path.is_file(), path)
        check("下载内容与源文件一致", path.read_bytes() == payload_bytes)
        check("进度回调被多次触发（非一次性读完）", len(progress_calls) > 1,
              "{0} 次".format(len(progress_calls)))
        check("最终进度等于文件大小", progress_calls[-1][0] == len(payload_bytes),
              progress_calls[-1])
        check("总大小被正确识别", progress_calls[-1][1] == len(payload_bytes))
        check("没有残留 .part 文件", not list(out_dir.glob("*.part")))

        # 取消
        cancelled = {"flag": False}

        def should_cancel():
            return cancelled["flag"]

        def cancel_after_first(done, total):
            cancelled["flag"] = True

        try:
            download_installer(info, dest_dir=out_dir, progress=cancel_after_first,
                               should_cancel=should_cancel)
            check("取消下载应抛 UpdateError", False, "没有抛出异常")
        except UpdateError as exc:
            check("取消下载抛 UpdateError", "取消" in str(exc), exc)
        check("取消后清理了 .part", not list(out_dir.glob("*.part")))

        # 带正确 SHA256
        asset.digest = "sha256:" + real_sha
        path = download_installer(info, dest_dir=out_dir)
        check("SHA256 正确时下载通过", path.is_file())

        # 错误 SHA256
        asset.digest = "sha256:" + ("0" * 64)
        try:
            download_installer(info, dest_dir=out_dir)
            check("SHA256 不符应被拒绝", False, "没有抛出异常")
        except UpdateError as exc:
            check("SHA256 不符被拒绝", "校验失败" in str(exc), exc)

        # 大小不符
        asset.digest = ""
        asset.size = len(payload_bytes) + 999
        try:
            download_installer(info, dest_dir=out_dir)
            check("大小不符应被拒绝", False, "没有抛出异常")
        except UpdateError as exc:
            check("大小不符被拒绝", "大小不符" in str(exc), exc)

        # 没有安装包
        try:
            download_installer(UpdateInfo(version="9.9.9", tag="v9.9.9"), dest_dir=out_dir)
            check("无安装包应抛错", False, "没有抛出异常")
        except UpdateError as exc:
            check("无安装包时抛 UpdateError", True, exc)

        # 被网络拦截：返回的是 HTML 页面，但文件名仍是 .exe
        (work / "FileCare-Setup-8.8.8.exe").write_bytes(
            b"<!DOCTYPE html><html><body>Access denied</body></html>")
        blocked = UpdateInfo(version="8.8.8", tag="v8.8.8", asset=ReleaseAsset(
            name="FileCare-Setup-8.8.8.exe",
            url=server.url("FileCare-Setup-8.8.8.exe")))
        try:
            download_installer(blocked, dest_dir=out_dir)
            check("拦截页应被拒绝", False, "没有抛出异常")
        except UpdateError as exc:
            check("拦截页被拒绝（不是有效安装程序）", "不是有效" in str(exc), exc)
        check("拦截后没留下 .part", not list(out_dir.glob("*.part")))

        # 双通道回退：主地址（github.com）不通时自动改走 API 地址
        asset.size = len(payload_bytes)
        asset.digest = ""
        asset.url = "http://127.0.0.1:9/FileCare-Setup-9.9.9.exe"   # 必定连接失败
        asset.api_url = server.url("FileCare-Setup-9.9.9.exe")
        path = download_installer(info, dest_dir=out_dir)
        check("主通道失败时自动回退到备用通道",
              path.is_file() and path.read_bytes() == payload_bytes)

        # 两条通道都失败时给出可展示的错误
        asset.api_url = "http://127.0.0.1:9/also-dead.exe"
        try:
            download_installer(info, dest_dir=out_dir)
            check("两条通道都失败应抛错", False, "没有抛出异常")
        except UpdateError as exc:
            check("两条通道都失败时抛 UpdateError", "连接" in str(exc), exc)

        # 伪造 sha256: 前缀解析
        from updater import _digest_sha256, _safe_name
        check("digest 前缀被剥离", _digest_sha256("sha256:ABC") == "abc")
        check("非 sha256 digest 被忽略", _digest_sha256("md5:abc") == "")
        check("文件名中的路径被剥离", _safe_name("a/b\\c.exe") == "c.exe")
    finally:
        server.close()


# ------------------------------------------------------------ 5. 安装命令
def test_installer_command():
    print("\n=== 5. 安装命令行 ===")
    args = installer_command("C:/tmp/FileCare-Setup-9.9.9.exe", silent=True)
    check("第一个参数是安装包路径", args[0] == "C:/tmp/FileCare-Setup-9.9.9.exe", args)
    for flag in SILENT_INSTALL_FLAGS:
        check("包含静默参数 {0}".format(flag), flag in args)
    check("静默参数齐全", set(SILENT_INSTALL_FLAGS).issubset(set(args)))
    check("非静默模式只传路径",
          installer_command("x.exe", silent=False) == ["x.exe"])

    from updater import launch_installer
    try:
        launch_installer("C:/definitely/not/here.exe")
        check("启动不存在的安装包应报错", False, "没有抛出异常")
    except UpdateError as exc:
        check("启动不存在的安装包抛 UpdateError", True, exc)


# ------------------------------------------------------------ 6. 真实 GitHub
def test_real_github():
    print("\n=== 6. 真实 GitHub 接口（尽力而为）===")
    try:
        info = check_for_update()
        if info is None:
            print("[PASS] 当前仓库无更新版本（尚未发布 Release 属于正常）")
        else:
            print("[PASS] 检测到新版本 {0}，安装包={1}".format(
                info.version, info.asset.name if info.has_installer else "无"))
    except UpdateError as exc:
        print("[SKIP] GitHub 不可达或仓库无 Release：{0}".format(exc))
    except Exception as exc:  # noqa: BLE001
        check("真实 GitHub 检查不应抛出非 UpdateError 异常", False, repr(exc))


if __name__ == "__main__":
    print("FileCare 更新模块核心测试")
    print("当前程序版本：{0}".format(APP_VERSION))
    test_versions()
    test_asset_pick()
    test_parse_release()
    test_download()
    test_installer_command()
    test_real_github()
    print("\n" + ("=" * 50))
    if FAILURES:
        print("失败 {0} 项：".format(len(FAILURES)))
        for name in FAILURES:
            print("  - " + name)
        sys.exit(1)
    print("全部通过")
    sys.exit(0)