from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from seqviz import config as config_mod
from seqviz import theme as theme_mod
from seqviz.browser import FastaBrowser
from seqviz.fastq import parse_fastq
from seqviz.file_browser import run_file_browser, scan_directory
from seqviz.parsers import parse_fasta
from seqviz.renderer import (
    colorize_quality,
    colorize_sequence,
    position_ruler,
    quality_bar,
    quality_stats,
)
from seqviz.seq_type import SeqType, detect_seq_type
from seqviz.stats import calc_sequence_stats

app = typer.Typer()
console = Console()


def _check_file(file: Path) -> Path:
    """检查文件存在，不存在则友好报错退出。"""
    if not file.exists():
        console.print(f"[red]错误: 文件不存在: {file}[/red]")
        raise typer.Exit(code=1)
    return file


def _is_vcf(path: Path) -> bool:
    """判断是否为 VCF 文件（仅支持未压缩 .vcf）。"""
    return path.is_file() and path.suffix.lower() == ".vcf"


def _run_vcf_browser(path: Path):
    """快扫前 5000 条做校验后立即启动 TUI，剩余索引由浏览器后台续扫（启动即显）。

    空文件/无 #CHROM 表头时友好报错非零退出。
    """
    from seqviz.vcf import scan_vcf_quick
    from seqviz.vcf_browser import VcfBrowser
    QUICK_LIMIT = 5000
    meta, variants, skipped, cont = scan_vcf_quick(path, limit=QUICK_LIMIT)
    if not meta.has_header:
        console.print(f"[red]错误: 不是有效的 VCF 文件（缺少 #CHROM 表头）: {path}[/red]")
        raise typer.Exit(code=1)
    if not variants:
        console.print(f"[red]错误: VCF 文件中没有变异记录: {path}[/red]")
        raise typer.Exit(code=1)
    VcfBrowser(path, initial=(meta, variants, skipped, cont)).run()


def _launch_browser(paths: list[Path]):
    """根据路径启动浏览器：目录走文件选择器，文件直接打开。

    支持从序列浏览器按 B 返回文件选择器（循环）。
    单个 .vcf 文件路由到 VcfBrowser。
    """
    # 单文件且为 .vcf → VCF 变异浏览器
    if len(paths) == 1 and _is_vcf(paths[0]):
        _run_vcf_browser(paths[0])
        return

    source_dir: Path | None = None

    # 单个目录 → 记住来源目录，走文件选择器流程
    if len(paths) == 1 and paths[0].is_dir():
        source_dir = paths[0]
    else:
        # 混合输入：展开其中的目录为序列文件
        expanded: list[Path] = []
        for p in paths:
            if p.is_dir():
                expanded.extend(info.path for info in scan_directory(p))
            else:
                expanded.append(p)
        paths = expanded

    while True:
        # 有来源目录 → 先走文件选择器
        if source_dir is not None:
            selected = run_file_browser(source_dir)
            if not selected:
                console.print("[dim]未选择任何文件[/dim]")
                raise typer.Exit()
            open_paths = selected
        else:
            open_paths = paths

        if not open_paths:
            console.print("[red]没有找到可打开的序列文件[/red]")
            raise typer.Exit()

        # 选中结果若为单个 .vcf → 路由到 VcfBrowser
        if len(open_paths) == 1 and _is_vcf(open_paths[0]):
            _run_vcf_browser(open_paths[0])
            break

        # VCF 暂不支持与序列文件混合打开：剥离并提示，避免在 FastaBrowser 中产生静默空标签页
        mixed_vcfs = [p for p in open_paths if _is_vcf(p)]
        if mixed_vcfs and len(open_paths) > 1:
            console.print("[yellow]VCF 文件暂不支持与其他文件混合打开，已跳过: "
                          + ", ".join(p.name for p in mixed_vcfs) + "[/yellow]")
            open_paths = [p for p in open_paths if not _is_vcf(p)]
            if not open_paths:
                if source_dir is not None:
                    continue  # 回到文件选择器重新选择
                raise typer.Exit()

        # 运行序列浏览器；按 B 返回 "back" 则重新进入文件选择器
        result = FastaBrowser(open_paths, source_dir=source_dir).run()
        if result != "back":
            break


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """seqviz — 生物序列数据终端可视化工具。

    不带任何命令时，默认打开当前目录的文件浏览器。
    """
    if ctx.invoked_subcommand is None:
        _launch_browser([Path(".")])


@app.command()
def view(
    file: Path = typer.Argument(help="FASTA 文件路径"),
    wrap: int = typer.Option(60, min=1, help="序列每行换行宽度"),
):
    """美化查看 FASTA 文件"""
    _check_file(file)
    for header, seq in parse_fasta(str(file)):
        seqtype = detect_seq_type(seq)
        type_label = "DNA" if seqtype == SeqType.DNA else "Protein" if seqtype == SeqType.PROTEIN else "Unknown"

        # header + 类型标签 + 长度
        console.print(
            f"[bold cyan]> {header}[/bold cyan] "
            f"[dim]\\[{type_label}] {len(seq)}bp[/dim]"
        )
        
        # 按 wrap 宽度切分，逐行着色并输出（避免整条 Rich Text 的 span explosion）
        for chunk_start in range(0, len(seq), wrap):
            chunk_end = min(chunk_start + wrap, len(seq))
            ruler = position_ruler(chunk_start + 1, chunk_end - chunk_start)
            console.print("  ", end="")
            console.print(ruler)
            console.print("  ", end="")
            console.print(colorize_sequence(seq[chunk_start:chunk_end], seq_type=seqtype))
        
        console.print()  # 序列间空行

