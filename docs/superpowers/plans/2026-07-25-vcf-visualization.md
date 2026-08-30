# VCF 可视化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 seqviz 增加 VCF 终端可视化：独立 VcfBrowser App（双栏布局、懒扫描、过滤排序、基因型矩阵）。

**Architecture:** 纯解析层 `vcf.py`（无 UI 依赖）+ Textual App `vcf_browser.py`（镜像 browser.py 结构），`seqviz browse` 按 `.vcf` 后缀路由，复用主题/配置/剪贴板基础设施。

**Tech Stack:** Python 3.12+, Textual, Rich, Typer, pytest。测试命令统一 `uv run pytest test/ -x -q`。

**Spec:** `docs/superpowers/specs/2026-07-25-vcf-visualization-design.md`

---

### Task 1: vcf.py 数据结构 + classify_variant + parse_genotype

**Files:**
- Create: `src/seqviz/vcf.py`
- Test: `test/test_vcf.py`

- [ ] **Step 1: 写失败测试** `test/test_vcf.py`

```python
"""VCF 解析层测试。"""
import json
from pathlib import Path

import pytest

from seqviz import vcf as vcf_mod
from seqviz.vcf import (
    Variant, VcfMeta, VariantType,
    classify_variant, parse_genotype,
)

SAMPLE_VCF = Path(__file__).parent / "sample.vcf"


class TestClassifyVariant:
    def test_transition(self):
        assert classify_variant("A", "G") == VariantType.TRANSITION
        assert classify_variant("G", "A") == VariantType.TRANSITION
        assert classify_variant("C", "T") == VariantType.TRANSITION
        assert classify_variant("T", "C") == VariantType.TRANSITION

    def test_transversion(self):
        assert classify_variant("A", "T") == VariantType.TRANSVERSION
        assert classify_variant("G", "C") == VariantType.TRANSVERSION
        assert classify_variant("A", "C") == VariantType.TRANSVERSION

    def test_insertion(self):
        assert classify_variant("T", "TG") == VariantType.INSERTION
        assert classify_variant("A", "ACGT") == VariantType.INSERTION

    def test_deletion(self):
        assert classify_variant("AT", "A") == VariantType.DELETION
        assert classify_variant("GC", "G") == VariantType.DELETION

    def test_multiallelic_uses_first_alt(self):
        assert classify_variant("A", "G,T") == VariantType.TRANSITION

    def test_case_insensitive(self):
        assert classify_variant("a", "g") == VariantType.TRANSITION


class TestParseGenotype:
    def test_full_fields(self):
        result = parse_genotype("0/1:15:99:10,5", ["GT", "DP", "GQ", "AD"])
        assert result["GT"] == "0/1"
        assert result["DP"] == 15
        assert result["GQ"] == 99
        assert result["AD"] == [10, 5]

    def test_missing_gt(self):
        result = parse_genotype(".:.:.", ["GT", "DP", "GQ"])
        assert result["GT"] == "./."

    def test_fewer_values_than_fields(self):
        result = parse_genotype("0/0", ["GT", "DP"])
        assert result == {"GT": "0/0"}

    def test_non_int_kept_as_str(self):
        result = parse_genotype("0/1:abc", ["GT", "DP"])
        assert result["DP"] == "abc"
```

- [ ] **Step 2: 运行确认失败**：`uv run pytest test/test_vcf.py -x -q` → FAIL（模块不存在）

- [ ] **Step 3: 实现** `src/seqviz/vcf.py`

```python
"""VCF (Variant Call Format) 解析层 — 纯解析，无 UI 依赖。

支持未压缩纯文本 VCF v4.x。采用懒扫描策略：
scan_vcf 只解析前 8 列（含 INFO），样本基因型按需 seek 回读。
"""

from dataclasses import dataclass, field
from enum import Enum

_TRANSITIONS = {("A", "G"), ("G", "A"), ("C", "T"), ("T", "C")}


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
```

- [ ] **Step 4: 运行确认通过**：`uv run pytest test/test_vcf.py -x -q` → PASS
- [ ] **Step 5: 提交**：`git add src/seqviz/vcf.py test/test_vcf.py && git commit -m "feat(vcf): variant classification and genotype parsing"`

---

### Task 2: parse_meta（## 头部解析）

**Files:** Modify `src/seqviz/vcf.py` / `test/test_vcf.py`

