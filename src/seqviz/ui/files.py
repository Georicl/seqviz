"""目录文件选择器；后台计数，UI 线程更新预览和通知。"""

import threading
from functools import partial
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from seqviz import config
from seqviz.core.files import FileInfo, count_sequences, scan_directory
from seqviz.core.formats import FileFormat
from seqviz.ui.theme import (
    build_file_browser_css,
    get_theme,
    get_theme_name,
    is_dark_theme,
)


def format_size(size_bytes: int) -> str:
    """格式化文件大小。"""
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f}G"
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f}M"
    if size_bytes >= 1_000:
        return f"{size_bytes / 1_000:.1f}K"
    return f"{size_bytes}B"


class FilePreview(Static):
    """右侧文件预览面板。"""

    def show_info(self, info: FileInfo | None, error: str | None = None):
        if info is None:
            self.update(Text("  无文件", style="dim"))
            return

        fmt_label = info.fmt.value.upper()
        count_label = "变异数" if info.fmt == FileFormat.VCF else "序列数"
        content = Text()
        content.append("\n  文件详情\n\n", style="bold cyan")
        content.append("  名称: ", style="dim")
        content.append(f"{info.name}\n", style="bold white")
        content.append("  路径: ", style="dim")
        content.append(f"{info.path}\n", style="green")
        content.append("  大小: ", style="dim")
        content.append(f"{format_size(info.size)}\n", style="yellow")
        content.append("  格式: ", style="dim")
        content.append(f"{fmt_label}\n", style="magenta")
        content.append(f"  {count_label}: ", style="dim")
        if error is not None:
            content.append(f"读取失败: {error}\n", style="red")
        elif info.seq_count is None:
            content.append("统计中...\n", style="dim")
        else:
            content.append(f"{info.seq_count:,}\n", style="bold green")
        content.append("\n  [Enter] 打开  [Space] 多选\n", style="dim")
        self.update(content)


