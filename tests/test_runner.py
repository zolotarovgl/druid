import os
import signal
import threading
from pathlib import Path
from unittest import mock

import pytest

from druid import paths, runner


@pytest.fixture
def proj(tmp_path):
    """tmp_path is a druid project (publish writes only inside the project)."""
    (tmp_path / "druid.yaml").write_text("outdir: results\npartition: x\nqos: y\nparams: {}\n")
    paths.use(tmp_path)               # conftest's autouse fixture clears it after the test


def test_publish_marker_last_and_atomic(tmp_path, proj):
    work = tmp_path/"w"; dest = tmp_path/"d"; work.mkdir(); dest.mkdir()
    (work/"x.HG1.log").write_text("l"); (work/"x.HG1.treefile").write_text("(a,b);")
    order = []
    real = os.replace
    def spy(a, b): order.append(Path(b).name); real(a, b)
    with mock.patch("druid.runner.os.replace", spy):
        runner.publish(work, dest, ["x.HG1.log"], "x.HG1.treefile")
    assert order == ["x.HG1.log", "x.HG1.treefile"]
    assert not list(dest.glob("*.tmp-phylo"))


def test_publish_missing_marker_raises(tmp_path, proj):
    (tmp_path/"w").mkdir(); (tmp_path/"d").mkdir()
    with pytest.raises(FileNotFoundError):
        runner.publish(tmp_path/"w", tmp_path/"d", [], "x.HG1.treefile")


def test_publish_follows_symlinks_and_copies_dirs(tmp_path, proj):
    work = tmp_path/"w"; dest = tmp_path/"d"; work.mkdir()
    real = tmp_path/"real.txt"; real.write_text("R")
    (work/"x.HG1.aln.fasta").symlink_to(real)
    (work/"x.HG1.reconciliations").mkdir(); (work/"x.HG1.reconciliations"/"f").write_text("1")
    (work/"x.HG1.generax.tree").write_text("(a);")
    runner.publish(work, dest, ["x.HG1.aln.fasta", "x.HG1.reconciliations"], "x.HG1.generax.tree")
    assert not (dest/"x.HG1.aln.fasta").is_symlink()
    assert (dest/"x.HG1.aln.fasta").read_text() == "R"
    assert (dest/"x.HG1.reconciliations"/"f").read_text() == "1"


def test_publish_hg1_does_not_take_hg11(tmp_path, proj):
    work = tmp_path/"w"; dest = tmp_path/"d"; work.mkdir()
    (work/"tfs.A.HG11.log").write_text("11"); (work/"tfs.A.HG1.log").write_text("1")
    (work/"tfs.A.HG1.treefile").write_text("(a);")
    runner.publish(work, dest, ["tfs.A.HG1.log"], "tfs.A.HG1.treefile")
    assert sorted(p.name for p in dest.iterdir()) == ["tfs.A.HG1.log", "tfs.A.HG1.treefile"]


def test_stage_env(results_tree):
    cfg, root = results_tree
    env = runner.stage_env(cfg, "align", "tfs.A.HG11", 4)
    assert env["ID"] == "tfs.A.HG11" and env["CPUS"] == "4"
    assert env["OUTDIR"] == str(cfg.outdir)
    assert env["PROJECT_DIR"] == str(paths.project_root())
    assert env["DRUID_HOME"] == str(runner.DRUID_HOME) == str(paths.DRUID_HOME)
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PROJECT_DIR"] != env["DRUID_HOME"]
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["run_generax"] == "true" and env["MAX_SPR"] == "3"


def test_run_one_failure_publishes_nothing_and_keeps_work(results_tree, monkeypatch, tmp_path):
    cfg, root = results_tree
    stages = tmp_path/"stages"; stages.mkdir()
    (stages/"align.sh").write_text("echo partial > ${ID}.aln.fasta; exit 3\n")
    monkeypatch.setattr(runner, "STAGES_DIR", stages)
    rc = runner.run_one(cfg, "align", "tfs.A.HG11", root/"work")
    assert rc == 3
    assert not (cfg.outdir/"align"/"tfs.A.HG11.aln.fasta").exists()
    assert (root/"work"/"tfs.A.HG11"/"tfs.A.HG11.aln.fasta").exists()


