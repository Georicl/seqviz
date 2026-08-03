"""CLI 命令测试：view / stats / head / fqview / config 的输出验证"""

import json
from pathlib import Path

from typer.testing import CliRunner

from seqviz import config as config_mod
from seqviz import theme as theme_mod
from seqviz.cli import app

runner = CliRunner()
TEST_DIR = Path(__file__).parent
TEST_FA = str(TEST_DIR / "test.fa")
TEST_FASTQ = str(TEST_DIR / "test_fastq.fastq")


class TestViewCommand:
    def test_view_outputs_sequences(self):
        result = runner.invoke(app, ["view", TEST_FA])
        assert result.exit_code == 0
        assert "chr1" in result.output
        assert "chr2" in result.output

    def test_view_shows_type_label(self):
        result = runner.invoke(app, ["view", TEST_FA])
        assert "DNA" in result.output

    def test_view_shows_length(self):
        result = runner.invoke(app, ["view", TEST_FA])
        assert "20bp" in result.output  # chr1 是 20bp

    def test_view_missing_file(self):
        result = runner.invoke(app, ["view", "nonexistent.fa"])
        assert result.exit_code != 0
        assert "文件不存在" in result.output  # 友好错误提示

    def test_view_wrap_zero_rejected(self):
        """--wrap 0 应被拒绝（min=1），避免 range() 除零崩溃。"""
        result = runner.invoke(app, ["view", TEST_FA, "--wrap", "0"])
        assert result.exit_code != 0


class TestHeadCommand:
    def test_head_limits_count(self):
        result = runner.invoke(app, ["head", TEST_FA, "-n", "1"])
        assert result.exit_code == 0
        assert "chr1" in result.output
        assert "chr2" not in result.output  # 只要第一条

    def test_head_default(self):
        result = runner.invoke(app, ["head", TEST_FA])
        assert result.exit_code == 0
        assert "共显示" in result.output


class TestStatsCommand:
    def test_stats_outputs_table(self):
        result = runner.invoke(app, ["stats", TEST_FA])
        assert result.exit_code == 0
        assert "序列条数" in result.output
        assert "N50" in result.output
        assert "GC 含量" in result.output

    def test_stats_correct_count(self):
        result = runner.invoke(app, ["stats", TEST_FA])
        assert "2" in result.output  # 2 条序列


class TestFqviewCommand:
    def test_fqview_outputs_reads(self):
        result = runner.invoke(app, ["fqview", TEST_FASTQ])
        assert result.exit_code == 0
        assert "Read 1" in result.output

    def test_fqview_shows_quality(self):
        result = runner.invoke(app, ["fqview", TEST_FASTQ, "-n", "1"])
        assert result.exit_code == 0
        assert "Q=" in result.output  # 质量统计
        assert "Q30=" in result.output

    def test_fqview_limits_count(self):
        result = runner.invoke(app, ["fqview", TEST_FASTQ, "-n", "1"])
        assert result.exit_code == 0
        assert "Read 2" not in result.output


class TestConfigCommand:
    def test_config_shows_config(self):
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "browser" in result.output
        assert "wrap_width" in result.output

    def test_config_shows_theme(self):
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "background" in result.output
        assert "#1e1e2e" in result.output  # 默认 dark 主题背景


class TestConfigInit:
    def test_config_init_creates_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
        monkeypatch.setattr(theme_mod, "THEME_FILE", tmp_path / "theme.json")
        result = runner.invoke(app, ["config", "--init"])
        assert result.exit_code == 0
        assert (tmp_path / "config.json").exists()
        assert (tmp_path / "theme.json").exists()

    def test_config_init_theme_does_not_override(self, tmp_path, monkeypatch):
        """--init 生成的 theme.json 仅含注释键，不应覆盖内置主题（theme 切换仍有效）。"""
        monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
        monkeypatch.setattr(theme_mod, "THEME_FILE", tmp_path / "theme.json")
        config_mod._config = None
        theme_mod._theme = None
        runner.invoke(app, ["config", "--init"])
        data = json.loads((tmp_path / "theme.json").read_text())
        assert all(k.startswith("_") for k in data)  # 仅注释/模板键
        # 加载主题时这些键被忽略 → 仍为 dark 默认
        theme_mod._theme = None
        theme = theme_mod.load_theme()
        assert theme["background"] == "#1e1e2e"


