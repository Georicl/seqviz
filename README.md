# seqviz

**生物序列数据终端可视化工具 -- 做序列界的 `bat`**

在终端中彩色查看 FASTA/FASTQ 文件，支持 DNA 碱基着色、蛋白质氨基酸着色、质量值梯度显示、统计摘要、交互式 TUI 浏览器、目录文件选择器。

> 原名 `fasta-fmt`，现已更名为 `seqviz`，以涵盖更广的序列数据可视化场景（VCF 支持规划中）。

---

## 功能特性

- **彩色序列查看** -- DNA 碱基着色 (A/T/C/G 四色)，蛋白质按化学性质分组着色
- **序列类型自动检测** -- 自动识别 DNA / 蛋白质序列，切换对应配色方案
- **FASTQ 支持** -- 质量值 Phred 梯度着色，质量分布条，序列与质量值对齐显示
- **统计摘要** -- 序列条数、总长度、N50、GC 含量，Rich 表格输出
- **交互式浏览器** -- 基于 Textual 的 TUI，支持搜索、跳转、复制、范围选择、导出、多文件标签页
- **目录文件选择器** -- 传入目录自动扫描序列文件，支持预览与多选批量打开，`B` 键可从浏览器返回选择器
- **可定制主题** -- `theme.json` 控制界面配色（默认白底黑字 + 浅灰分隔线，让序列着色更清晰）
- **gzip 支持** -- 直接读取 `.gz` 压缩文件
- **管道友好** -- 非 TTY 环境自动关闭颜色输出
- **流式解析** -- 生成器逐条读取，GB 级文件不占满内存

---

## 安装

```bash
# 从源码安装 (需要 uv)
git clone https://github.com/Georicl/seqviz.git
cd seqviz
uv sync
uv tool install .

# 或开发模式
uv pip install -e .
```

---

## 快速开始

```bash
# 直接打开当前目录的文件浏览器 (默认行为)
seqviz

# 打开指定目录 (文件选择器)
seqviz browse ./sequences/

# 彩色查看 FASTA 文件
seqviz view genome.fasta

# 查看前 5 条序列
seqviz head genome.fasta -n 5

# 统计摘要
seqviz stats genome.fasta

# 查看 FASTQ 文件 (序列 + 质量值着色)
seqviz fqview reads.fastq

# 交互式浏览 (TUI)
seqviz browse genome.fasta

# 多文件标签页浏览
seqviz browse genome.fasta proteins.faa reads.fastq
```

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `seqviz` | 默认打开当前目录的文件浏览器 |
| `view <file>` | 美化查看 FASTA 文件 (碱基/氨基酸着色 + 位置标尺) |
| `head <file> [-n N]` | 查看前 N 条序列 |
| `stats <file>` | 统计摘要 (条数、长度、N50、GC%) |
| `fqview <file> [-n N]` | 美化查看 FASTQ 文件 (序列 + 质量值对齐着色) |
| `browse <path> [...]` | 交互式 TUI 浏览器 (目录 → 文件选择器，文件 → 多标签页) |
| `config [--init]` | 查看当前生效配置与主题 (--init 生成 config.json + theme.json 模板) |

---

## 配置与主题

seqviz 支持通过两个 JSON 文件自定义：**config.json**（行为/序列配色/文件后缀）和 **theme.json**（界面主题）。

```bash
# 生成默认配置文件模板 (config.json + theme.json)
seqviz config --init

# 查看当前生效配置与主题
seqviz config
```

文件位置：`~/.config/seqviz/config.json` 和 `~/.config/seqviz/theme.json`（不存在时使用内置默认值）。

仓库内置了默认模板 [`config/config.json`](config/config.json) 和 [`config/theme.json`](config/theme.json)，可直接复制后修改：

```bash
mkdir -p ~/.config/seqviz
cp config/config.json config/theme.json ~/.config/seqviz/
```

### config.json（行为与序列配色）

```json
{
  "browser": {
    "wrap_width": 60,           // 每行碱基数
    "scroll_step": 5,           // j/k 每次滚动行数
    "sidebar_width": 45,        // 侧栏宽度
    "show_line_numbers": true,  // 显示位置编号
    "show_quality": true        // FASTQ 显示质量值行
  },
  "colors": {
    "dna": {"A": "green", "T": "red", "C": "blue", "G": "yellow", "N": "dim"},
    "quality_thresholds": {"high": 30, "medium": 20, "low": 10}
  },
  "file_browser": {
    "extensions": [".fa", ".fasta", ".fna", ".faa", ".aa", ".seq", ".fq", ".fastq"]
  }
}
```

