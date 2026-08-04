"""VCF 交互式浏览器 — 双栏：左变异列表 + 右详情/基因型矩阵。

设计文档: docs/superpowers/specs/2026-07-25-vcf-visualization-design.md
"""

import re
import subprocess
from functools import partial
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

from seqviz import theme as theme_mod
from seqviz.vcf import (
    Variant,
    VariantType,
    classify_variant,
    compute_stats,
    load_variant_detail,
    parse_genotype,
    scan_vcf,
    scan_vcf_resume,
)

_TYPE_SYMBOL = {
    VariantType.TRANSITION: ("●", "green"),
    VariantType.TRANSVERSION: ("●", "blue"),
    VariantType.INSERTION: ("◆", "yellow"),
    VariantType.DELETION: ("◆", "red"),
    VariantType.COMPLEX: ("◆", "magenta"),
}
_TYPE_LABEL = {
    VariantType.TRANSITION: "SNP 转换",
    VariantType.TRANSVERSION: "SNP 颠换",
    VariantType.INSERTION: "插入",
    VariantType.DELETION: "缺失",
    VariantType.COMPLEX: "复杂变异",
}
_GT_LABEL = {"0/0": "纯合参考", "0/1": "杂合", "1/0": "杂合", "1/1": "纯合变异"}
_GT_MATRIX_STYLE = {"0/0": "dim", "0/1": "yellow", "1/0": "yellow", "1/1": "bold red"}
_FILTER_CYCLE = ["全部", "PASS", "SNP", "InDel"]


def _chrom_sort_key(chrom: str):
    """数字感知的染色体排序键：chr2 < chr10，非数字段按字典序。"""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", chrom))


class VariantList(OptionList):
    """大列表窗口化下的滚轮语义修正。

    默认滚轮只在物化的 WINDOW 条缓冲内滚动视口（不移动选中项），
    与“选中项 = 浏览位置”的模型矛盾；改为滚轮直接移动位置，窗口随之平移。
    小列表（全量物化，有滚动条）保持原生滚动行为。
    """

    def scroll_down(self, animate: bool = True) -> None:
        app = self.app
        if isinstance(app, VcfBrowser) and len(app.view) > app.WINDOW:
            app._goto_abs(app._abs_index() + 3)
        else:
            super().scroll_down(animate)

    def scroll_up(self, animate: bool = True) -> None:
        app = self.app
        if isinstance(app, VcfBrowser) and len(app.view) > app.WINDOW:
            app._goto_abs(app._abs_index() - 3)
        else:
            super().scroll_up(animate)


