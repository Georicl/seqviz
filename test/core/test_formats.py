"""文件格式识别。"""


def test_is_vcf_helper(tmp_path):
    """VCF 文件判定：后缀判定（大小写不敏感），不存在/非文件为 False。"""
    from seqviz.core.formats import is_vcf_file

    f = tmp_path / "x.VCF"
    f.write_text("")
    assert is_vcf_file(f) is True
    fa = tmp_path / "x.fa"
    fa.write_text("")
    assert is_vcf_file(fa) is False
    assert is_vcf_file(tmp_path / "missing.vcf") is False
