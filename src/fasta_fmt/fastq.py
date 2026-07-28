from pathlib import Path
import gzip


def parse_fastq(filepath: str | Path):
    """
    流式解析 FASTQ 文件。
    逐条 yield (header, sequence, quality)。
    """
    filepath = Path(filepath)
    opener = gzip.open if filepath.suffix == ".gz" else open
    
    with opener(filepath, "rt") as f:
        while True:
            header_line = f.readline()
            if not header_line:
                break  # EOF
            
            header_line = header_line.rstrip("\n")
            seq = f.readline().rstrip("\n")
            plus = f.readline()  # "+" 分隔符，跳过
            quality = f.readline().rstrip("\n")
            
            if not header_line.startswith("@"):
                raise ValueError(f"FASTQ 格式错误: 期望 '@' 开头, 得到: {header_line!r}")
            
            yield header_line[1:], seq, quality  # 去掉 @