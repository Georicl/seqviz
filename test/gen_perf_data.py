"""Generate large test files for performance testing."""
import os
import random
import time

random.seed(42)
BASES = "ATCG"
OUT_DIR = "/tmp/seqviz_perf_test"
os.makedirs(OUT_DIR, exist_ok=True)

def gen_genome_fasta():
    """Generate >5GB genome FASTA: 100,000 sequences x ~50KB each."""
    path = os.path.join(OUT_DIR, "genome_5g.fa")
    if os.path.exists(path) and os.path.getsize(path) > 5_000_000_000:
        print(f"  [skip] {path} already exists ({os.path.getsize(path)/1e9:.1f} GB)")
        return path
    print("  Generating genome_5g.fa (>5GB, 100K seqs x 50KB)...")
    t0 = time.time()
    line_width = 80
    seq_len = 50_000  # 50KB per sequence
    n_seqs = 100_000
    with open(path, "w", buffering=1024*1024) as f:
        for i in range(n_seqs):
            f.write(f">chr{i:06d} length={seq_len} genome=sim\n")
            for j in range(0, seq_len, line_width):
                chunk = "".join(random.choices(BASES, k=min(line_width, seq_len - j)))
                f.write(chunk + "\n")
            if (i + 1) % 10000 == 0:
                elapsed = time.time() - t0
                print(f"    {i+1}/{n_seqs} seqs ({elapsed:.0f}s)")
    size = os.path.getsize(path)
    print(f"  Done: {size/1e9:.2f} GB in {time.time()-t0:.0f}s")
    return path


def gen_long_sequence():
    """Generate >1GB single-sequence FASTA (1.2Gbp in 80bp lines)."""
    path = os.path.join(OUT_DIR, "long_1g.fa")
    if os.path.exists(path) and os.path.getsize(path) > 1_000_000_000:
        print(f"  [skip] {path} already exists ({os.path.getsize(path)/1e9:.1f} GB)")
        return path
    print("  Generating long_1g.fa (>1GB, single 1.2Gbp sequence)...")
    t0 = time.time()
    line_width = 80
    total_bp = 1_200_000_000  # 1.2 Gbp
    with open(path, "w", buffering=1024*1024) as f:
        f.write(">sim_chr1 length=1200000000 genome=hg_sim\n")
        written = 0
        while written < total_bp:
            n = min(line_width, total_bp - written)
            f.write("".join(random.choices(BASES, k=n)) + "\n")
            written += n
            if written % 100_000_000 == 0:
                elapsed = time.time() - t0
                print(f"    {written/1e9:.1f}/{total_bp/1e9:.1f} Gbp ({elapsed:.0f}s)")
    size = os.path.getsize(path)
    print(f"  Done: {size/1e9:.2f} GB in {time.time()-t0:.0f}s")
    return path


def gen_fastq_1g():
    """Generate ~1GB FASTQ: 2M reads x 500bp."""
    path = os.path.join(OUT_DIR, "reads_1g.fastq")
    if os.path.exists(path) and os.path.getsize(path) > 1_000_000_000:
        print(f"  [skip] {path} already exists ({os.path.getsize(path)/1e9:.1f} GB)")
        return path
    print("  Generating reads_1g.fastq (~1GB, 2M reads x 500bp)...")
    t0 = time.time()
    n_reads = 2_000_000
    read_len = 500
    with open(path, "w", buffering=1024*1024) as f:
        for i in range(n_reads):
            seq = "".join(random.choices(BASES, k=read_len))
            qual = "".join(chr(random.randint(33+20, 33+40)) for _ in range(read_len))
            f.write(f"@read_{i:08d} len={read_len}\n{seq}\n+\n{qual}\n")
            if (i + 1) % 200_000 == 0:
                elapsed = time.time() - t0
                print(f"    {i+1}/{n_reads} reads ({elapsed:.0f}s)")
    size = os.path.getsize(path)
    print(f"  Done: {size/1e9:.2f} GB in {time.time()-t0:.0f}s")
    return path


if __name__ == "__main__":
    print("=== Generating performance test files ===")
    gen_genome_fasta()
    gen_long_sequence()
    gen_fastq_1g()
    print("\n=== All files generated ===")
    for f in sorted(os.listdir(OUT_DIR)):
        fp = os.path.join(OUT_DIR, f)
        print(f"  {f}: {os.path.getsize(fp)/1e9:.2f} GB")
