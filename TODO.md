
# seqviz 开发计划

> 生物序列数据终端可视化工具 —— 做序列界的 `bat`
>
> 原名 `fasta-fmt`，已更名为 `seqviz`（涵盖 FASTA/FASTQ/VCF 等序列数据可视化）。

**当前版本**: v0.7.0rc2

---

## 项目结构

```
fasta-fmt/
├── src/
│   └── seqviz/
│       ├── __init__.py         # 包入口
│       ├── cli.py              # CLI 入口 (Typer)
│       ├── parsers.py          # FASTA 解析器
│       ├── fastq.py            # FASTQ 解析器
│       ├── vcf.py              # VCF 解析器
│       ├── renderer.py         # 序列着色渲染
│       ├── seq_type.py         # 序列类型检测 (DNA/Protein)
│       ├── stats.py            # 统计计算 (N50, GC%, 长度分布)
│       ├── browser.py          # TUI 交互式浏览器 (Textual)
│       ├── vcf_browser.py      # VCF TUI 浏览器 (双栏布局)
│       ├── file_browser.py     # 目录文件选择器
│       ├── clipboard.py        # 剪贴板操作 (分层回退)
│       ├── config.py           # JSON 配置系统
│       └── theme.py            # 主题系统 (8 套内置主题)
├── test/
│   ├── conftest.py             # 动态 fixture + 配置隔离
│   ├── test_browser.py
│   ├── test_cli.py
│   ├── test_config_theme.py
│   ├── test_core.py
│   ├── test_file_browser.py
│   ├── test_parsers.py
│   ├── test_performance.py
│   ├── test_regressions.py
│   ├── test_vcf.py
│   └── test_vcf_browser.py
├── config/
│   ├── config.json             # 默认配置模板
│   └── theme.json              # 主题配置模板
├── pyproject.toml
├── README.md
└── TODO.md
```

---

## 已完成功能

### Phase 1: MVP ✅

- [x] **1.1 项目基础配置**
  - [x] 配置 pyproject.toml (依赖: rich, textual, typer)
  - [x] 配置 uv 开发环境
  - [x] 设置 CLI 入口点 `seqviz`

- [x] **1.2 FASTA 解析器**
  - [x] 实现流式 FASTA 解析 (支持大文件, 分块加载)
  - [x] 解析 header (ID, description)
  - [x] 解析 sequence
  - [x] 支持 gzip 压缩文件 (.fa.gz)
  - [x] 大文件 seek 定位 + 虚拟列表

- [x] **1.3 序列着色渲染**
  - [x] DNA 碱基着色: A(绿) T(红) C(蓝) G(黄)
  - [x] 蛋白质氨基酸着色 (按化学性质分组)
  - [x] 使用 Rich 库实现终端彩色输出
  - [x] 支持管道输出 (检测是否为 TTY)
  - [x] 序列类型自动检测 (DNA/Protein)

- [x] **1.4 基础 CLI 命令**
  - [x] `seqviz view <file>` - 美化查看
  - [x] `seqviz stats <file>` - 统计摘要
  - [x] `seqviz head <file> -n 10` - 查看前N条序列

### Phase 2: 核心功能 ✅

- [x] **2.1 FASTQ 支持**
  - [x] FASTQ 格式解析
  - [x] 质量值着色 (Phred score 梯度色)
  - [x] `seqviz fqview` 命令 (序列 + 质量值对齐着色)

- [x] **2.2 统计功能增强**
  - [x] N50 / N90 / L50 计算
  - [x] GC 含量统计
  - [x] 序列长度分布 (min/max/mean/median)
  - [x] 表格化输出 (Rich Table)

- [ ] **2.3 序列筛选** (未实现，已移入下方待办)

### Phase 3: 进阶功能 ✅ (大幅超越原规划)

- [x] **3.1 VCF 格式支持** (原规划为 GFF/BED，实际实现 VCF)
  - [x] VCF 懒扫描解析 (30 万变异 ~1s)
  - [x] 变异分类与着色 (SNP/Insertion/Deletion)
  - [x] 双栏 TUI 布局 (变异列表 + 基因型矩阵)
  - [x] 过滤/排序/搜索
  - [x] 后台续扫 + GIL 让出优化

- [x] **3.2 交互式 TUI 浏览器** (Textual 框架)
  - [x] 大文件分块加载 (二进制快路径 + checkpoint 索引)
  - [x] 交互式翻页浏览 (j/k/Space/PageUp/PageDown)
  - [x] 序列搜索跳转 (/ 搜索, n 下一个)
  - [x] 位置跳转 (g 跳转输入)
  - [x] 序列范围复制 (y 键, 支持 100-200 格式)
  - [x] 帮助面板 (? 键)
  - [x] 多文件标签切换 (Tab)
  - [x] 侧栏序列信息面板

