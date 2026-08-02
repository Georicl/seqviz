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
