"""目录序列文件浏览器：扫描目录中的序列文件，提供选择界面。"""

from pathlib import Path
from dataclasses import dataclass, field
import gzip

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, Static, OptionList
from textual.widgets.option_list import Option
from textual.containers import Horizontal
from rich.text import Text

from seqviz.browser import FileFormat
from seqviz import config
from seqviz.theme import get_theme, build_file_browser_css, get_theme_name, is_dark_theme


# 支持的序列文件后缀（从配置加载，可被用户 JSON 覆盖）
SEQ_EXTENSIONS = set(config.get("file_browser.extensions", []))


def is_sequence_file(path: Path) -> bool:
    """判断是否为序列文件（支持 .gz 双后缀）。"""
    if not path.is_file():
        return False
    if path.suffix.lower() == ".gz":
        inner_suffix = Path(path.stem).suffix.lower()
        return inner_suffix in SEQ_EXTENSIONS
    return path.suffix.lower() in SEQ_EXTENSIONS


def detect_file_format(path: Path) -> FileFormat:
    """根据后缀或首字符检测文件格式。"""
    name = path.name.lower()
    if ".fq" in name or ".fastq" in name:
        return FileFormat.FASTQ
    # 其余序列后缀默认 FASTA（含 .fa/.fasta/.fna/.faa/.aa/.seq）
    if any(ext in name for ext in (".fa", ".fasta", ".fna", ".faa", ".aa", ".seq")):
        return FileFormat.FASTA
    # 后缀不明确时读首字符
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    try:
        with opener(path, "rt") as f:
            first = f.read(1)
        return FileFormat.FASTQ if first == "@" else FileFormat.FASTA
    except Exception:
        return FileFormat.FASTA


def count_sequences(path: Path, fmt: FileFormat) -> int:
    """快速统计序列条数。FASTA 数 '>' 行，FASTQ 按 4 行一组。"""
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    count = 0
    try:
        if fmt == FileFormat.FASTQ:
            # FASTQ: 每 4 行一条记录，数行数除以 4
            lines = 0
            with opener(path, "rb") as f:
                for _ in f:
                    lines += 1
            count = lines // 4
        else:
            # FASTA: 数以 '>' 开头的行
            with opener(path, "rb") as f:
                for line in f:
                    if line.startswith(b">"):
                        count += 1
    except Exception:
        count = 0
    return count


def format_size(size_bytes: int) -> str:
    """格式化文件大小。"""
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f}G"
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f}M"
    if size_bytes >= 1_000:
        return f"{size_bytes / 1_000:.1f}K"
    return f"{size_bytes}B"


@dataclass
class FileInfo:
    """序列文件的元信息。"""
    path: Path
    size: int
    fmt: FileFormat
    seq_count: int = 0

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_str(self) -> str:
        return format_size(self.size)


def scan_directory(directory: Path) -> list[FileInfo]:
    """扫描目录中的所有序列文件，返回按文件名排序的列表。"""
    files: list[FileInfo] = []
    for entry in sorted(directory.iterdir()):
        if is_sequence_file(entry):
            fmt = detect_file_format(entry)
            info = FileInfo(
                path=entry,
                size=entry.stat().st_size,
                fmt=fmt,
            )
            files.append(info)
    return files


class FilePreview(Static):
    """右侧文件预览面板。"""

    def show_info(self, info: FileInfo | None):
        if info is None:
            self.update(Text("  无文件", style="dim"))
            return

        fmt_label = "FASTQ" if info.fmt == FileFormat.FASTQ else "FASTA"
        content = Text()
        content.append("\n  文件详情\n\n", style="bold cyan")
        content.append("  名称: ", style="dim")
        content.append(f"{info.name}\n", style="bold white")
        content.append("  路径: ", style="dim")
        content.append(f"{info.path}\n", style="green")
        content.append("  大小: ", style="dim")
        content.append(f"{info.size_str}\n", style="yellow")
        content.append("  格式: ", style="dim")
        content.append(f"{fmt_label}\n", style="magenta")
        content.append("  序列数: ", style="dim")
        if info.seq_count > 0:
            content.append(f"{info.seq_count:,}\n", style="bold green")
        else:
            content.append("统计中...\n", style="dim")
        content.append("\n  [Enter] 打开  [Space] 多选\n", style="dim")
        self.update(content)


class FileBrowser(App):
    """目录序列文件选择器。

    返回值: 选中的文件路径列表 (list[Path])，取消则返回空列表。
    """

    TITLE = "Seqviz"
    SUB_TITLE = "序列文件选择器"
    DARK = is_dark_theme(get_theme_name())  # 根据主题自动切换

    CSS = build_file_browser_css(get_theme())

    BINDINGS = [
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

    def on_mount(self):
        # 扫描目录
        self.files = scan_directory(self.directory)
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
            fmt_tag = "Q" if info.fmt == FileFormat.FASTQ else "F"
            label.append(f"[{fmt_tag}] ", style="cyan" if fmt_tag == "Q" else "magenta")
            label.append(info.name, style="bold")
            label.append(f"  ({info.size_str})", style="dim")
            option_list.add_option(Option(label, id=f"file-{i}"))

    def _update_preview(self, index: int):
        """预览指定文件（含异步统计序列数）。"""
        if 0 <= index < len(self.files):
            info = self.files[index]
            # 快速统计序列数（若尚未统计）
            if info.seq_count == 0:
                info.seq_count = count_sequences(info.path, info.fmt)
            self.query_one("#preview", FilePreview).show_info(info)

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

    def on_option_list_option_highlighted(self, message: OptionList.OptionHighlighted) -> None:
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
