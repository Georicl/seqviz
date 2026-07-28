"""性能测试：大文件扫描、序列加载、滚动渲染的耗时验证"""

import asyncio
import random
import time
from pathlib import Path

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
            for j in range(0, len(seq), 70):
                f.write(seq[j:j + 70] + "\n")
    return p


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
