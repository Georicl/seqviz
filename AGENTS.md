# AGENTS.md — seqviz 项目代理指引

## 项目概述

seqviz 是一个生物序列数据的终端可视化工具，支持 **FASTA / FASTQ / VCF** 三种格式的彩色查看、统计与交互式浏览。核心卖点：DNA 碱基着色、FASTQ 质量值梯度、VCF 双栏浏览（变异列表 + 基因型矩阵）、GB 级大文件流畅滚动。

- 技术栈：**Typer**（CLI）+ **Rich**（终端渲染）+ **Textual**（TUI）
- Python：**>= 3.14**（`pyproject.toml` 中 `requires-python`）
- 构建/包管理：**uv**（`uv build`、`uv run`、`uv add`）
- 入口命令：`seqviz = "seqviz.cli:app"`，浏览是主功能（`seqviz <路径>` 直接打开浏览器）

## 常用命令

```bash
uv run pytest test/ -x -q --tb=short   # 运行测试
uv run ruff check src/ test/           # lint
uv build                               # 构建 wheel/sdist 到 dist/
```

## 核心模块职责

| 模块 | 职责 |
|------|------|
| `cli.py` | Typer CLI 入口；`_DefaultBrowseGroup` 实现"浏览为主"路由（首参非子命令时默认走 browse）；子命令 view/stats/head/fqview/config/browse |
| `browser.py` | FASTA/FASTQ 交互式 TUI 浏览器（Textual App）；分块加载 + O(1) seek 定位 + 多标签 |
| `vcf_browser.py` | VCF 双栏 TUI 浏览器：左变异列表 + 右详情/基因型矩阵；设计文档见 `docs/superpowers/specs/2026-07-25-vcf-visualization-design.md` |
| `file_browser.py` | 目录文件选择器：扫描序列文件、预览、多选批量打开 |
| `parsers.py` / `fastq.py` / `vcf.py` | 解析层：FASTA 流式解析 / FASTQ 解析 / VCF 分类·基因型·lazy-scan·统计 |
| `renderer.py` | Rich 渲染：碱基着色、质量值着色、位置标尺 |
| `seq_type.py` | 序列类型检测（DNA/RNA/蛋白质） |
| `stats.py` | 统计：条数、总长度、N50、GC 含量 |
| `clipboard.py` | 跨平台剪贴板复制：系统工具优先（pbcopy/xclip/wl-copy），失败回退 OSC 52；browser 与 vcf_browser 共用此实现 |
| `config.py` / `theme.py` | JSON 配置系统（`config/config.json`）；8 套内置主题 + `theme.json` 自定义 |

## 开发约定

1. **包布局**：`src/` layout，wheel 打包 `packages = ["src/seqviz"]`；所有源码在 `src/seqviz/`，测试在 `test/`（文件名与模块对应）。
2. **ruff per-file-ignores**（勿误改）：
   - `src/seqviz/cli.py` 豁免 `B008` — Typer 惯用法：`typer.Argument/Option` 在函数默认参数中调用；
   - `test/*` 豁免 `RUF059`/`RUF015` — 测试中解包未使用变量、切片取首元素是常见模式。
3. **坐标系统**：VCF 全链路保持 **1-based**（解析、存储、搜索、显示均不转换）；FASTA 范围复制时做 1-based → 0-based 转换。
4. **大文件策略**：浏览器侧用分块加载 + seek 定位 + 虚拟化列表；`parse_fasta` 全量流式解析仅用于 CLI view/stats/head 小路径，勿在大文件浏览路径中引入全量加载。
5. **gzip**：`.gz` 后缀（大小写不敏感）统一用 `gzip.open` 透明读取。
6. **Textual 注意**：Widget 基类无 `update` 方法，需类型断言为 `Static` 再调用。
7. **发布**：版本号遵循 PEP 440（如 `0.7.0rc1`，不用 `0.7.0-vcf.1` 这类格式）。

## 已知架构债务

修改以下区域时保持克制，勿扩大重复：

- **`browser.py` 是 God Object**（~1200 行，含多个类）；规划拆分为 `sequence_view.py`（分块引擎）/ `components.py`（共享 UI 组件）/ `app.py`（控制器）。
- **VCF 检测三处平行**：`cli.py:_is_vcf`、`file_browser.is_vcf_file`、`browser.detect_format`；`FileFormat` 枚举尚未纳入 VCF。
- **硬编码常量**：`vcf_browser.py` 中 `WINDOW = 400` 未走配置系统。
- **`_load_chunk` 无 LRU 缓存**：一次滚动约 40 次独立 seek+read。
- **CLI 双轨制**：view/stats/head 用 `parse_fasta` 全量加载，与浏览器的分块路径并存。
