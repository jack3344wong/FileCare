# -*- coding: utf-8 -*-
"""从 CHANGES.md 抽出指定版本的更新说明，用作 GitHub Release 的正文。

这样发布页上的说明与仓库里的改进记录保持一致，
用户点开 Release 看到的就是这个版本真正改了什么。

用法：
    python tools/extract_changelog.py 1.3.0
    python tools/extract_changelog.py v1.3.0 > body.md

找不到该版本时退出码为 0 并输出提示，方便构建脚本回退到自动生成的说明。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANGES = ROOT / "CHANGES.md"


def extract(version):
    text = CHANGES.read_text(encoding="utf-8")
    ver = version.strip().lstrip("vV")
    # 标题形如：## v1.3.0（2026-09-24） 或 ## v1.3.0 (2026-09-24)
    pattern = re.compile(
        r"^##\s+v?" + re.escape(ver) + r"\b[^\n]*\n(.*?)(?=^##\s|\Z)",
        re.M | re.S)
    match = pattern.search(text)
    if not match:
        return ""
    body = match.group(1)
    # 去掉结尾的分隔线
    body = re.sub(r"\n-{3,}\s*$", "", body.rstrip())
    return body.strip()


def main():
    if len(sys.argv) < 2:
        sys.exit("用法：python tools/extract_changelog.py <版本号>")
    version = sys.argv[1]
    body = extract(version)
    if not body:
        print("（CHANGES.md 中没有 {0} 的条目）".format(version))
        return 0
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())