import gzip
import re
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


def detect_format(filepath: Path) -> FileFormat:
    """根据文件后缀或首字符自动检测格式（支持 gzip，后缀大小写不敏感）。

    精确后缀匹配优先（.fastq/.fq → FASTQ；.fasta/.fa/.fna/.faa/.aa/.seq → FASTA），
    后缀不明确时读首字符判定（'@' → FASTQ，否则 FASTA）。为 browser 与
    file_browser 共用的单一入口，避免两套检测规则分歧。
    """
    suffix = filepath.suffix.lower()
    if suffix == ".gz":
        suffix = "." + filepath.stem.rsplit(".", 1)[-1].lower() if "." in filepath.stem else ""
    if suffix in (".fastq", ".fq"):
        return FileFormat.FASTQ
    if suffix in (".fasta", ".fa", ".fna", ".faa", ".aa", ".seq"):
        return FileFormat.FASTA
    # 后缀不明确时读首字符（透明处理 gzip）
    try:
        with _open_seq_file(filepath, "rb") as f:
            first_byte = f.read(1)
    except OSError:
        return FileFormat.FASTA
    return FileFormat.FASTQ if first_byte == b"@" else FileFormat.FASTA


class SequenceInfo:
    """存储一条序列的元信息（不加载序列本身）。

    uniform / chars_per_line / file_line_width / checkpoints 为大序列分块加载
    指标缓存，首次加载时懒填充，避免重复全量扫描。
    """
    __slots__ = (
        "chars_per_line",
        "checkpoints",
        "file_line_width",
        "has_quality",
        "header",
        "index",
        "length",
        "offset",
        "uniform",
    )

    def __init__(self, index: int, header: str, offset: int, length: int = -1, has_quality: bool = False):
        self.index = index
        self.header = header
        self.offset = offset        # 文件中的字节偏移量（用于快速定位）
        self.length = length        # -1 表示未知（懒计算）
        self.has_quality = has_quality  # FASTQ 记录有质量值
        self.uniform = None         # None=未知；True/False=行宽是否恒定（仅大序列使用）
        self.chars_per_line = 0     # 每行碱基数（行宽恒定时有效）
        self.file_line_width = 0    # 每行字节数（含换行符，行宽恒定时有效）
        self.checkpoints = None     # [(碱基位置, 文件偏移)]，仅非等宽大序列使用


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
                if not header_line.strip():
                    continue  # 跳过空行（尾部空行/空行分隔），避免产生幻影记录
                seq_line = f.readline()
                offset += len(seq_line)
                plus_line = f.readline()  # + 行
                offset += len(plus_line)
                quality_line = f.readline()  # quality 行
                offset += len(quality_line)
                if idx >= start_idx:
                    header = header_line.strip()[1:].decode(errors="replace")
                    yield SequenceInfo(idx, header, record_offset, len(seq_line.strip()), has_quality=True)
                idx += 1
    else:
        with _open_seq_file(filepath, "rb") as f:
            idx = 0
            offset = 0
            for raw_line in f:
                if raw_line.startswith(b">"):
                    if idx >= start_idx:
                        # errors="replace"：宽容非 UTF-8 编码的 header（遗留 latin-1/GBK 文件）
                        yield SequenceInfo(idx, raw_line[1:].strip().decode(errors="replace"), offset)
                    idx += 1
                offset += len(raw_line)


class SequenceList(OptionList):
    """左侧序列列表（基于 OptionList，内部虚拟化，支持大量序列）。

    注意：本组件不持有序列数据，仅负责渲染 Option。
    序列数据的唯一权威来源是 FileTab.sequences，由 FastaBrowser 统一追加，
    避免侧栏与标签页各持一份 list 导致重复追加/索引错位。
    """

    def __init__(self, sequences: list[SequenceInfo], **kwargs):
        super().__init__(**kwargs)
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
        """为新扫描到的序列追加 Option（后台扫描用）。

        只加 Option，不追加数据 list——数据由 FileTab.sequences 统一持有。
        """
        for seq in new_seqs:
            self.add_option(Option(self._make_label(seq), id=f"seq-{seq.index}"))


