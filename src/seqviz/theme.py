"""seqviz 主题系统：theme.json 控制 TUI 界面配色。

主题文件位置: ~/.config/seqviz/theme.json
设计目标: 白底黑字，浅灰分隔线，让序列着色更清晰。
"""

import json
from pathlib import Path

# 内置默认主题（白底黑字 + 浅灰线条）
DEFAULT_THEME: dict = {
    "background": "#ffffff",     # 全局背景（白）
    "foreground": "#1a1a1a",     # 普通文字（近黑）
    "border": "#d8d8d8",         # 区域分隔线（浅灰）
    "accent": "#0066cc",         # 强调色（焦点边框等）
    "panel": "#f4f4f4",          # 面板背景（状态栏/命令栏，极浅灰）
    "muted": "#8a8a8a",          # 弱化文字（灰）
    "highlight": "#e8f0fb",      # 选中高亮（浅蓝）
}

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


def load_theme() -> dict:
    """加载主题：内置默认值 <- 用户 theme.json。"""
    theme = DEFAULT_THEME
    if THEME_FILE.exists():
        try:
            with open(THEME_FILE) as f:
                user_theme = json.load(f)
            if isinstance(user_theme, dict):
                theme = _deep_merge(theme, user_theme)
        except (json.JSONDecodeError, OSError):
            pass
    return theme


_theme: dict | None = None


def get_theme() -> dict:
    """获取当前生效主题（懒加载单例）。"""
    global _theme
    if _theme is None:
        _theme = load_theme()
    return _theme


def build_browser_css(theme: dict) -> str:
    """生成序列浏览器（FastaBrowser）的 CSS。"""
    bg = theme["background"]
    fg = theme["foreground"]
    border = theme["border"]
    accent = theme["accent"]
    panel = theme["panel"]
    muted = theme["muted"]
    highlight = theme["highlight"]
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
        background: {panel};
        color: {fg};
    }}
    TabbedContent {{
        height: 1fr;
    }}
    Tabs {{
        background: {panel};
        color: {fg};
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
    accent = theme["accent"]
    panel = theme["panel"]
    muted = theme["muted"]
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
