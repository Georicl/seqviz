import gzip
import subprocess
from collections.abc import Generator
from enum import Enum
from pathlib import Path
from typing import IO, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Header,
    Input,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from seqviz import config
from seqviz.renderer import (
    colorize_quality,
    colorize_sequence,
    quality_bar,
    quality_stats,
)
from seqviz.seq_type import SeqType, detect_seq_type
from seqviz.theme import build_browser_css, get_theme, get_theme_name, is_dark_theme


def _open_seq_file(filepath: Path, mode: str = "rb") -> IO:
    """打开序列文件（透明处理 gzip 压缩）。

    默认二进制模式，保证 offset 计算正确且不受 CRLF 影响。
    """
    if filepath.suffix.lower() == ".gz":
        return gzip.open(filepath, mode)
    return open(filepath, mode)


class FileFormat(Enum):
    FASTA = "fasta"
    FASTQ = "fastq"


class SequenceInfo:
    """存储一条序列的元信息（不加载序列本身）。"""
    __slots__ = ("has_quality", "header", "index", "length", "offset")

    def __init__(self, index: int, header: str, offset: int, length: int = -1, has_quality: bool = False):
        self.index = index
        self.header = header
        self.offset = offset        # 文件中的字节偏移量（用于快速定位）
        self.length = length        # -1 表示未知（懒计算）
        self.has_quality = has_quality  # FASTQ 记录有质量值


def _iter_sequences(filepath: Path, fmt: FileFormat, start_idx: int = 0) -> Generator[SequenceInfo, None, None]:
    """通用序列迭代器：二进制模式流式解析 FASTA/FASTQ，yield SequenceInfo。

    Args:
        filepath: 序列文件路径
        fmt: 文件格式 (FASTA/FASTQ)
        start_idx: 起始索引（跳过之前的序列，用于后台续扫）
    """
    if fmt == FileFormat.FASTQ:
        offset = 0
        with _open_seq_file(filepath, "rb") as f:
            idx = 0
            while True:
                record_offset = offset
                header_line = f.readline()
                if not header_line:
                    return
                offset += len(header_line)
                seq_line = f.readline()
                offset += len(seq_line)
                plus_line = f.readline()  # + 行
                offset += len(plus_line)
                quality_line = f.readline()  # quality 行
                offset += len(quality_line)
                if idx >= start_idx:
                    header = header_line.strip()[1:].decode()
                    yield SequenceInfo(idx, header, record_offset, len(seq_line.strip()), has_quality=True)
                idx += 1
    else:
        with _open_seq_file(filepath, "rb") as f:
            idx = 0
            offset = 0
            for raw_line in f:
                if raw_line.startswith(b">"):
                    if idx >= start_idx:
                        yield SequenceInfo(idx, raw_line[1:].strip().decode(), offset)
                    idx += 1
                offset += len(raw_line)


class SequenceList(OptionList):
    """左侧序列列表（基于 OptionList，内部虚拟化，支持大量序列）。"""

    def __init__(self, sequences: list[SequenceInfo], **kwargs):
        super().__init__(**kwargs)
        self.sequences = sequences
        for seq in sequences:
            self.add_option(Option(self._make_label(seq), id=f"seq-{seq.index}"))

    @staticmethod
    def _make_label(seq: SequenceInfo) -> str:
        label = seq.header[:20] + "..." if len(seq.header) > 20 else seq.header
        if seq.length < 0:
            return f" {label}"
        if seq.length >= 1_000_000:
            size_str = f"{seq.length / 1_000_000:.1f}M"
        elif seq.length >= 1_000:
            size_str = f"{seq.length / 1_000:.1f}K"
        else:
            size_str = str(seq.length)
        return f" {label}  {size_str}bp"

    def append_sequences(self, new_seqs: list[SequenceInfo]):
        """追加新扫描到的序列（后台扫描用）。"""
        for seq in new_seqs:
            self.sequences.append(seq)
            self.add_option(Option(self._make_label(seq), id=f"seq-{seq.index}"))


