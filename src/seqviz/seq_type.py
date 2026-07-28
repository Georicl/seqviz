from enum import Enum

class SeqType(Enum):
    DNA = "dna"
    PROTEIN = "protein"
    UNKNOWN = "unknown"

DNA_CHARS = set("ATCGUNRYWSMKBDHV-.")

def detect_seq_type(seq: str, sample_size: int = 1000) -> SeqType:
    """
    序列属性检测器, 检测序列的简并码类型判断序列是碱基还是蛋白质或是其他文件
    """
    sample = seq[:sample_size].upper() # 获取指定长度的序列, 转换为大写
    non_dna = set(sample) - DNA_CHARS # 检测是否是DNA
    
    if not non_dna:
        # 如果没有, 返回DNA类型
        return SeqType.DNA

    protein_field = set("EFILPQ")
    if non_dna <= protein_field:
        # 如果全是蛋白质独有简并码, 返回蛋白质类型
        return SeqType.PROTEIN
        
    # 什么都不是返回未知
    return SeqType.UNKNOWN