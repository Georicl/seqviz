from rich.text import Text
from seqviz.seq_type import SeqType, detect_seq_type
from seqviz import config

# DNA 碱基配色方案（从配置加载，可被用户 JSON 覆盖）
DNA_COLORS = dict(config.get("colors.dna", {}))

# 质量值着色阈值（从配置加载）
_QUALITY_THRESHOLDS = config.get("colors.quality_thresholds", {})

PROTEIN_COLORS: dict[str, str] = {}

# 疏水性 → 绿色系
for _aa in "AVILMFYW":
    PROTEIN_COLORS[_aa] = "green"

# 亲水性 → 蓝色系
for _aa in "STNQ":
    PROTEIN_COLORS[_aa] = "blue"

# 碱性 → 红色系
for _aa in "RKH":
    PROTEIN_COLORS[_aa] = "red"

# 酸性 → 紫色系
for _aa in "DE":
    PROTEIN_COLORS[_aa] = "magenta"

# 特殊 → 灰色系
for _aa in "GPC":
    PROTEIN_COLORS[_aa] = "dim"

def colorize_sequence(seq: str, seq_type: SeqType | None = None) -> Text:
    if seq_type is None:
        seq_type = detect_seq_type(seq=seq)

    color_map = PROTEIN_COLORS if seq_type == SeqType.PROTEIN else DNA_COLORS

    # 按颜色分段批量 append（减少 span 数量，提升渲染性能）
    text = Text()
    if not seq:
        return text
    prev_color = color_map.get(seq[0].upper(), "white")
    start = 0
    for i in range(1, len(seq)):
        color = color_map.get(seq[i].upper(), "white")
        if color != prev_color:
            text.append(seq[start:i], style=prev_color)
            prev_color = color
            start = i
    text.append(seq[start:], style=prev_color)
    return text

def colorize_quality(quality: str) -> Text:
    """
    对 FASTQ 质量值进行 Phred 梯度着色（阈值可配置）。

    Phred score = ord(char) - 33 (Sanger/Illumina 1.8+ 编码)
    Q >= high   → 绿色 (高质量)
    Q >= medium → 黄色 (中等)
    Q >= low    → bright_red (低)
    Q <  low    → red (极低)
    """
    high = _QUALITY_THRESHOLDS.get("high", 30)
    medium = _QUALITY_THRESHOLDS.get("medium", 20)
    low = _QUALITY_THRESHOLDS.get("low", 10)

    def _style(score: int) -> str:
        if score >= high:
            return "green"
        if score >= medium:
            return "yellow"
        if score >= low:
            return "bright_red"
        return "red"

    # 按样式分段批量 append
    text = Text()
    if not quality:
        return text
    prev_style = _style(ord(quality[0]) - 33)
    start = 0
    for i in range(1, len(quality)):
        style = _style(ord(quality[i]) - 33)
        if style != prev_style:
            text.append(quality[start:i], style=prev_style)
            prev_style = style
            start = i
    text.append(quality[start:], style=prev_style)
    return text


def quality_stats(quality: str) -> dict:
    """
    计算一条 read 的质量统计信息。
    返回 {"min": int, "max": int, "mean": float, "q30_pct": float}
    """
    scores = [ord(c) - 33 for c in quality]
    if not scores:
        return {"min": 0, "max": 0, "mean": 0.0, "q30_pct": 0.0}
    q30_count = sum(1 for s in scores if s >= 30)
    return {
        "min": min(scores),
        "max": max(scores),
        "mean": sum(scores) / len(scores),
        "q30_pct": q30_count / len(scores),
    }


def quality_bar(quality: str, width: int = 40) -> Text:
    """
    将质量值压缩为一条可视化质量分布条。
    每个字符代表 N 个碱基的平均 Phred 值。
    """
    scores = [ord(c) - 33 for c in quality]
    if not scores:
        return Text()
    
    bin_size = max(1, len(scores) // width)
    text = Text()
    for i in range(0, len(scores), bin_size):
        chunk = scores[i:i + bin_size]
        avg = sum(chunk) / len(chunk)
        if avg >= 30:
            text.append("█", style="green")
        elif avg >= 20:
            text.append("█", style="yellow")
        elif avg >= 10:
            text.append("█", style="bright_red")
        else:
            text.append("█", style="red")
    return text


def position_ruler(start: int, length: int) -> Text:
    """
    生成位置标尺，每 10bp 标注一次刻度。
    输出宽度精确等于 length，与序列/质量行对齐。
    start: 当前 chunk 第一个碱基的全局位置 (1-based)
    length: 当前 chunk 的碱基数
    """
    # 先构建纯字符串，再统一着色
    chars = [' '] * length
    for i in range(length):
        pos = start + i  # 1-based
        if (pos - 1) % 10 == 0:
            num_str = str(pos)
            for j, ch in enumerate(num_str):
                if i + j < length:
                    chars[i + j] = ch
    
    text = Text()
    for ch in chars:
        if ch.isdigit():
            text.append(ch, style="dim")
        else:
            text.append(ch)
    return text