- [ ] **Step 1: 写失败测试**（追加到 `test/test_vcf.py`）

```python
from seqviz.vcf import parse_meta


class TestParseMeta:
    def test_sample_vcf_meta(self):
        lines = SAMPLE_VCF.read_text().splitlines()
        header = [l for l in lines if l.startswith("##")]
        meta = parse_meta(header)
        assert meta.fileformat == "VCFv4.3"
        assert meta.contigs["chr1"] == 79116311
        assert meta.info_defs["DP"] == "Total Depth"
        assert meta.format_defs["GT"] == "Genotype"
        assert meta.filter_defs["PASS"] == "All filters passed"

    def test_empty_header(self):
        meta = parse_meta([])
        assert meta.fileformat == ""
        assert meta.contigs == {}

    def test_contig_without_length(self):
        meta = parse_meta(["##contig=<ID=chrX>"])
        assert meta.contigs["chrX"] == 0
```

- [ ] **Step 2: 运行确认失败** → FAIL（parse_meta 未定义）
- [ ] **Step 3: 实现**（追加到 `vcf.py`）

```python
import re

_ID_RE = re.compile(r"ID=([^,>]+)")
_DESC_RE = re.compile(r'Description="([^"]*)"')
_LEN_RE = re.compile(r"length=(\d+)")


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
```

- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交**：`git commit -am "feat(vcf): parse VCF meta header lines"`

---

### Task 3: scan_vcf + parse_variant_line + load_variant_detail

**Files:** Modify `src/seqviz/vcf.py` / `test/test_vcf.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
from seqviz.vcf import scan_vcf, parse_variant_line, load_variant_detail


class TestParseVariantLine:
    def test_full_line(self):
        line = "chr1\t10234\trs12345\tA\tG\t99.5\tPASS\tDP=45;AF=0.333;DB\tGT:DP\t0/1:15\t0/0:18"
        v = parse_variant_line(line, offset=100, sample_names=["s1", "s2"])
        assert v.chrom == "chr1" and v.pos == 10234
        assert v.id == "rs12345" and v.qual == 99.5
        assert v.info == {"DP": "45", "AF": "0.333", "DB": ""}
        assert v.samples == {"s1": "0/1:15", "s2": "0/0:18"}
        assert v.offset == 100

    def test_dot_id_and_qual(self):
        v = parse_variant_line("chr1\t5\t.\tA\tG\t.\tPASS\t.")
        assert v.id == "" and v.qual is None

    def test_malformed_fewer_than_8_cols(self):
        assert parse_variant_line("chr1\t100\tA") is None

    def test_bad_pos(self):
        assert parse_variant_line("chr1\txyz\t.\tA\tG\t.\tPASS\t.") is None

    def test_header_line_rejected(self):
        assert parse_variant_line("#CHROM\tPOS\tID") is None


class TestScanVcf:
    def test_sample_vcf(self):
        meta, variants, skipped = scan_vcf(SAMPLE_VCF)
        assert len(variants) == 17
        assert skipped == 0
        assert meta.samples == ["sample1", "sample2", "sample3"]
        first = variants[0]
        assert (first.chrom, first.pos, first.ref, first.alt) == ("chr1", 10234, "A", "G")
        assert first.info["AF"] == "0.333"   # INFO 在索引阶段已解析
        assert first.samples == {}            # 样本列懒加载
        assert first.offset > 0

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.vcf"
        f.write_text("")
        meta, variants, skipped = scan_vcf(f)
        assert variants == [] and meta.samples == []

    def test_no_header_line(self, tmp_path):
        f = tmp_path / "nohdr.vcf"
        f.write_text("chr1\t1\t.\tA\tG\t.\tPASS\t.\n")
        meta, variants, skipped = scan_vcf(f)
        assert len(variants) == 1
        assert meta.samples == []

    def test_malformed_lines_skipped_and_counted(self, tmp_path):
        f = tmp_path / "bad.vcf"
        f.write_text("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                     "chr1\t1\t.\tA\tG\t.\tPASS\t.\n"
                     "garbage line\n"
                     "chr1\t2\t.\tC\tT\t.\tPASS\t.\n")
        _, variants, skipped = scan_vcf(f)
        assert len(variants) == 2 and skipped == 1


class TestLoadVariantDetail:
    def test_roundtrip(self):
        _, variants, _ = scan_vcf(SAMPLE_VCF)
        first = variants[0]
        meta_samples = ["sample1", "sample2", "sample3"]
        load_variant_detail(SAMPLE_VCF, first, meta_samples)
        assert first.samples["sample1"] == "0/1:15:99:10,5"
        assert first.format_fields == ["GT", "DP", "GQ", "AD"]
        assert first.raw.startswith("chr1\t10234")
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（追加到 `vcf.py`）

```python
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


