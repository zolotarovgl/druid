"""phylocli/model.py: the print-free data layer shared by the CLI and the TUI."""
from __future__ import annotations

import os
import stat

import pytest

from phylocli import model
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
