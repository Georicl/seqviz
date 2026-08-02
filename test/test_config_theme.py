"""config 与 theme 系统测试：加载、深度合并、覆盖对行为的实际影响"""

import json

import pytest

from seqviz import config as config_mod
from seqviz import theme as theme_mod


# ──────────────────────────────────────────────
# config 系统
# ──────────────────────────────────────────────
class TestConfig:
    def setup_method(self):
        # 每个测试前重置单例，避免相互污染
        config_mod._config = None

    def teardown_method(self):
        config_mod._config = None

    def test_default_values(self):
        cfg = config_mod.get_config()
        assert cfg["browser"]["wrap_width"] == 60
        assert cfg["browser"]["scroll_step"] == 5
        assert cfg["browser"]["sidebar_width"] == 32
        assert cfg["browser"]["show_line_numbers"] is True
        assert cfg["browser"]["show_quality"] is True

    def test_default_dna_colors(self):
        cfg = config_mod.get_config()
        assert cfg["colors"]["dna"]["A"] == "green"
        assert cfg["colors"]["dna"]["T"] == "red"
        assert cfg["colors"]["dna"]["C"] == "blue"
        assert cfg["colors"]["dna"]["G"] == "yellow"

    def test_default_extensions(self):
        cfg = config_mod.get_config()
        exts = cfg["file_browser"]["extensions"]
        assert ".fa" in exts
        assert ".fastq" in exts
        assert ".aa" in exts

    def test_deep_merge_override(self):
        merged = config_mod._deep_merge(
            {"browser": {"wrap_width": 60, "scroll_step": 5}},
            {"browser": {"wrap_width": 100}},
        )
        assert merged["browser"]["wrap_width"] == 100
        assert merged["browser"]["scroll_step"] == 5  # 未覆盖的保留

    def test_deep_merge_add_new_key(self):
        merged = config_mod._deep_merge({"a": 1}, {"b": 2})
        assert merged == {"a": 1, "b": 2}

    def test_load_config_from_file(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"browser": {"wrap_width": 120}}))
        monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)
        config_mod._config = None
        cfg = config_mod.get_config()
        assert cfg["browser"]["wrap_width"] == 120
        assert cfg["browser"]["scroll_step"] == 5  # 其他保持默认

    def test_load_config_invalid_json_falls_back(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("{invalid json!!!")
        monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)
        config_mod._config = None
        cfg = config_mod.get_config()
        assert cfg["browser"]["wrap_width"] == 60  # 回退默认

    def test_load_config_missing_file_uses_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "nonexistent.json")
        config_mod._config = None
        cfg = config_mod.get_config()
        assert cfg == config_mod.DEFAULT_CONFIG

    def test_get_dot_path(self):
        assert config_mod.get("browser.wrap_width") == 60
        assert config_mod.get("colors.dna.A") == "green"

    def test_get_missing_returns_default(self):
        assert config_mod.get("nonexistent.key") is None
        assert config_mod.get("nonexistent.key", "fallback") == "fallback"

    def test_reload_config(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)
        config_mod._config = None
        assert config_mod.get_config()["browser"]["wrap_width"] == 60
        # 修改文件后 reload 应生效
        cfg_file.write_text(json.dumps({"browser": {"wrap_width": 99}}))
        config_mod.reload_config()
        assert config_mod.get_config()["browser"]["wrap_width"] == 99

    def test_load_config_wrong_type_falls_back(self, tmp_path, monkeypatch):
        """用户配置类型错误时应回退默认值而非令消费方崩溃。"""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "colors": {"dna": "red"},          # 应为 dict，误写为 str
            "browser": {"wrap_width": "wide"},  # 应为 int，误写为 str
        }))
        monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)
        config_mod._config = None
        cfg = config_mod.get_config()
        assert cfg["colors"]["dna"]["A"] == "green"  # dna 回退默认 dict
        assert cfg["browser"]["wrap_width"] == 60      # wrap_width 回退默认 int

    def test_load_config_lenient_conversions(self, tmp_path, monkeypatch):
        """0/1 作 bool、整数值 float 应被安全转换而非静默回退/反转。"""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "browser": {"auto_wrap": 0, "wrap_width": 80.0},
            "colors": {"quality_thresholds": {"high": 25.0}},
        }))
        monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)
        config_mod._config = None
        cfg = config_mod.get_config()
        assert cfg["browser"]["auto_wrap"] is False  # 0 → False，不反转
        assert cfg["browser"]["wrap_width"] == 80    # 80.0 → 80，不丢弃
        assert cfg["colors"]["quality_thresholds"]["high"] == 25


