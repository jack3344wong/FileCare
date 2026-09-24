# -*- coding: utf-8 -*-
"""当前正式功能的安全回归测试。"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))

# main 必须先导入，确保 Qt 插件路径在 QApplication 之前设置。
import main  # noqa: E402,F401
from PyQt5.QtWidgets import QApplication  # noqa: E402
from disk_scanner import DiskScannerThread  # noqa: E402
from file_association import FileAssociation  # noqa: E402
from main_window import DiskMonitor  # noqa: E402


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_onedrive_temp_identity(self):
        with tempfile.TemporaryDirectory(prefix="OneDriveTemp_", dir=str(PROJECT_DIR)) as tmp:
            folder = Path(tmp) / "0123456789abcdef-Personal"
            folder.mkdir()
            info = FileAssociation(str(folder)).get_detailed_identity()
            self.assertIn("OneDrive", info.sync_software)
            self.assertGreaterEqual(info.confidence, 0.9)

    def test_recursive_scanner(self):
        with tempfile.TemporaryDirectory(prefix="scanner_test_", dir=str(PROJECT_DIR)) as tmp:
            root = Path(tmp)
            (root / "a" / "b").mkdir(parents=True)
            (root / "a" / "b" / "large.bin").write_bytes(b"x" * 4096)
            old_log = root / "old.log"
            old_log.write_bytes(b"y" * 2048)
            old = time.time() - 100 * 86400
            os.utime(old_log, (old, old))
            scanner = DiskScannerThread(
                str(root), threshold_mb=0.001,
                folder_threshold_mb=0.001, top_n=20)
            received = []
            scanner.finished_signal.connect(received.append)
            scanner.start()
            while scanner.isRunning():
                self.app.processEvents()
                time.sleep(0.01)
            self.app.processEvents()
            result = received[0]
            self.assertEqual(result["total_size"], 6144)
            root_result = next(x for x in result["large_folders"] if os.path.normcase(x["path"]) == os.path.normcase(str(root)))
            self.assertEqual(root_result["file_count"], 2)
            self.assertEqual(root_result["folder_count"], 2)
            self.assertTrue(any(x["name"] == "old.log" for x in result["suggestions"]))

    def test_main_window_contract(self):
        window = DiskMonitor()
        window.show()
        self.app.processEvents()
        self.assertEqual(window.tree.columnCount(), 2)
        self.assertTrue(all(hasattr(window, name) for name in
                            ("_navigate_to", "_go_up", "_go_root", "_go_back_history", "_drive_combo")))
        self.assertGreaterEqual(window.minimumWidth(), 1100)
        self.assertGreaterEqual(window.minimumHeight(), 700)
        window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
