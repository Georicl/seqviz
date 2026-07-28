
# seqviz 开发计划

> 生物序列数据终端可视化工具 —— 做序列界的 `bat`
>
> 原名 `fasta-fmt`，已更名为 `seqviz`（涵盖 FASTA/FASTQ/VCF 等序列数据可视化）。以下为初始规划文档，包名/命令请以 `seqviz` 为准。

---

## 项目结构

```
fasta-fmt/
├── src/
│   └── fasta_fmt/
│       ├── __init__.py
│       ├── cli.py              # CLI 入口 (Typer)
│       ├── parsers/            # 格式解析器
│       │   ├── __init__.py
│       │   ├── base.py         # 解析器基类
│       │   ├── fasta.py        # FASTA 解析
│       │   ├── fastq.py        # FASTQ 解析
│       │   ├── gff.py          # GFF/GFF3 解析
│       │   └── bed.py          # BED 解析
│       ├── renderers/          # 渲染引擎
│       │   ├── __init__.py
│       │   ├── sequence.py     # 序列着色渲染
│       │   ├── quality.py      # 质量值可视化
│       │   └── table.py        # 表格/统计渲染
│       ├── stats/              # 统计计算
│       │   ├── __init__.py
│       │   └── calculator.py   # N50, GC%, 长度分布等
│       ├── filters/            # 序列筛选
│       │   ├── __init__.py
│       │   └── sequence.py     # 按长度/GC/名称筛选
│       └── themes/             # 配色主题
│           ├── __init__.py
│           └── default.py      # 默认碱基配色
├── tests/
│   ├── test_parsers.py
│   ├── test_renderers.py
│   └── test_stats.py
├── pyproject.toml
├── README.md
└── TODO.md
```

---

## 开发阶段

### Phase 1: MVP (第1周)

- [ ] **1.1 项目基础配置**
  - [ ] 配置 pyproject.toml (依赖: rich, typer)
  - [ ] 配置 uv 开发环境
  - [ ] 设置 CLI 入口点 `fasta-fmt`

- [ ] **1.2 FASTA 解析器**
  - [ ] 实现流式 FASTA 解析 (支持大文件, 不全部加载)
  - [ ] 支持 gzip 压缩文件 (.fa.gz)
  - [ ] 解析 header (ID, description)
  - [ ] 解析 sequence

- [ ] **1.3 序列着色渲染**
  - [ ] DNA 碱基着色: A(绿) T(红) C(蓝) G(黄)
  - [ ] 蛋白质氨基酸着色 (按化学性质分组)
  - [ ] 使用 Rich 库实现终端彩色输出
  - [ ] 支持管道输出 (检测是否为 TTY)

- [ ] **1.4 基础 CLI 命令**
  - [ ] `fasta-fmt view <file>` - 美化查看
  - [ ] `fasta-fmt stats <file>` - 统计摘要
  - [ ] `fasta-fmt head <file> -n 10` - 查看前N条序列

### Phase 2: 核心功能 (第2周)

- [ ] **2.1 FASTQ 支持**
  - [ ] FASTQ 格式解析
  - [ ] 质量值着色 (Phred score 梯度色)
  - [ ] 质量值分布图 (终端内 ASCII 图)

- [ ] **2.2 统计功能增强**
  - [ ] N50 / N90 / L50 计算
  - [ ] GC 含量统计
  - [ ] 序列长度分布 (min/max/mean/median)
  - [ ] 多文件批量统计
  - [ ] 表格化输出 (Rich Table)

- [ ] **2.3 序列筛选**
  - [ ] `--min-len` / `--max-len` 按长度筛选
  - [ ] `--min-gc` / `--max-gc` 按 GC 含量筛选
  - [ ] `--grep` 按名称/描述模糊搜索
  - [ ] `--regex` 按序列 motif 正则筛选

### Phase 3: 进阶功能 (第3-4周)

- [ ] **3.1 多格式支持**
  - [ ] GFF/GFF3 解析与美化
  - [ ] BED 格式支持
  - [ ] 格式互转: `fasta-fmt convert input.gff --to bed`

- [ ] **3.2 交互式浏览 (可选)**
  - [ ] 大文件索引 (记录每条序列的偏移量)
  - [ ] 交互式翻页浏览
  - [ ] 序列搜索跳转

- [ ] **3.3 输出增强**
  - [ ] `--format markdown` 输出 Markdown 表格
  - [ ] `--format html` 生成 HTML 报告
  - [ ] `--no-color` 纯文本输出 (管道友好)
  - [ ] `--wrap N` 序列换行宽度

### Phase 4: 发布 (第4周)

- [ ] **4.1 文档与测试**
  - [ ] 完善 README (含 GIF 演示)
  - [ ] 单元测试覆盖率 > 80%
  - [ ] 添加示例数据

- [ ] **4.2 发布配置**
  - [ ] PyPI 发布配置
  - [ ] GitHub Actions CI
  - [ ] LICENSE (MIT)

---

## 技术栈

| 组件 | 选择 | 用途 |
|------|------|------|
| CLI 框架 | Typer | 命令行参数解析 |
| 终端渲染 | Rich | 彩色输出、表格、面板 |
| 包管理 | uv | 依赖管理 |
| 测试 | pytest | 单元测试 |
| Python | >= 3.14 | 运行时 |

---

## CLI 命令设计

```bash
# 查看序列 (碱基着色)
fasta-fmt view genome.fasta
fasta-fmt view reads.fastq --quality    # 显示质量值着色

# 统计信息
fasta-fmt stats genome.fasta
fasta-fmt stats *.fasta --format table  # 多文件表格对比

# 查看前N条
fasta-fmt head genome.fasta -n 5

# 筛选
fasta-fmt view genome.fasta --min-len 1000 --max-len 50000
fasta-fmt view genome.fasta --grep "mitochondria"
fasta-fmt view genome.fasta --min-gc 0.4

# 格式转换
fasta-fmt convert annotation.gff3 --to bed
fasta-fmt convert genes.fasta --to fastq --dummy-quality 30

# 序列提取
fasta-fmt extract genome.fasta --id "chr1" --start 1000 --end 2000
```

---

## 碱基配色方案

```
DNA:
  A (Adenine)  → 绿色 (green)
  T (Thymine)  → 红色 (red)
  C (Cytosine) → 蓝色 (blue)
  G (Guanine)  → 黄色 (yellow)
  N (Unknown)  → 灰色 (dim)

Protein (按化学性质):
  疏水性 (AVILMFYW) → 绿色系
  亲水性 (STNQ)     → 蓝色系
  碱性 (RKH)        → 红色系
  酸性 (DE)         → 紫色系
  特殊 (GPC)        → 灰色系

Quality (Phred):
  Q >= 30  → 绿色 (高质量)
  Q >= 20  → 黄色 (中等)
  Q >= 10  → 橙色 (低)
  Q < 10   → 红色 (极低)
```

---

## 性能目标

- 1GB FASTA 文件: `view` 首屏输出 < 100ms (流式)
- 100MB FASTQ 文件: `stats` 完成 < 5s
- 内存占用: 不超过文件大小 (流式处理)

---

## 里程碑

| 版本 | 内容 | 预计时间 |
|------|------|----------|
| v0.1.0 | MVP: view + stats + 碱基着色 | 第1周 |
| v0.2.0 | FASTQ + 筛选 + 多文件统计 | 第2周 |
| v0.3.0 | 多格式 + 转换 + HTML报告 | 第3-4周 |
| v1.0.0 | 稳定版 + 完整文档 + PyPI | 第4周 |
```

---

