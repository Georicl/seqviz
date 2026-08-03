"""文件选择器测试：目录扫描、文件列表、多选、全选、打开、取消、预览"""

import asyncio
from pathlib import Path

from seqviz.file_browser import (
    FileBrowser,
    FileInfo,
    is_sequence_file,
    scan_directory,
    format_size,
    detect_file_format,
)
from seqviz.browser import FileFormat

TEST_DIR = Path(__file__).parent


def run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────
# 文件识别与扫描
# ──────────────────────────────────────────────
class TestFileDetection:
    def test_fasta_extensions(self, tmp_path):
        for ext in [".fa", ".fasta", ".fna", ".faa", ".aa", ".seq"]:
            f = tmp_path / f"seq{ext}"
            f.write_text(">s\nAT\n")
            assert is_sequence_file(f), f"{ext} 应被识别"

    def test_fastq_extensions(self, tmp_path):
        for ext in [".fq", ".fastq"]:
            f = tmp_path / f"reads{ext}"
            f.write_text("@r\nAT\n+\nII\n")
            assert is_sequence_file(f), f"{ext} 应被识别"

    def test_gz_double_extension(self, tmp_path):
        f = tmp_path / "seq.fa.gz"
        f.write_bytes(b"")
        assert is_sequence_file(f)

    def test_vcf_recognized(self, tmp_path):
        f = tmp_path / "var.vcf"
        f.write_text("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        assert is_sequence_file(f)

    def test_vcf_gz_excluded(self, tmp_path):
        """压缩 VCF 暂不支持，不应被列入文件选择器（避免误标为 FASTA/计数0）。"""
        f = tmp_path / "var.vcf.gz"
        f.write_bytes(b"")
        assert not is_sequence_file(f)

    def test_non_sequence_file(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello")
        assert not is_sequence_file(f)

    def test_directory_not_file(self, tmp_path):
        assert not is_sequence_file(tmp_path)

    def test_detect_format_fasta(self, tmp_path):
        f = tmp_path / "seq.fasta"
        f.write_text(">s\nAT\n")
        assert detect_file_format(f) == FileFormat.FASTA

    def test_detect_format_fastq(self, tmp_path):
        f = tmp_path / "reads.fastq"
        f.write_text("@r\nAT\n+\nII\n")
        assert detect_file_format(f) == FileFormat.FASTQ

    def test_detect_format_by_content(self, tmp_path):
        # 后缀不明确，靠首字符判断
        f = tmp_path / "data.xyz"
        f.write_text("@r\nAT\n+\nII\n")
        assert detect_file_format(f) == FileFormat.FASTQ


class TestScanDirectory:
    def test_scan_finds_sequence_files(self):
        files = scan_directory(TEST_DIR)
        names = {f.name for f in files}
        assert "test.fa" in names
        assert "test_fastq.fastq" in names
        assert "test_protein.fa" in names

    def test_scan_excludes_non_sequence(self):
        files = scan_directory(TEST_DIR)
        names = {f.name for f in files}
        assert "test.py" not in names

    def test_scan_returns_fileinfo(self):
        files = scan_directory(TEST_DIR)
        assert all(isinstance(f, FileInfo) for f in files)
        # 每个文件有大小和格式
        for f in files:
            assert f.size >= 0
            assert f.fmt in (FileFormat.FASTA, FileFormat.FASTQ)

    def test_scan_empty_dir(self, tmp_path):
        assert scan_directory(tmp_path) == []

    def test_format_size(self):
        assert format_size(500) == "500B"
        assert format_size(1500) == "1.5K"
        assert format_size(1_500_000) == "1.5M"
        assert format_size(1_500_000_000) == "1.5G"


# ──────────────────────────────────────────────
# 文件选择器交互
# ──────────────────────────────────────────────
class TestFileBrowserInteraction:
    def test_launch_lists_files(self):
        async def _t():
            app = FileBrowser(TEST_DIR)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert len(app.files) > 0
                ol = app.query_one("#file-list")
                assert ol.option_count == len(app.files)
        run(_t())

    def test_select_toggle(self):
        async def _t():
            app = FileBrowser(TEST_DIR)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert len(app.selected) == 0
                await pilot.press("space")
                await pilot.pause()
                assert len(app.selected) == 1
                await pilot.press("space")  # 再按取消
                await pilot.pause()
                assert len(app.selected) == 0
        run(_t())

    def test_select_all(self):
        async def _t():
            app = FileBrowser(TEST_DIR)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                assert len(app.selected) == len(app.files)
                await pilot.press("a")  # 再按取消全选
                await pilot.pause()
                assert len(app.selected) == 0
        run(_t())

    def test_enter_opens_selected(self):
        async def _t():
            app = FileBrowser(TEST_DIR)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("space")  # 选中第一个
                await pilot.press("enter")
                await pilot.pause()
                assert len(app.return_value) == 1
                assert isinstance(app.return_value[0], Path)
        run(_t())

    def test_enter_without_selection_opens_highlighted(self):
        async def _t():
            app = FileBrowser(TEST_DIR)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("enter")  # 无多选，打开高亮项
                await pilot.pause()
                assert len(app.return_value) == 1
        run(_t())

    def test_multi_select_opens_multiple(self):
        async def _t():
            app = FileBrowser(TEST_DIR)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("space")
                await pilot.press("j")
                await pilot.press("space")
                await pilot.press("enter")
                await pilot.pause()
                assert len(app.return_value) == 2
        run(_t())

    def test_quit_cancels(self):
        async def _t():
            app = FileBrowser(TEST_DIR)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("q")
                await pilot.pause()
                assert app.return_value == []
        run(_t())

    def test_navigation_moves_highlight(self):
        async def _t():
            app = FileBrowser(TEST_DIR)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                ol = app.query_one("#file-list")
                initial = ol.highlighted if ol.highlighted is not None else -1
                await pilot.press("j")
                await pilot.pause()
                assert ol.highlighted == initial + 1
        run(_t())


# ──────────────────────────────────────────────
# 序列计数（预览面板数据来源）
# ──────────────────────────────────────────────
class TestCountSequences:
    def test_count_fasta(self, tmp_path):
        import threading
        from seqviz.file_browser import count_sequences
        p = tmp_path / "x.fa"
        p.write_text("".join(f">s{i}\nACGT\n" for i in range(7)))
        assert count_sequences(p, FileFormat.FASTA) == 7
        # 显式传入未置位的取消事件不影响结果
        assert count_sequences(p, FileFormat.FASTA, threading.Event()) == 7

    def test_count_fastq(self, tmp_path):
        from seqviz.file_browser import count_sequences
        p = tmp_path / "x.fastq"
        p.write_text("".join(f"@r{i}\nACGT\n+\nIIII\n" for i in range(5)))
        assert count_sequences(p, FileFormat.FASTQ) == 5

    def test_count_gzip(self, tmp_path):
        import gzip
        from seqviz.file_browser import count_sequences
        p = tmp_path / "x.fa.gz"
        with gzip.open(p, "wt") as f:
            f.write("".join(f">s{i}\nACGT\n" for i in range(3)))
        assert count_sequences(p, FileFormat.FASTA) == 3

    def test_count_empty_file(self, tmp_path):
        from seqviz.file_browser import count_sequences
        p = tmp_path / "empty.fa"
        p.write_text("")
        assert count_sequences(p, FileFormat.FASTA) == 0

    def test_count_missing_file_returns_zero(self, tmp_path):
        from seqviz.file_browser import count_sequences
        assert count_sequences(tmp_path / "nope.fa", FileFormat.FASTA) == 0

    def test_cancel_event_interrupts_large_count(self, tmp_path):
        """取消事件置位后应尽早中断（返回值小于完整计数）。"""
        import threading
        from seqviz.file_browser import count_sequences
        p = tmp_path / "big.fa"
        p.write_text("".join(f">s{i}\nA\n" for i in range(20000)))
        ev = threading.Event()
        ev.set()
        assert count_sequences(p, FileFormat.FASTA, ev) < 20000
