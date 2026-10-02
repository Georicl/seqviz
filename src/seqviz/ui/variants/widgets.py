"""VCF 浏览器的列表、滚动条、帮助与详情控件。"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import OptionList, Static

if TYPE_CHECKING:
    from seqviz.ui.variants.app import VcfBrowser


class VariantList(OptionList):
    """大列表滚轮移动选中项及窗口；小列表使用原生视口滚动。"""

    def scroll_down(self, animate: bool = True) -> None:
        app = cast("VcfBrowser", self.app)
        if len(app.view) > app.WINDOW:
            app._goto_abs(app._abs_index() + 3)
        else:
            super().scroll_down(animate)

    def scroll_up(self, animate: bool = True) -> None:
        app = cast("VcfBrowser", self.app)
        if len(app.view) > app.WINDOW:
            app._goto_abs(app._abs_index() - 3)
        else:
            super().scroll_up(animate)


class AbsoluteScrollbar(Widget):
    """按全量 view 的当前位置和窗口占比绘制滚动条，支持点击及拖拽。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._dragging = False

    def render(self):
        app = cast("VcfBrowser", self.app)
        h = self.size.height
        txt = Text()
        if h <= 0 or len(app.view) <= app.WINDOW:
            return txt
        n = len(app.view)
        thumb_h = max(1, round(h * min(app.WINDOW, n) / n))
        track = h - thumb_h
        frac = app._abs_index() / max(n - 1, 1)
        thumb_start = round(frac * track)
        for row in range(h):
            if thumb_start <= row < thumb_start + thumb_h:
                txt.append("█")
            else:
                txt.append("░", style="dim")
            if row < h - 1:
                txt.append("\n")
        return txt

    def _jump_to(self, y: int):
        app = cast("VcfBrowser", self.app)
        if not app.view:
            return
        h = max(self.size.height, 1)
        frac = min(max(y / h, 0.0), 1.0)
        app._goto_abs(int(frac * (len(app.view) - 1)))

    def on_mouse_down(self, event) -> None:
        self._dragging = True
        self.capture_mouse()
        self._jump_to(event.y)
        event.stop()

    def on_mouse_move(self, event) -> None:
        if self._dragging:
            self._jump_to(event.y)
            event.stop()

    def on_mouse_up(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self.release_mouse()
            event.stop()


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

    BINDINGS: Sequence[Binding] = [
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
            ("j / k", "上下移动（右侧聚焦时滚动详情）"),
            ("n / p", "下/上一条变异"),
            ("g / G", "顶部 / 底部"),
            ("/", "搜索: ID / chr:pos / chr:a-b"),
            ("f", "过滤循环 (全部/PASS/SNP/InDel)"),
            ("s", "排序切换 (位置/QUAL)"),
            ("t", "详情 ↔ 基因型矩阵"),
            ("Tab / Esc", "左侧列表 ↔ 右侧详情面板"),
            ("i", "文件信息"),
            ("y", "复制当前 VCF 行"),
            ("?", "帮助"),
            ("q", "退出"),
        ]
        for key, desc in rows:
            text.append(f"{key:<14}", style="bold green")
            text.append(desc + "\n")
        panel.update(text)


class DetailPanel(VerticalScroll, can_focus=True):
    """可滚动的详情/基因型矩阵；聚焦后接收内容导航键，Esc 返回列表。"""

    BINDINGS: Sequence[Binding] = [
        Binding("down", "detail_down", "详情下滚", show=False),
        Binding("up", "detail_up", "详情上滚", show=False),
        Binding("pageup", "detail_page_up", "上翻页", show=False),
        Binding("pagedown", "detail_page_down", "下翻页", show=False),
        Binding("g", "detail_home", "详情顶部", show=False),
        Binding("G", "detail_end", "详情底部", show=False),
        Binding("escape", "back_to_list", "返回列表", show=False),
    ]

    STEP = 3  # 每次 j/k/↑/↓ 滚动行数（与滚轮默认步幅一致）

    def compose(self) -> ComposeResult:
        yield Static("", id="detail-content")

    def content(self) -> Static:
        return self.query_one("#detail-content", Static)

    def set_content(self, renderable) -> None:
        """更新内容并回到顶部（切换变异/视图时调用）。"""
        self.content().update(renderable)
        self.scroll_home(animate=False)

    def action_detail_down(self):
        self.scroll_relative(0, self.STEP, animate=False)

    def action_detail_up(self):
        self.scroll_relative(0, -self.STEP, animate=False)

    def action_detail_page_down(self):
        self.scroll_relative(0, self.size.height, animate=False)

    def action_detail_page_up(self):
        self.scroll_relative(0, -self.size.height, animate=False)

    def action_detail_home(self):
        self.scroll_home(animate=False)

    def action_detail_end(self):
        self.scroll_end(animate=False)

    def action_back_to_list(self):
        self.app.query_one("#variant-list", OptionList).focus()
