<div align="center">

<img src="assets/logo.svg" width="240" alt="seqviz logo">

# Seqviz — 终端序列查看器

**在终端里彩色、交互地看 FASTA / FASTQ / VCF 文件**

[安装](#安装) · [快速开始](#快速开始) · [浏览器](#交互式浏览器) · [配置](#配置)

<sup>v0.7.0 · Python >= 3.14</sup>

</div>

---

做生信的人大概都有过这种体验：想看一眼 FASTA 文件的内容，`cat` 出来满屏 ATCG 糊在一起；想统计序列条数和 N50，得现写一段 Python；想翻 VCF 文件找某个变异，`grep` 半天对不齐列。

Seqviz 就是为了解决这些小事。一个终端工具，装上就能用。

## 能做什么

- **彩色查看序列** — DNA 四色碱基着色 (A/T/C/G)，蛋白质按化学性质分组，一眼就能看出序列特征
- **FASTQ 质量可视化** — Phred 梯度着色、Q30 统计，质控不用开 FastQC
- **VCF 变异浏览** — 变异类型着色、逐样本基因型 + reads 比例条、Ts/Tv 统计
- **交互式浏览器** — 搜索、跳转、复制、导出、多标签页，十万级序列流畅滚动
- **目录文件选择器** — 扫描目录里的序列文件，预览、多选批量打开
- **统计摘要** — 条数、总长度、N50、GC 含量，一条命令搞定
- **大文件友好** — 未压缩文件 O(1) seek 定位 + 虚拟化列表，GB 级文件也能流畅浏览
- **8 套主题** — nord / gruvbox / catppuccin / tokyo-night 等，`config.json` 改一行就换
- **gzip 直接读** — `.gz` 文件不用解压就能看（随机跳转需解压，会慢一些）

## 安装

```bash
# 推荐方式
git clone https://github.com/Georicl/seqviz.git && cd seqviz
uv tool install .

# 或者下载 wheel 安装
uv tool install seqviz-<version>-py3-none-any.whl
```

Shell 补全（可选）：

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
# 直接打开文件（主功能，自动识别 FASTA/FASTQ/VCF）
seqviz genome.fasta
seqviz variants.vcf

# 不传文件？打开目录选择器
seqviz

# 看文件
seqviz view genome.fasta
seqviz fqview reads.fastq

# 统计
seqviz stats genome.fasta
```

## 命令

| 命令 | 干什么的 |
|------|---------|
| `seqviz <path>` | 交互式浏览器（主功能，自动识别 FASTA/FASTQ/VCF） |
| `seqviz` | 打开目录文件选择器 |
| `seqviz view <file>` | 彩色看 FASTA |
| `seqviz fqview <file>` | 彩色看 FASTQ（带质量值） |
| `seqviz head <file>` | 看前 N 条序列 |
| `seqviz stats <file>` | 统计摘要 |
| `seqviz config [--init]` | 看/生成配置 |

## 交互式浏览器

```bash
seqviz genome.fasta
```

左边序列列表（虚拟化渲染），右边序列详情（按需加载）。
较大的 FASTA 会先显示序列前段；长度索引完成后可跳转全长并复制或导出。

### 快捷键

| 按键 | 功能 | 按键 | 功能 |
|------|------|------|------|
| `j` / `k` | 上下滚 | `n` / `p` | 下/上一条 |
| `Space` / `b` | 翻页 | `g` / `G` | 顶/底部 |
| `/` | 搜索序列名 | `:` | 跳到第 N 条 |
| `y` | 复制 | `c` | 范围复制 |
| `e` | 导出 | `B` | 回文件选择器 |
| `Tab` | 切标签页 | `?` | 帮助 |
| `q` | 退出 | | |

### 文件选择器

传目录（如 `seqviz data/`，或直接运行 `seqviz`）就会启动。自动扫描 `.fa .fasta .fna .fq .fastq .vcf` 及 `.gz`。

| 按键 | 功能 |
|------|------|
| `j` / `k` | 上下移 |
| `Space` | 多选 |
| `a` | 全选/取消 |
| `Enter` | 打开（多选会开多个标签页） |
| `q` | 退出 |

## VCF 变异浏览器

```bash
seqviz variants.vcf
```

左边变异列表，右边详情面板或基因型矩阵。

- 变异类型着色：转换 ● 绿 · 颠换 ● 蓝 · 插入 ◆ 黄 · 缺失 ◆ 红
- 行颜色表示可信度：PASS 绿 · 低质量黄 · 低深度红
- 详情面板逐样本展示基因型 + AD reads 比例条

| 按键 | 功能 | 按键 | 功能 |
|------|------|------|------|
| `j` / `k` | 上下移（右侧聚焦时滚动详情） | `g` / `G` | 顶/底部 |
| `/` | 搜索 | `f` | 筛选循环 |
| `s` | 排序 | `t` | 详情 ↔ 矩阵 |
| `Tab` / `Esc` | 列表 ↔ 详情面板 | `i` | 文件信息 |
| `y` | 复制行 | `?` | 帮助 |
| `q` | 退出 | | |

**搜索 `/` 支持：**

- `rs12345` — 按 ID 搜
- `chr1:10234` — 跳到坐标最近的变异
- `chr1:10000-20000` — 跳到区间内第一个变异

> 列表右侧是真实比例滚动条，点击/拖拽直达任意位置。大文件用快扫启动 + 后台续扫。底部状态栏实时显示变异总数、SNP/InDel、Ts/Tv、PASS 数、AF 均值。

## 配置

```bash
seqviz config --init    # 生成 ~/.config/seqviz/config.json
seqviz config           # 查看当前配置
```

只写想改的字段，其余保持默认。

<details>
<summary>config.json 示例</summary>

```json
{
  "theme": "nord",
  "browser": {
    "wrap_width": 60,
    "auto_wrap": true,
    "scroll_step": 5
  },
  "colors": {
    "dna": { "A": "green", "T": "red", "C": "blue", "G": "yellow" }
  }
}
```

</details>

## 主题

8 套配色，`config.json` 里 `"theme": "名称"` 切换：

| 主题 | 风格 |
|------|------|
| `light` | 白底，明亮 |
| `dark` | 经典深色（默认） |
| `nord` | 北极冷色 |
| `gruvbox` | 暖色复古 |
| `catppuccin` | 柔和粉彩 |
| `solarized` | 经典 Solarized Dark |
| `rose-pine` | 低饱和暖紫 |
| `tokyo-night` | 蓝紫冷调 |

也可以用 `~/.config/seqviz/theme.json` 自定义任意颜色。

## 性能

Apple Silicon + SMB 网络卷实测：

| 操作 | 规模 | 耗时 |
|------|------|------|
| 扫描索引 | 10K 序列 (25MB) | ~7 ms |
| 扫描索引 | 50K reads (30MB) | ~46 ms |
| 扫描索引 | 1.3G pangenome (350 seqs) | ~1.3 s |
| 加载序列 | 79Mbp chr1 | ~3 ms |
| 滚动 | 超长序列 | ~3.8 ms/次 |

## 开发

```bash
git clone https://github.com/Georicl/seqviz.git && cd seqviz
uv sync
uv run pytest test/ -x -q --tb=short
uvx ruff@0.16.3 check src/ test/
uv build
```

### 代码结构

```text
src/seqviz/
├── cli.py                  # 命令路由与终端输出
├── config.py               # 用户配置加载与校验
├── clipboard.py            # 系统剪贴板与 OSC 52
├── core/                   # 格式、索引、区间读取、统计；不依赖界面
│   ├── formats.py          # 文件识别与 gzip 打开
│   ├── index.py            # 序列元信息、首屏快扫、可取消的完整扫描
│   ├── sequence_reader.py  # 序列读取、行宽索引与一屏缓冲
│   ├── fasta.py / fastq.py  # 流式记录解析
│   ├── vcf.py              # VCF 解析、分类、懒加载与统计
│   ├── files.py            # 目录发现与记录计数
│   └── stats.py / seq_type.py
└── ui/
    ├── sequence/           # FASTA/FASTQ：app 控制器、view 内容、widgets 控件
    ├── variants/           # VCF：app 控制器、widgets 控件
    ├── files.py            # 目录选择与预览
    ├── renderer.py         # Rich 着色与标尺
    └── theme.py            # 主题与 Textual CSS
```

数据处理放在 `core`，界面通过它取得记录和序列区间。`SequenceReader` 管理文件句柄和有限缓冲；`SequenceView` 负责换行、着色和可见行。后台扫描把批次交给主线程更新控件，取消检查在读取块之间执行。

FASTA 区间读取使用 0-based、右端不包含的坐标；界面的范围复制使用 1-based、两端包含的坐标，在调用读取器前转换。VCF 的位置从解析到显示都保持 1-based。gzip 读取支持顺序扫描，随机 seek 仍需要解压中间数据。

测试按 `test/core/`、`test/ui/`、`test/cli/`、`test/performance/` 分类，公共样例位于 `test/data/`。单元测试使用小型生成数据；GB 级手工基准由 `test/performance/gen_perf_data.py` 和 `run_perf_test.py` 配套执行。

## License

MIT
