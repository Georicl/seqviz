"""VCF 交互式浏览器 — 双栏：左变异列表 + 右详情/基因型矩阵。

设计文档: docs/superpowers/specs/2026-07-25-vcf-visualization-design.md
"""

import subprocess
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

    def __init__(self, filepath: Path):
        super().__init__()
        self.filepath = filepath
        self.meta, self.variants, self.skipped = scan_vcf(filepath)
        self.view: list[int] = list(range(len(self.variants)))  # 过滤/排序后的下标映射
        self.filter_mode = "全部"
        self.sort_mode = "位置"
        self.matrix_mode = False
        self._last_copied: str = ""  # 最后一次复制内容（测试用）

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield OptionList(id="variant-list")
            yield Static("", id="detail")
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self):
        self._refresh_list()
        self.query_one("#variant-list", OptionList).focus()

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
        ol = self.query_one("#variant-list", OptionList)
        ol.clear_options()
        ol.add_options([self._make_option(self.variants[i]) for i in self.view])
        if self.view:
            ol.highlighted = 0
            self._show_detail(0)
        else:
            self.query_one("#detail", Static).update(Text("（无匹配变异）", style="dim"))
        self._update_status_bar()

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
        load_variant_detail(self.filepath, v, self.meta.samples)
        self.query_one("#detail", Static).update(self._build_detail(v))

    def _detail_text(self) -> str:
        """当前详情的纯文本（供测试断言）。"""
        if not self.view:
            return ""
        ol = self.query_one("#variant-list", OptionList)
        v = self.variants[self.view[ol.highlighted or 0]]
        load_variant_detail(self.filepath, v, self.meta.samples)
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
            load_variant_detail(self.filepath, v, self.meta.samples)
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
        ol = self.query_one("#variant-list", OptionList)
        return str(self._build_matrix(ol.highlighted or 0))

    def _render_matrix(self, list_index: int):
        self.query_one("#detail", Static).update(self._build_matrix(list_index))

    # ── 状态栏 ──
    def _update_status_bar(self):
        s = compute_stats([self.variants[i] for i in self.view])
        parts = (
            f" {s['total']} 变异 │ SNP {s['snp']} · InDel {s['indel']} │ "
            f"Ts/Tv {s['ts_tv']:.2f} │ PASS {s['pass_count']} │ "
            f"AF均值 {s['mean_af']:.2f} │ [过滤:{self.filter_mode}] [排序:{self.sort_mode}]"
        )
        if self.skipped:
            parts += f" │ 跳过 {self.skipped} 行畸形数据"
        self.query_one("#status-bar", Static).update(Text(parts))

    # ── 过滤 / 排序 ──
    def _apply_filter_sort(self):
        idxs = list(range(len(self.variants)))
        if self.filter_mode == "PASS":
            idxs = [i for i in idxs if self.variants[i].filter == "PASS"]
        elif self.filter_mode == "SNP":
            idxs = [i for i in idxs if classify_variant(
                self.variants[i].ref, self.variants[i].alt)
                in (VariantType.TRANSITION, VariantType.TRANSVERSION)]
        elif self.filter_mode == "InDel":
            idxs = [i for i in idxs if classify_variant(
                self.variants[i].ref, self.variants[i].alt)
                in (VariantType.INSERTION, VariantType.DELETION)]
        if self.sort_mode == "QUAL":
            # QUAL 缺失排最后，其余降序
            idxs.sort(key=lambda i: (
                self.variants[i].qual is None,
                -(self.variants[i].qual or 0.0)))
        else:
            idxs.sort(key=lambda i: (self.variants[i].chrom, self.variants[i].pos))
        self.view = idxs
        self._refresh_list()

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
                ol = self.query_one("#variant-list", OptionList)
                ol.highlighted = li
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
            self._show_detail(event.option_index)

    # ── Actions ──
    def action_cursor_down(self):
        self.query_one("#variant-list", OptionList).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#variant-list", OptionList).action_cursor_up()

    def action_page_down(self):
        self.query_one("#variant-list", OptionList).action_page_down()

    def action_page_up(self):
        self.query_one("#variant-list", OptionList).action_page_up()

    def action_home(self):
        self.query_one("#variant-list", OptionList).highlighted = 0

    def action_end(self):
        ol = self.query_one("#variant-list", OptionList)
        if ol.option_count:
            ol.highlighted = ol.option_count - 1

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
        ol = self.query_one("#variant-list", OptionList)
        self._show_detail(ol.highlighted or 0)

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
        self.query_one("#detail", Static).update(txt)

    def action_copy_line(self):
        if not self.view:
            self.notify("没有可复制的变异", severity="warning")
            return
        ol = self.query_one("#variant-list", OptionList)
        v = self.variants[self.view[ol.highlighted or 0]]
        load_variant_detail(self.filepath, v, self.meta.samples)
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
