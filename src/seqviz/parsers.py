from pathlib import Path
import gzip

def parse_fasta(filepath: str | Path):
    """流式打开fasta 文件"""

    filepath = Path(filepath)

    # 选择打开格式, 如果是.gz结尾, 则使用gzip
    opener = gzip.open if filepath.suffix == ".gz" else open

    header = None
    seq_parts: list[str] = []

    with opener(filepath, "rt") as f:
        for line in f:
            line = line.rstrip("\n")

            if line.startswith(">"):
                # 如果上一条有header, 清除
                if header is not None:
                    yield header, "".join(seq_parts)

                header = line[1:]  # 去掉 > 符号
                seq_parts = []

            else:
                seq_parts.append(line)

        if header is not None:
            yield header, "".join(seq_parts)
            
