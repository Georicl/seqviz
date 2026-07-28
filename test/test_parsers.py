"""seqviz.parsers 模块的测试套件"""

import gzip
import tempfile
from pathlib import Path

import pytest

from seqviz.parsers import parse_fasta

# 测试数据路径
TEST_FA = Path(__file__).parent / "test.fa"


# ── 使用 test.fa 的基础测试 ──────────────────────────────────


class TestParseFastaWithTestFile:
    """使用 test/test.fa 进行的集成测试"""

    def test_parse_and_print_all_records(self):
        """解析 test.fa 并打印所有记录"""
        records = list(parse_fasta(TEST_FA))
        print(f"\n共解析 {len(records)} 条序列:")
        print("-" * 50)
        for i, (header, seq) in enumerate(records, 1):
            print(f"[{i}] Header : {header}")
            print(f"    Seq    : {seq}")
            print(f"    Length : {len(seq)}")
        print("-" * 50)
        assert len(records) == 2

    def test_first_record_header(self):
        """第一条序列的 header"""
        records = list(parse_fasta(TEST_FA))
        assert records[0][0] == "chr1 Homo sapiens chromosome 1"

    def test_first_record_sequence(self):
        """第一条序列由多行拼接而成"""
        records = list(parse_fasta(TEST_FA))
        assert records[0][1] == "ATCGATCGATCG" + "NNNNNNNN"

    def test_first_record_length(self):
        """第一条序列长度 = 12 + 8 = 20"""
        records = list(parse_fasta(TEST_FA))
        assert len(records[0][1]) == 20

    def test_second_record_header(self):
        """第二条序列的 header"""
        records = list(parse_fasta(TEST_FA))
        assert records[1][0] == "chr2"

    def test_second_record_sequence(self):
        """第二条序列"""
        records = list(parse_fasta(TEST_FA))
        assert records[1][1] == "GGGGAAAACCCC"

    def test_second_record_length(self):
        """第二条序列长度 = 12"""
        records = list(parse_fasta(TEST_FA))
        assert len(records[1][1]) == 12

    def test_parse_accepts_string_path(self):
        """支持 str 类型路径"""
        records = list(parse_fasta(str(TEST_FA)))
        assert len(records) == 2

    def test_parse_accepts_path_object(self):
        """支持 Path 类型路径"""
        records = list(parse_fasta(TEST_FA))
        assert len(records) == 2

    def test_parse_is_generator(self):
        """返回的是生成器(流式解析)"""
        import types
        result = parse_fasta(TEST_FA)
        assert isinstance(result, types.GeneratorType)


# ── 边界情况测试 ──────────────────────────────────────────────


class TestParseFastaEdgeCases:
    """边界情况与异常处理测试"""

    def test_empty_file(self, tmp_path: Path):
        """空文件不产生任何记录"""
        f = tmp_path / "empty.fa"
        f.write_text("")
        assert list(parse_fasta(f)) == []

    def test_single_sequence(self, tmp_path: Path):
        """单条序列"""
        f = tmp_path / "single.fa"
        f.write_text(">seq1\nATCG\n")
        records = list(parse_fasta(f))
        assert len(records) == 1
        assert records[0] == ("seq1", "ATCG")

    def test_multiline_sequence(self, tmp_path: Path):
        """多行序列正确拼接"""
        f = tmp_path / "multi.fa"
        f.write_text(">seq1\nAAA\nCCC\nGGG\n")
        records = list(parse_fasta(f))
        assert records[0][1] == "AAACCCGGG"

    def test_empty_sequence(self, tmp_path: Path):
        """header 后无序列行"""
        f = tmp_path / "noseq.fa"
        f.write_text(">seq1\n>seq2\nATCG\n")
        records = list(parse_fasta(f))
        assert len(records) == 2
        assert records[0] == ("seq1", "")
        assert records[1] == ("seq2", "ATCG")

    def test_header_with_special_chars(self, tmp_path: Path):
        """header 包含特殊字符"""
        f = tmp_path / "special.fa"
        f.write_text(">sp|P12345|PROTEIN_OS Human gene=XXX\nMKWVTFIS\n")
        records = list(parse_fasta(f))
        assert records[0][0] == "sp|P12345|PROTEIN_OS Human gene=XXX"

    def test_no_trailing_newline(self, tmp_path: Path):
        """文件末尾无换行符"""
        f = tmp_path / "nonl.fa"
        f.write_text(">seq1\nATCG")
        records = list(parse_fasta(f))
        assert len(records) == 1
        assert records[0][1] == "ATCG"

    def test_many_sequences(self, tmp_path: Path):
        """大量序列的解析"""
        f = tmp_path / "many.fa"
        content = "".join(f">seq{i}\nATCG\n" for i in range(100))
        f.write_text(content)
        records = list(parse_fasta(f))
        assert len(records) == 100


# ── gzip 压缩文件测试 ────────────────────────────────────────


class TestParseFastaGzip:
    """gzip 压缩 FASTA 文件测试"""

    def test_gzip_file(self, tmp_path: Path, capsys):
        """能正确解析 .gz 文件"""
        f = tmp_path / "test.fa.gz"
        content = ">seq1\nATCG\n>seq2\nGGGG\n"
        with gzip.open(f, "wt") as fh:
            fh.write(content)
        records = list(parse_fasta(f))
        print(f"\ngzip 解析 {len(records)} 条序列:")
        for header, seq in records:
            print(f"  {header} -> {seq} (len={len(seq)})")
        assert len(records) == 2
        assert records[0] == ("seq1", "ATCG")
        assert records[1] == ("seq2", "GGGG")

    def test_gzip_multiline(self, tmp_path: Path):
        """gzip 文件中多行序列"""
        f = tmp_path / "multi.fa.gz"
        content = ">seq1\nAAA\nCCC\n"
        with gzip.open(f, "wt") as fh:
            fh.write(content)
        records = list(parse_fasta(f))
        assert records[0][1] == "AAACCC"
