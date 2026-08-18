"""跨平台剪贴板复制：系统工具优先，失败后回退 OSC 52。

OSC 52 通过终端转义序列写入剪贴板，适用于无图形界面 / SSH 场景。
browser.py 与 vcf_browser.py 共用此实现，避免两套逻辑漂移。
"""

import subprocess
from collections.abc import Callable


def copy_to_clipboard(text: str, osc52_fallback: Callable[[str], None]) -> bool:
    """复制文本到剪贴板，成功返回 True。

    策略：系统工具优先（反馈可靠），失败后回退 OSC 52（需终端支持，SSH 下同样有效）。
    """
    import platform
    system = platform.system()
    data = text.encode()
    try:
        if system == "Darwin":  # macOS
            subprocess.run(["pbcopy"], input=data, check=True)
            return True
        elif system == "Linux":
            # 依次尝试 xclip / xsel / wl-copy，任一成功即可
            for cmd in (
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
                ["wl-copy"],
            ):
                try:
                    subprocess.run(cmd, input=data, check=True)
                    return True
                except (OSError, subprocess.CalledProcessError):
                    continue
        else:  # Windows
            subprocess.run(["clip"], input=data, check=True)
            return True
    except (OSError, subprocess.CalledProcessError):
        pass  # 工具缺失或异常退出（非 OSError），回退 OSC 52
    try:
        osc52_fallback(text)
        return True
    except Exception:  # noqa: BLE001
        return False  # 剪贴板不可用