def _parse_info(info_str: str) -> dict:
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
```

- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交**：`git commit -am "feat(vcf): lazy scan index and on-demand detail loading"`

---

### Task 4: compute_stats（状态栏统计）

**Files:** Modify `src/seqviz/vcf.py` / `test/test_vcf.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
from seqviz.vcf import compute_stats


class TestComputeStats:
    def test_sample_vcf_stats(self):
        _, variants, _ = scan_vcf(SAMPLE_VCF)
        stats = compute_stats(variants)
        assert stats["total"] == 17
        assert stats["snp"] + stats["indel"] + stats["complex"] == 17
        assert stats["snp"] == 11
        assert stats["indel"] == 6
        assert stats["pass_count"] == 13
        assert stats["ts_tv"] == pytest.approx(7 / 4)  # 样本中 7 转换 4 颠换
        assert 0.0 < stats["mean_af"] < 1.0

    def test_empty(self):
        stats = compute_stats([])
        assert stats["total"] == 0 and stats["ts_tv"] == 0.0

    def test_no_tv_avoids_zero_division(self):
        v = Variant("chr1", 1, "", "A", "G", 50.0, "PASS")
        stats = compute_stats([v])
        assert stats["ts_tv"] == 0.0
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（追加到 `vcf.py`）

```python
def compute_stats(variants: list[Variant]) -> dict:
    """统计总数/SNP/InDel/Ts:Tv/PASS 数/AF 均值（懒扫描索引即可计算）。"""
    snp = indel = complex_ = ts = tv = pass_count = 0
    af_sum = 0.0
    af_count = 0
    for v in variants:
        t = classify_variant(v.ref, v.alt)
        if t is VariantType.TRANSITION:
            snp += 1; ts += 1
        elif t is VariantType.TRANSVERSION:
            snp += 1; tv += 1
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
    total = len(variants)
    return {
        "total": total, "snp": snp, "indel": indel, "complex": complex_,
        "ts_tv": (ts / tv) if tv else 0.0,
        "pass_count": pass_count,
        "mean_af": (af_sum / af_count) if af_count else 0.0,
    }
```

- [ ] **Step 4: 运行确认通过**（注意核对 sample.vcf 实际 Ts/Tv，若与测试断言不符以实测修正测试断言）
- [ ] **Step 5: 提交**：`git commit -am "feat(vcf): compute summary statistics for status bar"`

---

### Task 5: theme.py 新增 build_vcf_browser_css

**Files:** Modify `src/seqviz/theme.py`

- [ ] **Step 1:** 参照 `build_file_browser_css` 结构追加：

```python
def build_vcf_browser_css(theme: dict) -> str:
    """生成 VCF 浏览器（VcfBrowser）的 CSS。"""
    bg = theme["background"]
    fg = theme["foreground"]
    border = theme["border"]
    accent = theme.get("accent", fg)
    panel = theme.get("panel", bg)
    highlight = theme.get("highlight", bg)
    return f"""
    Screen {{
        background: {bg};
    }}
    Horizontal {{
        height: 1fr;
    }}
    #variant-list {{
        width: 40;
        border-right: thick {border};
        background: {bg};
        color: {fg};
    }}
    #variant-list:focus {{
        border-right: thick {accent};
    }}
    #variant-list > OptionList > .option-list--option-highlighted {{
        background: {highlight};
        color: {fg};
    }}
    #detail {{
        width: 1fr;
        padding: 0 1;
        background: {bg};
        color: {fg};
    }}
    #status-bar {{
        dock: bottom;
        height: 1;
        background: {panel};
        color: {fg};
    }}
    Header {{
        background: {panel};
        color: {fg};
    }}
    Footer {{
        background: {panel};
        color: {fg};
    }}
    """
```

- [ ] **Step 2: 运行 `uv run pytest test/ -x -q` 确认无回归**
- [ ] **Step 3: 提交**：`git commit -am "feat(theme): add build_vcf_browser_css"`

