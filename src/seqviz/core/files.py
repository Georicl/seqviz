"""序列文件发现与计数；调用方负责显示读取错误。"""

import threading
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from seqviz.core.formats import (
    DEFAULT_EXTENSIONS,
    FileFormat,
    detect_format,
    open_seq_file,
)
from seqviz.core.index import iter_fasta_headers


@dataclass
class FileInfo:
    """文件元信息；None 表示条数尚未完成统计。"""

    path: Path
    size: int
    fmt: FileFormat
    seq_count: int | None = None

    @property
    def name(self) -> str:
        return self.path.name


def is_sequence_file(
    path: Path, extensions: Collection[str] = DEFAULT_EXTENSIONS
) -> bool:
    """按允许的后缀识别文件；压缩 VCF 暂不列入选择器。"""
    if not path.is_file():
        return False
    if path.suffix.lower() == ".gz":
        suffix = Path(path.stem).suffix.lower()
        return suffix in extensions and suffix != ".vcf"
    return path.suffix.lower() in extensions


def scan_directory(
    directory: Path, extensions: Collection[str] = DEFAULT_EXTENSIONS
) -> list[FileInfo]:
    """返回目录中的序列文件，按文件名排序。"""
    return [
        FileInfo(entry, entry.stat().st_size, detect_format(entry))
        for entry in sorted(directory.iterdir())
        if is_sequence_file(entry, extensions)
    ]


def count_sequences(
    path: Path, fmt: FileFormat, cancel_event: threading.Event | None = None
) -> int:
    """统计 FASTA/FASTQ 记录或 VCF 数据行；取消时返回已读部分。"""
    if cancel_event is not None and cancel_event.is_set():
        return 0
    if fmt == FileFormat.FASTA:
        # 有界扫描避免未换行的染色体整条进入内存。
        cancelled = cancel_event.is_set if cancel_event is not None else None
        return sum(1 for _ in iter_fasta_headers(path, cancelled=cancelled))

    count = 0
    with open_seq_file(path, "rb") as f:
        if fmt == FileFormat.VCF:
            for line_number, line in enumerate(f, 1):
                if not line.startswith(b"#") and line.strip():
                    count += 1
                if (
                    cancel_event is not None
                    and line_number % 16384 == 0
                    and cancel_event.is_set()
                ):
                    break
        else:
            # FASTQ 允许记录间空行；只计算完整的四行记录。
            while header := f.readline():
                if not header.strip():
                    continue
                if not (f.readline() and f.readline() and f.readline()):
                    break
                count += 1
                if (
                    cancel_event is not None
                    and count % 4096 == 0
                    and cancel_event.is_set()
                ):
                    break
    return count
