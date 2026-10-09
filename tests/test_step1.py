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
from phylocli.tests.test_history import hist  # noqa: E402,F401  (fixture)

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


# ---- Task 3: stage scripts -----------------------------------------------------------------

# Stand-in for phylogeny/main.py (the worktree's submodule is not checked out). hmmsearch
# behaves like helper/hmmsearch.py: the row is looked up by NAME (last row wins) and outputs are
# named after THAT row's prefix; an unknown name writes nothing and exits 0.
FAKE_MAIN = r'''
import os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_ARGS"], "a") as fh:
    fh.write(" ".join(a) + "\n")
if a[0] == "hmmsearch":
    mode = os.environ.get("FAKE_HMM", "hits")
    if "--hmm_dir" in a:              # helper/hmmsearch.py fetches missing models INTO hmm_dir
        with open(os.path.join(a[a.index("--hmm_dir") + 1], "fetched.hmm"), "w") as fh:
            fh.write("fetched\n")
    if mode == "notfound":
        sys.exit(0)
    fam, gene = a[5], a[a.index("-g") + 1]
    rows = [l.strip().split("\t") for l in open(gene) if l.strip()]
    out = [r[-1] for r in rows if r[0] == fam][-1] + "." + fam
    if mode == "hits":
        open(out + ".domains.fasta", "w").write(">s1\nMKV\n")
        open(out + ".domains.csv", "w").write("s1\t1\t3\tPF\n")
        open(out + ".domains_ummerged.csv", "w").write("s1\t1\t3\tPF\n")
        open(out + ".genes.list", "w").write("s1\n")
    else:                             # nohits: helper writes an empty genes.list and stops
        open(out + ".genes.list", "w").write("")
elif a[0] == "cluster":               # HG by the first letter of the sequence name: a b c d
    fasta, out = a[a.index("-f") + 1], a[a.index("--out_file") + 1]
    names = [l[1:].split()[0] for l in open(fasta) if l.startswith(">")]
    with open(out, "w") as fh:
        for n in names:
            fh.write(f"HG{'abcd'.index(n[0]) + 1}\t{n}\n")
'''

FAKE_SAMTOOLS = r'''
import sys
assert sys.argv[1] == "faidx"
path, ids = sys.argv[2], sys.argv[3:]
recs, cur = {}, None
for line in open(path):
    line = line.rstrip("\n")
    if line.startswith(">"):
        cur = line[1:].split()[0]
        recs[cur] = []
    elif cur is not None:
        recs[cur].append(line)
if not ids:
    with open(path + ".fai", "w") as fh:
        fh.write("".join(f"{k}\t{len(''.join(v))}\n" for k, v in recs.items()))
else:
    sys.stdout.write("".join(f">{i}\n" + "\n".join(recs[i]) + "\n" for i in ids))
'''

DOMAINS = ("".join(f">a{i}\nMKA\n" for i in range(1, 2))               # HG1: 1 seq
           + "".join(f">b{i}\nMK{'B' * i}\n" for i in range(1, 5))     # HG2: 4 seqs
           + "".join(f">c{i}\nMK{'C' * i}\n" for i in range(1, 6))     # HG3: 5 distinct
           + "".join(f">d{i}\nMKDD\n" for i in range(1, 6)))           # HG4: 5 identical


