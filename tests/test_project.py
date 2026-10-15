"""druid init / druid adopt (spec 2026-10-14)."""
import hashlib
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from druid import cli, core, paths, project


def _md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def _tree_state(d: Path) -> dict:
    return {str(p.relative_to(d)): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in d.rglob("*")}


def test_init_makes_a_loadable_frozen_project(tmp_path, monkeypatch):
    dest = tmp_path / "proj"
    written = project.init(dest, today="14/10/2026")
    raw = yaml.safe_load((dest / "druid.yaml").read_text())
    assert raw["proteome_glob"] == "{sp}_long.pep.fasta" and raw["species"] == []
    assert raw["prepare"] == "auto" and raw["runs_dir"] == "runs"
    assert "14/10/2026" in (dest / "druid.yaml").read_text()
    for f in project.ShippedData:
        assert _md5(dest / "data" / f) == _md5(paths.DRUID_HOME / "druid/data" / f)
    assert (dest / "data/families.csv").read_text() == ""
    assert all(p.resolve().is_relative_to(dest.resolve()) for p in written)
    monkeypatch.setenv("DRUID_PROJECT", str(dest))
    cfg = core.load_config()
    assert cfg.outdir == dest.resolve() / "results"
    assert cfg.params["SPECIES_TREE"] == str(dest.resolve() / "data/species_tree.binary.newick")


def test_init_into_an_empty_existing_dir_is_fine(tmp_path):
    (tmp_path / "e").mkdir()
    project.init(tmp_path / "e", today="14/10/2026")
    assert (tmp_path / "e" / "druid.yaml").is_file()


def test_init_refuses_a_non_empty_dir_and_writes_nothing(tmp_path):
    d = tmp_path / "full"
    d.mkdir()
    (d / "x").write_text("x")
    before = _tree_state(d)
    with pytest.raises(project.ProjectError, match="not empty"):
        project.init(d, today="14/10/2026")
    assert _tree_state(d) == before


def _phylohpc(tmp_path) -> Path:
    v3 = tmp_path / "v3"
    (v3 / "phylocli" / "runs" / "20261001-000000_align").mkdir(parents=True)
    (v3 / "data").mkdir()
    (v3 / "data" / "input.fasta").write_text(">a\nM\n")
    (v3 / "phylocli" / "config.yaml").write_text(
        "outdir: results\npartition: genoa64\nqos: normal\nparams:\n"
        "  infasta: data/input.fasta\n  genefam_info: data/gene_families_searchinfo.csv\n"
        "  SPECIES_TREE: data/species_tree.binary.newick\n")
    return v3


def test_adopt_writes_only_druid_yaml_and_keeps_history(tmp_path, monkeypatch):
    v3 = _phylohpc(tmp_path)
    before = _tree_state(v3)
    out = project.adopt(v3, today="14/10/2026")
    after = _tree_state(v3)
    assert out == v3 / "druid.yaml"
    assert set(after) - set(before) == {"druid.yaml"}
    assert {k: v for k, v in after.items() if k != "druid.yaml"} == before
    raw = yaml.safe_load(out.read_text())
    assert raw["prepare"] == "locked" and raw["runs_dir"] == "phylocli/runs"
    assert raw["nextflow_dir"] == "."
    monkeypatch.setenv("DRUID_PROJECT", str(v3))
    assert paths.runs_dir() == v3.resolve() / "phylocli" / "runs"
    cfg = core.load_config()
    assert cfg.params["infasta"] == str(v3.resolve() / "data/input.fasta")


def test_adopt_refuses_existing_druid_yaml_or_missing_config(tmp_path):
    v3 = _phylohpc(tmp_path)
    (v3 / "druid.yaml").write_text("x: 1\n")
    with pytest.raises(project.ProjectError, match="already"):
        project.adopt(v3, today="14/10/2026")
    assert (v3 / "druid.yaml").read_text() == "x: 1\n"
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(project.ProjectError, match="phylocli/config.yaml"):
        project.adopt(bare, today="14/10/2026")
    assert list(bare.iterdir()) == []


def test_cli_init_and_adopt(tmp_path):
    r = CliRunner().invoke(cli.app, ["init", str(tmp_path / "p")])
    assert r.exit_code == 0, r.output
    assert "druid.yaml" in r.output
    r = CliRunner().invoke(cli.app, ["init", str(tmp_path / "p")])
    assert r.exit_code == 2 and "not empty" in r.output