---

### Task 6: vcf_browser.py 骨架（列表 + 详情渲染）

**Files:** Create `src/seqviz/vcf_browser.py`, Test `test/test_vcf_browser.py`

- [ ] **Step 1: 写失败测试**

```python
"""VcfBrowser TUI 测试。"""
from pathlib import Path

import pytest
from textual.widgets import OptionList

from seqviz.vcf_browser import VcfBrowser

SAMPLE_VCF = Path(__file__).parent / "sample.vcf"


@pytest.mark.asyncio
async def test_app_starts_and_lists_variants():
    app = VcfBrowser(SAMPLE_VCF)
    async with app.run_test() as pilot:
        ol = app.query_one("#variant-list", OptionList)
        assert ol.option_count == 17


@pytest.mark.asyncio
async def test_detail_shows_selected_variant():
    app = VcfBrowser(SAMPLE_VCF)
    async with app.run_test() as pilot:
        detail = app.query_one("#detail")
        text = str(detail.renderable) if hasattr(detail, "renderable") else ""
        # 第一条变异的坐标应出现在详情区
        assert "10234" in app._detail_text()
```

（注：确认 pytest-asyncio 已可用——参考现有 `test_browser.py` 的 async 测试写法与 conftest，若项目用 `run_test` 同步上下文则对齐其风格。）

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现** `src/seqviz/vcf_browser.py`（要点，镜像 browser.py 结构）：

