import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from druid import cli as cli_mod, paths

_state = {}


def calls_txt():
    return _state["bin"] / "calls.txt"


def runs_dir():
    return _state["runs"]


def dry_dir():
    return _state["dry"]


def hide_tool(monkeypatch, name):
    """Make `name` absent from PATH: drop the fake and every real copy (a cluster node has a real
    squeue/sacct; a laptop does not)."""
    (_state["bin"] / name).unlink()
    keep = [d for d in os.environ["PATH"].split(os.pathsep) if not (Path(d) / name).exists()]
    monkeypatch.setenv("PATH", os.pathsep.join(keep))


@pytest.fixture
def cli(results_tree, tmp_path, monkeypatch):
    cfg, root = results_tree
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "sbatch").write_text(f'#!/bin/sh\necho "$@" >> {bindir}/calls.txt\necho 12345\n')
    (bindir / "squeue").write_text('#!/bin/sh\nprintf "%s" "${FAKE_SQUEUE:-}"\n')
    (bindir / "sacct").write_text('#!/bin/sh\nprintf "%b" "${FAKE_SACCT:-}"\n')
    for t in "mafft clipkit iqtree2 generax mpirun".split():
        (bindir / t).write_text("#!/bin/sh\nexit 0\n")
    (bindir / "python").write_text(
        '#!/bin/sh\n[ "$PYTHONNOUSERSITE" = 1 ] || { echo "PYTHONNOUSERSITE unset" >&2; exit 3; }\n'
        '[ "$PYTHONDONTWRITEBYTECODE" = 1 ] || { echo "PYTHONDONTWRITEBYTECODE unset" >&2; exit 4; }\n'
        'if [ -n "$FAKE_PY_FAIL" ]; then echo "ModuleNotFoundError: No module named ete3" >&2; exit 1; fi\n'
        'echo "$@" >> ' + str(bindir) + '/pycalls.txt\nexit 0\n')
    for p in bindir.iterdir():
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
    runs = root / "runs"                       # the fixture's druid.yaml: runs_dir: runs
    _state.update({"bin": bindir, "runs": runs, "dry": root / ".druid" / "tmp" / "dryrun"})
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SQUEUE", "")
    runner = CliRunner()
    return lambda args: runner.invoke(cli_mod.app, args)


def test_submit_refuses_existing_output(cli):
    r = cli(["submit", "align", "tfs.A.HG1", "tfs.A.HG11"])
    assert r.exit_code == 2 and "output_exists" in r.output and "tfs.A.HG1" in r.output
    assert not calls_txt().exists()
    assert not runs_dir().exists() or not list(runs_dir().glob("*"))


def test_submit_missing_dry_run(cli):
    r = cli(["submit", "align", "--missing", "--dry-run"])
    assert r.exit_code == 0 and "tfs.A.HG11" in r.output and "tfs.C_x.HG1" in r.output
    assert "dry run" in r.output and "nothing submitted (dry run)" in r.output
    row = next(l.split() for l in r.output.splitlines() if l.split()[:2] == ["0", "2"])
    assert row[2:] == ["4", "4.0", "GB", "4h", "normal", "–"]      # cpus, memory, time, qos, signal
    assert "array 0: tfs.A.HG11, tfs.C_x.HG1" in r.output
    assert not calls_txt().exists()
    run = next(dry_dir().glob("*_align"))
    assert (run / "ids_0.txt").read_text().split() == ["tfs.A.HG11", "tfs.C_x.HG1"]
    assert (run / "array_0.sbatch").exists()


def test_submit_real_writes_jobs_tsv(cli):
    r = cli(["submit", "align", "tfs.A.HG11"])
    assert r.exit_code == 0 and "--parsable" in calls_txt().read_text()
    run = next(runs_dir().glob("*_align"))
    assert (run / "jobs.tsv").read_text().startswith("12345\t")
    assert (run / "ids_0.txt").read_text().split() == ["tfs.A.HG11"]


def test_submit_all_refuses_already_queued(cli, monkeypatch):
    cli(["submit", "align", "tfs.A.HG11"])
    monkeypatch.setenv("FAKE_SQUEUE", "12345_0|phylo-align\n")
    r = cli(["submit", "align", "tfs.A.HG11", "--all"])
    assert r.exit_code == 2 and "queued" in r.output


def test_missing_lists_ids(cli):
    r = cli(["missing", "align"])
    assert r.output.split() == ["tfs.A.HG11", "tfs.C_x.HG1"]


def test_selection_is_exclusive(cli):
    assert cli(["submit", "align", "--missing", "tfs.A.HG11"]).exit_code != 0
    assert cli(["submit", "align"]).exit_code != 0


