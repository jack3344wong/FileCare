# -*- coding: utf-8 -*-
"""开机自启动管理模块"""
import sys
import winreg
from pathlib import Path


REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "FileCare"


def get_executable_path():
    """获取当前可执行文件路径"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的 exe
        return sys.executable
    else:
        # 开发环境，使用 Python 运行 main.py
        main_path = Path(__file__).parent / "main.py"
        return f'"{sys.executable}" "{main_path}"'


def is_auto_start_enabled():
    """检查是否已启用开机自启动"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except Exception:
        return False


def enable_auto_start():
    """启用开机自启动"""
    try:
        exe_path = get_executable_path()
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
        winreg.CloseKey(key)
        return True, "已启用开机自启动"
    except Exception as e:
        return False, f"启用失败: {str(e)}"


def disable_auto_start():
    """禁用开机自启动"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, APP_NAME)
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
        return True, "已禁用开机自启动"
    except Exception as e:
        return False, f"禁用失败: {str(e)}"


def set_auto_start(enabled):
    """设置开机自启动状态"""
    if enabled:
        return enable_auto_start()
    else:
        return disable_auto_start()