@pytest.mark.parametrize("text", ["a: [unclosed\n", "- just\n- a list\n", "scalar\n"])
def test_adopt_refuses_malformed_or_non_mapping_config(tmp_path, text):
    v3 = _phylohpc(tmp_path)
    (v3 / "phylocli" / "config.yaml").write_text(text)
    before = _tree_state(v3)
    with pytest.raises(project.ProjectError, match="config.yaml"):
        project.adopt(v3, today="14/10/2026")
    assert _tree_state(v3) == before and not (v3 / "druid.yaml").exists()


def test_cli_adopt_success_and_existing_druid_yaml(tmp_path):
    v3 = _phylohpc(tmp_path)
    r = CliRunner().invoke(cli.app, ["adopt", str(v3)])
    assert r.exit_code == 0, r.output
    assert f"wrote {v3 / 'druid.yaml'}" in r.output and "prepare: locked" in r.output
    assert (v3 / "druid.yaml").is_file()
    r = CliRunner().invoke(cli.app, ["adopt", str(v3)])
    assert r.exit_code == 2 and "ERROR" in r.output and "already exists" in r.output


def test_cli_adopt_malformed_config_is_an_error_line(tmp_path):
    v3 = _phylohpc(tmp_path)
    (v3 / "phylocli" / "config.yaml").write_text("a: [unclosed\n")
    r = CliRunner().invoke(cli.app, ["adopt", str(v3)])
    assert r.exit_code == 2 and "ERROR" in r.output and not (v3 / "druid.yaml").exists()


def _old_config(v3, **edit):
    p = v3 / "phylocli" / "config.yaml"
    raw = yaml.safe_load(p.read_text())
    for k, v in edit.items():
        if v is None:
            raw.pop(k, None)
        elif k.startswith("params."):
            raw["params"][k[7:]] = v
        else:
            raw[k] = v
    p.write_text(yaml.safe_dump(raw))


@pytest.mark.parametrize("edit,needle", [
    ({"partition": None}, "partition"),
    ({"params": None}, "params"),
    ({"params.infasta": "/elsewhere/x"}, "infasta"),
    ({"outdir": "/elsewhere/results"}, "outdir"),
    ({"runs_dir": "."}, "runs_dir"),
])
def test_adopt_validates_before_writing(tmp_path, edit, needle):
    v3 = _phylohpc(tmp_path)
    _old_config(v3, **edit)
    before = _tree_state(v3)
    with pytest.raises(project.ProjectError, match=needle):
        project.adopt(v3, today="15/10/2026")
    assert _tree_state(v3) == before and not (v3 / "druid.yaml").exists()


def test_cli_adopt_invalid_config_is_an_error_line(tmp_path):
    v3 = _phylohpc(tmp_path)
    _old_config(v3, partition=None)
    r = CliRunner().invoke(cli.app, ["adopt", str(v3)])
    assert r.exit_code == 2 and "ERROR" in r.output and "partition" in r.output
    assert "Traceback" not in r.output and not (v3 / "druid.yaml").exists()


def _read_only(d: Path):
    import os
    d.chmod(0o555)
    if os.access(d, os.W_OK):
        pytest.skip("directory permissions are not enforced here (running as root?)")


def test_cli_init_into_a_read_only_parent_is_an_error_line(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    _read_only(ro)
    try:
        r = CliRunner().invoke(cli.app, ["init", str(ro / "p")])
    finally:
        ro.chmod(0o755)
    assert r.exit_code == 2 and "ERROR" in r.output and "Traceback" not in r.output
    assert not (ro / "p").exists()


def test_cli_init_into_a_read_only_empty_dir_is_an_error_line(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    _read_only(ro)
    try:
        r = CliRunner().invoke(cli.app, ["init", str(ro)])
    finally:
        ro.chmod(0o755)
    assert r.exit_code == 2 and "ERROR" in r.output and "Traceback" not in r.output


def test_cli_adopt_into_a_read_only_project_is_an_error_line(tmp_path):
    v3 = _phylohpc(tmp_path)
    _read_only(v3)
    try:
        r = CliRunner().invoke(cli.app, ["adopt", str(v3)])
    finally:
        v3.chmod(0o755)
    assert r.exit_code == 2 and "ERROR" in r.output and "Traceback" not in r.output
    assert not (v3 / "druid.yaml").exists()