class SequenceView(Static):
    """右侧序列详情显示区（按需渲染，只生成可见行）。"""

    # 超过此阈值的 FASTA 序列使用分块加载（1Mbp）
    LARGE_SEQ_THRESHOLD = 1_000_000

    def __init__(self, filepath: Path, file_format: FileFormat = FileFormat.FASTA, **kwargs):
        super().__init__(**kwargs)
        self.filepath = filepath
        self.file_format = file_format
        self.view_offset = 0
        self.current_seq: SequenceInfo | None = None
        # 从配置加载显示参数
        self._config_wrap = config.get("browser.wrap_width", 60)
        self.WRAP = self._config_wrap
        self.auto_wrap = config.get("browser.auto_wrap", True)  # 自适应窗口宽度
        self.show_line_numbers = config.get("browser.show_line_numbers", True)
        self.show_quality = config.get("browser.show_quality", True)
        # 序列数据
        self._seq: str = ""
        self._quality: str = ""  # FASTQ 质量值
        self._seq_type: SeqType = SeqType.DNA
        self._header_lines: list[Text] = []  # 统计信息行
        self._total_lines: int = 0
        self._lines_per_chunk: int = 1  # FASTA=1行/chunk, FASTQ=2行/chunk(序列+质量)
        # P1: 大序列分块加载
        self._is_large: bool = False
        self._seq_data_offset: int = 0   # 序列数据在文件中的起始偏移
        self._file_line_width: int = 80  # FASTA 文件每行字节数（含换行符）
        self._chars_per_line: int = 79   # 每行实际碱基数（去除换行符）
        self._seq_length: int = 0        # 序列总长度
        # 持久文件句柄（避免频繁 open/close）
        self._fh: IO | None = None
        self._is_gzip: bool = filepath.suffix.lower() == ".gz"

    def _get_fh(self) -> IO:
        """获取持久文件句柄（懒初始化）。"""
        if self._fh is None or self._fh.closed:
            self._fh = _open_seq_file(self.filepath, "rb")
        return self._fh

    def close(self):
        """关闭持久文件句柄。"""
        if self._fh and not self._fh.closed:
            self._fh.close()
            self._fh = None

    def load_sequence(self, seq_info: SequenceInfo):
        """用 offset 直接 seek 到目标位置，O(1) 定位。大序列分块加载。"""
        self.current_seq = seq_info
        self.view_offset = 0
        self._quality = ""
        self._is_large = False
        # 根据当前窗口宽度计算换行宽度
        self.WRAP = self._compute_wrap()

        # ── 用 seek 直接跳到序列位置（二进制模式） ──
        f = self._get_fh()
        f.seek(seq_info.offset)

        if self.file_format == FileFormat.FASTQ:
            # FASTQ: 4 行一组 (@header / seq / + / quality)
            f.readline()  # 跳过 @header
            self._seq = f.readline().strip().decode()
            f.readline()  # 跳过 +
            self._quality = f.readline().strip().decode()
            self._lines_per_chunk = 2 if self.show_quality else 1
            self._seq_length = len(self._seq)
        else:
            # FASTA: 二进制模式读取
            f.readline()  # 跳过 >header
            seq_data_start = f.tell()
            first_seq_line = f.readline()
            file_line_len = len(first_seq_line)  # 字节数（含 \n 或 \r\n）
            # 计算每行实际碱基数（去除 \n 或 \r\n）
            actual_chars = len(first_seq_line.rstrip(b"\r\n"))

            # 估算序列长度
            est_length = seq_info.length if seq_info.length >= 0 else -1

            # 读取序列：先尝试全量读取（最多读到阈值），超过则切换分块模式
            f.seek(seq_data_start)
            seq_parts: list[str] = []
            total_read = 0
            is_large = False
            while True:
                raw_line = f.readline()
                if not raw_line or raw_line.startswith(b">"):
                    break
                stripped = raw_line.strip().decode()
                seq_parts.append(stripped)
                total_read += len(stripped)
                if est_length < 0 and total_read > self.LARGE_SEQ_THRESHOLD:
                    # 超过阈值，切换为分块模式
                    is_large = True
                    break

            if is_large or (est_length > self.LARGE_SEQ_THRESHOLD):
                # ── 大序列：分块加载模式 ──
                self._is_large = True
                self._seq_data_offset = seq_data_start
                self._file_line_width = file_line_len
                self._chars_per_line = actual_chars
                # Issue #1 修复：计算准确长度（扫描到下一个 > 或 EOF）
                if est_length > 0:
                    self._seq_length = est_length
                else:
                    # 先回到序列数据开头，再扫描全长
                    f.seek(seq_data_start)
                    self._seq_length = self._calc_fasta_length(f, seq_data_start)
                # 只保留前 10K 用于类型检测
                self._seq = "".join(seq_parts)[:10000]
                self._lines_per_chunk = 1
            else:
                # ── 普通序列：全量加载 ──
                self._seq = "".join(seq_parts)
                self._seq_length = len(self._seq)
                self._lines_per_chunk = 1

        self._seq_type = detect_seq_type(self._seq[:10000])

        # ── 生成统计信息行 ──
        type_label = "DNA" if self._seq_type == SeqType.DNA else "Protein"
        type_icon = "[DNA]" if self._seq_type == SeqType.DNA else "[Protein]"

        # GC 含量：大序列用前 10K 估算
        sample = self._seq[:10000] if self._is_large else self._seq
        sample_upper = sample.upper()
        gc = (sample_upper.count("G") + sample_upper.count("C")) / len(sample) * 100 if sample else 0

        seq_id = seq_info.header.split()[0] if seq_info.header else "unknown"
        desc = seq_info.header[len(seq_id):].strip() if len(seq_info.header) > len(seq_id) else ""

        title_line = Text()
        title_line.append(f" {type_icon} ", style="bold")
        title_line.append(seq_id, style="bold cyan")
        if desc:
            title_line.append(f"  {desc[:60]}", style="dim")

        info_line = Text()
        info_line.append("   Length: ", style="dim")
        if self._seq_length > 0:
            info_line.append(f"{self._seq_length:,}", style="bold green")
        else:
            info_line.append("...", style="bold green")
        info_line.append(" bp   GC: ", style="dim")
        gc_note = "~" if self._is_large else ""
        info_line.append(f"{gc_note}{gc:.1f}%", style="bold yellow")
        info_line.append("   Type: ", style="dim")
        info_line.append(type_label, style="bold magenta")

        header_lines = [title_line, info_line]

        # FASTQ 额外显示质量统计 + 质量分布条
        if self._quality:
            qstats = quality_stats(self._quality)
            q_line = Text()
            q_line.append("   Quality: ", style="dim")
            q_line.append(f"Q={qstats['mean']:.1f}", style="bold green")
            q_line.append(f"  (min={qstats['min']}, max={qstats['max']})", style="dim")
            q_line.append("  Q30: ", style="dim")
            q_line.append(f"{qstats['q30_pct']:.0%}", style="bold yellow")
            header_lines.append(q_line)

            bar_line = Text("   ", style="dim")
            bar_line.append(quality_bar(self._quality, width=50))
            header_lines.append(bar_line)

        header_lines.append(Text("─" * 70, style="dim"))
        header_lines.append(Text())
        self._header_lines = header_lines

        # 计算总行数
        self._recalc_total_lines()

        self._update_display()

    @staticmethod
    def _calc_fasta_length(f: IO, seq_data_start: int) -> int:
        """计算 FASTA 序列的准确长度（二进制模式，读到下一个 > 或 EOF）。"""
        length = 0
        while True:
            raw_line = f.readline()
            if not raw_line or raw_line.startswith(b">"):
                break
            length += len(raw_line.strip())
        f.seek(seq_data_start)  # 回到序列数据开头
        return length

    def _load_chunk(self, seq_start: int, seq_end: int) -> str:
        """P1: 从文件加载序列的 [seq_start, seq_end) 区间（大序列用）。"""
        if not self._is_large:
            return self._seq[seq_start:seq_end]

        # 使用精确的每行碱基数和字节数计算文件偏移
        chars_per_line = self._chars_per_line
        line_bytes = self._file_line_width

        if chars_per_line <= 0:
            chars_per_line = 80
        if line_bytes <= 0:
            line_bytes = chars_per_line + 1

        start_line = seq_start // chars_per_line
        start_col = seq_start % chars_per_line
        file_offset = self._seq_data_offset + start_line * line_bytes + start_col

        needed = seq_end - seq_start
        result: list[str] = []
        total = 0
        f = self._get_fh()
        f.seek(file_offset)
        while total < needed:
            raw_line = f.readline()
            if not raw_line or raw_line.startswith(b">"):
                break
            decoded = raw_line.strip().decode()
            result.append(decoded)
            total += len(decoded)
        return "".join(result)[:needed]

    def _make_prefix(self, pos: int | None) -> Text:
        """生成行前缀（位置编号，可配置关闭）。"""
        if not self.show_line_numbers:
            return Text("  ", style="dim")
        if pos is None:
            return Text(f"  {'':>10} │ ", style="dim")
        return Text(f"  {pos:>10,} │ ", style="dim")

    def _get_line(self, index: int) -> Text:
        """按需生成第 index 行（懒加载，大序列分块读取）。"""
        if index < len(self._header_lines):
            return self._header_lines[index]

        body_idx = index - len(self._header_lines)

        if self._lines_per_chunk == 2:
            # FASTQ: 偶数行=序列，奇数行=质量
            chunk_idx = body_idx // 2
            is_quality_line = body_idx % 2 == 1
            chunk_start = chunk_idx * self.WRAP
            chunk_end = min(chunk_start + self.WRAP, self._seq_length)

            if chunk_start >= self._seq_length:
                return Text()

            if is_quality_line:
                colored_q = colorize_quality(self._quality[chunk_start:chunk_end])
                line = self._make_prefix(None)
                line.append(colored_q)
                return line
            else:
                seq_chunk = self._load_chunk(chunk_start, chunk_end)
                colored = colorize_sequence(seq_chunk, self._seq_type)
                line = self._make_prefix(chunk_start + 1)
                line.append(colored)
                return line
        else:
            # FASTA 或关闭质量值的 FASTQ
            chunk_start = body_idx * self.WRAP
            chunk_end = min(chunk_start + self.WRAP, self._seq_length)

            if chunk_start >= self._seq_length:
                return Text()

            seq_chunk = self._load_chunk(chunk_start, chunk_end)
            colored = colorize_sequence(seq_chunk, self._seq_type)
            line = self._make_prefix(chunk_start + 1)
            line.append(colored)
            return line

    def _compute_wrap(self) -> int:
        """根据窗口宽度自适应计算换行宽度。"""
        if not self.auto_wrap:
            return self._config_wrap
        width = self.size.width
        if width <= 0:
            return self._config_wrap
        # 行前缀宽度: "  {pos:>10,} │ " ≈ 15 字符；加上容器 padding
        prefix_width = 15 if self.show_line_numbers else 2
        available = width - prefix_width - 2
        return max(available, 20)  # 最小 20 字符

    def _recalc_total_lines(self):
        """根据当前 WRAP 重新计算总行数。"""
        if self._seq_length > 0:
            chunk_count = (self._seq_length + self.WRAP - 1) // self.WRAP
        elif self._is_large:
            import os
            try:
                file_size = os.path.getsize(self.filepath)
                est_bp = int(file_size * 0.9)
                chunk_count = (est_bp + self.WRAP - 1) // self.WRAP
            except OSError:
                chunk_count = 100000
        else:
            chunk_count = 0
        self._total_lines = len(self._header_lines) + chunk_count * self._lines_per_chunk

    def _update_display(self):
        """只渲染当前可见区域的行。"""
        height = self.size.height if self.size.height > 0 else 30
        content = Text()
        end = min(self.view_offset + height, self._total_lines)
        for i in range(self.view_offset, end):
            content.append(self._get_line(i))
            content.append("\n")
        self.update(content)

    def on_resize(self, event) -> None:
        """组件尺寸变化时重新计算换行宽度并渲染（适应终端缩放、填满窗口）。"""
        new_wrap = self._compute_wrap()
        if new_wrap != self.WRAP:
            self.WRAP = new_wrap
            self._recalc_total_lines()
        if self._seq or self._header_lines:
            self._update_display()

    def scroll_content_up(self, n: int = 5):
        new_offset = max(0, self.view_offset - n)
        if new_offset != self.view_offset:
            self.view_offset = new_offset
            self._update_display()

    def scroll_content_down(self, n: int = 5):
        new_offset = min(max(0, self._total_lines - 1), self.view_offset + n)
        if new_offset != self.view_offset:
            self.view_offset = new_offset
            self._update_display()

