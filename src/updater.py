# -*- coding: utf-8 -*-
"""从 GitHub Releases 检查、下载并安装新版本。

只使用标准库（urllib），不引入新的第三方依赖：
一是控制安装包体积，二是保持 Win7 构建环境（Python 3.8）可用。

国内网络的现实情况：github.com 主域经常不可达，而 api.github.com 与
资源 CDN（release-assets.githubusercontent.com）通常可达。因此下载时
同时保留「浏览器下载地址」和「API 资源地址」两条通道，前者失败自动改走后者。

典型用法::

    info = check_for_update()            # None 表示已是最新
    if info and info.has_installer:
        path = download_installer(info, progress=on_progress,
                                  should_cancel=lambda: cancelled)
        launch_installer(path)           # 之后由调用方退出本程序
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from version import (
    APP_VERSION,
    GITHUB_LATEST_API,
    GITHUB_RELEASES_URL,
    INSTALLER_ASSET_PREFIX,
    INSTALLER_ASSET_SUFFIX,
    is_newer,
)

USER_AGENT = "FileCare-Updater/{0}".format(APP_VERSION)
API_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 30
CHUNK_SIZE = 256 * 1024

# /UPDATE 是给安装脚本 [Code] 段识别的自定义标记：
# 静默安装结束后由安装程序自动重新启动文件管家。
SILENT_INSTALL_FLAGS = (
    "/SILENT",
    "/NORESTART",
    "/CLOSEAPPLICATIONS",
    "/UPDATE",
)

# 可执行文件的文件头，用来识别"下载到的其实是拦截页/错误页"的情况。
FILE_SIGNATURES = (
    (".exe", b"MZ"),
    (".msi", b"\xd0\xcf\x11\xe0"),
)


class UpdateError(Exception):
    """可以直接展示给用户的错误（网络、校验、启动失败等）。"""


class _Cancelled(Exception):
    """内部使用：用户主动取消下载（不触发备用地址重试）。"""


class _TransportError(Exception):
    """内部使用：连接层面失败，可以换一条下载通道重试。"""


@dataclass
class ReleaseAsset:
    """Release 中的一个附件。"""

    name: str
    url: str = ""          # browser_download_url，走 github.com
    api_url: str = ""      # API 资源地址，走 api.github.com，国内更稳
    size: int = 0
    digest: str = ""


@dataclass
class UpdateInfo:
    """一次可用更新的完整信息。"""

    version: str
    tag: str
    notes: str = ""
    page_url: str = GITHUB_RELEASES_URL
    published_at: str = ""
    asset: Optional[ReleaseAsset] = None

    @property
    def has_installer(self) -> bool:
        """该版本是否附带了可直接安装的安装包。"""
        if self.asset is None:
            return False
        return bool(self.asset.url or self.asset.api_url)

    @property
    def size_display(self) -> str:
        if self.asset is None:
            return "未知大小"
        return format_size(self.asset.size)


def format_size(num_bytes) -> str:
    """把字节数格式化成 KB / MB 便于展示。"""
    try:
        value = float(num_bytes or 0)
    except (TypeError, ValueError):
        return "未知大小"
    if value <= 0:
        return "未知大小"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return "{0:d} B".format(int(value))
            return "{0:.1f} {1}".format(value, unit)
        value /= 1024
    return "{0:.1f} GB".format(value)


def is_installed_build() -> bool:
    """当前是否为安装包安装后的运行环境（而非源码运行）。

    源码运行时替换不了程序文件，界面应改为引导用户去发布页手动下载。
    """
    return bool(getattr(sys, "frozen", False))


def default_download_dir() -> Path:
    """安装包下载目录，放在临时目录下避免污染用户目录。"""
    base = os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
    return Path(base) / "FileCare-Update"


# ---------------------------------------------------------------- 网络请求

def _http_get(url: str, timeout: int = API_TIMEOUT) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _describe_network_error(exc) -> str:
    """把底层异常翻译成用户看得懂的中文说明。"""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return "仓库还没有发布任何版本，或该版本已被删除。"
        if exc.code in (403, 429):
            return "GitHub 暂时拒绝了访问（多为访问频率限制），请稍后再试。"
        return "GitHub 返回错误：HTTP {0}".format(exc.code)
    if isinstance(exc, urllib.error.URLError):
        return "无法连接 GitHub，请检查网络或代理设置。"
    return "网络请求失败：{0}".format(exc)


# ---------------------------------------------------------------- 检查更新

def check_for_update(current_version: str = APP_VERSION,
                     timeout: int = API_TIMEOUT) -> Optional[UpdateInfo]:
    """查询 GitHub 上最新的正式 Release。

    有新版本返回 UpdateInfo；已是最新返回 None；失败抛 UpdateError。
    预发布（prerelease）和草稿不会被 /releases/latest 返回，因此不会推给用户。
    """
    try:
        raw = _http_get(GITHUB_LATEST_API, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - 统一转成可展示错误
        raise UpdateError(_describe_network_error(exc)) from exc

    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise UpdateError("GitHub 返回的内容无法解析。") from exc
    if not isinstance(payload, dict):
        raise UpdateError("GitHub 返回的内容格式异常。")

    return _parse_release(payload, current_version)


def _parse_release(payload: dict, current_version: str) -> Optional[UpdateInfo]:
    """解析 Release JSON，判断是否需要更新。"""
    tag = str(payload.get("tag_name") or "").strip()
    version = tag.lstrip("vV").strip() or str(payload.get("name") or "").strip()
    if not version:
        return None
    if not is_newer(version, current_version):
        return None

    return UpdateInfo(
        version=version,
        tag=tag or "v{0}".format(version),
        notes=str(payload.get("body") or "").strip(),
        page_url=str(payload.get("html_url") or GITHUB_RELEASES_URL).strip(),
        published_at=str(payload.get("published_at") or "").strip(),
        asset=_pick_installer_asset(payload.get("assets") or [], version),
    )


def _pick_installer_asset(assets, version: str) -> Optional[ReleaseAsset]:
    """从 Release 附件里挑出安装包。

    优先级：FileCare-Setup-<版本>.exe > 其它 FileCare-Setup-*.exe > 任意 .exe > .msi。
    没有可执行的安装包时返回 None（界面会退回到"打开发布页"）。
    """
    candidates = []
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or "").strip()
        api_url = str(item.get("url") or "").strip()
        if not name or not (url or api_url):
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        candidates.append(ReleaseAsset(
            name=name,
            url=url,
            api_url=api_url,
            size=size,
            digest=str(item.get("digest") or "").strip(),
        ))
    if not candidates:
        return None

    prefix = INSTALLER_ASSET_PREFIX.lower()
    suffix = INSTALLER_ASSET_SUFFIX.lower()

    def score(asset: ReleaseAsset):
        lower = asset.name.lower()
        if lower.startswith(prefix) and lower.endswith(suffix):
            rank = 0
        elif lower.endswith(suffix):
            rank = 1
        elif lower.endswith(".msi"):
            rank = 2
        else:
            rank = 99
        version_penalty = 0 if (version and version in asset.name) else 1
        return (rank, version_penalty, lower)

    best = min(candidates, key=score)
    if score(best)[0] >= 99:
        return None
    return best


# ---------------------------------------------------------------- 下载安装包

def _safe_name(name: str) -> str:
    """去掉可能存在的目录分隔符，只保留文件名。"""
    cleaned = str(name or "").replace("\\", "/").split("/")[-1].strip()
    return cleaned or "FileCare-Setup.exe"


def _digest_sha256(digest: str) -> str:
    """解析 GitHub 返回的 digest 字段（形如 'sha256:abc...'）。"""
    text = str(digest or "").strip().lower()
    if text.startswith("sha256:"):
        return text.split(":", 1)[1].strip()
    return ""


def _silent_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def download_candidates(asset: ReleaseAsset) -> List[str]:
    """两条下载通道：先走浏览器地址，失败再走 API 资源地址。"""
    ordered = []
    for candidate in (asset.url, asset.api_url):
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _download_headers(url: str) -> dict:
    headers = {"User-Agent": USER_AGENT}
    # API 资源端点需要显式要求二进制流，否则返回的是 JSON 元数据。
    if "api.github.com" in url and "/releases/assets/" in url:
        headers["Accept"] = "application/octet-stream"
    return headers


def _download_once(url: str, part: Path, asset: ReleaseAsset,
                   progress: Optional[Callable[[int, int], None]],
                   should_cancel: Optional[Callable[[], bool]]) -> Tuple[str, int]:
    """从单个地址下载到 .part 文件，返回 (sha256, 字节数)。"""
    hasher = hashlib.sha256()
    done = 0
    request = urllib.request.Request(url, headers=_download_headers(url))
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            with open(part, "wb") as handle:
                total = asset.size or 0
                try:
                    total = int(response.headers.get("Content-Length") or total)
                except (TypeError, ValueError):
                    pass
                if progress:
                    progress(0, total)
                while True:
                    if should_cancel is not None and should_cancel():
                        raise _Cancelled()
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    except _Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - 连接层失败，交给上层换通道
        raise _TransportError(_describe_network_error(exc)) from exc
    return hasher.hexdigest(), done


def download_installer(info: UpdateInfo,
                       dest_dir=None,
                       progress: Optional[Callable[[int, int], None]] = None,
                       should_cancel: Optional[Callable[[], bool]] = None) -> Path:
    """下载安装包到临时目录并校验完整性，返回本地文件路径。

    progress(done, total)：每收到一块数据回调一次（total 可能为 0 表示未知）。
    should_cancel()：返回 True 时中止下载并抛 UpdateError。
    第一条下载通道连接失败时会自动改用备用通道。
    """
    asset = info.asset if info is not None else None
    if asset is None:
        raise UpdateError("该版本没有附带安装包，请到发布页手动下载。")

    target_dir = Path(dest_dir) if dest_dir else default_download_dir()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise UpdateError("无法创建下载目录：{0}".format(exc)) from exc

    target = target_dir / _safe_name(asset.name)
    part = target.with_name(target.name + ".part")

    candidates = download_candidates(asset)
    if not candidates:
        raise UpdateError("该版本没有可用的下载地址，请到发布页手动下载。")

    last_error = ""
    for url in candidates:
        _silent_unlink(part)
        try:
            sha256_hex, size = _download_once(url, part, asset, progress, should_cancel)
        except _Cancelled:
            _silent_unlink(part)
            raise UpdateError("已取消下载。") from None
        except _TransportError as exc:
            last_error = str(exc)
            continue

        try:
            _verify_download(size, asset, sha256_hex, part)
        except UpdateError:
            _silent_unlink(part)
            raise

        try:
            _silent_unlink(target)
            part.replace(target)
        except OSError as exc:
            _silent_unlink(part)
            raise UpdateError("无法保存安装包：{0}".format(exc)) from exc
        return target

    _silent_unlink(part)
    raise UpdateError(last_error or "下载失败，请检查网络后重试。")


def _verify_download(size: int, asset: ReleaseAsset, sha256_hex: str, path: Path) -> None:
    """校验大小、SHA256 与文件头，避免把半截文件或拦截页交给安装程序。"""
    if size <= 0:
        raise UpdateError("下载到的安装包为空，已中止。")
    if asset.size and size != asset.size:
        raise UpdateError(
            "安装包大小不符（应为 {0}，实际 {1}），已中止。".format(
                format_size(asset.size), format_size(size)))
    expected = _digest_sha256(asset.digest)
    if expected and expected != sha256_hex:
        raise UpdateError("安装包校验失败（SHA256 不匹配），可能未下载完整，已中止。")
    _verify_file_signature(path, asset.name)


def _verify_file_signature(path: Path, name: str) -> None:
    """确认下载到的是真正的可执行文件，而不是被网络拦截后返回的网页。"""
    lower = str(name or "").lower()
    expected = None
    for suffix, signature in FILE_SIGNATURES:
        if lower.endswith(suffix):
            expected = signature
            break
    if expected is None:
        return
    try:
        with open(path, "rb") as handle:
            head = handle.read(len(expected))
    except OSError:
        return
    if head != expected:
        raise UpdateError(
            "下载到的文件不是有效的安装程序（可能被网络拦截页替换），已中止。")


# ---------------------------------------------------------------- 启动安装

def installer_command(path, silent: bool = True):
    """构造安装程序的命令行参数。"""
    args = [str(path)]
    if silent:
        args.extend(SILENT_INSTALL_FLAGS)
    return args


def launch_installer(path, silent: bool = True) -> None:
    """以独立进程启动安装包，使其在本程序退出后继续运行。

    静默参数由安装脚本配合：安装完成后安装程序会自动重新启动文件管家。
    """
    target = Path(path)
    if not target.is_file():
        raise UpdateError("安装包不存在：{0}".format(target))

    creationflags = 0
    if os.name == "nt":
        creationflags = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
    try:
        subprocess.Popen(installer_command(target, silent=silent),
                         close_fds=True, creationflags=creationflags)
    except OSError as exc:
        raise UpdateError("无法启动安装程序：{0}".format(exc)) from exc