# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PyQt5 import QtCore

from disk_scanner import DiskScannerThread
from main_window import DiskMonitor
from settings import Settings


class _SettingsStub:
    def __init__(self, interval):
        self.interval = interval

    def get(self, section, key, default=None):
        if (section, key) == ("scan", "auto_scan_interval"):
            return self.interval
        return default


class _TimerHarness(QtCore.QObject):
    _setup_auto_scan_timer = DiskMonitor._setup_auto_scan_timer

    def __init__(self, interval):
        super().__init__()
        self._settings = _SettingsStub(interval)
        self._auto_scan_timer = None

    def _on_auto_scan_timer_tick(self):
        pass


class V120RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    def test_wildcard_and_excluded_subdirectory(self):
        with tempfile.TemporaryDirectory(dir=str(PROJECT_DIR)) as tmp:
            root = Path(tmp)
            excluded = root / "excluded"
            excluded.mkdir()
            (root / "keep.txt").write_text("keep", encoding="utf-8")
            (root / "skip.tmp").write_text("skip", encoding="utf-8")
            (excluded / "hidden.txt").write_text("hidden", encoding="utf-8")
            scanner = DiskScannerThread(
                str(root), threshold_mb=0, folder_threshold_mb=0,
                exclude_dirs=[str(excluded) + os.sep],
                exclude_patterns=["*.tmp"], top_n=20)
            received = []
            scanner.finished_signal.connect(received.append)
            scanner.start()
            while scanner.isRunning():
                self.app.processEvents()
                time.sleep(0.01)
            self.app.processEvents()
            result = received[0]
            self.assertEqual(result["total_files"], 1)
            self.assertEqual([item["name"] for item in result["large_files"]],
                             ["keep.txt"])

    def test_invalid_config_falls_back_and_invalid_import_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=str(PROJECT_DIR)) as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text("[]", encoding="utf-8")
            settings = Settings(str(config_path))
            self.assertEqual(settings.get("scan", "exclude_dirs"), [])

            invalid_import = Path(tmp) / "invalid.json"
            invalid_import.write_text(
                json.dumps({"scan": {"exclude_dirs": "not-a-list"}}),
                encoding="utf-8")
            self.assertFalse(settings.import_config(str(invalid_import)))
            self.assertEqual(settings.get("scan", "exclude_dirs"), [])

    def test_monthly_timer_uses_safe_daily_tick(self):
        harness = _TimerHarness("monthly")
        harness._setup_auto_scan_timer()
        self.assertEqual(harness._auto_scan_target_days, 30)
        self.assertEqual(harness._auto_scan_timer.interval(), 24 * 60 * 60 * 1000)
        harness._auto_scan_timer.stop()


if __name__ == "__main__":
    unittest.main()
