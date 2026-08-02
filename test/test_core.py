"""核心模块测试：parsers / seq_type / stats / renderer"""

import gzip
from pathlib import Path

import pytest
from rich.text import Text

from seqviz.parsers import parse_fasta
from seqviz.fastq import parse_fastq
from seqviz.seq_type import SeqType, detect_seq_type
from seqviz.stats import calc_sequence_stats, SequenceStats
from seqviz.renderer import (
    colorize_sequence,
    colorize_quality,
    quality_stats,
    quality_bar,
    position_ruler,
    DNA_COLORS,
)


# ──────────────────────────────────────────────
# parsers.parse_fasta
# ──────────────────────────────────────────────
class TestParseFasta:
    def test_basic(self, tmp_path):
        p = tmp_path / "seq.fa"
        p.write_text(">seq1\nATCG\n>seq2\nGGCC\n")
        records = list(parse_fasta(p))
        assert records == [("seq1", "ATCG"), ("seq2", "GGCC")]

    def test_multiline_sequence(self, tmp_path):
        p = tmp_path / "seq.fa"
        p.write_text(">seq1\nATCG\nATCG\nTTTT\n")
        records = list(parse_fasta(p))
        assert records == [("seq1", "ATCGATCGTTTT")]

    def test_header_with_description(self, tmp_path):
        p = tmp_path / "seq.fa"
        p.write_text(">seq1 some description here\nATCG\n")
        header, seq = list(parse_fasta(p))[0]
        assert header == "seq1 some description here"
        assert seq == "ATCG"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.fa"
        p.write_text("")
        assert list(parse_fasta(p)) == []

    def test_no_sequences_only_header(self, tmp_path):
        p = tmp_path / "h.fa"
        p.write_text(">only_header\n")
        records = list(parse_fasta(p))
        assert records == [("only_header", "")]

    def test_gzip_support(self, tmp_path):
        p = tmp_path / "seq.fa.gz"
        with gzip.open(p, "wt") as f:
            f.write(">seq1\nATCG\n")
        records = list(parse_fasta(p))
        assert records == [("seq1", "ATCG")]

    def test_gzip_uppercase_extension(self, tmp_path):
        """大写 .GZ 后缀也应透明解压（后缀大小写不敏感）。"""
        p = tmp_path / "seq.fa.GZ"
        with gzip.open(p, "wt") as f:
            f.write(">s\nAT\n")
        assert list(parse_fasta(p)) == [("s", "AT")]

    def test_accepts_str_path(self, tmp_path):
        p = tmp_path / "seq.fa"
        p.write_text(">s\nAT\n")
        assert list(parse_fasta(str(p))) == [("s", "AT")]

    def test_is_generator(self, tmp_path):
        p = tmp_path / "seq.fa"
        p.write_text(">s\nAT\n")
        import types
        assert isinstance(parse_fasta(p), types.GeneratorType)


# ──────────────────────────────────────────────
# fastq.parse_fastq
# ──────────────────────────────────────────────
class TestParseFastq:
    def test_basic(self, tmp_path):
        p = tmp_path / "reads.fq"
        p.write_text("@read1\nATCG\n+\nIIII\n@read2\nGGCC\n+\nHHHH\n")
        records = list(parse_fastq(p))
        assert records == [("read1", "ATCG", "IIII"), ("read2", "GGCC", "HHHH")]

    def test_quality_length_matches_seq(self, tmp_path):
        p = tmp_path / "reads.fq"
        p.write_text("@r\nATCGAT\n+\nIIIIII\n")
        _, seq, qual = list(parse_fastq(p))[0]
        assert len(seq) == len(qual)

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.fq"
        p.write_text("")
        assert list(parse_fastq(p)) == []

    def test_invalid_format_raises(self, tmp_path):
        p = tmp_path / "bad.fq"
        p.write_text(">not_fastq\nATCG\n")
        with pytest.raises(ValueError):
            list(parse_fastq(p))

    def test_gzip_support(self, tmp_path):
        p = tmp_path / "reads.fq.gz"
        with gzip.open(p, "wt") as f:
            f.write("@r\nAT\n+\nII\n")
        assert list(parse_fastq(p)) == [("r", "AT", "II")]


