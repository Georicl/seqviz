"""TUI 浏览器交互测试：导航、搜索、跳转、复制、返回、多标签页、命令栏渲染"""

import asyncio
from pathlib import Path

import pytest

from seqviz.browser import FastaBrowser

TEST_DIR = Path(__file__).parent
TEST_FA = TEST_DIR / "test.fa"
TEST_FASTQ = TEST_DIR / "test_fastq.fastq"
TEST_PROTEIN = TEST_DIR / "test_protein.fa"


def run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────
# 启动与加载
# ──────────────────────────────────────────────
class TestBrowserLaunch:
    def test_launch_loads_first_sequence(self):
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                assert mv._seq != ""  # 第一条序列已加载
                assert app.current_tab.current_index == 0
        run(_t())

    def test_launch_with_fastq(self):
        async def _t():
            app = FastaBrowser([TEST_FASTQ])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                assert mv._seq != ""
                assert mv._quality != ""  # FASTQ 有质量值
        run(_t())

    def test_sequence_count_indexed(self):
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert len(app.current_tab.sequences) == 2  # test.fa 有 2 条
        run(_t())


# ──────────────────────────────────────────────
# 导航
# ──────────────────────────────────────────────
class TestNavigation:
    def test_next_sequence(self):
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert app.current_tab.current_index == 0
                await pilot.press("n")
                await pilot.pause()
                assert app.current_tab.current_index == 1
        run(_t())

    def test_prev_sequence_at_start_stays(self):
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("p")  # 已在第一条
                await pilot.pause()
                assert app.current_tab.current_index == 0
        run(_t())

    def test_next_at_end_stays(self):
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("n")
                await pilot.press("n")  # 超出最后一条
                await pilot.pause()
                assert app.current_tab.current_index == 1  # 停在最后
        run(_t())

    def test_scroll_changes_offset(self):
        async def _t():
            app = FastaBrowser([Path(__file__).parent / "chr2.fa"])
            async with app.run_test(size=(100, 20)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                initial = mv.view_offset
                await pilot.press("j")
                await pilot.pause()
                assert mv.view_offset > initial
        run(_t())


# ──────────────────────────────────────────────
# 搜索与跳转（命令栏）
# ──────────────────────────────────────────────
class TestSearchGoto:
    def test_search_opens_command_bar(self):
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert app._get_command_bar() is None
                await pilot.press("/")
                await pilot.pause()
                assert app._get_command_bar() is not None
        run(_t())

    def test_command_bar_captures_input(self):
        """命令栏应能捕获输入的字符（值被记录）。"""
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press(":")
                await pilot.pause()
                await pilot.press("2")
                await pilot.pause()
                bar = app._get_command_bar()
                assert bar.value == "2"
        run(_t())

    def test_goto_jumps_to_sequence(self):
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press(":")
                await pilot.press("2")
                await pilot.press("enter")
                await pilot.pause()
                assert app.current_tab.current_index == 1  # 第2条 (1-based)
                assert app._get_command_bar() is None  # 已关闭
        run(_t())

    def test_search_finds_sequence(self):
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("/")
                for ch in "chr2":
                    await pilot.press(ch)
                await pilot.press("enter")
                await pilot.pause()
                assert app.current_tab.current_index == 1  # chr2 是第2条
        run(_t())

    def test_escape_closes_command_bar(self):
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("/")
                await pilot.pause()
                assert app._get_command_bar() is not None
                await pilot.press("escape")
                await pilot.pause()
                assert app._get_command_bar() is None
        run(_t())


# ──────────────────────────────────────────────
# 复制与导出
# ──────────────────────────────────────────────
class TestCopyExport:
    def test_copy_seq_to_clipboard(self, monkeypatch):
        async def _t():
            copied = {}
            import seqviz.browser as b
            def fake_run(cmd, input=None, check=False):
                copied["data"] = input.decode() if input else ""
                class R: pass
                return R()
            monkeypatch.setattr(b.subprocess, "run", fake_run)
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("y")
                await pilot.pause()
            assert ">chr1" in copied.get("data", "")  # 复制了第一条序列
        run(_t())

    def test_export_creates_file(self, tmp_path, monkeypatch):
        async def _t():
            monkeypatch.chdir(tmp_path)
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("e")
                await pilot.pause()
            exported = list(tmp_path.glob("*.fasta"))
            assert len(exported) == 1
            content = exported[0].read_text()
            assert content.startswith(">chr1")
        run(_t())


# ──────────────────────────────────────────────
# 返回文件选择器
# ──────────────────────────────────────────────
class TestBackNavigation:
    def test_back_with_source_dir(self):
        async def _t():
            app = FastaBrowser([TEST_FA], source_dir=TEST_DIR)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("B")
                await pilot.pause()
                assert app.return_value == "back"
        run(_t())

    def test_back_without_source_dir(self):
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("B")
                await pilot.pause()
                assert app.return_value is None  # 不返回
        run(_t())


# ──────────────────────────────────────────────
# 多标签页
# ──────────────────────────────────────────────
class TestMultiTab:
    def test_multi_file_creates_tabs(self):
        async def _t():
            app = FastaBrowser([TEST_FA, TEST_FASTQ])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert len(app.file_tabs) == 2
        run(_t())

    def test_single_file_no_tabs(self):
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert len(app.file_tabs) == 1
        run(_t())


# ──────────────────────────────────────────────
# 蛋白质检测
# ──────────────────────────────────────────────
class TestProteinDetection:
    def test_protein_sequence_detected(self):
        async def _t():
            app = FastaBrowser([TEST_PROTEIN])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                from seqviz.seq_type import SeqType
                assert mv._seq_type == SeqType.PROTEIN
        run(_t())


# ──────────────────────────────────────────────
# 审查补强：翻页/顶底、Tab 切换、范围复制、空文件安全
# ──────────────────────────────────────────────
class TestNavigationExtras:
    def test_goto_bottom_and_top(self):
        async def _t():
            app = FastaBrowser([TEST_DIR / "chr2.fa"])
            async with app.run_test(size=(100, 20)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                await pilot.press("G")  # 跳到底部
                await pilot.pause()
                assert mv.view_offset == max(0, mv._total_lines - 1)
                await pilot.press("g")  # 跳到顶部
                await pilot.pause()
                assert mv.view_offset == 0
        run(_t())

    def test_page_down_up(self):
        async def _t():
            app = FastaBrowser([TEST_DIR / "chr2.fa"])
            async with app.run_test(size=(100, 20)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                initial = mv.view_offset
                await pilot.press("space")  # 向下翻页
                await pilot.pause()
                assert mv.view_offset > initial
                await pilot.press("b")  # 向上翻页
                await pilot.pause()
                assert mv.view_offset == initial
        run(_t())


class TestTabSwitch:
    def test_tab_switches_active_tab(self):
        async def _t():
            app = FastaBrowser([TEST_FA, TEST_FASTQ])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert app.active_tab == 0
                await pilot.press("tab")  # 切到下一个标签页
                await pilot.pause()
                assert app.active_tab == 1
                await pilot.press("tab")  # 循环回第一个
                await pilot.pause()
                assert app.active_tab == 0
        run(_t())


class TestRangeCopy:
    def test_range_copy_success(self, monkeypatch):
        async def _t():
            copied: list[str] = []
            monkeypatch.setattr(FastaBrowser, "_copy_to_clipboard", lambda self, text: copied.append(text) or True)
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                expected = app._get_main_view()._seq[0:4]
                await pilot.press("c")
                for ch in "1-4":
                    await pilot.press(ch)
                await pilot.press("enter")
                await pilot.pause()
            assert copied == [expected]
        run(_t())

    def test_range_copy_out_of_bounds(self, monkeypatch):
        async def _t():
            copied: list[str] = []
            monkeypatch.setattr(FastaBrowser, "_copy_to_clipboard", lambda self, text: copied.append(text) or True)
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("c")
                for ch in "999-9999":
                    await pilot.press(ch)
                await pilot.press("enter")
                await pilot.pause()
            assert copied == []  # 越界不复制
        run(_t())

    def test_range_copy_invalid_format(self, monkeypatch):
        async def _t():
            copied: list[str] = []
            monkeypatch.setattr(FastaBrowser, "_copy_to_clipboard", lambda self, text: copied.append(text) or True)
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("c")
                for ch in "abc":
                    await pilot.press(ch)
                await pilot.press("enter")
                await pilot.pause()
            assert copied == []  # 非法格式不复制
        run(_t())


class TestEmptyFileSafety:
    def test_export_copy_empty_file_no_crash(self, tmp_path, monkeypatch):
        """空文件按 e/y 应友好提示而非 IndexError 崩溃。"""
        p = tmp_path / "empty.fa"
        p.write_text("")

        async def _t():
            monkeypatch.chdir(tmp_path)
            app = FastaBrowser([p])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("e")  # 不应崩溃
                await pilot.pause()
                await pilot.press("y")  # 不应崩溃
                await pilot.pause()
            assert list(tmp_path.glob("*.fasta")) == []  # 无序列可导出
        run(_t())


class TestStatusBarLayout:
    def test_statusbar_visible_above_footer(self):
        """状态栏应可见且位于 Footer 上方（回归：两者同 dock:bottom 重叠遮挡）。"""
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                statusbar = app.query_one("#statusbar")
                footer = app.query_one("Footer")
                sb_region = statusbar.region
                ft_region = footer.region
                assert sb_region.height >= 1 and sb_region.width > 0
                # 状态栏整体位于 Footer 上方，无重叠
                assert sb_region.y + sb_region.height <= ft_region.y
        run(_t())


class TestHelpScreen:
    def test_help_shows_all_keys(self):
        """? 打开帮助面板，应包含全部已声明快捷键（含 y/c/B/Tab）。"""
        from seqviz.browser import HelpScreen

        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("question_mark")
                for _ in range(20):  # 等待模态屏幕挂载就绪
                    await pilot.pause()
                    if isinstance(app.screen, HelpScreen):
                        break
                assert isinstance(app.screen, HelpScreen)
                from textual.css.query import NoMatches
                panel = None
                for _ in range(20):  # 等待模态屏幕内面板挂载就绪
                    await pilot.pause()
                    try:
                        panel = app.screen.query_one("#help-panel")
                        break
                    except NoMatches:
                        continue
                assert panel is not None
                text = str(panel.render())
                for key_desc in ("复制当前序列", "范围复制", "返回文件选择器", "切换文件标签页"):
                    assert key_desc in text
        run(_t())

    def test_q_closes_help_not_exit(self):
        """帮助面板打开时按 q 应关闭面板而非退出浏览器（回归用户报告的 bug）。"""
        from seqviz.browser import HelpScreen

        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("question_mark")
                await pilot.pause()
                assert isinstance(app.screen, HelpScreen)
                await pilot.press("q")  # 应关闭帮助而非退出
                await pilot.pause()
                assert not isinstance(app.screen, HelpScreen)
                app.query_one("#main-0")  # 应用仍在运行
                await pilot.press("q")  # 再按才退出
                await pilot.pause()
        run(_t())

    def test_tab_does_not_switch_while_help_open(self):
        """帮助面板打开时按 Tab 不应在背后切换标签页。"""
        from seqviz.browser import HelpScreen

        async def _t():
            app = FastaBrowser([TEST_FA, TEST_FASTQ])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("question_mark")
                await pilot.pause()
                assert isinstance(app.screen, HelpScreen)
                await pilot.press("tab")
                await pilot.pause()
                assert app.active_tab == 0  # 未切换
        run(_t())


# ──────────────────────────────────────────────
# 三轮审查回归测试
# ──────────────────────────────────────────────
class TestExportSafety:
    def test_export_twice_no_overwrite(self, tmp_path, monkeypatch):
        """重复导出同一序列应自动追加序号，不静默覆盖已有文件。"""
        async def _t():
            monkeypatch.chdir(tmp_path)
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("e")
                await pilot.pause()
                await pilot.press("e")
                await pilot.pause()
            names = sorted(p.name for p in tmp_path.glob("*.fasta"))
            assert names == ["chr1.fasta", "chr1_1.fasta"]
        run(_t())

    def test_export_sanitizes_illegal_chars(self, tmp_path, monkeypatch):
        """header 含跨平台非法文件名字符（: * | 等）时应净化而非 OSError 崩溃。"""
        p = tmp_path / "bad.fa"
        p.write_text(">seq:1|test*A\nACGT\n")

        async def _t():
            monkeypatch.chdir(tmp_path)
            app = FastaBrowser([p])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("e")  # 不应崩溃
                await pilot.pause()
            exported = list(tmp_path.glob("*.fasta"))
            assert len(exported) == 1
            assert ":" not in exported[0].name and "|" not in exported[0].name
        run(_t())


class TestDuplicatePathScan:
    def test_same_file_opened_twice_scan_no_cross_pollution(self, tmp_path):
        """同一路径打开两次（>500 条触发后台续扫）：两个标签页各自完整，不错配。"""
        p = tmp_path / "many.fa"
        p.write_text("".join(f">s{i}\nACGT\n" for i in range(600)))

        async def _t():
            app = FastaBrowser([p, p])
            async with app.run_test(size=(100, 30)) as pilot:
                for _ in range(100):  # 等待后台扫描完成
                    await pilot.pause()
                    if all(len(t.sequences) >= 600 for t in app.file_tabs):
                        break
            assert len(app.file_tabs[0].sequences) == 600
            assert len(app.file_tabs[1].sequences) == 600  # 不再停留在 500
        run(_t())


class TestResizeClamp:
    def test_view_offset_clamped_after_wrap_change(self):
        """换行宽度变化（窗口加宽）后 view_offset 应钳制在有效范围，避免空白屏。"""
        async def _t():
            app = FastaBrowser([TEST_FA])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                view = app.query_one("#main-0")
                view.view_offset = 10_000  # 模拟越界偏移
                view.WRAP = 5  # 强制 on_resize 认定宽度已变化并重算
                view.on_resize(None)
                assert view.view_offset <= max(0, view._total_lines - 1)
        run(_t())


class TestNonUtf8Header:
    def test_latin1_header_no_crash(self, tmp_path):
        """非 UTF-8 编码的 header（latin-1 字节）应宽容处理而非 UnicodeDecodeError。"""
        p = tmp_path / "latin1.fa"
        p.write_bytes(b">caf\xe9 header\nACGT\n")

        async def _t():
            app = FastaBrowser([p])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
            seqs = app.file_tabs[0].sequences
            assert len(seqs) == 1
            assert "caf" in seqs[0].header  # 非法字节被替换，其余保留
        run(_t())
