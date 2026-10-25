"""Helpers and the `run` fixture shared by test_step1run, test_cli and test_tui.

Imports no test_* module at module level (that would recreate an import cycle); the shared fake-cluster
state lives in tests.test_cli and is fetched lazily."""
from __future__ import annotations

import stat

import pytest

from druid import core, paths

PREF = "x"


def _state():
    from tests.test_cli import _state as st
    return st


@pytest.fixture
def run(cli, monkeypatch):
    """The cli fixture's project with its own sbatch: prints 101, 102, ... (counter file), logs
    each call's argv as one line, fails on call FAKE_SBATCH_FAIL."""
    b = _state()["bin"]
    sb = b / "sbatch"
    sb.write_text(
        "#!/bin/sh\n"
        f'n=$(cat {b}/count 2>/dev/null || echo 0); n=$((n + 1)); echo $n > {b}/count\n'
        f'echo "$@" >> {b}/sbatch.log\n'
        'if [ "$n" = "${FAKE_SBATCH_FAIL:-0}" ]; then echo "denied" >&2; exit 1; fi\n'
        'echo $((100 + n))\n')
    sb.chmod(sb.stat().st_mode | stat.S_IXUSR)
    monkeypatch.delenv("FAKE_SBATCH_FAIL", raising=False)
    return paths.project_root()


def _calls():
    f = _state()["bin"] / "sbatch.log"
    return f.read_text().splitlines() if f.exists() else []


def _fams(root, names):
    """The genefam file holds exactly these families (ids x.<name>)."""
    (root / "gene_families_searchinfo.csv").write_text(
        "".join(f"{n}\tPF_{n}\t1.1\t3\tGA\tTF\t{PREF}\n" for n in names))
    return [f"{PREF}.{n}" for n in names]


def _cfg_raw():
    return core.load_config(paths.config_file()), paths.read_raw()


def _out(cfg, rel, text=""):
    p = cfg.outdir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _queued(root, stage, jid, ids, monkeypatch, k=1):
    """A druid array of `stage` in runs/ (jobs.tsv) whose job is listed by the fake squeue."""
    d = root / "runs" / f"20261001-00000{k}_{stage}"
    d.mkdir(parents=True)
    (d / "ids_0.txt").write_text("\n".join(ids) + "\n")
    (d / "jobs.tsv").write_text(f"{jid}\t{d / 'ids_0.txt'}\n")
    monkeypatch.setenv("FAKE_SQUEUE", f"{jid}_0|whatever\n")


def _five(run, monkeypatch):
    cfg, _raw = _cfg_raw()
    f1, f2, f3, f4, f5 = _fams(run, ["F1", "F2", "F3", "F4", "F5"])
    _out(cfg, f"search/{f2}.domains.fasta", ">a\nM\n")             # hits, not clustered
    _out(cfg, f"search/{f3}.domains.fasta", "")                    # no hits
    _out(cfg, f"search/{f4}.domains.fasta", ">a\nM\n")             # clustered
    _out(cfg, f"clusters/{f4}_cluster.tsv", "a\t1\n")
    _queued(run, "search", "900", [f5], monkeypatch)               # queued for search
    return f1, f2, f3, f4, f5
