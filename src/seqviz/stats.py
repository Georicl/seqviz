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
    """返回 (length, gc_count)。一次遍历同时算两个值。"""
    length = len(seq)
    gc_count = 0
    for base in seq.upper():
        if base in ("G", "C"):
            gc_count += 1
    return length, gc_count