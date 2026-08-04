"""VcfBrowser TUI 测试（对应 docs/superpowers/plans Task 6-8）。"""
import asyncio
from pathlib import Path

from textual.widgets import OptionList

from seqviz.vcf import scan_vcf_quick
from seqviz.vcf_browser import VcfBrowser, AbsoluteScrollbar

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

    def test_empty_vcf_app_level_graceful(self, tmp_path):
        """App 层面对空文件仍可优雅打开（CLI 层拦截报错，见 test_cli）。"""
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
                # 规格要求：INFO/FORMAT 字段定义也要展示
                assert "Total Depth" in text      # ##INFO DP 的 Description
                assert "Genotype" in text         # ##FORMAT GT 的 Description
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


# ──────────────────────────────────────────────
# 后台续扫（启动即显）
# ──────────────────────────────────────────────
class TestBackgroundScan:
    def test_immediate_display_then_background_completion(self):
        """快扫 2 条立即启动，后台续扫完成后总量补齐、无丢失。"""
        meta, head, skipped, cont = scan_vcf_quick(SAMPLE_VCF, limit=2)
        assert cont >= 0
        async def _t():
            app = VcfBrowser(SAMPLE_VCF, initial=(meta, head, skipped, cont))
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                assert len(app.variants) >= 2  # 首屏至少有快扫的 2 条
                # 等待后台扫描完成（对账补齐；小文件可能瞬间完成）
                for _ in range(100):
                    if not app.scanning:
                        break
                    await pilot.pause()
                assert app.scanning is False
                assert len(app.variants) == 18  # sample.vcf 全量，不丢不重
                assert len(app.view) == 18
                ol = app.query_one("#variant-list", OptionList)
                assert ol.option_count == 18
        run(_t())

    def test_scan_aborts_on_exit(self, tmp_path):
        """退出应用后扫描线程停止（不挂起）。"""
        # 生成 2 万条使续扫需要一定时间
        f = tmp_path / "m.vcf"
        lines = ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]
        lines += [f"chr1\t{i}\t.\tA\tG\t50\tPASS\t." for i in range(1, 20_001)]
        f.write_text("\n".join(lines) + "\n")
        meta, head, skipped, cont = scan_vcf_quick(f, limit=10)
        async def _t():
            app = VcfBrowser(f, initial=(meta, head, skipped, cont))
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
            # 退出后 scanning 标志应被置 False（on_unmount）
            assert app.scanning is False
        run(_t())


# ──────────────────────────────────────────────
# 批次追加不重置浏览位置（回归：列表周期性跳顶）
# ──────────────────────────────────────────────
class TestBatchAppendPositionStability:
    @staticmethod
    def _make_vcf(tmp_path, n):
        f = tmp_path / "pos.vcf"
        lines = ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]
        lines += [f"chr1\t{1000 + i * 10}\t.\tA\tG\t50\tPASS\t." for i in range(n)]
        f.write_text("\n".join(lines) + "\n")
        return f

    def test_batch_append_never_resets_position(self, tmp_path):
        """窗口不在尾部时，批次追加不触碰列表：高亮/窗口/物化数均不变。"""
        f = self._make_vcf(tmp_path, 1000)
        meta, head, skipped, cont = scan_vcf_quick(f, limit=500)
        from seqviz.vcf import scan_vcf_resume
        tail, _ = scan_vcf_resume(f, cont)

        async def _t():
            app = VcfBrowser(f, initial=(meta, head, skipped, -1))
            app.scanning = True  # 手工驱动批次，不启动后台线程
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                assert ol.option_count == app.WINDOW  # 500 条只物化 400
                for _ in range(50):
                    await pilot.press("j")
                await pilot.pause()
                before = (app._win_start, ol.highlighted, app._abs_index())
                app._append_batch(tail[:250])
                await pilot.pause()
                after = (app._win_start, ol.highlighted, app._abs_index())
                assert before == after  # 位置零变化（无 clear 重建）
                assert ol.option_count == app.WINDOW  # 窗口不在尾部 → 不追加选项
                assert len(app.view) == 750
                app.scanning = False
        run(_t())

    def test_batch_append_incremental_at_tail(self, tmp_path):
        """窗口贴尾部且未填满：增量 add_options（非 clear 重建），高亮不变。"""
        meta, head, skipped, cont = scan_vcf_quick(SAMPLE_VCF, limit=2)
        from seqviz.vcf import scan_vcf_resume
        tail, _ = scan_vcf_resume(SAMPLE_VCF, cont)

        async def _t():
            app = VcfBrowser(SAMPLE_VCF, initial=(meta, head, skipped, -1))
            app.scanning = True
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                await pilot.press("j")
                await pilot.pause()
                hl_before = ol.highlighted
                app._append_batch(tail)  # 16 条，窗口未满 → 增量补充
                await pilot.pause()
                assert ol.option_count == 18  # 全部补齐
                assert ol.highlighted == hl_before  # 高亮未被重置
                app.scanning = False
        run(_t())


