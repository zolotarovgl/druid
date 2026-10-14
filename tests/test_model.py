"""phylocli/model.py: the print-free data layer shared by the CLI and the TUI."""
from __future__ import annotations

import dataclasses
import os
import stat

import pytest

from druid import core, model, paths
from tests.test_cli import _state, cli  # noqa: F401  (fixture)


def _fake(name, body):
    p = _state["bin"] / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)


def test_live_maps_array_task_to_hg(cli, monkeypatch):
    r = cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"])
    assert r.exit_code == 0, r.output
    monkeypatch.setenv("FAKE_SQUEUE", "12345_1|phylo-align\n")
    assert model.live({"tfs.A.HG11", "tfs.C_x.HG1"}) == {"align": {"tfs.C_x.HG1"}}


def test_live_none_without_squeue(cli):
    (_state["bin"] / "squeue").unlink()
    assert model.live(set()) is None


def test_squeue_timeout_is_model_error(cli, monkeypatch):
    _fake("squeue", "sleep 5")
    monkeypatch.setattr(model, "SLURM_TIMEOUT", 1)
    with pytest.raises(model.ModelError, match="squeue timed out"):
        model.squeue("%i|%j")


def test_task_states_and_category(cli, monkeypatch):
    monkeypatch.setenv("FAKE_SACCT", "7_0|COMPLETED\\n7_1|OUT_OF_MEMORY\\n7_[2-3%50]|PENDING\\n")
    st = model.task_states(["7"])
    assert st == {"7": {0: "COMPLETED", 1: "OUT_OF_MEMORY", 2: "PENDING", 3: "PENDING"}}
    assert [model.category(s) for s in ("COMPLETED", "OUT_OF_MEMORY", "RUNNING", "PENDING")] == \
        ["done", "failed", "running", "pending"]


def test_submissions_newest_first(cli):
    assert cli(["submit", "align", "tfs.A.HG11"]).exit_code == 0
    subs = model.submissions(None, 10)
    assert [(s[1], s[2]) for s in subs] == [("align", "12345")]


def _cfg():
    return core.load_config(paths.config_file())


def test_stage_rows_counts(cli):
    cfg = _cfg()
    rows, known, done = model.stage_rows(cfg, core.expected(cfg))
    by = {r.stage: r for r in rows}
    assert known is True
    assert (by["align"].done, by["align"].ready, by["align"].total) == (1, 2, 3)
    assert by["align"].done + by["align"].running + by["align"].ready + by["align"].blocked == 3
    assert "tfs.A.HG1" in done["align"]


