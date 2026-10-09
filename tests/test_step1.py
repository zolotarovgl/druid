"""step1 stages (search, cluster): family ids, stage table, stage scripts, model, CLI, TUI."""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import os
import stat
import sys
from pathlib import Path

import pytest
import yaml

import report_status
from phylocli import core, history, model, runner
from phylocli import phylo as cli_mod
from phylocli.tests.test_cli import _state, calls_txt, cli, dry_dir, runs_dir  # noqa: F401  (fixture)

FAMS = {"tfs.A", "tfs.B", "tfs.C_x", "slc.NEW", "cal.Trail"}


def _cfg():
    return core.load_config(os.environ["PHYLOCLI_CONFIG"])


def _raw():
    return yaml.safe_load(open(os.environ["PHYLOCLI_CONFIG"]).read())


# ---- Task 1: family ids ------------------------------------------------------------------

def test_parse_genefam_trailing_tab_and_blank_lines(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("A\tPF\t1.1\t3\tGA\tTF\ttfs\n\n   \nCarb\tPF\t1.1\t3\tGA\tcalcium\tcal\t\n")
    assert core.parse_genefam(p) == (["tfs.A", "cal.Carb"], [])


def test_parse_genefam_duplicates(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("SLC44\tCholine_transpo\t1.1\t3\tGA\tneural\tslc\n"
                 "Synapsin\tSynapsin\t1.1\t3\tGA\tneural\tneu\n"
                 "SLC44\tCholine_transpo\t1.1\t3\tGA\tneural\tslc\n"
                 "Synapsin\tSynapsin,Synapsin_C\t1.1\t3\tGA\tneural\tneu\n"
                 "CSD\tCSD\t1.1\t3\tGA\tRBP\trbp\n"
                 "CSD\tCSD\t1.1\t3\tGA\tTF\ttfs\n")
    ids, dups = core.parse_genefam(p)
    assert ids == ["slc.SLC44", "neu.Synapsin", "rbp.CSD", "tfs.CSD"]
    assert dups == ["neu.Synapsin", "slc.SLC44"]           # rbp.CSD / tfs.CSD are different ids
    assert core.name_collisions(p) == {"CSD": (["rbp", "tfs"], "tfs")}   # the last CSD row is tfs


def test_family_ids_fixture(results_tree):
    cfg, _ = results_tree
    assert core.family_ids(cfg) == FAMS


def test_duplicates_and_name_collisions_are_warnings(results_tree):
    cfg, root = results_tree
    assert core.family_warnings(cfg) == []
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "A\tPF_A2\t1.1\t3\tGA\tTF\ttfs\n"      # duplicate id tfs.A
                 + "NEW\tPF_N2\t1.1\t3\tGA\tTF\ttfs\n")                   # name NEW: slc and tfs
    assert core.family_ids(cfg) == FAMS | {"tfs.NEW"}          # no error; each id once
    w = core.family_warnings(cfg)
    assert w == [
        f"warning: duplicate family ids in {g} (1): tfs.A; the last row of each is used "
        "(main.py hmmsearch keys rows by name, the last row wins)",
        "warning: family name NEW is listed under 2 prefixes (slc, tfs); hmmsearch keys rows by "
        "name, so slc.NEW's hits are written as tfs.NEW.* and slc.NEW looks like \"no hits\""]
    assert core.family_warnings(cfg, collisions=False) == w[:1]


def test_family_ids_missing_file(results_tree, tmp_path):
    cfg, _ = results_tree
    cfg = dataclasses.replace(cfg, params={**cfg.params, "genefam_info": str(tmp_path / "none.csv")})
    with pytest.raises(core.FamilyError, match="genefam file not found"):
        core.family_ids(cfg)
    assert core.family_ids(cfg, strict=False) == set()


def test_config_step1_params():
    raw = yaml.safe_load((core.ROOT / "phylocli/config.yaml").read_text())
    p = raw["params"]
    assert (p["genefam_info"], p["infasta"], p["pfam_db"], p["hmm_dir"]) == (
        "data/gene_families_searchinfo.csv", "data/input.fasta",
        "/users/asebe/xgraubove/data/pfam/Pfam-A.hmm", None)
    assert (p["domain_expand"], p["s1_ncpu"], p["s2_ncpu"], p["max_n"], p["s2_inflation"]) == \
        (30, 4, 4, 2000, 1.1)
    cfg = core.config_from_raw(raw)
    assert cfg.params["genefam_info"] == str(core.ROOT / "data/gene_families_searchinfo.csv")
    assert cfg.params["infasta"] == str(core.ROOT / "data/input.fasta")
    assert cfg.params["hmm_dir"] is None


def test_set_hmm_dir_and_inflation():
    raw = yaml.safe_load((core.ROOT / "phylocli/config.yaml").read_text())
    notes = core.apply_sets(raw, ["hmm_dir=/x/hmms", "s2_inflation=1.4"])
    assert raw["params"]["hmm_dir"] == "/x/hmms" and raw["params"]["s2_inflation"] == 1.4
    assert notes == ["set hmm_dir=/x/hmms (was None)", "set s2_inflation=1.4 (was 1.1)"]