class HelpScreen(ModalScreen):
    """帮助面板：显示所有快捷键。"""

    CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-panel {
        width: 60;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS: ClassVar[list] = [Binding("escape", "dismiss", "关闭", show=False), Binding("q", "dismiss", "关闭", show=False)]

    def compose(self) -> ComposeResult:
        help_text = Text()
        help_text.append("\n  seqviz browser 快捷键\n\n", style="bold cyan")

        keys = [
            ("j / k", "上下滚动"),
            ("n / p", "下一条 / 上一条序列"),
            ("Space / b", "向下翻页 / 向上翻页"),
            ("g / G", "跳到顶部 / 底部"),
            ("/", "搜索序列名称"),
            (":", "跳转到第 N 条序列"),
            ("e", "导出当前序列到文件"),
            ("?", "显示此帮助"),
            ("Tab", "切换文件标签页"),
            ("q", "退出"),
        ]
        for key, desc in keys:
            help_text.append(f"  {key:<12}", style="bold yellow")
            help_text.append(f"{desc}\n", style="white")

        help_text.append("\n  按 Esc 或 q 关闭\n", style="dim")
        yield Static(help_text, id="help-panel")


class CommandBar(Input):
    """搜索/跳转/范围复制命令栏（按需动态挂载）。"""

    def __init__(self, mode: str = "search", **kwargs):
        super().__init__(**kwargs)
        self.mode = mode


class StatusBar(Static):
    """底部状态栏：显示当前位置和进度。"""

    def update_status(self, seq_index: int, total_seqs: int,
                      view_offset: int, total_lines: int,
                      seq_length: int):
        bar = Text()
        bar.append(" ", style="bold")
        bar.append(f"序列 {seq_index + 1}/{total_seqs}", style="bold cyan")
        bar.append("  │  ", style="dim")
        bar.append(f"行 {view_offset + 1}/{total_lines}", style="green")
        bar.append("  │  ", style="dim")
        bar.append(f"序列长度 {seq_length:,} bp", style="yellow")

        # 进度百分比
        pct = (view_offset / max(total_lines, 1)) * 100
        bar.append("  │  ", style="dim")
        bar.append(f"{pct:.0f}%", style="bold magenta")

        self.update(bar)


class FileTab:
    """单个文件的标签页数据。"""
    def __init__(self, filepath: Path, sequences: list[SequenceInfo], file_format: FileFormat):
        self.filepath = filepath
        self.sequences = sequences
        self.file_format = file_format
        self.current_index = 0


class FastaBrowser(App):
    """FASTA/FASTQ 文件交互式浏览器（支持多文件标签页）"""

    TITLE = "Seqviz"
    SUB_TITLE = "生物序列终端浏览器"
    DARK = is_dark_theme(get_theme_name())  # 根据主题自动切换

    CSS = build_browser_css(get_theme())

    BINDINGS: ClassVar[list] = [
        Binding("j", "scroll_down", "下移", show=True, priority=True),
        Binding("k", "scroll_up", "上移", show=True, priority=True),
        Binding("n", "next_seq", "下一条", show=True, priority=True),
        Binding("p", "prev_seq", "上一条", show=True, priority=True),
        Binding("space", "page_down", "翻页", show=True, priority=True),
        Binding("b", "page_up", "回翻", show=True, priority=True),
        Binding("g", "goto_top", "顶部", show=False, priority=True),
        Binding("G", "goto_bottom", "底部", show=False, priority=True),
        Binding("/", "search", "搜索", show=True, priority=True),
        Binding("colon", "goto_seq", "跳转", show=True, priority=True),
        Binding("e", "export_seq", "导出", show=True, priority=True),
        Binding("y", "copy_seq", "复制", show=True, priority=True),
        Binding("c", "copy_range", "范围复制", show=True, priority=True),
        Binding("B", "back", "返回选择", show=True, priority=True),
        Binding("question_mark", "help", "帮助", show=True, priority=True),
        Binding("q", "quit", "退出", show=True, priority=True),
        Binding("ctrl+c", "quit", "退出", show=False, priority=True),
        Binding("ctrl+q", "quit", "退出", show=False, priority=True),
    ]

    def __init__(self, filepaths: list[Path], source_dir: Path | None = None):
        super().__init__()
        self.file_tabs: list[FileTab] = []
        self.active_tab = 0
        self._command_mode: str = ""  # "search" or "goto"
        self.source_dir = source_dir  # 来源目录（非 None 时 B 键可返回文件选择器）
        self._scan_tasks: list[tuple[Path, FileFormat, int]] = []  # 待后台扫描的文件

        # 快速扫描前 500 条（首屏快速呈现），剩余加入后台扫描队列
        QUICK_LIMIT = 500
        for fp in filepaths:
            fmt = self._detect_format(fp)
            seqs, is_done = self._scan_file_quick(fp, fmt, limit=QUICK_LIMIT)
            self.file_tabs.append(FileTab(fp, seqs, fmt))
            if not is_done:
                self._scan_tasks.append((fp, fmt, len(seqs)))

    @staticmethod
    def _detect_format(filepath: Path) -> FileFormat:
        """根据文件后缀或首字符自动检测格式（支持 gzip）。"""
        suffix = filepath.suffix.lower()
        if suffix == ".gz":
            suffix = "." + filepath.stem.rsplit(".", 1)[-1].lower() if "." in filepath.stem else ""
        if suffix in (".fastq", ".fq"):
            return FileFormat.FASTQ
        if suffix in (".fasta", ".fa", ".fna", ".faa"):
            return FileFormat.FASTA
        # 后缀不明确时读首字符（透明处理 gzip）
        with _open_seq_file(filepath, "rb") as f:
            first_byte = f.read(1)
        return FileFormat.FASTQ if first_byte == b"@" else FileFormat.FASTA

    @staticmethod
    def _scan_file_quick(filepath: Path, fmt: FileFormat, limit: int = 500) -> tuple[list[SequenceInfo], bool]:
        """快速扫描文件前 N 条序列（二进制模式，支持 gzip）。返回 (sequences, is_done)。"""
        sequences: list[SequenceInfo] = []
        for seq_info in _iter_sequences(filepath, fmt):
            sequences.append(seq_info)
            if len(sequences) >= limit:
                return sequences, False
        return sequences, True

    @staticmethod
    def _scan_file(filepath: Path, fmt: FileFormat) -> list[SequenceInfo]:
        """扫描文件建立索引（二进制模式，FASTA 不计算长度，支持 gzip）。"""
        return list(_iter_sequences(filepath, fmt))

    @property
    def current_tab(self) -> FileTab:
        return self.file_tabs[self.active_tab]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            if len(self.file_tabs) == 1:
                # 单文件：不用标签页
                tab = self.file_tabs[0]
                yield Horizontal(
                    SequenceList(tab.sequences, id="sidebar-0", classes="sidebar"),
                    SequenceView(tab.filepath, file_format=tab.file_format, id="main-0", classes="main-view"),
                )
            else:
                # 多文件：标签页
                with TabbedContent(id="tabs"):
                    for i, tab in enumerate(self.file_tabs):
                        with TabPane(tab.filepath.name, id=f"tab-{i}"):
                            yield Horizontal(
                                SequenceList(tab.sequences, id=f"sidebar-{i}", classes="sidebar"),
                                SequenceView(tab.filepath, file_format=tab.file_format, id=f"main-{i}", classes="main-view"),
                            )

        yield StatusBar(id="statusbar")
        yield Footer()

    def on_mount(self):
        """启动后加载第一个文件的第一条序列，并设置焦点。"""
        self._apply_sidebar_width()
        self._load_current()
        # 显式设置焦点到侧栏，确保 Footer 显示完整快捷键
        self._get_sidebar().focus()
        # 后台继续扫描剩余序列
        if self._scan_tasks:
            self.run_worker(self._background_scan(), exclusive=False)

    async def _background_scan(self):
        """后台扫描剩余序列，每批 200 条更新一次侧栏。"""
        BATCH = 200
        for fp, fmt, start_idx in self._scan_tasks:
            tab_idx = next(i for i, t in enumerate(self.file_tabs) if t.filepath == fp)
            tab = self.file_tabs[tab_idx]
            batch: list[SequenceInfo] = []

            for seq_info in _iter_sequences(fp, fmt, start_idx=start_idx):
                tab.sequences.append(seq_info)
                batch.append(seq_info)
                if len(batch) >= BATCH:
                    self._update_sidebar(tab_idx, batch)
                    batch = []

            if batch:
                self._update_sidebar(tab_idx, batch)

        self._scan_tasks.clear()

    def _update_sidebar(self, tab_idx: int, new_seqs: list[SequenceInfo]):
        """更新侧栏（从 worker 回调到 UI 线程）。"""
        try:
            sidebar = self.query_one(f"#sidebar-{tab_idx}", SequenceList)
            sidebar.append_sequences(new_seqs)
        except Exception:  # noqa: BLE001, S110
            pass  # 侧栏可能已被卸载（标签页切换时），静默忽略

    def _apply_sidebar_width(self):
        """从配置应用侧栏宽度。"""
        width = config.get("browser.sidebar_width", 32)
        for sidebar in self.query(SequenceList):
            sidebar.styles.width = width

    def _get_main_view(self) -> SequenceView:
        return self.query_one(f"#main-{self.active_tab}", SequenceView)

    def _get_sidebar(self) -> SequenceList:
        return self.query_one(f"#sidebar-{self.active_tab}", SequenceList)

    def _load_current(self):
        tab = self.current_tab
        if tab.sequences:
            main_view = self._get_main_view()
            main_view.load_sequence(tab.sequences[tab.current_index])
            self._update_status()

    def _update_status(self):
        tab = self.current_tab
        main_view = self._get_main_view()
        status = self.query_one("#statusbar", StatusBar)
        status.update_status(
            seq_index=tab.current_index,
            total_seqs=len(tab.sequences),
            view_offset=main_view.view_offset,
            total_lines=main_view._total_lines,
            seq_length=main_view._seq_length,
        )

    # ── 滚动 ──
    def action_scroll_down(self):
        step = config.get("browser.scroll_step", 5)
        self._get_main_view().scroll_content_down(step)
        self._update_status()

    def action_scroll_up(self):
        step = config.get("browser.scroll_step", 5)
        self._get_main_view().scroll_content_up(step)
        self._update_status()

    def action_page_down(self):
        mv = self._get_main_view()
        mv.scroll_content_down(mv.size.height if mv.size.height > 0 else 30)
        self._update_status()

    def action_page_up(self):
        mv = self._get_main_view()
        mv.scroll_content_up(mv.size.height if mv.size.height > 0 else 30)
        self._update_status()

    def action_goto_top(self):
        mv = self._get_main_view()
        mv.view_offset = 0
        mv._update_display()
        self._update_status()

    def action_goto_bottom(self):
        mv = self._get_main_view()
        mv.view_offset = max(0, mv._total_lines - 1)
        mv._update_display()
        self._update_status()

    # ── 序列切换 ──
    def action_next_seq(self):
        tab = self.current_tab
        if tab.current_index < len(tab.sequences) - 1:
            tab.current_index += 1
            self._select_and_load(tab.current_index)

    def action_prev_seq(self):
        tab = self.current_tab
        if tab.current_index > 0:
            tab.current_index -= 1
            self._select_and_load(tab.current_index)

    def _select_and_load(self, index: int) -> None:
        tab = self.current_tab
        sidebar = self._get_sidebar()
        sidebar.highlighted = index
        main_view = self._get_main_view()
        main_view.load_sequence(tab.sequences[index])
        self._update_status()

    def on_option_list_option_selected(self, message: OptionList.OptionSelected) -> None:
        # 从消息发送者（被点击的侧栏）确定标签页，不依赖可能过期的 active_tab
        sender = message.control
        sender_id = sender.id or ""
        if sender_id.startswith("sidebar-"):
            tab_idx = int(sender_id[len("sidebar-"):])
            self.active_tab = tab_idx  # 同步 active_tab

        option_id = message.option.id or ""
        if option_id.startswith("seq-"):
            idx = int(option_id[4:])
            tab = self.current_tab
            if 0 <= idx < len(tab.sequences):
                tab.current_index = idx
                self._get_main_view().load_sequence(tab.sequences[idx])
                self._update_status()

    # ── 命令栏（动态挂载/卸载）──
    def _get_command_bar(self) -> "CommandBar | None":
        bars = self.query("#command-bar")
        return bars.first() if bars else None

    def _remove_command_bar(self) -> None:
        bar = self._get_command_bar()
        if bar is not None:
            bar.remove()

    async def _show_command_bar(self, mode: str, placeholder: str) -> None:
        """挂载命令栏到 #body 顶部并聚焦。"""
        self._command_mode = mode
        self._remove_command_bar()
        bar = CommandBar(id="command-bar", mode=mode)
        bar.placeholder = placeholder
        body = self.query_one("#body")
        if body.children:
            await body.mount(bar, before=body.children[0])
        else:
            await body.mount(bar)
        bar.focus()

    # ── 搜索 ──
    async def action_search(self):
        await self._show_command_bar("search", "输入关键词搜索序列名称... (Enter 确认, Esc 取消)")

    async def action_goto_seq(self):
        await self._show_command_bar("goto", "输入序列编号 (1-based)... (Enter 确认, Esc 取消)")

    async def action_copy_range(self):
        await self._show_command_bar("range", "输入位置范围 (如 100-200)... (Enter 复制, Esc 取消)")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """命令栏回车确认。"""
        self._remove_command_bar()
        self._get_sidebar().focus()
        value = event.value.strip()
        if not value:
            return

        tab = self.current_tab
        if self._command_mode == "search":
            # 从当前位置向后搜索
            keyword = value.lower()
            start = tab.current_index + 1
            n = len(tab.sequences)
            for offset in range(n):
                i = (start + offset) % n
                if keyword in tab.sequences[i].header.lower():
                    tab.current_index = i
                    self._select_and_load(i)
                    self.notify(f"找到: {tab.sequences[i].header[:50]}", title="搜索")
                    return
            self.notify(f"未找到匹配 \"{value}\"", title="搜索", severity="warning")

        elif self._command_mode == "goto":
            try:
                idx = int(value) - 1  # 用户输入 1-based
                if 0 <= idx < len(tab.sequences):
                    tab.current_index = idx
                    self._select_and_load(idx)
                    self.notify(f"跳转到序列 {idx + 1}", title="Goto")
                else:
                    self.notify(f"编号超出范围 (1-{len(tab.sequences)})", title="Goto", severity="warning")
            except ValueError:
                self.notify("请输入有效数字", title="Goto", severity="error")

        elif self._command_mode == "range":
            self._handle_range_copy(value)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Esc 取消由 key handler 处理。"""

    def on_key(self, event) -> None:
        """全局按键拦截：命令栏 Esc 关闭 + q 强制退出。"""
        bar = self._get_command_bar()

        # 命令栏存在时，Esc 关闭，其他键交给 Input 处理
        if bar is not None:
            if event.key == "escape":
                self._remove_command_bar()
                self._get_sidebar().focus()
                event.stop()
            return

        # 命令栏不存在时，q 强制退出（兜底，防止 widget 拦截）
        if event.key == "q":
            self.exit()
            event.stop()

    # ── 导出 & 复制 ──
    def _copy_to_clipboard(self, text: str) -> bool:
        """复制文本到剪贴板，成功返回 True。

        策略：系统工具优先（反馈可靠），失败后回退 OSC 52（适用于无图形界面/SSH 场景）。
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
        except OSError:
            pass
        # 回退: OSC 52 —— 通过终端转义序列写入本地剪贴板（需终端支持，SSH 下同样有效）
        try:
            self.copy_to_clipboard(text)
            return True
        except Exception:  # noqa: BLE001
            return False  # 剪贴板不可用

    def _handle_range_copy(self, value: str):
        """解析位置范围并复制对应序列片段。"""
        main_view = self._get_main_view()
        seq_len = main_view._seq_length
        if not seq_len:
            self.notify("当前没有序列", title="范围复制", severity="warning")
            return

        # 支持 "start-end" 或 "start..end" 或单个 "pos"
        value = value.replace("..", "-").strip()
        try:
            if "-" in value:
                start_s, end_s = value.split("-", 1)
                start, end = int(start_s), int(end_s)
            else:
                start = end = int(value)
        except ValueError:
            self.notify("格式应为: 100-200", title="范围复制", severity="error")
            return

        # 边界检查 (1-based, 含两端)
        if start < 1 or end > seq_len or start > end:
            self.notify(f"范围超出序列长度 (1-{seq_len})", title="范围复制", severity="warning")
            return

        fragment = main_view._load_chunk(start - 1, end)
        if self._copy_to_clipboard(fragment):
            self.notify(f"已复制 {start}-{end} ({len(fragment)} bp) 到剪贴板", title="范围复制")
        else:
            self.notify("剪贴板不可用", title="范围复制", severity="warning")

    def _build_seq_text(self) -> str:
        """构建当前序列的纯文本（FASTA/FASTQ 格式）。小序列用，大序列用流式导出。"""
        tab = self.current_tab
        main_view = self._get_main_view()
        seq_info = tab.sequences[tab.current_index]
        if tab.file_format == FileFormat.FASTQ:
            return f"@{seq_info.header}\n{main_view._seq}\n+\n{main_view._quality}\n"
        else:
            if not main_view._is_large:
                # 普通序列：直接构建
                lines = [f">{seq_info.header}"]
                seq = main_view._seq
                for i in range(0, len(seq), 60):
                    lines.append(seq[i:i + 60])
                return "\n".join(lines) + "\n"
            else:
                # 大序列：分块构建（避免一次性加载全部）
                lines = [f">{seq_info.header}"]
                seq_len = main_view._seq_length
                CHUNK = 6000  # 每次加载 6000bp
                for i in range(0, seq_len, CHUNK):
                    chunk = main_view._load_chunk(i, min(i + CHUNK, seq_len))
                    for j in range(0, len(chunk), 60):
                        lines.append(chunk[j:j + 60])
                return "\n".join(lines) + "\n"

    def action_export_seq(self):
        tab = self.current_tab
        seq_info = tab.sequences[tab.current_index]

        seq_id = seq_info.header.split()[0].replace("/", "_").replace("\\", "_")
        ext = ".fastq" if tab.file_format == FileFormat.FASTQ else ".fasta"
        out_path = Path(f"{seq_id}{ext}")

        with open(out_path, "w") as f:
            f.write(self._build_seq_text())

        self.notify(f"已导出: {out_path}", title="导出")

    def action_copy_seq(self):
        """复制当前序列到系统剪贴板。"""
        text = self._build_seq_text()
        if self._copy_to_clipboard(text):
            self.notify(f"已复制 {len(text)} 字符到剪贴板", title="复制")
        else:
            self.notify("剪贴板不可用，请用 e 导出到文件", title="复制", severity="warning")

    # ── 返回文件选择器 ──
    def action_back(self):
        """B 键：返回文件选择器（仅当从目录打开时可用）。"""
        if self.source_dir is None:
            self.notify("当前不是从目录打开，无法返回文件选择", title="返回", severity="warning")
            return
        # 以 "back" 结果退出，由 CLI 循环重新启动文件选择器
        self.exit(result="back")

    # ── 帮助 ──
    def action_help(self):
        self.push_screen(HelpScreen())

    # ── 标签页切换 ──
    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        tab_id = event.tab.id or ""
        if tab_id.startswith("tab-"):
            self.active_tab = int(tab_id[4:])
            self._load_current()