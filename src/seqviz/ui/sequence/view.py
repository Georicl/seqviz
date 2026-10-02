"""序列可见区域的布局与渲染。"""

from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from seqviz import config
from seqviz.core.formats import FileFormat
from seqviz.core.index import SequenceInfo
from seqviz.core.seq_type import SeqType
from seqviz.core.sequence_reader import SequenceReader
from seqviz.core.stats import quality_stats
from seqviz.ui.renderer import colorize_quality, colorize_sequence, quality_bar


class SequenceView(Static):
    """只生成可见行；文件读取及缓存由 SequenceReader 管理。"""

    def __init__(
        self, filepath: Path, file_format: FileFormat = FileFormat.FASTA, **kwargs
    ):
        super().__init__(**kwargs)
        self.reader = SequenceReader(filepath, file_format)
        self.view_offset = 0
        self._config_wrap = max(1, int(config.get("browser.wrap_width", 60)))
        self.WRAP = self._config_wrap
        self.auto_wrap = config.get("browser.auto_wrap", True)
        self.show_line_numbers = config.get("browser.show_line_numbers", True)
        self.show_quality = config.get("browser.show_quality", True)
        self._header_lines: list[Text] = []
        self._total_lines = 0
        self._lines_per_chunk = 1

    def on_unmount(self):
        # Textual 先卸载子组件，文件句柄在组件自身的生命周期结束时关闭。
        self.reader.close()

    def load_sequence(self, seq_info: SequenceInfo, defer_metrics: bool = False):
        self.view_offset = 0
        self.WRAP = self._compute_wrap()
        self.reader.set_window_size(self.WRAP * (self.size.height or 30))
        self.reader.load_sequence(seq_info, defer_metrics=defer_metrics)
        self._lines_per_chunk = 2 if seq_info.has_quality and self.show_quality else 1

        # ── 生成统计信息行 ──
        type_label = "DNA" if self.reader.seq_type == SeqType.DNA else "Protein"
        type_icon = "[DNA]" if self.reader.seq_type == SeqType.DNA else "[Protein]"

        # GC 含量：大序列用前 10K 估算
        sample = (
            self.reader.sequence[:10000]
            if self.reader.is_large
            else self.reader.sequence
        )
        sample_upper = sample.upper()
        gc = (
            (sample_upper.count("G") + sample_upper.count("C")) / len(sample) * 100
            if sample
            else 0
        )

        seq_id = seq_info.header.split()[0] if seq_info.header else "unknown"
        desc = (
            seq_info.header[len(seq_id) :].strip()
            if len(seq_info.header) > len(seq_id)
            else ""
        )

        title_line = Text()
        title_line.append(f" {type_icon} ", style="bold")
        title_line.append(seq_id, style="bold cyan")
        if desc:
            title_line.append(f"  {desc[:60]}", style="dim")

        info_line = Text()
        info_line.append("   Length: ", style="dim")
        if self.reader.metrics_pending:
            info_line.append("索引中", style="bold green")
        elif self.reader.length > 0:
            info_line.append(f"{self.reader.length:,}", style="bold green")
        else:
            info_line.append("...", style="bold green")
        info_line.append(" bp   GC: ", style="dim")
        gc_note = "~" if self.reader.is_large else ""
        info_line.append(f"{gc_note}{gc:.1f}%", style="bold yellow")
        info_line.append("   Type: ", style="dim")
        info_line.append(type_label, style="bold magenta")

        header_lines = [title_line, info_line]

        # FASTQ 额外显示质量统计 + 质量分布条
        if self.reader.quality:
            qstats = quality_stats(self.reader.quality)
            q_line = Text()
            q_line.append("   Quality: ", style="dim")
            q_line.append(f"Q={qstats['mean']:.1f}", style="bold green")
            q_line.append(f"  (min={qstats['min']}, max={qstats['max']})", style="dim")
            q_line.append("  Q30: ", style="dim")
            q_line.append(f"{qstats['q30_pct']:.0%}", style="bold yellow")
            header_lines.append(q_line)

            bar_line = Text("   ", style="dim")
            bar_line.append(quality_bar(self.reader.quality, width=50))
            header_lines.append(bar_line)

        header_lines.append(Text("─" * 70, style="dim"))
        header_lines.append(Text())
        self._header_lines = header_lines

        # 计算总行数
        self._recalc_total_lines()

        self._update_display()

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
            chunk_end = min(chunk_start + self.WRAP, self.reader.length)

            if chunk_start >= self.reader.length:
                return Text()

            if is_quality_line:
                colored_q = colorize_quality(self.reader.quality[chunk_start:chunk_end])
                line = self._make_prefix(None)
                line.append(colored_q)
                return line
            else:
                seq_chunk = self.reader.read_range(chunk_start, chunk_end)
                colored = colorize_sequence(seq_chunk, self.reader.seq_type)
                line = self._make_prefix(chunk_start + 1)
                line.append(colored)
                return line
        else:
            # FASTA 或关闭质量值的 FASTQ
            chunk_start = body_idx * self.WRAP
            chunk_end = min(chunk_start + self.WRAP, self.reader.length)

            if chunk_start >= self.reader.length:
                return Text()

            seq_chunk = self.reader.read_range(chunk_start, chunk_end)
            colored = colorize_sequence(seq_chunk, self.reader.seq_type)
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
        chunk_count = (self.reader.length + self.WRAP - 1) // self.WRAP
        self._total_lines = (
            len(self._header_lines) + chunk_count * self._lines_per_chunk
        )

    def _update_display(self):
        """只渲染当前可见区域的行。"""
        height = self.size.height if self.size.height > 0 else 30
        self.reader.set_window_size(self.WRAP * height)
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
        if self.reader.sequence or self._header_lines:
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