### theme.json（界面主题）

默认采用白底黑字 + 浅灰分隔线，让序列着色更清晰：

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

只需写入想覆盖的字段，其余保持默认（深度合并）。

---

## 交互式浏览器

```bash
seqviz browse genome.fasta
```

左右双栏布局：左侧序列列表 (虚拟化，支持十万级序列)，右侧序列详情 (按需渲染)。

### 快捷键

| 按键 | 功能 |
|------|------|
| `j` / `k` | 上下滚动 |
| `n` / `p` | 下一条 / 上一条序列 |
| `Space` / `b` | 向下翻页 / 向上翻页 |
| `g` / `G` | 跳到顶部 / 底部 |
| `/` | 搜索序列名称 (模糊匹配，循环搜索) |
| `:` | 跳转到第 N 条序列 |
| `y` | 复制当前序列到系统剪贴板 |
| `c` | 范围复制 (输入位置如 `100-200`) |
| `e` | 导出当前序列到文件 |
| `B` | 返回文件选择器 (从目录打开时可用) |
| `?` | 显示帮助面板 |
| `Tab` | 切换文件标签页 (多文件模式) |
| `q` | 退出 |

### 文件选择器

传入目录时启动，自动扫描 `.fa .fasta .fna .faa .aa .seq .fq .fastq` 及对应 `.gz` 文件。

| 按键 | 功能 |
|------|------|
| `j` / `k` | 上下移动 |
| `Space` | 切换多选 |
| `a` | 全选 / 取消全选 |
| `Enter` | 打开 (有多选则批量打开) |
| `q` | 取消 |

### 性能设计

- **O(1) 序列定位** -- 预建文件索引，用 `seek` 直接跳转，不重扫文件
- **虚拟化列表** -- 侧栏基于 OptionList，十万条序列只渲染可见项
- **按需渲染** -- 序列行懒加载，只生成当前屏幕可见的行

---

## 配色方案

```
DNA:
  A (Adenine)  -> 绿色    T (Thymine)  -> 红色
  C (Cytosine) -> 蓝色    G (Guanine)  -> 黄色
  N (Unknown)  -> 灰色

Protein (按化学性质):
  疏水性 (AVILMFYW) -> 绿色系    亲水性 (STNQ) -> 蓝色系
  碱性 (RKH)        -> 红色系    酸性 (DE)     -> 紫色系
  特殊 (GPC)        -> 灰色系

Quality (Phred):
  Q >= 30 -> 绿色 (高质量)    Q >= 20 -> 黄色 (中等)
  Q >= 10 -> 橙色 (低)        Q <  10 -> 红色 (极低)
```

---

## 技术栈

| 组件 | 用途 |
|------|------|
| Python >= 3.14 | 运行时 |
| Typer | CLI 框架 |
| Rich | 终端彩色渲染 |
| Textual | TUI 交互式界面 |
| uv | 包管理 |
| pytest | 测试 |

---

## 开发

```bash
# 克隆项目
git clone https://github.com/Georicl/seqviz.git
cd seqviz

# 安装依赖
uv sync

# 运行
uv run seqviz view test/test.fa

# 测试
uv run pytest

# Shell 补全 (zsh)
seqviz --install-completion zsh
```

---

## 项目结构

```
src/seqviz/
  __init__.py
  cli.py            # CLI 入口 (Typer)
  parsers.py        # FASTA 流式解析器
  fastq.py          # FASTQ 流式解析器
  renderer.py       # 序列/质量值着色渲染
  seq_type.py       # 序列类型自动检测
  stats.py          # 统计计算 (N50, GC%)
  browser.py        # TUI 交互式浏览器 (Textual)
  file_browser.py   # 目录文件选择器
  config.py         # JSON 配置系统 (config.json)
  theme.py          # 主题系统 (theme.json)
```

---

## Roadmap

- [x] v0.1.0 -- MVP: view / stats / head / fqview / browse
- [x] v0.2.0 -- 目录文件选择器、多文件标签页、范围复制、默认命令
- [x] v0.3.0 -- JSON 配置系统、渲染性能优化、更名为 seqviz
- [x] v0.4.0 -- 白底黑字主题 (theme.json)、返回文件选择器 (B 键)、应用名 Seqviz
- [ ] v0.5.0 -- VCF 可视化、序列筛选 (--min-len, --min-gc, --grep)
- [ ] v0.6.0 -- 多格式支持 (GFF/BED)，格式互转
- [ ] v1.0.0 -- PyPI 发布，完整测试覆盖，CI

---

## License

MIT
