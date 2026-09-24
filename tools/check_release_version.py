# -*- coding: utf-8 -*-
"""校验版本号在各处是否一致。

不一致会导致很实际的故障：安装包文件名与实际版本对不上时，
应用内「检查更新」会永远认为自己是旧版本，反复提示更新。

比对三处：
  src/version.py          的 APP_VERSION     —— 程序内检查更新的当前版本
  packaging/FileCare.iss  的 MyAppVersion    —— 安装包文件名与注册表版本
  Git tag（可选）                             —— GitHub Release 标签 vX.Y.Z

用法：
    python tools/check_release_version.py            # 只比对仓库内两处
    python tools/check_release_version.py v1.3.0     # 额外比对标签

未传标签时自动读取环境变量 GITHUB_REF_NAME（GitHub Actions 会设置）。
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def read_app_version():
    path = ROOT / "src" / "version.py"
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"',
                      path.read_text(encoding="utf-8"), re.M)
    if not match:
        sys.exit("错误：src/version.py 里找不到 APP_VERSION")
    return match.group(1)


def read_iss_version():
    path = ROOT / "packaging" / "FileCare.iss"
    match = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"',
                      path.read_text(encoding="utf-8-sig"))
    if not match:
        sys.exit("错误：packaging/FileCare.iss 里找不到 MyAppVersion")
    return match.group(1)


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_REF_NAME", "")
    tag = tag.strip()
    # 只在看起来像发布标签（v + 数字）时才比对；分支名（如 master）直接忽略，
    # 否则手动触发构建时会因为分支名不是标签而误报失败。
    if tag and not re.match(r"^v\d", tag, re.I):
        print("提示：{0} 看起来不是发布标签，跳过标签比对".format(tag))
        tag = ""

    app = read_app_version()
    iss = read_iss_version()
    tag_version = tag.lstrip("vV") if tag else ""

    print("src/version.py        APP_VERSION   = {0}".format(app))
    print("packaging/FileCare.iss MyAppVersion = {0}".format(iss))
    print("Release 标签                          = {0}".format(tag or "（未提供，跳过比对）"))

    problems = []
    if app != iss:
        problems.append(
            "APP_VERSION({0}) 与 MyAppVersion({1}) 不一致："
            "安装包文件名会和程序自报版本对不上".format(app, iss))
    if tag:
        if not tag.lower().startswith("v"):
            problems.append("发布标签应以 v 开头（例如 v{0}），当前为 {1}".format(app, tag))
        if tag_version != app:
            problems.append(
                "标签 {0} 与 APP_VERSION({1}) 不一致："
                "应用内检查更新会误判版本".format(tag, app))

    if problems:
        print()
        for p in problems:
            print("版本校验失败：" + p)
        sys.exit(1)

    print()
    print("版本号一致：{0}".format(app))
    return 0


if __name__ == "__main__":
    sys.exit(main())