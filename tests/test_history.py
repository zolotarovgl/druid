"""Per-HG job history: Nextflow run database + phylocli submissions (`phylo status HG`)."""
import os
import stat

import pytest
import yaml

from phylocli import core, history
from phylocli.tests.test_cli import _state, cli  # noqa: F401  (fixture)

HG = "tfs.A.HG1"
NF_OK = "\n".join([
    "Picked up _JAVA_OPTIONS: -Xmx1g",
    f"ALN\t{HG}\tCOMPLETED\t0\t1\t4\t4 GB\t4h\t1.2 GB\t5m 3s\t/w/aa/1\t2026-09-24 15:46:02.123",
    f"PHY\t{HG}\tFAILED\t137\t1\t4\t300 MB\t30m\t-\t8m 25s\t/w/bb/2\t2026-09-24 16:00:00.000",
    f"PHY\t{HG}\tCOMPLETED\t0\t2\t4\t600 MB\t6h 30m\t535.5 MB\t1h 22m 8s\t/w/cc/3\t2026-09-24 16:10:00.000",
    f"PHY\t{HG}\tCACHED\t0\t1\t4\t600 MB\t6h 30m\t-\t-\t/w/cc/3\t2026-09-24 15:00:00.000",
    f"GR_watcher\t{HG}\tFAILED\t140\t1\t2\t500 MB\t30m\t-\t24m 50s\t/w/dd/4\t2026-09-24 17:00:00.000",
    f"PVM_PREV\tpre_{HG}\tCOMPLETED\t0\t1\t1\t500 MB\t5m\t100 MB\t30s\t/w/ee/5\t2026-09-24 16:30:00.000",
    "REPORT\t-\tCOMPLETED\t0\t1\t1\t1 GB\t1h\t-\t1m\t/w/ff/6\t2026-09-24 18:00:00.000",
    "PHY\ttfs.B.HG2\tCOMPLETED\t0\t1\t4\t300 MB\t30m\t50 MB\t1m\t/w/gg/7\t2026-09-24 16:00:00.000",
    "",
])
NF_LIVE = f"GXSUP\t{HG}\tFAILED\t65\t1\t2\t2 GB\t30m\t-\t1m\t/w/hh/8\t2026-09-30 10:00:00.000\n"

HISTORY = (
    "2026-09-24 15:40:00\t1h\trun_ok\tOK\th1\tu1\tnextflow run -ansi-log false step2.nf -profile slurm\n"
    "2026-09-20 10:00:00\t1m\trun_s1\tOK\th2\tu1\tnextflow run -ansi-log false step1.nf -resume\n"
    "2026-09-30 09:00:00\t-\trun_live\t-\th3\tu1\tnextflow run -ansi-log false step2.nf -resume\n"
)

SACCT = ("555_0|COMPLETED||00:01:00|0:0\\n555_0.batch|COMPLETED|1000K|00:01:00|0:0\\n"
         "777_0|COMPLETED||00:00:10|0:0\\n777_0.batch|COMPLETED|1000K|00:00:10|0:0\\n"
         "777_1|OUT_OF_MEMORY||00:12:44|0:125\\n777_1.batch|OUT_OF_MEMORY|1234567K|00:12:44|0:125\\n")


def _sbatch(cpus, mem, time):
    return (f"#!/usr/bin/env bash\n#SBATCH --cpus-per-task={cpus}\n#SBATCH --mem={mem}\n"
            f"#SBATCH --time={time}\n")


def _run(runs, name, stage, jid, ids, sbatch):
    d = runs / name
    (d / "logs").mkdir(parents=True)
    (d / "ids_0.txt").write_text("\n".join(ids) + "\n")
    (d / "array_0.sbatch").write_text(sbatch)
    (d / "jobs.tsv").write_text(f"{jid}\t/nonexistent/elsewhere/ids_0.txt\n")   # resolved via run dir


