"""prepare: input.fasta (prefix only in the copy), trees, species_info; refusals write nothing."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from druid import cli, core, model, paths, prepare, project, yamledit
from tests.conftest import GENEFAM

CLADES = {"Hsap": "Chordata", "Zzz": "Ctenophora"}
TAX = ("Abcd\tAbcd sp\t1\t1\t1\tMetazoa, Foo\tsrc\t1\tMT\tNA\n"
       "Wxyz\tWxyz sp\t1\t1\t1\tMetazoa, Ctenophora, Bar\tsrc\t1\tMT\tNA\n"
       "Hsap\tHomo sapiens\t1\t1\t1\tMetazoa, Chordata\tsrc\t1\tMT\tNA\n"
       "Zzzz\tZzzz sp\t1\t1\t1\tMetazoa, Qux\tsrc\t1\tMT\tNA\n")
TREE = "((Abcd:1,Wxyz:1)n1:1,(Hsap:1,Zzzz:1)n2:1)R;"


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "p"
    project.init(root, "23/10/2026")
    paths.use(root)
    prot = tmp_path / "prot"
    prot.mkdir()
    (prot / "Abcd.faa").write_text(">XP_1 desc\nMKV\n>XP_2\nMM\n")
    (prot / "Wxyz.faa").write_text(">Wxyz_7\nAA\n>other\nCC")       # no trailing newline
    (prot / "Hsap.faa").write_bytes(b">h1\r\nMK\r\n\r\n>h2\r\nMM\r\n")
    (prot / "Zzzz.faa").write_text(">z1\nM\n")
    (root / "data" / "tax.tsv").write_text(TAX)
    (root / "data" / "families.csv").write_text(GENEFAM)
    for f in ("base_tree.binary.newick", "base_tree.newick"):
        (root / "data" / f).write_text(TREE)
    yamledit.update_config({("proteomes_dir",): str(prot), ("proteome_glob",): "{sp}.faa",
                            ("taxonomy",): "data/tax.tsv", ("species",): ["Wxyz", "Abcd", "Hsap"]})
    return root, prot


def _go(extra=None):
    raw = paths.read_raw()
    cfg = core.config_from_raw(raw)
    notes = []
    out = prepare.run(raw, cfg, paths.project_root(), notes)
    cfg.params.update({k: Path(cfg.params[k]) for k in ("infasta", "SPECIES_TREE", "ORIGIN_TREE")})
    return out, cfg, notes


def _snap(root):
    return {str(f): (f.read_bytes(), f.stat().st_mtime_ns) for f in (root / "data").iterdir() if f.is_file()}


def test_prepare_concat_order_and_prefix(proj):
    root, prot = proj
    src = prot / "Abcd.faa"
    st = src.stat()
    before = src.read_bytes()
    _out, cfg, _ = _go()
    assert cfg.params["infasta"].read_text() == (
        ">Wxyz_7\nAA\n>Wxyz_other\nCC\n"             # species: order, newline guaranteed
        ">Abcd_XP_1 desc\nMKV\n>Abcd_XP_2\nMM\n"
        ">Hsap_h1\nMK\n>Hsap_h2\nMM\n")              # CRLF stripped, blank line dropped
    assert src.read_bytes() == before and src.stat().st_mtime_ns == st.st_mtime_ns


def test_already_prefixed_untouched(proj):
    _out, cfg, _ = _go()
    assert ">Wxyz_7\n" in cfg.params["infasta"].read_text()
    assert ">Wxyz_Wxyz_7" not in cfg.params["infasta"].read_text()


def test_concat_no_trailing_newline_crlf(proj):
    _out, cfg, _ = _go()
    text = cfg.params["infasta"].read_text()
    assert "\r" not in text and text.endswith("\n") and "\n\n" not in text and ">Wxyz_other\nCC\n>Abcd" in text


def test_missing_file_blocks_and_keeps_old(proj):
    root, prot = proj
    _out, cfg, _ = _go()
    fa = cfg.params["infasta"]
    old = fa.read_text()
    (prot / "Abcd.faa").unlink()
    with pytest.raises(prepare.PrepareError, match="Abcd"):
        _go()
    assert fa.read_text() == old
    assert not list((root / ".druid" / "tmp").glob("*"))


def test_refuses_locked_and_species_locked(proj):
    root, _ = proj
    cfg = core.config_from_raw(paths.read_raw())
    snap = _snap(root)
    raw = paths.read_raw()
    raw["prepare"] = "locked"
    with pytest.raises(prepare.PrepareError, match="locked"):
        prepare.run(raw, cfg, root)
    yamledit.update_config({("species_locked",): True})
    with pytest.raises(prepare.PrepareError, match="locked"):
        prepare.run(paths.read_raw(), cfg, root)
    assert _snap(root) == snap


def test_trees_written_only_when_switch_on(proj):
    yamledit.update_config({("params", "origins"): False, ("params", "run_generax"): False})
    root = paths.project_root()
    snap = _snap(root)
    out, cfg, _ = _go()
    assert cfg.params["SPECIES_TREE"] not in out and cfg.params["ORIGIN_TREE"] not in out
    after = _snap(root)
    assert all(after[k] == v for k, v in snap.items() if "tree" in os.path.basename(k)), \
        [k for k, v in snap.items() if "tree" in os.path.basename(k) and after[k] != v]
    assert cfg.params["infasta"] in out
    yamledit.update_config({("params", "origins"): True})
    out, cfg, _ = _go()
    t = cfg.params["SPECIES_TREE"].read_text()
    assert "Zzzz" not in t and "Abcd" in t and cfg.params["ORIGIN_TREE"].is_file()
    assert cfg.params["SPECIES_TREE"] in out and cfg.params["ORIGIN_TREE"] in out


def test_species_info_clade_rules(proj):
    yamledit.update_config({("species",): ["Abcd", "Wxyz", "Hsap"]})
    _out, cfg, _ = _go()
    rows = [l.split("\t") for l in model.species_info_path(cfg).read_text().splitlines()]
    assert rows == [["Abcd", "Abcd sp", "Other"],
                    ["Wxyz", "Wxyz sp", "Ctenophora"],            # taxonomy element in the shipped column
                    ["Hsap", "Homo sapiens", "Chordata"]]         # the shipped row


def test_source_dirs_read_only(proj, tmp_path):
    root, prot = proj
    tax = root / "data" / "tax.tsv"
    os.chmod(tax, 0o444)
    for f in prot.iterdir():
        os.chmod(f, 0o444)
    os.chmod(prot, 0o555)
    try:
        out, _cfg, _ = _go()
    finally:
        os.chmod(prot, 0o755)
    assert out and all(root in p.parents for p in out)


def test_cli_prepare_error_exit_2(proj):
    root, prot = proj
    (prot / "Abcd.faa").unlink()
    r = CliRunner().invoke(cli.app, ["--project", str(root), "prepare"])
    assert r.exit_code == 2 and "ERROR: cannot prepare" in r.output and "Abcd" in r.output


def test_cli_prepare_ok(proj):
    root, _ = proj
    r = CliRunner().invoke(cli.app, ["--project", str(root), "prepare"])
    assert r.exit_code == 0, r.output
    assert "input.fasta" in r.output and "species_info.tsv" in r.output