@app.command()
def stats(
    file: Path = typer.Argument(help="FASTA 文件路径")
):
    """统计 FASTA 文件特征"""
    _check_file(file)
    lengths: list[int] = []
    total_gc = 0
    total_len = 0
    count = 0

    for header, seq in parse_fasta(str(file)):
        length, gc = calc_sequence_stats(seq)
        lengths.append(length)
        total_gc += gc
        total_len += length
        count += 1
    
    if count == 0:
        console.print("[red]文件中没有序列[/red]")
        raise typer.Exit(code=1)  # 错误路径应非零退出

    lengths.sort(reverse=True)
    n50 = _calc_n50(lengths, total_len)
    # 用 Rich Table 输出
    table = Table(title=f"{file} 统计摘要")
    table.add_column("指标", style="bold cyan")
    table.add_column("值", style="green")

    table.add_row("序列条数", str(count))
    table.add_row("总长度 (bp)", f"{total_len:,}")
    table.add_row("最短序列", f"{lengths[-1]:,}")
    table.add_row("最长序列", f"{lengths[0]:,}")
    table.add_row("平均长度", f"{total_len // count:,}")
    table.add_row("N50", f"{n50:,}")
    table.add_row("GC 含量", f"{total_gc / total_len:.2%}" if total_len else "N/A")

    console.print(table)

@app.command()
def head(
    file: Path = typer.Argument(help="FASTA 文件路径"),
    n: int = typer.Option(10, "-n", "--num", help="显示前 N 条序列"),
    wrap: int = typer.Option(60, min=1, help="序列每行换行宽度"),
):
    """查看 FASTA 文件的前 N 条序列。"""
    _check_file(file)
    count = 0
    for header, seq in parse_fasta(str(file)):
        if count >= n:
            break
        
        seqtype = detect_seq_type(seq)
        type_label = "DNA" if seqtype == SeqType.DNA else "Protein" if seqtype == SeqType.PROTEIN else "Unknown"
        console.print(
            f"[bold cyan]> {header}[/bold cyan] "
            f"[dim]\\[{type_label}] {len(seq)}bp[/dim]"
        )
        # 按 chunk 着色，避免整条 span explosion
        for chunk_start in range(0, len(seq), wrap):
            chunk_end = min(chunk_start + wrap, len(seq))
            ruler = position_ruler(chunk_start + 1, chunk_end - chunk_start)
            console.print("  ", end="")
            console.print(ruler)
            console.print("  ", end="")
            console.print(colorize_sequence(seq[chunk_start:chunk_end], seq_type=seqtype))
        console.print()
        count += 1
    
    if count == 0:
        console.print("[red]文件中没有序列[/red]")
        raise typer.Exit(code=1)  # 错误路径应非零退出
    
    console.print(f"[dim]共显示 {count} 条序列[/dim]")

@app.command()
def fqview(
    file: Path = typer.Argument(help="FASTQ 文件路径"),
    n: int = typer.Option(0, "-n", "--num", help="只显示前 N 条 (0=全部)"),
    wrap: int = typer.Option(60, min=1, help="序列每行换行宽度"),
):
    """美化查看 FASTQ 文件（序列 + 质量值对齐着色）"""
    _check_file(file)
    count = 0
    try:
        for header, seq, quality in parse_fastq(str(file)):
            if n > 0 and count >= n:
                break

            count += 1
            seqtype = detect_seq_type(seq)
            qstats = quality_stats(quality)

            # ── header 行：名称 + 类型 + 长度 + 平均质量 ──
            type_label = "DNA" if seqtype == SeqType.DNA else "Protein" if seqtype == SeqType.PROTEIN else "Unknown"
            console.print(
                f"[bold cyan]▶ Read {count}[/bold cyan] "
                f"[white]{header}[/white] "
                f"[dim]\\[{type_label}] {len(seq)}bp "
                f"Q={qstats['mean']:.1f} "
                f"Q30={qstats['q30_pct']:.0%}[/dim]"
            )

            # ── 质量分布条 ──
            bar = quality_bar(quality, width=wrap)
            console.print("[dim]Q: [/dim]", end="")
            console.print(bar)

            # ── 序列 + 质量值逐行对齐显示（按 chunk 着色） ──
            for chunk_start in range(0, len(seq), wrap):
                chunk_end = min(chunk_start + wrap, len(seq))

                # 位置标尺
                ruler = position_ruler(chunk_start + 1, chunk_end - chunk_start)
                console.print("  ", end="")
                console.print(ruler)

                # 序列行（按 chunk 着色）
                console.print("  ", end="")
                console.print(colorize_sequence(seq[chunk_start:chunk_end], seq_type=seqtype))

                # 质量行（与序列等宽对齐）
                console.print("  ", end="")
                console.print(colorize_quality(quality[chunk_start:chunk_end]))

                console.print()  # chunk 间小间距

            console.print()  # read 间空行
    except ValueError as e:
        # 畸形 FASTQ（非 '@' 开头记录等）：友好报错而非裸 traceback
        console.print(f"[red]错误: {e}[/red]")
        raise typer.Exit(code=1) from None
    
    if count == 0:
        console.print("[red]文件中没有序列[/red]")
        raise typer.Exit(code=1)  # 错误路径应非零退出
    
    console.print(f"[dim]共显示 {count} 条 reads[/dim]")


