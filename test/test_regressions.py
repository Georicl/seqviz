"""回归测试：覆盖 v0.6.x 修复的正确性缺陷（Issue #1/#3/#4 复核意见）。

包括：
- CRLF / UTF-8 header / FASTQ 的二进制 offset 正确性（Issue #3）
- 大序列分块加载的长度与内容正确性（Issue #1）
- 可变行宽 / 含空行 FASTA 的 _load_chunk 正确性（Issue #1 复核）
- 长度缓存回写（Issue #1 复核小点）
- 后台扫描不重复追加、点选映射正确（Issue #4 复核回退）
- >1Mbp 大序列首/中/末窗口内容断言（Issue #4 复核 benchmark gate）
"""
import asyncio
import random
from pathlib import Path

from seqviz.browser import FastaBrowser, FileFormat, SequenceView

random.seed(2026)


def run(coro):
    return asyncio.run(coro)


def _view(path: Path, fmt: FileFormat) -> tuple[SequenceView, list]:
    """构建 SequenceView 并屏蔽显示刷新，返回 (view, records)。"""
    recs = FastaBrowser._scan_file(path, fmt)
    v = SequenceView(path, fmt)
    v._update_display = lambda: None
    return v, recs


# ──────────────────────────────────────────────
# Issue #3：CRLF / UTF-8 header 的 offset 正确性
# ──────────────────────────────────────────────
class TestCrlfOffsets:
    def test_crlf_fasta_offsets(self, tmp_path):
        p = tmp_path / "crlf.fa"
        p.write_bytes(b">one\r\nAAAA\r\n>two\r\nCCCC\r\n")
        recs = FastaBrowser._scan_file(p, FileFormat.FASTA)
        assert [r.offset for r in recs] == [0, 12]  # 每个 offset 落在 '>' 字节上

        v, _ = _view(p, FileFormat.FASTA)
        v.load_sequence(recs[1])
        assert v._seq == "CCCC"
        assert v._seq_length == 4

    def test_crlf_utf8_header(self, tmp_path):
        p = tmp_path / "utf8.fa"
        p.write_bytes(">序列一 描述\r\nATCG\r\n>序列二\r\nGGGGTTTT\r\n".encode())
        recs = FastaBrowser._scan_file(p, FileFormat.FASTA)
        # offset 必须落在每个 '>' 的字节位置
        raw = p.read_bytes()
        assert all(raw[r.offset:r.offset + 1] == b">" for r in recs)
        assert recs[0].header == "序列一 描述"
        assert recs[1].header == "序列二"

        v, _ = _view(p, FileFormat.FASTA)
        v.load_sequence(recs[1])
        assert v._seq == "GGGGTTTT"

    def test_crlf_fastq_offsets(self, tmp_path):
        p = tmp_path / "crlf.fastq"
        p.write_bytes(b"@r1\r\nAAAA\r\n+\r\nIIII\r\n@r2\r\nTTTT\r\n+\r\nJJJJ\r\n")
        recs = FastaBrowser._scan_file(p, FileFormat.FASTQ)
        assert [r.offset for r in recs] == [0, 20]

        v, _ = _view(p, FileFormat.FASTQ)
        v.load_sequence(recs[1])
        assert v._seq == "TTTT"
        assert v._quality == "JJJJ"

    def test_lf_crlf_equivalent(self, tmp_path):
        """LF 与 CRLF 同内容文件应解析出相同的记录与序列。"""
        lf = tmp_path / "lf.fa"
        crlf = tmp_path / "crlf.fa"
        lf.write_bytes(b">a\nATCG\n>b\nGGCC\n")
        crlf.write_bytes(b">a\r\nATCG\r\n>b\r\nGGCC\r\n")
        recs_lf = FastaBrowser._scan_file(lf, FileFormat.FASTA)
        recs_crlf = FastaBrowser._scan_file(crlf, FileFormat.FASTA)
        assert [r.header for r in recs_lf] == [r.header for r in recs_crlf]

        for path, recs in ((lf, recs_lf), (crlf, recs_crlf)):
            v, _ = _view(path, FileFormat.FASTA)
            v.load_sequence(recs[1])
            assert v._seq == "GGCC"


