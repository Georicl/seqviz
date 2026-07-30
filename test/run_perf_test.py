"""Comprehensive performance test for seqviz with large files."""
import os
import sys
import time
import gzip
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from seqviz.browser import FastaBrowser, FileFormat, SequenceView, _open_seq_file

DATA_DIR = "/tmp/seqviz_perf_test"
GENOME = Path(DATA_DIR) / "genome_5g.fa"
LONG_SEQ = Path(DATA_DIR) / "long_1g.fa"
FASTQ = Path(DATA_DIR) / "reads_1g.fastq"

PASS = 0
FAIL = 0

def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name} {detail}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def test_genome_scan():
    """Test scanning >5GB genome file (100K sequences)."""
    print("\n=== Test: 5GB Genome Scan ===")
    t0 = time.perf_counter()
    seqs = FastaBrowser._scan_file(GENOME, FileFormat.FASTA)
    elapsed = time.perf_counter() - t0
    check("Scan 100K seqs", len(seqs) == 100_000, f"({len(seqs)} seqs)")
    check("Scan time < 30s", elapsed < 30, f"({elapsed:.1f}s)")
    check("First offset = 0", seqs[0].offset == 0)
    check("Header parsed", "chr000000" in seqs[0].header, f"({seqs[0].header[:30]})")
    # Verify last record offset is valid
    check("Last offset > 0", seqs[-1].offset > 0, f"({seqs[-1].offset:,})")
    return seqs


def test_genome_load(seqs):
    """Test loading sequences from 5GB file by seek."""
    print("\n=== Test: 5GB Genome Load ===")
    view = SequenceView(GENOME, FileFormat.FASTA)
    view._update_display = lambda: None

    # Load first sequence
    t0 = time.perf_counter()
    view.load_sequence(seqs[0])
    t1 = time.perf_counter() - t0
    check("Load seq[0] < 1s", t1 < 1.0, f"({t1*1000:.0f}ms)")
    check("Seq[0] length = 50000", view._seq_length == 50_000, f"({view._seq_length})")
    check("Seq[0] not empty", len(view._seq) > 0)

    # Load middle sequence (O(1) seek)
    t0 = time.perf_counter()
    view.load_sequence(seqs[50_000])
    t2 = time.perf_counter() - t0
    check("Load seq[50000] < 1s", t2 < 1.0, f"({t2*1000:.0f}ms)")
    check("Seq[50000] length = 50000", view._seq_length == 50_000)

    # Load last sequence
    t0 = time.perf_counter()
    view.load_sequence(seqs[-1])
    t3 = time.perf_counter() - t0
    check("Load seq[-1] < 1s", t3 < 1.0, f"({t3*1000:.0f}ms)")
    check("Seq[-1] length = 50000", view._seq_length == 50_000)

    view.close()


def test_long_sequence():
    """Test >1GB single sequence (1.2Gbp) - chunk mode."""
    print("\n=== Test: 1.2Gbp Long Sequence ===")
    seqs = FastaBrowser._scan_file(LONG_SEQ, FileFormat.FASTA)
    check("Long file has 1 seq", len(seqs) == 1)

    view = SequenceView(LONG_SEQ, FileFormat.FASTA)
    view._update_display = lambda: None

    t0 = time.perf_counter()
    view.load_sequence(seqs[0])
    elapsed = time.perf_counter() - t0
    check("Load 1.2Gbp < 60s", elapsed < 60, f"({elapsed:.1f}s)")
    check("Is large mode", view._is_large)
    check("Length = 1.2Gbp", view._seq_length == 1_200_000_000,
          f"({view._seq_length:,})")

    # Test chunk loading at various positions
    t0 = time.perf_counter()
    chunk_start = view._load_chunk(0, 80)
    t1 = time.perf_counter() - t0
    check("Chunk[0:80] < 0.1s", t1 < 0.1, f"({t1*1000:.1f}ms)")
    check("Chunk[0:80] len=80", len(chunk_start) == 80)
    check("Chunk is ACGT", all(c in "ATCG" for c in chunk_start))

    # Middle
    t0 = time.perf_counter()
    chunk_mid = view._load_chunk(600_000_000, 600_000_080)
    t2 = time.perf_counter() - t0
    check("Chunk[600M] < 0.1s", t2 < 0.1, f"({t2*1000:.1f}ms)")
    check("Chunk[600M] len=80", len(chunk_mid) == 80)

    # Near end
    t0 = time.perf_counter()
    chunk_end = view._load_chunk(1_199_999_920, 1_200_000_000)
    t3 = time.perf_counter() - t0
    check("Chunk[end] < 0.1s", t3 < 0.1, f"({t3*1000:.1f}ms)")
    check("Chunk[end] len=80", len(chunk_end) == 80)

    # Scroll simulation
    t0 = time.perf_counter()
    for i in range(100):
        view._load_chunk(i * 80, (i + 1) * 80)
    t4 = time.perf_counter() - t0
    check("100 sequential chunks < 1s", t4 < 1.0, f"({t4*1000:.0f}ms)")

    view.close()


