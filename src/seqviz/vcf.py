"""VCF (Variant Call Format) 解析层 — 纯解析，无 UI 依赖。

支持未压缩纯文本 VCF v4.x。采用懒扫描策略：
scan_vcf 只解析前 8 列（含 INFO），样本基因型按需 seek 回读。
"""

import re
from dataclasses import dataclass, field
from enum import Enum

_TRANSITIONS = {("A", "G"), ("G", "A"), ("C", "T"), ("T", "C")}

_ID_RE = re.compile(r"ID=([^,>]+)")
_DESC_RE = re.compile(r'Description="([^"]*)"')
_LEN_RE = re.compile(r"length=(\d+)")


class VariantType(Enum):
    TRANSITION = "transition"      # 转换（嘌呤↔嘌呤 / 嘧啶↔嘧啶）
    TRANSVERSION = "transversion"  # 颠换
    INSERTION = "insertion"        # 插入
    DELETION = "deletion"          # 缺失
    COMPLEX = "complex"            # 复杂变异


@dataclass
class Variant:
    chrom: str
    pos: int
    id: str                     # "." 存为 ""
    ref: str
    alt: str
    qual: float | None          # "." 或非数字存为 None
    filter: str
    info: dict = field(default_factory=dict)      # 懒扫描时已含 INFO（第8列）
    format_fields: list = field(default_factory=list)  # 懒扫描为空，按需填充
    samples: dict = field(default_factory=dict)   # 同上
    offset: int = 0             # 行首字节偏移（seek 回读用）
    raw: str = ""               # 完整原始行，按需填充，y 键复制用


@dataclass
class VcfMeta:
    fileformat: str = ""
    contigs: dict = field(default_factory=dict)      # ID → length
    info_defs: dict = field(default_factory=dict)    # ID → Description
    format_defs: dict = field(default_factory=dict)
    filter_defs: dict = field(default_factory=dict)
    samples: list = field(default_factory=list)


def classify_variant(ref: str, alt: str) -> VariantType:
    """按 REF/ALT 长度与碱基判定变异类型；多等位取第一个 ALT。"""
    first_alt = alt.split(",")[0]
    ref_u, alt_u = ref.upper(), first_alt.upper()
    if len(ref) == 1 and len(first_alt) == 1:
        return VariantType.TRANSITION if (ref_u, alt_u) in _TRANSITIONS else VariantType.TRANSVERSION
    if len(first_alt) > len(ref):
        return VariantType.INSERTION
    if len(ref) > len(first_alt):
        return VariantType.DELETION
    return VariantType.COMPLEX


def parse_genotype(sample_str: str, format_fields: list[str]) -> dict:
    """把 '0/1:15:99:10,5' 按 FORMAT 声明解析为 dict。

    GT 缺失(".") 归一为 "./."；AD 解析为 int 列表；其余可转 int 则转。
    """
    values = sample_str.split(":")
    result = {}
    for key, val in zip(format_fields, values):
        if key == "GT":
            result["GT"] = val if val != "." else "./."
        elif key == "AD":
            try:
                result["AD"] = [int(x) for x in val.split(",")]
            except ValueError:
                result["AD"] = []
        else:
            try:
                result[key] = int(val)
            except ValueError:
                result[key] = val
    return result


def parse_meta(header_lines: list[str]) -> VcfMeta:
    """解析 ## 元数据行（fileformat/contig/INFO/FORMAT/FILTER 定义）。"""
    meta = VcfMeta()
    for line in header_lines:
        line = line.rstrip("\n")
        if line.startswith("##fileformat="):
            meta.fileformat = line.split("=", 1)[1]
        elif line.startswith("##contig="):
            m = _ID_RE.search(line)
            lm = _LEN_RE.search(line)
            if m:
                meta.contigs[m.group(1)] = int(lm.group(1)) if lm else 0
        elif line.startswith("##INFO=") or line.startswith("##FORMAT="):
            m = _ID_RE.search(line)
            dm = _DESC_RE.search(line)
            target = meta.info_defs if line.startswith("##INFO=") else meta.format_defs
            if m:
                target[m.group(1)] = dm.group(1) if dm else ""
        elif line.startswith("##FILTER="):
            m = _ID_RE.search(line)
            dm = _DESC_RE.search(line)
            if m:
                meta.filter_defs[m.group(1)] = dm.group(1) if dm else ""
    return meta


