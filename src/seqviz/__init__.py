"""seqviz — 生物序列数据终端可视化工具。

FASTA / FASTQ / VCF 的彩色查看、统计与交互式终端浏览。
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("seqviz")
except PackageNotFoundError:  # 源码树直接运行时（未安装）回退
    __version__ = "0.7.0rc2"

__all__ = ["__version__"]
