"""seqviz 配置系统：用户级 JSON 配置覆盖内置默认值。

配置文件位置: ~/.config/seqviz/config.json
"""

import copy
import json
from pathlib import Path

# 内置默认配置
DEFAULT_CONFIG: dict = {
    "theme": "dark",               # 内置主题名: light/dark/nord/gruvbox/catppuccin/solarized/rose-pine/tokyo-night
    "browser": {
        "wrap_width": 60,           # 每行碱基数（auto_wrap 关闭时生效）
        "auto_wrap": True,          # 根据窗口宽度自动换行
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
            "low": 10,      # Q >= low   -> 亮红, 否则红色
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


def _coerce_types(default, value):
    """递归类型校验：value 与 default 类型不符时回退 default（dict 逐键校验）。

    防止用户配置写错类型（如 "dna": "red"）导致消费方（如 dict(...) ）在
    导入期崩溃；用户新增的未知键原样保留。
    """
    if isinstance(default, dict):
        if not isinstance(value, dict):
            return _coerce_types(default, {})  # 整体类型不符 → 全部回退
        result = {}
        for k, dv in default.items():
            result[k] = _coerce_types(dv, value[k]) if k in value else dv
        # 保留用户新增键（不在默认 schema 中）
        for k, v in value.items():
            if k not in default:
                result[k] = v
        return result
    if isinstance(default, bool):  # bool 须在 int 之前判断（bool 是 int 子类）
        if isinstance(value, bool):
            return value
        # 宽容 0/1 写为 false/true 的常见写法，避免静默反转行为
        return bool(value) if value in (0, 1) else default
    if isinstance(default, int):
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        # 宽容整数值 float（如 80.0），避免静默丢弃
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    if isinstance(default, list):
        return value if isinstance(value, list) else list(default)
    return value


def load_config() -> dict:
    """加载配置：内置默认值 <- 用户配置文件。配置无效（语法或类型）时回退默认值。

    返回值可安全修改：无用户配置时返回默认值的深拷贝，
    避免消费方原地修改污染全局 DEFAULT_CONFIG。
    """
    config = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                user_config = json.load(f)
            if isinstance(user_config, dict):
                merged = _deep_merge(DEFAULT_CONFIG, user_config)
                config = _coerce_types(DEFAULT_CONFIG, merged)
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
    """强制重新加载配置（同步刷新 theme 单例，保持两者重载语义一致）。"""
    global _config
    _config = None
    cfg = get_config()
    from seqviz import theme as theme_mod  # 延迟导入避免循环依赖
    theme_mod.reset_theme()
    return cfg


def get(path: str, default=None):
    """按点分路径获取配置值，如 get('browser.wrap_width')。"""
    current = get_config()
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current
