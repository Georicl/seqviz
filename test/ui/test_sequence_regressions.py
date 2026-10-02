"""后台扫描、序列选择与导出交互。"""

import asyncio
import io
import random
from pathlib import Path

import seqviz.core.index as index_module
from seqviz.core.formats import FileFormat
from seqviz.core.index import scan_file
from seqviz.core.sequence_reader import SequenceReader
from seqviz.ui.sequence.app import FastaBrowser

random.seed(2026)


def run(coro):
    return asyncio.run(coro)


def _reader(path: Path, fmt: FileFormat) -> tuple[SequenceReader, list]:
    """直接测试读取器，不启动 Textual。"""
    recs = scan_file(path, fmt)
    v = SequenceReader(path, fmt)
    return v, recs


# ──────────────────────────────────────────────
# Issue #3：CRLF / UTF-8 header 的 offset 正确性
# ──────────────────────────────────────────────
class TestBackgroundScanNoDuplicates:
    def test_cancel_while_reading_a_long_skipped_header(self, tmp_path, monkeypatch):
        class CountedReader(io.BytesIO):
            read_count = 0

            def readline(self, *args):
                self.read_count += 1
                return super().readline(*args)

        reader = CountedReader(b">" + b"x" * 2_000_000 + b"\nACGT\n")
        monkeypatch.setattr(index_module, "open_seq_file", lambda *args: reader)
        records = list(
            index_module.iter_sequences(
                tmp_path / "unused.fa",
                FileFormat.FASTA,
                start_idx=1,
                cancelled=lambda: reader.read_count == 3,
            )
        )
        assert records == []
        assert reader.read_count == 3
        assert reader.closed

    def test_cancel_within_one_long_sequence(self, tmp_path, monkeypatch):
        """已索引过的长记录没有下一个 header，也应在块读取之间取消。"""
        p = tmp_path / "long.fa"
        p.write_bytes(b">chr1\n" + b"A" * 2_000_000 + b"\n")
        app = FastaBrowser([p])
        original_open = index_module.open_seq_file
        read_sizes = []

        class CancelReader:
            def __enter__(self):
                self.f = original_open(p)
                return self

            def __exit__(self, *args):
                self.f.close()

            def readline(self, *args):
                raw = self.f.readline(*args)
                read_sizes.append(len(raw))
                if len(read_sizes) == 3:
                    app._scan_cancelled = True
                return raw

        monkeypatch.setattr(index_module, "open_seq_file", lambda *args: CancelReader())
        app._background_scan()
        assert len(read_sizes) == 3
        assert max(read_sizes) <= index_module.FASTA_READ_BLOCK

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
                from seqviz.ui.sequence.widgets import SequenceList

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


class TestCopyGuardAndScanCancel:
    def test_copy_seq_guard_large(self, tmp_path, monkeypatch):
        """>10Mbp 大序列按 y 应拒绝复制并提示，不进入剪贴板。"""
        seq = "".join(random.choices("ATCG", k=10_000_001))
        p = tmp_path / "big.fa"
        with p.open("w") as f:
            f.write(">big\n")
            for i in range(0, len(seq), 70):
                f.write(seq[i : i + 70] + "\n")

        copied: list[str] = []

        async def _t():
            monkeypatch.setattr(
                FastaBrowser,
                "_copy_to_clipboard",
                lambda self, text: copied.append(text) or True,
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


class TestExportCorrectness:
    def test_export_large_sequence_content(self, tmp_path, monkeypatch):
        """大序列导出内容应与原序列一致（流式写入不损坏数据）。"""
        seq = "".join(random.choices("ATCG", k=1_100_000))
        p = tmp_path / "exp.fa"
        with p.open("w") as f:
            f.write(">expseq\n")
            for i in range(0, len(seq), 70):
                f.write(seq[i : i + 70] + "\n")

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
