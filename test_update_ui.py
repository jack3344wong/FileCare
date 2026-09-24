# -*- coding: utf-8 -*-
"""「检查更新」界面集成测试。

覆盖：设置页软件更新分组、保存/加载、按钮触发检查、发现新版本对话框
的两种形态（有/无安装包）、托盘菜单项接线。
不联网：检查动作被打桩，下载线程不会启动。

用 WA_DontShowOnScreen + grab() 渲染，而不是 QT_QPA_PLATFORM=offscreen，
因为离屏平台不渲染文字，无法据截图判断界面是否正确。
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton

import settings_page as sp
from settings import Settings
from tray_manager import TrayManager
from update_dialog import UpdateAvailableDialog
from updater import ReleaseAsset, UpdateInfo
from version import APP_VERSION

# 测试不得触碰真实系统：
# 1) _on_save 会比对并改写「开机自启动」注册表项，这里替换成空实现；
# 2) _on_save / _on_check_update_now 成功时会弹阻塞式消息框，这里静默掉。
import auto_start

auto_start.is_auto_start_enabled = lambda: False
auto_start.set_auto_start = lambda flag: (True, "")
sp.QMessageBox.information = staticmethod(lambda *a, **k: None)
sp.QMessageBox.warning = staticmethod(lambda *a, **k: None)

app = QApplication.instance() or QApplication(sys.argv)

# 渲染结果要贴近真实程序：没有全局样式表时，「立即更新」的 #primary
# 蓝底主按钮样式不会生效，会误判成"主按钮没做视觉区分"。
try:
    import main_window

    app.setStyleSheet(main_window.STYLESHEET_DEFAULT)
    print("已应用程序全局样式表，渲染结果贴近真实界面")
except Exception as exc:                                   # pragma: no cover
    print("警告：未能加载全局样式表，按钮配色可能看不出真实效果:", exc)

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print("  {0} {1}{2}".format("通过" if cond else "失败", name,
                                "  [" + str(extra) + "]" if extra else ""))


def render(widget, path):
    """不显示窗口但正常渲染（含文字），用于目视核对。"""
    widget.setAttribute(Qt.WA_DontShowOnScreen, True)
    widget.resize(widget.sizeHint().width(), widget.sizeHint().height())
    widget.show()
    app.processEvents()
    widget.grab().save(str(path))
    widget.hide()
    return path


tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="filecare_ui_test_"))
cfg = tmpdir / "config.json"

print("=" * 72)
print("设置页 - 软件更新分组")
print("=" * 72)
s = Settings(str(cfg))
page = sp.SettingsPage(s)

check("显示当前版本 v{0}".format(APP_VERSION),
      page._current_version_label.text() == "v{0}".format(APP_VERSION),
      page._current_version_label.text())
check("检查更新下拉框有三个选项",
      page._check_update_combo.count() == 3,
      [page._check_update_combo.itemData(i) for i in range(3)])
check("存在「立即检查更新」按钮", hasattr(page, "_check_now_btn")
      and isinstance(page._check_now_btn, QPushButton))
check("按钮文案正确", page._check_now_btn.text() == "立即检查更新",
      page._check_now_btn.text())
check("说明文字提示更新源为 GitHub 发布页",
      "GitHub" in page._update_hint_label.text())
check("已移除虚构的更新服务器输入框", not hasattr(page, "_update_server_edit"))

# 按钮点击应触发检查，并且检查期间禁用按钮
calls = []
sp.check_and_prompt = lambda parent, **kw: calls.append((parent, kw))
page._on_check_update_now()
check("点击按钮会调用检查流程", len(calls) == 1,
      "调用 {0} 次".format(len(calls)))
if calls:
    kw = calls[0][1]
    check("检查时把按钮置为忙碌（禁用）",
          kw.get("busy_widgets") == (page._check_now_btn,), kw.get("busy_widgets"))
    check("手动检查时信息提示更充分",
          kw.get("notify_when_latest") is True and kw.get("show_errors") is True)

print()
print("=" * 72)
print("设置页 - 保存与加载")
print("=" * 72)
idx = page._check_update_combo.findData("manual")
page._check_update_combo.setCurrentIndex(idx)
page._on_save()
saved = json.loads(cfg.read_text(encoding="utf-8"))
check("保存了检查更新设置", saved.get("advanced", {}).get("check_update") == "manual",
      saved.get("advanced", {}).get("check_update"))
check("不再写入已废弃的 update_server 配置项",
      "update_server" not in saved.get("advanced", {}))

s2 = Settings(str(cfg))
page2 = sp.SettingsPage(s2)
check("重新加载后下拉框恢复为「手动检查」",
      page2._check_update_combo.currentData() == "manual",
      page2._check_update_combo.currentData())

print()
print("=" * 72)
print("发现新版本对话框")
print("=" * 72)
info = UpdateInfo(
    version="1.4.0", tag="v1.4.0",
    notes="- 新增某某功能\n- 修复某某问题",
    page_url="https://github.com/jack3344wong/FileCare/releases",
    published_at="2026-09-24T10:00:00Z",
    asset=ReleaseAsset(name="FileCare-Setup-1.4.0.exe",
                       url="https://example.com/x.exe", size=38 * 1024 * 1024,
                       digest="sha256:abc"))
dlg = UpdateAvailableDialog(info)
labels = [l.text() for l in dlg.findChildren(QLabel)]
buttons = [b.text() for b in dlg.findChildren(QPushButton)]

check("显示当前版本", any(APP_VERSION in t for t in labels), labels[:4])
check("显示最新版本 1.4.0", any("1.4.0" in t for t in labels))
check("显示更新说明标题", any("更新说明" in t for t in labels))
check("有安装包时显示安装包大小（{0}）".format(info.size_display),
      any(info.size_display in t for t in labels), labels)
check("按钮包含立即更新/打开发布页/稍后再说",
      {"立即更新", "打开发布页", "稍后再说"}.issubset(set(buttons)), buttons)

for btn in dlg.findChildren(QPushButton):
    if btn.text() == "立即更新":
        btn.click()
check("点击「立即更新」返回 RUN_UPDATE",
      dlg.result() == UpdateAvailableDialog.RUN_UPDATE, dlg.result())
render(dlg, tmpdir / "update_dialog.png")

no_asset = UpdateInfo(version="1.4.1", tag="v1.4.1", notes="", page_url="https://x")
dlg2 = UpdateAvailableDialog(no_asset)
buttons2 = [b.text() for b in dlg2.findChildren(QPushButton)]
labels2 = [l.text() for l in dlg2.findChildren(QLabel)]
check("没有安装包时不提供「立即更新」",
      "立即更新" not in buttons2, buttons2)
check("没有安装包时提示到发布页手动下载",
      any("没有附带安装包" in t for t in labels2), labels2)
render(dlg2, tmpdir / "update_dialog_noasset.png")

print()
print("=" * 72)
print("托盘菜单接线")
print("=" * 72)
tray = TrayManager()
icon = pathlib.Path(__file__).resolve().parent / "assets" / "filecare.ico"
try:
    tray.setup(str(icon), "文件管家")
except Exception as exc:
    print("  跳过（托盘不可用）:", exc)
else:
    if tray.tray_menu is None:
        print("  跳过（本机系统托盘不可用）")
    else:
        acts = {a.text(): a for a in tray.tray_menu.actions()}
        check("托盘菜单含「检查更新」", "检查更新" in acts, list(acts))
        if "检查更新" in acts:
            check("「检查更新」菜单项已启用", acts["检查更新"].isEnabled())
            seen = []
            tray.update_requested.connect(lambda: seen.append(1))
            acts["检查更新"].trigger()
            check("点击菜单项会发出 update_requested 信号", len(seen) == 1)

def _is_descendant(widget, ancestor):
    """widget 是否位于 ancestor 之内（render() 会 hide 控件，不能用 isVisible）。"""
    w = widget
    while w is not None:
        if w is ancestor:
            return True
        w = w.parentWidget()
    return False


# 设置页截图：软件更新分组在「高级设置」页（索引 3），需要先切过去
page._nav_list.setCurrentRow(3)
app.processEvents()
check("切到高级设置后软件更新分组位于当前页",
      page._content_stack.currentIndex() == 3
      and _is_descendant(page._update_group, page._content_stack.currentWidget()),
      page._content_stack.currentIndex())
render(page, tmpdir / "settings_page_advanced.png")
page._update_group.setAttribute(Qt.WA_DontShowOnScreen, True)
page._update_group.show()
app.processEvents()
page._update_group.grab().save(str(tmpdir / "settings_update_group.png"))
page._update_group.hide()

print()
print("=" * 72)
print("check_and_prompt 回调接线")
print("（回归：回调名写错会抛 NameError，PyQt5 遇槽内异常直接终止进程，")
print("  表现为打开软件后不久闪退）")
print("=" * 72)
import update_dialog as ud


class _FakeCheckWorker(QObject):
    """替身：信号与真身同名，但不真正起线程，便于手动触发回调。"""

    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, current_version=None, parent=None):
        super().__init__(parent)
        self.started = False

    def start(self):
        self.started = True


real_worker_cls = ud.UpdateCheckWorker
ud.UpdateCheckWorker = _FakeCheckWorker

msgs = []


def _record(kind):
    def _fn(*args, **kwargs):
        msgs.append((kind, args[2] if len(args) > 2 else ""))
    return staticmethod(_fn)


ud.QMessageBox.information = _record("info")
ud.QMessageBox.warning = _record("warn")

try:
    busy_btn = QPushButton("立即检查更新")
    busy_btn.setEnabled(True)
    worker = ud.check_and_prompt(page, notify_when_latest=False,
                                 show_errors=False, busy_widgets=(busy_btn,))
    check("check_and_prompt 正常返回后台线程（不抛 NameError）",
          isinstance(worker, _FakeCheckWorker))
    check("检查期间禁用忙碌控件", busy_btn.isEnabled() is False)
    check("后台线程已启动", getattr(worker, "started", False) is True)
    check("调用方持有线程引用，避免被回收",
          getattr(page, "_filecare_update_worker", None) is worker)

    msgs.clear()
    worker.finished_ok.emit(None)
    check("自动检查「已是最新」时保持安静", msgs == [], msgs)
    check("回调结束后恢复忙碌控件", busy_btn.isEnabled() is True)

    manual = ud.check_and_prompt(page, notify_when_latest=True, show_errors=True)
    msgs.clear()
    manual.finished_ok.emit(None)
    check("手动检查「已是最新」时给出提示",
          any("已是最新" in text for _, text in msgs), msgs)

    silent_fail = ud.check_and_prompt(page, show_errors=False)
    msgs.clear()
    silent_fail.failed.emit("网络不可达")
    check("自动检查网络失败时不弹窗", msgs == [], msgs)

    loud_fail = ud.check_and_prompt(page, show_errors=True)
    msgs.clear()
    loud_fail.failed.emit("网络不可达")
    check("手动检查网络失败时给出原因",
          any("网络不可达" in text for _, text in msgs), msgs)
finally:
    ud.UpdateCheckWorker = real_worker_cls


print()
print("=" * 72)
failed = [n for n, ok in results if not ok]
print("合计 {0} 项，通过 {1} 项，失败 {2} 项".format(
    len(results), len(results) - len(failed), len(failed)))
for n in failed:
    print("  失败:", n)
print("截图目录:", tmpdir)
print("=" * 72)
sys.exit(1 if failed else 0)