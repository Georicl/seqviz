import typer
from pathlib import Path
from rich.console import Console
from fasta_fmt.parsers import parse_fasta
from fasta_fmt.stats import calc_sequence_stats
from fasta_fmt.seq_type import SeqType, detect_seq_type
from fasta_fmt.fastq import parse_fastq
from fasta_fmt.browser import FastaBrowser
from fasta_fmt.file_browser import run_file_browser, scan_directory, is_sequence_file
from fasta_fmt.renderer import colorize_sequence, colorize_quality, quality_stats, quality_bar, position_ruler
from rich.table import Table

app = typer.Typer()
console = Console()


def _launch_browser(paths: list[Path]):
    """根据路径启动浏览器：目录走文件选择器，文件直接打开。"""
    # 单个目录 → 启动文件选择器
    if len(paths) == 1 and paths[0].is_dir():
        selected = run_file_browser(paths[0])
        if not selected:
            console.print("[dim]未选择任何文件[/dim]")
            raise typer.Exit()
        paths = selected
    else:
        # 混合输入：展开其中的目录为序列文件
        expanded: list[Path] = []
        for p in paths:
            if p.is_dir():
                expanded.extend(info.path for info in scan_directory(p))
            else:
                expanded.append(p)
        paths = expanded

    if not paths:
        console.print("[red]没有找到可打开的序列文件[/red]")
        raise typer.Exit()

    FastaBrowser(paths).run()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """fasta-fmt — 生物序列终端美化工具。

    不带任何命令时，默认打开当前目录的文件浏览器。
    """
    if ctx.invoked_subcommand is None:
        _launch_browser([Path(".")])


@app.command()
def view(
    file: str = typer.Argument(help="FASTA 文件路径"),
    wrap: int = typer.Option(60, help="序列每行换行宽度"),
):
    """美化查看 FASTA 文件"""
    for header, seq in parse_fasta(file):
        seqtype = detect_seq_type(seq)
        type_label = "DNA" if seqtype == SeqType.DNA else "Protein" if seqtype == SeqType.PROTEIN else "Unknown"

        # header + 类型标签 + 长度
        console.print(
            f"[bold cyan]> {header}[/bold cyan] "
            f"[dim]\\[{type_label}] {len(seq)}bp[/dim]"
        )
        
        # 按 wrap 宽度切分，逐行显示标尺 + 序列
        colored = colorize_sequence(seq, seq_type=seqtype)
        for chunk_start in range(0, len(seq), wrap):
            chunk_end = min(chunk_start + wrap, len(seq))
            ruler = position_ruler(chunk_start + 1, chunk_end - chunk_start)
            console.print(f"  ", end="")
            console.print(ruler)
            console.print(f"  ", end="")
            console.print(colored[chunk_start:chunk_end])
        
        console.print()  # 序列间空行

@app.command()
def stats(
    file: str = typer.Argument(help="FASTA 文件路径")
):
    """统计 FASTA 文件特征"""
    lengths: list[int] = []
    total_gc = 0
    total_len = 0
    count = 0

    for header, seq in parse_fasta(file):
        length, gc = calc_sequence_stats(seq)
        lengths.append(length)
        total_gc += gc
        total_len += length
        count += 1
    
    if count == 0:
        console.print("[red]文件中没有序列[/red]")
        raise typer.Exit()

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
    file: str = typer.Argument(help="FASTA 文件路径"),
    n: int = typer.Option(10, "-n", "--num", help="显示前 N 条序列"),
    wrap: int = typer.Option(60, help="序列每行换行宽度"),
):
    """查看 FASTA 文件的前 N 条序列。"""
    count = 0
    for header, seq in parse_fasta(file):
        if count >= n:
            break
        
        seqtype = detect_seq_type(seq)
        type_label = "DNA" if seqtype == SeqType.DNA else "Protein" if seqtype == SeqType.PROTEIN else "Unknown"
        console.print(
            f"[bold cyan]> {header}[/bold cyan] "
            f"[dim]\\[{type_label}] {len(seq)}bp[/dim]"
        )
        colored = colorize_sequence(seq, seq_type=seqtype)
        for chunk_start in range(0, len(seq), wrap):
            chunk_end = min(chunk_start + wrap, len(seq))
            ruler = position_ruler(chunk_start + 1, chunk_end - chunk_start)
            console.print(f"  ", end="")
            console.print(ruler)
            console.print(f"  ", end="")
            console.print(colored[chunk_start:chunk_end])
        console.print()
        count += 1
    
    if count == 0:
        console.print("[red]文件中没有序列[/red]")
        raise typer.Exit()
    
    console.print(f"[dim]共显示 {count} 条序列[/dim]")

@app.command()
def fqview(
    file: str = typer.Argument(help="FASTQ 文件路径"),
    n: int = typer.Option(0, "-n", "--num", help="只显示前 N 条 (0=全部)"),
    wrap: int = typer.Option(60, help="序列每行换行宽度"),
):
    """美化查看 FASTQ 文件（序列 + 质量值对齐着色）"""
    count = 0
    for header, seq, quality in parse_fastq(file):
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
        console.print(f"[dim]Q: [/dim]", end="")
        console.print(bar)
        
        # ── 序列 + 质量值逐行对齐显示 ──
        colored_seq = colorize_sequence(seq, seq_type=seqtype)
        colored_qual = colorize_quality(quality)
        
        for chunk_start in range(0, len(seq), wrap):
            chunk_end = min(chunk_start + wrap, len(seq))
            
            # 位置标尺
            ruler = position_ruler(chunk_start + 1, chunk_end - chunk_start)
            console.print(f"  ", end="")
            console.print(ruler)
            
            # 序列行
            seq_slice = colored_seq[chunk_start:chunk_end]
            console.print(f"  ", end="")
            console.print(seq_slice)
            
            # 质量行（与序列等宽对齐）
            qual_slice = colored_qual[chunk_start:chunk_end]
            console.print(f"  ", end="")
            console.print(qual_slice)
            
            console.print()  # chunk 间小间距
        
        console.print()  # read 间空行
    
    if count == 0:
        console.print("[red]文件中没有序列[/red]")
        raise typer.Exit()
    
    console.print(f"[dim]共显示 {count} 条 reads[/dim]")


@app.command()
def browse(
    files: list[str] = typer.Argument(help="FASTA/FASTQ 文件或目录路径（目录会启动文件选择器）"),
):
    """交互式浏览 FASTA/FASTQ 文件（支持多文件标签页、目录浏览）。"""
    _launch_browser([Path(f) for f in files])


def _calc_n50(sorted_lengths: list[int], total_len: int) -> int:
    """计算 N50：累计长度达到总长 50% 时对应的序列长度。"""
    half = total_len / 2
    cumsum = 0
    for length in sorted_lengths:
        cumsum += length
        if cumsum >= half:
            return length
    return 0