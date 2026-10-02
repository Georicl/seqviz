"""序列浏览器的列表、帮助面板和命令栏。"""

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from seqviz.core.index import SequenceInfo


class SequenceList(OptionList):
    """左侧序列列表（基于 OptionList，内部虚拟化，支持大量序列）。

    注意：本组件不持有序列数据，仅负责渲染 Option。
    序列数据的唯一权威来源是 FileTab.sequences，由 FastaBrowser 统一追加，
    避免侧栏与标签页各持一份 list 导致重复追加/索引错位。
    """

    def __init__(self, sequences: list[SequenceInfo], **kwargs):
        super().__init__(**kwargs)
        self.add_options(
            [
                Option(Text(self._make_label(seq)), id=f"seq-{seq.index}")
                for seq in sequences
            ]
        )

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

        记录数据由 FileTab.sequences 持有；批量添加可避免逐项触发布局。
        """
        self.add_options(
            [
                Option(Text(self._make_label(seq)), id=f"seq-{seq.index}")
                for seq in new_seqs
            ]
        )


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

    BINDINGS: ClassVar[list] = [
        Binding("escape", "dismiss", "关闭", show=False),
        Binding("q", "dismiss", "关闭", show=False),
    ]

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

    def update_status(
        self,
        seq_index: int,
        total_seqs: int,
        view_offset: int,
        total_lines: int,
        seq_length: int,
        metrics_pending: bool = False,
    ):
        bar = Text()
        bar.append(" ", style="bold")
        bar.append(f"序列 {seq_index + 1}/{total_seqs}", style="bold cyan")
        bar.append("  │  ", style="dim")
        bar.append(f"行 {view_offset + 1}/{total_lines}", style="green")
        bar.append("  │  ", style="dim")
        length_label = "索引中" if metrics_pending else f"{seq_length:,} bp"
        bar.append(f"序列长度 {length_label}", style="yellow")

        # 进度百分比
        pct = (view_offset / max(total_lines, 1)) * 100
        bar.append("  │  ", style="dim")
        bar.append(
            "索引中…" if metrics_pending else f"{pct:.0f}%", style="bold magenta"
        )

        self.update(bar)
