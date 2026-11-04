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
    with mock.patch("druid.paths.os.replace", spy):
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


@pytest.mark.parametrize("hg", ["", ".", "..", ".hidden", "a/b", "../x", "/abs", "a\0b"])
def test_run_one_rejects_an_hg_id_that_is_not_a_plain_name(results_tree, hg):
    cfg, root = results_tree
    work_root = root / "work"
    (work_root / "keep").mkdir(parents=True)
    (work_root / "keep" / "f").write_text("x")
    (root / "outside_marker").write_text("x")
    with pytest.raises(ValueError, match="HG id"):
        runner.run_one(cfg, "align", hg, work_root)
    assert (work_root / "keep" / "f").read_text() == "x" and (root / "outside_marker").exists()
    assert sorted(p.name for p in work_root.iterdir()) == ["keep"]


def test_cli_run_with_a_bad_hg_id_is_an_error_line(results_tree):
    from typer.testing import CliRunner
    from druid import cli
    cfg, root = results_tree
    rd = root / "runs" / "r"
    (rd / "work" / "keep").mkdir(parents=True)
    r = CliRunner().invoke(cli.app, ["_run", "align", "../keep", "--run-dir", str(rd)])
    assert r.exit_code == 2 and "ERROR:" in r.output and "HG id" in r.output
    assert (rd / "work" / "keep").is_dir()


def test_cluster_no_hits_exits_0(results_tree, monkeypatch, tmp_path, capsys):
    cfg, root = results_tree
    (cfg.outdir/"search").mkdir()
    (cfg.outdir/"search"/"a.F1.domains.fasta").write_text("")
    stages = tmp_path/"stages"; stages.mkdir()
    (stages/"cluster.sh").write_text("exit 9\n")          # must not run
    monkeypatch.setattr(runner, "STAGES_DIR", stages)
    before = set(os.listdir(cfg.outdir/"clusters"))
    assert runner.run_one(cfg, "cluster", "a.F1", root/"work") == 0
    assert "no hits: nothing to cluster for a.F1" in capsys.readouterr().out
    assert not (root/"work"/"a.F1").exists()
    assert set(os.listdir(cfg.outdir/"clusters")) == before


def test_cluster_env_uses_the_familys_inflation(results_tree, tmp_path):
    cfg, root = results_tree
    fam = tmp_path / "fam.csv"
    fam.write_text("Fox\tForkhead\t1.6\t3\tGA\ttfs\ttfs\nSox\tHMG\t\t3\tGA\ttfs\ttfs\n")
    cfg.params["genefam_info"] = str(fam)
    cfg.params["s2_inflation"] = 1.1
    assert runner.stage_env(cfg, "cluster", "tfs.Fox", 2)["s2_inflation"] == "1.6"
    assert runner.stage_env(cfg, "cluster", "tfs.Sox", 2)["s2_inflation"] == "1.1"   # blank field
    assert runner.stage_env(cfg, "cluster", "tfs.Nope", 2)["s2_inflation"] == "1.1"  # absent id
    assert runner.stage_env(cfg, "align", "tfs.Fox.HG1", 2)["s2_inflation"] == "1.1"  # other stages