# ──────────────────────────────────────────────
# config 覆盖对渲染行为的实际影响
# ──────────────────────────────────────────────
class TestConfigAffectsBehavior:
    def test_dna_color_override_affects_colorize(self, tmp_path, monkeypatch):
        """修改 config 的 dna 颜色后，colorize 应使用新颜色（消费时读取配置）。"""
        from seqviz.renderer import colorize_sequence
        from seqviz.seq_type import SeqType
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"colors": {"dna": {"A": "cyan"}}}))
        monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)
        config_mod._config = None
        assert config_mod.get("colors.dna.A") == "cyan"
        # 渲染路径消费时读取配置 → A 应着 cyan（验证 reload 契约生效）
        result = colorize_sequence("A", SeqType.DNA)
        assert str(result._spans[0].style) == "cyan"

    def test_quality_threshold_override(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"colors": {"quality_thresholds": {"high": 35}}}))
        monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)
        config_mod._config = None
        assert config_mod.get("colors.quality_thresholds.high") == 35
        assert config_mod.get("colors.quality_thresholds.medium") == 20  # 保留默认


# ──────────────────────────────────────────────
# theme 系统
# ──────────────────────────────────────────────
class TestTheme:
    def setup_method(self):
        theme_mod._theme = None

    def teardown_method(self):
        theme_mod._theme = None

    def test_default_theme_dark_bg(self):
        theme = theme_mod.get_theme()
        assert theme["background"] == "#1e1e2e"  # 默认 dark 主题
        assert theme["foreground"] == "#cdd6f4"

    def test_default_theme_borders(self):
        theme = theme_mod.get_theme()
        assert theme["border"] == "#45475a"
        assert theme["accent"] == "#89b4fa"

    def test_deep_merge(self):
        merged = theme_mod._deep_merge(
            {"background": "#ffffff", "foreground": "#1a1a1a"},
            {"background": "#000000"},
        )
        assert merged["background"] == "#000000"
        assert merged["foreground"] == "#1a1a1a"

    def test_load_theme_from_file(self, tmp_path, monkeypatch):
        theme_file = tmp_path / "theme.json"
        theme_file.write_text(json.dumps({"background": "#eeeeee"}))
        monkeypatch.setattr(theme_mod, "THEME_FILE", theme_file)
        theme_mod._theme = None
        theme = theme_mod.get_theme()
        assert theme["background"] == "#eeeeee"
        assert theme["foreground"] == "#cdd6f4"  # 保留默认(dark)

    def test_load_theme_invalid_falls_back(self, tmp_path, monkeypatch):
        theme_file = tmp_path / "theme.json"
        theme_file.write_text("not json")
        monkeypatch.setattr(theme_mod, "THEME_FILE", theme_file)
        theme_mod._theme = None
        theme = theme_mod.get_theme()
        assert theme["background"] == "#1e1e2e"  # 回退 dark 默认

    def test_build_browser_css_contains_colors(self):
        theme = theme_mod.get_theme()
        css = theme_mod.build_browser_css(theme)
        assert "#1e1e2e" in css  # 背景(dark)
        assert "#cdd6f4" in css  # 文字
        assert "#45475a" in css  # 边框
        assert "Screen" in css
        assert ".sidebar" in css
        assert ".main-view" in css

    def test_build_browser_css_custom_theme(self):
        theme = dict(theme_mod.DEFAULT_THEME)
        theme["background"] = "#123456"
        css = theme_mod.build_browser_css(theme)
        assert "#123456" in css

    def test_build_file_browser_css_contains_colors(self):
        theme = theme_mod.get_theme()
        css = theme_mod.build_file_browser_css(theme)
        assert "#1e1e2e" in css
        assert "#file-list" in css
        assert "#preview" in css

    def test_browser_uses_dark_theme(self):
        """FastaBrowser 应使用深色主题 (DARK=True)。"""
        from seqviz.browser import FastaBrowser
        assert FastaBrowser.DARK is True

    def test_file_browser_uses_dark_theme(self):
        from seqviz.file_browser import FileBrowser
        assert FileBrowser.DARK is True

    def test_app_title_is_seqviz(self):
        from seqviz.browser import FastaBrowser
        from seqviz.file_browser import FileBrowser
        assert FastaBrowser.TITLE == "Seqviz"
        assert FileBrowser.TITLE == "Seqviz"
