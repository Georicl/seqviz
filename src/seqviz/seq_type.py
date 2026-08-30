from enum import Enum


class SeqType(Enum):
    DNA = "dna"
    PROTEIN = "protein"
    UNKNOWN = "unknown"

DNA_CHARS = set("ATCGUNRYWSMKBDHV-.")
# 蛋白质独有氨基酸：除经典 E/F/I/L/P/Q 外，X（未知氨基酸）、J（亮/异亮）、
# O（吡咯赖氨酸）、Z（谷氨酰胺/谷氨酸）在实际蛋白质文件中很常见，
# 不纳入会导致含这些字符的蛋白质被误判为 UNKNOWN 并使用 DNA 调色板着色。
PROTEIN_ONLY_CHARS = set("EFILPQXJZO")

def detect_seq_type(seq: str, sample_size: int = 1000) -> SeqType:
    """
    序列属性检测器, 检测序列的简并码类型判断序列是碱基还是蛋白质或是其他文件
    """
    sample = seq[:sample_size].upper() # 获取指定长度的序列, 转换为大写
    non_dna = set(sample) - DNA_CHARS # 检测是否是DNA
    
    if not non_dna:
        # 如果没有, 返回DNA类型
        return SeqType.DNA

    if non_dna <= PROTEIN_ONLY_CHARS and (non_dna & set("EFILPQ")):
        # 如果全是蛋白质独有简并码且至少含一个经典蛋白残基（E/F/I/L/P/Q），返回蛋白质类型。
        # 要求经典残基：真核基因组软屏蔽（RepeatMasker 小写 x 重复区）主体为 DNA + x，
        # 若无此条件会被误判为 PROTEIN（真实蛋白质在前 1000 字符采样中几乎必含经典残基）。
        return SeqType.PROTEIN
        
    # 什么都不是返回未知
    return SeqType.UNKNOWN