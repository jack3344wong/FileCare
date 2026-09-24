# -*- coding: utf-8 -*-
"""配置管理模块 - 读写 JSON 配置文件"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Optional


# 默认配置
DEFAULT_CONFIG = {
    # 常规设置
    "general": {
        "auto_start": False,              # 开机自启动
        "start_minimized": False,         # 启动时最小化到托盘
        "close_to_tray": True,            # 关闭窗口时最小化到托盘（False=直接退出）
        "auto_scan_on_start": False,      # 启动时自动扫描索引
        "language": "zh",                 # 语言（预留）
    },
    # 扫描与索引设置
    "scan": {
        "index_db_path": "",              # 索引数据库路径（空=默认 ~/.diskwise/）
        "auto_scan_interval": "off",      # 自动扫描间隔：off/daily/weekly/monthly
        "exclude_dirs": [],               # 排除的目录列表
        "exclude_patterns": ["*.tmp", "*.log", "*.bak"],  # 排除的文件类型
    },
    # 界面设置
    "ui": {
        "theme": "light",                 # 主题：light/dark/system
        "font_size": "medium",            # 字体大小：small/medium/large
        "treemap_colors": "default",      # Treemap 配色方案
    },
    # 清理设置
    "cleanup": {
        "confirm_before_delete": True,    # 删除前确认
        "use_system_recycle": True,       # 使用系统回收站
        "large_file_threshold_mb": 100,   # 大文件阈值 (MB)
        "large_folder_threshold_mb": 1024, # 大文件夹阈值 (MB)
    },
    # 高级设置
    "advanced": {
        "check_update": "auto",           # 检查更新：auto/manual/off
        # 更新源固定为 GitHub 官方发布页（见 src/version.py 的 GITHUB_* 常量），
        # 不再提供可配置的更新服务器地址。
        "log_level": "info",              # 日志级别：error/warning/info/debug
    },
    # 窗口状态（内部使用）
    "_window": {
        "geometry": None,                 # 窗口位置和大小
        "maximized": False,               # 是否最大化
    },
}


class Settings:
    """配置管理器"""
    
    def __init__(self, config_path: Optional[str] = None):
        """初始化配置管理器
        
        Args:
            config_path: 配置文件路径，默认 ~/.diskwise/config.json
        """
        if config_path:
            self._config_path = Path(config_path)
        else:
            # 默认路径：~/.diskwise/config.json
            config_dir = Path.home() / ".diskwise"
            config_dir.mkdir(parents=True, exist_ok=True)
            self._config_path = config_dir / "config.json"
        
        self._config: Dict[str, Any] = {}
        self._load()
    
    def _load(self):
        """加载配置文件"""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # 合并默认配置（保留新增的默认项）
                    self._config = self._merge_with_defaults(loaded)
            except (json.JSONDecodeError, IOError, TypeError, ValueError) as e:
                print(f"加载配置文件失败: {e}，使用默认配置")
                self._config = copy.deepcopy(DEFAULT_CONFIG)
        else:
            # 首次运行，使用默认配置
            self._config = copy.deepcopy(DEFAULT_CONFIG)
            self._save()
    
    def _merge_with_defaults(self, loaded: Dict) -> Dict:
        """将加载的配置与默认配置合并，保留新增的默认项"""
        if not isinstance(loaded, dict):
            raise ValueError("配置文件根节点必须是 JSON 对象")
        result = copy.deepcopy(DEFAULT_CONFIG)
        for section, values in loaded.items():
            if section in result and isinstance(result[section], dict):
                if not isinstance(values, dict):
                    raise ValueError(f"配置节 {section!r} 必须是 JSON 对象")
                for key, value in values.items():
                    if key in result[section]:
                        default = result[section][key]
                        if not self._is_compatible_value(default, value):
                            raise ValueError(
                                f"配置项 {section}.{key} 类型不正确")
                # 合并子项
                result[section] = {**result[section], **values}
            else:
                result[section] = values
        return result

    @staticmethod
    def _is_compatible_value(default: Any, value: Any) -> bool:
        """检查导入值是否与默认配置的基本类型兼容。"""
        if default is None:
            return True
        if isinstance(default, bool):
            return isinstance(value, bool)
        if isinstance(default, int):
            return isinstance(value, int) and not isinstance(value, bool)
        if isinstance(default, list):
            return (isinstance(value, list) and
                    all(isinstance(item, str) for item in value))
        return isinstance(value, type(default))
    
    def _save(self):
        """保存配置到文件"""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"保存配置文件失败: {e}")
    
    def get(self, section: str, key: str, default: Any = None) -> Any:
        """获取配置项
        
        Args:
            section: 配置节（如 "general", "scan"）
            key: 配置键
            default: 默认值
            
        Returns:
            配置值
        """
        return self._config.get(section, {}).get(key, default)
    
    def set(self, section: str, key: str, value: Any):
        """设置配置项
        
        Args:
            section: 配置节
            key: 配置键
            value: 配置值
        """
        if section not in self._config:
            self._config[section] = {}
        self._config[section][key] = value
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """获取整个配置节
        
        Args:
            section: 配置节名称
            
        Returns:
            该节的所有配置项
        """
        return copy.deepcopy(self._config.get(section, {}))
    
    def set_section(self, section: str, values: Dict[str, Any]):
        """设置整个配置节
        
        Args:
            section: 配置节名称
            values: 配置项字典
        """
        self._config[section] = copy.deepcopy(values)
    
    def save(self):
        """保存配置到文件"""
        self._save()
    
    def reset_to_default(self):
        """恢复默认配置"""
        self._config = copy.deepcopy(DEFAULT_CONFIG)
        self._save()
    
    def get_config_path(self) -> Path:
        """获取配置文件路径"""
        return self._config_path
    
    def export_config(self, export_path: str) -> bool:
        """导出配置到指定文件
        
        Args:
            export_path: 导出文件路径
            
        Returns:
            是否成功
        """
        try:
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
            return True
        except IOError as e:
            print(f"导出配置失败: {e}")
            return False
    
    def import_config(self, import_path: str) -> bool:
        """从文件导入配置
        
        Args:
            import_path: 导入文件路径
            
        Returns:
            是否成功
        """
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                imported = json.load(f)
                self._config = self._merge_with_defaults(imported)
                self._save()
                return True
        except (json.JSONDecodeError, IOError, TypeError, ValueError) as e:
            print(f"导入配置失败: {e}")
            return False


# 全局单例（延迟初始化）
_settings_instance: Optional[Settings] = None


def get_settings() -> Settings:
    """获取全局配置管理器实例"""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def reset_settings_instance():
    """重置全局实例（用于测试）"""
    global _settings_instance
    _settings_instance = None