```python
"""VCF 交互式浏览器 — 双栏：左变异列表 + 右详情/矩阵。"""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option
from rich.text import Text

from seqviz import config
from seqviz import theme as theme_mod
from seqviz.vcf import (
    Variant, VariantType, VcfMeta,
    classify_variant, compute_stats, load_variant_detail,
    parse_genotype, scan_vcf,
)

DARK = theme_mod.is_dark_theme(theme_mod.get_theme_name())

_TYPE_SYMBOL = {
    VariantType.TRANSITION: ("●", "green"),
    VariantType.TRANSVERSION: ("●", "blue"),
    VariantType.INSERTION: ("◆", "yellow"),
    VariantType.DELETION: ("◆", "red"),
    VariantType.COMPLEX: ("◆", "magenta"),
}
_TYPE_LABEL = {
    VariantType.TRANSITION: "SNP 转换",
    VariantType.TRANSVERSION: "SNP 颠换",
    VariantType.INSERTION: "插入",
    VariantType.DELETION: "缺失",
    VariantType.COMPLEX: "复杂变异",
}
_GT_LABEL = {"0/0": "纯合参考", "0/1": "杂合", "1/0": "杂合", "1/1": "纯合变异"}
_FILTER_CYCLE = ["全部", "PASS", "SNP", "InDel"]


class VcfBrowser(App):
    TITLE = "Seqviz — VCF"
    DARK = DARK

    BINDINGS = [
        Binding("j", "cursor_down", "下移"),
        Binding("k", "cursor_up", "上移"),
        Binding("n", "next_variant", "下一条"),
        Binding("p", "prev_variant", "上一条"),
        Binding("space", "page_down", "下翻页"),
        Binding("b", "page_up", "上翻页"),
        Binding("g", "home", "顶部"),
        Binding("G", "end", "底部"),
        Binding("slash", "search", "搜索"),
        Binding("f", "cycle_filter", "过滤"),
        Binding("s", "toggle_sort", "排序"),
        Binding("t", "toggle_view", "矩阵"),
        Binding("i", "file_info", "信息"),
        Binding("y", "copy_line", "复制"),
        Binding("question_mark", "help", "帮助"),
        Binding("q", "quit", "退出"),
    ]

    def __init__(self, filepath: Path):
        super().__init__()
        self.filepath = filepath
        self.meta, self.variants, self.skipped = scan_vcf(filepath)
        self.stats = compute_stats(self.variants)
        self.view: list[int] = list(range(len(self.variants)))  # 过滤/排序后的下标映射
        self.filter_mode = "全部"
        self.sort_mode = "位置"
        self.matrix_mode = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield OptionList(id="variant-list")
            yield Static("", id="detail")
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self):
        self.query_one(OptionList).styles  # noqa
        self._refresh_list()
        self.query_one("#variant-list", OptionList).focus()

    # ── 列表 ──
    def _make_option(self, v: Variant) -> Option:
        symbol, _color = _TYPE_SYMBOL[classify_variant(v.ref, v.alt)]
        line = Text()
        # 行颜色按 FILTER/QUAL 编码可信度
        if v.filter == "PASS":
            row_style = "green"
        elif v.filter == "LowDP" or (v.qual is not None and v.qual < 20):
            row_style = "red"
        else:
            row_style = "yellow"
        qual_s = f"{v.qual:>6.1f}" if v.qual is not None else "     -"
        vid = v.id or "."
        line.append(f"{symbol} ", style=_color)
        line.append(f"{v.chrom}:{v.pos:,}", style=row_style)
        line.append(f"  {vid:<12}", style="dim")
        summary = f"{v.ref}→{v.alt}" if len(v.ref) <= 3 and len(v.alt) <= 3 else (
            "ins" if classify_variant(v.ref, v.alt) is VariantType.INSERTION else "del")
        line.append(f"{summary:<8}")
        line.append(qual_s, style=row_style)
        return Option(line)

    def _refresh_list(self):
        ol = self.query_one("#variant-list", OptionList)
        ol.clear_options()
        ol.add_options([self._make_option(self.variants[i]) for i in self.view])
        if self.view:
            ol.highlighted = 0
            self._show_detail(0)
        self._update_status_bar()

    # ── 详情 ──
    def _detail_text(self) -> str:
        """当前详情的纯文本（供测试断言与复制）。"""
        if not self.view:
            return ""
        ol = self.query_one("#variant-list", OptionList)
        idx = self.view[ol.highlighted or 0]
        v = self.variants[idx]
        load_variant_detail(self.filepath, v, self.meta.samples)
        return str(self._build_detail(v))

    def _build_detail(self, v: Variant) -> Text:
        t = classify_variant(v.ref, v.alt)
        sym, color = _TYPE_SYMBOL[t]
        txt = Text()
        txt.append(f"{sym} ", style=color)
        txt.append(f"[{_TYPE_LABEL[t]}]", style=f"bold {color}")
        if v.id:
            txt.append(f" {v.id}", style="bold")
        pass_color = "green" if v.filter == "PASS" else "red"
        txt.append(f"   {v.filter}", style=f"bold {pass_color}")
        txt.append("\n\n")
        txt.append("  位置     ", style="dim"); txt.append(f"{v.chrom}:{v.pos:,}\n", style="bold")
        txt.append("  变异     ", style="dim"); txt.append(f"{v.ref} → {v.alt}\n", style="bold")
        qual_s = f"{v.qual:.1f}" if v.qual is not None else "-"
        txt.append("  质量     ", style="dim"); txt.append(f"{qual_s}\n", style="bold")
        if v.info:
            txt.append("\n"); txt.append("─" * 40 + "\n", style="dim")
            for k, val in v.info.items():
                desc = self.meta.info_defs.get(k, "")
                txt.append(f"  {k:<6}", style="cyan")
                txt.append(f" {val or '(flag)'}", style="bold")
                if desc:
                    txt.append(f"  {desc}", style="dim")
                txt.append("\n")
        if v.samples:
            txt.append("\n"); txt.append("─" * 40 + "\n", style="dim")
            txt.append("  基因型\n\n")
            for name, raw_gt in v.samples.items():
                gt = parse_genotype(raw_gt, v.format_fields)
                gt_s = gt.get("GT", "./.")
                label = _GT_LABEL.get(gt_s, gt_s)
                txt.append(f"  {name:<12}", style="bold")
                txt.append(f"{gt_s} {label}", style="yellow")
                if "DP" in gt:
                    txt.append(f"  DP={gt['DP']}", style="dim")
                if "GQ" in gt:
                    txt.append(f"  GQ={gt['GQ']}", style="dim")
                txt.append("\n")
                ad = gt.get("AD")
                if ad and sum(ad) > 0:
                    total = sum(ad)
                    ref_w = round(ad[0] / total * 20)
                    txt.append("            REF ", style="dim")
                    txt.append("▓" * ref_w, style="green")
                    txt.append(f" {ad[0]}\n", style="dim")
                    txt.append("            ALT ", style="dim")
                    txt.append("▓" * (20 - ref_w), style="red")
                    txt.append(f" {sum(ad[1:])}\n", style="dim")
        return txt

    def _show_detail(self, list_index: int):
        if self.matrix_mode:
            self._render_matrix()
            return
        idx = self.view[list_index]
        v = self.variants[idx]
        load_variant_detail(self.filepath, v, self.meta.samples)
        detail = self.query_one("#detail", Static)
        detail.update(self._build_detail(v))

    # ── 状态栏 ──
    def _update_status_bar(self):
        s = compute_stats([self.variants[i] for i in self.view])
        bar = self.query_one("#status-bar", Static)
        bar.update(Text.from_markup(
            f" {s['total']} 变异 │ SNP {s['snp']} · InDel {s['indel']} │ "
            f"Ts/Tv {s['ts_tv']:.2f} │ PASS {s['pass_count']} │ "
            f"AF均值 {s['mean_af']:.2f} │ [过滤:{self.filter_mode}] [排序:{self.sort_mode}]"
            + (f" │ 跳过{s.__class__ and self.skipped}行畸形" if self.skipped else "")
        ))

    # ── 事件 ──
    def on_option_list_option_highlighted(self, event):
        if event.option is not None:
            self._show_detail(event.option_index)

    def action_cursor_down(self):
        ol = self.query_one("#variant-list", OptionList)
        ol.action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#variant-list", OptionList).action_cursor_up()

    def action_next_variant(self):
        self.action_cursor_down()

    def action_prev_variant(self):
        self.action_cursor_up()

    def action_page_down(self):
        self.query_one("#variant-list", OptionList).action_page_down()

    def action_page_up(self):
        self.query_one("#variant-list", OptionList).action_page_up()

    def action_home(self):
        self.query_one("#variant-list", OptionList).highlighted = 0

    def action_end(self):
        ol = self.query_one("#variant-list", OptionList)
        ol.highlighted = ol.option_count - 1

    def action_quit(self):
        self.exit()

    def get_css(self):  # 若项目用 CSS 变量注入方式则对齐 browser.py 的接入点
        return theme_mod.build_vcf_browser_css(theme_mod.get_theme())
```

