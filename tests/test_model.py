"""phylocli/model.py: the print-free data layer shared by the CLI and the TUI."""
from __future__ import annotations

import dataclasses
import os
import stat

import pytest

from phylocli import core, model
from phylocli.tests.test_cli import _state, cli  # noqa: F401  (fixture)


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
    return core.load_config(os.environ["PHYLOCLI_CONFIG"])


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
