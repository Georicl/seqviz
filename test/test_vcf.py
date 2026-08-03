"""VCF 解析层测试（对应 docs/superpowers/plans Task 1-4）。"""
from pathlib import Path

import pytest

from seqviz.vcf import (
    Variant,
    VariantType,
    classify_variant,
    compute_stats,
    load_variant_detail,
    parse_genotype,
    parse_meta,
    parse_variant_line,
    scan_vcf,
)

SAMPLE_VCF = Path(__file__).parent / "sample.vcf"


class TestClassifyVariant:
    def test_transition(self):
        assert classify_variant("A", "G") == VariantType.TRANSITION
        assert classify_variant("G", "A") == VariantType.TRANSITION
        assert classify_variant("C", "T") == VariantType.TRANSITION
        assert classify_variant("T", "C") == VariantType.TRANSITION

    def test_transversion(self):
        assert classify_variant("A", "T") == VariantType.TRANSVERSION
        assert classify_variant("G", "C") == VariantType.TRANSVERSION
        assert classify_variant("A", "C") == VariantType.TRANSVERSION

    def test_insertion(self):
        assert classify_variant("T", "TG") == VariantType.INSERTION
        assert classify_variant("A", "ACGT") == VariantType.INSERTION

    def test_deletion(self):
        assert classify_variant("AT", "A") == VariantType.DELETION
        assert classify_variant("GC", "G") == VariantType.DELETION

    def test_multiallelic_uses_first_alt(self):
        assert classify_variant("A", "G,T") == VariantType.TRANSITION

    def test_case_insensitive(self):
        assert classify_variant("a", "g") == VariantType.TRANSITION

    def test_symbolic_alleles_are_complex(self):
        """符号等位基因（SV caller / gVCF）不污染 SNP/InDel 计数与 Ts/Tv。"""
        assert classify_variant("A", "<DEL>") == VariantType.COMPLEX
        assert classify_variant("A", "<INS>") == VariantType.COMPLEX
        assert classify_variant("A", "*") == VariantType.COMPLEX
        assert classify_variant("A", "<DUP>,G") == VariantType.COMPLEX  # 多等位取首个


class TestParseGenotype:
    def test_full_fields(self):
        result = parse_genotype("0/1:15:99:10,5", ["GT", "DP", "GQ", "AD"])
        assert result["GT"] == "0/1"
        assert result["DP"] == 15
        assert result["GQ"] == 99
        assert result["AD"] == [10, 5]

    def test_missing_gt(self):
        result = parse_genotype(".:.:.", ["GT", "DP", "GQ"])
        assert result["GT"] == "./."

    def test_fewer_values_than_fields(self):
        result = parse_genotype("0/0", ["GT", "DP"])
        assert result == {"GT": "0/0"}

    def test_non_int_kept_as_str(self):
        result = parse_genotype("0/1:abc", ["GT", "DP"])
        assert result["DP"] == "abc"


class TestParseMeta:
    def test_sample_vcf_meta(self):
        lines = SAMPLE_VCF.read_text().splitlines()
        header = [l for l in lines if l.startswith("##")]
        meta = parse_meta(header)
        assert meta.fileformat == "VCFv4.3"
        assert meta.contigs["chr1"] == 79116311
        assert meta.info_defs["DP"] == "Total Depth"
        assert meta.format_defs["GT"] == "Genotype"
        assert meta.filter_defs["PASS"] == "All filters passed"

    def test_empty_header(self):
        meta = parse_meta([])
        assert meta.fileformat == ""
        assert meta.contigs == {}

    def test_contig_without_length(self):
        meta = parse_meta(["##contig=<ID=chrX>"])
        assert meta.contigs["chrX"] == 0


