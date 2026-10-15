"""align in a fresh project writes nothing outside it: not the druid install (including any .pyc),
not a configured read-only proteome dir, not the rest of tmp_path (spec 2026-10-14, Write boundary).
Needs mafft + clipkit + a `python` with ete3 (cluster phylo env).

The proteome dir is only a canary here: align never receives a proteome path. It is read by
`prepare` (sub-project 2), whose own sandbox test must cover it."""
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from druid import core, paths, project, runner


def _stage_python_has_ete3() -> bool:
    """The stage scripts run `python main.py ...` with PYTHONNOUSERSITE=1; that python needs ete3."""
    py = shutil.which("python")
    return bool(py) and subprocess.run(
        [py, "-c", "import ete3"], env=dict(os.environ, PYTHONNOUSERSITE="1"),
        stdin=subprocess.DEVNULL, capture_output=True).returncode == 0


needs_tools = pytest.mark.skipif(
    not (shutil.which("mafft") and shutil.which("clipkit") and _stage_python_has_ete3()),
    reason="needs mafft, clipkit and a `python` with ete3 (cluster phylo env)")


def _snapshot(d: Path, skip=()) -> dict:
    """Every directory and every file (mtime, size, md5) under d, __pycache__ and .pyc included.
    Only .git and .pytest_cache are skipped, plus any path under one of `skip`."""
    out = {}
    for p in sorted(d.rglob("*")):
        if ".pytest_cache" in p.parts or ".git" in p.parts or any(s in p.parents or s == p for s in skip):
            continue
        if p.is_symlink():
            out[str(p)] = ("link", os.readlink(p))
        elif p.is_dir():
            out[str(p)] = ("dir",)
        elif p.is_file():
            st = p.stat()
            out[str(p)] = ("file", st.st_mtime_ns, st.st_size, hashlib.md5(p.read_bytes()).hexdigest())
    return out


def test_snapshot_sees_new_pyc_and_new_empty_dirs(tmp_path):
    (tmp_path / "helpers" / "__pycache__").mkdir(parents=True)
    before = _snapshot(tmp_path)
    (tmp_path / "helpers" / "__pycache__" / "x.cpython-39.pyc").write_bytes(b"\0")
    assert _snapshot(tmp_path) != before
    before = _snapshot(tmp_path)
    (tmp_path / "newdir").mkdir()
    assert _snapshot(tmp_path) != before


@needs_tools
def test_align_writes_nothing_outside_the_project(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)   # in-process imports only
    # The stage must get PYTHONDONTWRITEBYTECODE=1 from stage_env alone, not from our own environment.
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    prot = tmp_path / "xgraubove"
    prot.mkdir()
    (prot / "Aaa_long.pep.fasta").write_text(">Aaa_1\nMKVLAAGIVG\n>Aaa_2\nMKVLSAGIVG\n")
    for p in (prot / "Aaa_long.pep.fasta", prot):
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        dest = tmp_path / "proj"
        project.init(dest, today="14/10/2026")
        cfg_file = dest / "druid.yaml"
        raw = yaml.safe_load(cfg_file.read_text())
        raw.update(proteomes_dir=str(prot), species=["Aaa"])    # the project really points at it
        cfg_file.write_text(yaml.safe_dump(raw))
        monkeypatch.setenv("DRUID_PROJECT", str(dest))
        paths.use(None)
        hg = "tst.Fam.HG1"
        clusters = dest / "results" / "clusters"
        clusters.mkdir(parents=True)
        (clusters / f"{hg}.fasta").write_text(
            ">Aaa_1\nMKVLAAGIVGLLA\n>Bbb_1\nMKVLSAGIVGLLA\n>Ccc_1\nMKILAAGIVGLMA\n")
        home_before = _snapshot(paths.DRUID_HOME)
        outside_before = _snapshot(tmp_path, skip=(dest,))     # the proteome dir is in here too
        assert str(prot / "Aaa_long.pep.fasta") in outside_before
        cfg = core.load_config()
        rc = runner.run_one(cfg, "align", hg, dest / "runs" / "work")
        assert rc == 0
        assert (dest / "results" / "align" / f"{hg}.aln.fasta").is_file()
        assert _snapshot(paths.DRUID_HOME) == home_before
        assert _snapshot(tmp_path, skip=(dest,)) == outside_before
    finally:                                    # let pytest remove tmp_path afterwards
        for p in (prot, prot / "Aaa_long.pep.fasta"):
            try:
                p.chmod(p.stat().st_mode | stat.S_IWUSR)
            except FileNotFoundError:
                pass
