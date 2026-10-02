"""与界面无关的序列读取器：索引指标、区间读取与有界窗口缓存。"""

from collections.abc import Callable
from pathlib import Path
from typing import IO

from seqviz.core.formats import FileFormat, open_seq_file
from seqviz.core.index import FASTA_READ_BLOCK, SequenceInfo
from seqviz.core.seq_type import SeqType, detect_seq_type


class SequenceReader:
    """持有一个文件句柄和当前记录，调用方负责在使用结束时 close。"""

    LARGE_SEQ_THRESHOLD = 1_000_000
    CHECKPOINT_INTERVAL = 1_000_000

    def __init__(self, filepath: Path, file_format: FileFormat = FileFormat.FASTA):
        self.filepath = filepath
        self.file_format = file_format
        self.current_seq: SequenceInfo | None = None
        self.sequence = ""
        self.quality = ""
        self.seq_type = SeqType.DNA
        self.length = 0
        self.is_large = False
        self.metrics_pending = False
        self.seq_data_offset = 0
        self._uniform_lines = True
        self._chars_per_line = 0
        self._file_line_width = 0
        self._checkpoints: list[tuple[int, int]] | None = None
        self._chunk_start = 0
        self._chunk_seq = ""
        self._window_size = 0
        self._fh: IO | None = None

    def set_window_size(self, base_count: int):
        """设置可缓存的碱基数；界面按一屏大小传入，批量导出不扩大缓存。"""
        if self._window_size != base_count:
            self._window_size = base_count
            self._chunk_seq = ""

    def _get_fh(self) -> IO:
        """获取持久文件句柄（懒初始化）。"""
        if self._fh is None or self._fh.closed:
            self._fh = open_seq_file(self.filepath, "rb")
        return self._fh

    def close(self):
        """关闭持久文件句柄。"""
        self._chunk_seq = ""
        if self._fh and not self._fh.closed:
            self._fh.close()
            self._fh = None

    def load_sequence(self, seq_info: SequenceInfo, defer_metrics: bool = False):
        """用 offset 直接 seek 到目标位置。大序列分块加载。

        未压缩文件为 O(1) 定位；gzip 文件无块索引，seek 需解压中间数据，
        随机跳转为 O(文件大小)，仅适合顺序浏览。
        """
        self.current_seq = seq_info
        self.quality = ""
        self.is_large = False
        self.metrics_pending = False
        self._chunk_seq = ""

        # ── 用 seek 直接跳到序列位置（二进制模式） ──
        f = self._get_fh()
        f.seek(seq_info.offset)

        if self.file_format == FileFormat.FASTQ:
            # FASTQ: 4 行一组 (@header / seq / + / quality)
            f.readline()  # 跳过 @header
            self.sequence = f.readline().strip().decode()
            f.readline()  # 跳过 +
            self.quality = f.readline().strip().decode()
            self.length = len(self.sequence)
        else:
            # FASTA: 二进制模式读取
            f.readline()  # 跳过 >header
            seq_data_start = f.tell()

            # 估算序列长度（-1 表示未知）
            est_length = seq_info.length if seq_info.length >= 0 else -1
            is_large = est_length > self.LARGE_SEQ_THRESHOLD

            # 读取序列：
            # - 已知大序列（缓存过长度）：只读 10K 样本用于类型检测，避免整条读入内存；
            # - 未知/小序列：读到阈值或 EOF，以判定是否为大序列（小序列需全量保留）。
            seq_parts: list[str] = []
            total_read = 0
            if is_large:
                while total_read < 10_000:
                    raw_line = f.readline(FASTA_READ_BLOCK)
                    if not raw_line or raw_line.startswith(b">"):
                        break
                    stripped = raw_line.strip().decode()
                    seq_parts.append(stripped)
                    total_read += len(stripped)
            else:
                while True:
                    raw_line = f.readline(FASTA_READ_BLOCK)
                    if not raw_line or raw_line.startswith(b">"):
                        break
                    stripped = raw_line.strip().decode()
                    seq_parts.append(stripped)
                    total_read += len(stripped)
                    if total_read > self.LARGE_SEQ_THRESHOLD:
                        is_large = True  # 首次发现超过阈值
                        break

            if is_large:
                # ── 大序列：分块加载模式 ──
                self.is_large = True
                self.seq_data_offset = seq_data_start
                # 获取分块指标（长度/行宽均匀性/行宽/checkpoint）：优先用缓存，否则扫描
                if est_length > 0 and seq_info.uniform is not None:
                    self.length = seq_info.length
                    self._uniform_lines = seq_info.uniform
                    self._chars_per_line = seq_info.chars_per_line
                    self._file_line_width = seq_info.file_line_width
                    self._checkpoints = seq_info.checkpoints
                elif defer_metrics:
                    # 首屏先显示已读取的前段；后台完成全长指标后再开放完整跳转/导出。
                    self.metrics_pending = True
                    self.length = total_read
                else:
                    f.seek(seq_data_start)
                    (
                        self.length,
                        self._uniform_lines,
                        self._chars_per_line,
                        self._file_line_width,
                        checkpoints,
                    ) = self.scan_fasta_metrics(f, seq_data_start)
                    # 非等宽行宽需要 checkpoint 索引才能正确定位
                    self._checkpoints = checkpoints if not self._uniform_lines else None
                    # 回写缓存，避免同一记录重复全量扫描
                    seq_info.length = self.length
                    seq_info.uniform = self._uniform_lines
                    seq_info.chars_per_line = self._chars_per_line
                    seq_info.file_line_width = self._file_line_width
                    seq_info.checkpoints = self._checkpoints
                # 指标待完成时保留已读前段用于首屏；完成后仅保留类型检测样本。
                self.sequence = "".join(seq_parts)
                if not self.metrics_pending:
                    self.sequence = self.sequence[:10000]
            else:
                # ── 普通序列：全量加载 ──
                self.sequence = "".join(seq_parts)
                self.length = len(self.sequence)

        self.seq_type = detect_seq_type(self.sequence[:10000])

    @staticmethod
    def scan_fasta_metrics(
        f: IO,
        seq_data_start: int,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, bool, int, int, list[tuple[int, int]]]:
        """一次遍历扫描 FASTA 记录，返回分块加载所需的全部指标。

        Returns:
            (length, uniform, chars_per_line, file_line_width, checkpoints)
            - length: 序列准确总长（碱基数）
            - uniform: 所有序列行（除可能的末行短尾外）是否行宽恒定
            - chars_per_line: 首行碱基数（uniform 时用于等宽换算）
            - file_line_width: 首行字节数（含换行符，uniform 时用于等宽换算）
            - checkpoints: [(碱基位置, 文件偏移)]，每 CHECKPOINT_INTERVAL 一个，
              供非等宽行宽记录快速定位（uniform 时不使用）。

        uniform 判定宽容“末行短尾”（FASTA 最后一行不足行宽是合法的），
        但不宽容中间行宽变化、空行、行首空白或末行长于首行——
        这些都会导致等宽 offset 换算错位。
        """
        length = 0
        first_chars = -1
        first_bytes = -1
        pending_mismatch = False  # 上一行与首行不同（可能只是末行短尾，待下一行确认）
        nonuniform = False
        checkpoints: list[tuple[int, int]] = []
        next_checkpoint = 0
        cur_offset = seq_data_start
        lines = 0
        while True:
            lines += 1
            if lines % 256 == 0 and cancelled is not None and cancelled():
                raise StopIteration
            line_offset = cur_offset
            raw_line = f.readline(FASTA_READ_BLOCK)
            if not raw_line or raw_line.startswith(b">"):
                break
            stripped_len = len(raw_line.strip())
            line_bytes = len(raw_line)
            # 跨越碱基边界时记录 checkpoint（用于非等宽记录的分段定位）
            if length >= next_checkpoint:
                checkpoints.append((length, line_offset))
                next_checkpoint += SequenceReader.CHECKPOINT_INTERVAL
            length += stripped_len
            cur_offset += line_bytes
            # 若上一行不匹配且其后还有行，则确认非等宽
            if pending_mismatch:
                nonuniform = True
                pending_mismatch = False
            if not nonuniform:
                if first_chars < 0:
                    first_chars, first_bytes = stripped_len, line_bytes
                elif stripped_len != first_chars or line_bytes != first_bytes:
                    pending_mismatch = True  # 暂记，若为末行则不算非等宽
                # 行首空白（空格/制表符等）会使碱基偏离行首字节，破坏等宽换算；
                # 行尾空白不偏移碱基位置，可安全容忍（首行也需检测）
                if stripped_len > 0 and raw_line.lstrip() != raw_line:
                    nonuniform = True
        # EOF 时仅允许“末行严格短于首行”作为合法短尾；
        # 末行更长会破坏等宽换算（start_line 越过末行导致 offset 错位）
        if pending_mismatch and first_chars >= 0 and stripped_len > first_chars:
            nonuniform = True
        f.seek(seq_data_start)  # 回到序列数据开头
        return length, (not nonuniform), first_chars, first_bytes, checkpoints

    def read_range(self, seq_start: int, seq_end: int) -> str:
        """从文件加载序列的 [seq_start, seq_end) 区间（大序列用）。

        行宽恒定时用等宽换算直接 seek（O(1)）；
        行宽可变时借助 checkpoint 索引定位到最近边界后顺序读取（正确但较慢）。
        """
        if self.metrics_pending or not self.is_large:
            return self.sequence[seq_start:seq_end]

        if seq_end <= seq_start:
            return ""
        if self._chunk_start <= seq_start and seq_end <= self._chunk_start + len(
            self._chunk_seq
        ):
            return self._chunk_seq[
                seq_start - self._chunk_start : seq_end - self._chunk_start
            ]

        requested = seq_end - seq_start
        viewport_size = self._window_size
        cacheable = requested <= viewport_size
        needed = min(viewport_size, self.length - seq_start) if cacheable else requested
        f = self._get_fh()

        if self._uniform_lines:
            # ── 等宽行宽：直接换算文件偏移 ──
            chars_per_line = self._chars_per_line
            line_bytes = self._file_line_width
            start_line = seq_start // chars_per_line
            start_col = seq_start % chars_per_line
            file_offset = self.seq_data_offset + start_line * line_bytes + start_col
            f.seek(file_offset)
            skip = 0
        else:
            # ── 可变行宽：定位到不超过 seq_start 的最近 checkpoint ──
            checkpoints = self._checkpoints or [(0, self.seq_data_offset)]
            # 二分查找最大的 base_pos <= seq_start
            lo, hi = 0, len(checkpoints) - 1
            idx = 0
            while lo <= hi:
                mid = (lo + hi) // 2
                if checkpoints[mid][0] <= seq_start:
                    idx = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            base_pos, file_offset = checkpoints[idx]
            f.seek(file_offset)
            skip = seq_start - base_pos  # 需跳过的碱基数

        result: list[str] = []
        total = 0
        while total < needed:
            raw_line = f.readline(FASTA_READ_BLOCK)
            if not raw_line or raw_line.startswith(b">"):
                break
            if skip > 0:
                # 整行都可跳过时无需 decode/切片（超长行避免重复分配内存）
                stripped_len = len(raw_line.strip())
                if stripped_len <= skip:
                    skip -= stripped_len
                    continue
            decoded = raw_line.strip().decode()
            if not decoded:
                continue  # 跳过空行
            if skip > 0:
                decoded = decoded[skip:]
                skip = 0
            take = needed - total
            result.append(decoded[:take])
            total += len(decoded[:take])
        chunk = "".join(result)
        if cacheable:
            self._chunk_start = seq_start
            self._chunk_seq = chunk
        return chunk[:requested]
