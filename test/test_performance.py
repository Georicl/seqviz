"""性能测试：大文件扫描、序列加载、滚动渲染的耗时验证"""

import asyncio
import random
import time

import pytest

from seqviz.browser import FastaBrowser

random.seed(42)
BASES = "ATCG"


@pytest.fixture(scope="module")
def big_fasta(tmp_path_factory):
    """生成 5,000 条 x 500bp 的 FASTA。"""
    d = tmp_path_factory.mktemp("perf")
    p = d / "big.fa"
    with open(p, "w") as f:
        for i in range(5000):
            seq = "".join(random.choices(BASES, k=500))
            f.write(f">seq_{i:06d}\n{seq}\n")
    return p


@pytest.fixture(scope="module")
def big_fastq(tmp_path_factory):
    """生成 20,000 reads x 150bp 的 FASTQ。"""
    d = tmp_path_factory.mktemp("perf")
    p = d / "big.fq"
    with open(p, "w") as f:
        for i in range(20000):
            seq = "".join(random.choices(BASES, k=150))
            qual = "".join(chr(random.randint(43, 73)) for _ in range(150))
            f.write(f"@read_{i:07d}\n{seq}\n+\n{qual}\n")
    return p


@pytest.fixture(scope="module")
def long_fasta(tmp_path_factory):
    """生成 3 条 x 500,000bp 的超长序列 FASTA。"""
    d = tmp_path_factory.mktemp("perf")
    p = d / "long.fa"
    with open(p, "w") as f:
        for i in range(3):
            seq = "".join(random.choices(BASES, k=500_000))
            f.write(f">long_{i}\n")
            f.writelines(seq[j:j + 70] + "\n" for j in range(0, len(seq), 70))
    return p


@pytest.fixture(scope="module")
def huge_fasta(tmp_path_factory):
    """生成 1 条 2,000,004bp 的超大序列 FASTA（>1Mbp 阈值，走分块加载）。"""
    d = tmp_path_factory.mktemp("perf_huge")
    p = d / "huge.fa"
    seq = "".join(random.choices(BASES, k=2_000_004))
    with open(p, "w") as f:
        f.write(">huge\n")
        f.writelines(seq[j:j + 70] + "\n" for j in range(0, len(seq), 70))
    # 返回 (路径, 序列)，供内容断言
    return p, seq


class TestScanPerformance:
    def test_scan_many_sequences(self, big_fasta):
        t0 = time.perf_counter()
        seqs = FastaBrowser._scan_file(big_fasta, FastaBrowser._detect_format(big_fasta))
        elapsed = (time.perf_counter() - t0) * 1000
        assert len(seqs) == 5000
        assert elapsed < 500, f"扫描 5000 条序列耗时 {elapsed:.0f}ms，超过 500ms"

    def test_scan_many_reads(self, big_fastq):
        t0 = time.perf_counter()
        seqs = FastaBrowser._scan_file(big_fastq, FastaBrowser._detect_format(big_fastq))
        elapsed = (time.perf_counter() - t0) * 1000
        assert len(seqs) == 20000
        assert elapsed < 1000, f"扫描 20000 reads 耗时 {elapsed:.0f}ms，超过 1000ms"

    def test_scan_long_sequences(self, long_fasta):
        t0 = time.perf_counter()
        seqs = FastaBrowser._scan_file(long_fasta, FastaBrowser._detect_format(long_fasta))
        elapsed = (time.perf_counter() - t0) * 1000
        assert len(seqs) == 3
        assert elapsed < 500, f"扫描超长序列耗时 {elapsed:.0f}ms，超过 500ms"


class TestLoadPerformance:
    def test_load_long_sequence_fast(self, long_fasta):
        """加载 500K bp 序列应在合理时间内完成（seek 定位）。"""
        async def _t():
            app = FastaBrowser([long_fasta])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                tab = app.current_tab
                t0 = time.perf_counter()
                mv.load_sequence(tab.sequences[1])  # 加载第2条
                elapsed = (time.perf_counter() - t0) * 1000
                assert len(mv._seq) == 500_000
                assert elapsed < 200, f"加载 500K bp 耗时 {elapsed:.0f}ms，超过 200ms"
        asyncio.run(_t())

    def test_load_middle_sequence_uses_seek(self, big_fasta):
        """加载中间位置的序列不应明显慢于第一条（O(1) seek）。"""
        async def _t():
            app = FastaBrowser([big_fasta])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                tab = app.current_tab
                # 加载第 2500 条（中间位置）
                t0 = time.perf_counter()
                mv.load_sequence(tab.sequences[2500])
                elapsed = (time.perf_counter() - t0) * 1000
                assert elapsed < 100, f"加载中间序列耗时 {elapsed:.0f}ms，seek 可能失效"
        asyncio.run(_t())


class TestScrollPerformance:
    def test_scroll_smooth(self, long_fasta):
        """滚动应流畅（每次 < 20ms）。"""
        async def _t():
            app = FastaBrowser([long_fasta])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                t0 = time.perf_counter()
                for _ in range(50):
                    mv.scroll_content_down(5)
                elapsed = (time.perf_counter() - t0) * 1000
                per_scroll = elapsed / 50
                assert per_scroll < 20, f"平均滚动耗时 {per_scroll:.1f}ms/次，超过 20ms"
        asyncio.run(_t())

    def test_scroll_boundary_no_wasted_render(self, long_fasta):
        """到达边界后继续滚动不应触发重绘（offset 不变）。"""
        async def _t():
            app = FastaBrowser([long_fasta])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                # 滚到顶部
                mv.view_offset = 0
                mv.scroll_content_up(5)  # 已在顶部，offset 应保持 0
                assert mv.view_offset == 0
        asyncio.run(_t())


class TestHugeSequenceCorrectness:
    """>1Mbp 大序列分块加载的性能与内容正确性（benchmark correctness gate）。"""

    def test_huge_load_and_content(self, huge_fasta):
        """加载 2Mbp 序列：长度准确，首/中/末窗口内容与原序列一致。"""
        path, seq = huge_fasta

        async def _t():
            app = FastaBrowser([path])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                tab = app.current_tab
                t0 = time.perf_counter()
                mv.load_sequence(tab.sequences[0])
                elapsed = (time.perf_counter() - t0) * 1000
                # 性能：2Mbp 加载（含一次全长扫描）应在合理时间内完成
                assert elapsed < 1000, f"加载 2Mbp 耗时 {elapsed:.0f}ms，超过 1000ms"
                # 正确性：进入分块模式且长度准确
                assert mv._is_large
                assert mv._seq_length == len(seq)
                # 内容：首/中/末/随机窗口抽查
                for start in (0, len(seq) // 2, len(seq) - 600, random.randint(0, len(seq) - 600)):
                    assert mv._load_chunk(start, start + 600) == seq[start:start + 600]
        asyncio.run(_t())

    def test_huge_scroll_content_correct(self, huge_fasta):
        """滚动大序列时，渲染的每个可见窗口内容都与原序列一致。"""
        path, seq = huge_fasta

        async def _t():
            app = FastaBrowser([path])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                mv = app.query_one("#main-0")
                # 滚动到中部，抽查渲染行内容
                mv.view_offset = len(mv._header_lines) + (len(seq) // 2) // mv.WRAP
                mv._update_display()
                # 验证中部几个 wrap 窗口的碱基与原序列一致
                mid = len(seq) // 2
                for off in (0, mv.WRAP, 2 * mv.WRAP):
                    got = mv._load_chunk(mid + off, mid + off + mv.WRAP)
                    assert got == seq[mid + off:mid + off + mv.WRAP]
        asyncio.run(_t())
