"""序列格式识别与压缩文件读取。"""

import gzip
from enum import Enum
from pathlib import Path
from typing import IO

DEFAULT_EXTENSIONS = (
    ".fa",
    ".fasta",
    ".fna",
    ".faa",
    ".aa",
    ".seq",
    ".fq",
    ".fastq",
    ".vcf",
)


def open_seq_file(filepath: Path, mode: str = "rb", **kwargs) -> IO:
    """打开序列文件（透明处理 gzip 压缩）。

    默认二进制模式，保证 offset 计算正确且不受 CRLF 影响。
    """
    if filepath.suffix.lower() == ".gz":
        return gzip.open(filepath, mode, **kwargs)
    return open(filepath, mode, **kwargs)


class FileFormat(Enum):
    FASTA = "fasta"
    FASTQ = "fastq"
    VCF = "vcf"


def detect_format(filepath: Path) -> FileFormat:
    """根据文件后缀或首字符自动检测格式（支持 gzip，后缀大小写不敏感）。

    精确后缀匹配优先（.vcf → VCF；.fastq/.fq → FASTQ；.fasta/.fa 等 → FASTA），
    后缀不明确时读首字符判定（'@' → FASTQ，否则 FASTA）。所有入口共用此检测规则。
    """
    suffix = filepath.suffix.lower()
    if suffix == ".gz":
        suffix = (
            "." + filepath.stem.rsplit(".", 1)[-1].lower()
            if "." in filepath.stem
            else ""
        )
    if suffix == ".vcf":
        return FileFormat.VCF
    if suffix in (".fastq", ".fq"):
        return FileFormat.FASTQ
    if suffix in (".fasta", ".fa", ".fna", ".faa", ".aa", ".seq"):
        return FileFormat.FASTA
    # 后缀不明确时读首字符（透明处理 gzip）
    with open_seq_file(filepath, "rb") as f:
        first_byte = f.read(1)
    return FileFormat.FASTQ if first_byte == b"@" else FileFormat.FASTA


def is_vcf_file(filepath: Path) -> bool:
    """判断是否为未压缩 VCF 文件。"""
    return filepath.is_file() and filepath.suffix.lower() == ".vcf"