@pytest.fixture
def hist(cli, results_tree, tmp_path, monkeypatch):   # noqa: F811
    cfg, root = results_tree
    nf = tmp_path / "nf"
    (nf / ".nextflow").mkdir(parents=True)
    (nf / ".nextflow/history").write_text(HISTORY)
    cfgfile = root / "config.yaml"
    raw = yaml.safe_load(cfgfile.read_text())
    raw["nextflow_dir"] = str(nf)
    cfgfile.write_text(yaml.safe_dump(raw))
    nflog = tmp_path / "nflog"
    nflog.mkdir()
    (nflog / "run_ok.tsv").write_text(NF_OK)
    (nflog / "run_live.tsv").write_text(NF_LIVE)
    nfbin = tmp_path / "nfbin"
    nfbin.mkdir()
    calls = tmp_path / "nfcalls.txt"
    fake = nfbin / "nextflow"
    fake.write_text(
        '#!/bin/sh\n'
        '[ "$1" = "-log" ] || { echo "nextflow without -log" >&2; exit 9; }\n'
        f'case "$2" in "{nf}"/*|"{root}"/*) echo "log inside project" >&2; exit 8;; esac\n'
        f'echo "$4 $PWD $NXF_VER" >> {calls}\n'
        '[ "$3" = log ] && cat "$FAKE_NFLOG_DIR/$4.tsv"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("FAKE_NFLOG_DIR", str(nflog))
    monkeypatch.delenv("NXF_VER", raising=False)
    monkeypatch.delenv("PHYLOCLI_HISTORY", raising=False)
    monkeypatch.setenv("PATH", f"{nfbin}{os.pathsep}{_state['bin']}{os.pathsep}/usr/bin{os.pathsep}/bin")
    runs = _state["runs"]
    _run(runs, "20260930-120000_generax", "generax", "777", ["tfs.B.HG2", HG], _sbatch(2, "500M", 30))
    _run(runs, "20260901-000000_tree", "tree", "555", [HG], _sbatch(4, "300M", 30))
    monkeypatch.setenv("FAKE_SACCT", SACCT)
    cfg = core.load_config(cfgfile)
    return cli, cfg, calls, tmp_path


def _by(atts, **kw):
    return [a for a in atts if all(getattr(a, k) == v for k, v in kw.items())]


def test_cached_rows_skipped_and_stage_map(hist):
    _cli, cfg, _c, _t = hist
    atts = history.attempts(cfg, HG)
    nf = _by(atts, source="nextflow")
    assert all(a.status != "CACHED" for a in nf)
    assert sorted((a.stage, a.attempt, a.status) for a in nf if a.run == "run_ok") == sorted([
        ("align", 1, "COMPLETED"), ("tree", 1, "FAILED"), ("tree", 2, "COMPLETED"),
        ("generax", 1, "FAILED"), ("possvm_prev", 1, "COMPLETED")])
    a = _by(nf, stage="tree", attempt=2)[0]
    assert (a.cpus, a.mem, a.time, a.peak_rss, a.realtime, a.exit) == \
        ("4", "600 MB", "6h 30m", "535.5 MB", "1h 22m 8s", "0")
    assert a.submitted == "2026-09-24 16:10:00" and a.log == "/w/cc/3/.command.err"
    assert _by(nf, stage="gxsup")[0].run == "run_live"      # running run included
    assert not _by(atts, run="run_s1")                       # step1 run ignored
    assert not any(x.stage == "possvm" for x in atts)        # REPORT and other HG ignored


def test_prefixed_tag_resolved(hist):
    _cli, cfg, _c, _t = hist
    assert _by(history.attempts(cfg, HG), stage="possvm_prev")      # pre_<id> -> <id>


def test_sorted_and_latest_across_sources(hist):
    _cli, cfg, _c, _t = hist
    atts = history.attempts(cfg, HG)
    assert [a.submitted for a in atts] == sorted(a.submitted for a in atts)
    latest = history.latest_by_stage(atts)
    assert latest["generax"].source == "phylocli"            # later than the nextflow attempt
    assert latest["tree"].source == "nextflow" and latest["tree"].attempt == 2   # phylocli one is older
    assert latest["gxsup"].run == "run_live"


def test_sacct_used_resources_and_requested(hist):
    _cli, cfg, _c, _t = hist
    a = _by(history.attempts(cfg, HG), source="phylocli", stage="generax")[0]
    assert a.run == "20260930-120000_generax" and a.submitted == "2026-09-30 12:00:00"
    assert (a.status, a.peak_rss, a.realtime) == ("OUT_OF_MEMORY", "1.2 GB", "12m 44s")
    assert (a.cpus, a.mem, a.time) == ("2", "500 MB", "30m")
    assert a.log.endswith("20260930-120000_generax/logs/generax_777_1.err")
    assert history.reason(a.status, a.exit) == "out of memory"


def test_reasons():
    assert history.reason("COMPLETED", "0") == "ok"
    assert history.reason("FAILED", "137") == "killed: out of memory?"
    assert history.reason("FAILED", "140") == "time limit (SIGUSR2 warning)"
    assert history.reason("FAILED", "143") == "terminated"
    assert history.reason("FAILED", "10") == "GeneRax parse error"
    assert history.reason("FAILED", "65") == "stage produced no output"
    assert history.reason("TIMEOUT", "0") == "time limit"
    assert history.reason("CANCELLED", "0") == "cancelled"
    assert history.reason("FAILED", "3") == "exit 3"


def test_sacct_missing_gives_unknown(hist):
    _cli, cfg, _c, _t = hist
    (_state["bin"] / "sacct").unlink()
    a = _by(history.attempts(cfg, HG), source="phylocli", stage="generax")[0]
    assert (a.status, a.peak_rss, a.realtime) == ("unknown", "-", "-")


def test_cache_finished_not_running(hist):
    _cli, cfg, calls, tmp = hist
    history.attempts(cfg, HG)
    history.attempts(cfg, HG)
    names = [l.split()[0] for l in calls.read_text().splitlines()]
    assert names.count("run_ok") == 1 and names.count("run_live") == 2 and "run_s1" not in names
    assert (tmp / "history/nf_run_ok.tsv").is_file()
    assert not (tmp / "history/nf_run_live.tsv").exists()
    first = calls.read_text().splitlines()[0].split()
    assert first[1] == str(cfg.nextflow_dir) and first[2] == "25.04.2"   # cwd, pinned NXF_VER


def test_old_dash_run_cached_newest_not(hist):
    """Only the newest run can still be running: an older "-" run is a dead session."""
    _cli, cfg, calls, tmp = hist
    hf = cfg.nextflow_dir / ".nextflow/history"
    hf.write_text(
        "2026-09-01 09:00:00\t-\trun_old\t-\th0\tu1\tnextflow run -ansi-log false step2.nf\n"
        + HISTORY)                                        # run_live ("-") is the newest here
    (tmp / "nflog/run_old.tsv").write_text(
        f"PHY\t{HG}\tFAILED\t137\t1\t4\t300 MB\t30m\t-\t1m\t/w/oo/9\t2026-09-01 09:10:00.000\n")
    history.attempts(cfg, HG)
    history.attempts(cfg, HG)
    names = [l.split()[0] for l in calls.read_text().splitlines()]
    assert names.count("run_old") == 1 and names.count("run_live") == 2
    assert (tmp / "history/nf_run_old.tsv").is_file()
    assert not (tmp / "history/nf_run_live.tsv").exists()
    # a newer finished run makes run_live old -> it is cached too
    hf.write_text(hf.read_text() + "2026-10-01 09:00:00\t1h\trun_new\tOK\th4\tu1\tnextflow run step2.nf\n")
    (tmp / "nflog/run_new.tsv").write_text("")
    history.attempts(cfg, HG)
    history.attempts(cfg, HG)
    names = [l.split()[0] for l in calls.read_text().splitlines()]
    assert names.count("run_live") == 3 and names.count("run_new") == 1
    assert (tmp / "history/nf_run_live.tsv").is_file()


def test_history_env_dir(hist, monkeypatch, tmp_path):
    _cli, cfg, _c, _t = hist
    monkeypatch.setenv("PHYLOCLI_HISTORY", str(tmp_path / "elsewhere"))
    history.attempts(cfg, HG)
    assert (tmp_path / "elsewhere/nf_run_ok.tsv").is_file()


def test_nextflow_missing_warns_and_keeps_phylocli(hist, monkeypatch):
    cli, cfg, calls, _t = hist
    monkeypatch.setenv("PATH", f"{_state['bin']}{os.pathsep}/usr/bin{os.pathsep}/bin")
    r = cli(["status", HG, "--history"])
    assert r.exit_code == 0, r.output
    assert "nextflow not on PATH: Nextflow history skipped" in r.output
    assert "20260930-120000_generax" in r.output and "run_ok" not in r.output
    assert not calls.exists()


def test_status_hg_table(hist):
    cli, _cfg, _c, _t = hist
    r = cli(["status", HG])
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0].split()[:3] == [HG, "(3", "seqs)"]
    rows = {l.split()[0]: l for l in lines if l.split() and l.split()[0] in core.HG_STAGES}
    assert list(rows) == core.HG_STAGES
    assert "done" in rows["align"] and "nextflow" in rows["align"]
    assert "ready" in rows["generax"] and "phylocli" in rows["generax"]
    assert "out of memory" in rows["generax"] and "1.2 GB" in rows["generax"]
    assert "blocked" in rows["possvm"] and "–" in rows["possvm"]
    assert "stage produced no output" in rows["gxsup"]
    assert "log (generax): " in r.output and "generax_777_1.err" in r.output
    assert "log (gxsup): /w/hh/8/.command.err" in r.output
    assert "log (align)" not in r.output