class SequenceView(Static):
    """右侧序列详情显示区（按需渲染，只生成可见行）。"""

    # 超过此阈值的 FASTA 序列使用分块加载（1Mbp）
    LARGE_SEQ_THRESHOLD = 1_000_000
    # 非等宽行宽大序列的 checkpoint 间隔（每 1Mbp 记录一个文件偏移，用于快速定位）
    CHECKPOINT_INTERVAL = 1_000_000

    def __init__(self, filepath: Path, file_format: FileFormat = FileFormat.FASTA, **kwargs):
        super().__init__(**kwargs)
        self.filepath = filepath
        self.file_format = file_format
        self.view_offset = 0
        self.current_seq: SequenceInfo | None = None
        # 从配置加载显示参数
        self._config_wrap = max(1, int(config.get("browser.wrap_width", 60)))  # 下限 1，避免除零
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
        self._uniform_lines: bool = True  # 行宽是否恒定（可变行宽需走 checkpoint 回退）
        self._checkpoints: list[tuple[int, int]] | None = None  # [(碱基位置, 文件偏移)] 仅非等宽时用
        # 持久文件句柄（避免频繁 open/close）
        self._fh: IO | None = None

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
        """用 offset 直接 seek 到目标位置。大序列分块加载。

        未压缩文件为 O(1) 定位；gzip 文件无块索引，seek 需解压中间数据，
        随机跳转为 O(文件大小)，仅适合顺序浏览。
        """
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

            # 估算序列长度（-1 表示未知）
            est_length = seq_info.length if seq_info.length >= 0 else -1
            is_large = est_length > self.LARGE_SEQ_THRESHOLD

            # 读取序列：
            # - 已知大序列（缓存过长度）：只读 10K 样本用于类型检测，避免整条读入内存；
            # - 未知/小序列：读到阈值或 EOF，以判定是否为大序列（小序列需全量保留）。
            seq_parts: list[str] = []
            total_read = 0
            if is_large:
                while total_read < 10_000:
                    raw_line = f.readline()
                    if not raw_line or raw_line.startswith(b">"):
                        break
                    stripped = raw_line.strip().decode()
                    seq_parts.append(stripped)
                    total_read += len(stripped)
            else:
                while True:
                    raw_line = f.readline()
                    if not raw_line or raw_line.startswith(b">"):
                        break
                    stripped = raw_line.strip().decode()
                    seq_parts.append(stripped)
                    total_read += len(stripped)
                    if total_read > self.LARGE_SEQ_THRESHOLD:
                        is_large = True  # 首次发现超过阈值
                        break

            if is_large:
                # ── 大序列：分块加载模式 ──
                self._is_large = True
                self._seq_data_offset = seq_data_start
                # 获取分块指标（长度/行宽均匀性/行宽/checkpoint）：优先用缓存，否则扫描
                if est_length > 0 and seq_info.uniform is not None:
                    self._seq_length = seq_info.length
                    self._uniform_lines = seq_info.uniform
                    self._chars_per_line = seq_info.chars_per_line
                    self._file_line_width = seq_info.file_line_width
                    self._checkpoints = seq_info.checkpoints
                else:
                    f.seek(seq_data_start)
                    (self._seq_length, self._uniform_lines,
                     self._chars_per_line, self._file_line_width,
                     checkpoints) = self._scan_fasta_metrics(f, seq_data_start)
                    # 非等宽行宽需要 checkpoint 索引才能正确定位
                    self._checkpoints = checkpoints if not self._uniform_lines else None
                    # 回写缓存，避免同一记录重复全量扫描
                    seq_info.length = self._seq_length
                    seq_info.uniform = self._uniform_lines
                    seq_info.chars_per_line = self._chars_per_line
                    seq_info.file_line_width = self._file_line_width
                    seq_info.checkpoints = self._checkpoints
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
    def _scan_fasta_metrics(f: IO, seq_data_start: int) -> tuple[int, bool, int, int, list[tuple[int, int]]]:
        """一次遍历扫描 FASTA 记录，返回分块加载所需的全部指标。

        Returns:
            (length, uniform, chars_per_line, file_line_width, checkpoints)
            - length: 序列准确总长（碱基数）
            - uniform: 所有序列行（除可能的末行短尾外）是否行宽恒定
            - chars_per_line: 首行碱基数（uniform 时用于等宽换算）
            - file_line_width: 首行字节数（含换行符，uniform 时用于等宽换算）
            - checkpoints: [(碱基位置, 文件偏移)]，每 CHECKPOINT_INTERVAL 一个，
              供非等宽行宽记录快速定位（uniform 时不使用）。

        uniform 判定宽容“末行短尾”（FASTA 最后一行不足行宽是合法的），
        但不宽容中间行宽变化、空行、行首空白或末行长于首行——
        这些都会导致等宽 offset 换算错位。
        """
        length = 0
        first_chars = -1
        first_bytes = -1
        pending_mismatch = False  # 上一行与首行不同（可能只是末行短尾，待下一行确认）
        nonuniform = False
        checkpoints: list[tuple[int, int]] = []
        next_checkpoint = 0
        cur_offset = seq_data_start
        while True:
            line_offset = cur_offset
            raw_line = f.readline()
            if not raw_line or raw_line.startswith(b">"):
                break
            stripped_len = len(raw_line.strip())
            line_bytes = len(raw_line)
            # 跨越碱基边界时记录 checkpoint（用于非等宽记录的分段定位）
            if length >= next_checkpoint:
                checkpoints.append((length, line_offset))
                next_checkpoint += SequenceView.CHECKPOINT_INTERVAL
            length += stripped_len
            cur_offset += line_bytes
            # 若上一行不匹配且其后还有行，则确认非等宽
            if pending_mismatch:
                nonuniform = True
                pending_mismatch = False
            if not nonuniform:
                if first_chars < 0:
                    first_chars, first_bytes = stripped_len, line_bytes
                elif stripped_len != first_chars or line_bytes != first_bytes:
                    pending_mismatch = True  # 暂记，若为末行则不算非等宽
                # 行首空白（空格/制表符等）会使碱基偏离行首字节，破坏等宽换算；
                # 行尾空白不偏移碱基位置，可安全容忍（首行也需检测）
                if stripped_len > 0 and raw_line.lstrip() != raw_line:
                    nonuniform = True
        # EOF 时仅允许“末行严格短于首行”作为合法短尾；
        # 末行更长会破坏等宽换算（start_line 越过末行导致 offset 错位）
        if pending_mismatch and first_chars >= 0 and stripped_len > first_chars:
            nonuniform = True
        f.seek(seq_data_start)  # 回到序列数据开头
        return length, (not nonuniform), first_chars, first_bytes, checkpoints

    def _load_chunk(self, seq_start: int, seq_end: int) -> str:
        """P1: 从文件加载序列的 [seq_start, seq_end) 区间（大序列用）。

        行宽恒定时用等宽换算直接 seek（O(1)）；
        行宽可变时借助 checkpoint 索引定位到最近边界后顺序读取（正确但较慢）。
        """
        if not self._is_large:
            return self._seq[seq_start:seq_end]

        needed = seq_end - seq_start
        f = self._get_fh()

        if self._uniform_lines:
            # ── 等宽行宽：直接换算文件偏移 ──
            chars_per_line = self._chars_per_line
            line_bytes = self._file_line_width
            if chars_per_line <= 0:
                chars_per_line = 80
            if line_bytes <= 0:
                line_bytes = chars_per_line + 1
            start_line = seq_start // chars_per_line
            start_col = seq_start % chars_per_line
            file_offset = self._seq_data_offset + start_line * line_bytes + start_col
            f.seek(file_offset)
            skip = 0
        else:
            # ── 可变行宽：定位到不超过 seq_start 的最近 checkpoint ──
            checkpoints = self._checkpoints or [(0, self._seq_data_offset)]
            # 二分查找最大的 base_pos <= seq_start
            lo, hi = 0, len(checkpoints) - 1
            idx = 0
            while lo <= hi:
                mid = (lo + hi) // 2
                if checkpoints[mid][0] <= seq_start:
                    idx = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            base_pos, file_offset = checkpoints[idx]
            f.seek(file_offset)
            skip = seq_start - base_pos  # 需跳过的碱基数

        result: list[str] = []
        total = 0
        while total < needed:
            raw_line = f.readline()
            if not raw_line or raw_line.startswith(b">"):
                break
            if skip > 0:
                # 整行都可跳过时无需 decode/切片（超长行避免重复分配内存）
                stripped_len = len(raw_line.strip())
                if stripped_len <= skip:
                    skip -= stripped_len
                    continue
            decoded = raw_line.strip().decode()
            if not decoded:
                continue  # 跳过空行
            if skip > 0:
                decoded = decoded[skip:]
                skip = 0
            take = needed - total
            result.append(decoded[:take])
            total += len(decoded[:take])
        return "".join(result)

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
            # 钳制偏移：窗口加宽后总行数减少，旧偏移可能越界导致渲染空白屏
            self.view_offset = min(self.view_offset, max(0, self._total_lines - 1))
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
            ("y", "复制当前序列"),
            ("c", "范围复制 (如 100-200)"),
            ("B", "返回文件选择器"),
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
    # DARK/CSS 在导入时从主题单例取值；切换主题后需新建实例（见 theme.reset_theme 说明）
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
        Binding("tab", "next_tab", "下一标签", show=True, priority=True),
        Binding("question_mark", "help", "帮助", show=True, priority=True),
        Binding("q", "quit_app", "退出", show=True, priority=True),
        Binding("ctrl+c", "quit", "退出", show=False, priority=True),
        Binding("ctrl+q", "quit", "退出", show=False, priority=True),
    ]

    def __init__(self, filepaths: list[Path], source_dir: Path | None = None):
        super().__init__()
        self.file_tabs: list[FileTab] = []
        self.active_tab = 0
        self._command_mode: str = ""  # "search" or "goto"
        self.source_dir = source_dir  # 来源目录（非 None 时 B 键可返回文件选择器）
        self._scan_tasks: list[tuple[int, Path, FileFormat, int]] = []  # 待后台扫描的 (标签页索引, 文件, 格式, 起始位置)
        self._scan_cancelled = False  # 退出时置 True，后台扫描线程尽早结束

        # 快速扫描前 500 条（首屏快速呈现），剩余加入后台扫描队列
        QUICK_LIMIT = 500
        for fp in filepaths:
            fmt = self._detect_format(fp)
            seqs, is_done = self._scan_file_quick(fp, fmt, limit=QUICK_LIMIT)
            self.file_tabs.append(FileTab(fp, seqs, fmt))
            if not is_done:
                # 直接记录标签页索引：同一路径可打开多次（如目录展开+显式参数），
                # 按路径反查会错配到首个同名标签页导致数据污染/缺失
                self._scan_tasks.append((len(self.file_tabs) - 1, fp, fmt, len(seqs)))

    @staticmethod
    def _detect_format(filepath: Path) -> FileFormat:
        """根据文件后缀或首字符自动检测格式（委托给模块级 detect_format）。"""
        return detect_format(filepath)

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
            # 状态栏 dock 在 body 内底部：位于内容之下、Footer 之上，
            # 避免与同样 dock: bottom 的 Footer 重叠遮挡
            yield StatusBar(id="statusbar")

        yield Footer()

    def on_mount(self):
        """启动后加载第一个文件的第一条序列，并设置焦点。"""
        self._apply_sidebar_width()
        self._load_current()
        # 显式设置焦点到侧栏，确保 Footer 显示完整快捷键
        self._get_sidebar().focus()
        # 后台继续扫描剩余序列（线程 worker，不阻塞事件循环）
        if self._scan_tasks:
            self.run_worker(self._background_scan, thread=True, exclusive=False)

    def on_unmount(self):
        """应用退出时置取消标志并关闭所有持久文件句柄，避免文件描述符泄露。

        后台扫描线程在每批之间检查取消标志后尽早退出，
        避免退出后继续占用 CPU/IO 或向已关闭的事件循环投递更新。
        """
        self._scan_cancelled = True
        try:
            for view in self.query(SequenceView):
                view.close()
        except Exception:  # noqa: BLE001, S110
            pass  # 应用启动期异常时 screen 栈可能不存在，避免掩盖真实错误

    def _background_scan(self):
        """后台扫描剩余序列（在独立线程中运行，避免阻塞 Textual 事件循环）。

        文件循环是同步 I/O，若直接跑在事件循环上会造成 UI 冻结；
        因此放入 thread worker，每批通过 call_from_thread 回 UI 线程更新。
        """
        BATCH = 200
        for tab_idx, fp, fmt, start_idx in self._scan_tasks:
            if self._scan_cancelled:
                break
            batch: list[SequenceInfo] = []

            for seq_info in _iter_sequences(fp, fmt, start_idx=start_idx):
                if self._scan_cancelled:
                    break
                batch.append(seq_info)
                if len(batch) >= BATCH:
                    self._apply_batch_safe(tab_idx, batch)
                    batch = []

            if batch and not self._scan_cancelled:
                self._apply_batch_safe(tab_idx, batch)

        self._scan_tasks.clear()

    def _apply_batch_safe(self, tab_idx: int, batch: list[SequenceInfo]):
        """回 UI 线程应用批次；应用已退出时事件循环已关闭，安全忽略投递失败。"""
        try:
            self.call_from_thread(self._apply_scan_batch, tab_idx, batch)
        except RuntimeError:
            pass  # App is not running：退出竞态窗口内的残留投递

    def _apply_scan_batch(self, tab_idx: int, new_seqs: list[SequenceInfo]):
        """在 UI 线程追加一批扫描结果（数据追加的唯一入口，避免重复）。

        先写入 FileTab.sequences（唯一数据源），再为侧栏补充 Option。
        """
        tab = self.file_tabs[tab_idx]
        tab.sequences.extend(new_seqs)
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
        except (OSError, subprocess.CalledProcessError):
            pass  # 工具缺失或异常退出（非 OSError），回退 OSC 52
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

    def _iter_seq_text(self) -> Generator[str, None, None]:
        """流式生成当前序列的纯文本（FASTA/FASTQ 格式），逐块 yield，内存恒定。

        大序列不会一次性拼接整条字符串，导出时边生成边写入。
        """
        tab = self.current_tab
        main_view = self._get_main_view()
        seq_info = tab.sequences[tab.current_index]
        if tab.file_format == FileFormat.FASTQ:
            yield f"@{seq_info.header}\n{main_view._seq}\n+\n{main_view._quality}\n"
            return

        yield f">{seq_info.header}\n"
        if not main_view._is_large:
            seq = main_view._seq
            for i in range(0, len(seq), 60):
                yield seq[i:i + 60] + "\n"
        else:
            seq_len = main_view._seq_length
            CHUNK = 6000  # 每次加载 6000bp
            for i in range(0, seq_len, CHUNK):
                chunk = main_view._load_chunk(i, min(i + CHUNK, seq_len))
                for j in range(0, len(chunk), 60):
                    yield chunk[j:j + 60] + "\n"

    def action_export_seq(self):
        tab = self.current_tab
        if not tab.sequences:
            self.notify("当前没有序列可导出", title="导出", severity="warning")
            return
        seq_info = tab.sequences[tab.current_index]

        seq_id = seq_info.header.split()[0] if seq_info.header else "unknown"
        # 净化跨平台非法文件名字符（原仅替换 / \，含 : * ? < > | 时 open 会抛 OSError）
        seq_id = re.sub(r'[\\/:*?"<>|]', "_", seq_id) or "unknown"
        ext = ".fastq" if tab.file_format == FileFormat.FASTQ else ".fasta"
        out_path = Path(f"{seq_id}{ext}")
        # 防静默覆盖：目标已存在时自动追加序号
        if out_path.exists():
            n = 1
            while Path(f"{seq_id}_{n}{ext}").exists():
                n += 1
            out_path = Path(f"{seq_id}_{n}{ext}")

        # 流式写入：边生成边写，内存占用与序列总长无关
        try:
            with open(out_path, "w") as f:
                f.writelines(self._iter_seq_text())
        except OSError as e:
            self.notify(f"导出失败: {e}", title="导出", severity="error")
            return

        self.notify(f"已导出: {out_path}", title="导出")

    def action_copy_seq(self):
        """复制当前序列到系统剪贴板。超大序列建议改用 e 导出。"""
        if not self.current_tab.sequences:
            self.notify("当前没有序列可复制", title="复制", severity="warning")
            return
        main_view = self._get_main_view()
        # 剪贴板需要完整字符串；超大序列（>10Mbp）拼接开销大，提示改用导出
        if main_view._is_large and main_view._seq_length > 10_000_000:
            self.notify("序列过长，复制占用内存高，建议按 e 导出到文件", title="复制", severity="warning")
            return
        text = "".join(self._iter_seq_text())
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

    def action_next_tab(self):
        """Tab: 切换到下一个文件标签页（多文件时）。"""
        # 命令栏或帮助面板激活时不切换（App 级 priority 绑定会穿透模态屏幕）
        if self._get_command_bar() is not None or isinstance(self.screen, HelpScreen):
            return
        if len(self.file_tabs) <= 1:
            return
        next_idx = (self.active_tab + 1) % len(self.file_tabs)
        try:
            tabs = self.query_one(TabbedContent)
            # 程序化设置 active 会投递 TabActivated；抑制事件，
            # 以本方法的手动更新为唯一加载路径（避免双重 load_sequence）
            with tabs.prevent(TabbedContent.TabActivated):
                tabs.active = f"tab-{next_idx}"
        except Exception:  # noqa: BLE001, S110
            pass
        self.active_tab = next_idx
        self._load_current()

    def action_quit_app(self):
        """q: 退出；帮助面板打开时先关闭面板而非退出应用。"""
        if isinstance(self.screen, HelpScreen):
            self.screen.dismiss()
            return
        self.exit()

    # ── 标签页切换 ──
    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        tab_id = event.tab.id or ""
        # ContentTab 的 id 带 "--content-tab-" 内部前缀，先归一化为 "tab-N"
        tab_id = tab_id.removeprefix("--content-tab-")
        if tab_id.startswith("tab-"):
            idx = int(tab_id[4:])
            if idx != self.active_tab:  # 键盘切换已手动处理，避免重复加载
                self.active_tab = idx
                self._load_current()