（CSS 接入方式：对照 browser.py 现有做法——若它用 `CSS = ...` 类变量或 `self.stylesheet`，则按同样方式接入 `build_vcf_browser_css`，删除示意中的 `get_css`。）

- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交**：`git commit -am "feat(vcf): VcfBrowser skeleton with list and detail pane"`

---

### Task 7: 过滤 / 排序 / 搜索

**Files:** Modify `src/seqviz/vcf_browser.py` / `test/test_vcf_browser.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_filter_cycle():
    app = VcfBrowser(SAMPLE_VCF)
    async with app.run_test() as pilot:
        ol = app.query_one("#variant-list", OptionList)
        assert ol.option_count == 17
        await pilot.press("f")  # PASS only
        assert app.filter_mode == "PASS"
        assert ol.option_count == 13
        await pilot.press("f")  # SNP
        assert app.filter_mode == "SNP"
        await pilot.press("f")  # InDel
        assert app.filter_mode == "InDel"
        await pilot.press("f")  # 回到全部
        assert ol.option_count == 17


@pytest.mark.asyncio
async def test_sort_by_qual():
    app = VcfBrowser(SAMPLE_VCF)
    async with app.run_test() as pilot:
        await pilot.press("s")
        assert app.sort_mode == "QUAL"
        first_idx = app.view[0]
        quals = [app.variants[i].qual or -1 for i in app.view]
        assert quals == sorted(quals, reverse=True)
        await pilot.press("s")
        assert app.sort_mode == "位置"
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**（追加 actions 与 view 重算）

```python
    def _apply_filter_sort(self):
        idxs = list(range(len(self.variants)))
        if self.filter_mode == "PASS":
            idxs = [i for i in idxs if self.variants[i].filter == "PASS"]
        elif self.filter_mode == "SNP":
            idxs = [i for i in idxs if classify_variant(
                self.variants[i].ref, self.variants[i].alt)
                in (VariantType.TRANSITION, VariantType.TRANSVERSION)]
        elif self.filter_mode == "InDel":
            idxs = [i for i in idxs if classify_variant(
                self.variants[i].ref, self.variants[i].alt)
                in (VariantType.INSERTION, VariantType.DELETION)]
        if self.sort_mode == "QUAL":
            idxs.sort(key=lambda i: (
                self.variants[i].qual is None,
                -(self.variants[i].qual or 0)))
        else:
            idxs.sort(key=lambda i: (self.variants[i].chrom, self.variants[i].pos))
        self.view = idxs
        self._refresh_list()

    def action_cycle_filter(self):
        i = _FILTER_CYCLE.index(self.filter_mode)
        self.filter_mode = _FILTER_CYCLE[(i + 1) % len(_FILTER_CYCLE)]
        self._apply_filter_sort()

    def action_toggle_sort(self):
        self.sort_mode = "QUAL" if self.sort_mode == "位置" else "位置"
        self._apply_filter_sort()

    def action_search(self):
        """搜索：匹配 ID 或坐标(chr:pos)，跳到第一条命中。"""
        self.notify("输入搜索词(命令行风格暂缓)", title="搜索")  # 占位——见 Step 3b
