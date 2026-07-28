# fasta-fmt

**生物序列终端美化工具 -- 做序列界的 `bat`**

在终端中彩色查看 FASTA/FASTQ 文件，支持 DNA 碱基着色、蛋白质氨基酸着色、质量值梯度显示、统计摘要、交互式 TUI 浏览器。

---

## 功能特性

- **彩色序列查看** -- DNA 碱基着色 (A/T/C/G 四色)，蛋白质按化学性质分组着色
- **序列类型自动检测** -- 自动识别 DNA / 蛋白质序列，切换对应配色方案
- **FASTQ 支持** -- 质量值 Phred 梯度着色，质量分布条，序列与质量值对齐显示
- **统计摘要** -- 序列条数、总长度、N50、GC 含量，Rich 表格输出
- **交互式浏览器** -- 基于 Textual 的 TUI，支持搜索、跳转、复制、导出、多文件标签页
- **gzip 支持** -- 直接读取 `.gz` 压缩文件
- **管道友好** -- 非 TTY 环境自动关闭颜色输出
- **流式解析** -- 生成器逐条读取，GB 级文件不占满内存

---

## 安装

```bash
# 从源码安装 (需要 uv)
git clone https://github.com/Georicl/fasta-fmt.git
cd fasta-fmt
uv sync
uv tool install .

# 或开发模式
uv pip install -e .
```

---

## 快速开始

```bash
# 彩色查看 FASTA 文件
fasta-fmt view genome.fasta

# 查看前 5 条序列
fasta-fmt head genome.fasta -n 5

# 统计摘要
fasta-fmt stats genome.fasta

# 查看 FASTQ 文件 (序列 + 质量值着色)
fasta-fmt fqview reads.fastq

# 交互式浏览 (TUI)
fasta-fmt browse genome.fasta

# 多文件标签页浏览
fasta-fmt browse genome.fasta proteins.faa reads.fastq
```

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `view <file>` | 美化查看 FASTA 文件 (碱基/氨基酸着色 + 位置标尺) |
| `head <file> [-n N]` | 查看前 N 条序列 |
| `stats <file>` | 统计摘要 (条数、长度、N50、GC%) |
| `fqview <file> [-n N]` | 美化查看 FASTQ 文件 (序列 + 质量值对齐着色) |
| `browse <file> [file2 ...]` | 交互式 TUI 浏览器 (支持多文件标签页) |

---

## 交互式浏览器

```bash
fasta-fmt browse genome.fasta
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
| `e` | 导出当前序列到文件 |
| `?` | 显示帮助面板 |
| `Tab` | 切换文件标签页 (多文件模式) |
| `q` | 退出 |

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
git clone https://github.com/Georicl/fasta-fmt.git
cd fasta-fmt

# 安装依赖
uv sync

# 运行
uv run fasta-fmt view test/test.fa

# 测试
uv run pytest

# Shell 补全 (zsh)
fasta-fmt --install-completion zsh
```

---

## 项目结构

```
src/fasta_fmt/
  __init__.py
  cli.py            # CLI 入口 (Typer)
  parsers.py        # FASTA 流式解析器
  fastq.py          # FASTQ 流式解析器
  renderer.py       # 序列/质量值着色渲染
  seq_type.py       # 序列类型自动检测
  stats.py          # 统计计算 (N50, GC%)
  browser.py        # TUI 交互式浏览器 (Textual)
```

---

## Roadmap

- [x] v0.1.0 -- MVP: view / stats / head / fqview / browse
- [ ] v0.2.0 -- 序列筛选 (--min-len, --min-gc, --grep, --regex)
- [ ] v0.3.0 -- 多格式支持 (GFF/BED)，格式互转
- [ ] v1.0.0 -- PyPI 发布，完整测试覆盖，CI

---

## License

MIT
