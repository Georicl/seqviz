from dataclasses import dataclass


@dataclass
class SequenceStats:
    header: str
    length: int
    gc_count: int

    @property
    def gc_content(self) -> float:
        if self.length == 0:
            return 0.0
        return self.gc_count / self.length

def calc_sequence_stats(seq: str) -> tuple[int, int]:
    """返回 (length, gc_count)。使用 count 代替逐字符遍历。"""
    upper_seq = seq.upper()
    length = len(upper_seq)
    gc_count = upper_seq.count("G") + upper_seq.count("C")
    return length, gc_count