# ──────────────────────────────────────────────
# 滚动条诚实性（回归：拖到底只见 chr1:17,065）
# ──────────────────────────────────────────────
class TestScrollbarHonesty:
    def test_large_list_hides_scrollbar(self, tmp_path):
        """大列表（>WINDOW）永不显示滚动条，避免虚假的“拖到底=全部末尾”暗示。"""
        f = tmp_path / "big.vcf"
        lines = ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]
        lines += [f"chr1\t{i}\t.\tA\tG\t50\tPASS\t." for i in range(1, 1001)]
        f.write_text("\n".join(lines) + "\n")
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                assert len(app.view) == 1000 > app.WINDOW
                assert ol.show_scrollbar is False
        run(_t())

    def test_small_list_shows_scrollbar(self):
        """小列表全量物化，滚动条正常显示。"""
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                assert len(app.view) == 18 <= app.WINDOW
                assert ol.show_scrollbar is True
        run(_t())

    def test_filter_to_small_restores_scrollbar(self, tmp_path):
        """过滤后列表变小（≤WINDOW）时滚动条恢复。"""
        f = tmp_path / "mixed.vcf"
        lines = ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]
        lines += [f"chr1\t{i}\t.\tA\tG\t50\tPASS\t." for i in range(1, 501)]
        lines += [f"chr1\t{i}\t.\tA\tG\t50\tLowQual\t." for i in range(1001, 1401)]
        f.write_text("\n".join(lines) + "\n")
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                assert ol.show_scrollbar is False  # 900 条 > WINDOW
                await pilot.press("f")  # PASS → 500 条 > WINDOW
                await pilot.pause()
                assert ol.show_scrollbar is False
                await pilot.press("f")  # SNP → 900 条
                await pilot.press("f")  # InDel → 0 条 ≤ WINDOW
                await pilot.pause()
                assert ol.show_scrollbar is True
        run(_t())


# ──────────────────────────────────────────────
# 扫描完成后 G 到真实末尾（回归：底部数据不完整）
# ──────────────────────────────────────────────
class TestEndAfterScan:
    def test_G_reaches_true_last_variant(self):
        """后台扫描完成后，G 应定位到最后一条变异（非 400 条缓冲尾部）。"""
        meta, head, skipped, cont = scan_vcf_quick(SAMPLE_VCF, limit=2)
        async def _t():
            app = VcfBrowser(SAMPLE_VCF, initial=(meta, head, skipped, cont))
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                for _ in range(200):
                    if not app.scanning:
                        break
                    await pilot.pause()
                assert not app.scanning
                assert len(app.variants) == 18
                await pilot.press("G")
                await pilot.pause()
                v = app.variants[app.view[app._abs_index()]]
                assert (v.chrom, v.pos) == ("chr3", 33333)  # 真实末尾
                assert "33,333" in app._detail_text()
        run(_t())

    def test_position_indicator_updates(self):
        """位置指示器（副标题）随导航更新。"""
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                assert app.sub_title == "1 / 18"
                await pilot.press("j")
                await pilot.pause()
                assert app.sub_title == "2 / 18"
                await pilot.press("G")
                await pilot.pause()
                assert app.sub_title == "18 / 18"
        run(_t())

    def test_wheel_moves_position_on_large_list(self, tmp_path):
        """大列表滚轮 = 移动浏览位置（窗口平移），非缓冲内视口滚动。"""
        f = tmp_path / "w.vcf"
        lines = ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]
        lines += [f"chr1\t{i}\t.\tA\tG\t50\tPASS\t." for i in range(1, 1001)]
        f.write_text("\n".join(lines) + "\n")
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                assert app._abs_index() == 0
                ol = app.query_one("#variant-list", OptionList)
                ol.scroll_down()  # 滚轮下滚
                await pilot.pause()
                assert app._abs_index() == 3
                ol.scroll_up()
                await pilot.pause()
                assert app._abs_index() == 0
        run(_t())


