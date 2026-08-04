<div align="center">

<img src="assets/logo.svg" width="240" alt="seqviz logo">

# Seqviz — ⚡ Terminal Sequence Viewer

**在终端中彩色、交互地查看 FASTA / FASTQ 序列文件**

[安装](#安装) · [快速开始](#快速开始) · [浏览器](#交互式浏览器) · [配置](#配置)

<sup>当前版本 v0.6.3 · 需要 Python >= 3.12</sup>

</div>

---

## ✨ 功能特性

- 🧬 **DNA / 蛋白质自动检测** — 四色碱基着色 (A/T/C/G)，氨基酸按化学性质分组着色
- 📊 **FASTQ 质量可视化** — Phred 梯度着色、质量分布条、Q30 统计
- 🧪 **VCF 变异浏览** — 变异类型着色、逐样本基因型 + reads 比例条、基因型矩阵、过滤/排序/Ts-Tv 统计
- 🖥️ **交互式 TUI 浏览器** — 搜索、跳转、复制、导出、多标签页，支持十万级序列
- 📁 **目录文件选择器** — 扫描目录中的序列文件，预览、多选批量打开
- 📈 **统计摘要** — 序列条数、总长度、N50、GC 含量，表格化输出
- ⚡ **极致性能** — 未压缩文件 O(1) seek 定位 + 虚拟化列表 + 按需渲染，GB 级文件流畅浏览
- 🎨 **8 套内置主题** — light / dark / nord / gruvbox / catppuccin / solarized / rose-pine / tokyo-night，一键切换
- 📦 **gzip 支持** — 直接读取 `.gz` 压缩文件，无需预解压（顺序浏览；随机跳转需解压中间数据，随文件大小线性变慢）

## 安装

```bash
# 从源码安装（推荐，PyPI 发布筹备中）
git clone https://github.com/Georicl/seqviz.git && cd seqviz
uv tool install .

# 或从 GitHub Release 下载 wheel 后安装
uv tool install seqviz-<version>-py3-none-any.whl
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

# VCF 变异浏览器
seqviz browse variants.vcf
```

## 命令一览

| 命令 | 说明 |
|------|------|
| `seqviz` | 打开当前目录文件选择器 |
| `seqviz view <file>` | 彩色查看 FASTA 文件 |
| `seqviz fqview <file>` | 彩色查看 FASTQ 文件（含质量值） |
| `seqviz head <file>` | 查看前 N 条序列 |
| `seqviz stats <file>` | 输出统计摘要表格 |
| `seqviz browse <path>` | 交互式 TUI 浏览器（FASTA/FASTQ/VCF 自动路由） |
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

当 `browse` 传入目录（或直接运行 `seqviz`）时启动。自动扫描 `.fa .fasta .fna .faa .aa .seq .fq .fastq .vcf` 及 `.gz`。

| 按键 | 功能 |
|------|------|
| `j` / `k` | 上下移动 |
| `Space` | 切换多选 |
| `a` | 全选/取消 |
| `Enter` | 打开（多选则批量标签页） |
| `q` | 取消并退出 |

## VCF 变异浏览器

```bash
seqviz browse variants.vcf
```

左右双栏：**左侧变异列表**（懒扫描索引 + 虚拟化）+ **右侧变异详情 / 基因型矩阵**。

- 变异类型着色：转换 ● 绿 · 颠换 ● 蓝 · 插入 ◆ 黄 · 缺失 ◆ 红
- 行颜色编码可信度：PASS 绿 · 低质量黄 · 低深度红
- 详情面板逐样本展示基因型 + AD reads 比例条

| 按键 | 功能 | 按键 | 功能 |
|------|------|------|------|
| `j` / `k` | 上下移动 | `Space` / `b` | 翻页 |
| `/` | 搜索：ID / 坐标 / 范围 | `f` | 过滤循环（全部/PASS/SNP/InDel） |
| `s` | 排序（位置 ↔ QUAL） | `t` | 详情 ↔ 基因型矩阵 |
| `i` | 文件信息 | `y` | 复制当前 VCF 行 |
| `?` | 帮助 | `q` | 退出 |

**搜索 `/` 支持的格式：**

- `rs12345` — 按变异 ID 搜索
- `chr1:10234` — 跳到该坐标最近的变异（精确或最近邻）
- `chr1:10000-20000` / `chr1:10000..20000` — 跳到区间内第一个变异（两种分隔符均可，支持千分位逗号）

> 列表右侧为**真实比例滚动条**：滑块位置/长度映射全量变异（非窗口缓冲），点击/拖拽可直达任意位置。大文件采用快扫启动 + 后台续扫，扫描中搜索仅在已索引数据内查找并提示已索引条数。

> 底部状态栏常驻统计：变异总数 · SNP/InDel · Ts/Tv · PASS 数 · AF 均值，随过滤实时联动。目前支持未压缩 `.vcf`（bgzip/tabix 规划中）。

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
  },
  "colors": {
    "dna": { "A": "green", "T": "red", "C": "blue", "G": "yellow", "N": "dim" },
    "quality_thresholds": { "high": 30, "medium": 20, "low": 10 }
  },
  "file_browser": {
    "extensions": [".fa", ".fasta", ".fna", ".faa", ".aa", ".seq", ".fq", ".fastq"]
  }
}
```

> `auto_wrap: true`（默认）时，序列按窗口宽度自动换行；设为 `false` 则使用固定的 `wrap_width`。
>
> `colors.dna` 自定义碱基着色（Rich 颜色名或十六进制）；`colors.quality_thresholds` 控制质量值三档着色的 Phred 阈值；`file_browser.extensions` 控制文件选择器扫描的后缀。运行 `seqviz config` 可查看完整默认值。

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
≥30 绿色 · ≥20 黄色 · ≥10 亮红 · <10 红色

## 性能

基于大文件实测（Apple Silicon · SMB 网络卷）：

| 操作 | 数据规模 | 耗时 |
|------|---------|------|
| 扫描索引 | 10K 序列 (25MB) | ~7 ms |
| 扫描索引 | 50K reads (30MB) | ~46 ms |
| 扫描索引 | 1.3G pangenome (350 seqs) | ~1.3 s |
| 加载序列 | 79Mbp chr1 (分块模式) | ~3 ms |
| 滚动 | 超长序列浏览 | ~3.8 ms/次 |

> **v0.6.3 健壮性与可靠性修复**：导出不再静默覆盖已有文件（自动追加序号）并净化全部跨平台非法文件名字符；同一文件多标签页后台扫描不再错配污染数据；非 UTF-8 编码 header 宽容处理不再崩溃；theme.json 非法类型字段自动过滤不再导致应用无法启动；文件选择器序列计数真正可取消（GB 级文件预览后退出不再挂起）；窗口加宽后不再空白屏；剪贴板工具异常退出不再崩溃；畸形 FASTQ 空行宽容与友好报错；空文件 CLI 改为非零退出；测试环境隔离用户配置；测试套件扩充至 210 项。
>
> **v0.6.2 健壮性与体验修复**：修复帮助面板打开时按 q 直接退出应用（现为关闭面板）；Tab 键真实切换文件标签页且不再穿透模态帮助屏；空文件按 e/y 不再崩溃；配置类型校验宽容 0/1 与整数值 float（避免行为静默反转）；文件选择器序列计数移入后台线程并去重、退出可取消；格式检测统一单一入口、gzip 后缀大小写全链路一致；`config --init` 不再生成覆盖内置主题的 theme.json；修复状态栏被 Footer 遮挡；测试套件扩充至 183 项。
>
> **v0.6.1 正确性与性能修复**：修复后台扫描重复追加导致的侧栏点选错位；修复可变行宽/含空行 FASTA 分块读取错位（checkpoint 索引回退）；后台扫描移入线程不再冻结 UI（p95 延迟 1445ms→71ms）；大序列指标缓存 + 流式导出；测试套件扩充至 160 项。
>
> **v0.5.0 性能优化**：懒长度扫描使索引提速 25-68x，分块加载使大序列（>1Mbp）加载提速 634x、内存降低 7917x。

## 开发

```bash
git clone https://github.com/Georicl/seqviz.git && cd seqviz
uv sync
uv run pytest test/ -v          # 254 个测试
```

## License

MIT