class FileBrowser(App):
    """目录序列文件选择器。

    返回值: 选中的文件路径列表 (list[Path])，取消则返回空列表。
    """

    TITLE = "Seqviz"
    SUB_TITLE = "序列文件选择器"
    # 类样式在导入时生成；主题重载不修改已定义的类。
    DARK = is_dark_theme(get_theme_name())  # 根据主题自动切换

    CSS = build_file_browser_css(get_theme())

    BINDINGS: ClassVar[list] = [
        Binding("j", "cursor_down", "下移", show=True, priority=True),
        Binding("k", "cursor_up", "上移", show=True, priority=True),
        Binding("space", "toggle_select", "多选", show=True, priority=True),
        Binding("enter", "open_file", "打开", show=True, priority=True),
        Binding("a", "select_all", "全选", show=True, priority=True),
        Binding("q", "cancel", "退出", show=True, priority=True),
        Binding("ctrl+c", "cancel", "退出", show=False, priority=True),
    ]

    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory
        self.files: list[FileInfo] = []
        self.selected: set[int] = set()  # 多选索引集合
        self._preview_index = -1  # 当前预览的文件索引
        self._count_cancel_event = (
            threading.Event()
        )  # 中断 count_sequences 的全文件读取
        self._count_errors: dict[int, str] = {}
        self._counting: set[int] = set()  # 正在计数的文件索引（去重，避免重复全量读取）

    def on_mount(self):
        # 扫描目录
        self.files = scan_directory(
            self.directory, config.get("file_browser.extensions")
        )
        self._rebuild_list()
        # 高亮第一项并预览
        if self.files:
            self._update_preview(0)
        self.query_one("#file-list", OptionList).focus()

    def _rebuild_list(self):
        """重建文件列表（带选择标记）。"""
        option_list = self.query_one("#file-list", OptionList)
        option_list.clear_options()
        for i, info in enumerate(self.files):
            # 用 Text 对象避免方括号被当作 Rich 标记解析
            label = Text()
            if i in self.selected:
                label.append(" ✓ ", style="bold green")
            else:
                label.append("   ", style="dim")
            if info.fmt == FileFormat.VCF:
                fmt_tag = "V"
            else:
                fmt_tag = "Q" if info.fmt == FileFormat.FASTQ else "F"
            tag_style = {"Q": "cyan", "F": "magenta", "V": "green"}[fmt_tag]
            label.append(f"[{fmt_tag}] ", style=tag_style)
            label.append(info.name, style="bold")
            label.append(f"  ({format_size(info.size)})", style="dim")
            option_list.add_option(Option(label, id=f"file-{i}"))

    def _update_preview(self, index: int):
        """预览指定文件；序列数在后台线程统计，避免大文件全量读取冻屏。"""
        if not (0 <= index < len(self.files)):
            return
        self._preview_index = index
        info = self.files[index]
        self.query_one("#preview", FilePreview).show_info(
            info, self._count_errors.get(index)
        )
        if (
            info.seq_count is None
            and index not in self._counting
            and index not in self._count_errors
        ):
            # 后台统计（thread worker），完成后回 UI 线程刷新预览；
            # _counting 去重避免导航事件重复派发全文件读取
            self._counting.add(index)
            self.run_worker(
                partial(self._count_in_thread, index), thread=True, exclusive=False
            )

    def _count_in_thread(self, index: int):
        """读取错误与计数结果都交回 UI 线程，退出后停止投递。"""
        info = self.files[index]
        try:
            count = count_sequences(info.path, info.fmt, self._count_cancel_event)
            callback = partial(self._apply_seq_count, index, count)
        except OSError as exc:
            callback = partial(self._apply_count_error, index, str(exc))
        if not self._count_cancel_event.is_set():
            try:
                self.call_from_thread(callback)
            except RuntimeError:
                pass  # 检查标志与投递之间应用可能已退出。

    def _apply_count_error(self, index: int, error: str):
        self._counting.discard(index)
        self._count_errors[index] = error
        self.notify(
            f"{self.files[index].name}: {error}", title="读取失败", severity="error"
        )
        if index == self._preview_index:
            self.query_one("#preview", FilePreview).show_info(self.files[index], error)

    def _apply_seq_count(self, index: int, count: int):
        """UI 线程：回填序列数，仅当该文件仍是当前预览时刷新。"""
        self._counting.discard(index)
        self.files[index].seq_count = count
        if index == self._preview_index:
            self.query_one("#preview", FilePreview).show_info(self.files[index])

    def on_unmount(self):
        """退出时置取消标志：计数线程中断文件读取且不再投递 UI 更新。"""
        self._count_cancel_event.set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            OptionList(id="file-list"),
            FilePreview(id="preview"),
        )
        yield Footer()

    # ── 导航 ──
    def action_cursor_down(self):
        option_list = self.query_one("#file-list", OptionList)
        option_list.action_cursor_down()
        self._update_preview(option_list.highlighted or 0)

    def action_cursor_up(self):
        option_list = self.query_one("#file-list", OptionList)
        option_list.action_cursor_up()
        self._update_preview(option_list.highlighted or 0)

    def on_option_list_option_highlighted(
        self, message: OptionList.OptionHighlighted
    ) -> None:
        """鼠标/键盘高亮变化时更新预览。"""
        option_id = message.option.id if message.option else None
        if option_id and option_id.startswith("file-"):
            idx = int(option_id[5:])
            self._update_preview(idx)

    # ── 选择 ──
    def action_toggle_select(self):
        """Space: 切换当前项的多选状态。"""
        option_list = self.query_one("#file-list", OptionList)
        idx = option_list.highlighted or 0
        if idx in self.selected:
            self.selected.discard(idx)
        else:
            self.selected.add(idx)
        self._rebuild_list()
        option_list.highlighted = idx

    def action_select_all(self):
        """a: 全选/取消全选。"""
        if len(self.selected) == len(self.files):
            self.selected.clear()
        else:
            self.selected = set(range(len(self.files)))
        self._rebuild_list()

    # ── 打开 ──
    def action_open_file(self):
        """Enter: 打开。若有多选则打开多选，否则打开当前高亮项。"""
        if self.selected:
            paths = [self.files[i].path for i in sorted(self.selected)]
        else:
            option_list = self.query_one("#file-list", OptionList)
            idx = option_list.highlighted or 0
            if 0 <= idx < len(self.files):
                paths = [self.files[idx].path]
            else:
                paths = []
        self.exit(result=paths)

    def action_cancel(self):
        """q: 取消，返回空列表。"""
        self.exit(result=[])


def run_file_browser(directory: Path) -> list[Path]:
    """启动文件浏览器，返回用户选中的文件路径列表。"""
    app = FileBrowser(directory)
    result = app.run()
    return result or []