class TestParseVariantLine:
    def test_full_line(self):
        line = "chr1\t10234\trs12345\tA\tG\t99.5\tPASS\tDP=45;AF=0.333;DB\tGT:DP\t0/1:15\t0/0:18"
        v = parse_variant_line(line, offset=100, sample_names=["s1", "s2"])
        assert v.chrom == "chr1" and v.pos == 10234
        assert v.id == "rs12345" and v.qual == 99.5
        assert v.info == {"DP": "45", "AF": "0.333", "DB": ""}
        assert v.samples == {"s1": "0/1:15", "s2": "0/0:18"}
        assert v.offset == 100

    def test_dot_id_and_qual(self):
        v = parse_variant_line("chr1\t5\t.\tA\tG\t.\tPASS\t.")
        assert v.id == "" and v.qual is None

    def test_malformed_fewer_than_8_cols(self):
        assert parse_variant_line("chr1\t100\tA") is None

    def test_bad_pos(self):
        assert parse_variant_line("chr1\txyz\t.\tA\tG\t.\tPASS\t.") is None

    def test_header_line_rejected(self):
        assert parse_variant_line("#CHROM\tPOS\tID") is None

    def test_unnamed_samples_get_generated_names(self):
        v = parse_variant_line("chr1\t5\t.\tA\tG\t.\tPASS\t.\tGT\t0/1\t1/1")
        assert list(v.samples.keys()) == ["sample1", "sample2"]


class TestScanVcf:
    def test_sample_vcf(self):
        meta, variants, skipped = scan_vcf(SAMPLE_VCF)
        assert len(variants) == 18
        assert skipped == 0
        assert meta.samples == ["sample1", "sample2", "sample3"]
        assert meta.has_header is True
        first = variants[0]
        assert (first.chrom, first.pos, first.ref, first.alt) == ("chr1", 10234, "A", "G")
        assert first.info["AF"] == "0.333"   # INFO 在索引阶段已解析
        assert first.samples == {}            # 样本列懒加载
        assert first.offset > 0

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.vcf"
        f.write_text("")
        meta, variants, skipped = scan_vcf(f)
        assert variants == [] and meta.samples == []
        assert meta.has_header is False  # 无效文件判定依据

    def test_no_header_line(self, tmp_path):
        f = tmp_path / "nohdr.vcf"
        f.write_text("chr1\t1\t.\tA\tG\t.\tPASS\t.\n")
        meta, variants, skipped = scan_vcf(f)
        assert len(variants) == 1
        assert meta.samples == []

    def test_malformed_lines_skipped_and_counted(self, tmp_path):
        f = tmp_path / "bad.vcf"
        f.write_text("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                     "chr1\t1\t.\tA\tG\t.\tPASS\t.\n"
                     "garbage line\n"
                     "chr1\t2\t.\tC\tT\t.\tPASS\t.\n")
        _, variants, skipped = scan_vcf(f)
        assert len(variants) == 2 and skipped == 1


class TestLoadVariantDetail:
    def test_roundtrip(self):
        _, variants, _ = scan_vcf(SAMPLE_VCF)
        first = variants[0]
        meta_samples = ["sample1", "sample2", "sample3"]
        load_variant_detail(SAMPLE_VCF, first, meta_samples)
        assert first.samples["sample1"] == "0/1:15:99:10,5"
        assert first.format_fields == ["GT", "DP", "GQ", "AD"]
        assert first.raw.startswith("chr1\t10234")

    def test_idempotent(self):
        _, variants, _ = scan_vcf(SAMPLE_VCF)
        first = variants[0]
        load_variant_detail(SAMPLE_VCF, first, ["sample1", "sample2", "sample3"])
        raw1 = first.raw
        load_variant_detail(SAMPLE_VCF, first, ["sample1", "sample2", "sample3"])
        assert first.raw == raw1


class TestComputeStats:
    def test_sample_vcf_stats(self):
        _, variants, _ = scan_vcf(SAMPLE_VCF)
        stats = compute_stats(variants)
        assert stats["total"] == 18
        assert stats["snp"] + stats["indel"] + stats["complex"] == 18
        assert stats["snp"] == 12
        assert stats["indel"] == 6
        assert stats["pass_count"] == 13
        assert stats["ts_tv"] == pytest.approx(1.0)  # 实测 6 转换 6 颠换
        assert 0.0 < stats["mean_af"] < 1.0

    def test_empty(self):
        stats = compute_stats([])
        assert stats["total"] == 0 and stats["ts_tv"] == 0.0

    def test_no_tv_avoids_zero_division(self):
        v = Variant("chr1", 1, "", "A", "G", 50.0, "PASS")
        stats = compute_stats([v])
        assert stats["ts_tv"] == 0.0
