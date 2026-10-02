"""FASTA/FASTQ 记录索引；偏移量始终是二进制文件的字节位置。"""

from collections.abc import Callable, Generator
from pathlib import Path

from seqviz.core.formats import FileFormat, open_seq_file

FASTA_READ_BLOCK = 64 * 1024
FASTA_QUICK_BYTES = 1024 * 1024


class SequenceInfo:
    """存储一条序列的元信息（不加载序列本身）。

    uniform / chars_per_line / file_line_width / checkpoints 为大序列分块加载
    指标缓存，首次加载时懒填充，避免重复全量扫描。
    """

    __slots__ = (
        "chars_per_line",
        "checkpoints",
        "file_line_width",
        "has_quality",
        "header",
        "index",
        "length",
        "offset",
        "uniform",
    )

    def __init__(
        self,
        index: int,
        header: str,
        offset: int,
        length: int = -1,
        has_quality: bool = False,
    ):
        self.index = index
        self.header = header
        self.offset = offset  # 文件中的字节偏移量（用于快速定位）
        self.length = length  # -1 表示未知（懒计算）
        self.has_quality = has_quality  # FASTQ 记录有质量值
        self.uniform = None  # None=未知；True/False=行宽是否恒定（仅大序列使用）
        self.chars_per_line = 0  # 每行碱基数（行宽恒定时有效）
        self.file_line_width = 0  # 每行字节数（含换行符，行宽恒定时有效）
        self.checkpoints = None  # [(碱基位置, 文件偏移)]，仅非等宽大序列使用


def iter_fasta_headers(
    filepath: Path,
    start_idx: int = 0,
    byte_limit: int | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Generator[SequenceInfo, None, bool]:
    """分块扫描 FASTA 表头；返回值表示是否读到 EOF。"""
    with open_seq_file(filepath, "rb") as f:
        idx = 0
        offset = 0
        at_line_start = True
        while byte_limit is None or offset < byte_limit:
            if cancelled is not None and cancelled():
                return False
            line_offset = offset
            block = (
                min(FASTA_READ_BLOCK, byte_limit - offset)
                if byte_limit is not None
                else FASTA_READ_BLOCK
            )
            raw_line = f.readline(block)
            if not raw_line:
                return True
            offset += len(raw_line)
            if at_line_start and raw_line.startswith(b">"):
                header_parts = [raw_line[1:]]
                while not raw_line.endswith(b"\n"):
                    if cancelled is not None and cancelled():
                        return False
                    raw_line = f.readline(FASTA_READ_BLOCK)
                    if not raw_line:
                        break
                    offset += len(raw_line)
                    header_parts.append(raw_line)
                if idx >= start_idx:
                    header = b"".join(header_parts).strip().decode(errors="replace")
                    yield SequenceInfo(idx, header, line_offset)
                idx += 1
            at_line_start = raw_line.endswith(b"\n")
        return False


def iter_sequences(
    filepath: Path,
    fmt: FileFormat,
    start_idx: int = 0,
    cancelled: Callable[[], bool] | None = None,
) -> Generator[SequenceInfo]:
    """通用序列迭代器：二进制模式流式解析 FASTA/FASTQ，yield SequenceInfo。

    Args:
        filepath: 序列文件路径
        fmt: 文件格式 (FASTA/FASTQ)
        start_idx: 起始索引（跳过之前的序列，用于后台续扫）
    """
    if fmt == FileFormat.FASTQ:
        offset = 0
        with open_seq_file(filepath, "rb") as f:
            idx = 0
            while True:
                if cancelled is not None and cancelled():
                    return
                record_offset = offset
                header_line = f.readline()
                if not header_line:
                    return
                offset += len(header_line)
                if not header_line.strip():
                    continue  # 跳过空行（尾部空行/空行分隔），避免产生幻影记录
                seq_line = f.readline()
                offset += len(seq_line)
                plus_line = f.readline()  # + 行
                offset += len(plus_line)
                quality_line = f.readline()  # quality 行
                offset += len(quality_line)
                if not (seq_line and plus_line and quality_line):
                    return  # 文件在记录中间截断：丢弃不完整记录，避免幻影条目
                if not header_line.startswith(b"@"):
                    raise ValueError(
                        f"FASTQ 格式错误: 期望 '@' 开头, 得到: {header_line.rstrip()!r}"
                    )
                if not plus_line.startswith(b"+"):
                    raise ValueError(
                        f"FASTQ 格式错误: 记录 {header_line[1:].strip()!r} 缺少 '+' 分隔符"
                    )
                seq_length = len(seq_line.rstrip(b"\r\n"))
                quality_length = len(quality_line.rstrip(b"\r\n"))
                if seq_length != quality_length:
                    raise ValueError(
                        f"FASTQ 格式错误: 记录 {header_line[1:].strip()!r} 的序列长度 "
                        f"{seq_length} 与质量值长度 {quality_length} 不一致"
                    )
                if idx >= start_idx:
                    header = header_line.strip()[1:].decode(errors="replace")
                    yield SequenceInfo(
                        idx, header, record_offset, seq_length, has_quality=True
                    )
                idx += 1
    else:
        yield from iter_fasta_headers(
            filepath, start_idx=start_idx, cancelled=cancelled
        )


def scan_file_quick(
    filepath: Path, fmt: FileFormat, limit: int = 500
) -> tuple[list[SequenceInfo], bool]:
    """快速扫描前 N 条；FASTA 同时限制首屏前读取量。"""
    sequences: list[SequenceInfo] = []
    scanner = (
        iter_fasta_headers(filepath, byte_limit=FASTA_QUICK_BYTES)
        if fmt == FileFormat.FASTA
        else iter_sequences(filepath, fmt)
    )
    while len(sequences) < limit:
        try:
            sequences.append(next(scanner))
        except StopIteration as stop:
            return sequences, bool(stop.value) if fmt == FileFormat.FASTA else True
    return sequences, False


def scan_file(filepath: Path, fmt: FileFormat) -> list[SequenceInfo]:
    """扫描文件建立索引（二进制模式，FASTA 不计算长度，支持 gzip）。"""
    return list(iter_sequences(filepath, fmt))
