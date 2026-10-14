"""druid/paths.py: project discovery and the write gate (spec 14/10/2026, Write boundary)."""
import os
from pathlib import Path

import pytest

from druid import paths


@pytest.fixture
def proj(tmp_path, monkeypatch):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "druid.yaml").write_text("outdir: results\nruns_dir: runs\npartition: x\nqos: y\nparams: {}\n")
    monkeypatch.delenv("DRUID_PROJECT", raising=False)
    monkeypatch.delenv("DRUID_CONFIG", raising=False)
    paths.use(None)
    yield p.resolve()
    paths.use(None)


def test_discovery_order_explicit_env_walkup(proj, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    (other / "druid.yaml").write_text("outdir: r\n")
    (proj / "a" / "b").mkdir(parents=True)
    monkeypatch.chdir(proj / "a" / "b")
    assert paths.project_root() == proj                       # walk up
    monkeypatch.setenv("DRUID_PROJECT", str(other))
    assert paths.project_root() == other.resolve()            # env beats walk-up
    paths.use(proj)
    assert paths.project_root() == proj                       # explicit beats env


def test_no_project_names_the_three_ways(tmp_path, monkeypatch):
    monkeypatch.delenv("DRUID_PROJECT", raising=False)
    paths.use(None)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(paths.NoProject) as e:
        paths.project_root()
    msg = str(e.value)
    assert "--project" in msg and "DRUID_PROJECT" in msg and "druid init" in msg


def test_env_or_explicit_without_druid_yaml_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("DRUID_PROJECT", str(tmp_path))
    with pytest.raises(paths.NoProject):
        paths.project_root()
    monkeypatch.delenv("DRUID_PROJECT")
    paths.use(tmp_path)
    with pytest.raises(paths.NoProject):
        paths.project_root()
    paths.use(None)


def test_config_file_and_runs_dir(proj, monkeypatch, tmp_path):
    paths.use(proj)
    assert paths.config_file() == proj / "druid.yaml"
    assert paths.runs_dir() == proj / "runs"
    run_cfg = proj / "runs" / "r1" / "config.yaml"
    run_cfg.parent.mkdir(parents=True)
    run_cfg.write_text("outdir: results\nruns_dir: phylocli/runs\n")
    monkeypatch.setenv("DRUID_CONFIG", str(run_cfg))
    assert paths.config_file() == run_cfg
    assert paths.runs_dir() == proj / "phylocli" / "runs"     # still relative to the project


def test_runs_dir_defaults_to_runs(proj):
    (proj / "druid.yaml").write_text("outdir: results\n")
    paths.use(proj)
    assert paths.runs_dir() == proj / "runs"


def test_writable_inside_and_outside(proj, tmp_path):
    paths.use(proj)
    assert paths.writable(proj / "results" / "x.txt") == proj / "results" / "x.txt"
    for bad in (tmp_path / "elsewhere.txt", proj / ".." / "escape.txt", Path("/tmp/x")):
        with pytest.raises(paths.OutsideProject):
            paths.writable(bad)


def test_writable_relative_is_against_cwd(proj, tmp_path, monkeypatch):
    paths.use(proj)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(paths.OutsideProject):
        paths.writable("x.txt")
    monkeypatch.chdir(proj)
    assert paths.writable("x.txt") == proj / "x.txt"


def test_writable_content_through_outward_symlink_is_refused(proj, tmp_path):
    paths.use(proj)
    outside = tmp_path / "xgraubove"
    outside.mkdir()
    (outside / "Mlei_long.pep.fasta").write_text(">a\nM\n")
    (proj / "data").mkdir()
    (proj / "data" / "link.fasta").symlink_to(outside / "Mlei_long.pep.fasta")
    (proj / "dirlink").symlink_to(outside)
    with pytest.raises(paths.OutsideProject):
        paths.write_text(proj / "data" / "link.fasta", "x")
    with pytest.raises(paths.OutsideProject):
        paths.write_text(proj / "dirlink" / "new.txt", "x")
    assert (outside / "Mlei_long.pep.fasta").read_text() == ">a\nM\n"


def test_unlinking_an_outward_symlink_is_allowed_and_keeps_the_target(proj, tmp_path):
    paths.use(proj)
    target = tmp_path / "t.txt"
    target.write_text("keep")
    link = proj / "l.txt"
    link.symlink_to(target)
    paths.unlink(link)
    assert not link.is_symlink() and target.read_text() == "keep"


def test_rmtree_of_a_workdir_with_outward_links_keeps_targets(proj, tmp_path):
    paths.use(proj)
    target = tmp_path / "t.txt"
    target.write_text("keep")
    work = proj / "runs" / "work" / "HG1"
    paths.mkdir(work, parents=True)
    paths.symlink(work / "t.txt", target)
    paths.rmtree(work)
    assert not work.exists() and target.read_text() == "keep"


def test_ops_inside(proj, tmp_path):
    paths.use(proj)
    src = tmp_path / "src.txt"
    src.write_text("s")
    d = paths.mkdir(proj / "a" / "b", parents=True)
    assert d.is_dir()
    paths.write_text(d / "f.txt", "hello")
    paths.copy2(src, d / "g.txt")
    paths.replace(d / "g.txt", d / "h.txt")
    assert (d / "h.txt").read_text() == "s" and not (d / "g.txt").exists()
    sd = tmp_path / "sd"
    sd.mkdir()
    (sd / "x").write_text("x")
    paths.copytree(sd, d / "sd")
    assert (d / "sd" / "x").read_text() == "x"
    with pytest.raises(paths.OutsideProject):
        paths.copy2(d / "h.txt", tmp_path / "out.txt")
    with pytest.raises(paths.OutsideProject):
        paths.replace(d / "h.txt", tmp_path / "out.txt")


def test_tmp_dir_and_mkstemp_are_in_the_project(proj):
    paths.use(proj)
    assert paths.tmp_dir() == proj / ".druid" / "tmp" and paths.tmp_dir().is_dir()
    f = paths.mkstemp(prefix="nxflog-", suffix=".log")
    assert f.parent == proj / ".druid" / "tmp" and f.name.startswith("nxflog-") and f.exists()


def test_druid_home_is_the_install():
    assert (paths.DRUID_HOME / "druid" / "paths.py").is_file()
