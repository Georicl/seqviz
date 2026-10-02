"""序列读取器的坐标、缓存、长行与取消行为。"""

import asyncio
import random
from pathlib import Path

from seqviz.core.formats import FileFormat
from seqviz.core.index import scan_file
from seqviz.core.sequence_reader import SequenceReader

random.seed(2026)


def run(coro):
    return asyncio.run(coro)


def _reader(path: Path, fmt: FileFormat) -> tuple[SequenceReader, list]:
    """直接测试读取器，不启动 Textual。"""
    recs = scan_file(path, fmt)
    v = SequenceReader(path, fmt)
    return v, recs


# ──────────────────────────────────────────────
# Issue #3：CRLF / UTF-8 header 的 offset 正确性
# ──────────────────────────────────────────────
class TestCrlfOffsets:
    def test_crlf_fasta_offsets(self, tmp_path):
        p = tmp_path / "crlf.fa"
        p.write_bytes(b">one\r\nAAAA\r\n>two\r\nCCCC\r\n")
        recs = scan_file(p, FileFormat.FASTA)
        assert [r.offset for r in recs] == [0, 12]  # 每个 offset 落在 '>' 字节上

        v, _ = _reader(p, FileFormat.FASTA)
        v.load_sequence(recs[1])
        assert v.sequence == "CCCC"
        assert v.length == 4

    def test_crlf_utf8_header(self, tmp_path):
        p = tmp_path / "utf8.fa"
        p.write_bytes(">序列一 描述\r\nATCG\r\n>序列二\r\nGGGGTTTT\r\n".encode())
        recs = scan_file(p, FileFormat.FASTA)
        # offset 必须落在每个 '>' 的字节位置
        raw = p.read_bytes()
        assert all(raw[r.offset : r.offset + 1] == b">" for r in recs)
        assert recs[0].header == "序列一 描述"
        assert recs[1].header == "序列二"

        v, _ = _reader(p, FileFormat.FASTA)
        v.load_sequence(recs[1])
        assert v.sequence == "GGGGTTTT"

    def test_crlf_fastq_offsets(self, tmp_path):
        p = tmp_path / "crlf.fastq"
        p.write_bytes(b"@r1\r\nAAAA\r\n+\r\nIIII\r\n@r2\r\nTTTT\r\n+\r\nJJJJ\r\n")
        recs = scan_file(p, FileFormat.FASTQ)
        assert [r.offset for r in recs] == [0, 20]

        v, _ = _reader(p, FileFormat.FASTQ)
        v.load_sequence(recs[1])
        assert v.sequence == "TTTT"
        assert v.quality == "JJJJ"

    def test_lf_crlf_equivalent(self, tmp_path):
        """LF 与 CRLF 同内容文件应解析出相同的记录与序列。"""
        lf = tmp_path / "lf.fa"
        crlf = tmp_path / "crlf.fa"
        lf.write_bytes(b">a\nATCG\n>b\nGGCC\n")
        crlf.write_bytes(b">a\r\nATCG\r\n>b\r\nGGCC\r\n")
        recs_lf = scan_file(lf, FileFormat.FASTA)
        recs_crlf = scan_file(crlf, FileFormat.FASTA)
        assert [r.header for r in recs_lf] == [r.header for r in recs_crlf]

        for path, recs in ((lf, recs_lf), (crlf, recs_crlf)):
            v, _ = _reader(path, FileFormat.FASTA)
            v.load_sequence(recs[1])
            assert v.sequence == "GGCC"