class HelpScreen(ModalScreen):
    """帮助面板：显示所有快捷键。"""

    CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-panel {
        width: 62;
        height: auto;
        border: thick $accent;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("question_mark", "dismiss", "关闭"),
        Binding("escape", "dismiss", "关闭"),
        Binding("q", "dismiss", "关闭"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(id="help-panel")

    def on_mount(self):
        panel = self.query_one("#help-panel", Static)
        panel.border_title = "Seqviz VCF — 快捷键"
        text = Text()
        rows = [
            ("j / k", "上下移动"), ("n / p", "下/上一条变异"),
            ("Space / b", "翻页"), ("g / G", "顶部 / 底部"),
            ("/", "搜索 ID 或坐标"), ("f", "过滤循环 (全部/PASS/SNP/InDel)"),
            ("s", "排序切换 (位置/QUAL)"), ("t", "详情 ↔ 基因型矩阵"),
            ("i", "文件信息"), ("y", "复制当前 VCF 行"),
            ("?", "帮助"), ("q", "退出"),
        ]
        for key, desc in rows:
            text.append(f"{key:<14}", style="bold green")
            text.append(desc + "\n")
        panel.update(text)


class VcfBrowser(App):
    """VCF 变异浏览器。"""

    TITLE = "Seqviz — VCF"
    DARK = theme_mod.is_dark_theme(theme_mod.get_theme_name())
    CSS = theme_mod.build_vcf_browser_css(theme_mod.get_theme())

    BINDINGS = [
        Binding("j", "cursor_down", "下移", show=True, priority=True),
        Binding("k", "cursor_up", "上移", show=True, priority=True),
        Binding("n", "cursor_down", "下一条", show=False),
        Binding("p", "cursor_up", "上一条", show=False),
        Binding("space", "page_down", "下翻页", show=True),
        Binding("b", "page_up", "上翻页", show=True),
        Binding("g", "home", "顶部", show=True),
        Binding("G", "end", "底部", show=True),
        Binding("slash", "search", "搜索", show=True),
        Binding("f", "cycle_filter", "过滤", show=True),
        Binding("s", "toggle_sort", "排序", show=True),
        Binding("t", "toggle_view", "矩阵", show=True),
        Binding("i", "file_info", "信息", show=True),
        Binding("y", "copy_line", "复制", show=True),
        Binding("question_mark", "help", "帮助", show=True),
        Binding("q", "quit", "退出", show=True),
    ]

    # 列表窗口化虚拟化：OptionList 只物化当前窗口，避免大文件全量重建冻结 UI
    WINDOW = 400
    PAGE = 20

    def __init__(self, filepath: Path, scanned=None, initial=None):
        """scanned=(meta, variants, skipped) 全量结果；
        initial=(meta, variants, skipped, cont_offset) 快扫部分结果，cont_offset>=0 时后台续扫。"""
        super().__init__()
        self.filepath = filepath
        self._cont_offset = -1
        self.scanning = False
        if initial is not None:
            self.meta, self.variants, self.skipped, self._cont_offset = initial
            self.scanning = self._cont_offset >= 0
        elif scanned is not None:
            self.meta, self.variants, self.skipped = scanned
        else:
            self.meta, self.variants, self.skipped = scan_vcf(filepath)
        self._fh = None             # 详情回读复用句柄（二进制）
        self._order_dirty = False   # 后台扫描破坏坐标序时置位，下次过滤/排序前重建
        self._view_dirty = False    # 扫描中用户改过过滤/排序，完成后重建 view
        self._initial_count = 0     # 快扫初始条数（续扫对账基准）
        self.view: list[int] = list(range(len(self.variants)))  # 过滤/排序后的下标映射
        self._chrom_keys: dict[str, tuple] | None = None  # 数字感知染色体键缓存
        self._qual_order: list[int] | None = None         # 全局 QUAL 降序（首次 s 键懒计算）
        self._types: list[VariantType] | None = None      # 变异类型缓存（SNP/InDel 过滤时懒计算）
        self._stats_token = 0                             # 异步统计的版本号（防竞态）
        # 默认按位置排序：VCF 通常已按坐标排序（O(n) 校验快路径），否则全量排序一次并缓存。
        # 后续过滤在有序列表上做保序筛选，不再重复排序（5M 级免冻结的关键）。
        self._scan_sorted = self._check_scan_sorted()
        if self._scan_sorted:
            self._pos_order = list(self.view)
        else:
            self.view.sort(key=self._pos_key)
            self._pos_order = list(self.view)
        self._initial_count = len(self.variants)
        self._win_start = 0  # 当前窗口在 view 中的起始下标
        self.filter_mode = "全部"
        self.sort_mode = "位置"
        self.matrix_mode = False
        self._last_copied: str = ""  # 最后一次复制内容（测试用）

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield VariantList(id="variant-list")
            yield Static("", id="detail")
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self):
        self._refresh_list()
        self.query_one("#variant-list", OptionList).focus()
        if self.scanning:
            self.run_worker(self._background_scan_worker, thread=True, exclusive=False)

    def on_unmount(self):
        if self._fh is not None and not self._fh.closed:
            self._fh.close()
        self.scanning = False  # 通知后台扫描线程尽早退出

    # ── 后台续扫（启动即显） ──
    def _background_scan_worker(self):
        """后台线程：从快扫断点继续索引，按时间节流回 UI 线程增量追加。"""
        import time as _time

        def _dispatch(batch):
            if not self.scanning:
                raise StopIteration  # 应用已关闭，中断扫描
            try:
                self.call_from_thread(self._append_batch, batch)
            except RuntimeError:
                raise StopIteration
            _time.sleep(0.02)  # 让出 GIL，保证 UI 线程滚动流畅
        try:
            new_all, skipped_add = scan_vcf_resume(
                self.filepath, self._cont_offset, on_batch=_dispatch)
        except Exception:  # noqa: BLE001
            return
        try:
            self.call_from_thread(self._finish_scan, new_all, skipped_add)
        except RuntimeError:
            pass  # 应用已退出

    def _pos_ge(self, a: Variant, b: Variant) -> bool:
        """a 是否位于 b 同位或之后（坐标序判定）。"""
        ka, kb = self._chrom_key_of(a.chrom), self._chrom_key_of(b.chrom)
        return ka > kb or (ka == kb and a.pos >= b.pos)

    def _chrom_key_of(self, chrom: str):
        if self._chrom_keys is None:
            self._chrom_keys = {}
        k = self._chrom_keys.get(chrom)
        if k is None:
            k = self._chrom_keys[chrom] = _chrom_sort_key(chrom)
        return k

    def _extend_index(self, batch: list[Variant]):
        """纯数据层：追加索引并维护位置序/pos_order/view（不碰 UI 控件）。"""
        ok = self._scan_sorted and not self._order_dirty
        if ok and self.variants and not self._pos_ge(batch[0], self.variants[-1]):
            ok = False
        if ok:
            for x, y in zip(batch, batch[1:]):
                if not self._pos_ge(y, x):
                    ok = False
                    break
        start = len(self.variants)
        self.variants.extend(batch)
        new_idxs = list(range(start, len(self.variants)))
        if ok:
            self._pos_order.extend(new_idxs)
        else:
            self._order_dirty = True
        default_view = (self.filter_mode == "全部" and self.sort_mode == "位置" and not self._order_dirty)
        if default_view:
            self.view.extend(new_idxs)
        else:
            self._view_dirty = True
        return default_view

    def _extend_and_sync(self, batch: list[Variant]) -> bool:
        """追加索引数据，按需增量延展列表窗口。

        永不 clear 重建：clear_options 会重置滚动状态，导致用户视角周期性跳顶；
        仅当窗口贴着数据尾部且未填满时才 add_options 增量补充。
        """
        ol = self.query_one("#variant-list", OptionList)
        window_at_tail = self._win_start + ol.option_count >= len(self.view)
        default_view = self._extend_index(batch)
        if default_view and window_at_tail and ol.option_count < self.WINDOW:
            start_new = len(self.view) - len(batch)
            room = self.WINDOW - ol.option_count
            ol.add_options([
                self._make_option(self.variants[i])
                for i in range(start_new, min(start_new + room, len(self.view)))
            ])
        return default_view

    def _append_batch(self, batch: list[Variant]):
        """UI 线程：追加一批索引（增量，不打断浏览）。"""
        if not self.scanning:
            return
        self._extend_and_sync(batch)
        self._update_status_bar()
        self._sync_position_indicator()

    def _finish_scan(self, new_all: list[Variant], skipped_add: int):
        """扫描完成：用全量结果对账补齐（节流回调可能漏尾），刷新视图。"""
        self.scanning = False
        self.skipped += skipped_add
        appended = len(self.variants) - self._initial_count
        if appended < len(new_all):
            self._extend_and_sync(new_all[appended:])
        if self._view_dirty or self._order_dirty:
            self._apply_filter_sort()
        else:
            self._update_status_bar()
        self._sync_scrollbar()
        self._sync_position_indicator()
        self.notify(f"扫描完成，共 {len(self.variants):,} 条变异", title="VCF")

    def _sync_scrollbar(self):
        """滚动条仅在列表全量物化（≤WINDOW 条）时显示。

        大列表只物化窗口，滚动条会虚假地暗示“拖到底 = 全部数据末尾”
        （实际只能到 400 条缓冲底部），因此隐藏；改用位置指示器 + G/g 跳转。
        """
        ol = self.query_one("#variant-list", OptionList)
        ol.show_scrollbar = len(self.view) <= self.WINDOW

    def _sync_position_indicator(self):
        """副标题位置指示器：当前行 / 总行数（含扫描中增长的总量）。"""
        if self.view:
            self.sub_title = f"{self._abs_index() + 1:,} / {len(self.view):,}"
        else:
            self.sub_title = "0 / 0"

    def _detail_fh(self):
        """详情回读复用句柄（避免每次导航 open/close）。"""
        if self._fh is None or self._fh.closed:
            self._fh = open(self.filepath, "rb")
        return self._fh

    # ── 排序/过滤基础设施 ──
    def _check_scan_sorted(self) -> bool:
        """O(n) 校验扫描顺序是否已按（数字感知染色体, 坐标）有序（VCF 常态）。"""
        key_cache: dict[str, tuple] = {}
        prev_key = None
        prev_pos = -1
        for v in self.variants:
            ck = key_cache.get(v.chrom)
            if ck is None:
                ck = key_cache[v.chrom] = _chrom_sort_key(v.chrom)
            if prev_key is not None and (ck < prev_key or (ck == prev_key and v.pos < prev_pos)):
                return False
            prev_key, prev_pos = ck, v.pos
        self._chrom_keys = key_cache
        return True

    def _pos_key(self, i: int):
        """位置排序键（染色体键缓存，避免重复正则）。"""
        if self._chrom_keys is None:
            self._chrom_keys = {c: _chrom_sort_key(c) for c in {v.chrom for v in self.variants}}
        v = self.variants[i]
        return (self._chrom_keys[v.chrom], v.pos)

    def _match_filter(self, i: int) -> bool:
        """当前过滤模式是否命中第 i 条变异（全部模式不调用）。"""
        v = self.variants[i]
        if self.filter_mode == "PASS":
            return v.filter == "PASS"
        if self._types is None:
            self._types = [classify_variant(x.ref, x.alt) for x in self.variants]
        t = self._types[i]
        if self.filter_mode == "SNP":
            return t in (VariantType.TRANSITION, VariantType.TRANSVERSION)
        return t in (VariantType.INSERTION, VariantType.DELETION)

    def _apply_filter_sort(self):
        """过滤/排序：在缓存的全局有序列表上做保序筛选，不重复全量排序。"""
        if self._order_dirty:
            # 后台扫描破坏了坐标序：一次性重建全局位置序（显式操作时才付出该成本）
            order = list(range(len(self.variants)))
            order.sort(key=self._pos_key)
            self._pos_order = order
            self._qual_order = None
            self._order_dirty = False
        if self.sort_mode == "QUAL":
            if self._qual_order is None:
                # 首次全局 QUAL 降序（缺失排最后），后续过滤直接复用
                order = list(range(len(self.variants)))
                order.sort(key=lambda i: (
                    self.variants[i].qual is None,
                    -(self.variants[i].qual or 0.0)))
                self._qual_order = order
            base = self._qual_order
        else:
            base = self._pos_order
        if self.filter_mode == "全部":
            self.view = list(base)
        else:
            self.view = [i for i in base if self._match_filter(i)]
        self._refresh_list()

    # ── 列表渲染 ──
    def _make_option(self, v: Variant) -> Option:
        t = classify_variant(v.ref, v.alt)
        symbol, sym_color = _TYPE_SYMBOL[t]
        # 行颜色按 FILTER/QUAL 编码可信度
        if v.filter == "PASS":
            row_style = "green"
        elif v.filter == "LowDP" or (v.qual is not None and v.qual < 20):
            row_style = "red"
        else:
            row_style = "yellow"
        line = Text()
        line.append(f"{symbol} ", style=sym_color)
        line.append(f"{v.chrom}:{v.pos:,}", style=row_style)
        line.append(f"  {(v.id or '.'):<12}", style="dim")
        if t is VariantType.INSERTION:
            summary = "ins"
        elif t is VariantType.DELETION:
            summary = "del"
        else:
            summary = f"{v.ref}→{v.alt}"
        line.append(f"{summary:<8}")
        line.append(f"{v.qual:>6.1f}" if v.qual is not None else "     -", style=row_style)
        return Option(line)

    def _refresh_list(self):
        self._win_start = 0
        self._rebuild_window(0, highlight_abs=0)
        if self.view:
            self._show_detail(0)
        else:
            self.query_one("#detail", Static).update(Text("（无匹配变异）", style="dim"))
        self._sync_scrollbar()
        self._sync_position_indicator()
        self._update_status_bar()

    def _rebuild_window(self, win_start: int, highlight_abs: int):
        """重建 OptionList 窗口（只物化 view[win_start:win_start+WINDOW]）。"""
        self._win_start = max(0, min(win_start, len(self.view)))
        ol = self.query_one("#variant-list", OptionList)
        ol.clear_options()
        ol.add_options([
            self._make_option(self.variants[i])
            for i in self.view[self._win_start:self._win_start + self.WINDOW]
        ])
        if ol.option_count:
            ol.highlighted = max(0, min(highlight_abs - self._win_start, ol.option_count - 1))

    def _abs_index(self) -> int:
        """当前高亮项在 view 中的绝对下标。"""
        ol = self.query_one("#variant-list", OptionList)
        return self._win_start + (ol.highlighted or 0)

    def _goto_abs(self, target: int):
        """跳转到 view 中的绝对下标（必要时平移窗口）。"""
        if not self.view:
            return
        target = max(0, min(target, len(self.view) - 1))
        materialized = min(self.WINDOW, len(self.view) - self._win_start)
        if self._win_start <= target < self._win_start + materialized:
            self.query_one("#variant-list", OptionList).highlighted = target - self._win_start
        else:
            new_start = min(max(target - self.WINDOW // 2, 0), max(0, len(self.view) - self.WINDOW))
            self._rebuild_window(new_start, target)

    # ── 详情渲染 ──
    def _build_detail(self, v: Variant) -> Text:
        t = classify_variant(v.ref, v.alt)
        sym, color = _TYPE_SYMBOL[t]
        txt = Text()
        txt.append(f"{sym} ", style=color)
        txt.append(f"[{_TYPE_LABEL[t]}]", style=f"bold {color}")
        if v.id:
            txt.append(f" {v.id}", style="bold")
        pass_style = "bold green" if v.filter == "PASS" else "bold red"
        txt.append(f"   {v.filter}", style=pass_style)
        txt.append("\n\n")
        txt.append("  位置     ", style="dim")
        txt.append(f"{v.chrom}:{v.pos:,}\n", style="bold")
        txt.append("  变异     ", style="dim")
        txt.append(f"{v.ref} → {v.alt}\n", style="bold")
        txt.append("  质量     ", style="dim")
        txt.append(f"{v.qual:.1f}\n" if v.qual is not None else "-\n", style="bold")
        if v.info:
            txt.append("\n")
            txt.append("─" * 46 + "\n", style="dim")
            for k, val in v.info.items():
                desc = self.meta.info_defs.get(k, "")
                txt.append(f"  {k:<6}", style="cyan")
                txt.append(f" {val or '(flag)'}", style="bold")
                if desc:
                    txt.append(f"  {desc}", style="dim")
                txt.append("\n")
        if v.samples:
            txt.append("\n")
            txt.append("─" * 46 + "\n", style="dim")
            txt.append("  基因型\n\n")
            for name, raw_gt in v.samples.items():
                gt = parse_genotype(raw_gt, v.format_fields)
                gt_s = gt.get("GT", "./.")
                label = _GT_LABEL.get(gt_s, gt_s)
                gt_style = _GT_MATRIX_STYLE.get(gt_s, "dim").replace("bold ", "")
                txt.append(f"  {name:<14}", style="bold")
                txt.append(f"{gt_s} {label}", style=gt_style)
                if "DP" in gt:
                    txt.append(f"  DP={gt['DP']}", style="dim")
                if "GQ" in gt:
                    txt.append(f"  GQ={gt['GQ']}", style="dim")
                txt.append("\n")
                ad = gt.get("AD")
                if isinstance(ad, list) and ad and sum(ad) > 0:
                    total = sum(ad)
                    ref_w = round(ad[0] / total * 20)
                    txt.append("               REF ", style="dim")
                    txt.append("▓" * ref_w, style="green")
                    txt.append(f" {ad[0]}\n", style="dim")
                    txt.append("               ALT ", style="dim")
                    txt.append("▓" * max(20 - ref_w, 1), style="red")
                    txt.append(f" {sum(ad[1:])}\n", style="dim")
        return txt

    def _show_detail(self, list_index: int):
        if self.matrix_mode:
            self._render_matrix(list_index)
            return
        if not self.view:
            return
        idx = self.view[list_index]
        v = self.variants[idx]
        load_variant_detail(self.filepath, v, self.meta.samples, fh=self._detail_fh())
        self.query_one("#detail", Static).update(self._build_detail(v))

    def _detail_text(self) -> str:
        """当前详情的纯文本（供测试断言）。"""
        if not self.view:
            return ""
        v = self.variants[self.view[self._abs_index()]]
        load_variant_detail(self.filepath, v, self.meta.samples, fh=self._detail_fh())
        return str(self._build_detail(v))

    # ── 基因型矩阵 ──
    def _build_matrix(self, current_list_index: int = 0) -> Text:
        txt = Text()
        samples = self.meta.samples or ["sample1"]
        name_w = max(len(s) for s in samples) + 2
        txt.append(" " * 24)
        for s in samples:
            txt.append(f"{s:>{name_w}}", style="bold cyan")
        txt.append("\n\n")
        start = max(0, current_list_index - 10)
        end = min(start + 21, len(self.view))
        for li in range(start, end):
            v = self.variants[self.view[li]]
            load_variant_detail(self.filepath, v, self.meta.samples, fh=self._detail_fh())
            is_cur = li == current_list_index
            txt.append("▶ " if is_cur else "  ", style="bold green" if is_cur else "")
            txt.append(f"{v.chrom}:{v.pos:<12}", style="bold" if is_cur else "")
            for s in samples:
                gt = parse_genotype(v.samples.get(s, "."), v.format_fields).get("GT", "./.")
                txt.append(f"{gt:>{name_w}}", style=_GT_MATRIX_STYLE.get(gt, "dim"))
            txt.append("\n")
        txt.append("\n")
        txt.append("  0/0 纯合参考 · 0/1 杂合 · 1/1 纯合变异", style="dim")
        return txt

    def _matrix_text(self) -> str:
        return str(self._build_matrix(self._abs_index()))

    def _render_matrix(self, list_index: int):
        self.query_one("#detail", Static).update(self._build_matrix(list_index))

    # ── 状态栏（异步统计，避免大文件过滤切换时冻结 UI） ──
    def _update_status_bar(self):
        """立即刷新计数/过滤/排序；重型统计后台计算后回填。扫描中只显示进度。"""
        if self.scanning:
            parts = (
                f" {len(self.view):,} 变异（扫描中… 已索引 {len(self.variants):,}） │ "
                f"[过滤:{self.filter_mode}] [排序:{self.sort_mode}]"
            )
            if self.skipped:
                parts += f" │ 跳过 {self.skipped} 行畸形数据"
            self.query_one("#status-bar", Static).update(Text(parts))
            return
        parts = (
            f" {len(self.view):,} 变异 │ [过滤:{self.filter_mode}] [排序:{self.sort_mode}] │ 统计中…"
        )
        if self.skipped:
            parts += f" │ 跳过 {self.skipped} 行畸形数据"
        self.query_one("#status-bar", Static).update(Text(parts))
        self._stats_token += 1
        token = self._stats_token
        snapshot = list(self.view)
        self.run_worker(partial(self._stats_worker, token, snapshot), thread=True, exclusive=False)

    def _stats_worker(self, token: int, snapshot: list[int]):
        """后台线程：计算统计后回 UI 线程回填（版本号防竞态）。"""
        s = compute_stats([self.variants[i] for i in snapshot])
        if token == self._stats_token:
            try:
                self.call_from_thread(self._apply_stats_bar, s, token)
            except RuntimeError:
                pass  # 应用已退出

    def _apply_stats_bar(self, s: dict, token: int):
        if not self.is_running or token != self._stats_token:
            return  # 应用退出中或已有更新的统计请求，丢弃过时结果
        parts = (
            f" {s['total']:,} 变异 │ SNP {s['snp']:,} · InDel {s['indel']:,} │ "
            f"Ts/Tv {s['ts_tv']:.2f} │ PASS {s['pass_count']:,} │ "
            f"AF均值 {s['mean_af']:.2f} │ [过滤:{self.filter_mode}] [排序:{self.sort_mode}]"
        )
        if self.skipped:
            parts += f" │ 跳过 {self.skipped} 行畸形数据"
        self.query_one("#status-bar", Static).update(Text(parts))

    # ── 剪贴板（与 browser.py 相同的分层回退策略） ──
    def _copy_to_clipboard(self, text: str) -> bool:
        """系统工具优先，失败后回退 OSC 52。"""
        import platform
        system = platform.system()
        data = text.encode()
        try:
            if system == "Darwin":
                subprocess.run(["pbcopy"], input=data, check=True)
                return True
            elif system == "Linux":
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
            pass
        try:
            self.copy_to_clipboard(text)
            return True
        except Exception:  # noqa: BLE001
            return False

    # ── 搜索命令栏 ──
    async def _show_search_bar(self) -> None:
        self._remove_search_bar()
        bar = Input(placeholder="搜索 ID 或坐标 (如 rs12345 / chr1:10234)... (Enter 确认, Esc 取消)",
                    id="search-input")
        await self.mount(bar)
        bar.focus()

    def _remove_search_bar(self) -> None:
        try:
            self.query_one("#search-input", Input).remove()
        except Exception:  # noqa: BLE001
            pass

    def _get_search_bar(self) -> Input | None:
        try:
            return self.query_one("#search-input", Input)
        except Exception:  # noqa: BLE001
            return None

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._remove_search_bar()
        self.query_one("#variant-list", OptionList).focus()
        value = event.value.strip()
        if not value:
            return
        q = value.lower()
        for li, vi in enumerate(self.view):
            v = self.variants[vi]
            coord = f"{v.chrom}:{v.pos}".lower()
            coord_comma = f"{v.chrom}:{v.pos:,}".lower()
            if q == v.id.lower() or q in (coord, coord_comma) or q in v.id.lower():
                self._goto_abs(li)
                self.notify(f"找到: {v.chrom}:{v.pos:,} {v.id or ''}".strip(), title="搜索")
                return
        self.notify(f"未找到匹配 \"{value}\"", title="搜索", severity="warning")

    def on_key(self, event) -> None:
        """命令栏存在时：Esc 关闭，其他键交给 Input。"""
        bar = self._get_search_bar()
        if bar is not None:
            if event.key == "escape":
                self._remove_search_bar()
                self.query_one("#variant-list", OptionList).focus()
                event.stop()
            else:
                event.stop()  # 防止 j/k/q 等绑定穿透到 Input

    # ── 事件 ──
    def on_option_list_option_highlighted(self, event) -> None:
        if event.option is not None:
            # 窗口内下标 → view 绝对下标
            self._show_detail(self._win_start + event.option_index)
            self._sync_position_indicator()

    # ── Actions ──
    def action_cursor_down(self):
        self._goto_abs(self._abs_index() + 1)

    def action_cursor_up(self):
        self._goto_abs(self._abs_index() - 1)

    def action_page_down(self):
        self._goto_abs(self._abs_index() + self.PAGE)

    def action_page_up(self):
        self._goto_abs(self._abs_index() - self.PAGE)

    def action_home(self):
        self._goto_abs(0)

    def action_end(self):
        self._goto_abs(len(self.view) - 1)

    async def action_search(self):
        await self._show_search_bar()

    def action_cycle_filter(self):
        i = _FILTER_CYCLE.index(self.filter_mode)
        self.filter_mode = _FILTER_CYCLE[(i + 1) % len(_FILTER_CYCLE)]
        self._apply_filter_sort()
        self.notify(f"过滤: {self.filter_mode}", title="过滤")

    def action_toggle_sort(self):
        self.sort_mode = "QUAL" if self.sort_mode == "位置" else "位置"
        self._apply_filter_sort()
        self.notify(f"排序: {self.sort_mode}", title="排序")

    def action_toggle_view(self):
        self.matrix_mode = not self.matrix_mode
        self._show_detail(self._abs_index())

    def action_file_info(self):
        txt = Text()
        txt.append("文件信息\n\n", style="bold")
        txt.append("  格式     ", style="dim")
        txt.append(f"{self.meta.fileformat or '未知'}\n")
        txt.append("  样本数   ", style="dim")
        txt.append(f"{len(self.meta.samples)}  ({', '.join(self.meta.samples) or '无'})\n")
        txt.append("  变异数   ", style="dim")
        txt.append(f"{len(self.variants):,}\n")
        if self.skipped:
            txt.append("  跳过     ", style="dim")
            txt.append(f"{self.skipped} 行畸形数据\n")
        if self.meta.contigs:
            txt.append("\nContigs:\n", style="bold cyan")
            for cid, length in self.meta.contigs.items():
                txt.append(f"  {cid:<10}")
                txt.append(f"{length:,} bp\n", style="green")
        if self.meta.filter_defs:
            txt.append("\nFILTER 定义:\n", style="bold cyan")
            for fid, desc in self.meta.filter_defs.items():
                txt.append(f"  {fid:<10}{desc}\n")
        if self.meta.info_defs:
            txt.append("\nINFO 定义:\n", style="bold cyan")
            for iid, desc in self.meta.info_defs.items():
                txt.append(f"  {iid:<10}{desc}\n")
        if self.meta.format_defs:
            txt.append("\nFORMAT 定义:\n", style="bold cyan")
            for fid, desc in self.meta.format_defs.items():
                txt.append(f"  {fid:<10}{desc}\n")
        self.query_one("#detail", Static).update(txt)

    def action_copy_line(self):
        if not self.view:
            self.notify("没有可复制的变异", severity="warning")
            return
        v = self.variants[self.view[self._abs_index()]]
        load_variant_detail(self.filepath, v, self.meta.samples, fh=self._detail_fh())
        ok = self._copy_to_clipboard(v.raw)
        self._last_copied = v.raw
        if ok:
            self.notify(f"已复制 {v.chrom}:{v.pos:,}", title="复制")
        else:
            self.notify("剪贴板不可用", title="复制", severity="warning")

    def action_help(self):
        self.push_screen(HelpScreen())

    def action_quit(self):
        self.exit()