def test_status_hg_history(hist):
    cli, _cfg, _c, _t = hist
    r = cli(["status", HG, "--history"])
    assert r.exit_code == 0, r.output
    body = [l for l in r.output.splitlines() if "COMPLETED" in l or "FAILED" in l or "OUT_OF" in l]
    assert len(body) == 8                                  # 5 + gxsup (nf) + 2 phylocli
    assert "time limit (SIGUSR2 warning)" in r.output and "killed: out of memory?" in r.output
    assert "/w/bb/2/.command.err" in r.output
    assert "2026-09-01" in body[0] and "2026-09-30" in body[-1]      # oldest first


def test_unknown_hg(hist):
    cli, _cfg, _c, _t = hist
    r = cli(["status", "tfs.Z.HG9"])
    assert r.exit_code == 1 and "tfs.Z.HG9" in r.output


def test_hg_with_fam_or_ids_is_usage_error(hist, tmp_path):
    cli, _cfg, _c, _t = hist
    assert cli(["status", HG, "--fam", "tfs"]).exit_code == 2
    f = tmp_path / "ids.txt"
    f.write_text(HG + "\n")
    assert cli(["status", HG, "--ids", str(f)]).exit_code == 2


def test_status_without_hg_unchanged(hist):
    cli, _cfg, calls, _t = hist
    r = cli(["status"])
    assert r.exit_code == 0 and "HGs done" in r.output and not calls.exists()


