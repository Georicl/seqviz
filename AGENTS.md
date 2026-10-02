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
uvx ruff@0.16.3 check src/ test/        # 与 CI 一致的 lint
uv build                               # 构建 wheel/sdist 到 dist/
```

## 核心模块职责

| 模块 | 职责 |
|------|------|
| `cli.py` | Typer CLI 入口；`_DefaultBrowseGroup` 实现"浏览为主"路由（首参非子命令时默认走 browse）；子命令 view/stats/head/fqview/config/browse |
| `core/formats.py` | 文件格式识别和 gzip 打开；格式判断共用这个入口 |
| `core/index.py` | 序列元信息、首屏快扫与可取消的完整扫描 |
| `core/sequence_reader.py` | 文件句柄、序列读取、行宽指标、checkpoint 与有限缓冲 |
| `core/fasta.py` / `core/fastq.py` / `core/vcf.py` | 流式解析；VCF 分类、基因型、懒加载及统计 |
| `core/files.py` | 目录文件发现、元信息与记录计数 |
| `core/seq_type.py` / `core/stats.py` | 序列类型识别与长度、GC、N50、质量值统计 |
| `ui/sequence/app.py` | FASTA/FASTQ 应用控制器、后台任务、多标签及命令处理 |
| `ui/sequence/view.py` / `widgets.py` | 序列显示、换行、侧栏及交互控件 |
| `ui/variants/app.py` / `widgets.py` | VCF 列表、详情与基因型矩阵；历史设计见 `docs/superpowers/specs/2026-07-25-vcf-visualization-design.md` |
| `ui/files.py` | 目录选择器、预览与批量打开 |
| `ui/renderer.py` | Rich 碱基着色、质量值着色与位置标尺 |
| `clipboard.py` | 跨平台剪贴板复制：系统工具优先（pbcopy/xclip/wl-copy），失败回退 OSC 52；序列与 VCF 界面共用此实现 |
| `config.py` / `ui/theme.py` | JSON 配置系统；8 套内置主题与用户覆盖 |

## 开发约定

1. **包布局**：`src/` layout，wheel 打包 `packages = ["src/seqviz"]`；`core` 不依赖 Rich、Textual 或 `ui`。测试按 `test/core/`、`test/ui/`、`test/cli/`、`test/performance/` 分类，公共数据在 `test/data/`。移动内部模块时同步更新调用方，不保留无用途的转发模块。
2. **ruff per-file-ignores**（勿误改）：
   - `src/seqviz/cli.py` 豁免 `B008` — Typer 惯用法：`typer.Argument/Option` 在函数默认参数中调用；
   - `test/**` 豁免 `RUF059`/`RUF015` — 测试中解包未使用变量、切片取首元素是常见模式。
3. **坐标系统**：VCF 全链路保持 **1-based**（解析、存储、搜索、显示均不转换）；FASTA 范围复制时做 1-based → 0-based 转换。
4. **大文件策略**：浏览器用分块读取、seek 定位与有限缓冲；`parse_fasta` 按记录拼接完整序列，仅用于 CLI view/stats/head。扫描取消在块读取之间检查，不等到下一条记录才检查。非等宽 FASTA 应复用同一屏内容，避免每个显示行重新扫描 checkpoint 前缀。
5. **gzip**：`.gz` 后缀（大小写不敏感）统一用 `gzip.open` 透明读取。
6. **Textual 注意**：Widget 基类无 `update` 方法，需类型断言为 `Static` 再调用。
7. **发布**：版本号遵循 PEP 440（如 `0.7.0rc1`，不用 `0.7.0-vcf.1` 这类格式）。

## 已知架构债务

修改以下区域时保持克制：

- FASTA/FASTQ 侧栏仍为每条记录创建 Option，尚未采用 VCF 的有限窗口。
- VCF 索引仍持有全量 Python 对象，已查看的样本详情会留在索引中。
- VCF 的 `WINDOW = 400` 尚未接入配置系统。
- CLI 按记录解析与浏览器按区间读取并存；格式规则需保持一致。

注释应说明坐标、缓冲生命周期、线程归属和取消条件。删除已过时的修复编号、空事件处理器与重复校验；保留实际输入校验、任务失效判断和导出防覆盖行为。
