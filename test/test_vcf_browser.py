"""VcfBrowser TUI 测试（对应 docs/superpowers/plans Task 6-8）。"""
import asyncio
from pathlib import Path

from textual.widgets import OptionList

from seqviz.vcf_browser import VcfBrowser

TEST_DIR = Path(__file__).parent
SAMPLE_VCF = TEST_DIR / "sample.vcf"


def run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────
# 启动与列表
# ──────────────────────────────────────────────
class TestLaunch:
    def test_app_starts_and_lists_variants(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                assert ol.option_count == 18
        run(_t())

    def test_detail_shows_first_variant(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                text = app._detail_text()
                assert "10,234" in text  # 千分位坐标
                assert "sample1" in text  # 逐样本基因型已加载
        run(_t())

    def test_empty_vcf(self, tmp_path):
        f = tmp_path / "empty.vcf"
        f.write_text("")
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                assert ol.option_count == 0
        run(_t())


# ──────────────────────────────────────────────
# 导航
# ──────────────────────────────────────────────
class TestNavigation:
    def test_jk_moves_highlight(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                assert ol.highlighted == 0
                await pilot.press("j")
                await pilot.pause()
                assert ol.highlighted == 1
                await pilot.press("k")
                await pilot.pause()
                assert ol.highlighted == 0
        run(_t())

    def test_g_G_jumps(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                await pilot.press("G")
                await pilot.pause()
                assert ol.highlighted == ol.option_count - 1
                await pilot.press("g")
                await pilot.pause()
                assert ol.highlighted == 0
        run(_t())


# ──────────────────────────────────────────────
# 过滤与排序
# ──────────────────────────────────────────────
class TestFilterSort:
    def test_filter_cycle(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                assert ol.option_count == 18
                await pilot.press("f")  # PASS
                await pilot.pause()
                assert app.filter_mode == "PASS"
                assert ol.option_count == 13
                await pilot.press("f")  # SNP
                await pilot.pause()
                assert app.filter_mode == "SNP"
                assert ol.option_count == 12
                await pilot.press("f")  # InDel
                await pilot.pause()
                assert app.filter_mode == "InDel"
                assert ol.option_count == 6
                await pilot.press("f")  # 回到全部
                await pilot.pause()
                assert ol.option_count == 18
        run(_t())

    def test_sort_by_qual(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()
                assert app.sort_mode == "QUAL"
                quals = [app.variants[i].qual for i in app.view]
                non_none = [q for q in quals if q is not None]
                assert non_none == sorted(non_none, reverse=True)
                assert quals[-1] is None or all(q is not None for q in quals)
                await pilot.press("s")
                await pilot.pause()
                assert app.sort_mode == "位置"
        run(_t())


# ──────────────────────────────────────────────
# 搜索
# ──────────────────────────────────────────────
class TestSearch:
    def test_search_by_id(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("slash")
                await pilot.pause()
                await pilot.press(*"rs67890")
                await pilot.press("enter")
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                v = app.variants[app.view[ol.highlighted]]
                assert v.id == "rs67890"
        run(_t())

    def test_search_by_coordinate(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("slash")
                await pilot.pause()
                await pilot.press(*"chr2:12345")
                await pilot.press("enter")
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                v = app.variants[app.view[ol.highlighted]]
                assert (v.chrom, v.pos) == ("chr2", 12345)
        run(_t())

    def test_search_escape_cancels(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("slash")
                await pilot.pause()
                assert app._get_search_bar() is not None
                await pilot.press("escape")
                await pilot.pause()
                assert app._get_search_bar() is None
        run(_t())


# ──────────────────────────────────────────────
# 矩阵 / 信息 / 复制
# ──────────────────────────────────────────────
class TestMatrixInfoCopy:
    def test_matrix_toggle(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("t")
                await pilot.pause()
                assert app.matrix_mode is True
                assert "sample1" in app._matrix_text()
                await pilot.press("t")
                await pilot.pause()
                assert app.matrix_mode is False
        run(_t())

    def test_file_info_panel(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("i")
                await pilot.pause()
                detail = app.query_one("#detail")
                # 信息面板渲染为 Rich Text，检查其纯文本内容
                text = str(detail.render())
                assert "VCFv4.3" in text
                assert "chr1" in text
        run(_t())

    def test_copy_line_records_raw(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("y")
                await pilot.pause()
                assert app._last_copied.startswith("chr1\t10234\trs12345")
        run(_t())

    def test_help_screen_opens_and_q_closes(self):
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("question_mark")
                await pilot.pause()
                assert len(app.screen_stack) > 1  # 帮助屏已推入
                await pilot.press("q")
                await pilot.pause()
                assert len(app.screen_stack) == 1  # q 只关闭帮助屏，不退出
        run(_t())