def test_run_one_success_publishes(results_tree, monkeypatch, tmp_path):
    cfg, root = results_tree
    stages = tmp_path/"stages"; stages.mkdir()
    (stages/"align.sh").write_text('test "$1" = tfs.A.HG11.fasta; cp "$1" "${ID}.aln.fasta"\n')
    monkeypatch.setattr(runner, "STAGES_DIR", stages)
    assert runner.run_one(cfg, "align", "tfs.A.HG11", root/"work") == 0
    assert (cfg.outdir/"align"/"tfs.A.HG11.aln.fasta").read_text().startswith(">")
    assert not (root/"work"/"tfs.A.HG11").exists()


def test_sigusr2_forwarded(results_tree, monkeypatch, tmp_path):
    cfg, root = results_tree
    stages = tmp_path/"stages"; stages.mkdir()
    (stages/"align.sh").write_text("trap 'echo got > sig.txt; exit 140' USR2\nsleep 30 & wait\n")
    monkeypatch.setattr(runner, "STAGES_DIR", stages)
    t = threading.Timer(1.0, lambda: os.kill(os.getpid(), signal.SIGUSR2)); t.start()
    rc = runner.run_one(cfg, "align", "tfs.A.HG11", root/"work")
    assert rc == 140
    assert (root/"work"/"tfs.A.HG11"/"sig.txt").read_text().strip() == "got"


def test_exit0_without_marker_returns_65(results_tree, monkeypatch, tmp_path, capsys):
    cfg, root = results_tree
    stages = tmp_path/"stages"; stages.mkdir()
    (stages/"align.sh").write_text("true\n")
    monkeypatch.setattr(runner, "STAGES_DIR", stages)
    rc = runner.run_one(cfg, "align", "tfs.A.HG11", root/"work")
    assert rc == 65
    assert "tfs.A.HG11.aln.fasta" in capsys.readouterr().err
    assert not (cfg.outdir/"align"/"tfs.A.HG11.aln.fasta").exists()
    assert (root/"work"/"tfs.A.HG11").is_dir()


def test_handlers_installed_before_popen_and_restored(results_tree, monkeypatch, tmp_path):
    cfg, root = results_tree
    stages = tmp_path/"stages"; stages.mkdir()
    (stages/"align.sh").write_text('cp "$1" "${ID}.aln.fasta"\n')
    monkeypatch.setattr(runner, "STAGES_DIR", stages)
    seen = {}
    real = runner.subprocess.Popen
    def spy(*a, **k):
        seen["usr2"] = signal.getsignal(signal.SIGUSR2)
        seen["term"] = signal.getsignal(signal.SIGTERM)
        return real(*a, **k)
    monkeypatch.setattr(runner.subprocess, "Popen", spy)
    before = (signal.getsignal(signal.SIGUSR2), signal.getsignal(signal.SIGTERM))
    assert runner.run_one(cfg, "align", "tfs.A.HG11", root/"work") == 0
    assert callable(seen["usr2"]) and seen["usr2"] is not before[0]
    assert callable(seen["term"]) and seen["term"] is not before[1]
    assert (signal.getsignal(signal.SIGUSR2), signal.getsignal(signal.SIGTERM)) == before


def test_signal_during_popen_is_forwarded(results_tree, monkeypatch, tmp_path):
    cfg, root = results_tree
    stages = tmp_path/"stages"; stages.mkdir()
    (stages/"align.sh").write_text("trap 'exit 140' USR2\nsleep 30 & wait\n")
    monkeypatch.setattr(runner, "STAGES_DIR", stages)
    real = runner.subprocess.Popen
    def spy(*a, **k):
        os.kill(os.getpid(), signal.SIGUSR2)  # arrives before Popen returns
        return real(*a, **k)
    monkeypatch.setattr(runner.subprocess, "Popen", spy)
    assert runner.run_one(cfg, "align", "tfs.A.HG11", root/"work") in (140, -12, 138)