def test_sbatch_script_content(cli, results_tree):
    cfg, _ = results_tree
    (cfg.outdir / "align/tfs.A.HG11.aln.fasta").write_text(">a\nAA\n")
    r = cli(["submit", "tree", "tfs.A.HG11", "--dry-run"])
    assert r.exit_code == 0, r.output
    s = next(dry_dir().glob("*_tree")).joinpath("array_0.sbatch").read_text()
    assert "#SBATCH --signal=B:USR2@180" in s and "#SBATCH --mem=800M" in s and "#SBATCH --time=1140" in s  # resources.tsv row
    assert "#SBATCH --job-name=t-tree" in s and "--array=0-0%50" in s
    assert "kill -USR2 $PID" in s and "_run tree" in s
    run = next(dry_dir().glob("*_tree"))
    assert f"#SBATCH --chdir={run}\n" in s               # the job starts in its run dir, not in $HOME


def test_missing_tool_is_error(cli, monkeypatch, tmp_path):
    (_state["bin"] / "mafft").unlink()
    monkeypatch.setenv("PATH", str(_state["bin"]))
    r = cli(["submit", "align", "tfs.A.HG11", "--dry-run"])
    assert r.exit_code != 0 and "mafft" in r.output and "conda activate phylo" in r.output


def test_squeue_absent_only_ok_for_dry_run(cli, monkeypatch):
    (_state["bin"] / "squeue").unlink()
    monkeypatch.setenv("PATH", str(_state["bin"]) + os.pathsep + "/usr/nonexistent")
    # python3 must stay findable for nothing here: align needs only mafft/clipkit
    r = cli(["submit", "align", "tfs.A.HG11"])
    assert r.exit_code != 0 and "squeue" in r.output
    assert not calls_txt().exists()
    assert cli(["submit", "align", "tfs.A.HG11", "--dry-run"]).exit_code == 0


def test_status_prints_bars_not_table(cli):
    r = cli(["status"])
    assert r.exit_code == 0 and "HGs done" in r.output
    assert "TOTAL" not in r.output and "category" not in r.output
    assert any(l.split()[:1] == ["align"] for l in r.output.splitlines())


def _total(output, stage="align"):
    line = next(l for l in output.splitlines() if l.split()[:1] == [stage])
    return int(line.split()[5])              # stage done running ready blocked TOTAL


def test_status_fam_filters_by_whole_id_parts(cli):
    assert _total(cli(["status"]).output) == 3
    assert _total(cli(["status", "--fam", "tfs"]).output) == 3
    assert _total(cli(["status", "--fam", "tfs.A"]).output) == 2      # HG1, HG11
    assert _total(cli(["status", "-f", "tfs.C_x"]).output) == 1


def test_status_fam_no_partial_part_match(cli):
    r = cli(["status", "--fam", "tfs.C"])                              # must not match tfs.C_x
    assert r.exit_code == 1 and "no HGs match" in r.output


def test_missing_fam(cli, results_tree):
    _align_hg11(results_tree)
    assert cli(["missing", "align", "--all", "--fam", "tfs.C_x"]).output.split() == ["tfs.C_x.HG1"]
    assert _total(cli(["missing", "--fam", "tfs.A"]).output, "tree") == 2


def test_run_hidden_command(cli, results_tree, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli_mod, "run_one",
                        lambda cfg, stage, hg, work: seen.update(a=(stage, hg, work)) or 65)
    r = cli(["_run", "align", "tfs.A.HG11", "--run-dir", str(tmp_path / "rd")])
    assert r.exit_code == 65 and seen["a"] == ("align", "tfs.A.HG11", tmp_path / "rd" / "work")


def test_preflight_python_import_fails(cli, monkeypatch):
    monkeypatch.setenv("FAKE_PY_FAIL", "1")
    r = cli(["submit", "align", "tfs.A.HG11", "--dry-run"])
    assert r.exit_code != 0 and "ete3" in r.output and "python" in r.output
    assert "conda activate phylo" in r.output
    assert not runs_dir().exists() or not list(runs_dir().glob("*"))
    assert not calls_txt().exists()