def test_sacct_timeout_gives_unknown(hist, monkeypatch):
    import time
    _cli, cfg, _c, _t = hist
    p = _state["bin"] / "sacct"
    p.write_text("#!/bin/sh\nexec sleep 5\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(history, "SACCT_TIMEOUT", 1)
    t0 = time.time()
    a = _by(history.attempts(cfg, HG), source="phylocli", stage="generax")[0]
    assert (a.status, a.peak_rss, a.realtime) == ("unknown", "-", "-")
    assert time.time() - t0 < 4


def test_nextflow_log_timeout_skips_run(hist, monkeypatch):
    import time
    _cli, cfg, _c, tmp = hist
    nxf = tmp / "nfbin" / "nextflow"
    nxf.write_text("#!/bin/sh\nexec sleep 5\n")
    monkeypatch.setattr(history, "NEXTFLOW_TIMEOUT", 1)
    t0 = time.time()
    warned = []
    atts = history.attempts(cfg, HG, warn=warned.append)
    assert time.time() - t0 < 8
    assert not _by(atts, source="nextflow")
    assert any("timed out" in w for w in warned)


# ---- finished-array cache ------------------------------------------------------------------

def _count_sacct(monkeypatch):
    calls = []
    real = history._sacct

    def spy(ids):
        calls.append(list(ids))
        return real(ids)
    monkeypatch.setattr(history, "_sacct", spy)
    return calls


def _with_running(monkeypatch):
    _run(_state["runs"], "20261001-000000_tree", "tree", "888", [HG], _sbatch(1, "100M", 10))
    monkeypatch.setenv("FAKE_SACCT", SACCT + "888_0|RUNNING||00:00:05|0:0\\n")


def test_finished_arrays_cached_running_requeried(hist, monkeypatch):
    _cli, cfg, _c, _t = hist
    _with_running(monkeypatch)
    calls = _count_sacct(monkeypatch)
    first = history._phylocli_attempts(None)
    assert sorted(calls[0]) == ["555", "777", "888"]
    assert (history.history_dir() / "phylocli_arrays.json").is_file()
    second = history._phylocli_attempts(None)
    assert calls[1] == ["888"]                        # only the running array is queried again
    assert first == second


def test_cache_identical_with_and_without(hist, monkeypatch):
    _cli, cfg, _c, _t = hist
    _with_running(monkeypatch)
    history._phylocli_attempts(None)                  # fill
    cached = history._phylocli_attempts(None)
    (history.history_dir() / "phylocli_arrays.json").unlink()
    assert history._phylocli_attempts(None) == cached
    assert history._phylocli_attempts(HG) == [a for a in cached if a.hg == HG]


def test_changed_ids_file_invalidates(hist, monkeypatch):
    _cli, cfg, _c, _t = hist
    history._phylocli_attempts(None)
    calls = _count_sacct(monkeypatch)
    history._phylocli_attempts(None)
    assert [c for c in calls if c] == []              # everything cached, no sacct job queried
    ids = _state["runs"] / "20260901-000000_tree" / "ids_0.txt"
    ids.write_text("tfs.Z.HG9\n")
    atts = history._phylocli_attempts(None)
    assert [c for c in calls if c] == [["555"]]
    assert [a.hg for a in atts if a.run == "20260901-000000_tree"] == ["tfs.Z.HG9"]


def test_vanished_run_dir_dropped(hist):
    import json, shutil
    _cli, cfg, _c, _t = hist
    history._phylocli_attempts(None)
    shutil.rmtree(_state["runs"] / "20260901-000000_tree")
    history._phylocli_attempts(None)
    data = json.loads((history.history_dir() / "phylocli_arrays.json").read_text())
    assert not any("20260901-000000_tree" in k for k in json.dumps(data).split('"'))


def test_no_cache_without_sacct(hist):
    _cli, cfg, _c, _t = hist
    (_state["bin"] / "sacct").unlink()
    atts = history._phylocli_attempts(None)
    assert atts and all(a.status == "unknown" for a in atts)
    assert not (history.history_dir() / "phylocli_arrays.json").exists()
