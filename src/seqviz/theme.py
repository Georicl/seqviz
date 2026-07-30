"""seqviz 主题系统：内置多套配色方案，支持 theme.json 自定义覆盖。

主题选择: config.json 中 "theme" 字段指定内置主题名
自定义覆盖: ~/.config/seqviz/theme.json 中的字段会覆盖内置主题
"""

import json
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  内置主题
# ═══════════════════════════════════════════════════════════════

BUILTIN_THEMES: dict[str, dict] = {

    # ── 1. light（默认 · 白底黑字 · 清晰明亮） ──
    "light": {
        "background": "#ffffff",
        "foreground": "#1a1a1a",
        "border": "#d8d8d8",
        "accent": "#0066cc",
        "panel": "#f4f4f4",
        "muted": "#8a8a8a",
        "highlight": "#e8f0fb",
        "cursor": "#0066cc",
        "gutter": "#f0f0f0",
    },

    # ── 2. dark（经典深色 · 护眼低对比） ──
    "dark": {
        "background": "#1e1e2e",
        "foreground": "#cdd6f4",
        "border": "#45475a",
        "accent": "#89b4fa",
        "panel": "#181825",
        "muted": "#6c7086",
        "highlight": "#313244",
        "cursor": "#89b4fa",
        "gutter": "#181825",
    },

    # ── 3. nord（北极冷色 · 柔和优雅） ──
    "nord": {
        "background": "#2e3440",
        "foreground": "#d8dee9",
        "border": "#434c5e",
        "accent": "#88c0d0",
        "panel": "#272e3a",
        "muted": "#616e88",
        "highlight": "#3b4252",
        "cursor": "#88c0d0",
        "gutter": "#272e3a",
    },

    # ── 4. gruvbox（暖色复古 · 棕黄基调） ──
    "gruvbox": {
        "background": "#282828",
        "foreground": "#ebdbb2",
        "border": "#504945",
        "accent": "#fabd2f",
        "panel": "#1d2021",
        "muted": "#928374",
        "highlight": "#3c3836",
        "cursor": "#fabd2f",
        "gutter": "#1d2021",
    },

    # ── 5. catppuccin（柔和粉彩 · 温暖暗色） ──
    "catppuccin": {
        "background": "#1e1e2e",
        "foreground": "#cdd6f4",
        "border": "#585b70",
        "accent": "#cba6f7",
        "panel": "#181825",
        "muted": "#6c7086",
        "highlight": "#313244",
        "cursor": "#f5c2e7",
        "gutter": "#181825",
    },

    # ── 6. solarized（经典 Solarized Dark） ──
    "solarized": {
        "background": "#002b36",
        "foreground": "#839496",
        "border": "#073642",
        "accent": "#268bd2",
        "panel": "#073642",
        "muted": "#586e75",
        "highlight": "#073642",
        "cursor": "#268bd2",
        "gutter": "#073642",
    },

    # ── 7. rose-pine（玫瑰松木 · 低饱和暖紫） ──
    "rose-pine": {
        "background": "#191724",
        "foreground": "#e0def4",
        "border": "#26233a",
        "accent": "#c4a7e7",
        "panel": "#1f1d2e",
        "muted": "#6e6a86",
        "highlight": "#26233a",
        "cursor": "#ebbcba",
        "gutter": "#1f1d2e",
    },

    # ── 8. tokyo-night（东京夜景 · 蓝紫冷调） ──
    "tokyo-night": {
        "background": "#1a1b26",
        "foreground": "#c0caf5",
        "border": "#292e42",
        "accent": "#7aa2f7",
        "panel": "#16161e",
        "muted": "#565f89",
        "highlight": "#283457",
        "cursor": "#7aa2f7",
        "gutter": "#16161e",
    },
}

# 默认主题名
DEFAULT_THEME_NAME = "dark"

# 暗色主题集合（用于自动设置 App.DARK）
DARK_THEMES = {"dark", "nord", "gruvbox", "catppuccin", "solarized", "rose-pine", "tokyo-night"}

# ═══════════════════════════════════════════════════════════════
#  主题加载
# ═══════════════════════════════════════════════════════════════

THEME_DIR = Path.home() / ".config" / "seqviz"
THEME_FILE = THEME_DIR / "theme.json"


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并：override 覆盖 base。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_theme(theme_name: str | None = None) -> dict:
    """加载主题：内置主题 <- 用户 theme.json 覆盖。

    Args:
        theme_name: 内置主题名（如 "dark", "nord"）。
                    None 时从 config 的 "theme" 字段读取，
                    若也没有则使用 DEFAULT_THEME_NAME。
    """
    if theme_name is None:
        theme_name = get_theme_name()

    base = BUILTIN_THEMES.get(theme_name, BUILTIN_THEMES[DEFAULT_THEME_NAME])
    theme = dict(base)

    # 用户 theme.json 覆盖
    if THEME_FILE.exists():
        try:
            with open(THEME_FILE) as f:
                user_theme = json.load(f)
            if isinstance(user_theme, dict):
                user_colors = {k: v for k, v in user_theme.items() if k != "name"}
                if user_colors:
                    theme = _deep_merge(theme, user_colors)
        except (json.JSONDecodeError, OSError):
            pass
    return theme