def stage_project(tmp_path, monkeypatch) -> Path:
    """PROJECT_DIR with the stub main.py and the REAL workflow/ (drop_small_hgs.py,
    report_status.py); PATH with a real `python` and a fake `samtools`. The stage scripts run
    are the real phylocli/stages/*.sh (runner.STAGES_DIR is left alone)."""
    proj = tmp_path / "proj"
    (proj / "phylogeny").mkdir(parents=True)
    (proj / "phylogeny" / "main.py").write_text(FAKE_MAIN)
    (proj / "workflow").symlink_to(core.ROOT / "workflow")
    b = tmp_path / "s1bin"
    b.mkdir()
    (b / "python").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (b / "samtools.py").write_text(FAKE_SAMTOOLS)
    (b / "samtools").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{b}/samtools.py" "$@"\n')
    for n in ("python", "samtools"):
        (b / n).chmod((b / n).stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_ARGS", str(tmp_path / "args.txt"))
    monkeypatch.setattr(runner, "ROOT", proj)              # stage_env: PROJECT_DIR
    return proj


def _spy_replace(monkeypatch) -> list:
    order, real = [], os.replace
    monkeypatch.setattr(runner.os, "replace", lambda a, b: (order.append(Path(b).name), real(a, b)))
    return order


def test_stage_env_none_is_empty(results_tree):
    cfg, _ = results_tree
    env = runner.stage_env(cfg, "search", "slc.NEW", 4)
    assert env["hmm_dir"] == "" and env["pfam_db"].endswith("Pfam-A.hmm") and env["ID"] == "slc.NEW"


def test_search_publishes_marker_last(results_tree, tmp_path, monkeypatch):
    cfg, root = results_tree
    stage_project(tmp_path, monkeypatch)
    order = _spy_replace(monkeypatch)
    assert runner.run_one(cfg, "search", "slc.NEW", tmp_path / "work") == 0
    assert order == ["slc.NEW.domains.csv", "slc.NEW.domains_ummerged.csv", "slc.NEW.genes.list",
                     "slc.NEW.domains.fasta"]
    assert (tmp_path / "args.txt").read_text().split() == [
        "hmmsearch", "-f", "input.fasta", "-g", "gene_families_searchinfo.csv", "NEW", "-o", ".",
        "--pfam_db", str(root / "Pfam-A.hmm"), "--domain_expand", "30", "--ncpu", "4"]
    assert core.family_done(cfg, {"slc.NEW"})["hits"] == {"slc.NEW"}
    assert not (tmp_path / "work" / "slc.NEW").exists()


def test_search_trailing_tab_family(results_tree, tmp_path, monkeypatch):
    cfg, _ = results_tree
    stage_project(tmp_path, monkeypatch)
    assert runner.run_one(cfg, "search", "cal.Trail", tmp_path / "work") == 0
    assert (cfg.outdir / "search/cal.Trail.domains.fasta").read_text() == ">s1\nMKV\n"


def test_search_no_hits_publishes_empty_marker(results_tree, tmp_path, monkeypatch):
    cfg, _ = results_tree
    stage_project(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_HMM", "nohits")
    assert runner.run_one(cfg, "search", "slc.NEW", tmp_path / "work") == 0
    d = core.family_done(cfg, {"slc.NEW"})
    assert d["no_hits"] == {"slc.NEW"} and d["cluster"] == {"slc.NEW"}


def test_search_name_under_two_prefixes_warns_and_publishes_empty(results_tree, tmp_path, monkeypatch,
                                                                   capfd):
    cfg, root = results_tree
    stage_project(tmp_path, monkeypatch)
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "Dup\tPF_D\t1.1\t3\tGA\tRBP\trbp\nDup\tPF_D\t1.1\t3\tGA\tTF\ttfs\n")
    assert runner.run_one(cfg, "search", "rbp.Dup", tmp_path / "work") == 0   # hits went to tfs.Dup.*
    err = capfd.readouterr().err
    assert "WARNING: family name Dup" in err and "rbp.Dup's hits are written as tfs.Dup.*" in err
    s = cfg.outdir / "search"
    assert (s / "rbp.Dup.domains.fasta").read_text() == ""                   # step1.nf behaviour
    assert core.family_done(cfg, {"rbp.Dup"})["no_hits"] == {"rbp.Dup"}
    assert not list(s.glob("tfs.Dup.*"))                                      # not this task's id
    monkeypatch.setenv("FAKE_HMM", "notfound")                                # name not found at all
    assert runner.run_one(cfg, "search", "slc.NEW", tmp_path / "work") == 0
    assert "WARNING: main.py hmmsearch wrote nothing named slc.NEW.*" in capfd.readouterr().err
    assert core.family_done(cfg, {"slc.NEW"})["no_hits"] == {"slc.NEW"}


def test_search_hmm_dir_is_never_written(results_tree, tmp_path, monkeypatch):
    cfg, root = results_tree
    stage_project(tmp_path, monkeypatch)
    hmms = root / "hmms"
    hmms.mkdir()
    (hmms / "PF_N.hmm").write_text("HMMER3/f\n")
    cfg = dataclasses.replace(cfg, params={**cfg.params, "hmm_dir": str(hmms)})
    assert runner.run_one(cfg, "search", "slc.NEW", tmp_path / "work") == 0
    assert sorted(p.name for p in hmms.iterdir()) == ["PF_N.hmm"]       # fetched.hmm went to the copy
    assert "--hmm_dir hmm_dir.work" in (tmp_path / "args.txt").read_text()


def _cluster_cfg(results_tree, domains: str):
    cfg, _ = results_tree
    cfg = dataclasses.replace(cfg, params={**cfg.params, "min_seqs": 5, "min_distinct": 4})
    (cfg.outdir / "search").mkdir(exist_ok=True)
    (cfg.outdir / "search/slc.NEW.domains.fasta").write_text(domains)
    return cfg


def test_cluster_drops_small_hgs_keeps_full_tsv(results_tree, tmp_path, monkeypatch, capfd):
    cfg = _cluster_cfg(results_tree, DOMAINS)
    stage_project(tmp_path, monkeypatch)
    order = _spy_replace(monkeypatch)
    assert runner.run_one(cfg, "cluster", "slc.NEW", tmp_path / "work") == 0
    assert "slc.NEW: skipped 3 HGs below min_seqs/min_distinct (5/4); kept 1" in capfd.readouterr().out
    assert order == ["slc.NEW.HG3.fasta", "slc.NEW_cluster.tsv"]          # marker last
    clu = cfg.outdir / "clusters"
    tsv = (clu / "slc.NEW_cluster.tsv").read_text().splitlines()
    assert len(tsv) == 15 and sorted({l.split("\t")[0] for l in tsv}) == ["HG1", "HG2", "HG3", "HG4"]
    assert sorted(p.name for p in clu.glob("slc.NEW.HG*.fasta")) == ["slc.NEW.HG3.fasta"]
    assert (clu / "slc.NEW.HG3.fasta").read_text().count(">") == 5
    # step2 sees exactly the files on disk
    assert {h for h in core.expected(cfg) if h.startswith("slc.NEW.")} == {"slc.NEW.HG3"}
    assert [h for h in cli_mod._missing(cfg, "align", None) if h.startswith("slc.NEW.")] == ["slc.NEW.HG3"]


def test_cluster_all_small_publishes_tsv_only(results_tree, tmp_path, monkeypatch):
    cfg = _cluster_cfg(results_tree, DOMAINS.split(">c1")[0])                  # HG1 + HG2 only
    stage_project(tmp_path, monkeypatch)
    assert runner.run_one(cfg, "cluster", "slc.NEW", tmp_path / "work") == 0
    assert (cfg.outdir / "clusters/slc.NEW_cluster.tsv").is_file()
    assert not list((cfg.outdir / "clusters").glob("slc.NEW.HG*.fasta"))
    assert core.family_done(cfg, {"slc.NEW"})["cluster"] == {"slc.NEW"}


# ---- Task 4: data layer ------------------------------------------------------------------

S1_LOG = ("SEARCH\ttfs.A\tFAILED\t137\t1\t4\t500 MB\t5m\t-\t2m\t/w/s1/1\t2026-09-20 10:01:00.000\n"
          "SEARCH\ttfs.A\tCOMPLETED\t0\t2\t4\t1 GB\t15m\t300 MB\t3m\t/w/s1/2\t2026-09-20 10:05:00.000\n"
          "CLUSTER\ttfs.A\tCOMPLETED\t0\t1\t4\t300 MB\t10m\t100 MB\t1m\t/w/s1/3\t2026-09-20 10:10:00.000\n"
          "CLUSTER\ttfs.ZZ\tCOMPLETED\t0\t1\t4\t300 MB\t10m\t100 MB\t1m\t/w/s1/4\t2026-09-20 10:11:00.000\n")
SACCT_S1 = ("12345_0|OUT_OF_MEMORY||00:03:00|0:125\\n12345_0.batch|OUT_OF_MEMORY|512000K|00:03:00|0:125\\n"
            "12345_1|COMPLETED||00:01:00|0:0\\n")


def test_family_attempts_read_step1_runs(hist):
    _cli, cfg, _calls, tmp = hist
    (tmp / "nflog/run_s1.tsv").write_text(S1_LOG)
    atts = history.family_attempts(cfg, "tfs.A")
    assert [(a.stage, a.attempt, a.status, a.run) for a in atts] == [
        ("search", 1, "FAILED", "run_s1"), ("search", 2, "COMPLETED", "run_s1"),
        ("cluster", 1, "COMPLETED", "run_s1")]
    assert history.latest_by_stage(atts)["search"].mem == "1 GB"
    assert not any(a.hg == "tfs.ZZ" for a in history.family_attempts(cfg))   # not in the genefam file
    assert all(a.stage in core.HG_STAGES for a in history.attempts(cfg))     # step2 history unchanged


def test_live_family_tags(cli, monkeypatch):
    monkeypatch.setenv("FAKE_SQUEUE", "999|nf-SEARCH_(slc.NEW)\n998|nf-CLUSTER_(tfs.C_x)\n")
    assert model.live(set()) == {"search": {"slc.NEW"}, "cluster": {"tfs.C_x"}}


def test_stage_rows_with_families(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    rows, _known, _d = model.stage_rows(_cfg(), core.expected(_cfg()), FAMS)
    assert [r.stage for r in rows] == core.STAGES
    by = {r.stage: r for r in rows}
    assert (by["search"].done, by["search"].ready, by["search"].blocked, by["search"].total) == (3, 2, 0, 5)
    assert (by["cluster"].done, by["cluster"].ready, by["cluster"].blocked, by["cluster"].no_hits) == \
        (2, 1, 2, 1)
    assert [r.stage for r in model.stage_rows(_cfg(), core.expected(_cfg()))[0]] == core.HG_STAGES


def test_family_states(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    fs = model.family_states(_cfg(), FAMS, {})
    assert fs["search"] == {"tfs.A": 0, "tfs.B": 0, "tfs.C_x": 0, "slc.NEW": 2, "cal.Trail": 2}
    assert fs["cluster"] == {"tfs.A": 0, "tfs.B": 0, "tfs.C_x": 2, "slc.NEW": 3, "cal.Trail": 3}
    assert model.family_states(_cfg(), FAMS, {"search": {"slc.NEW"}})["search"]["slc.NEW"] == 1
    assert model.family_states(_cfg(), set(), {}) == {}


def test_group_rows_with_families(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    exp = core.expected(_cfg())
    rows, _k = model.group_rows(_cfg(), exp, "category", fams=FAMS)
    by = {r.group: r for r in rows}
    assert list(by) == ["ALL", "tfs", "cal", "slc"]            # cal, slc: families, no HG yet
    srows = {s.stage: s for s in model.stage_rows(_cfg(), exp, FAMS)[0]}
    for st in core.STAGES:                                     # ALL == the CLI summary, all 8 stages
        s = srows[st]
        assert by["ALL"].per_stage[st] == (s.done, s.running, s.ready, s.blocked)
    assert (by["ALL"].total, by["ALL"].n_fams) == (3, 5)
    assert (by["tfs"].total, by["tfs"].n_fams, by["tfs"].per_stage["search"]) == (3, 3, (3, 0, 0, 0))
    assert (by["slc"].total, by["slc"].per_stage["search"], by["slc"].per_stage["align"]) == \
        (0, (0, 0, 1, 0), (0, 0, 0, 0))
    fam = {r.group: r for r in model.group_rows(_cfg(), exp, "family", fams=FAMS)[0]}
    assert list(fam) == ["ALL", "tfs.A", "tfs.C_x", "cal.Trail", "slc.NEW", "tfs.B"]
    assert (fam["tfs.B"].total, fam["tfs.B"].per_stage["cluster"]) == (0, (1, 0, 0, 0))   # no hits
    for st in core.FAMILY_STAGES:                              # family rows sum to ALL
        assert tuple(sum(r.per_stage[st][i] for g, r in fam.items() if g != "ALL")
                     for i in range(4)) == fam["ALL"].per_stage[st]


def test_select_and_plan_family_ids(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    sel = model.select(_cfg(), "cluster", ["slc.NEW", "tfs.C_x"])
    assert sel.selected == ["tfs.C_x"] and sel.notes == ["skipped 1 families without inputs"]
    assert model.plan(_cfg(), "cluster", sel).errors == {"output_exists": ["tfs.C_x"]}
    with pytest.raises(model.ModelError) as e:
        model.select(_cfg(), "search", ["slc.NOPE"])
    assert e.value.code == 2 and "unknown (1): slc.NOPE" in str(e.value)
    p = model.plan(_cfg(), "search", model.select(_cfg(), "search", ["slc.NEW"]))
    assert p.groups == [(core.Res(4, 500, 5, "normal", None), ["slc.NEW"])]
    assert p.notes == ["resources: step1 defaults for 1 families"]


def test_select_family_duplicates_proceed(cli, results_tree, tmp_path):
    _, root = results_tree
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "B\tPF_B\t1.1\t3\tGA\tTF\ttfs\n")
    sel = model.select(_cfg(), "search", ["slc.NEW", "tfs.B"])
    assert sel.selected == ["slc.NEW", "tfs.B"]
    gone = dataclasses.replace(_cfg(), params={**_cfg().params, "genefam_info": str(tmp_path / "x")})
    with pytest.raises(model.ModelError) as e:
        model.select(gone, "search", ["slc.NEW"])
    assert e.value.code == 1 and "genefam file not found" in str(e.value)


def test_preflight_family_tools_and_files(cli, results_tree, monkeypatch, tmp_path):
    cfg, _ = results_tree
    monkeypatch.setenv("PATH", str(_state["bin"]))
    assert "not on PATH: hmmsearch hmmfetch bedtools samtools" in model.preflight("search", cfg)
    assert "not on PATH: samtools diamond mcl" in model.preflight("cluster", cfg)
    step1_tools()
    assert model.preflight("search", cfg) is None and model.preflight("cluster", cfg) is None
    gone = dataclasses.replace(cfg, params={**cfg.params, "pfam_db": str(tmp_path / "no.hmm")})
    assert model.preflight("search", gone) == f"ERROR: not found: pfam_db={tmp_path / 'no.hmm'}"
    assert model.preflight("align", gone) is None                  # HG stages: same checks as before


def test_write_run_search_snapshots_genefam(cli, results_tree):
    cfg, root = results_tree
    raw = _raw()
    before = copy.deepcopy(raw)
    p = model.plan(cfg, "search", model.Selection(["slc.NEW"], [], set()))
    w = model.write_run(cfg, raw, p, dry_run=True)
    snap = w.run_dir / "genefam.csv"
    src = root / "gene_families_searchinfo.csv"
    assert snap.read_text() == src.read_text()
    assert yaml.safe_load((w.run_dir / "config.yaml").read_text())["params"]["genefam_info"] == str(snap)
    assert raw == before                                           # the caller's raw is not changed
    src.write_text("")                                             # edited after the submission:
    assert core.family_ids(core.load_config(w.run_dir / "config.yaml")) == FAMS   # job reads the copy
    p = model.plan(cfg, "align", model.Selection(["tfs.C_x.HG1"], [], set()))
    w = model.write_run(cfg, _raw(), p, dry_run=True)
    assert not (w.run_dir / "genefam.csv").exists()               # HG stages: no snapshot


# ---- Task 5: CLI -----------------------------------------------------------------------------

def test_summary_family_rows_first(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    out = cli(["missing"]).output.splitlines()
    assert [l.split()[0] if l.strip() else "" for l in out][:5] == ["stage", "search", "cluster", "", "align"]
    rows = {l.split()[0]: l.split()[1:6] for l in out[1:] if l.strip()}
    assert rows["search"] == ["3", "0", "2", "0", "5"]            # done running ready blocked total
    assert rows["cluster"] == ["2", "0", "1", "2", "5"]
    assert out[2].rstrip().endswith("  1 no hits")
    assert rows["align"] == ["1", "0", "2", "0", "3"]             # HG rows: same numbers as before


def test_status_ids_of_hgs_has_no_family_rows(cli, tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("tfs.A.HG1\n")
    lines = cli(["status", "--ids", str(f)]).output.splitlines()
    assert lines[0].split()[0] == "stage" and lines[1].split()[0] == "align"


def test_status_fam_matching_only_families(cli):
    r = cli(["status", "-f", "slc"])
    assert r.exit_code == 0, r.output
    line = next(l for l in r.output.splitlines() if l.split()[:1] == ["search"])
    assert line.split()[1:6] == ["0", "0", "1", "0", "1"]
    assert cli(["status", "-f", "nope"]).exit_code == 1


def test_missing_family_stages(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    assert cli(["missing", "search"]).output.split() == ["cal.Trail", "slc.NEW"]
    # tfs.C_x (HG FASTAs, no tsv) is output_exists in validate: not missing, noted on stderr
    assert [l for l in cli(["missing", "cluster"]).output.splitlines()
            if not l.startswith("skipped")] == []
    assert [l for l in cli(["missing", "cluster", "--all"]).output.splitlines()
            if not l.startswith("skipped")] == ["cal.Trail", "slc.NEW"]
    assert cli(["missing", "search", "-f", "slc"]).output.split() == ["slc.NEW"]
    r = cli(["missing", "search", "-f", "tfs.C"])
    assert r.exit_code == 1 and "no families match --fam tfs.C" in r.output
    r = cli(["missing", "cluster", "--per-fam"])
    assert r.exit_code == 2 and "--per-fam" in r.output


def test_missing_search_skips_queued(cli, monkeypatch):
    monkeypatch.setenv("FAKE_SQUEUE", "999|nf-SEARCH_(slc.NEW)\n")
    assert "slc.NEW" not in cli(["missing", "search"]).output.split()
    assert "slc.NEW" in cli(["missing", "search", "--all"]).output.split()


def test_submit_search_missing_dry_run(cli, results_tree):
    cfg, root = results_tree
    step1_outputs(cfg.outdir)
    step1_tools()
    r = cli(["submit", "search", "--missing", "-n"])
    assert r.exit_code == 0, r.output
    assert "families 2 in 1 array(s)" in " ".join(r.output.split())
    assert "resources: step1 defaults for 2 families" in r.output
    run = next(dry_dir().glob("*_search"))
    assert (run / "ids_0.txt").read_text().split() == ["cal.Trail", "slc.NEW"]
    s = (run / "array_0.sbatch").read_text()
    assert "#SBATCH --cpus-per-task=4" in s and "#SBATCH --mem=500M" in s and "#SBATCH --time=5\n" in s
    assert (run / "genefam.csv").read_text() == (root / "gene_families_searchinfo.csv").read_text()
    assert not calls_txt().exists()


def test_submit_cluster_overrides(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    (cfg.outdir / "search/slc.NEW.domains.fasta").write_text(">n\nMK\n")
    step1_tools()
    r = cli(["submit", "cluster", "slc.NEW", "-n", "--mem", "2G", "--time", "1h"])
    assert r.exit_code == 0, r.output
    s = next(dry_dir().glob("*_cluster")).joinpath("array_0.sbatch").read_text()
    assert "#SBATCH --mem=2048M" in s and "#SBATCH --time=60\n" in s and "#SBATCH --cpus-per-task=4" in s


def test_submit_search_real(cli):
    step1_tools()
    r = cli(["submit", "search", "slc.NEW"])
    assert r.exit_code == 0, r.output
    assert "submitted 12345: 1 families (4 cpus, 500M, 5 min)" in r.output
    run = next(runs_dir().glob("*_search"))
    assert yaml.safe_load((run / "config.yaml").read_text())["params"]["genefam_info"] == \
        str(run / "genefam.csv")
    assert any(l.split()[1:3] == ["search", "12345"] for l in cli(["jobs"]).output.splitlines()
               if len(l.split()) > 2)


def test_family_rows_states(cli, results_tree, monkeypatch):
    # here, not in Task 4: it submits through the CLI, which accepts `search` from this task on
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    step1_tools()
    assert cli(["submit", "search", "slc.NEW", "cal.Trail"]).exit_code == 0   # task 0 = cal.Trail
    monkeypatch.setenv("FAKE_SACCT", SACCT_S1)
    assert {r.hg: r.state for r in model.hg_rows(_cfg(), "search")} == {
        "tfs.A": "done", "tfs.B": "done", "tfs.C_x": "done", "cal.Trail": "failed", "slc.NEW": "ready"}
    assert {r.hg: r.state for r in model.hg_rows(_cfg(), "cluster")} == {
        "tfs.A": "done", "tfs.B": "done", "tfs.C_x": "ready", "cal.Trail": "blocked", "slc.NEW": "blocked"}


def test_submit_family_ids_file_set_and_cpus(cli, results_tree, tmp_path):
    step1_tools()
    f = tmp_path / "fams.txt"
    f.write_text("slc.NEW\n\ncal.Trail\n")
    r = cli(["submit", "search", "--ids", str(f), "-n", "--set", "domain_expand=50", "--cpus", "2"])
    assert r.exit_code == 0, r.output
    assert "domain_expand=50" in r.output
    run = next(dry_dir().glob("*_search"))
    assert (run / "ids_0.txt").read_text().split() == ["cal.Trail", "slc.NEW"]
    assert yaml.safe_load((run / "config.yaml").read_text())["params"]["domain_expand"] == 50
    assert "#SBATCH --cpus-per-task=2" in (run / "array_0.sbatch").read_text()
    r = cli(["submit", "cluster", "--ids", str(f), "-n"])          # no domains FASTA yet: both skipped
    assert r.exit_code == 0 and "skipped 2 families without inputs" in r.output
    assert "nothing to submit" in r.output
    r = cli(["submit", "search", "--ids", str(f), "-n", "--set", "s1_ncpu=x"])
    assert r.exit_code == 2 and "s1_ncpu" in r.output


def test_submit_family_errors(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    step1_tools()
    r = cli(["submit", "search", "tfs.A"])
    assert r.exit_code == 2 and "output_exists (1): tfs.A" in r.output and "nothing submitted" in r.output
    r = cli(["submit", "cluster", "slc.NOPE", "-n"])
    assert r.exit_code == 2 and "unknown (1): slc.NOPE" in r.output
    r = cli(["submit", "cluster", "slc.NEW", "tfs.C_x", "-n"])   # explicit: stray HG FASTA still refused
    assert r.exit_code == 2 and "output_exists (1): tfs.C_x" in r.output
    r = cli(["submit", "cluster", "--missing", "--all", "-n"])   # C_x is skipped, not refused
    assert r.exit_code == 2 and "input_missing (2): cal.Trail slc.NEW" in r.output
    assert "output_exists" not in r.output
    r = cli(["submit", "search", "--missing", "-f", "nope", "-n"])
    assert r.exit_code == 1 and "no families match --fam nope" in r.output
    assert not calls_txt().exists()


def test_submit_search_preflight(cli, monkeypatch):
    monkeypatch.setenv("PATH", str(_state["bin"]))
    r = cli(["submit", "search", "slc.NEW", "-n"])
    assert r.exit_code == 78 and "hmmsearch" in r.output


def test_duplicates_warn_and_proceed(cli, results_tree):
    _, root = results_tree
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "NEW\tPF_N\t1.1\t3\tGA\tslc\tslc\nA\tPF_A\t1.1\t3\tGA\tTF\ttfs\n")
    r = cli(["missing"])
    assert r.exit_code == 0 and "warning: duplicate family ids" in r.output and "slc.NEW tfs.A" in r.output
    firsts = [l.split()[0] for l in r.output.splitlines() if l.strip()]
    assert "search" in firsts and "align" in firsts
    step1_tools()
    r = cli(["missing", "search"])
    assert r.exit_code == 0 and "slc.NEW tfs.A" in r.output
    assert {"cal.Trail", "slc.NEW"} <= set(r.output.splitlines())             # ids still listed
    r = cli(["submit", "search", "slc.NEW", "-n"])
    assert r.exit_code == 0 and "duplicate family ids" in r.output
    assert "families 1 in 1 array(s)" in " ".join(r.output.split())
    r = cli(["status", "slc.NEW"])
    assert r.exit_code == 0 and "duplicate family ids" in r.output
    assert any(l.split()[:1] == ["search"] for l in r.output.splitlines())
    r = cli(["missing", "align"])
    assert r.exit_code == 0 and "duplicate" not in r.output                   # HG commands: silent


def test_name_collision_warnings(cli, results_tree):
    _, root = results_tree
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "NEW\tPF_N2\t1.1\t3\tGA\tTF\ttfs\n")           # NEW under slc and tfs
    msg = ("warning: family name NEW is listed under 2 prefixes (slc, tfs); hmmsearch keys rows by "
           "name, so slc.NEW's hits are written as tfs.NEW.* and slc.NEW looks like \"no hits\"")
    assert msg in cli(["status"]).output and msg in cli(["missing"]).output
    step1_tools()
    r = cli(["submit", "search", "slc.NEW", "tfs.NEW", "-n"])
    assert r.exit_code == 0 and msg in r.output
    assert "family name NEW" not in cli(["missing", "search"]).output   # collisions: summaries, TUI, submit search
    assert "family name NEW" not in cli(["submit", "cluster", "--missing", "-n"]).output


def test_status_family_rows(hist):
    cli, cfg, _calls, tmp = hist
    (tmp / "nflog/run_s1.tsv").write_text(S1_LOG)
    step1_outputs(cfg.outdir)
    r = cli(["status", "tfs.A"])
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0].split()[:3] == ["tfs.A", "(2", "HGs)"]
    rows = {l.split()[0]: l for l in lines if l.split()[:1] in (["search"], ["cluster"])}
    assert list(rows) == ["search", "cluster"]
    assert "done" in rows["search"] and "nextflow" in rows["search"] and "1 GB" in rows["search"]
    assert "done" in rows["cluster"] and "run_s1" in rows["cluster"]
    assert not any(l.split()[:1] == ["align"] for l in lines)
    r = cli(["status", "tfs.B"])
    assert "done (no hits)" in next(l for l in r.output.splitlines() if l.split()[:1] == ["cluster"])
    r = cli(["status", "tfs.A", "--history"])
    assert r.exit_code == 0 and "/w/s1/1/.command.err" in r.output and "killed: out of memory?" in r.output


# ---- Task 6: TUI -----------------------------------------------------------------------------

def _tui():
    pytest.importorskip("textual")
    from phylocli import tui
    return tui


def _calls():
    p = _state["bin"] / "calls.txt"
    return p.read_text().splitlines() if p.exists() else []


def test_tui_overview_family_cells_and_open(cli, results_tree, monkeypatch):
    tui = _tui()
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    step1_tools()
    assert cli(["submit", "search", "slc.NEW", "cal.Trail"]).exit_code == 0   # task 0 = cal.Trail
    monkeypatch.setenv("FAKE_SACCT", SACCT_S1)
    app = tui.PhyloApp(_cfg(), refresh_s=3600)
    n0 = len(_calls())

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            ov = app.query_one("#overview")
            assert [str(c.label) for c in ov.columns.values()][:5] == ["\ngroup", "\nHGs", "step1 ·\nsearch",
                                                                    "families\ncluster", "│\n│"]
            rows = {r.group: r for r in app.ov_rows}
            assert list(rows) == ["ALL", "tfs", "cal", "slc"]
            s = {x.stage: x for x in model.stage_rows(_cfg(), core.expected(_cfg()), FAMS)[0]}
            for st in core.FAMILY_STAGES:                         # same numbers as phylo status
                assert rows["ALL"].per_stage[st] == (s[st].done, s[st].running, s[st].ready, s[st].blocked)
            assert (rows["cal"].total, rows["cal"].n_fams) == (0, 1)
            ov.move_cursor(row=2, column=tui.ov_column("search"))             # cal x search
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            app.load_now()                                         # HG view: history now
            await pilot.pause()
            assert app.view == "hgs" and app.group == "cal" and app.stage == "search"
            assert app.filter == "actionable" and [r.hg for r in app.visible()] == ["cal.Trail"]  # failed
            await pilot.press("f")                                 # actionable -> failed: same family
            assert app.filter == "failed" and [r.hg for r in app.visible()] == ["cal.Trail"]
            st = app.query_one("#stages")
            assert str(st.get_cell_at((core.STAGES.index("search"), 5))) == "1"    # cal's families
            assert str(st.get_cell_at((core.STAGES.index("align"), 5))) == "0"     # cal's HGs
            text = app._detail_text("cal.Trail")
            assert "cal.Trail" in text and "0 HGs" in text and "search" in text and "align" not in text
            await pilot.press("a", "r")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, tui.ResubmitScreen) and scr.stage == "search"
            assert [(g[0], g[1].mem_mb, g[2]) for g in scr.groups] == [("OOM", 1000, ["cal.Trail"])]
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "resources: step1 defaults for 1 families" in scr._shown
            assert "array 0: 1 families" in scr._shown
            assert len(_calls()) == n0                             # dry run only
    asyncio.run(go())


def test_tui_overview_step1_step2_separator(cli, monkeypatch):
    tui = _tui()
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_S1)
    app = tui.PhyloApp(_cfg(), refresh_s=3600)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            ov = app.query_one("#overview")
            labels = [str(c.label) for c in ov.columns.values()]
            assert ov.header_height == 2
            assert labels[2:7] == ["step1 ·\nsearch", "families\ncluster", "│\n│", "step2 ·\nalign", "HGs\ntree"]
            sep = tui.ov_column("cluster") + 1
            assert tui.stage_at_column(sep) is None and tui.ov_column("align") == sep + 1
            assert all(str(ov.get_cell_at((i, sep))) == "│" for i in range(ov.row_count))
            ov.move_cursor(row=0, column=tui.ov_column("align"))               # ALL x align
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.view == "hgs" and app.stage == "align"
            await pilot.press("escape")
            await pilot.pause()
            app.stage = "tree"                                                 # the "current" stage
            ov.move_cursor(row=0, column=sep)                                  # ALL x │
            await pilot.pause()
            await pilot.press("enter")                                         # not a stage: no crash
            await pilot.pause()
            assert app.view == "hgs" and app.stage == "tree" and app.group is None
            await pilot.press("escape")
            await pilot.pause()
            ov.move_cursor(row=0, column=sep)
            app.load_now()                                                     # a refill restores...
            await pilot.pause()
            assert ov.cursor_column == tui.ov_column("align")                  # ...never onto │
    asyncio.run(go())


def test_tui_notifies_on_duplicate_ids(cli, results_tree):
    tui = _tui()
    _, root = results_tree
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "NEW\tPF_N\t1.1\t3\tGA\tslc\tslc\n")
    app = tui.PhyloApp(_cfg(), refresh_s=3600)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            msgs = [str(n.message) for n in app._notifications]
            assert any("duplicate family ids" in m and "slc.NEW" in m for m in msgs)
            assert app.view == "overview"                              # a warning; the app goes on
            assert app.ov_rows[0].n_fams == 5                       # still counted, de-duplicated
            assert "search" in [str(c.label).split("\n")[-1] for c in app.query_one("#overview").columns.values()]
    asyncio.run(go())


def test_status_hg_survives_malformed_genefam(cli, monkeypatch):
    def boom(path):
        raise ValueError("malformed genefam row")
    monkeypatch.setattr(core, "parse_genefam", boom)
    with pytest.raises(ValueError):                                # the family parse really fails
        core.family_ids(_cfg(), strict=False)
    r = cli(["status", "tfs.A.HG11"])
    assert r.exit_code == 0, r.output
    assert "tfs.A.HG11" in r.output


# ---- Task 7: step1.nf ------------------------------------------------------------------------

def test_step1_nf_calls_stage_scripts():
    nf = (core.ROOT / "step1.nf").read_text()
    assert "exec bash ${projectDir}/phylocli/stages/search.sh genefam.csv input.fasta" in nf
    assert "exec bash ${projectDir}/phylocli/stages/cluster.sh ${domains_fasta}" in nf
    assert "min_seqs=${params.min_seqs} min_distinct=${params.min_distinct}" in nf
    assert 'path("${pref}.${family}.*.fasta", optional: true)' in nf
    assert "python ${projectDir}/phylogeny/main.py" not in nf          # bodies live in the scripts
    assert "def familyIsDone" in nf and "stageInMode 'copy'" in nf      # skip logic / staging kept


def _set_nf_history(tmp_path, text):
    nf = tmp_path / "nf_active"
    (nf / ".nextflow").mkdir(parents=True, exist_ok=True)
    (nf / ".nextflow/history").write_text(text)
    raw = _raw()
    raw["nextflow_dir"] = str(nf)
    Path(os.environ["PHYLOCLI_CONFIG"]).write_text(yaml.safe_dump(raw))


def test_submit_warns_when_step1_nf_active(cli, results_tree, tmp_path):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    step1_tools()
    _set_nf_history(tmp_path, "2026-10-09 09:00:00\t-\tlive_run\t-\th3\tu1\t"
                              "nextflow run -ansi-log false step1.nf -resume\n")
    warn = ("warning: a step1.nf Nextflow run appears to be active (live_run); running step1.nf "
            "and phylocli search/cluster at the same time can mix two clusterings of one family")
    for stage in ("search", "cluster"):
        r = cli(["submit", stage, "--missing", "-n"])
        assert warn in r.output, (stage, r.output)
        assert r.exit_code != 78                                  # a warning, not a refusal
    # finished step1.nf run, or an active step2.nf run: no warning
    _set_nf_history(tmp_path, "2026-10-09 09:00:00\t1m\tdone_run\tOK\th3\tu1\tnextflow run step1.nf\n"
                              "2026-10-09 10:00:00\t-\tlive2\t-\th4\tu1\tnextflow run step2.nf\n")
    assert "appears to be active" not in cli(["submit", "search", "--missing", "-n"]).output


def test_missing_cluster_skips_hg_fastas_without_tsv(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    step1_tools()
    r = cli(["missing", "cluster"])
    assert "skipped 1 families with HG FASTAs but no _cluster.tsv (killed publish?): tfs.C_x" in r.output
    assert "tfs.C_x" not in [l for l in r.output.splitlines() if not l.startswith("skipped")]
    r = cli(["submit", "cluster", "--missing", "-n"])             # no longer refuses the batch
    assert "output_exists" not in r.output and "skipped 1 families with HG FASTAs" in r.output