```

Step 3b：搜索实现复用 browser.py 的命令栏 Input 模式（动态 mount/unmount）。若 browser.py 用 `Input` + 回调，照搬其结构：Enter 时在 `self.view` 中查找 `v.id == q or f"{v.chrom}:{v.pos}" == q` 的第一个下标并 `ol.highlighted = view_index`，未命中 notify 提示。

- [ ] **Step 4: 运行确认通过**（`_refresh_list` 中已含 `_update_status_bar`）
- [ ] **Step 5: 提交**：`git commit -am "feat(vcf): filter cycle, qual sort and search"`

---

### Task 8: 矩阵视图 + 元数据面板 + 复制

**Files:** Modify `src/seqviz/vcf_browser.py` / `test/test_vcf_browser.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_matrix_toggle():
    app = VcfBrowser(SAMPLE_VCF)
    async with app.run_test() as pilot:
        await pilot.press("t")
        assert app.matrix_mode is True
        assert "sample1" in app._matrix_text()
        await pilot.press("t")
        assert app.matrix_mode is False


@pytest.mark.asyncio
async def test_copy_line(tmp_path, monkeypatch):
    # 复用现有剪贴板测试的 monkeypatch 方式（参考 test_browser.py）
    app = VcfBrowser(SAMPLE_VCF)
    async with app.run_test() as pilot:
        await pilot.press("y")
        copied = app._last_copied  # 实现中记录最后一次复制内容
        assert copied.startswith("chr1\t10234\trs12345")
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**

```python
    _GT_MATRIX_STYLE = {"0/0": "dim", "0/1": "yellow", "1/0": "yellow", "1/1": "bold red"}

    def _matrix_text(self) -> str:
        return str(self._build_matrix())

    def _build_matrix(self) -> Text:
        """基因型矩阵：行=当前视图前 N 条变异，列=样本。"""
        txt = Text()
        samples = self.meta.samples or ["sample1"]
        name_w = max(len(s) for s in samples) + 2
        txt.append(" " * (24 + name_w))  # 对齐表头
        for s in samples:
            txt.append(f"{s:>{name_w}}", style="bold cyan")
        txt.append("\n")
        ol = self.query_one("#variant-list", OptionList)
        cur = ol.highlighted or 0
        start = max(0, cur - 10)
        for li in range(start, min(start + 21, len(self.view))):
            v = self.variants[self.view[li]]
            load_variant_detail(self.filepath, v, self.meta.samples)
            marker = "▶ " if li == cur else "  "
            txt.append(f"{marker}{v.chrom}:{v.pos:<10}", style="bold" if li == cur else "")
            for s in samples:
                gt = parse_genotype(v.samples.get(s, "."), v.format_fields).get("GT", "./.")
                txt.append(f"{gt:>{name_w}}", style=self._GT_MATRIX_STYLE.get(gt, "dim"))
            txt.append("\n")
        return txt

    def _render_matrix(self):
        self.query_one("#detail", Static).update(self._build_matrix())

    def action_toggle_view(self):
        self.matrix_mode = not self.matrix_mode
        ol = self.query_one("#variant-list", OptionList)
        self._show_detail(ol.highlighted or 0)

    def action_file_info(self):
        txt = Text()
        txt.append("文件信息\n\n", style="bold")
        txt.append(f"格式     {self.meta.fileformat or '未知'}\n")
        txt.append(f"样本数   {len(self.meta.samples)}  ({', '.join(self.meta.samples) or '无'})\n")
        txt.append(f"变异数   {len(self.variants)}\n\n")
        txt.append("Contigs:\n", style="bold cyan")
        for cid, length in self.meta.contigs.items():
            txt.append(f"  {cid:<10}{length:,} bp\n")
        self.query_one("#detail", Static).update(txt)

    def action_copy_line(self):
        if not self.view:
            self.notify("没有可复制的变异", severity="warning")
            return
        ol = self.query_one("#variant-list", OptionList)
        v = self.variants[self.view[ol.highlighted or 0]]
        load_variant_detail(self.filepath, v, self.meta.samples)
        # 复用 browser.py 的剪贴板分层回退函数（提取为共享工具或直接复制实现）
        from seqviz.browser import _copy_to_clipboard  # 若无此导出则按 browser.py 实际函数名
        ok = _copy_to_clipboard(v.raw)
        self._last_copied = v.raw
        self.notify("已复制 VCF 行" if ok else "复制失败", severity="info" if ok else "error")
```