def test_fastq_scan():
    """Test scanning ~1GB FASTQ (2M reads)."""
    print("\n=== Test: 1GB FASTQ Scan ===")
    t0 = time.perf_counter()
    seqs = FastaBrowser._scan_file(FASTQ, FileFormat.FASTQ)
    elapsed = time.perf_counter() - t0
    check("Scan 2M reads", len(seqs) == 2_000_000, f"({len(seqs):,})")
    check("Scan time < 60s", elapsed < 60, f"({elapsed:.1f}s)")
    check("Read length = 500", seqs[0].length == 500)
    check("Has quality", seqs[0].has_quality)
    return seqs


def test_fastq_load(seqs):
    """Test loading reads from 1GB FASTQ."""
    print("\n=== Test: 1GB FASTQ Load ===")
    view = SequenceView(FASTQ, FileFormat.FASTQ)
    view._update_display = lambda: None

    t0 = time.perf_counter()
    view.load_sequence(seqs[0])
    t1 = time.perf_counter() - t0
    check("Load read[0] < 0.5s", t1 < 0.5, f"({t1*1000:.0f}ms)")
    check("Read[0] seq len=500", len(view._seq) == 500)
    check("Read[0] qual len=500", len(view._quality) == 500)

    # Load middle read
    t0 = time.perf_counter()
    view.load_sequence(seqs[1_000_000])
    t2 = time.perf_counter() - t0
    check("Load read[1M] < 0.5s", t2 < 0.5, f"({t2*1000:.0f}ms)")
    check("Read[1M] seq len=500", len(view._seq) == 500)

    view.close()


def test_gzip_support():
    """Test gzip compressed file support."""
    print("\n=== Test: Gzip Support ===")
    # Create small gzip FASTA
    gz_fa = Path(tempfile.mktemp(suffix=".fa.gz"))
    with gzip.open(gz_fa, "wt") as f:
        f.write(">gz_seq1\nATCGATCG\n>gz_seq2\nGGGGCCCC\n")

    fmt = FastaBrowser._detect_format(gz_fa)
    check("Detect .fa.gz as FASTA", fmt == FileFormat.FASTA)

    seqs = FastaBrowser._scan_file(gz_fa, fmt)
    check("Gzip FASTA 2 seqs", len(seqs) == 2)

    view = SequenceView(gz_fa, fmt)
    view._update_display = lambda: None
    view.load_sequence(seqs[0])
    check("Gzip seq1 = ATCGATCG", view._seq == "ATCGATCG")
    view.load_sequence(seqs[1])
    check("Gzip seq2 = GGGGCCCC", view._seq == "GGGGCCCC")
    view.close()
    os.unlink(gz_fa)

    # Create small gzip FASTQ
    gz_fq = Path(tempfile.mktemp(suffix=".fastq.gz"))
    with gzip.open(gz_fq, "wt") as f:
        f.write("@gz_read1\nATCG\n+\nIIII\n")

    fmt2 = FastaBrowser._detect_format(gz_fq)
    check("Detect .fastq.gz as FASTQ", fmt2 == FileFormat.FASTQ)

    seqs2 = FastaBrowser._scan_file(gz_fq, fmt2)
    check("Gzip FASTQ 1 read", len(seqs2) == 1)

    view2 = SequenceView(gz_fq, fmt2)
    view2._update_display = lambda: None
    view2.load_sequence(seqs2[0])
    check("Gzip read seq = ATCG", view2._seq == "ATCG")
    check("Gzip read qual = IIII", view2._quality == "IIII")
    view2.close()
    os.unlink(gz_fq)