class TestBrowseCommand:
    def test_browse_missing_path(self):
        """browse 不存在的路径应友好报错而非裸 traceback。"""
        result = runner.invoke(app, ["browse", "nonexistent_file.fa"])
        assert result.exit_code != 0
        assert "路径不存在" in result.output

    def test_browse_happy_path_passes_paths(self, monkeypatch):
        """browse 正常入口：路径列表传入 FastaBrowser 并启动。"""
        import seqviz.cli as cli_mod
        captured: dict = {}

        def fake_run(self):
            captured["n_tabs"] = len(self.file_tabs)

        monkeypatch.setattr(cli_mod.FastaBrowser, "run", fake_run)
        result = runner.invoke(app, ["browse", TEST_FA])
        assert result.exit_code == 0
        assert captured["n_tabs"] == 1

    def test_browse_vcf_routes_to_vcf_browser(self, monkeypatch):
        """browse 单个 .vcf 应路由到 VcfBrowser 而非 FastaBrowser。"""
        import seqviz.cli as cli_mod
        from seqviz import vcf_browser as vcf_browser_mod
        called: dict = {}

        def fake_vcf_run(self):
            called["vcf"] = str(self.filepath)

        def fake_fasta_run(self):
            called["fasta"] = True

        monkeypatch.setattr(vcf_browser_mod.VcfBrowser, "run", fake_vcf_run)
        monkeypatch.setattr(cli_mod.FastaBrowser, "run", fake_fasta_run)
        vcf_path = str(Path(__file__).parent / "sample.vcf")
        result = runner.invoke(app, ["browse", vcf_path])
        assert result.exit_code == 0
        assert called.get("vcf") == vcf_path
        assert "fasta" not in called

    def test_is_vcf_helper(self, tmp_path):
        """_is_vcf 辅助函数：后缀判定（大小写不敏感），不存在/非文件为 False。"""
        from seqviz.cli import _is_vcf
        f = tmp_path / "x.VCF"
        f.write_text("")
        assert _is_vcf(f) is True
        fa = tmp_path / "x.fa"
        fa.write_text("")
        assert _is_vcf(fa) is False
        assert _is_vcf(tmp_path / "missing.vcf") is False

    def test_browse_empty_vcf_friendly_error(self, tmp_path):
        """空 VCF：友好报错并非零退出（对齐现有空文件策略）。"""
        f = tmp_path / "empty.vcf"
        f.write_text("")
        result = runner.invoke(app, ["browse", str(f)])
        assert result.exit_code != 0
        assert "缺少 #CHROM 表头" in result.output

    def test_browse_header_only_vcf_friendly_error(self, tmp_path):
        """有表头但无变异记录：友好报错并非零退出。"""
        f = tmp_path / "hdr.vcf"
        f.write_text("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        result = runner.invoke(app, ["browse", str(f)])
        assert result.exit_code != 0
        assert "没有变异记录" in result.output

    def test_browse_mixed_vcf_and_fasta_skips_vcf(self, tmp_path, monkeypatch):
        """VCF 与序列文件混合打开：VCF 被剥离并提示，FastaBrowser 只收到序列文件。"""
        import seqviz.cli as cli_mod
        fa = tmp_path / "x.fa"
        fa.write_text(">s1\nATCG\n")
        vcf = tmp_path / "x.vcf"
        vcf.write_text("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                       "chr1\t1\t.\tA\tG\t50\tPASS\t.\n")
        captured: dict = {}

        def fake_fasta_run(self):
            captured["paths"] = [str(t.filepath) for t in self.file_tabs]

        monkeypatch.setattr(cli_mod.FastaBrowser, "run", fake_fasta_run)
        result = runner.invoke(app, ["browse", str(vcf), str(fa)])
        assert result.exit_code == 0
        assert "混合打开" in result.output  # 提示信息已输出
        assert captured["paths"] == [str(fa)]  # VCF 未进入 FastaBrowser


class TestHelpCommand:
    def test_main_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "view" in result.output
        assert "stats" in result.output
        assert "browse" in result.output
        assert "config" in result.output

    def test_view_help(self):
        result = runner.invoke(app, ["view", "--help"])
        assert result.exit_code == 0


class TestN50Value:
    def test_n50_numeric_correctness(self):
        """N50 数值正确性（回归：此前仅字符串存在断言）。"""
        from seqviz.cli import _calc_n50
        # 长度 [20, 12]，总长 32，半值 16；降序累计 20 >= 16 → N50 = 20
        assert _calc_n50([20, 12], 32) == 20
        # [100, 50, 30, 20] 总长 200，半值 100；累计 100 >= 100 → N50 = 100
        assert _calc_n50([100, 50, 30, 20], 200) == 100
        assert _calc_n50([], 0) == 0

    def test_stats_n50_value_in_output(self):
        """stats 输出的 N50 应为具体数值（test.fa: 20bp + 12bp → N50=20）。"""
        result = runner.invoke(app, ["stats", TEST_FA])
        assert result.exit_code == 0
        assert "N50" in result.output
        assert "20" in result.output


class TestEmptyFileCli:
    def test_stats_empty_file(self, tmp_path):
        """空 FASTA 输入 stats 应友好报错并非零退出。"""
        p = tmp_path / "empty.fa"
        p.write_text("")
        result = runner.invoke(app, ["stats", str(p)])
        assert result.exit_code != 0
        assert "没有序列" in result.output

    def test_head_empty_file(self, tmp_path):
        p = tmp_path / "empty.fa"
        p.write_text("")
        result = runner.invoke(app, ["head", str(p)])
        assert result.exit_code != 0
        assert "没有序列" in result.output

    def test_fqview_empty_file(self, tmp_path):
        p = tmp_path / "empty.fastq"
        p.write_text("")
        result = runner.invoke(app, ["fqview", str(p)])
        assert result.exit_code != 0
        assert "没有序列" in result.output


class TestMalformedFastq:
    def test_trailing_blank_line_tolerated(self, tmp_path):
        """尾部空行应被跳过而非报格式错误。"""
        p = tmp_path / "t.fastq"
        p.write_text("@r1\nACGT\n+\nIIII\n\n")
        result = runner.invoke(app, ["fqview", str(p)])
        assert result.exit_code == 0
        assert "共显示 1 条" in result.output

    def test_invalid_record_friendly_error(self, tmp_path):
        """非 '@' 开头的记录应友好报错而非裸 traceback。"""
        p = tmp_path / "bad.fastq"
        p.write_text(">not_fastq\nACGT\n+\nIIII\n")
        result = runner.invoke(app, ["fqview", str(p)])
        assert result.exit_code == 1
        assert "错误" in result.output
        assert "Traceback" not in result.output

    def test_non_utf8_header_fqview(self, tmp_path):
        """非 UTF-8 编码 header 不应 UnicodeDecodeError 崩溃。"""
        p = tmp_path / "latin1.fastq"
        p.write_bytes(b"@caf\xe9\nACGT\n+\nIIII\n")
        result = runner.invoke(app, ["fqview", str(p)])
        assert result.exit_code == 0

    def test_non_utf8_header_view(self, tmp_path):
        """view/stats 对 latin-1 header 宽容处理。"""
        p = tmp_path / "latin1.fa"
        p.write_bytes(b">caf\xe9 header\nACGT\n")
        result = runner.invoke(app, ["view", str(p)])
        assert result.exit_code == 0
        result = runner.invoke(app, ["stats", str(p)])
        assert result.exit_code == 0