# ──────────────────────────────────────────────
# seq_type.detect_seq_type
# ──────────────────────────────────────────────
class TestDetectSeqType:
    def test_dna(self):
        assert detect_seq_type("ATCGATCG") == SeqType.DNA

    def test_dna_with_degenerate(self):
        assert detect_seq_type("ATCGNRYWSMKBDHV") == SeqType.DNA

    def test_dna_with_gap(self):
        assert detect_seq_type("ATCG-ATCG.") == SeqType.DNA

    def test_protein(self):
        # 含蛋白质特有氨基酸 E/F/I/L/P/Q
        assert detect_seq_type("MELFPQWY") == SeqType.PROTEIN

    def test_protein_realistic(self):
        assert detect_seq_type("MALWMRLLPLLALLALWGPDPAAA") == SeqType.PROTEIN

    def test_unknown(self):
        # 含非 DNA 也非蛋白质典型字符
        assert detect_seq_type("ATCGZBXOU") == SeqType.UNKNOWN

    def test_empty(self):
        assert detect_seq_type("") == SeqType.DNA  # 空集合是 DNA 子集

    def test_case_insensitive(self):
        assert detect_seq_type("atcg") == SeqType.DNA
        assert detect_seq_type("melfpq") == SeqType.PROTEIN

    def test_sample_size_limit(self):
        # 只看前 sample_size 个字符
        seq = "ATCG" * 10 + "EEEE"  # E 在 40 字符处
        assert detect_seq_type(seq, sample_size=20) == SeqType.DNA
        assert detect_seq_type(seq, sample_size=100) == SeqType.PROTEIN


# ──────────────────────────────────────────────
# stats
# ──────────────────────────────────────────────
class TestStats:
    def test_calc_sequence_stats(self):
        length, gc = calc_sequence_stats("ATCG")
        assert length == 4
        assert gc == 2  # 1 G + 1 C

    def test_gc_count_accurate(self):
        length, gc = calc_sequence_stats("GGGCCCAT")
        assert length == 8
        assert gc == 6  # 3 G + 3 C

    def test_gc_case_insensitive(self):
        _, gc = calc_sequence_stats("ggcc")
        assert gc == 4

    def test_empty_sequence(self):
        assert calc_sequence_stats("") == (0, 0)

    def test_sequence_stats_gc_content(self):
        s = SequenceStats(header="x", length=4, gc_count=2)
        assert s.gc_content == 0.5

    def test_sequence_stats_zero_length(self):
        s = SequenceStats(header="x", length=0, gc_count=0)
        assert s.gc_content == 0.0


# ──────────────────────────────────────────────
# renderer
# ──────────────────────────────────────────────
class TestRenderer:
    def test_colorize_dna_returns_text(self):
        result = colorize_sequence("ATCG", SeqType.DNA)
        assert isinstance(result, Text)
        assert result.plain == "ATCG"

    def test_colorize_dna_colors(self):
        result = colorize_sequence("A", SeqType.DNA)
        # 检查 A 被着绿色
        span = result._spans[0]
        assert str(span.style) == DNA_COLORS["A"]

    def test_colorize_empty(self):
        result = colorize_sequence("", SeqType.DNA)
        assert result.plain == ""

    def test_colorize_preserves_sequence(self):
        seq = "ATCGATCGNN"
        result = colorize_sequence(seq, SeqType.DNA)
        assert result.plain == seq

    def test_colorize_quality_returns_text(self):
        result = colorize_quality("IIII")
        assert isinstance(result, Text)
        assert result.plain == "IIII"

    def test_colorize_quality_empty(self):
        assert colorize_quality("").plain == ""

    def test_quality_stats(self):
        # 'I' = ord('I')-33 = 40, '!' = 0
        stats = quality_stats("II")
        assert stats["min"] == 40
        assert stats["max"] == 40
        assert stats["mean"] == 40.0
        assert stats["q30_pct"] == 1.0

    def test_quality_stats_low(self):
        stats = quality_stats("!!")  # Q0
        assert stats["min"] == 0
        assert stats["q30_pct"] == 0.0

    def test_quality_stats_empty(self):
        stats = quality_stats("")
        assert stats["mean"] == 0.0
        assert stats["q30_pct"] == 0.0

    def test_quality_bar_returns_text(self):
        result = quality_bar("I" * 100)
        assert isinstance(result, Text)
        assert len(result.plain) > 0

    def test_quality_bar_empty(self):
        assert quality_bar("").plain == ""

    def test_position_ruler_length(self):
        result = position_ruler(1, 60)
        # 标尺宽度应等于 length
        assert len(result.plain) == 60

    def test_position_ruler_contains_start(self):
        result = position_ruler(1, 60)
        assert "1" in result.plain

    def test_position_ruler_contains_61(self):
        result = position_ruler(61, 60)
        assert "61" in result.plain
