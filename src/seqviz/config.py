"""seqviz 配置系统：用户级 JSON 配置覆盖内置默认值。

配置文件位置: ~/.config/seqviz/config.json
"""

import json
from pathlib import Path

# 内置默认配置
DEFAULT_CONFIG: dict = {
    "theme": "light",               # 内置主题名: light/dark/nord/gruvbox/catppuccin/solarized/rose-pine/tokyo-night
    "browser": {
        "wrap_width": 60,           # 每行碱基数
        "scroll_step": 5,           # j/k 每次滚动行数
        "sidebar_width": 32,        # 侧栏宽度
        "show_line_numbers": True,  # 显示位置编号
        "show_quality": True,       # FASTQ 显示质量值行
    },
    "colors": {
        "dna": {
            "A": "green",
            "T": "red",
            "C": "blue",
            "G": "yellow",
            "N": "dim",
        },
        "quality_thresholds": {
            "high": 30,     # Q >= high  -> 绿色
            "medium": 20,   # Q >= medium -> 黄色
            "low": 10,      # Q >= low   -> 橙色, 否则红色
        },
    },
    "file_browser": {
        "extensions": [
            ".fa", ".fasta", ".fna", ".faa", ".aa", ".seq",
            ".fq", ".fastq",
        ],
    },
}

CONFIG_DIR = Path.home() / ".config" / "seqviz"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并：override 覆盖 base，返回新 dict（不修改原对象）。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    """加载配置：内置默认值 <- 用户配置文件。配置无效时回退默认值。"""
    config = DEFAULT_CONFIG
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                user_config = json.load(f)
            if isinstance(user_config, dict):
                config = _deep_merge(config, user_config)
        except (json.JSONDecodeError, OSError):
            pass  # 配置损坏时静默使用默认值
    return config


# 全局配置实例（懒加载单例）
_config: dict | None = None


def get_config() -> dict:
    """获取当前生效配置（首次调用时加载）。"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> dict:
    """强制重新加载配置。"""
    global _config
    _config = None
    return get_config()


def get(path: str, default=None):
    """按点分路径获取配置值，如 get('browser.wrap_width')。"""
    current = get_config()
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current