def test_stage_rows_running_from_squeue(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SQUEUE", "12345_0|phylo-align\n")
    rows, _k, _d = model.stage_rows(_cfg(), core.expected(_cfg()))
    a = next(r for r in rows if r.stage == "align")
    assert (a.running, a.ready) == (1, 1)


def test_stage_rows_not_applicable(cli):
    cfg = _cfg()
    cfg = dataclasses.replace(cfg, params={**cfg.params, "gxsup": False})
    rows, _k, _d = model.stage_rows(cfg, core.expected(cfg))
    assert next(r for r in rows if r.stage == "gxsup").applicable is False


def test_stage_rows_without_squeue(cli):
    (_state["bin"] / "squeue").unlink()
    rows, known, _d = model.stage_rows(_cfg(), core.expected(_cfg()))
    assert known is False and all(r.running == 0 for r in rows)


SACCT_OOM = ("12345_0|COMPLETED|10M|00:01:00|0:0\\n"
             "12345_1|OUT_OF_MEMORY|4100M|00:03:00|0:125\\n")


def test_hg_rows_failed_vs_ready(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)
    rows = {r.hg: r for r in model.hg_rows(_cfg(), "align")}
    assert rows["tfs.A.HG1"].state == "done"
    assert rows["tfs.C_x.HG1"].state == "failed"
    assert rows["tfs.C_x.HG1"].last.status == "OUT_OF_MEMORY"
    assert rows["tfs.A.HG11"].state == "ready"          # its attempt COMPLETED, output absent


def test_hg_rows_running_and_blocked(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11"]).exit_code == 0
    monkeypatch.setenv("FAKE_SQUEUE", "12345_0|phylo-align\n")
    rows = {r.hg: r.state for r in model.hg_rows(_cfg(), "align")}
    assert rows["tfs.A.HG11"] == "running"
    gx = {r.hg: r.state for r in model.hg_rows(_cfg(), "gxsup")}
    assert set(gx.values()) == {"blocked"}              # no generax trees in the fixture


def test_hg_detail(cli):
    d = model.hg_detail(_cfg(), "tfs.C_x.HG1")
    assert d.nseq == 600 and d.states["align"] == "ready" and d.latest == {}


def test_array_rows(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", "12345_0|COMPLETED\\n12345_1|RUNNING\\n")
    rows, known = model.array_rows()
    assert known and len(rows) == 1
    r = rows[0]
    assert (r.stage, r.job, r.n, r.counts["done"], r.counts["running"]) == ("align", "12345", 2, 1, 1)


from druid import history


def _att(status, exit_="-", mem="2.0 GB", time="30m"):
    return history.Attempt("tfs.A.HG11", "gxsup", "phylocli", "r", "2026-10-08 22:00:00", 1,
                           status, exit_, "2", mem, time, "-", "-", "x.err")


RES = core.Res(2, 2048, 30, "normal", None)


def test_parse_duration():
    assert [model.parse_duration_min(s) for s in ("30m", "4h", "1h30m", "1d", "2d 3h", "?")] == \
        [30, 240, 90, 1440, 3060, None]


def test_bump_oom_doubles_mem():
    assert model.bump(_att("OUT_OF_MEMORY"), RES) == core.Res(2, 4096, 30, "normal", None)
    assert model.bump(_att("FAILED", "137"), RES).mem_mb == 4096


def test_bump_timeout_doubles_time():
    assert model.bump(_att("TIMEOUT"), RES) == core.Res(2, 2048, 60, "normal", None)


def test_bump_other_keeps_last_request():
    r = model.bump(_att("FAILED", "1", mem="4.0 GB", time="1h30m"), RES)
    assert (r.mem_mb, r.time_min) == (4096, 90)          # previous, larger request is kept
    assert model.bump(None, RES) == RES


def test_group_per_hg_splits_arrays(cli):
    g = core.group(_cfg(), "align", ["tfs.A.HG11", "tfs.C_x.HG1"],
                   per_hg={"tfs.C_x.HG1": {"mem_mb": 8192}})
    assert sorted(r.mem_mb for r in g) == [4096, 8192]


import yaml  # noqa: E402


def _raw():
    return yaml.safe_load(paths.config_file().read_text())


def test_select_skips_unready_and_queued(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SQUEUE", "12345_0|phylo-align\n")
    sel = model.select(_cfg(), "align", ["tfs.A.HG11", "tfs.C_x.HG1"])
    assert sel.selected == ["tfs.A.HG11"] and "skipped 1 HGs already queued" in sel.notes


def test_select_unknown_is_error(cli):
    with pytest.raises(model.ModelError) as e:
        model.select(_cfg(), "align", ["tfs.Z.HG9"])
    assert e.value.code == 2 and "unknown (1): tfs.Z.HG9" in str(e.value)


def test_plan_not_applicable(cli):
    cfg = dataclasses.replace(_cfg(), params={**_cfg().params, "gxsup": False})
    sel = model.Selection(["tfs.A.HG11"], [], set())
    assert model.plan(cfg, "gxsup", sel).errors["not_applicable"] == ["tfs.A.HG11"]


def test_write_and_sbatch_with_per_hg(cli):
    cfg = _cfg()
    sel = model.select(cfg, "align", ["tfs.A.HG11", "tfs.C_x.HG1"])
    p = model.plan(cfg, "align", sel, per_hg={"tfs.C_x.HG1": {"mem_mb": 8192}})
    assert not any(p.errors.values()) and len(p.groups) == 2
    w = model.write_run(cfg, _raw(), p, dry_run=False)
    jids, err = model.sbatch_all(w)
    assert err is None and jids == ["12345", "12345"]
    scripts = sorted(s.read_text() for _r, _i, _f, s in w.arrays)
    assert any("--mem=8192M" in s for s in scripts) and any("--mem=4096M" in s for s in scripts)
    assert (w.run_dir / "jobs.tsv").read_text().count("12345") == 2


def test_preflight_message(cli, monkeypatch):
    monkeypatch.setenv("FAKE_PY_FAIL", "1")
    msg = model.preflight("align")
    assert msg and "ete3" in msg and "conda activate phylo" in msg
    assert model.preflight("gxsup") is None


def test_sbatch_all_timeout_reports_partial_submission(cli, monkeypatch):
    cfg = _cfg()
    sel = model.select(cfg, "align", ["tfs.A.HG11", "tfs.C_x.HG1"])
    p = model.plan(cfg, "align", sel, per_hg={"tfs.C_x.HG1": {"mem_mb": 8192}})
    w = model.write_run(cfg, _raw(), p, dry_run=False)
    assert len(w.arrays) == 2
    # first call answers at once; the second hangs past SLURM_TIMEOUT
    marker = _state["bin"] / "first_done"
    _fake("sbatch", f'if [ -e {marker} ]; then exec sleep 5; fi\ntouch {marker}\necho 12345')
    monkeypatch.setattr(model, "SLURM_TIMEOUT", 1)
    jids, err = model.sbatch_all(w)
    assert jids == ["12345"]
    lines = err.splitlines()
    assert len(lines) == 3
    assert lines[0] == (f"sbatch timed out after 1 s for {w.arrays[1][3]}: the array may have been "
                        "queued — check 'squeue --me' before resubmitting")
    assert lines[1] == "submitted job ids: 12345"
    assert lines[2] == "not submitted (or unknown): " + str(w.arrays[1][3])
    assert (w.run_dir / "jobs.tsv").read_text().count("12345") == 1


def test_sbatch_all_jobs_tsv_write_error_keeps_jid(cli, monkeypatch):
    import builtins
    cfg = _cfg()
    sel = model.select(cfg, "align", ["tfs.A.HG11"])
    w = model.write_run(cfg, _raw(), model.plan(cfg, "align", sel), dry_run=False)
    _fake("sbatch", "echo 12345")
    real_open = builtins.open

    def deny(path, *a, **k):
        if str(path).endswith("jobs.tsv"):
            raise OSError("Stale file handle")
        return real_open(path, *a, **k)
    monkeypatch.setattr(builtins, "open", deny)
    got: list = []
    with pytest.raises(OSError):
        model.sbatch_all(w, got)
    assert got == ["12345"]                          # queued, so the caller must know


def test_bar_segments():
    assert model.bar_segments((1, 0, 1, 0), 10) == [5, 0, 5, 0]
    assert sum(model.bar_segments((7, 1, 1, 1), 30)) == 30
    assert model.bar_segments((0, 0, 0, 0), 10) == []


def test_group_key():
    assert model.group_key("tfs.T-box.HG1", "category") == "tfs"
    assert model.group_key("tfs.T-box.HG1", "family") == "tfs.T-box"
    assert model.group_key("adh.Cad.herin.HG12", "family") == "adh.Cad.herin"


def test_group_rows_all_equals_stage_rows(cli):
    cfg = _cfg()
    exp = core.expected(cfg)
    rows, known = model.group_rows(cfg, exp, "category")
    srows, _k, _d = model.stage_rows(cfg, exp)
    assert rows[0].group == "ALL" and rows[0].total == len(exp)
    for s in srows:
        got = rows[0].per_stage[s.stage]
        assert got == ((s.done, s.running, s.ready, s.blocked) if s.applicable else None)
    assert [r.group for r in rows] == ["ALL", "tfs"]


def test_group_rows_family_sum_to_all(cli):
    cfg = _cfg()
    exp = core.expected(cfg)
    rows, _k = model.group_rows(cfg, exp, "family")
    assert [r.group for r in rows] == ["ALL", "tfs.A", "tfs.C_x"]
    for st, allc in rows[0].per_stage.items():
        if allc is None:
            continue
        assert tuple(sum(r.per_stage[st][i] for r in rows[1:]) for i in range(4)) == allc


# ---- ortholog groups (Results window) --------------------------------------------------------
from pathlib import Path  # noqa: E402

OG_HEAD = "gene\torthogroup\torthogroup_support\treference_ortholog\treference_support\n"
SP4 = "((Mlei:1,Bova:1)Cteno:1,(Hsap:1,Nvec:1)Para:1);\n"       # 4 tips; internal names ignored
SPINFO = ("Mlei\tMnemiopsis leidyi\tCtenophora\n"
          "Bova\tBeroe ovata\tCtenophora\n"
          "Hsap\tHomo sapiens\tChordata\t\n"                    # trailing tab, as Lpol in v3
          "Nvec\tNematostella vectensis\n"                      # no phylum column, as Dicjap
          "\n"
          "Zzz\tZz zz\tPorifera\n")                             # not a tip of the species tree
POSSVM_HG1 = [("Mlei_v05_G1", "tfs.A.HG1.0:T/Tbx19", "78.4", "T/Tbx19", "98.2/98.2"),
              ("Mlei_v05_G2", "tfs.A.HG1.0:T/Tbx19", "78.4", "T/Tbx19", "98.2/98.2"),
              ("Hsap_ENSP1", "tfs.A.HG1.0:T/Tbx19", "78.4", "T/Tbx19", "98.2/98.2"),
              ("Hsap_ENSP2", "tfs.A.HG1.1:like:Eomes/Tbr1", "0.0", "NA", "NA"),
              ("Nvec_v1_g3", "tfs.A.HG1.1:like:Eomes/Tbr1", "0.0", "NA", "NA")]
POSSVM_HG11 = [("Bova_x1", "tfs.A.HG11.0:Tbx20", "85.0", "Tbx20", "90.0"),
               ("Mlei_v05_G9", "tfs.A.HG11.0:Tbx20", "85.0", "Tbx20", "90.0")]
PREV_HG1 = [("Mlei_v05_G1", "tfs.A.HG1.0:like:Tbx2/Tbx3", "98.0", "NA", "NA"),
            ("Zzz_q1", "tfs.A.HG1.0:like:Tbx2/Tbx3", "98.0", "NA", "NA")]


def og_csv(rows) -> str:
    return OG_HEAD + "".join("\t".join(r) + "\n" for r in rows)


def write_results(cfg) -> None:
    """POSSVM output for tfs.A.HG1 (possvm + possvm_prev) and tfs.A.HG11 (possvm only), the
    4-tip species tree and species_info.tsv next to it.  tfs.C_x.HG1 keeps no output."""
    o = cfg.outdir
    (o / "possvm/tfs.A.HG1.generax.support.tree.ortholog_groups.csv").write_text(og_csv(POSSVM_HG1))
    (o / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv").write_text(og_csv(POSSVM_HG11))
    (o / "possvm_prev/tfs.A.HG1.treefile.ortholog_groups.csv").write_text(og_csv(PREV_HG1))
    tree = Path(cfg.params["SPECIES_TREE"])
    tree.write_text(SP4)
    (tree.parent / "species_info.tsv").write_text(SPINFO)


def test_read_ogs_parses_and_sorts(cli):
    cfg = _cfg()
    write_results(cfg)
    ogs = model.read_ogs(cfg, "tfs.A.HG1", "possvm")
    assert [(o.id, o.name, len(o.genes), o.support, o.ref, o.ref_support) for o in ogs] == [
        ("tfs.A.HG1.0", "T/Tbx19", 3, 78.4, "T/Tbx19", "98.2/98.2"),
        ("tfs.A.HG1.1", "like:Eomes/Tbr1", 2, 0.0, "NA", "NA")]
    assert [m.gene for m in ogs[0].genes] == ["Mlei_v05_G1", "Mlei_v05_G2", "Hsap_ENSP1"]
    assert ogs[1].genes[0] == model.Member("Hsap_ENSP2", "Hsap", "NA", "NA")
    # tfs.A.HG1 must not pick up tfs.A.HG11's file (HG1 is a prefix of HG11)
    assert [o.id for o in model.read_ogs(cfg, "tfs.A.HG11", "possvm")] == ["tfs.A.HG11.0"]
    assert [o.name for o in model.read_ogs(cfg, "tfs.A.HG1", "possvm_prev")] == ["like:Tbx2/Tbx3"]


def test_read_ogs_none_when_missing_or_empty(cli):
    cfg = _cfg()
    assert model.read_ogs(cfg, "tfs.C_x.HG1", "possvm") is None
    assert model.read_ogs(cfg, "tfs.A.HG11", "possvm") is None     # fixture file is empty = not done
    assert model.read_ogs(cfg, "tfs.A.HG1", "no_such_dir") is None


def test_read_ogs_two_files_is_error(cli):
    cfg = _cfg()
    write_results(cfg)
    (cfg.outdir / "possvm/tfs.A.HG1.generax.tree.ortholog_groups.csv").write_text(og_csv(POSSVM_HG1))
    with pytest.raises(model.ModelError) as e:
        model.read_ogs(cfg, "tfs.A.HG1", "possvm")
    assert "tfs.A.HG1.generax.tree.ortholog_groups.csv" in str(e.value)
    assert "tfs.A.HG1.generax.support.tree.ortholog_groups.csv" in str(e.value)


def test_read_ogs_bad_rows_name_file_and_line(cli):
    cfg = _cfg()
    with pytest.raises(model.ModelError, match=r":1: not a POSSVM"):  # fixture file holds "x\n"
        model.read_ogs(cfg, "tfs.A.HG1", "possvm_prev")
    p = cfg.outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv"
    p.write_text(OG_HEAD + "Mlei_v05_G9\ttfs.A.HG11.0:Tbx20\t85.0\tTbx20\t90.0\nbroken row\n")
    with pytest.raises(model.ModelError, match=r"ortholog_groups\.csv:3: cannot parse row"):
        model.read_ogs(cfg, "tfs.A.HG11", "possvm")
    p.write_text(OG_HEAD + "Mlei_v05_G9\ttfs.A.HG11.0:Tbx20\tlots\tTbx20\t90.0\n")
    with pytest.raises(model.ModelError, match=r":2: bad orthogroup_support 'lots'"):
        model.read_ogs(cfg, "tfs.A.HG11", "possvm")
    p.write_text(OG_HEAD + "Mlei_v05_G9\ttfs.B.HG2.0:Tbx20\t85.0\tTbx20\t90.0\n")   # wrong HG
    with pytest.raises(model.ModelError, match=r":2: cannot parse row"):
        model.read_ogs(cfg, "tfs.A.HG11", "possvm")


def test_read_ogs_negative_and_na_support(cli):
    cfg = _cfg()
    p = cfg.outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv"
    p.write_text(og_csv([("Mlei_v05_G9", "tfs.A.HG11.1:Tbx20", "-1", "Tbx20", "95.3"),
                         ("Hsap_E1", "tfs.A.HG11.0:like:Tbx1", "NA", "NA", "NA")]))
    ogs = model.read_ogs(cfg, "tfs.A.HG11", "possvm")
    assert [(o.id, o.support) for o in ogs] == [("tfs.A.HG11.0", None), ("tfs.A.HG11.1", -1.0)]


def test_species_of():
    assert model.species_of("Mlei_v05_G009201") == "Mlei"
    assert model.species_of("Mertsp_Mesp_sb563561") == "Mertsp"
    assert model.species_of("nounderscore") == "nounderscore"


def test_group_ogs_lists_hgs_with_output_one_listing(cli, monkeypatch):
    cfg = _cfg()
    write_results(cfg)
    (cfg.outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv").write_text(
        OG_HEAD + "bad\n")
    calls = []
    real = core.report_status.nonempty_files
    monkeypatch.setattr(core.report_status, "nonempty_files", lambda d: calls.append(d) or real(d))
    rows, missing = model.group_ogs(cfg, ["tfs.C_x.HG1", "tfs.A.HG11", "tfs.A.HG1"], "possvm")
    assert [r.hg for r in rows] == ["tfs.A.HG1", "tfs.A.HG11"] and missing == 1
    assert len(rows[0].ogs) == 2 and rows[0].error == ""
    assert rows[1].ogs == [] and ":2: cannot parse row" in rows[1].error
    assert len(calls) == 1                                   # one listing for all HGs
    assert sorted(["tfs.A.HG2", "tfs.A.HG10", "tfs.A.HG1"], key=model.hg_sort_key) == \
        ["tfs.A.HG1", "tfs.A.HG2", "tfs.A.HG10"]


def test_default_source(cli):
    import shutil
    cfg = _cfg()
    assert model.default_source(cfg) == "possvm"
    shutil.rmtree(cfg.outdir / "possvm")
    assert model.default_source(cfg) == "possvm_prev"


def test_species_universe_reads_tip_names(cli):
    cfg = _cfg()
    write_results(cfg)
    assert model.species_universe(cfg) == ["Mlei", "Bova", "Hsap", "Nvec"]
    Path(cfg.params["SPECIES_TREE"]).write_text("((A:1,(B:0.5,C:2)x.y:1)Clade_1:1,D);\n")
    assert model.species_universe(cfg) == ["A", "B", "C", "D"]          # clade names skipped
    Path(cfg.params["SPECIES_TREE"]).unlink()
    with pytest.raises(FileNotFoundError):
        model.species_universe(cfg)


def test_phyla_from_species_info(cli):
    cfg = _cfg()
    write_results(cfg)
    assert model.species_info_path(cfg) == Path(cfg.params["SPECIES_TREE"]).parent / "species_info.tsv"
    assert model.phyla(cfg) == {"Mlei": "Ctenophora", "Bova": "Ctenophora", "Hsap": "Chordata",
                                "Nvec": "unknown", "Zzz": "Porifera"}


def test_og_species_stats_per_phylum(cli):
    cfg = _cfg()
    write_results(cfg)
    uni, ph = model.species_universe(cfg), model.phyla(cfg)
    og = model.read_ogs(cfg, "tfs.A.HG1", "possvm")[0]            # Mlei 2, Hsap 1
    rows = model.og_species_stats(og, uni, ph)
    assert [(r.phylum, r.covered, r.total, r.n_genes, r.species) for r in rows] == [
        ("Ctenophora", 1, 2, 2, [("Mlei", 2)]),
        ("Chordata", 1, 1, 1, [("Hsap", 1)]),
        ("unknown", 0, 1, 0, [])]                                  # absent phyla last
    assert model.og_outside(og, uni) == []
    prev = model.read_ogs(cfg, "tfs.A.HG1", "possvm_prev")[0]     # Mlei 1, Zzz 1
    assert model.og_outside(prev, uni) == [("Zzz", 1)]            # in species_info, not a tip
    assert [r.phylum for r in model.og_species_stats(prev, uni, {})] == ["unknown"]


def test_og_group_rows_sums_per_group(cli):
    cfg = _cfg()
    write_results(cfg)
    exp = {"tfs.A.HG1", "tfs.A.HG11", "tfs.C_x.HG1"}
    rows, missing = model.group_ogs(cfg, exp, "possvm")
    rows.append(model.HGOgs("tfs.C_x.HG1", [], "bad.csv:2: cannot parse row"))
    out = model.og_group_rows(["ALL", "tfs", "cal"], exp, "category", rows)
    assert [(r.group, r.hgs, r.with_output, r.ogs, r.genes, r.zero, r.unreadable) for r in out] == [
        ("ALL", 3, 3, 3, 7, 1, 1), ("tfs", 3, 3, 3, 7, 1, 1), ("cal", 0, 0, 0, 0, 0, 0)]
    fam = model.og_group_rows(["tfs.A", "tfs.C_x"], exp, "family", rows[:2])
    assert [(r.group, r.hgs, r.with_output, r.ogs) for r in fam] == [("tfs.A", 2, 2, 3),
                                                                     ("tfs.C_x", 1, 0, 0)]


def test_origin_tree_path_default(cli):
    cfg = _cfg()
    assert model.origin_tree_path(cfg) == Path(cfg.params["ORIGIN_TREE"])
    import dataclasses
    bare = dataclasses.replace(cfg, params={k: v for k, v in cfg.params.items() if k != "ORIGIN_TREE"})
    assert model.origin_tree_path(bare) == paths.project_root() / "data/species_tree.newick"


def test_config_resolves_origin_tree_relative_to_root(results_tree):
    raw = {"outdir": "results", "partition": "p", "qos": "q",
           "params": {"ORIGIN_TREE": "data/species_tree.newick"}}
    assert core.config_from_raw(raw).params["ORIGIN_TREE"] == str(paths.project_root() / "data/species_tree.newick")


def test_og_origins_on_the_fixture(cli):
    cfg = _cfg()
    write_results(cfg)
    rows, _ = model.group_ogs(cfg, ["tfs.A.HG1", "tfs.A.HG11"], "possvm")
    got = model.og_origins(rows, model.origin_tree(cfg))
    assert {k: (v.label, v.depth) for k, v in got.items()} == {
        "tfs.A.HG1.0": ("root", 0), "tfs.A.HG1.1": ("Para", 1), "tfs.A.HG11.0": ("Cteno", 1)}


def test_og_origins_ignore_species_off_the_tree(cli):
    cfg = _cfg()
    write_results(cfg)
    rows, _ = model.group_ogs(cfg, ["tfs.A.HG1"], "possvm_prev")      # Mlei + Zzz (not a tip)
    assert model.og_origins(rows, model.origin_tree(cfg)) == {"tfs.A.HG1.0": ("Mlei", 2)}


def test_og_origins_none_and_error_rows(cli):
    cfg = _cfg()
    tree = model.origin_tree(cfg)
    og = model.OG("x.HG1.0", "n", [model.Member("Zzz_1", "Zzz", "NA", "NA")], None, "NA", "NA")
    rows = [model.HGOgs("x.HG1", [og], None), model.HGOgs("x.HG2", [], "bad file")]
    assert model.og_origins(rows, tree) == {"x.HG1.0": None}


def test_origin_tree_unreadable_raises(cli):
    cfg = _cfg()
    Path(cfg.params["ORIGIN_TREE"]).unlink()
    with pytest.raises(OSError):
        model.origin_tree(cfg)


def test_hg_tree_files_from_the_og_csv_name(cli):
    cfg = _cfg()
    write_results(cfg)
    tree, csv = model.hg_tree_files(cfg, "tfs.A.HG1", "possvm")
    assert csv.name == "tfs.A.HG1.generax.support.tree.ortholog_groups.csv"
    assert tree == cfg.outdir / "possvm/tfs.A.HG1.generax.support.tree"
    assert model.hg_tree_files(cfg, "tfs.A.HG1", "possvm_prev")[0].name == "tfs.A.HG1.treefile"
    assert model.hg_tree_files(cfg, "tfs.C_x.HG1", "possvm") is None
