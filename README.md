<div align="center">

<img src="assets/logo.svg" width="240" alt="seqviz logo">

# Seqviz — ⚡ Terminal Sequence Viewer

**在终端中彩色、交互地查看 FASTA / FASTQ 序列文件**

[安装](#安装) · [快速开始](#快速开始) · [浏览器](#交互式浏览器) · [配置](#配置)

<sup>当前版本 v0.5.0 · 需要 Python >= 3.12</sup>

</div>

---

## ✨ 功能特性

- 🧬 **DNA / 蛋白质自动检测** — 四色碱基着色 (A/T/C/G)，氨基酸按化学性质分组着色
- 📊 **FASTQ 质量可视化** — Phred 梯度着色、质量分布条、Q30 统计
- 🖥️ **交互式 TUI 浏览器** — 搜索、跳转、复制、导出、多标签页，支持十万级序列
- 📁 **目录文件选择器** — 扫描目录中的序列文件，预览、多选批量打开
- 📈 **统计摘要** — 序列条数、总长度、N50、GC 含量，表格化输出
- ⚡ **极致性能** — O(1) seek 定位 + 虚拟化列表 + 按需渲染，GB 级文件流畅浏览
- 🎨 **8 套内置主题** — light / dark / nord / gruvbox / catppuccin / solarized / rose-pine / tokyo-night，一键切换
- 📦 **gzip 支持** — 直接读取 `.gz` 压缩文件，无需预解压

## 安装

```bash
# 从 PyPI 安装（推荐）
pipx install seqviz

# 或 pip 安装
pip install seqviz

# 从源码安装
git clone https://github.com/Georicl/seqviz.git && cd seqviz
uv tool install .
```

安装后启用 shell 补全（可选）：

```bash
seqviz --install-completion zsh   # 或 bash
```

开发模式：

```bash
uv pip install -e .
uv run seqviz --help
```

## 快速开始

```bash
# 打开当前目录的文件选择器
seqviz

# 查看单个文件
seqviz view genome.fasta
seqviz fqview reads.fastq

# 统计摘要
seqviz stats genome.fasta

# 交互式浏览器
seqviz browse genome.fasta
```

## 命令一览

| 命令 | 说明 |
|------|------|
| `seqviz` | 打开当前目录文件选择器 |
| `seqviz view <file>` | 彩色查看 FASTA 文件 |
| `seqviz fqview <file>` | 彩色查看 FASTQ 文件（含质量值） |
| `seqviz head <file>` | 查看前 N 条序列 |
| `seqviz stats <file>` | 输出统计摘要表格 |
| `seqviz browse <path>` | 交互式 TUI 浏览器 |
| `seqviz config [--init]` | 查看/生成配置文件 |

## 交互式浏览器

```bash
seqviz browse genome.fasta
```

左右双栏布局：**左侧序列列表**（虚拟化）+ **右侧序列详情**（按需渲染）

### 快捷键

| 按键 | 功能 | 按键 | 功能 |
|------|------|------|------|
| `j` / `k` | 上下滚动 | `n` / `p` | 下/上一条序列 |
| `Space` / `b` | 下/上翻页 | `g` / `G` | 跳到顶部/底部 |
| `/` | 搜索序列名 | `:` | 跳转到第 N 条 |
| `y` | 复制到剪贴板 | `c` | 范围复制 (如 `100-200`) |
| `e` | 导出序列到文件 | `B` | 返回文件选择器 |
| `Tab` | 切换文件标签页 | `?` | 帮助面板 |
| `q` | 退出 | | |

### 文件选择器

当 `browse` 传入目录（或直接运行 `seqviz`）时启动。自动扫描 `.fa .fasta .fna .faa .aa .seq .fq .fastq` 及 `.gz`。

| 按键 | 功能 |
|------|------|
| `j` / `k` | 上下移动 |
| `Space` | 切换多选 |
| `a` | 全选/取消 |
| `Enter` | 打开（多选则批量标签页） |

## 配置

```bash
seqviz config --init    # 生成 ~/.config/seqviz/config.json 和 theme.json
seqviz config           # 查看当前生效配置与可用主题
```

只需写入想覆盖的字段，其余自动保持默认（深度合并）。

<details>
<summary>config.json 示例</summary>

```json
{
  "theme": "nord",
  "browser": {
    "wrap_width": 60,
    "auto_wrap": true,
    "scroll_step": 5,
    "sidebar_width": 32,
    "show_line_numbers": true,
    "show_quality": true
  }
}
```

> `auto_wrap: true`（默认）时，序列按窗口宽度自动换行；设为 `false` 则使用固定的 `wrap_width`。

</details>

## 内置主题

8 套精选配色，在 `config.json` 中设置 `"theme": "名称"` 即可切换：

| 主题 | 风格 | 色调 |
|------|------|------|
| `light` | 白底黑字 · 清晰明亮 | ☀️ 亮色 |
| `dark` | 经典深色 · 护眼低对比（默认） | 🌙 暗色 |
| `nord` | 北极冷色 · 柔和优雅 | 🧊 冷色 |
| `gruvbox` | 暖色复古 · 棕黄基调 | 🔥 暖色 |
| `catppuccin` | 柔和粉彩 · 温暖暗色 | 🌸 粉彩 |
| `solarized` | 经典 Solarized Dark | 🌊 青蓝 |
| `rose-pine` | 玫瑰松木 · 低饱和暖紫 | 🌹 暖紫 |
| `tokyo-night` | 东京夜景 · 蓝紫冷调 | 🌃 蓝紫 |

用户可通过 `~/.config/seqviz/theme.json` 进一步覆盖任意颜色字段。

## 配色方案

**DNA 碱基：**
`A` 绿色 · `T` 红色 · `C` 蓝色 · `G` 黄色 · `N` 灰色

**蛋白质氨基酸（按化学性质）：**
疏水性 (AVILMFYW) 绿色系 · 亲水性 (STNQ) 蓝色系 · 碱性 (RKH) 红色系 · 酸性 (DE) 紫色系 · 特殊 (GPC) 灰色系

**质量值 (Phred)：**
≥30 绿色 · ≥20 黄色 · ≥10 橙色 · <10 红色

## 性能

基于大文件实测（Apple Silicon · SMB 网络卷）：

| 操作 | 数据规模 | 耗时 |
|------|---------|------|
| 扫描索引 | 10K 序列 (25MB) | ~7 ms |
| 扫描索引 | 50K reads (30MB) | ~46 ms |
| 扫描索引 | 1.3G pangenome (350 seqs) | ~1.3 s |
| 加载序列 | 79Mbp chr1 (分块模式) | ~3 ms |
| 滚动 | 超长序列浏览 | ~3.8 ms/次 |

> **v0.5.0 性能优化**：懒长度扫描使索引提速 25-68x，分块加载使大序列（>1Mbp）加载提速 634x、内存降低 7917x。

## 开发

```bash
git clone https://github.com/Georicl/seqviz.git && cd seqviz
uv sync
uv run pytest test/ -v          # 147 个测试
```

## License

MIT