def test_preflight_python_import_ok_sets_nousersite(cli):
    r = cli(["submit", "align", "tfs.A.HG11", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "import ete3, Bio, yaml" in (_state["bin"] / "pycalls.txt").read_text()


def test_preflight_skips_python_for_gxsup(cli, monkeypatch):
    monkeypatch.setenv("FAKE_PY_FAIL", "1")
    cli_mod._preflight("gxsup")  # must not exit


def test_chunks_of_1000():
    ids = [f"hg{i}" for i in range(2500)]
    ch = cli_mod._chunks(ids)
    assert [len(c) for c in ch] == [1000, 1000, 500]
    assert [x for c in ch for x in c] == ids
    assert cli_mod._chunks(ids[:1000]) == [ids[:1000]] and cli_mod._chunks([]) == []


def _align_hg11(results_tree):
    cfg, _ = results_tree
    (cfg.outdir / "align" / "tfs.A.HG11.aln.fasta").write_text(">a\nMK\n>b\nMK\n")


def test_missing_default_is_ready_all_lists_everything(cli, results_tree):
    _align_hg11(results_tree)
    assert cli(["missing", "tree"]).output.split() == ["tfs.A.HG11"]
    assert cli(["missing", "tree", "--all"]).output.split() == ["tfs.A.HG11", "tfs.C_x.HG1"]


def test_submit_missing_skips_unready_by_default(cli, results_tree):
    _align_hg11(results_tree)
    r = cli(["submit", "tree", "--missing", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "skipped 1 HGs without inputs" in r.output
    run = next(dry_dir().glob("*_tree"))
    assert (run / "ids_0.txt").read_text().split() == ["tfs.A.HG11"]


def test_submit_all_is_strict(cli, results_tree):
    _align_hg11(results_tree)
    r = cli(["submit", "tree", "--missing", "--all", "--dry-run"])
    assert r.exit_code == 2 and "input_missing" in r.output


def test_submit_nothing_ready(cli):
    r = cli(["submit", "tree", "--missing", "--dry-run"])
    assert r.exit_code == 0 and "nothing to submit" in r.output
    assert not runs_dir().exists() or not list(runs_dir().glob("*"))


def test_submit_skips_queued_by_default(cli, results_tree, monkeypatch):
    _align_hg11(results_tree)
    assert cli(["submit", "tree", "tfs.A.HG11"]).exit_code == 0
    monkeypatch.setenv("FAKE_SQUEUE", "12345_0|phylo-tree\n")
    r = cli(["submit", "tree", "--missing"])
    assert r.exit_code == 0 and "skipped 1 HGs already queued" in r.output
    assert "nothing to submit" in r.output


def test_existing_output_still_refused_by_default(cli):
    r = cli(["submit", "align", "tfs.A.HG1"])
    assert r.exit_code == 2 and "output_exists" in r.output


def test_missing_without_stage_prints_summary(cli, results_tree):
    _align_hg11(results_tree)
    r = cli(["missing"])
    assert r.exit_code == 0, r.output
    rows = {l.split()[0]: l.split()[1:6] for l in r.output.splitlines()[1:] if l.strip()}
    # 3 expected HGs; align: HG1 done, HG11 has align (fixture) -> done too; C_x ready (clusters exist)
    assert rows["align"] == ["2", "0", "1", "0", "3"]          # done running ready blocked total
    # tree: HG1 done; HG11 ready (alignment); C_x blocked (no alignment)
    assert rows["tree"] == ["1", "0", "1", "1", "3"]
    assert "\x1b[" not in r.output          # no colour codes when not a terminal
    assert all(len(l) > 40 for l in r.output.splitlines()[1:] if l.strip())   # bar present


def test_ready_set_matches_inputs_ready(results_tree):
    from druid import core
    cfg, _ = results_tree
    _align_hg11(results_tree)
    hgs = sorted(core.expected(cfg))
    for st in core.STAGES:
        if core.applicable(cfg, st):
            assert core.ready_set(cfg, st, hgs) == {h for h in hgs if core.inputs_ready(cfg, st, h)}


def _bar_of(output, stage):
    lines = output.splitlines()
    hdr = next(l for l in lines if l.split()[:1] == ["stage"])
    col = hdr.index("total") + len("total") + 2          # bars start under the legend
    line = next(l for l in lines if l.split() and l.split()[0] == stage)
    return line[col:].rstrip()


def test_status_appends_stage_summary(cli, results_tree):
    _align_hg11(results_tree)
    r = cli(["status"])
    assert r.exit_code == 0 and "HGs done" in r.output
    bar = _bar_of(r.output, "tree")                  # tree: done 1, ready 1, blocked 1
    assert bar == "█" * 10 + "▓" * 10 + "░" * 10


def test_missing_summary_blank_done_green_ready(cli, results_tree):
    _align_hg11(results_tree)
    bar = _bar_of(cli(["missing"]).output, "tree")
    assert bar == " " * 10 + "█" * 10 + "░" * 10


def test_submit_missing_fam(cli, results_tree):
    r = cli(["submit", "align", "--missing", "-f", "tfs.C_x", "--dry-run"])
    assert r.exit_code == 0, r.output
    run = next(dry_dir().glob("*_align"))
    assert (run / "ids_0.txt").read_text().split() == ["tfs.C_x.HG1"]


def test_submit_fam_no_match(cli):
    r = cli(["submit", "align", "--missing", "--fam", "tfs.C", "--dry-run"])
    assert r.exit_code == 1 and "no HGs match" in r.output


def test_missing_per_fam_counts(cli, results_tree):
    _align_hg11(results_tree)
    # tree: tfs.A has HG1 (done) + HG11 (ready); tfs.C_x has HG1 (blocked: no alignment)
    out = [l for l in cli(["missing", "tree", "--per-fam"]).output.split("\n") if l.strip()]
    assert out[0].split() == ["family", "ready/total"]
    assert dict(l.split() for l in out[1:]) == {"tfs.A": "1/2"}   # ready only; C_x omitted
    out = [l for l in cli(["missing", "tree", "--per-fam", "--all"]).output.split("\n") if l.strip()]
    assert out[0].split() == ["family", "missing/total"]
    assert dict(l.split() for l in out[1:]) == {"tfs.A": "1/2", "tfs.C_x": "1/1"}


def test_dry_run_short_flag(cli):
    r = cli(["submit", "align", "--missing", "-n"])
    assert r.exit_code == 0, r.output
    assert not calls_txt().exists()                       # sbatch never called
    assert next(dry_dir().glob("*_align"))


def test_per_fam_sorted_by_count(cli, results_tree):
    cfg, _ = results_tree
    for i in (1, 2, 3):
        (cfg.outdir / "clusters" / f"tfs.Z.HG{i}.fasta").write_text(">a\nAA\n>b\nAA\n")
    out = [l.split() for l in cli(["missing", "align", "--per-fam"]).output.split("\n")[1:] if l.strip()]
    # tfs.Z 3/3, tfs.A 1/2 (HG11), tfs.C_x 1/1  -> by count desc, then total desc
    assert [r[0] for r in out] == ["tfs.Z", "tfs.A", "tfs.C_x"]


def _hg11_aligned_tree_script(cli, results_tree, *extra):
    cfg, _ = results_tree
    (cfg.outdir / "align/tfs.A.HG11.aln.fasta").write_text(">a\nAA\n")
    r = cli(["submit", "tree", "tfs.A.HG11", "-n", *extra])
    assert r.exit_code == 0, r.output
    return r.output, next(dry_dir().glob("*_tree")).joinpath("array_0.sbatch").read_text()


def test_resource_overrides(cli, results_tree):
    out, s = _hg11_aligned_tree_script(cli, results_tree, "--mem", "16G", "--time", "2h", "--cpus", "8")
    assert "#SBATCH --mem=16384M" in s and "#SBATCH --time=120" in s and "#SBATCH --cpus-per-task=8" in s


def test_partial_override_keeps_table_values(cli, results_tree):
    out, s = _hg11_aligned_tree_script(cli, results_tree, "--time", "1d")
    assert "#SBATCH --time=1440" in s and "#SBATCH --mem=800M" in s     # mem still from resources.tsv


def test_notifies_resources_tsv_rows(cli, results_tree):
    out, _ = _hg11_aligned_tree_script(cli, results_tree)
    assert "resources.tsv: row found for 1 of 1 HGs" in out


def test_notifies_zero_rows(cli):
    r = cli(["submit", "align", "tfs.C_x.HG1", "-n"])
    assert r.exit_code == 0 and "resources.tsv: row found for 0 of 1 HGs" in r.output


def test_bad_override_is_error(cli):
    r = cli(["submit", "align", "tfs.C_x.HG1", "-n", "--mem", "16X"])
    assert r.exit_code != 0 and "bad memory value" in r.output
    assert not runs_dir().exists() or not list(runs_dir().glob("*"))


def test_unknown_id_reported_not_skipped(cli):
    r = cli(["submit", "align", "tfs.C_x.HG1.", "-n"])        # typo: trailing dot
    assert r.exit_code == 2
    assert "unknown" in r.output and "tfs.C_x.HG1." in r.output
    assert "without inputs" not in r.output


def test_dry_run_leaves_runs_dir_empty(cli):
    r = cli(["submit", "align", "--missing", "-n"])
    assert r.exit_code == 0, r.output
    assert not runs_dir().exists() or not list(runs_dir().glob("*"))
    assert len(list(dry_dir().glob("*_align"))) == 1


def _submit_two_align(cli):
    r = cli(["submit", "align", "--missing"])          # one array, 2 HGs: HG11 (task 0), C_x (task 1)
    assert r.exit_code == 0, r.output


def _row(output, jid="12345"):
    """Summary row tokens without the trailing progress bar."""
    toks = next(l.split() for l in output.splitlines() if jid in l.split())
    return toks[:-1] if set(toks[-1]) <= set("█×▓░") else toks


def test_jobs_counts_from_sacct(cli, monkeypatch):
    _submit_two_align(cli)
    monkeypatch.setenv("FAKE_SACCT", "12345_0|FAILED\\n12345_1|RUNNING\\n")
    r = cli(["jobs"])
    assert r.exit_code == 0, r.output
    row = _row(r.output)
    assert row[-5:] == ["2", "0", "1", "0", "1"]        # HGs, pending, running, done, failed


def test_jobs_pending_range_and_unseen_tasks(cli, monkeypatch):
    _submit_two_align(cli)
    monkeypatch.setenv("FAKE_SACCT", "12345_[0-1%50]|PENDING\\n")
    assert _row(cli(["jobs"]).output)[-5:] == ["2", "2", "0", "0", "0"]
    monkeypatch.setenv("FAKE_SACCT", "")               # not in sacct yet -> pending
    assert _row(cli(["jobs"]).output)[-5:] == ["2", "2", "0", "0", "0"]


def test_jobs_completed_and_cancelled(cli, monkeypatch):
    _submit_two_align(cli)
    monkeypatch.setenv("FAKE_SACCT", "12345_0|COMPLETED\\n12345_1|CANCELLED by 1000\\n")
    assert _row(cli(["jobs"]).output)[-5:] == ["2", "0", "0", "1", "1"]


def test_jobs_failed_lists_hgs_and_logs(cli, monkeypatch):
    _submit_two_align(cli)
    monkeypatch.setenv("FAKE_SACCT", "12345_0|COMPLETED\\n12345_1|OUT_OF_MEMORY\\n")
    r = cli(["jobs", "--failed"])
    assert r.exit_code == 0, r.output
    line = next(l for l in r.output.splitlines() if "tfs.C_x.HG1" in l)
    assert "OUT_OF_MEMORY" in line and "align_12345_1.err" in line
    assert "tfs.A.HG11" not in r.output


def test_queue_is_hidden_alias(cli, monkeypatch):
    _submit_two_align(cli)
    monkeypatch.setenv("FAKE_SACCT", "12345_0|COMPLETED\\n12345_1|COMPLETED\\n")
    assert _row(cli(["queue"]).output)[-5:] == ["2", "0", "0", "2", "0"]
    assert "queue" not in cli(["--help"]).output


def test_jobs_without_sacct_shows_unknown(cli, monkeypatch):
    _submit_two_align(cli)
    hide_tool(monkeypatch, "sacct")
    r = cli(["jobs"])
    assert r.exit_code == 0 and "sacct not on PATH" in r.output
    assert _row(r.output)[-5:] == ["2", "?", "?", "?", "?"]


def _dry_run_dir(stage):
    return next(dry_dir().glob(f"*_{stage}"))


def test_set_param_written_to_run_config(cli, results_tree):
    import yaml
    _, root = results_tree
    before = (root / "druid.yaml").read_text()
    r = cli(["submit", "align", "tfs.C_x.HG1", "-n", "--set", "MAFFT_OPT=--auto", "--set", "MAX_SPR=2"])
    assert r.exit_code == 0, r.output
    run = _dry_run_dir("align")
    params = yaml.safe_load((run / "config.yaml").read_text())["params"]
    assert params["MAFFT_OPT"] == "--auto" and params["MAX_SPR"] == 2
    text = (run / "array_0.sbatch").read_text()
    assert f'export DRUID_CONFIG="{run}/config.yaml"' in text
    assert f'export DRUID_PROJECT="{paths.project_root()}"' in text
    assert f'python3 "{paths.DRUID_HOME}/druid/cli.py" _run' in text
    assert "#SBATCH --job-name=t-" in text
    assert "MAX_SPR=2" in r.output
    assert (root / "druid.yaml").read_text() == before        # global config untouched


def test_set_bool_coerced_and_used_at_submit(cli):
    r = cli(["submit", "generax", "tfs.A.HG11", "-n", "--set", "run_generax=false"])
    assert r.exit_code == 2 and "not_applicable" in r.output


def test_set_unknown_key_is_error(cli):
    r = cli(["submit", "align", "tfs.C_x.HG1", "-n", "--set", "MAXSPR=2"])
    assert r.exit_code == 2 and "MAXSPR" in r.output
    assert not dry_dir().exists() or not list(dry_dir().glob("*"))


def test_set_malformed_is_error(cli):
    r = cli(["submit", "align", "tfs.C_x.HG1", "-n", "--set", "MAX_SPR"])
    assert r.exit_code == 2 and "KEY=VALUE" in r.output


def test_set_bad_type_is_error(cli):
    r = cli(["submit", "align", "tfs.C_x.HG1", "-n", "--set", "MAX_SPR=two"])
    assert r.exit_code == 2 and "MAX_SPR" in r.output


def test_run_config_always_written(cli):
    assert cli(["submit", "align", "tfs.C_x.HG1", "-n"]).exit_code == 0
    run = _dry_run_dir("align")
    assert (run / "config.yaml").exists()
    assert "export DRUID_CONFIG=" in (run / "array_0.sbatch").read_text()


def _task_rows(output):
    return {l.split()[1]: l.split() for l in output.splitlines()
            if l.split() and l.split()[0].isdigit() and "·" not in l}


def test_jobs_jobid_lists_tasks_with_hgs(cli, monkeypatch):
    _submit_two_align(cli)        # task 0 = tfs.A.HG11, task 1 = tfs.C_x.HG1
    monkeypatch.setenv("FAKE_SACCT", "12345_0|COMPLETED\\n12345_1|RUNNING\\n")
    r = cli(["jobs", "12345"])
    assert r.exit_code == 0, r.output
    rows = _task_rows(r.output)
    assert rows["tfs.A.HG11"][:3] == ["0", "tfs.A.HG11", "COMPLETED"]
    assert rows["tfs.C_x.HG1"][:3] == ["1", "tfs.C_x.HG1", "RUNNING"]
    assert "align_12345_1.err" in r.output


def test_jobs_jobid_filters(cli, monkeypatch):
    _submit_two_align(cli)
    monkeypatch.setenv("FAKE_SACCT", "12345_0|COMPLETED\\n12345_1|TIMEOUT\\n")
    assert list(_task_rows(cli(["jobs", "12345", "--failed"]).output)) == ["tfs.C_x.HG1"]
    assert list(_task_rows(cli(["jobs", "12345", "--running"]).output)) == []


def test_jobs_jobid_pending_when_not_in_sacct(cli, monkeypatch):
    _submit_two_align(cli)
    monkeypatch.setenv("FAKE_SACCT", "")
    rows = _task_rows(cli(["jobs", "12345"]).output)
    assert rows["tfs.A.HG11"][2] == "PENDING" and rows["tfs.C_x.HG1"][2] == "PENDING"


def test_jobs_unknown_jobid(cli):
    _submit_two_align(cli)
    r = cli(["jobs", "999"])
    assert r.exit_code == 1 and "999" in r.output


def test_jobs_summary_has_fraction_bar(cli, monkeypatch):
    _submit_two_align(cli)
    monkeypatch.setenv("FAKE_SACCT", "12345_0|FAILED\\n12345_1|RUNNING\\n")
    line = next(l for l in cli(["jobs"]).output.splitlines() if "12345" in l.split())
    bar = line.split()[-1]
    assert bar == "×" * 10 + "▓" * 10                 # failed 1 of 2, running 1 of 2 (width 20)


def test_jobs_summary_bar_done_and_pending(cli, monkeypatch):
    _submit_two_align(cli)
    monkeypatch.setenv("FAKE_SACCT", "12345_0|COMPLETED\\n")     # task 1 not reported -> pending
    bar = next(l for l in cli(["jobs"]).output.splitlines() if "12345" in l.split()).split()[-1]
    assert bar == "█" * 10 + "░" * 10


def _summary_rows(output):
    return {l.split()[0]: l.split()[1:6] for l in output.splitlines()
            if l.split() and l.split()[0] in ("align", "tree", "possvm_prev", "generax", "gxsup", "possvm")}


def test_running_phylocli_array_task_counted(cli, monkeypatch):
    _submit_two_align(cli)                      # task 0 = tfs.A.HG11, task 1 = tfs.C_x.HG1
    monkeypatch.setenv("FAKE_SQUEUE", "12345_1|phylo-align\n")
    rows = _summary_rows(cli(["missing"]).output)
    assert rows["align"] == ["1", "1", "1", "0", "3"]      # HG1 done, C_x running, HG11 ready


def test_running_nextflow_job_counted(cli, results_tree, monkeypatch):
    _align_hg11(results_tree)
    monkeypatch.setenv("FAKE_SQUEUE", "999|nf-PHY_(tfs.A.HG11)\n")
    rows = _summary_rows(cli(["status"]).output)
    assert rows["tree"] == ["1", "1", "0", "1", "3"]       # HG1 done, HG11 running (Nextflow), C_x blocked
    r = cli(["submit", "tree", "--missing", "-n"])
    assert "skipped 1 HGs already queued" in r.output and "nothing to submit" in r.output


def test_running_bar_segment(cli, results_tree, monkeypatch):
    _align_hg11(results_tree)
    monkeypatch.setenv("FAKE_SQUEUE", "999|nf-PHY_(tfs.A.HG11)\n")
    assert _bar_of(cli(["status"]).output, "tree") == "█" * 10 + "▒" * 10 + "░" * 10


def test_status_hg_shows_running(cli, results_tree, monkeypatch):
    _align_hg11(results_tree)
    monkeypatch.setenv("FAKE_SQUEUE", "999|nf-PHY_(tfs.A.HG11)\n")
    line = next(l for l in cli(["status", "tfs.A.HG11"]).output.splitlines() if l.split()[:1] == ["tree"])
    assert line.split()[1] == "running"


def test_summary_without_squeue(cli, monkeypatch):
    hide_tool(monkeypatch, "squeue")
    r = cli(["missing"])
    assert r.exit_code == 0 and "squeue not on PATH" in r.output


def test_cli_outside_project_says_how(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from druid import cli, paths
    monkeypatch.delenv("DRUID_PROJECT", raising=False)
    monkeypatch.delenv("DRUID_CONFIG", raising=False)
    paths.use(None)
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli.app, ["status"])
    assert r.exit_code == 2
    assert "--project" in r.output and "druid init" in r.output
    assert "Traceback" not in r.output


def test_project_option_selects_the_project(results_tree, tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from druid import cli, paths
    _cfg, root = results_tree
    monkeypatch.delenv("DRUID_PROJECT", raising=False)
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli.app, ["--project", str(root), "missing"])
    assert r.exit_code == 0, r.output
    assert paths.project_root() == root.resolve()
    paths.use(None)


def test_dry_run_scripts_go_under_the_project(results_tree):
    from druid import model, paths
    d = model.new_run_dir("align", dry_run=True)
    assert d.parent == paths.project_root() / ".druid" / "tmp" / "dryrun"


def _set_druid_yaml(root, **kv):
    import yaml
    f = root / "druid.yaml"
    raw = yaml.safe_load(f.read_text())
    raw.update(kv)
    f.write_text(yaml.safe_dump(raw))


def test_outdir_outside_the_project_is_a_clean_error(cli, results_tree, tmp_path):
    _cfg, root = results_tree
    _set_druid_yaml(root, outdir=str(tmp_path / "outside"))
    r = cli(["status"])
    assert r.exit_code == 2 and "inside the project" in r.output
    assert "Traceback" not in r.output and not (tmp_path / "outside").exists()


def test_runs_dir_equal_to_the_project_is_a_clean_error(cli, results_tree):
    _cfg, root = results_tree
    _set_druid_yaml(root, runs_dir=".")
    r = cli(["status"])
    assert r.exit_code == 2 and "runs_dir must be a subdirectory" in r.output
    assert "Traceback" not in r.output


def test_submit_set_outside_write_target_is_a_clean_error(cli, tmp_path):
    outside = tmp_path / "outside.fasta"
    r = cli(["submit", "align", "tfs.C_x.HG1", "-n", "--set", f"infasta={outside}"])
    assert r.exit_code == 2 and "inside the project" in r.output
    assert "Traceback" not in r.output
    assert not dry_dir().exists() or not list(dry_dir().glob("*"))


def test_submit_history_dir_outside_the_project_is_a_clean_error(cli, monkeypatch, tmp_path):
    monkeypatch.setenv("DRUID_HISTORY", str(tmp_path / "outside"))
    r = cli(["submit", "align", "tfs.C_x.HG1", "-n"])
    assert r.exit_code == 2 and "ERROR:" in r.output and "outside the project" in r.output
    assert "Traceback" not in r.output and not (tmp_path / "outside").exists()
    assert not dry_dir().exists() or not list(dry_dir().glob("*"))


def test_usage_says_druid_not_cli_py(results_tree, monkeypatch, capsys):
    """bin/druid runs druid/cli.py: the usage lines name druid (Grygoriy, 23/10/2026)."""
    import runpy
    import sys
    for args, want in ((["--help"], "Usage: druid [OPTIONS] COMMAND"),
                       (["init", "--help"], "Usage: druid init [OPTIONS]")):
        monkeypatch.setattr(sys, "argv", [str(paths.DRUID_HOME / "druid" / "cli.py"), *args])
        with pytest.raises(SystemExit) as e:
            runpy.run_path(str(paths.DRUID_HOME / "druid" / "cli.py"), run_name="__main__")
        out = capsys.readouterr().out
        assert e.value.code == 0 and want in out and "cli.py" not in out


def _tty(monkeypatch, on):
    from druid import tui as tui_mod
    started = []
    monkeypatch.setattr(tui_mod.PhyloApp, "run", lambda self, **kw: started.append(self))
    monkeypatch.setattr(cli_mod, "_on_terminal", lambda: on)  # CliRunner swaps sys.stdin/stdout
    return started


def test_init_not_a_tty_does_not_open_tui(tmp_path, monkeypatch):
    from druid import tui as tui_mod
    started = []
    monkeypatch.setattr(tui_mod.PhyloApp, "run", lambda self, **kw: started.append(self))
    r = CliRunner().invoke(cli_mod.app, ["init", str(tmp_path / "p")])
    assert r.exit_code == 0 and not started
    assert "druid tui" in r.output and (tmp_path / "p" / "druid.yaml").is_file()


def test_init_no_tui_never_starts_app(tmp_path, monkeypatch):
    started = _tty(monkeypatch, True)
    r = CliRunner().invoke(cli_mod.app, ["init", str(tmp_path / "p"), "--no-tui"])
    assert r.exit_code == 0 and not started


def test_init_without_dest_uses_the_current_dir(tmp_path, monkeypatch):
    _tty(monkeypatch, False)
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli_mod.app, ["init"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "druid.yaml").is_file()


def test_init_without_dest_in_a_non_empty_dir_writes_nothing(tmp_path, monkeypatch):
    _tty(monkeypatch, False)
    (tmp_path / "x.txt").write_text("keep")
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli_mod.app, ["init"])
    assert r.exit_code == 2 and "not empty" in r.output
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.txt"]


def test_init_on_a_tty_opens_tui_on_new_project(tmp_path, monkeypatch):
    started = _tty(monkeypatch, True)
    try:
        r = CliRunner().invoke(cli_mod.app, ["init", str(tmp_path / "p")])
        assert r.exit_code == 0, r.output
        assert len(started) == 1
        assert Path(started[0].cfg.nextflow_dir).resolve() == (tmp_path / "p").resolve()  # project root
    finally:
        paths.use(None)


# ---- druid run (step 1 in one command) -------------------------------------------------------
from tests.step1run_helpers import _calls as _run_calls, _cfg_raw as _run_cfg_raw, _five as _run_five  # noqa: E402
from tests.step1run_helpers import run  # noqa: E402,F401  (fixture: counting sbatch)


def test_run_dry_run_prints_plan(run, cli, monkeypatch):
    _run_five(run, monkeypatch)
    r = cli(["run", "-n"])
    assert r.exit_code == 0, r.output
    assert "search+cluster 1 · cluster only 1 · no hits 1 · done 1 · queued 1" in r.output
    assert r.output.count("dry run ·") == 3                      # search, linked cluster, cluster only
    # runs/ holds only the fixture's queued search run (_five), nothing the dry run wrote
    assert _run_calls() == [] and [d.name for d in (run / "runs").iterdir()] == ["20261001-000001_search"]
    assert dry_dir().is_dir()


def test_run_submits_and_reports(run, cli, monkeypatch):
    _run_five(run, monkeypatch)
    r = cli(["run"])
    assert r.exit_code == 0, r.output
    lines = [l for l in r.output.splitlines() if l.startswith("submitted")]
    assert lines[0].startswith("submitted 101: search 1 families ")
    assert lines[1].startswith("submitted 102: cluster 1 families (after 101) ")
    assert lines[2].startswith("submitted 103: cluster 1 families ")
    assert "after" not in lines[2]
    assert all(l.endswith(" min)") and " cpus, " in l for l in lines)       # resources tail
    assert "search+cluster 1 · cluster only 1" in r.output
    assert len(_run_calls()) == 3 and "--dependency=aftercorr:101" in _run_calls()[1]


def test_run_refuses_without_squeue(run, cli, monkeypatch):
    _run_five(run, monkeypatch)
    hide_tool(monkeypatch, "squeue")
    r = cli(["run"])
    assert r.exit_code == 1 and "squeue not on PATH" in r.output
    assert _run_calls() == []


def test_run_refusals_and_nothing_to_do(run, cli, monkeypatch):
    cfg, raw = _run_cfg_raw()
    from druid import paths as _paths
    yml = _paths.config_file()
    text = yml.read_text()
    yml.write_text("".join(l for l in text.splitlines(True) if not l.startswith("job_prefix:")))
    r = cli(["run"])
    assert r.exit_code == 2 and "ERROR: set job_prefix in Setup (druid.yaml job_prefix)" in r.output
    assert _run_calls() == []
    yml.write_text(text)
    (run / "input.fasta").unlink()
    r = cli(["run"])
    assert r.exit_code == 2 and "ERROR: run prepare first" in r.output
    assert _run_calls() == []
    (run / "input.fasta").write_text(">p\nM\n")
    # every family done or queued: nothing to submit, exit 0
    fams = ["x.F1"]
    (run / "gene_families_searchinfo.csv").write_text("F1\tPF\t1.1\t3\tGA\tTF\tx\n")
    (cfg.outdir / "search").mkdir(parents=True, exist_ok=True)
    (cfg.outdir / f"search/{fams[0]}.domains.fasta").write_text("")      # no hits
    r = cli(["run"])
    assert r.exit_code == 0 and "nothing to submit" in r.output
    assert "search+cluster 0 · cluster only 0 · no hits 1 · done 0 · queued 0" in r.output
    assert _run_calls() == [] and not (run / "runs").exists()


def test_run_submit_failure_reports_ids(run, cli, monkeypatch):
    _run_five(run, monkeypatch)
    monkeypatch.setenv("FAKE_SBATCH_FAIL", "2")
    r = cli(["run"])
    assert r.exit_code == 1 and "submitted 101: search" in r.output
    assert "denied" in r.output


def _linked_runs(cli):
    from druid import paths as _p
    runs = _p.runs_dir()
    for name, jid in (("20261001-100000_search", "101"), ("20261001-100001_cluster", "102")):
        d = runs / name
        d.mkdir(parents=True)
        (d / "ids_0.txt").write_text("F1\nF2\nF3\n")
        (d / "jobs.tsv").write_text(f"{jid}\t{d / 'ids_0.txt'}\n")
    (runs / "20261001-100001_cluster" / "depends.tsv").write_text("102\t101\n")


LINKED = ("101_0|COMPLETED\\n101_1|FAILED\\n101_2|COMPLETED\\n"
          "102_0|COMPLETED\\n102_1|CANCELLED by 0\\n102_2|CANCELLED by 0\\n")


def test_jobs_cascade_cancel_is_not_a_cluster_failure(cli, monkeypatch):
    _linked_runs(cli)
    monkeypatch.setenv("FAKE_SACCT", LINKED)
    r = cli(["jobs", "--last", "1", "--stage", "cluster"])
    assert r.exit_code == 0, r.output
    # HGs, pending, running, done, failed: only the real cancel (task 2) counts as failed
    assert _row(r.output, "102")[-5:] == ["3", "0", "0", "1", "1"]
    assert "1 cancelled: search failed" in r.output
    r = cli(["jobs", "--failed", "--stage", "cluster"])
    assert "F3" in r.output and "F2" not in r.output
    r = cli(["jobs", "102"])
    assert "cancelled: search failed" in r.output
    r = cli(["jobs", "102", "--failed"])
    assert "F3" in r.output and "F2" not in r.output
    from druid import model
    rows, _k = model.array_rows("cluster", 1)
    assert rows[0].counts["failed"] == 1 and rows[0].counts["cancelled"] == 1