# ──────────────────────────────────────────────
# 坐标/范围跳转（/ 命令栏）
# ──────────────────────────────────────────────
class TestCoordJump:
    @staticmethod
    def _capture_notify(app) -> list:
        """包装 app.notify 捕获消息（Notifications 对象不提供读取接口）。"""
        msgs: list = []
        orig = app.notify

        def capture(message, *args, **kwargs):
            msgs.append(str(message))
            return orig(message, *args, **kwargs)

        app.notify = capture
        return msgs

    async def _search(self, pilot, query: str):
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press(*query)
        await pilot.press("enter")
        await pilot.pause()

    def test_exact_coord_jump(self):
        """精确坐标：chr1:15892 命中 rs67890。"""
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            msgs = self._capture_notify(app)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await self._search(pilot, "chr1:15892")
                v = app.variants[app.view[app._abs_index()]]
                assert (v.chrom, v.pos, v.id) == ("chr1", 15892, "rs67890")
                assert "跳转到 chr1:15,892" in msgs[-1]
        run(_t())

    def test_nearest_coord_jump(self):
        """最近邻：chr1:10300 → 10234（跞66）而非 10567（跞267）。"""
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await self._search(pilot, "chr1:10300")
                v = app.variants[app.view[app._abs_index()]]
                assert v.pos == 10234
                # 反方向最近邻：10500 → 10567
                await self._search(pilot, "chr1:10500")
                v = app.variants[app.view[app._abs_index()]]
                assert v.pos == 10567
        run(_t())

    def test_range_jump_first_in_range(self, tmp_path):
        """范围跳转：命中区间内第一个变异（两种分隔符）。"""
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await self._search(pilot, "chr1:11000-40000")
                v = app.variants[app.view[app._abs_index()]]
                assert v.pos == 15892  # [11000,40000] 内第一条
                await self._search(pilot, "chr2:20000..50000")
                v = app.variants[app.view[app._abs_index()]]
                assert (v.chrom, v.pos) == ("chr2", 23456)
        run(_t())

    def test_range_no_match_warns(self):
        """范围内无变异：提示该范围内无变异。"""
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            msgs = self._capture_notify(app)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await self._search(pilot, "chr1:50000000-60000000")
                assert "该范围内无变异" in msgs[-1]
        run(_t())

    def test_chrom_without_variants_warns(self):
        """不存在的染色体单坐标：提示未找到。"""
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            msgs = self._capture_notify(app)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await self._search(pilot, "chrX:100")
                assert "未找到" in msgs[-1]
        run(_t())

    def test_invalid_format_falls_back_to_id_search(self):
        """格式错误（chr1:abc）回退 ID 搜索 → 未找到匹配。"""
        async def _t():
            app = VcfBrowser(SAMPLE_VCF)
            msgs = self._capture_notify(app)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await self._search(pilot, "chr1:abc")
                assert "未找到匹配" in msgs[-1]
        run(_t())

    def test_coord_jump_shifts_window_on_large_list(self, tmp_path):
        """大列表（窗口化）坐标跳转：跨窗口平移且详情同步。"""
        f = tmp_path / "c.vcf"
        lines = ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]
        lines += [f"chr1\t{i}\t.\tA\tG\t50\tPASS\t." for i in range(1, 1001)]
        f.write_text("\n".join(lines) + "\n")
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await self._search(pilot, "chr1:800")
                assert app._abs_index() == 799  # pos=800 是第 800 条
                assert app._win_start > 0       # 窗口已平移
                assert "800" in app._detail_text()
        run(_t())

    def test_scanning_suffix_in_message(self, tmp_path):
        """扫描中搜索：提示含（当前已索引 N 条）。"""
        f = tmp_path / "s.vcf"
        lines = ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                 "chr1\t100\t.\tA\tG\t50\tPASS\t."]
        f.write_text("\n".join(lines) + "\n")
        async def _t():
            app = VcfBrowser(f)
            msgs = self._capture_notify(app)
            app.scanning = True  # 模拟扫描中
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await self._search(pilot, "chr9:1-2")
                assert "该范围内无变异" in msgs[-1]
                assert "当前已索引" in msgs[-1]
                app.scanning = False
        run(_t())


