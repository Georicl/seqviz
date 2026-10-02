"""按记录解析 FASTA，供 CLI 查看与统计使用。"""

from collections.abc import Generator
from pathlib import Path

from seqviz.core.formats import open_seq_file


def parse_fasta(filepath: str | Path) -> Generator[tuple[str, str]]:
    """逐条解析 FASTA，序列行两端空白不计入碱基。"""

    filepath = Path(filepath)

    header = None
    seq_parts: list[str] = []

    with open_seq_file(filepath, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")

            if line.startswith(">"):
                if header is not None:
                    yield header, "".join(seq_parts)

                header = line[1:].strip()  # 与序列索引使用相同的标题规则。
                seq_parts = []

            else:
                # 序列行两端的空白属于排版，与浏览器使用同一条规则。
                seq_parts.append(line.strip())

        if header is not None:
            yield header, "".join(seq_parts)
