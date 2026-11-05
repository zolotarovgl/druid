"""generax.sh hands GeneRax the model IQ-TREE selected for the family (Grygoriy, 05/11/2026);
SUBS_MODEL only when the tree log has no "Best-fit model:" line (FastTree, fixed model, no log)."""
import os
import subprocess
from pathlib import Path

import pytest

STAGE = Path(__file__).resolve().parents[1] / "druid" / "stages" / "generax.sh"


def _run(tmp_path, log_text):
    out, work, fake = tmp_path / "out", tmp_path / "work", tmp_path / "bin"
    for d in (out / "gene_trees", work, fake):
        d.mkdir(parents=True)
    if log_text is not None:
        (out / "gene_trees" / "f.HG1.log").write_text(log_text)
    for n in ("a.fa", "g.nwk", "s.nwk"):
        (work / n).write_text(">A\nM\n" if n == "a.fa" else "(A);\n")
    (fake / "python").write_text(f'#!/bin/sh\necho "$@" > {tmp_path}/args.txt\n')
    (fake / "python").chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "CPUS": "1", "OUTDIR": str(out),
           "ID": "f.HG1", "SUBS_MODEL": "LG", "MAX_SPR": "3", "DRUID_HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(STAGE), "a.fa", "g.nwk", "s.nwk"], cwd=work, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    args = (tmp_path / "args.txt").read_text().split()
    return args[args.index("--subs_model") + 1]


@pytest.mark.parametrize("log, want", [
    ("...\nBest-fit model: WAG+F+I+G4 chosen according to BIC\n", "WAG+F+I+G4"),
    ("FastTree Version 2.1.11\n", "LG"),
    (None, "LG"),
])
def test_generax_model_from_tree_log(tmp_path, log, want):
    assert _run(tmp_path, log) == want