# ──────────────────────────────────────────────
# 真实比例滚动条（遗留建议：映射全量 view）
# ──────────────────────────────────────────────
class TestAbsoluteScrollbar:
    def test_visibility_follows_list_size(self, tmp_path):
        """大列表显示真实比例滚动条，小列表隐藏。"""
        f = tmp_path / "b.vcf"
        lines = ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]
        lines += [f"chr1\t{i}\t.\tA\tG\t50\tPASS\t." for i in range(1, 1001)]
        f.write_text("\n".join(lines) + "\n")
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                sb = app.query_one("#abs-scrollbar", AbsoluteScrollbar)
                assert str(sb.styles.display) == "block"  # 1000 > WINDOW
                rendered = str(sb.render())
                assert "█" in rendered and "░" in rendered  # 滑块 + 轨道
            # 小列表：隐藏
            app2 = VcfBrowser(SAMPLE_VCF)
            async with app2.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                sb2 = app2.query_one("#abs-scrollbar", AbsoluteScrollbar)
                assert str(sb2.styles.display) == "none"  # 18 ≤ WINDOW
        run(_t())

    def test_jump_to_maps_full_view(self, tmp_path):
        """点击映射全量 view：底部 → 最后一条，中部 → 中位附近。"""
        f = tmp_path / "j.vcf"
        lines = ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]
        lines += [f"chr1\t{i * 100}\t.\tA\tG\t50\tPASS\t." for i in range(1, 5001)]
        f.write_text("\n".join(lines) + "\n")
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                sb = app.query_one("#abs-scrollbar", AbsoluteScrollbar)
                sb._jump_to(sb.size.height)  # 底部
                await pilot.pause()
                assert app._abs_index() == len(app.view) - 1 == 4999
                sb._jump_to(0)  # 顶部
                await pilot.pause()
                assert app._abs_index() == 0
        run(_t())

    def test_thumb_position_tracks_navigation(self, tmp_path):
        """导航后滑块位置同步（渲染内容随位置变化）。"""
        f = tmp_path / "n.vcf"
        lines = ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]
        lines += [f"chr1\t{i}\t.\tA\tG\t50\tPASS\t." for i in range(1, 2001)]
        f.write_text("\n".join(lines) + "\n")
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                sb = app.query_one("#abs-scrollbar", AbsoluteScrollbar)
                top_render = str(sb.render())
                await pilot.press("G")
                await pilot.pause()
                sb.refresh()
                bottom_render = str(sb.render())
                assert top_render != bottom_render  # 滑块已移动
        run(_t())


# ──────────────────────────────────────────────
# 大文件窗口化虚拟化（回归：全量重建 OptionList 冻结 UI）
# ──────────────────────────────────────────────
class TestWindowedVirtualization:
    @staticmethod
    def _make_big_vcf(tmp_path, n=5000):
        lines = ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]
        for i in range(n):
            lines.append(f"chr1\t{1000 + i}\t.\tA\tG\t50.0\tPASS\tDP=10")
        f = tmp_path / "big.vcf"
        f.write_text("\n".join(lines) + "\n")
        return f

    def test_window_caps_materialized_options(self, tmp_path):
        """列表只物化 WINDOW 条，而非全量。"""
        f = self._make_big_vcf(tmp_path)
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                assert len(app.view) == 5000
                assert ol.option_count == app.WINDOW  # 只物化窗口
        run(_t())

    def test_G_jumps_to_last_across_windows(self, tmp_path):
        """G 键跨窗口跳到最后一条，绝对下标正确。"""
        f = self._make_big_vcf(tmp_path)
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("G")
                await pilot.pause()
                assert app._abs_index() == 4999
                assert "5,999" in app._detail_text()  # 最后一条 pos=1000+4999（千分位）
                await pilot.press("g")
                await pilot.pause()
                assert app._abs_index() == 0
        run(_t())

    def test_filter_rebuild_is_windowed(self, tmp_path):
        """过滤切换后列表仍只物化窗口大小（不再全量重建）。"""
        f = self._make_big_vcf(tmp_path)
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("f")  # PASS only（全部 PASS）
                await pilot.pause()
                ol = app.query_one("#variant-list", OptionList)
                assert len(app.view) == 5000
                assert ol.option_count == app.WINDOW
        run(_t())


# ──────────────────────────────────────────────
# 染色体排序（回归：chr10 字典序排在 chr2 前）
# ──────────────────────────────────────────────
class TestChromNaturalSort:
    def test_position_sort_natural_order(self, tmp_path):
        f = tmp_path / "sort.vcf"
        f.write_text(
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "chr10\t100\t.\tA\tG\t50\tPASS\t.\n"
            "chr2\t50\t.\tA\tG\t50\tPASS\t.\n"
            "chr1\t999\t.\tA\tG\t50\tPASS\t.\n"
        )
        async def _t():
            app = VcfBrowser(f)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                order = [app.variants[i].chrom for i in app.view]
                assert order == ["chr1", "chr2", "chr10"]  # 非字典序的 chr1,chr10,chr2
        run(_t())
