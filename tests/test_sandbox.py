"""One HG through align in a fresh project with a read-only proteome dir: nothing outside the
project changes (spec 2026-10-14, Write boundary). Needs mafft + clipkit (cluster phylo env)."""
import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from druid import core, paths, project, runner


def _stage_python_has_ete3() -> bool:
    """The stage scripts run `python main.py ...` with PYTHONNOUSERSITE=1; that python needs ete3."""
    py = shutil.which("python")
    return bool(py) and subprocess.run(
        [py, "-c", "import ete3"], env=dict(os.environ, PYTHONNOUSERSITE="1"),
        stdin=subprocess.DEVNULL, capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(
    not (shutil.which("mafft") and shutil.which("clipkit") and _stage_python_has_ete3()),
    reason="needs mafft, clipkit and a `python` with ete3 (cluster phylo env)")


def _snapshot(d: Path) -> dict:
    out = {}
    for p in sorted(d.rglob("*")):
        if "__pycache__" in p.parts or ".pytest_cache" in p.parts or ".git" in p.parts:
            continue
        if p.is_file() and not p.is_symlink():
            out[str(p)] = (p.stat().st_mtime_ns, hashlib.md5(p.read_bytes()).hexdigest())
    return out


def test_align_writes_only_inside_the_project(tmp_path, monkeypatch):
    prot = tmp_path / "xgraubove"
    prot.mkdir()
    (prot / "Aaa_long.pep.fasta").write_text(">Aaa_1\nMKVLAAGIVG\n>Aaa_2\nMKVLSAGIVG\n")
    for p in (prot / "Aaa_long.pep.fasta", prot):
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        dest = tmp_path / "proj"
        project.init(dest, today="14/10/2026")
        monkeypatch.setenv("DRUID_PROJECT", str(dest))
        paths.use(None)
        hg = "tst.Fam.HG1"
        clusters = dest / "results" / "clusters"
        clusters.mkdir(parents=True)
        (clusters / f"{hg}.fasta").write_text(
            ">Aaa_1\nMKVLAAGIVGLLA\n>Bbb_1\nMKVLSAGIVGLLA\n>Ccc_1\nMKILAAGIVGLMA\n")
        home_before, prot_before = _snapshot(paths.DRUID_HOME), _snapshot(prot)
        outside_before = {p.name for p in tmp_path.iterdir()}
        cfg = core.load_config()
        rc = runner.run_one(cfg, "align", hg, dest / "runs" / "work")
        assert rc == 0
        assert (dest / "results" / "align" / f"{hg}.aln.fasta").is_file()
        assert _snapshot(paths.DRUID_HOME) == home_before
        assert _snapshot(prot) == prot_before
        assert {p.name for p in tmp_path.iterdir()} == outside_before
        assert not list((paths.DRUID_HOME / "druid" / "helpers").glob("__pycache__/*.cpython-*.pyc.*"))
    finally:                                    # let pytest remove tmp_path afterwards
        for p in (prot, prot / "Aaa_long.pep.fasta"):
            p.chmod(p.stat().st_mode | stat.S_IWUSR)