class TestLargeSeqChunking:
    def test_viewport_reads_nonuniform_sequence_once(self, tmp_path):
        """一屏连续行只回扫一次 checkpoint，跳转、缩放和切换后仍显示正确内容。"""
        seq = "ACGTTGCA" * 160_000
        p = tmp_path / "window.fa"
        with p.open("w") as f:
            for header, bases in (
                ("one", seq),
                ("two", seq.translate(str.maketrans("ACGT", "TGCA"))),
            ):
                f.write(f">{header}\n")
                start = 0
                line = 0
                while start < len(bases):
                    width = (60, 59)[line % 2]
                    f.write(bases[start : start + width] + "\n")
                    start += width
                    line += 1

        view, recs = _reader(p, FileFormat.FASTA)
        view.set_window_size(60 * 30)
        view.load_sequence(recs[0])

        class CountedReader:
            def __init__(self, f):
                self.f = f
                self.bytes_read = 0

            def __getattr__(self, name):
                return getattr(self.f, name)

            def readline(self, *args):
                raw = self.f.readline(*args)
                self.bytes_read += len(raw)
                return raw

        reader = CountedReader(view._get_fh())
        view._fh = reader
        try:
            # 模拟 30 行视口；读取量应只包含一次 checkpoint 回扫。
            for start in range(900_000, 901_800, 60):
                assert view.read_range(start, start + 60) == seq[start : start + 60]
            assert reader.bytes_read < 1_000_000

            for start in (1_100_000, 300, len(seq) - 60):
                assert view.read_range(start, start + 60) == seq[start : start + 60]

            view.set_window_size(37 * 30)
            for start in range(900_000, 900_740, 37):
                assert view.read_range(start, start + 37) == seq[start : start + 37]

            view.load_sequence(recs[1])
            second = seq.translate(str.maketrans("ACGT", "TGCA"))
            assert view.read_range(900_000, 900_060) == second[900_000:900_060]
        finally:
            view.close()

    def test_large_fasta_length_and_content(self, tmp_path):
        """>1Mbp 固定行宽：长度准确，首/中/末窗口内容正确。"""
        seq = "".join(random.choices("ATCG", k=1_200_000))
        p = tmp_path / "large.fa"
        with p.open("w") as f:
            f.write(">large\n")
            for i in range(0, len(seq), 70):
                f.write(seq[i : i + 70] + "\n")

        v, recs = _reader(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert v.is_large
        assert v.length == len(seq)
        # 首 / 中 / 末 / 随机窗口抽查
        for start in (
            0,
            len(seq) // 2,
            len(seq) - 600,
            random.randint(0, len(seq) - 600),
        ):
            assert v.read_range(start, start + 600) == seq[start : start + 600]

    def test_variable_line_width(self, tmp_path):
        """可变行宽（70/60/50 交替）：长度准确，_load_chunk 不错位。"""
        seq = "ATCGGCTA" * 150_000  # 1,200,000 bp
        p = tmp_path / "varwidth.fa"
        with p.open("w") as f:
            f.write(">varwidth\n")
            i = k = 0
            while i < len(seq):
                w = (70, 60, 50)[k % 3]
                f.write(seq[i : i + w] + "\n")
                i += w
                k += 1

        v, recs = _reader(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert v.length == len(seq)
        assert v._uniform_lines is False  # 检测到非等宽
        for start in (0, 1000, 600_000, len(seq) - 60):
            assert v.read_range(start, start + 60) == seq[start : start + 60]

    def test_unwrapped_then_wrapped_sequence(self, tmp_path):
        """超长单行后接普通短行，跨越虚拟读取块时仍按真实坐标取序列。"""
        seq = "ATCG" * 300_000
        p = tmp_path / "mixed_width.fa"
        with p.open("w") as f:
            f.write(">mixed\n")
            f.write(seq[:1_100_000] + "\n")
            for i in range(1_100_000, len(seq), 70):
                f.write(seq[i : i + 70] + "\n")

        v, recs = _reader(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert v.length == len(seq)
        for start in (1_099_940, 1_100_000, len(seq) - 60):
            assert v.read_range(start, start + 60) == seq[start : start + 60]

    def test_blank_lines_in_record(self, tmp_path):
        """记录内部含空行：长度准确（空行不计），_load_chunk 不错位。"""
        seq = "".join(random.choices("ATCG", k=1_100_000))
        p = tmp_path / "blank.fa"
        with p.open("w") as f:
            f.write(">blank\n")
            for idx, i in enumerate(range(0, len(seq), 70)):
                f.write(seq[i : i + 70] + "\n")
                if idx % 100 == 99:
                    f.write("\n")  # 每 100 行插一个空行

        v, recs = _reader(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert v.length == len(seq)
        assert v._uniform_lines is False
        for start in (0, 600_000, len(seq) - 100):
            assert v.read_range(start, start + 60) == seq[start : start + 60]

    def test_length_cached_after_load(self, tmp_path):
        """加载后长度与行宽指标应回写 SequenceInfo，二次加载走缓存。"""
        seq = "ATCGATCG" * 250_000  # 2,000,000 bp
        p = tmp_path / "cache.fa"
        with p.open("w") as f:
            f.write(">big\n")
            for i in range(0, len(seq), 70):
                f.write(seq[i : i + 70] + "\n")

        v, recs = _reader(p, FileFormat.FASTA)
        assert recs[0].length == -1  # 扫描时不计算长度
        v.load_sequence(recs[0])
        assert recs[0].length == len(seq)  # 已回写
        assert recs[0].uniform is True
        assert recs[0].chars_per_line == 70
        # 二次加载仍正确
        v.load_sequence(recs[0])
        assert v.length == len(seq)
        assert v.read_range(123_456, 123_516) == seq[123_456:123_516]

    def test_last_line_longer_than_width(self, tmp_path):
        """末行比首行更长：必须判非等宽走 checkpoint 回退，否则尾部静默错位。"""
        seq = "".join(random.choices("ATCG", k=1_200_040))
        p = tmp_path / "longtail.fa"
        with p.open("w") as f:
            f.write(">longtail\n")
            # 前 19999 行每行 60bp（共 1,199,940），末行 100bp > 60bp
            for i in range(0, 1_199_940, 60):
                f.write(seq[i : i + 60] + "\n")
            f.write(seq[1_199_940:] + "\n")

        v, recs = _reader(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert v.is_large
        assert v.length == len(seq)
        assert v._uniform_lines is False  # 修复前误判为 True，尾部内容错位
        for start in (0, 600_000, 1_199_940, 1_200_000, len(seq) - 600):
            end = min(start + 600, len(seq))
            assert v.read_range(start, end) == seq[start:end]

    def test_leading_whitespace_not_uniform(self, tmp_path):
        """每行行首统一缩进空白：必须判非等宽，否则等宽换算整条错位。"""
        seq = "".join(random.choices("ATCG", k=1_200_000))
        p = tmp_path / "indent.fa"
        with p.open("w") as f:
            f.write(">indent\n")
            for i in range(0, len(seq), 60):
                f.write("  " + seq[i : i + 60] + "\n")

        v, recs = _reader(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert v.is_large
        assert v.length == len(seq)
        assert v._uniform_lines is False  # 修复前误判为 True，内容错位
        for start in (0, 1000, 600_000, len(seq) - 100):
            assert v.read_range(start, start + 100) == seq[start : start + 100]

    def test_nonuniform_checkpoints_cached(self, tmp_path):
        """非等宽序列二次加载应复用缓存的 checkpoint，内容仍正确。"""
        seq = "ATCGGCTA" * 150_000  # 1,200,000 bp，行宽 70/60/50 交替
        p = tmp_path / "varwidth_cache.fa"
        with p.open("w") as f:
            f.write(">v\n")
            i = k = 0
            while i < len(seq):
                w = (70, 60, 50)[k % 3]
                f.write(seq[i : i + w] + "\n")
                i += w
                k += 1

        v, recs = _reader(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert recs[0].uniform is False
        assert recs[0].checkpoints is not None  # checkpoint 已缓存
        first_cps = recs[0].checkpoints
        # 二次加载：复用缓存的 checkpoint，内容仍正确
        v.load_sequence(recs[0])
        assert v._checkpoints is first_cps
        assert v._uniform_lines is False
        for start in (0, 600_000, len(seq) - 60):
            assert v.read_range(start, start + 60) == seq[start : start + 60]
