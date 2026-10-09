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


# ---- Task 2: stage table -----------------------------------------------------------------

def step1_outputs(outdir: Path) -> None:
    """search done for tfs.A (hits, clustered), tfs.B (no hits), tfs.C_x (hits, NOT clustered;
    the fixture's clusters/tfs.C_x.HG1.fasta has no _cluster.tsv). slc.NEW, cal.Trail: nothing."""
    s = outdir / "search"
    s.mkdir(parents=True, exist_ok=True)
    for fam, fasta in (("tfs.A", ">a\nMK\n"), ("tfs.B", ""), ("tfs.C_x", ">c\nMK\n")):
        for suf in (".domains.csv", ".domains_ummerged.csv", ".genes.list"):
            (s / f"{fam}{suf}").write_text("")
        (s / f"{fam}.domains.fasta").write_text(fasta)
    (outdir / "clusters" / "tfs.A_cluster.tsv").write_text("HG1\ta\nHG11\tb\n")


def step1_tools():
    """Fake the step1 tools in the cli fixture's bin (preflight only checks they are on PATH)."""
    for t in ("hmmsearch", "hmmfetch", "bedtools", "samtools", "diamond", "mcl"):
        p = _state["bin"] / t
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR)


def test_stage_table_order_and_units(results_tree):
    cfg, _ = results_tree
    assert core.STAGES == ["search", "cluster", "align", "tree", "possvm_prev", "generax",
                           "gxsup", "possvm"]
    assert core.FAMILY_STAGES == ["search", "cluster"] and core.STAGES[2:] == core.HG_STAGES
    assert [core.unit(s) for s in ("search", "cluster", "align")] == ["families", "families", "HGs"]
    assert all(core.applicable(cfg, st) for st in core.FAMILY_STAGES)


def test_family_done_and_ready(results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    d = core.family_done(cfg, FAMS)
    assert d["search"] == {"tfs.A", "tfs.B", "tfs.C_x"}
    assert d["no_hits"] == {"tfs.B"} and d["hits"] == {"tfs.A", "tfs.C_x"}
    assert d["cluster"] == {"tfs.A", "tfs.B"}                       # _cluster.tsv, or no hits
    assert core.ready_set(cfg, "search", sorted(FAMS) + ["slc.NOPE"]) == FAMS
    assert core.ready_set(cfg, "cluster", FAMS) == {"tfs.A", "tfs.C_x"}
    assert [core.inputs_ready(cfg, "cluster", f) for f in ("tfs.C_x", "tfs.B", "slc.NEW")] == \
        [True, False, False]
    assert core.hg_fasta_families(cfg) == {"tfs.A", "tfs.B", "tfs.C_x"}


def test_family_stage_inputs_and_publish(results_tree):
    cfg, root = results_tree
    assert core.stage_inputs(cfg, "search", "slc.NEW") == [root / "gene_families_searchinfo.csv",
                                                           root / "input.fasta"]
    hm = dataclasses.replace(cfg, params={**cfg.params, "hmm_dir": str(root / "hmms")})
    assert core.stage_inputs(hm, "search", "slc.NEW")[-1] == root / "hmms"
    assert core.stage_inputs(cfg, "cluster", "slc.NEW") == [cfg.outdir / "search/slc.NEW.domains.fasta"]
    assert core.publish_patterns("search", "slc.NEW") == (
        ["slc.NEW.domains.csv", "slc.NEW.domains_ummerged.csv", "slc.NEW.genes.list"],
        "slc.NEW.domains.fasta")
    assert core.publish_patterns("cluster", "slc.NEW") == (["slc.NEW.HG*.fasta"], "slc.NEW_cluster.tsv")
    assert core.publish_dir(cfg, "search") == cfg.outdir / "search"
    assert core.publish_dir(cfg, "cluster") == cfg.outdir / "clusters"


def test_family_resources(results_tree):
    cfg, _ = results_tree
    assert core.resources(cfg, "search", "slc.NEW", {}) == core.Res(4, 500, 5, "normal", None)
    assert core.resources(cfg, "cluster", "slc.NEW", {}) == core.Res(4, 300, 10, "normal", None)
    two = dataclasses.replace(cfg, params={**cfg.params, "s1_ncpu": 2, "s2_ncpu": 8})
    assert (core.resources(two, "search", "x.y", {}).cpus,
            core.resources(two, "cluster", "x.y", {}).cpus) == (2, 8)


def test_validate_family_stages(results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    e = core.validate(cfg, "search", ["tfs.A", "slc.NEW", "slc.NOPE"], set())
    assert (e["unknown"], e["output_exists"], e["input_missing"]) == (["slc.NOPE"], ["tfs.A"], [])
    e = core.validate(cfg, "cluster", ["tfs.A", "tfs.C_x", "slc.NEW"], {"tfs.A"})
    assert e["output_exists"] == ["tfs.A", "tfs.C_x"]     # C_x: HG FASTAs on disk, no _cluster.tsv
    assert e["input_missing"] == ["slc.NEW"] and e["queued"] == ["tfs.A"]


def test_validate_family_duplicates_proceed(results_tree):
    cfg, root = results_tree
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "NEW\tPF_N\t1.1\t3\tGA\tslc\tslc\n")     # duplicate: a warning only
    assert not any(core.validate(cfg, "search", ["slc.NEW"], set()).values())


def test_passes_is_the_expected_hgs_rule(results_tree):
    cfg, _ = results_tree
    clu = cfg.outdir / "clusters"
    (clu / "tfs.D.HG1.fasta").write_text("".join(f">s{i}\nAA\n" for i in range(8)))        # 8 identical
    (clu / "tfs.D.HG2.fasta").write_text("".join(f">s{i}\n{'A' * i}\n" for i in range(1, 6)))
    for ms, md in ((2, 1), (5, 1), (5, 4)):
        exp = report_status.expected_hgs(str(cfg.outdir), min_seqs=ms, min_distinct=md)
        rule = {f.name[:-6] for f in clu.glob("*.HG*.fasta") if report_status.passes(str(f), ms, md)}
        assert exp == rule
    assert report_status.passes(str(clu / "tfs.D.HG2.fasta"), 5, 4)
    assert not report_status.passes(str(clu / "tfs.D.HG1.fasta"), 5, 4)
