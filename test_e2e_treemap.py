# -*- coding: utf-8 -*-
"""端到端验证：扫描器生成 folder_tree（含文件叶子）→ treemap 布局不丢块。"""
import os, sys, tempfile, time
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QRectF

sys.path.insert(0, str(Path(__file__).parent / "src"))
from disk_scanner import DiskScannerThread  # noqa: E402
from treemap_widget import _squarify  # noqa: E402

app = QApplication.instance() or QApplication([])

with tempfile.TemporaryDirectory(prefix="e2e_", dir=".") as tmp:
    root = Path(tmp)
    # 造一个根目录大文件（类似 pagefile.sys）
    (root / "pagefile.sys").write_bytes(b"\0" * (60 * 1024 * 1024))
    # 造多层文件夹
    (root / "Windows" / "System32").mkdir(parents=True)
    (root / "Windows" / "System32" / "big.dll").write_bytes(b"\0" * (40 * 1024 * 1024))
    (root / "Users" / "data").mkdir(parents=True)
    for i in range(5):
        (root / "Users" / "data" / f"f{i}.txt").write_bytes(b"x" * (2 * 1024 * 1024))
    (root / "Program Files").mkdir()
    (root / "Program Files" / "app.bin").write_bytes(b"\0" * (30 * 1024 * 1024))

    scanner = DiskScannerThread(str(root), threshold_mb=1, top_n=100)
    received = []
    scanner.finished_signal.connect(received.append)
    scanner.start()
    while scanner.isRunning():
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    result = received[0]

    tree = result.get("folder_tree", {})
    names = [c["name"] for c in tree.get("children", [])]
    print("根节点子项:", names)
    file_leaves = [c["name"] for c in tree.get("children", []) if c.get("is_file")]
    print("文件叶子节点:", file_leaves if file_leaves else "无")
    assert "pagefile.sys" in file_leaves, "pagefile.sys 应作为文件叶子显示"

    # 用真实树数据跑布局
    def collect(node):
        items = []
        for c in node.get("children", []):
            items.append({"node": c, "size": max(int(c.get("size", 0)), 1)})
        return items
    items = collect(tree)
    res = _squarify(items, QRectF(0, 0, 1200, 600))
    covered = sum(r["rect"].width() * r["rect"].height() for r in res)
    print(f"\n布局：输入 {len(items)} 项，输出 {len(res)} 块，覆盖率 {covered/(1200*600)*100:.1f}%")
    assert len(res) == len(items), f"丢块！{len(res)} != {len(items)}"
    oob = [r["node"]["name"] for r in res
           if r["rect"].right() > 1200.5 or r["rect"].bottom() > 600.5]
    assert not oob, f"越界: {oob}"
    print("OK 端到端验证通过：文件叶子已显示 + 布局无丢块无越界")