def get_theme_name() -> str:
    """从 config 获取主题名。"""
    try:
        from seqviz import config as config_mod
        name = config_mod.get("theme")
        if name and name in BUILTIN_THEMES:
            return name
    except Exception:
        pass
    return DEFAULT_THEME_NAME


def is_dark_theme(theme_name: str | None = None) -> bool:
    """判断当前主题是否为暗色主题。"""
    if theme_name is None:
        theme_name = get_theme_name()
    return theme_name in DARK_THEMES


def list_themes() -> list[str]:
    """返回所有可用内置主题名。"""
    return list(BUILTIN_THEMES.keys())


# ═══════════════════════════════════════════════════════════════
#  单例 & 兼容
# ═══════════════════════════════════════════════════════════════

_theme: dict | None = None


def get_theme() -> dict:
    """获取当前生效主题（懒加载单例）。"""
    global _theme
    if _theme is None:
        _theme = load_theme()
    return _theme


def reset_theme():
    """重置主题单例（用于测试或主题切换后刷新）。"""
    global _theme
    _theme = None


# 兼容旧代码：DEFAULT_THEME 指向 light
DEFAULT_THEME = BUILTIN_THEMES[DEFAULT_THEME_NAME]


# ═══════════════════════════════════════════════════════════════
#  CSS 生成
# ═══════════════════════════════════════════════════════════════

def build_browser_css(theme: dict) -> str:
    """生成序列浏览器（FastaBrowser）的 CSS。"""
    bg = theme["background"]
    fg = theme["foreground"]
    border = theme["border"]
    accent = theme.get("accent", fg)
    panel = theme.get("panel", bg)
    muted = theme.get("muted", fg)
    highlight = theme.get("highlight", bg)
    cursor = theme.get("cursor", accent)
    gutter = theme.get("gutter", panel)
    return f"""
    Screen {{
        background: {bg};
    }}
    Horizontal {{
        height: 1fr;
    }}
    #body {{
        height: 1fr;
    }}
    .sidebar {{
        width: 32;
        border-right: thick {border};
        background: {bg};
        color: {fg};
    }}
    .sidebar:focus {{
        border-right: thick {accent};
    }}
    .sidebar > OptionList {{
        background: {bg};
        color: {fg};
    }}
    .sidebar > OptionList > .option-list--option-highlighted {{
        background: {highlight};
        color: {fg};
    }}
    .sidebar > OptionList > .option-list--option-hover {{
        background: {highlight};
    }}
    .main-view {{
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        background: {bg};
        color: {fg};
    }}
    #statusbar {{
        dock: bottom;
        height: 1;
        background: {panel};
        color: {fg};
        padding: 0 1;
        border-top: tall {border};
    }}
    #command-bar {{
        height: 1;
        margin: 0 1;
        border: none;
        background: {gutter};
        color: {fg};
    }}
    Input {{
        background: {gutter};
        color: {fg};
        border: tall {border};
    }}
    Input:focus {{
        border: tall {accent};
    }}
    TabbedContent {{
        height: 1fr;
    }}
    Tabs {{
        background: {panel};
        color: {muted};
    }}
    Tab {{
        color: {muted};
    }}
    Tab.-active {{
        background: {highlight};
        color: {fg};
    }}
    Header {{
        background: {panel};
        color: {fg};
    }}
    Footer {{
        background: {panel};
        color: {muted};
    }}
    FooterKey {{
        color: {fg};
    }}
    """


def build_file_browser_css(theme: dict) -> str:
    """生成文件选择器（FileBrowser）的 CSS。"""
    bg = theme["background"]
    fg = theme["foreground"]
    border = theme["border"]
    accent = theme.get("accent", fg)
    panel = theme.get("panel", bg)
    muted = theme.get("muted", fg)
    highlight = theme.get("highlight", bg)
    return f"""
    Screen {{
        background: {bg};
    }}
    Horizontal {{
        height: 1fr;
    }}
    #file-list {{
        width: 1fr;
        border-right: thick {border};
        background: {bg};
        color: {fg};
    }}
    #file-list:focus {{
        border-right: thick {accent};
    }}
    #file-list > OptionList > .option-list--option-highlighted {{
        background: {highlight};
        color: {fg};
    }}
    #preview {{
        width: 50;
        padding: 0 1;
        background: {bg};
        color: {fg};
    }}
    Header {{
        background: {panel};
        color: {fg};
    }}
    Footer {{
        background: {panel};
        color: {muted};
    }}
    FooterKey {{
        color: {fg};
    }}
    """
