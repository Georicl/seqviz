"""CLI 命令测试：view / stats / head / fqview / config 的输出验证"""

from pathlib import Path

from typer.testing import CliRunner

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
        assert "#ffffff" in result.output


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
