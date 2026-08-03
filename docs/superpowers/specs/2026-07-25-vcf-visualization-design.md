# VCF 可视化设计文档

日期：2026-07-25 · 分支：`vcf` · 状态：已确认

## 概述

为 seqviz 增加 VCF（Variant Call Format）格式的终端可视化支持。采用独立 App 架构（方案 B）：
新建 `vcf.py` 解析器 + `vcf_browser.py` Textual App，复用主题/配置/剪贴板基础设施，
`seqviz browse` 按后缀自动路由。仅支持未压缩纯文本 `.vcf`（v0.6.x 阶段不做 bgzip/tabix）。

## 需求确认结果

- **使用场景**：小文件逐条浏览 + 大文件探索两者兼顾（懒扫描索引 + 虚拟化列表混合策略）
- **压缩支持**：仅纯文本 VCF（复用 FASTA P0 懒扫描架构）
- **多样本**：逐样本基因型展示（GT/AD/DP 详情 + 比例条）

## 可视化布局（已确认）

双栏布局：

- **左栏（变异列表）**：一行一变异，`类型符号 + chr:pos + ID + REF→ALT摘要 + QUAL`
  - 类型符号：SNP `●`、插入/缺失 `◆`
  - 行颜色编码可信度：PASS→绿 / LowQual 或 QUAL<20→黄红系 / LowDP→红
- **右栏（变异详情）**三段式：
  1. 位点基本信息（坐标、ID、变异类型中文名、QUAL、FILTER）
  2. INFO 注释逐行展开（DP/AF/MQ/DB 等，按 `##INFO` 定义显示 Description）
  3. 逐样本基因型：GT 中文解读（纯合参考/杂合/纯合变异）+ DP/GQ + AD reads 比例条
- `t` 切换基因型矩阵视图：行=变异、列=样本，GT 着色（0/0 暗灰、0/1 黄、1/1 亮红）
- `i` 打开文件信息面板（`##` 元数据：contig 长度、INFO/FORMAT 字段定义）
- 底部状态栏常驻统计：变异总数、SNP/InDel 计数、Ts/Tv、PASS 数、AF 均值、当前过滤/排序

## 交互设计（已确认）

| 按键 | 功能 |
|------|------|
| `j`/`k`、`n`/`p` | 上下移动变异列表 |
| `Space`/`b`、`g`/`G` | 翻页、首/末条 |
| `/` | 搜索（ID 或坐标 `chr1:10234`） |
| `f` | 过滤循环：全部 → PASS → SNP → InDel → 全部 |
| `s` | 排序切换：位置 ↔ QUAL 降序 |
| `t` | 详情视图 ↔ 基因型矩阵视图 |
| `i` | 文件元数据面板 |
| `y` | 复制当前变异完整 VCF 行 |
| `?` / `q` | 帮助 / 退出 |

明确不做（YAGNI）：染色体密度图、bgzip/tabix、多文件标签页（VCF 单文件打开）。

## 实现架构

### 新文件

**`src/seqviz/vcf.py`** — 纯解析层（无 UI 依赖，可独立测试）