def _parse_info(info_str: str) -> dict:
    """解析 INFO 列：'DP=45;AF=0.333;DB' → {'DP':'45','AF':'0.333','DB':''}。"""
    info = {}
    for item in info_str.split(";"):
        if not item:
            continue
        if "=" in item:
            k, v = item.split("=", 1)
            info[k] = v
        else:
            info[item] = ""   # Flag 型（如 DB）
    return info


def parse_variant_line(line: str, offset: int = 0,
                       sample_names: list[str] | None = None) -> Variant | None:
    """完整解析单条数据行；畸形行（<8 列或 POS 非整数）返回 None。"""
    raw = line.rstrip("\n")
    parts = raw.split("\t")
    if len(parts) < 8 or parts[0].startswith("#"):
        return None
    try:
        pos = int(parts[1])
    except ValueError:
        return None
    qual = None
    if parts[5] != ".":
        try:
            qual = float(parts[5])
        except ValueError:
            pass
    info = _parse_info(parts[7])
    format_fields = parts[8].split(":") if len(parts) > 8 else []
    names = sample_names or []
    samples = {}
    for i, s in enumerate(parts[9:]):
        name = names[i] if i < len(names) else f"sample{i + 1}"
        samples[name] = s
    return Variant(
        chrom=parts[0], pos=pos,
        id="" if parts[2] == "." else parts[2],
        ref=parts[3], alt=parts[4],
        qual=qual, filter=parts[6],
        info=info, format_fields=format_fields,
        samples=samples, offset=offset, raw=raw,
    )


def scan_vcf(path) -> tuple[VcfMeta, list[Variant], int]:
    """懒扫描：解析 meta + 每行前 8 列 + 字节 offset。

    样本列不解析（按需 load_variant_detail）。返回 (meta, variants, skipped)。
    """
    header_lines: list[str] = []
    variants: list[Variant] = []
    sample_names: list[str] = []
    skipped = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        while True:
            offset = f.tell()
            line = f.readline()
            if not line:
                break
            if line.startswith("##"):
                header_lines.append(line)
                continue
            if line.startswith("#CHROM"):
                cols = line.rstrip("\n").split("\t")
                sample_names = cols[9:] if len(cols) > 9 else []
                continue
            parts = line.rstrip("\n").split("\t", 8)  # 只切前 8 列，避免样本列开销
            if len(parts) < 8 or parts[0].startswith("#"):
                skipped += 1
                continue
            try:
                pos = int(parts[1])
            except ValueError:
                skipped += 1
                continue
            qual = None
            if parts[5] != ".":
                try:
                    qual = float(parts[5])
                except ValueError:
                    pass
            variants.append(Variant(
                chrom=parts[0], pos=pos,
                id="" if parts[2] == "." else parts[2],
                ref=parts[3], alt=parts[4],
                qual=qual, filter=parts[6],
                info=_parse_info(parts[7]),
                offset=offset,
            ))
    meta = parse_meta(header_lines)
    meta.samples = sample_names
    return meta, variants, skipped


def load_variant_detail(path, variant: Variant, sample_names: list[str]) -> Variant:
    """seek(offset) 回读完整行，填充 format_fields/samples/raw（原地修改并返回）。"""
    if variant.raw:
        return variant  # 已加载
    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(variant.offset)
        line = f.readline()
    full = parse_variant_line(line, variant.offset, sample_names)
    if full is not None:
        variant.format_fields = full.format_fields
        variant.samples = full.samples
        variant.raw = full.raw
    return variant


def compute_stats(variants: list[Variant]) -> dict:
    """统计总数/SNP/InDel/Ts:Tv/PASS 数/AF 均值（懒扫描索引即可计算）。"""
    snp = indel = complex_ = ts = tv = pass_count = 0
    af_sum = 0.0
    af_count = 0
    for v in variants:
        t = classify_variant(v.ref, v.alt)
        if t is VariantType.TRANSITION:
            snp += 1
            ts += 1
        elif t is VariantType.TRANSVERSION:
            snp += 1
            tv += 1
        elif t in (VariantType.INSERTION, VariantType.DELETION):
            indel += 1
        else:
            complex_ += 1
        if v.filter == "PASS":
            pass_count += 1
        af = v.info.get("AF", "")
        if af:
            try:
                af_sum += float(af.split(",")[0])
                af_count += 1
            except ValueError:
                pass
    return {
        "total": len(variants),
        "snp": snp,
        "indel": indel,
        "complex": complex_,
        "ts_tv": (ts / tv) if tv else 0.0,
        "pass_count": pass_count,
        "mean_af": (af_sum / af_count) if af_count else 0.0,
    }
