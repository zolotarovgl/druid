#!/usr/bin/env python3
"""Count how many homology groups (HGs) have finished each step2 stage.

An HG is expected if it has a clusters/<id>.fasta with >= 2 sequences (the same filter
step2.nf applies), or, with --ids, if it is listed there. A stage counts as done when its
published output exists and is non-empty:

  align        align/<id>.aln.fasta
  tree         gene_trees/<id>.treefile
  possvm_prev  possvm_prev/<id>.*.ortholog_groups.csv   (POSSVM on the IQ-TREE tree)
  generax      generax/<id>.generax.tree
  gxsup        generax_support/<id>.generax.support.tree
  possvm       possvm/<id>.*.ortholog_groups.csv        (POSSVM on the GeneRax tree)

"done" is possvm when GeneRax was run (any generax/ output exists), else possvm_prev.
Counts are split by category (the text before the first '.' of the HG id, e.g. tfs, adh).

Usage:  report_status.py [--ids ids.txt] [--missing STAGE] [--outdir OUTDIR]
"""
import argparse
import collections
import os
import sys

STAGES = [
    ("align",       "align",           lambda i: [f"{i}.aln.fasta"]),
    ("tree",        "gene_trees",      lambda i: [f"{i}.treefile"]),
    ("possvm_prev", "possvm_prev",     None),
    ("generax",     "generax",         lambda i: [f"{i}.generax.tree"]),
    ("gxsup",       "generax_support", lambda i: [f"{i}.generax.support.tree"]),
    ("possvm",      "possvm",          None),
]
OG_SUFFIX = ".ortholog_groups.csv"
# step2.nf default: ${projectDir}/results, i.e. <repo>/results next to workflow/
DEFAULT_OUTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def nonempty_files(d):
    """{name: size>0} for a directory, one listing (fast on network mounts)."""
    out = set()
    if not os.path.isdir(d):
        return out
    with os.scandir(d) as it:
        for e in it:
            try:
                if e.is_file() and e.stat().st_size > 0:
                    out.add(e.name)
            except OSError:
                pass
    return out


def possvm_done(files):
    """HG ids with an ortholog_groups.csv, named <id>.<tree name>.ortholog_groups.csv."""
    done = set()
    for f in files:
        if f.endswith(OG_SUFFIX):
            base = f[:-len(OG_SUFFIX)]
            # <id> = category.domain.HGn; the tree name follows it
            parts = base.split(".")
            for k in range(len(parts), 0, -1):
                if parts[k - 1].startswith("HG"):
                    done.add(".".join(parts[:k]))
                    break
    return done


def count_seqs(path, stop=2):
    n = 0
    with open(path, errors="replace") as fh:
        for line in fh:
            if line.startswith(">"):
                n += 1
                if n >= stop:
                    break
    return n


def expected_hgs(outdir, ids_file=None, min_seqs=2):
    """Expected HG ids: the stripped non-blank lines of ids_file, else clusters/*.fasta with
    >= min_seqs seqs (phylocli passes params.min_seqs, = step2.nf's filter)."""
    if ids_file:
        with open(ids_file) as fh:
            return {l.strip() for l in fh if l.strip()}
    cdir = os.path.join(outdir, "clusters")
    return {f[:-6] for f in nonempty_files(cdir)
            if f.endswith(".fasta") and ".HG" in f
            and count_seqs(os.path.join(cdir, f), stop=min_seqs) >= min_seqs}


def done_by_stage(outdir, expected):
    """{stage: set of done HG ids} for every stage plus 'done'."""
    done = {}
    for stage, sub, names in STAGES:
        files = nonempty_files(os.path.join(outdir, sub))
        if names is None:
            done[stage] = possvm_done(files) & expected
        else:
            done[stage] = {i for i in expected if all(n in files for n in names(i))}
    final = "possvm" if done["generax"] else "possvm_prev"
    done["done"] = done[final]
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR,
                    help="step2 OUTDIR, only if the run used a custom --OUTDIR "
                         "(default: <repo>/results, as in step2.nf)")
    ap.add_argument("--ids", default=None, help="restrict to the HG ids listed in this file")
    ap.add_argument("--missing", default=None, choices=[s[0] for s in STAGES] + ["done"],
                    help="print the expected HG ids that have NOT finished this stage")
    a = ap.parse_args()

    cdir = os.path.join(a.outdir, "clusters")
    if not os.path.isdir(cdir):
        sys.exit(f"no clusters/ in {a.outdir} -- is --outdir the step2 OUTDIR?")

    expected = expected_hgs(a.outdir, a.ids)
    done = done_by_stage(a.outdir, expected)
    final = "possvm" if done["generax"] else "possvm_prev"

    if a.missing:
        for i in sorted(expected - done[a.missing]):
            print(i)
        return

    print_table(expected, done)


def print_table(expected, done):
    """Print the per-category status table and the summary line."""
    final = "possvm" if done["generax"] else "possvm_prev"
    cats = collections.Counter(i.split(".")[0] for i in expected)
    cols = [s[0] for s in STAGES] + ["done"]
    w = max([len(c) for c in cats] + [8])
    print(f"{'category':<{w}} {'HGs':>6} " + " ".join(f"{c:>11}" for c in cols))
    for cat in sorted(cats) + ["TOTAL"]:
        ids = expected if cat == "TOTAL" else {i for i in expected if i.split(".")[0] == cat}
        row = " ".join(f"{len(done[c] & ids):>11}" for c in cols)
        print(f"{cat:<{w}} {len(ids):>6} {row}")
    n = len(expected)
    print(f"\n{len(done['done'])}/{n} HGs done ({100 * len(done['done']) / max(n, 1):.1f} %; "
          f"done = {final}). List the rest with --missing done.")


if __name__ == "__main__":
    main()
