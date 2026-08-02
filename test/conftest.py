"""pytest conftest：动态生成测试数据文件。

测试数据文件（*.fa / *.fastq 等）被 .gitignore 忽略、不随仓库提交，
以保证 clean clone 体积最小。本 conftest 在测试会话开始前自动生成
所需的 fixture（若本地已存在同名文件则跳过，不覆盖用户数据）。

这样既保留了「数据文件不入库」的约定，又让 `uv run pytest` 在
全新克隆的环境里可以直接通过，无需手动准备测试数据。
"""
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).parent

# run_perf_test.py 是需要外部生成 GB 级数据的手动基准脚本（配合 gen_perf_data.py），
# 不属于常规 pytest 套件，排除收集。
collect_ignore = ["run_perf_test.py"]

# ── fixture 内容定义 ──────────────────────────────────────────

# test.fa：2 条 DNA 序列（chr1 为多行拼接共 20bp，chr2 为 12bp）
TEST_FA_CONTENT = (
    ">chr1 Homo sapiens chromosome 1\n"
    "ATCGATCGATCG\n"
    "NNNNNNNN\n"
    ">chr2\n"
    "GGGGAAAACCCC\n"
)

# test_protein.fa：2 条蛋白质序列（含 E/F/I/L/P/Q 等蛋白质特征氨基酸）
TEST_PROTEIN_CONTENT = (
    ">sp|P01308|INSU_HUMAN Insulin OS=Homo sapiens\n"
    "MALWMRLLPLLALLALWGPDPAAAFVNQHLCGSHLVEALYLVCGERGFFYTPKT\n"
    ">sp|P68871|HBB_HUMAN Hemoglobin subunit beta OS=Homo sapiens\n"
    "MVHLTPEEKSAVTALWGKVNVDEVGGEALGRLLVVYPWTQRFFESFGDLSTADAVMGNPKVKAHGKKVLGA\n"
)


def _build_fastq() -> str:
    """构造 3 条带质量值的 FASTQ reads。"""
    reads = [
        ("E150019865L1C001R00300001617/1", "TCTCAGCTCTGGTTCTGGTTCCGTACAGACTTTAGAGGACATGCAGAACATCTCTGCATTCAACTCATCC"),
        ("E150019865L1C001R00300002549/1", "CCCGGCTTGAGTCCAGATTTAACTTAGTCTGGCTCCAAAAATAAACTTCAATCAAAAAATTGAAAAAAGG"),
        ("E150019865L1C001R00300003311/1", "ATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCG"),
    ]
    lines = []
    for header, seq in reads:
        qual = "I" * len(seq)  # 高质量 Q40
        lines.append(f"@{header}\n{seq}\n+\n{qual}\n")
    return "".join(lines)


def _build_chr2() -> str:
    """构造一条约 5.6Kbp 的 DNA 序列（70bp 换行），供滚动测试使用。"""
    unit = "ATGGACGACTGGGTGGAAGAGGTAGGCAGGTTTTCAGTGGGTTATCCAGGTGTTTTTTGGTGTTTTTCCA"
    seq = (unit * 80)[:5600]
    lines = [">chr2"]
    for i in range(0, len(seq), 70):
        lines.append(seq[i:i + 70])
    return "\n".join(lines) + "\n"


def _ensure_fixtures() -> None:
    """生成缺失的测试数据文件（已存在则跳过）。"""
    targets = {
        "test.fa": TEST_FA_CONTENT,
        "test_protein.fa": TEST_PROTEIN_CONTENT,
        "test_fastq.fastq": _build_fastq(),
        "chr2.fa": _build_chr2(),
    }
    for name, content in targets.items():
        path = TEST_DIR / name
        if not path.exists():
            path.write_text(content)


@pytest.fixture(scope="session", autouse=True)
def _test_fixtures():
    """会话级自动 fixture：确保测试数据文件存在。"""
    _ensure_fixtures()
    yield


@pytest.fixture(autouse=True)
def _reset_config_theme_singletons():
    """每个测试后重置 config/theme 单例，避免缓存泄漏造成顺序敏感。"""
    yield
    from seqviz import config as config_mod
    from seqviz import theme as theme_mod
    config_mod._config = None
    theme_mod._theme = None
