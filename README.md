# Seqviz

**生物序列数据终端可视化工具 —— 做序列界的 `bat`**

> **v0.4.0 试用版** · 原名 `fasta-fmt`，现已更名为 `seqviz`

在终端中以彩色、交互的方式查看 FASTA / FASTQ 序列文件。支持 DNA 碱基着色、蛋白质氨基酸着色、质量值梯度显示、统计摘要、交互式 TUI 浏览器与目录文件选择器。白底黑字的默认主题让序列着色一目了然。

---

## 目录

- [功能特性](#功能特性)
- [安装](#安装)
- [快速开始](#快速开始)
- [命令参考](#命令参考)
- [交互式浏览器](#交互式浏览器)
- [文件选择器](#文件选择器)
- [配置指南](#配置指南)
- [主题定制](#主题定制)
- [配色方案](#配色方案)
- [性能表现](#性能表现)
- [常见问题](#常见问题)
- [开发指南](#开发指南)
- [项目结构](#项目结构)
- [Roadmap](#roadmap)

---

## 功能特性

| 功能 | 说明 |
|------|------|
| 彩色序列查看 | DNA 碱基四色着色 (A/T/C/G)，蛋白质按化学性质分组着色 |
| 序列类型自动检测 | 自动识别 DNA / 蛋白质序列并切换配色 |
| FASTQ 支持 | 质量值 Phred 梯度着色、质量分布条、序列与质量值对齐 |
| 统计摘要 | 序列条数、总长度、N50、GC 含量，表格化输出 |
| 交互式浏览器 | 基于 Textual 的 TUI，搜索、跳转、复制、范围选择、导出、多标签页 |
| 目录文件选择器 | 扫描目录中的序列文件，预览、多选批量打开，`B` 键返回 |
| 可定制主题 | `theme.json` 控制界面配色（默认白底黑字 + 浅灰分隔线） |
| 可定制行为 | `config.json` 控制换行宽度、滚动步长、序列配色等 |
| gzip 支持 | 直接读取 `.gz` 压缩文件 |
| 流式解析 | 生成器逐条读取，大文件不占满内存 |
| 管道友好 | 非 TTY 环境自动关闭颜色输出 |

---

## 安装

### 从源码安装（推荐）

```bash
git clone https://github.com/Georicl/seqviz.git
cd seqviz
uv sync                 # 安装依赖
uv tool install .       # 安装为全局命令
```

### 开发模式

```bash
uv pip install -e .
# 或直接用 uv run 运行
uv run seqviz --help
```

> 需要 Python >= 3.14 和 [uv](https://github.com/astral-sh/uv)。

---

## 快速开始

```bash
# 1. 在任意序列文件目录下，直接运行（打开文件选择器）
cd your_sequences/
seqviz

# 2. 查看单个 FASTA 文件
seqviz view genome.fasta

# 3. 查看统计信息
seqviz stats genome.fasta

# 4. 查看 FASTQ 测序文件（含质量值）
seqviz fqview reads.fastq

# 5. 交互式浏览（TUI）
seqviz browse genome.fasta
```

---

## 命令参考

### `seqviz`（无参数）

打开**当前目录**的文件选择器。

### `seqviz view <file>`

彩色查看 FASTA 文件，每条序列显示类型标签、长度、位置标尺和着色序列。

```bash
seqviz view genome.fasta
seqviz view proteins.faa --wrap 80    # 自定义每行宽度
```

| 选项 | 说明 | 默认 |
|------|------|------|
| `--wrap N` | 每行碱基数 | 60 |

### `seqviz head <file>`

查看前 N 条序列。

```bash
seqviz head genome.fasta -n 5
```

### `seqviz stats <file>`

输出统计摘要表格：序列条数、总长度、最短/最长/平均长度、N50、GC 含量。

```bash
seqviz stats genome.fasta
```

### `seqviz fqview <file>`

彩色查看 FASTQ 文件：序列 + 质量值上下对齐着色，每条 read 显示平均质量、Q30 占比和质量分布条。

```bash
seqviz fqview reads.fastq
seqviz fqview reads.fastq -n 10       # 只看前 10 条
```

### `seqviz browse <path> [...]`

交互式 TUI 浏览器。

- 传入**目录** → 打开文件选择器
- 传入**文件** → 直接打开（多个文件则以标签页展示）

```bash
seqviz browse ./sequences/                          # 目录 → 文件选择器
seqviz browse genome.fasta                          # 单文件
seqviz browse genome.fasta proteins.faa reads.fastq # 多文件标签页
```

### `seqviz config [--init]`

查看当前生效的配置与主题；`--init` 生成配置文件模板。

```bash
seqviz config --init    # 生成 ~/.config/seqviz/config.json 和 theme.json
seqviz config           # 查看当前生效配置
```

---

## 交互式浏览器

```bash
seqviz browse genome.fasta
```

左右双栏布局：**左侧序列列表**（虚拟化，支持十万级序列）+ **右侧序列详情**（按需渲染，含统计信息、位置编号、着色序列）。

### 快捷键

| 按键 | 功能 |
|------|------|
| `j` / `k` | 上下滚动 |
| `Space` / `b` | 向下翻页 / 向上翻页 |
| `g` / `G` | 跳到顶部 / 底部 |
| `n` / `p` | 下一条 / 上一条序列 |
| `/` | 搜索序列名称（模糊匹配，循环搜索） |
| `:` | 跳转到第 N 条序列 |
| `y` | 复制当前序列到系统剪贴板 |
| `c` | 范围复制（输入位置如 `100-200`） |
| `e` | 导出当前序列到文件 |
| `B` | 返回文件选择器（从目录打开时可用） |
| `Tab` | 切换文件标签页（多文件模式） |
| `?` | 显示帮助面板 |
| `q` | 退出 |

### 搜索与跳转

- 按 `/` 打开搜索框，输入关键词模糊匹配序列名（大小写不敏感），回车跳转到匹配项。
- 按 `:` 打开跳转框，输入序列编号（1-based），回车直接定位。
- 按 `Esc` 关闭输入框。

### 复制与导出

- `y`：将当前序列（含 header）复制到系统剪贴板，可直接粘贴。
- `c`：范围复制，输入如 `100-200` 复制第 100~200 位碱基。
- `e`：将当前序列导出为 `.fasta` / `.fastq` 文件（保存到当前目录）。

---

## 文件选择器

当 `browse` 传入目录（或直接运行 `seqviz`）时启动。

- 自动扫描目录下的序列文件：`.fa .fasta .fna .faa .aa .seq .fq .fastq` 及对应 `.gz`。
- 左侧文件列表（名称 + 大小 + 格式标记 `[F]`/`[Q]`），右侧实时预览（名称、路径、大小、格式、序列数）。

### 快捷键

| 按键 | 功能 |
|------|------|
| `j` / `k` | 上下移动 |
| `Space` | 切换多选 |
| `a` | 全选 / 取消全选 |
| `Enter` | 打开（有多选则批量打开为标签页） |
| `q` | 取消退出 |

在序列浏览器中按 `B` 可返回文件选择器重新选择。

---

## 配置指南

seqviz 通过 `~/.config/seqviz/config.json` 自定义行为。不存在时使用内置默认值。

### 生成配置模板

```bash
seqviz config --init
```

### 配置项说明

```json
{
  "browser": {
    "wrap_width": 60,           // 每行碱基数
    "scroll_step": 5,           // j/k 每次滚动行数
    "sidebar_width": 32,        // 侧栏宽度
    "show_line_numbers": true,  // 是否显示位置编号
    "show_quality": true        // FASTQ 是否显示质量值行
  },
  "colors": {
    "dna": {                    // DNA 碱基配色
      "A": "green", "T": "red", "C": "blue", "G": "yellow", "N": "dim"
    },
    "quality_thresholds": {     // 质量值着色阈值
      "high": 30, "medium": 20, "low": 10
    }
  },
  "file_browser": {
    "extensions": [".fa", ".fasta", ".fna", ".faa", ".aa", ".seq", ".fq", ".fastq"]
  }
}
```

**只需写入想覆盖的字段**，其余自动保持默认（深度合并）。例如只改换行宽度：

```json
{ "browser": { "wrap_width": 100 } }
```

---

## 主题定制

seqviz 通过 `~/.config/seqviz/theme.json` 自定义界面配色。默认采用**白底黑字 + 浅灰分隔线**，让序列着色更清晰。

### 主题项说明

```json
{
  "background": "#ffffff",   // 全局背景（白）
  "foreground": "#1a1a1a",   // 普通文字（近黑）
  "border": "#d8d8d8",       // 区域分隔线（浅灰）
  "accent": "#0066cc",       // 强调色（焦点边框）
  "panel": "#f4f4f4",        // 面板背景（状态栏/命令栏）
  "muted": "#8a8a8a",        // 弱化文字
  "highlight": "#e8f0fb"     // 选中高亮
}
```

### 示例：深色主题

```json
{
  "background": "#1e1e1e",
  "foreground": "#e0e0e0",
  "border": "#3a3a3a",
  "panel": "#2a2a2a"
}
```

> 修改配置或主题后需重新启动 seqviz 生效。

---

## 配色方案

### DNA 碱基

```
A (Adenine)  → 绿色    T (Thymine)  → 红色
C (Cytosine) → 蓝色    G (Guanine)  → 黄色
N (Unknown)  → 灰色
```

### 蛋白质氨基酸（按化学性质）

```
疏水性 (AVILMFYW) → 绿色系    亲水性 (STNQ) → 蓝色系
碱性   (RKH)      → 红色系    酸性   (DE)   → 紫色系
特殊   (GPC)      → 灰色系
```

### 质量值（Phred）

```
Q >= 30 → 绿色（高质量）    Q >= 20 → 黄色（中等）
Q >= 10 → 橙色（低）        Q <  10 → 红色（极低）
```

---

## 性能表现

基于大文件实测（Apple Silicon）：

| 操作 | 数据规模 | 耗时 |
|------|---------|------|
| 扫描索引 | 10,000 条序列 (25MB) | ~7 ms |
| 扫描索引 | 50,000 reads (30MB) | ~46 ms |
| 扫描索引 | 5 × 1M bp 超长序列 (24MB) | ~9 ms |
| 加载序列 | 1M bp 单条（seek 定位） | ~7 ms |
| 滚动 | 超长序列浏览 | ~3.8 ms/次 |

**性能设计：**

- **O(1) 序列定位** —— 启动时预建文件索引（记录每条序列的字节偏移），浏览任意序列用 `seek` 直接跳转，无需重扫文件。
- **虚拟化列表** —— 侧栏基于 OptionList，十万条序列只渲染可见项。
- **按需渲染** —— 序列行懒加载，只生成当前屏幕可见的行；到达边界不重复重绘。

---

## 常见问题

**Q: 修改配置后没生效？**
A: 配置在启动时加载，修改 `config.json` / `theme.json` 后需重新运行 seqviz。

**Q: 如何恢复默认配置？**
A: 删除 `~/.config/seqviz/config.json` 和 `theme.json` 即可，seqviz 会自动使用内置默认值。

**Q: 支持哪些文件格式？**
A: FASTA（`.fa .fasta .fna .faa .aa .seq`）和 FASTQ（`.fq .fastq`），均支持 `.gz` 压缩版本。

**Q: 文件很大，打开会卡吗？**
A: 不会。seqviz 使用流式解析 + 偏移索引 + 按需渲染，GB 级文件也能流畅浏览。

**Q: 如何只复制序列的一部分？**
A: 在浏览器中按 `c`，输入位置范围（如 `100-200`）即可复制对应片段。

---

## 开发指南

```bash
git clone https://github.com/Georicl/seqviz.git
cd seqviz
uv sync                     # 安装依赖（含开发依赖）

uv run seqviz view test/test.fa   # 运行
uv run pytest test/               # 运行全部测试（147 个）

seqviz --install-completion zsh   # 安装 shell 补全
```

### 运行测试

```bash
uv run pytest test/ -v            # 详细输出
uv run pytest test/test_performance.py -v   # 仅性能测试
```

---

## 项目结构

```
seqviz/
├── src/seqviz/
│   ├── cli.py            # CLI 入口 (Typer)
│   ├── parsers.py        # FASTA 流式解析器
│   ├── fastq.py          # FASTQ 流式解析器
│   ├── seq_type.py       # 序列类型自动检测 (DNA/蛋白质)
│   ├── renderer.py       # 序列/质量值着色渲染
│   ├── stats.py          # 统计计算 (N50, GC%)
│   ├── browser.py        # TUI 交互式浏览器 (Textual)
│   ├── file_browser.py   # 目录文件选择器
│   ├── config.py         # 行为配置系统 (config.json)
│   └── theme.py          # 主题系统 (theme.json)
├── config/
│   ├── config.json       # 默认配置模板
│   └── theme.json        # 默认主题模板
├── test/                 # 测试套件 (147 个测试)
└── pyproject.toml
```

---

## Roadmap

- [x] **v0.1.0** —— MVP：view / stats / head / fqview / browse
- [x] **v0.2.0** —— 目录文件选择器、多文件标签页、范围复制、默认命令
- [x] **v0.3.0** —— JSON 配置系统、渲染性能优化、更名为 seqviz
- [x] **v0.4.0** —— 白底黑字主题 (theme.json)、返回文件选择器 (B 键)、应用名 Seqviz、完整测试套件
- [ ] **v0.5.0** —— VCF 可视化、序列筛选 (`--min-len` / `--min-gc` / `--grep`)
- [ ] **v0.6.0** —— 多格式支持 (GFF/BED)、格式互转
- [ ] **v1.0.0** —— PyPI 发布、完整测试覆盖、CI

---

## License

MIT
