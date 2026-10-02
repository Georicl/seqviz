"""终端序列、质量值和标尺的渲染。"""

from rich.text import Text

from seqviz.core.seq_type import SeqType
from seqviz.core.stats import quality_stats
from seqviz.ui.renderer import (
    colorize_quality,
    colorize_sequence,
    position_ruler,
    quality_bar,
)


# ──────────────────────────────────────────────
# parsers.parse_fasta
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
        assert str(span.style) == "green"

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

    def test_quality_bar_respects_width(self):
        """条数不应超过指定宽度（len 落在 (width, 2*width) 区间时的回归）。"""
        for n, width in ((100, 60), (40, 60), (200, 40), (1000, 40)):
            result = quality_bar("I" * n, width=width)
            assert len(result.plain) <= width
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
