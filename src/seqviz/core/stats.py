"""序列长度、GC、N50 与 Phred 质量值统计。"""


def calc_sequence_stats(seq: str) -> tuple[int, int]:
    """返回 (length, gc_count)。使用 count 代替逐字符遍历。"""
    upper_seq = seq.upper()
    length = len(upper_seq)
    gc_count = upper_seq.count("G") + upper_seq.count("C")
    return length, gc_count


def calc_n50(sorted_lengths: list[int], total_len: int) -> int:
    """计算 N50：累计长度达到总长 50% 时对应的序列长度。"""
    half = total_len / 2
    cumsum = 0
    for length in sorted_lengths:
        cumsum += length
        if cumsum >= half:
            return length
    return 0


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