（剪贴板：先确认 browser.py 中现有剪贴板函数名/签名并对齐；若为方法则提取为模块级函数供两处复用。）

- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交**：`git commit -am "feat(vcf): genotype matrix view, meta panel, copy raw line"`

---

### Task 9: CLI 路由 + 文件选择器支持 .vcf

**Files:** Modify `src/seqviz/cli.py`, `src/seqviz/file_browser.py`, `config/config.json`, `src/seqviz/config.py`

- [ ] **Step 1: cli.py `_launch_browser` 增加路由**

```python
def _launch_browser(paths: list[Path]):
    # 单文件且为 .vcf → VCF 浏览器
    if len(paths) == 1 and paths[0].is_file() and paths[0].suffix.lower() == ".vcf":
        from seqviz.vcf_browser import VcfBrowser
        VcfBrowser(paths[0]).run()
        return
    # ... 其余逻辑不变
```

同时更新 `browse` 命令 help 文本为 "FASTA/FASTQ/VCF"。

- [ ] **Step 2: file_browser.py 支持 .vcf**
  - `config.py` DEFAULT_CONFIG 的 `file_browser.extensions` 追加 `".vcf"`；`config/config.json` 同步
  - file_browser 格式标记：`.vcf` 显示 `[V]`（对照现有 `[F]/[Q]` 判定函数扩展）
  - 打开选中文件时：若唯一选中为 `.vcf` → 启动 VcfBrowser（对照现有打开路径的实现方式接入）

- [ ] **Step 3: 测试**：`test_cli.py` 增加路由测试（用 CliRunner 无法跑 TUI，则直接断言 `_launch_browser` 分支逻辑——可提取 `_is_vcf(path)` 辅助函数并单测）
- [ ] **Step 4: 全量运行**：`uv run pytest test/ -x -q` → 全部通过
- [ ] **Step 5: 提交**：`git commit -am "feat(cli): route .vcf to VcfBrowser and support in file selector"`

---

### Task 10: README + 实测 + 收尾

**Files:** Modify `README.md`

- [ ] **Step 1: README 增加 VCF 章节**（功能特性列表加 `🧪 VCF 变异浏览`，命令一览 `seqviz browse x.vcf`，快捷键表格，版本号不变——发布时再 bump）
- [ ] **Step 2: 实测**：`uv run seqviz browse test/sample.vcf`，人工验证：列表着色、j/k 导航、f 过滤、s 排序、t 矩阵、i 信息、y 复制、q 退出
- [ ] **Step 3: 全量回归**：`uv run pytest test/ -v` → 全部通过
- [ ] **Step 4: 提交**：`git commit -am "docs: VCF browsing section in README"`

---

## Self-Review

- **Spec 覆盖**：布局(Task 6) / 交互(Task 6-8) / 懒扫描(Task 3) / 统计(Task 4) / 错误处理(Task 3 畸形行、空文件) / 主题(Task 5) / 路由(Task 9) ✓。染色体密度图与 bgzip 明确不做（spec YAGNI）✓
- **类型一致性**：`scan_vcf` 返回三元组 `(meta, variants, skipped)` 各任务一致；`load_variant_detail(path, variant, sample_names)` 签名一致；`Variant.info` 索引阶段已填充（Task 3 split("\t",8) 含第 8 列）与 Task 4 stats 依赖一致 ✓
- **已知待执行时确认点**：剪贴板函数在 browser.py 的实际导出名；CSS 接入方式（类变量 vs 其他）；async 测试基建（对齐 test_browser.py）——已在对应 Task 内注明对齐方式