@app.command()
def browse(
    files: list[Path] = typer.Argument(help="FASTA/FASTQ 文件或目录路径（目录会启动文件选择器）"),
):
    """交互式浏览 FASTA/FASTQ/VCF 文件（支持多文件标签页、目录浏览）。"""
    for p in files:  # 校验路径存在，与其他子命令的友好报错保持一致
        if not p.exists():
            console.print(f"[red]错误: 路径不存在: {p}[/red]")
            raise typer.Exit(code=1)
    _launch_browser(list(files))


@app.command()
def config(
    init: bool = typer.Option(False, "--init", help="生成默认配置文件模板 (config.json + theme.json)"),
):
    """查看当前生效的配置与主题（--init 生成配置文件模板）。"""
    import json

    if init:
        config_mod.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 生成 config.json
        if config_mod.CONFIG_FILE.exists():
            console.print(f"[yellow]配置文件已存在: {config_mod.CONFIG_FILE}[/yellow]")
        else:
            with open(config_mod.CONFIG_FILE, "w") as f:
                json.dump(config_mod.DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
            console.print(f"[green]已生成默认配置: {config_mod.CONFIG_FILE}[/green]")
        # 生成 theme.json（仅输出注释性模板，不写入完整主题，
        # 避免覆盖所有内置主题导致 config.json 的 theme 切换失效）
        if theme_mod.THEME_FILE.exists():
            console.print(f"[yellow]主题文件已存在: {theme_mod.THEME_FILE}[/yellow]")
        else:
            theme_template = {
                "_comment": (
                    "在此覆盖界面主题字段（对 config.json 中 theme 指定的内置主题生效）。"
                    "可用字段: background/foreground/border/accent/panel/muted/highlight/gutter。"
                    "仅写入想覆盖的字段，其余保持内置值；以 _ 开头的键为注释会被忽略。"
                    "切换主题请修改 config.json 的 \"theme\" 字段。"
                ),
                "_available_themes": theme_mod.list_themes(),
            }
            with open(theme_mod.THEME_FILE, "w") as f:
                json.dump(theme_template, f, indent=2, ensure_ascii=False)
            console.print(f"[green]已生成主题模板: {theme_mod.THEME_FILE}[/green]")
        console.print("[dim]编辑 config.json 自定义行为/序列配色/后缀；编辑 theme.json 自定义界面主题。[/dim]")
        console.print(f"[dim]可用内置主题:[/dim] {', '.join(theme_mod.list_themes())}")
        console.print("[dim]在 config.json 中设置 \"theme\": \"nord\" 即可切换[/dim]")
        raise typer.Exit()

    # 显示配置文件路径与生效配置
    cfg_path = config_mod.CONFIG_FILE
    exists = cfg_path.exists()
    console.print(f"[dim]配置文件:[/dim] {cfg_path} "
                  f"[green](已加载)[/green]" if exists else f"[dim]配置文件:[/dim] {cfg_path} [yellow](不存在，使用默认值)[/yellow]")
    console.print()
    console.print_json(json.dumps(config_mod.get_config(), ensure_ascii=False))
    console.print()
    # 显示主题
    th_path = theme_mod.THEME_FILE
    th_exists = th_path.exists()
    console.print(f"[dim]主题文件:[/dim] {th_path} "
                  f"[green](已加载)[/green]" if th_exists else f"[dim]主题文件:[/dim] {th_path} [yellow](不存在，使用默认值)[/yellow]")
    console.print()
    console.print_json(json.dumps(theme_mod.get_theme(), ensure_ascii=False))
    console.print()
    # 显示可用内置主题
    current = config_mod.get("theme", "dark")
    themes = theme_mod.list_themes()
    theme_list = "  ".join(
        f"[bold green]● {t}[/bold green]" if t == current else f"[dim]○ {t}[/dim]"
        for t in themes
    )
    console.print(f"[dim]可用主题:[/dim] {theme_list}")
    console.print(f"[dim]在 config.json 中设置 \"theme\": \"{themes[0]}\" 切换主题[/dim]")


def _calc_n50(sorted_lengths: list[int], total_len: int) -> int:
    """计算 N50：累计长度达到总长 50% 时对应的序列长度。"""
    half = total_len / 2
    cumsum = 0
    for length in sorted_lengths:
        cumsum += length
        if cumsum >= half:
            return length
    return 0