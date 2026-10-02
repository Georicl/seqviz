"""按字符组成识别核酸与蛋白质序列。"""

from enum import Enum


class SeqType(Enum):
    DNA = "dna"
    PROTEIN = "protein"
    UNKNOWN = "unknown"


DNA_CHARS = set("ATCGUNRYWSMKBDHV-.")
# 包含蛋白质扩展字母：X 未知，J 亮/异亮，O 吡咯赖氨酸，Z 谷氨酰胺/谷氨酸。
PROTEIN_ONLY_CHARS = set("EFILPQXJZO")


def detect_seq_type(seq: str, sample_size: int = 1000) -> SeqType:
    """
    序列属性检测器, 检测序列的简并码类型判断序列是碱基还是蛋白质或是其他文件
    """
    sample = seq[:sample_size].upper()  # 获取指定长度的序列, 转换为大写
    non_dna = set(sample) - DNA_CHARS  # 检测是否是DNA

    if not non_dna:
        # 如果没有, 返回DNA类型
        return SeqType.DNA

    if non_dna <= PROTEIN_ONLY_CHARS and (non_dna & set("EFILPQ")):
        # E/F/I/L/P/Q 提供蛋白证据，避免仅含软屏蔽 x 的 DNA 被误判。
        return SeqType.PROTEIN

    # 什么都不是返回未知
    return SeqType.UNKNOWN
