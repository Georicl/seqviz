"""FASTA/FASTQ 浏览器：导航、后台索引和交互命令。"""

import re
from collections.abc import Generator
from functools import partial
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, OptionList, TabbedContent, TabPane

from seqviz import clipboard, config
from seqviz.core.formats import FileFormat, detect_format, open_seq_file
from seqviz.core.index import SequenceInfo, iter_sequences, scan_file_quick
from seqviz.core.sequence_reader import SequenceReader
from seqviz.ui.sequence.view import SequenceView
from seqviz.ui.sequence.widgets import CommandBar, HelpScreen, SequenceList, StatusBar
from seqviz.ui.theme import build_browser_css, get_theme, get_theme_name, is_dark_theme


class FileTab:
    """单个文件的标签页数据。"""

    def __init__(
        self, filepath: Path, sequences: list[SequenceInfo], file_format: FileFormat
    ):
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
    DEFER_METRICS_FILE_BYTES = 32 * 1024 * 1024

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
        self._scan_tasks: list[
            tuple[int, Path, FileFormat, int]
        ] = []  # 待后台扫描的 (标签页索引, 文件, 格式, 起始位置)
        self._scan_cancelled = False  # 退出时置 True，后台扫描线程尽早结束
        self._metrics_generation = 0

        # 快速扫描前 500 条（首屏快速呈现），剩余加入后台扫描队列
        QUICK_LIMIT = 500
        for fp in filepaths:
            fmt = detect_format(fp)
            seqs, is_done = scan_file_quick(fp, fmt, limit=QUICK_LIMIT)
            self.file_tabs.append(FileTab(fp, seqs, fmt))
            if not is_done:
                # 直接记录标签页索引：同一路径可打开多次（如目录展开+显式参数），
                # 按路径反查会错配到首个同名标签页导致数据污染/缺失
                self._scan_tasks.append((len(self.file_tabs) - 1, fp, fmt, len(seqs)))

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
                    SequenceView(
                        tab.filepath,
                        file_format=tab.file_format,
                        id="main-0",
                        classes="main-view",
                    ),
                )
            else:
                # 多文件：标签页
                with TabbedContent(id="tabs"):
                    for i, tab in enumerate(self.file_tabs):
                        with TabPane(tab.filepath.name, id=f"tab-{i}"):
                            yield Horizontal(
                                SequenceList(
                                    tab.sequences, id=f"sidebar-{i}", classes="sidebar"
                                ),
                                SequenceView(
                                    tab.filepath,
                                    file_format=tab.file_format,
                                    id=f"main-{i}",
                                    classes="main-view",
                                ),
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
        """应用退出时置取消标志，通知后台扫描线程尽早退出。

        文件句柄关闭由 SequenceView.on_unmount 在组件自身卸载时完成
        """
        self._scan_cancelled = True

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

            try:
                for seq_info in iter_sequences(
                    fp,
                    fmt,
                    start_idx=start_idx,
                    cancelled=lambda: self._scan_cancelled,
                ):
                    if self._scan_cancelled:
                        break
                    batch.append(seq_info)
                    if len(batch) >= BATCH:
                        self._apply_batch_safe(tab_idx, batch)
                        batch = []
            except (ValueError, OSError) as exc:
                if batch and not self._scan_cancelled:
                    self._apply_batch_safe(tab_idx, batch)
                    batch = []
                try:
                    self.call_from_thread(
                        self.notify, str(exc), title="扫描失败", severity="error"
                    )
                except RuntimeError:
                    pass
                continue

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
        was_empty = not tab.sequences
        tab.sequences.extend(new_seqs)
        sidebar = self.query_one(f"#sidebar-{tab_idx}", SequenceList)
        sidebar.append_sequences(new_seqs)
        if was_empty and tab_idx == self.active_tab and new_seqs:
            self._load_current()

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
        self._metrics_generation += 1
        if tab.sequences:
            generation = self._metrics_generation
            main_view = self._get_main_view()
            seq_info = tab.sequences[tab.current_index]
            defer_metrics = tab.file_format == FileFormat.FASTA and (
                tab.filepath.suffix.lower() == ".gz"
                or tab.filepath.stat().st_size >= self.DEFER_METRICS_FILE_BYTES
            )
            main_view.load_sequence(seq_info, defer_metrics=defer_metrics)
            self._update_status()
            if main_view.reader.metrics_pending:
                self.run_worker(
                    partial(
                        self._scan_metrics_worker,
                        self.active_tab,
                        seq_info,
                        main_view.reader.seq_data_offset,
                        generation,
                    ),
                    thread=True,
                    exclusive=False,
                )

    def _scan_metrics_worker(
        self, tab_idx: int, seq_info: SequenceInfo, seq_data_start: int, generation: int
    ):
        """后台建立大 FASTA 序列的精确长度与定位指标。"""
        try:
            with open_seq_file(self.file_tabs[tab_idx].filepath, "rb") as f:
                f.seek(seq_data_start)
                metrics = SequenceReader.scan_fasta_metrics(
                    f,
                    seq_data_start,
                    cancelled=lambda: (
                        self._scan_cancelled or generation != self._metrics_generation
                    ),
                )
        except StopIteration:
            return
        except OSError as exc:
            try:
                self.call_from_thread(
                    self.notify, f"序列索引失败: {exc}", severity="error"
                )
            except RuntimeError:
                pass
            return
        try:
            self.call_from_thread(
                self._apply_metrics, tab_idx, seq_info, metrics, generation
            )
        except RuntimeError:
            pass

    def _apply_metrics(
        self, tab_idx: int, seq_info: SequenceInfo, metrics: tuple, generation: int
    ):
        if self._scan_cancelled or generation != self._metrics_generation:
            return
        (
            seq_info.length,
            seq_info.uniform,
            seq_info.chars_per_line,
            seq_info.file_line_width,
            checkpoints,
        ) = metrics
        seq_info.checkpoints = checkpoints if not seq_info.uniform else None
        main_view = self.query_one(f"#main-{tab_idx}", SequenceView)
        if (
            main_view.reader.current_seq is seq_info
            and main_view.reader.metrics_pending
        ):
            old_offset = main_view.view_offset
            main_view.load_sequence(seq_info)
            main_view.view_offset = min(old_offset, max(0, main_view._total_lines - 1))
            main_view._update_display()
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
            seq_length=main_view.reader.length,
            metrics_pending=main_view.reader.metrics_pending,
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
        sidebar = self._get_sidebar()
        sidebar.highlighted = index
        self._load_current()

    def on_option_list_option_selected(
        self, message: OptionList.OptionSelected
    ) -> None:
        # 从消息发送者（被点击的侧栏）确定标签页，不依赖可能过期的 active_tab
        sender = message.control
        sender_id = sender.id or ""
        if sender_id.startswith("sidebar-"):
            tab_idx = int(sender_id[len("sidebar-") :])
            self.active_tab = tab_idx  # 同步 active_tab

        option_id = message.option.id or ""
        if option_id.startswith("seq-"):
            idx = int(option_id[4:])
            tab = self.current_tab
            if 0 <= idx < len(tab.sequences):
                tab.current_index = idx
                self._load_current()

    # ── 命令栏（动态挂载/卸载）──
    def _get_command_bar(self) -> CommandBar | None:
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
        await self._show_command_bar(
            "search", "输入关键词搜索序列名称... (Enter 确认, Esc 取消)"
        )

    async def action_goto_seq(self):
        await self._show_command_bar(
            "goto", "输入序列编号 (1-based)... (Enter 确认, Esc 取消)"
        )

    async def action_copy_range(self):
        await self._show_command_bar(
            "range", "输入位置范围 (如 100-200)... (Enter 复制, Esc 取消)"
        )

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
            self.notify(f'未找到匹配 "{value}"', title="搜索", severity="warning")

        elif self._command_mode == "goto":
            try:
                idx = int(value) - 1  # 用户输入 1-based
                if 0 <= idx < len(tab.sequences):
                    tab.current_index = idx
                    self._select_and_load(idx)
                    self.notify(f"跳转到序列 {idx + 1}", title="Goto")
                else:
                    self.notify(
                        f"编号超出范围 (1-{len(tab.sequences)})",
                        title="Goto",
                        severity="warning",
                    )
            except ValueError:
                self.notify("请输入有效数字", title="Goto", severity="error")

        elif self._command_mode == "range":
            self._handle_range_copy(value)

    def on_key(self, event) -> None:
        """Esc 关闭命令栏并将焦点还给序列列表。"""
        bar = self._get_command_bar()
        if bar is not None and event.key == "escape":
            self._remove_command_bar()
            self._get_sidebar().focus()
            event.stop()

    # ── 导出 & 复制 ──
    def _copy_to_clipboard(self, text: str) -> bool:
        """复制文本到剪贴板，成功返回 True（系统工具优先，失败回退 OSC 52）。

        实现见 clipboard.py，与 VcfBrowser 共用同一套回退策略。
        """
        return clipboard.copy_to_clipboard(text, self.copy_to_clipboard)

    def _handle_range_copy(self, value: str):
        """解析位置范围并复制对应序列片段。"""
        main_view = self._get_main_view()
        if main_view.reader.metrics_pending:
            self.notify("序列索引中，请稍候", title="范围复制", severity="warning")
            return
        seq_len = main_view.reader.length
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
            self.notify(
                f"范围超出序列长度 (1-{seq_len})", title="范围复制", severity="warning"
            )
            return

        fragment = main_view.reader.read_range(start - 1, end)
        if self._copy_to_clipboard(fragment):
            self.notify(
                f"已复制 {start}-{end} ({len(fragment)} bp) 到剪贴板", title="范围复制"
            )
        else:
            self.notify("剪贴板不可用", title="范围复制", severity="warning")

    def _iter_seq_text(self) -> Generator[str]:
        """流式生成当前序列的纯文本（FASTA/FASTQ 格式），逐块 yield，内存恒定。

        大序列不会一次性拼接整条字符串，导出时边生成边写入。
        """
        tab = self.current_tab
        main_view = self._get_main_view()
        seq_info = tab.sequences[tab.current_index]
        if tab.file_format == FileFormat.FASTQ:
            yield f"@{seq_info.header}\n{main_view.reader.sequence}\n+\n{main_view.reader.quality}\n"
            return

        yield f">{seq_info.header}\n"
        if not main_view.reader.is_large:
            seq = main_view.reader.sequence
            for i in range(0, len(seq), 60):
                yield seq[i : i + 60] + "\n"
        else:
            seq_len = main_view.reader.length
            CHUNK = 6000  # 每次加载 6000bp
            for i in range(0, seq_len, CHUNK):
                chunk = main_view.reader.read_range(i, min(i + CHUNK, seq_len))
                for j in range(0, len(chunk), 60):
                    yield chunk[j : j + 60] + "\n"

    def action_export_seq(self):
        tab = self.current_tab
        if not tab.sequences:
            self.notify("当前没有序列可导出", title="导出", severity="warning")
            return
        seq_info = tab.sequences[tab.current_index]
        if self._get_main_view().reader.metrics_pending:
            self.notify("序列索引中，请稍候", title="导出", severity="warning")
            return

        seq_id = seq_info.header.split()[0] if seq_info.header else "unknown"
        # 输入标题用于本地文件名时，替换平台不接受的字符。
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
        if main_view.reader.metrics_pending:
            self.notify("序列索引中，请稍候", title="复制", severity="warning")
            return
        # 剪贴板需要完整字符串；超大序列（>10Mbp）拼接开销大，提示改用导出
        if main_view.reader.is_large and main_view.reader.length > 10_000_000:
            self.notify(
                "序列过长，复制占用内存高，建议按 e 导出到文件",
                title="复制",
                severity="warning",
            )
            return
        text = "".join(self._iter_seq_text())
        if self._copy_to_clipboard(text):
            self.notify(f"已复制 {len(text)} 字符到剪贴板", title="复制")
        else:
            self.notify(
                "剪贴板不可用，请用 e 导出到文件", title="复制", severity="warning"
            )

    # ── 返回文件选择器 ──
    def action_back(self):
        """B 键：返回文件选择器（仅当从目录打开时可用）。"""
        if self.source_dir is None:
            self.notify(
                "当前不是从目录打开，无法返回文件选择", title="返回", severity="warning"
            )
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
        tabs = self.query_one(TabbedContent)
        # 手动加载与 TabActivated 只执行一次，避免重复启动指标扫描。
        with tabs.prevent(TabbedContent.TabActivated):
            tabs.active = f"tab-{next_idx}"
        self.active_tab = next_idx
        self._load_current()

    def action_quit_app(self):
        """q: 退出；帮助面板打开时先关闭面板而非退出应用。"""
        if isinstance(self.screen, HelpScreen):
            self.screen.dismiss()
            return
        self.exit()

    # ── 标签页切换 ──
    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        tab_id = event.tab.id or ""
        # ContentTab 的 id 带 "--content-tab-" 内部前缀，先归一化为 "tab-N"
        tab_id = tab_id.removeprefix("--content-tab-")
        if tab_id.startswith("tab-"):
            idx = int(tab_id[4:])
            if idx != self.active_tab:  # 键盘切换已手动处理，避免重复加载
                self.active_tab = idx
                self._load_current()
