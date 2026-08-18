import gzip
from collections.abc import Generator
from pathlib import Path


def parse_fastq(filepath: str | Path) -> Generator[tuple[str, str, str], None, None]:
    """
    流式解析 FASTQ 文件。
    逐条 yield (header, sequence, quality)。

    文件在记录中间截断（缺序列行/分隔符/质量行）时抛 ValueError，
    避免静默产出空序列/空质量的幻影记录。
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

            if not header_line.startswith("@"):
                raise ValueError(f"FASTQ 格式错误: 期望 '@' 开头, 得到: {header_line!r}")

            seq = f.readline()
            if not seq:
                raise ValueError(f"FASTQ 格式错误: 记录 {header_line[1:]!r} 在序列行处截断")
            plus = f.readline()
            if not plus:
                raise ValueError(f"FASTQ 格式错误: 记录 {header_line[1:]!r} 缺少 '+' 分隔符（文件截断）")
            if not plus.startswith("+"):
                raise ValueError(f"FASTQ 格式错误: 期望 '+' 分隔符, 得到: {plus.rstrip(chr(10))!r}（序列可能跨行）")
            quality = f.readline()
            if not quality:
                raise ValueError(f"FASTQ 格式错误: 记录 {header_line[1:]!r} 缺少质量行（文件截断）")

            yield header_line[1:], seq.rstrip("\n"), quality.rstrip("\n")
