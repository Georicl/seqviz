import gzip
from collections.abc import Generator
from pathlib import Path


def parse_fastq(filepath: str | Path) -> Generator[tuple[str, str, str], None, None]:
    """
    流式解析 FASTQ 文件。
    逐条 yield (header, sequence, quality)。
    """
    filepath = Path(filepath)
    opener = gzip.open if filepath.suffix.lower() == ".gz" else open
    
    with opener(filepath, "rt", encoding="utf-8", errors="replace") as f:
        while True:
            header_line = f.readline()
            if not header_line:
                break  # EOF

            header_line = header_line.rstrip("\n")
            if not header_line.strip():
                continue  # 跳过空行（尾部空行/空行分隔），避免报格式错误

            seq = f.readline().rstrip("\n")
            f.readline()  # "+" 分隔符，跳过
            quality = f.readline().rstrip("\n")
            
            if not header_line.startswith("@"):
                raise ValueError(f"FASTQ 格式错误: 期望 '@' 开头, 得到: {header_line!r}")
            
            yield header_line[1:], seq, quality  # 去掉 @