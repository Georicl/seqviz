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