```python
class VariantType(Enum):
    TRANSITION    # 转换 SNP: A↔G, C↔T
    TRANSVERSION  # 颠换 SNP
    INSERTION     # len(ALT) > len(REF)
    DELETION      # len(REF) > len(ALT)
    COMPLEX       # 其余

@dataclass
class Variant:
    chrom: str
    pos: int
    id: str          # "." → ""
    ref: str
    alt: str
    qual: float | None   # "." → None
    filter: str
    info: dict[str, str]       # 懒扫描时为空 dict，按需解析填充
    format_fields: list[str]   # 同上
    samples: dict[str, str]    # 同上；样本名 → 原始 "0/1:15:99:10,5"
    offset: int      # 行首字节偏移（f.tell），支持 seek 回读完整行
    raw: str         # 原始行；懒扫描时为空，回读后填充，y 键复制用

@dataclass
class VcfMeta:
    fileformat: str
    contigs: dict[str, int]        # ID → length
    info_defs: dict[str, str]      # ID → Description
    format_defs: dict[str, str]
    filter_defs: dict[str, str]
    samples: list[str]

def parse_meta(lines) -> VcfMeta            # 解析 ## 头
def scan_vcf(path) -> tuple[VcfMeta, list[Variant]]
    # 懒扫描：每行只取前 8 列 + 字节 offset，INFO/FORMAT/样本列不解析
    # 复用 FASTA P0 模式（逐行 readline，记录 offset）
def load_variant_detail(path, variant) -> Variant
    # seek(offset) 回读完整行，填充 info/format/samples/raw
def parse_variant_line(line) -> Variant     # 按需完整解析单行
def classify_variant(ref, alt) -> VariantType
def parse_genotype(sample_str, format_fields) -> dict
    # → {"GT": "0/1", "DP": 15, "AD": [10, 5], ...}
def compute_stats(variants) -> dict
    # → total / snp / indel / ts_tv / pass_count / mean_af
```

**`src/seqviz/vcf_browser.py`** — Textual App（`VcfBrowser`）

- 结构镜像 `browser.py`：Header + 左 OptionList（虚拟化）+ 右 Static 详情 + Footer
- CSS 用 `theme.build_vcf_browser_css(theme)`（theme.py 新增该函数，复用现有样式骨架）
- 大文件策略：启动懒扫描全量索引（只 8 列，1.3G 级预计 <2s），列表虚拟化渲染
- 过滤/排序在内存索引列表上操作（保存过滤后下标映射）
- 剪贴板复用现有分层回退策略（browser.py 中的工具函数提取或复制）

### 修改文件

- **`src/seqviz/cli.py`**：`browse` 命令按后缀路由，`.vcf` → `VcfBrowser`
- **`src/seqviz/file_browser.py`**：`EXTENSIONS` 增加 `.vcf`，格式标记显示 `[V]`，打开时路由
- **`src/seqviz/theme.py`**：新增 `build_vcf_browser_css()`
- **`README.md`**：新增 VCF 章节

### 数据流

```
seqviz browse x.vcf → cli 路由 → VcfBrowser.__init__
  → scan_vcf()（懒扫描索引，只前 8 列）→ OptionList 虚拟化列表
  → 选中行 → load_variant_detail()（seek 回读完整行）→ 右栏渲染详情
  → t 切换 → 批量 load_variant_detail 当前窗口变异 → 基因型矩阵
```

## 错误处理

- 无 `#CHROM` 表头行 / 空文件：CLI 友好报错，非零退出（对齐现有空文件策略）
- 列数不足的数据行：跳过并计数，状态栏提示 `跳过 N 行畸形数据`
- QUAL 为 `.` 或非数字：`None`，排序时排最后，显示 `-`
- 非 UTF-8 行：宽容解码（`errors="replace"`），对齐 v0.6.3 策略

## 测试计划

- `test/test_vcf.py`：
  - 解析器：parse_meta / scan_vcf / parse_variant_line / classify_variant（转换颠换判定）/ parse_genotype / compute_stats（Ts/Tv 计算）
  - 畸形输入：空文件、无表头、列缺失、QUAL=`.`、非 UTF-8
- `test/test_vcf_browser.py`：App 启动、列表渲染、过滤循环、排序切换、矩阵视图、y 复制
- `test/test_cli.py`：`browse x.vcf` 路由
- 全量回归：现有 210 项测试保持通过
- 实测：`test/sample.vcf`

## 假设

- 单样本到 ~50 样本的 VCF（矩阵视图在列数超宽时横向滚动或截断，不做复杂折叠）
- ALT 多等位（`A,G`）按第一个 ALT 分类，详情显示完整 ALT
