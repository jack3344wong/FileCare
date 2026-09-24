# -*- coding: utf-8 -*-
"""版本号与 GitHub 发布信息的单一来源。

程序内置版本、安装包版本、更新检查比较基准都从这里取值，
避免出现"程序自报版本"与"安装包版本"不一致的情况。

发布新版本时只需要改这里的 APP_VERSION，并同步 packaging/FileCare.iss
里的 MyAppVersion（Release 标签用 v 加同一个版本号，例如 v1.3.0）。
"""
from __future__ import annotations

import re
from typing import Tuple

APP_VERSION = "1.3.0"
APP_NAME_ZH = "文件管家"
APP_NAME_EN = "FileCare"

GITHUB_OWNER = "jack3344wong"
GITHUB_REPO = "FileCare"
GITHUB_RELEASES_URL = "https://github.com/{0}/{1}/releases".format(
    GITHUB_OWNER, GITHUB_REPO)
GITHUB_LATEST_API = "https://api.github.com/repos/{0}/{1}/releases/latest".format(
    GITHUB_OWNER, GITHUB_REPO)

# 安装包在 Release 中的命名，例如 FileCare-Setup-1.3.0.exe
INSTALLER_ASSET_PREFIX = "FileCare-Setup-"
INSTALLER_ASSET_SUFFIX = ".exe"


def parse_version(text) -> Tuple[int, ...]:
    """把 'v1.3.0' / '1.3.0-rc1' 这类版本号解析成可比较的数字元组。

    只取前导数字段；带预发布后缀（-beta 等）的版本按"低于同号正式版"处理，
    这样 1.3.0-beta 不会被当成比 1.3.0 更新。解析不出来时返回空元组。
    """
    if text is None:
        return ()
    raw = str(text).strip().lstrip("vV")
    if not raw:
        return ()
    matched = re.match(r"(\d+(?:\.\d+)*)", raw)
    if not matched:
        return ()
    parts = tuple(int(piece) for piece in matched.group(1).split("."))
    if re.search(r"[-+]", raw):
        parts = parts + (-1,)
    return parts


def is_newer(remote, local) -> bool:
    """remote 是否比 local 新。任一方解析失败时返回 False（绝不误报更新）。"""
    remote_parts = parse_version(remote)
    local_parts = parse_version(local)
    if not remote_parts or not local_parts:
        return False
    width = max(len(remote_parts), len(local_parts))
    remote_parts = remote_parts + (0,) * (width - len(remote_parts))
    local_parts = local_parts + (0,) * (width - len(local_parts))
    return remote_parts > local_parts


def version_display() -> str:
    """界面上展示用的版本字符串。"""
    return "{0} v{1}".format(APP_NAME_ZH, APP_VERSION)


def releases_page() -> str:
    """发布页地址（手动下载回退用）。"""
    return GITHUB_RELEASES_URL