def test_cRLF():
    """Test CRLF file support."""
    print("\n=== Test: CRLF Support ===")
    p = Path(tempfile.mktemp(suffix=".fa"))
    p.write_bytes(b">crlf1\r\nAAAA\r\nTTTT\r\n>crlf2\r\nGGGG\r\nCCCC\r\n")

    seqs = FastaBrowser._scan_file(p, FileFormat.FASTA)
    check("CRLF 2 seqs", len(seqs) == 2)
    # >crlf1\r\n = 8 bytes, AAAA\r\n = 6, TTTT\r\n = 6 → offset2 = 20
    check("CRLF offset[1] = 20", seqs[1].offset == 20, f"({seqs[1].offset})")

    view = SequenceView(p, FileFormat.FASTA)
    view._update_display = lambda: None
    view.load_sequence(seqs[0])
    check("CRLF seq1 = AAAATTTT", view._seq == "AAAATTTT", f"({view._seq})")
    view.load_sequence(seqs[1])
    check("CRLF seq2 = GGGGCCCC", view._seq == "GGGGCCCC", f"({view._seq})")
    view.close()
    os.unlink(p)

    # CRLF FASTQ
    pq = Path(tempfile.mktemp(suffix=".fastq"))
    pq.write_bytes(b"@r1\r\nATCG\r\n+\r\nIIII\r\n@r2\r\nGGGG\r\n+\r\nHHHH\r\n")
    seqs_q = FastaBrowser._scan_file(pq, FileFormat.FASTQ)
    check("CRLF FASTQ 2 reads", len(seqs_q) == 2)
    # @r1\r\n=5, ATCG\r\n=6, +\r\n=3, IIII\r\n=6 → offset2 = 20
    check("CRLF FASTQ offset[1] = 20", seqs_q[1].offset == 20, f"({seqs_q[1].offset})")

    view_q = SequenceView(pq, FileFormat.FASTQ)
    view_q._update_display = lambda: None
    view_q.load_sequence(seqs_q[1])
    check("CRLF FASTQ read2 seq", view_q._seq == "GGGG", f"({view_q._seq})")
    view_q.close()
    os.unlink(pq)


def test_quick_scan():
    """Test quick scan + background scan mechanism."""
    print("\n=== Test: Quick Scan ===")
    t0 = time.perf_counter()
    seqs, is_done = FastaBrowser._scan_file_quick(GENOME, FileFormat.FASTA, limit=500)
    elapsed = time.perf_counter() - t0
    check("Quick scan returns 500", len(seqs) == 500)
    check("Quick scan not done", not is_done)
    check("Quick scan < 1s", elapsed < 1.0, f"({elapsed*1000:.0f}ms)")


if __name__ == "__main__":
    print("=" * 60)
    print("  SeqViz Comprehensive Performance & Correctness Test")
    print("=" * 60)

    # Check files exist
    for f in [GENOME, LONG_SEQ, FASTQ]:
        if not f.exists():
            print(f"\n[ERROR] Missing: {f}")
            print("Run gen_perf_data.py first!")
            sys.exit(1)
        print(f"  {f.name}: {os.path.getsize(f)/1e9:.2f} GB")

    test_quick_scan()
    genome_seqs = test_genome_scan()
    test_genome_load(genome_seqs)
    test_long_sequence()
    fastq_seqs = test_fastq_scan()
    test_fastq_load(fastq_seqs)
    test_gzip_support()
    test_cRLF()

    print("\n" + "=" * 60)
    print(f"  RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(1 if FAIL > 0 else 0)