# ──────────────────────────────────────────────
# Issue #1：大序列分块加载正确性 + 可变行宽
# ──────────────────────────────────────────────
class TestLargeSeqChunking:
    def test_large_fasta_length_and_content(self, tmp_path):
        """>1Mbp 固定行宽：长度准确，首/中/末窗口内容正确。"""
        seq = "".join(random.choices("ATCG", k=1_200_000))
        p = tmp_path / "large.fa"
        with p.open("w") as f:
            f.write(">large\n")
            for i in range(0, len(seq), 70):
                f.write(seq[i:i + 70] + "\n")

        v, recs = _view(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert v._is_large
        assert v._seq_length == len(seq)
        # 首 / 中 / 末 / 随机窗口抽查
        for start in (0, len(seq) // 2, len(seq) - 600, random.randint(0, len(seq) - 600)):
            assert v._load_chunk(start, start + 600) == seq[start:start + 600]

    def test_variable_line_width(self, tmp_path):
        """可变行宽（70/60/50 交替）：长度准确，_load_chunk 不错位。"""
        seq = "ATCGGCTA" * 150_000  # 1,200,000 bp
        p = tmp_path / "varwidth.fa"
        with p.open("w") as f:
            f.write(">varwidth\n")
            i = k = 0
            while i < len(seq):
                w = (70, 60, 50)[k % 3]
                f.write(seq[i:i + w] + "\n")
                i += w
                k += 1

        v, recs = _view(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert v._seq_length == len(seq)
        assert v._uniform_lines is False  # 检测到非等宽
        for start in (0, 1000, 600_000, len(seq) - 60):
            assert v._load_chunk(start, start + 60) == seq[start:start + 60]

    def test_blank_lines_in_record(self, tmp_path):
        """记录内部含空行：长度准确（空行不计），_load_chunk 不错位。"""
        seq = "".join(random.choices("ATCG", k=1_100_000))
        p = tmp_path / "blank.fa"
        with p.open("w") as f:
            f.write(">blank\n")
            for idx, i in enumerate(range(0, len(seq), 70)):
                f.write(seq[i:i + 70] + "\n")
                if idx % 100 == 99:
                    f.write("\n")  # 每 100 行插一个空行

        v, recs = _view(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert v._seq_length == len(seq)
        assert v._uniform_lines is False
        for start in (0, 600_000, len(seq) - 100):
            assert v._load_chunk(start, start + 60) == seq[start:start + 60]

    def test_length_cached_after_load(self, tmp_path):
        """加载后长度与行宽指标应回写 SequenceInfo，二次加载走缓存。"""
        seq = "ATCGATCG" * 250_000  # 2,000,000 bp
        p = tmp_path / "cache.fa"
        with p.open("w") as f:
            f.write(">big\n")
            for i in range(0, len(seq), 70):
                f.write(seq[i:i + 70] + "\n")

        v, recs = _view(p, FileFormat.FASTA)
        assert recs[0].length == -1  # 扫描时不计算长度
        v.load_sequence(recs[0])
        assert recs[0].length == len(seq)  # 已回写
        assert recs[0].uniform is True
        assert recs[0].chars_per_line == 70
        # 二次加载仍正确
        v.load_sequence(recs[0])
        assert v._seq_length == len(seq)
        assert v._load_chunk(123_456, 123_516) == seq[123_456:123_516]

    def test_last_line_longer_than_width(self, tmp_path):
        """末行比首行更长：必须判非等宽走 checkpoint 回退，否则尾部静默错位。"""
        seq = "".join(random.choices("ATCG", k=1_200_040))
        p = tmp_path / "longtail.fa"
        with p.open("w") as f:
            f.write(">longtail\n")
            # 前 19999 行每行 60bp（共 1,199,940），末行 100bp > 60bp
            for i in range(0, 1_199_940, 60):
                f.write(seq[i:i + 60] + "\n")
            f.write(seq[1_199_940:] + "\n")

        v, recs = _view(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert v._is_large
        assert v._seq_length == len(seq)
        assert v._uniform_lines is False  # 修复前误判为 True，尾部内容错位
        for start in (0, 600_000, 1_199_940, 1_200_000, len(seq) - 600):
            end = min(start + 600, len(seq))
            assert v._load_chunk(start, end) == seq[start:end]

    def test_leading_whitespace_not_uniform(self, tmp_path):
        """每行行首统一缩进空白：必须判非等宽，否则等宽换算整条错位。"""
        seq = "".join(random.choices("ATCG", k=1_200_000))
        p = tmp_path / "indent.fa"
        with p.open("w") as f:
            f.write(">indent\n")
            for i in range(0, len(seq), 60):
                f.write("  " + seq[i:i + 60] + "\n")

        v, recs = _view(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert v._is_large
        assert v._seq_length == len(seq)
        assert v._uniform_lines is False  # 修复前误判为 True，内容错位
        for start in (0, 1000, 600_000, len(seq) - 100):
            assert v._load_chunk(start, start + 100) == seq[start:start + 100]

    def test_nonuniform_checkpoints_cached(self, tmp_path):
        """非等宽序列二次加载应复用缓存的 checkpoint，内容仍正确。"""
        seq = "ATCGGCTA" * 150_000  # 1,200,000 bp，行宽 70/60/50 交替
        p = tmp_path / "varwidth_cache.fa"
        with p.open("w") as f:
            f.write(">v\n")
            i = k = 0
            while i < len(seq):
                w = (70, 60, 50)[k % 3]
                f.write(seq[i:i + w] + "\n")
                i += w
                k += 1

        v, recs = _view(p, FileFormat.FASTA)
        v.load_sequence(recs[0])
        assert recs[0].uniform is False
        assert recs[0].checkpoints is not None  # checkpoint 已缓存
        first_cps = recs[0].checkpoints
        # 二次加载：复用缓存的 checkpoint，内容仍正确
        v.load_sequence(recs[0])
        assert v._checkpoints is first_cps
        assert v._uniform_lines is False
        for start in (0, 600_000, len(seq) - 60):
            assert v._load_chunk(start, start + 60) == seq[start:start + 60]


# ──────────────────────────────────────────────
# Issue #4：后台扫描不重复追加、点选映射正确
# ──────────────────────────────────────────────
class TestBackgroundScanNoDuplicates:
    def test_no_duplicate_append(self, tmp_path):
        """>QUICK_LIMIT 的文件触发后台续扫，记录不应重复、点选映射正确。"""
        n = 1500
        p = tmp_path / "many.fa"
        with p.open("w") as f:
            for i in range(n):
                f.write(f">rec_{i}\nACGT\n")

        async def _t():
            app = FastaBrowser([p])
            tab = app.file_tabs[0]
            async with app.run_test(size=(100, 30)) as pilot:
                from seqviz.browser import SequenceList
                sidebar = app.query_one("#sidebar-0", SequenceList)
                # 等待后台扫描完成
                for _ in range(300):
                    await pilot.pause()
                    if not app._scan_tasks and len(tab.sequences) >= n:
                        break
                assert len(tab.sequences) == n  # 修复前会膨胀到 ~2500
                assert sidebar.option_count == n
                # 抽查点选映射：侧栏第 i 项应加载 rec_i
                for i in random.sample(range(n), 16):
                    opt = sidebar.get_option_at_index(i)
                    assert tab.sequences[int(opt.id[4:])].header == f"rec_{i}"
            app.exit()

        run(_t())


# ──────────────────────────────────────────────
# 复制守卫 & 后台扫描取消
# ──────────────────────────────────────────────
class TestCopyGuardAndScanCancel:
    def test_copy_seq_guard_large(self, tmp_path, monkeypatch):
        """>10Mbp 大序列按 y 应拒绝复制并提示，不进入剪贴板。"""
        seq = "".join(random.choices("ATCG", k=10_000_001))
        p = tmp_path / "big.fa"
        with p.open("w") as f:
            f.write(">big\n")
            for i in range(0, len(seq), 70):
                f.write(seq[i:i + 70] + "\n")

        copied: list[str] = []

        async def _t():
            monkeypatch.setattr(
                FastaBrowser, "_copy_to_clipboard", lambda self, text: copied.append(text) or True
            )
            app = FastaBrowser([p])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("y")  # 复制当前序列
                await pilot.pause()
            app.exit()

        run(_t())
        assert copied == []  # 守卫生效，未进入剪贴板

    def test_scan_cancelled_stops_background_scan(self, tmp_path):
        """on_unmount 置取消标志后，后台扫描应尽早退出且不再回 UI 线程。"""
        n = 1500
        p = tmp_path / "many2.fa"
        with p.open("w") as f:
            for i in range(n):
                f.write(f">rec_{i}\nACGT\n")

        async def _t():
            app = FastaBrowser([p])
            app.run_worker = lambda *a, **k: None  # type: ignore[method-assign]  # 阻止真实后台线程，消除竞态
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert app._scan_tasks  # 有待扫描任务
                app.on_unmount()  # 模拟退出
                assert app._scan_cancelled is True
                calls: list = []
                app.call_from_thread = lambda *a, **k: calls.append(a) or None  # type: ignore[method-assign]
                app._background_scan()
                assert calls == []  # 取消后不再投递 UI 更新
                app.exit()

        run(_t())


# ──────────────────────────────────────────────
# Issue #4：导出流式且内容正确
# ──────────────────────────────────────────────
class TestExportCorrectness:
    def test_export_large_sequence_content(self, tmp_path, monkeypatch):
        """大序列导出内容应与原序列一致（流式写入不损坏数据）。"""
        seq = "".join(random.choices("ATCG", k=1_100_000))
        p = tmp_path / "exp.fa"
        with p.open("w") as f:
            f.write(">expseq\n")
            for i in range(0, len(seq), 70):
                f.write(seq[i:i + 70] + "\n")

        out_dir = tmp_path / "out"
        out_dir.mkdir()

        async def _t():
            monkeypatch.chdir(out_dir)
            app = FastaBrowser([p])
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("e")  # 导出当前序列
                await pilot.pause()
            app.exit()

        run(_t())
        exported = list(out_dir.glob("*.fasta"))
        assert len(exported) == 1
        # 还原序列并与原序列比对
        lines = exported[0].read_text().splitlines()
        assert lines[0] == ">expseq"
        rebuilt = "".join(lines[1:])
        assert rebuilt == seq