- [x] **3.3 目录文件浏览器**
  - [x] 目录浏览与文件选择
  - [x] 文件格式标记 ([F] FASTA, [Q] FASTQ, [V] VCF)
  - [x] 序列数/变异数预览

- [x] **3.4 JSON 配置系统**
  - [x] 用户级配置 (~/.config/seqviz/config.json)
  - [x] 8 套内置主题
  - [x] 可配置交互参数 (wrap_width, scroll_step 等)
  - [x] `seqviz config` 命令 (查看/初始化配置)

### Phase 4: 发布 (部分完成)

- [x] **4.1 文档与测试**
  - [x] README 文档
  - [x] 单元测试 333 项全部通过
  - [x] 性能测试与回归测试
  - [x] 单元测试覆盖率 > 80% (CI 门禁 85%)
  - [ ] GIF 演示

- [x] **4.2 发布配置**
  - [x] PyPI 发布配置 (hatchling)
  - [x] GitHub Actions CI
  - [x] LICENSE

---

## 待办 / 未来规划

### 高优先级

- [x] 添加 GitHub Actions CI (自动测试 + ruff lint)
- [x] 添加 LICENSE 文件 (MIT)
- [ ] browser.py 拆分重构 (当前 1220 行 God Object)
  - [ ] 提取 sequence_view.py (分块引擎 + SequenceView)
  - [ ] 提取 components.py (共享 UI 组件)
  - [ ] 提取 app.py (控制器)
- [ ] 统一 VCF 检测逻辑 (消除 cli.py / file_browser.py / browser.py 三处平行判断)

### 中优先级

- [ ] _load_chunk 添加 LRU 缓存 (减少 HDD 上的 seek+read 次数)
- [ ] compute_stats 改为接受 Iterable (消除中间列表分配)
- [ ] vcf_browser.py 硬编码常量可配置化 (WINDOW=400)
- [x] 剪贴板逻辑去重 (已提取为 clipboard.py 共享模块)

### 低优先级 / 可选

- [ ] GFF/GFF3 格式支持
- [ ] BED 格式支持
- [ ] 格式互转命令
- [ ] `--format markdown` / `--format html` 输出
- [ ] `--no-color` 纯文本输出
- [ ] `--min-len` / `--max-len` 按长度筛选
- [ ] `--grep` 按名称/描述模糊搜索
- [ ] `--min-gc` / `--max-gc` 按 GC 含量筛选
- [ ] `--regex` 按序列 motif 正则筛选

---

## 技术栈

| 组件 | 选择 | 用途 |
|------|------|------|
| CLI 框架 | Typer | 命令行参数解析 |
| TUI 框架 | Textual | 交互式终端浏览器 |
| 终端渲染 | Rich | 彩色输出、表格、面板 |
| 包管理 | uv | 依赖管理 |
| 构建 | hatchling | wheel/sdist 构建 |
| 测试 | pytest + pytest-cov | 单元测试 + 覆盖率 |
| Lint | ruff | 代码检查与格式化 |
| Python | >= 3.14 | 运行时 |

---

## CLI 命令

```bash
# 交互式浏览器 (主功能，直接跟路径)
seqviz genome.fasta          # 打开单文件浏览器
seqviz data/                 # 目录文件选择器
seqviz                       # 当前目录浏览器

# 辅助命令
seqviz view genome.fasta     # 美化查看 (Rich 输出)
seqviz stats genome.fasta    # 统计摘要
seqviz head genome.fasta -n 5  # 查看前 N 条
seqviz fqview reads.fastq    # FASTQ 质量值着色
seqviz config                # 查看配置
seqviz config --init         # 生成配置模板
```

---

## 性能指标 (已达成)

- 50k 序列文件扫描: 36ms
- 2M bp 超长序列加载: 10ms
- 滚动渲染: 5.6ms/次
- 30 万 VCF 变异扫描: ~1s
- VCF 过滤切换: ~600ms (窗口化虚拟化)

---

## 里程碑

| 版本 | 内容 | 状态 |
|------|------|------|
| v0.1.0 | MVP: view + stats + 碱基着色 | ✅ 已发布 |
| v0.2.0 | FASTQ + 筛选 | ✅ 已发布 |
| v0.3.0 | JSON 配置 + 性能优化 | ✅ 已发布 |
| v0.5.0 | TUI 浏览器 + 文件选择器 | ✅ 已发布 |
| v0.7.0 | VCF 可视化 + 双栏布局 | 🔄 rc2 |
| v1.0.0 | 稳定版 + CI + 完整文档 | 📋 规划中 |
