# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import struct
import sys
from importlib.metadata import PackageNotFoundError, version

if sys.version_info[:2] != (3, 8) or struct.calcsize("P") != 8:
    raise SystemExit(
        "Win7 release must be built with 64-bit Python 3.8.x; "
        "install requirements-win7.txt in that environment."
    )

win7_native_versions = {
    "PyQt5": "5.15.10",
    "PyQt5-Qt5": "5.15.2",
    "psutil": "5.9.8",
    "Pillow": "9.5.0",
    "lxml": "4.9.3",
    "pyinstaller": "5.13.2",
}
try:
    incompatible = [
        f"{name}=={version(name)} (need {required})"
        for name, required in win7_native_versions.items()
        if version(name) != required
    ]
except PackageNotFoundError as exc:
    raise SystemExit(f"Missing Win7 build dependency: {exc}")
if incompatible:
    raise SystemExit("Wrong Win7 native dependency versions: " + ", ".join(incompatible))

# PyInstaller sets SPECPATH to the directory containing this spec file.
project = Path(SPECPATH).resolve().parent
code = project / "src"

# 安装动画由 Inno Setup 临时使用，不随应用重复安装。
datas = [
    (str(project / "assets" / name), "assets")
    for name in (
        "filecare.ico", "filecare-256.png", "filecare-logo.png",
        "arrow_up.png", "arrow_down.png",
    )
]
binaries = []
hiddenimports = [
    "main_window", "file_association", "file_operations",
    "web_search", "recycle_bin", "recycle_bin_ui", "disk_scanner",
    "quick_search", "fulltext_search", "content_extractor",
    "ui_event_handlers", "file_classifier", "duplicate_detector",
    "large_file_analyzer", "smart_cleaner", "cleanup",
    # 应用内「检查更新」相关模块
    "version", "updater", "update_dialog",
    "PyQt5.QtCore", "PyQt5.QtGui", "PyQt5.QtWidgets",
    "PyQt5.sip",
    "psutil",
    "pypdf", "docx", "openpyxl", "pptx", "striprtf.striprtf",
    "lxml", "PIL",
]

a = Analysis(
    [str(code / "main.py")],
    pathex=[str(code)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FileCare", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=False,
    icon=str(project / "assets" / "filecare.ico"),
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[], name="FileCare",
)
