# -*- coding: utf-8 -*-
"""开机自启动管理模块

通过 Windows 注册表 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run 实现。
使用当前用户权限（HKCU），不需要管理员权限，不弹 UAC。
"""
import sys
import winreg
from pathlib import Path


REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "FileCare"


def get_executable_path():
    """获取当前可执行文件路径（含 --minimized 参数）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的 exe
        return f'"{sys.executable}" --minimized'
    else:
        # 开发环境，使用 Python 运行 main.py
        main_path = Path(__file__).parent / "main.py"
        return f'"{sys.executable}" "{main_path}" --minimized'


def is_auto_start_enabled():
    """检查是否已启用开机自启动"""
    key = None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False
    finally:
        if key is not None:
            winreg.CloseKey(key)


def enable_auto_start():
    """启用开机自启动"""
    key = None
    try:
        exe_path = get_executable_path()
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
        return True, "已启用开机自启动"
    except Exception as e:
        return False, f"启用失败: {str(e)}"
    finally:
        if key is not None:
            winreg.CloseKey(key)


def disable_auto_start():
    """禁用开机自启动"""
    key = None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, APP_NAME)
        except FileNotFoundError:
            pass
        return True, "已禁用开机自启动"
    except Exception as e:
        return False, f"禁用失败: {str(e)}"
    finally:
        if key is not None:
            winreg.CloseKey(key)


def set_auto_start(enabled):
    """设置开机自启动状态"""
    if enabled:
        return enable_auto_start()
    else:
        return disable_auto_start()


def cleanup_auto_start():
    """清理注册表项（卸载时调用）"""
    return disable_auto_start()
