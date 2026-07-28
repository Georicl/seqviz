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
