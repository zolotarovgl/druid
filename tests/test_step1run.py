"""step1run: druid run's plan -- search arrays with per-task-linked cluster arrays (aftercorr),
cluster-only arrays, skipped done / no-hits / queued families, failing families dropped from both."""
from __future__ import annotations

import stat

import pytest

from druid import core, model, paths, setup_state, step1run
from tests.test_cli import _state, cli  # noqa: F401  (fixture: fake squeue / sacct on PATH)
from tests.test_setup_state import proj  # noqa: F401  (fixture: a fresh, unlocked project)

PREF = "x"


@pytest.fixture
def run(cli, monkeypatch):  # noqa: F811
    """The cli fixture's project with its own sbatch: prints 101, 102, ... (counter file), logs
    each call's argv as one line, fails on call FAKE_SBATCH_FAIL."""
    b = _state["bin"]
    sb = b / "sbatch"
    sb.write_text(
        "#!/bin/sh\n"
        f'n=$(cat {b}/count 2>/dev/null || echo 0); n=$((n + 1)); echo $n > {b}/count\n'
        f'echo "$@" >> {b}/sbatch.log\n'
        'if [ "$n" = "${FAKE_SBATCH_FAIL:-0}" ]; then echo "denied" >&2; exit 1; fi\n'
        'echo $((100 + n))\n')
    sb.chmod(sb.stat().st_mode | stat.S_IXUSR)
    monkeypatch.delenv("FAKE_SBATCH_FAIL", raising=False)
    return paths.project_root()


def _calls():
    f = _state["bin"] / "sbatch.log"
    return f.read_text().splitlines() if f.exists() else []


def _fams(root, names):
    """The genefam file holds exactly these families (ids x.<name>)."""
    (root / "gene_families_searchinfo.csv").write_text(
        "".join(f"{n}\tPF_{n}\t1.1\t3\tGA\tTF\t{PREF}\n" for n in names))
    return [f"{PREF}.{n}" for n in names]


def _cfg_raw():
    return core.load_config(paths.config_file()), paths.read_raw()


def _out(cfg, rel, text=""):
    p = cfg.outdir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _queued(root, stage, jid, ids, monkeypatch, k=1):
    """A druid array of `stage` in runs/ (jobs.tsv) whose job is listed by the fake squeue."""
    d = root / "runs" / f"20261001-00000{k}_{stage}"
    d.mkdir(parents=True)
    (d / "ids_0.txt").write_text("\n".join(ids) + "\n")
    (d / "jobs.tsv").write_text(f"{jid}\t{d / 'ids_0.txt'}\n")
    monkeypatch.setenv("FAKE_SQUEUE", f"{jid}_0|whatever\n")


def _ids(p):
    return [ids for _res, ids in p.groups]


def _five(run, monkeypatch):
    cfg, _raw = _cfg_raw()
    f1, f2, f3, f4, f5 = _fams(run, ["F1", "F2", "F3", "F4", "F5"])
    _out(cfg, f"search/{f2}.domains.fasta", ">a\nM\n")             # hits, not clustered
    _out(cfg, f"search/{f3}.domains.fasta", "")                    # no hits
    _out(cfg, f"search/{f4}.domains.fasta", ">a\nM\n")             # clustered
    _out(cfg, f"clusters/{f4}_cluster.tsv", "a\t1\n")
    _queued(run, "search", "900", [f5], monkeypatch)               # queued for search
    return f1, f2, f3, f4, f5


def test_plan_partitions_families(run, monkeypatch):
    f1, f2, *_ = _five(run, monkeypatch)
    cfg, raw = _cfg_raw()
    rp = step1run.plan_run(cfg, raw)
    assert _ids(rp.search) == [[f1]] and _ids(rp.linked) == [[f1]] and _ids(rp.only) == [[f2]]
    assert rp.search.stage == "search" and rp.linked.stage == "cluster" and rp.only.stage == "cluster"
    assert rp.counts == {"search": 1, "cluster_only": 1, "no_hits": 1, "done": 1, "queued": 1,
                         "dropped": 0}
    assert not rp.search.errors and not rp.linked.errors and not rp.only.errors
    # --fam narrows the families; nothing outside it is counted
    rp = step1run.plan_run(cfg, raw, fam=f2)
    assert rp.search is None and rp.linked is None and _ids(rp.only) == [[f2]]
    assert sum(rp.counts.values()) == 1


def test_counts_line():
    c = {"search": 3, "cluster_only": 1, "no_hits": 2, "done": 4, "queued": 0, "dropped": 0}
    assert (step1run.counts_line(c)
            == "search+cluster 3 · cluster only 1 · no hits 2 · done 4 · queued 0")
    assert (step1run.counts_line({**c, "dropped": 2})
            == "search+cluster 3 · cluster only 1 · no hits 2 · done 4 · queued 0 · dropped 2")


def test_submit_links_each_cluster_array(run, monkeypatch):
    _five(run, monkeypatch)
    cfg, raw = _cfg_raw()
    locks = []
    real = setup_state.lock_species
    monkeypatch.setattr(setup_state, "lock_species",
                        lambda r, c: locks.append(1) or real(r, c))
    rw = step1run.write(cfg, raw, step1run.plan_run(cfg, raw), dry_run=False)
    out, err = step1run.submit(rw)
    assert err is None
    assert out == [("search", "101", 1, None), ("cluster", "102", 1, "101"),
                   ("cluster", "103", 1, None)]
    s_script, l_script, o_script = (w.arrays[0][3] for w in (rw.search, rw.linked, rw.only))
    assert _calls() == [f"--parsable {s_script}",
                        f"--parsable --dependency=aftercorr:101 --kill-on-invalid-dep=yes {l_script}",
                        f"--parsable {o_script}"]
    assert (rw.linked.run_dir / "depends.tsv").read_text() == "102\t101\n"
    assert not (rw.only.run_dir / "depends.tsv").exists()
    for w, jid in ((rw.search, "101"), (rw.linked, "102"), (rw.only, "103")):
        assert (w.run_dir / "jobs.tsv").read_text() == f"{jid}\t{w.arrays[0][2]}\n"
        assert w.run_dir.parent == run / "runs"
    assert (rw.search.run_dir / "genefam.csv").is_file()          # search snapshots genefam.csv
    assert locks == [1]                                            # the lock is tried once, at 101


def test_chunks_pair_exactly(run, monkeypatch):
    monkeypatch.setattr(model, "MAX_ARRAY", 2)
    fams = _fams(run, ["F1", "F2", "F3", "F4", "F5"])
    cfg, raw = _cfg_raw()
    rp = step1run.plan_run(cfg, raw)
    assert [len(i) for i in _ids(rp.search)] == [2, 2, 1] and _ids(rp.linked) == _ids(rp.search)
    assert sorted(i for ids in _ids(rp.search) for i in ids) == fams
    rw = step1run.write(cfg, raw, rp, dry_run=False)
    for k in range(3):
        a, b = (rw.search.run_dir / f"ids_{k}.txt"), (rw.linked.run_dir / f"ids_{k}.txt")
        assert a.read_bytes() == b.read_bytes()
    out, err = step1run.submit(rw)
    assert err is None and rw.only is None
    assert out == [("search", "101", 2, None), ("cluster", "102", 2, "101"),
                   ("search", "103", 2, None), ("cluster", "104", 2, "103"),
                   ("search", "105", 1, None), ("cluster", "106", 1, "105")]
    calls = _calls()
    for k in range(3):
        assert calls[2 * k] == f"--parsable {rw.search.arrays[k][3]}"
        assert calls[2 * k + 1] == (f"--parsable --dependency=aftercorr:{101 + 2 * k} "
                                    f"--kill-on-invalid-dep=yes {rw.linked.arrays[k][3]}")
    assert (rw.linked.run_dir / "depends.tsv").read_text() == "102\t101\n104\t103\n106\t105\n"


def test_run_twice_skips_queued(run, monkeypatch):
    _fams(run, ["F1", "F2", "F3"])
    cfg, raw = _cfg_raw()
    out, err = step1run.submit(step1run.write(cfg, raw, step1run.plan_run(cfg, raw), dry_run=False))
    assert err is None and [o[1] for o in out] == ["101", "102"]
    monkeypatch.setenv("FAKE_SQUEUE", "101|t-search\n102|t-cluster\n")
    rp = step1run.plan_run(cfg, raw)
    assert rp.search is None and rp.linked is None and rp.only is None
    assert rp.counts["queued"] == 3 and rp.counts["search"] == 0


def test_cluster_sbatch_fails_after_search(run, monkeypatch):
    f1, f2 = _fams(run, ["F1", "F2"])
    cfg, raw = _cfg_raw()
    _out(cfg, f"search/{f2}.domains.fasta", ">a\nM\n")             # a cluster-only array too
    rw = step1run.write(cfg, raw, step1run.plan_run(cfg, raw), dry_run=False)
    monkeypatch.setenv("FAKE_SBATCH_FAIL", "2")
    out, err = step1run.submit(rw)
    assert out == [("search", "101", 1, None)]
    assert "101" in err and "the next druid run clusters them" in err
    assert "sbatch failed" in err and str(rw.only.arrays[0][3]) in err   # never submitted
    assert len(_calls()) == 2                                      # nothing after the failure
    assert not (rw.linked.run_dir / "jobs.tsv").exists()
    assert not (rw.linked.run_dir / "depends.tsv").exists()


def test_search_sbatch_fails_first(run, monkeypatch):
    _fams(run, ["F1"])
    cfg, raw = _cfg_raw()
    rw = step1run.write(cfg, raw, step1run.plan_run(cfg, raw), dry_run=False)
    monkeypatch.setenv("FAKE_SBATCH_FAIL", "1")
    out, err = step1run.submit(rw)
    assert out == [] and "submitted job ids: none" in err and len(_calls()) == 1
    assert str(rw.linked.arrays[0][3]) in err                      # its cluster array never goes


def test_stale_family_dropped_from_both(run, monkeypatch):
    f1, f6 = _fams(run, ["F1", "F6"])
    cfg, raw = _cfg_raw()
    _out(cfg, f"clusters/{f1}.HG1.fasta", ">a\nM\n")               # HG FASTA, no _cluster.tsv
    rp = step1run.plan_run(cfg, raw)
    assert _ids(rp.search) == [[f6]] and _ids(rp.linked) == [[f6]] and rp.only is None
    assert f"dropped (1): {f1}" in rp.notes
    assert rp.counts["dropped"] == 1 and rp.counts["search"] == 1
    # a searched family with stale HG FASTAs is dropped from the cluster-only arrays the same way
    f7, = _fams(run, ["F7"])
    _out(cfg, f"search/{f7}.domains.fasta", ">a\nM\n")
    _out(cfg, f"clusters/{f7}.HG1.fasta", ">a\nM\n")
    rp = step1run.plan_run(cfg, raw)
    assert rp.only is None and rp.notes == [f"dropped (1): {f7}"] and rp.counts["cluster_only"] == 0


def test_dry_run_writes_under_tmp(run):
    _fams(run, ["F1"])
    cfg, raw = _cfg_raw()
    rw = step1run.write(cfg, raw, step1run.plan_run(cfg, raw, dry_run=True), dry_run=True)
    dry = run / ".druid" / "tmp" / "dryrun"
    assert rw.search.run_dir.parent == dry and rw.linked.run_dir.parent == dry
    assert _calls() == [] and not (run / "runs").exists()


def test_refusal_cases(run, monkeypatch):
    cfg, raw = _cfg_raw()
    assert step1run.refusal(raw, cfg) == ""
    no = {k: v for k, v in raw.items() if k != "job_prefix"}
    assert (step1run.refusal(no, core.config_from_raw(no))
            == "ERROR: set job_prefix in Setup (druid.yaml job_prefix)")
    assert (step1run.refusal({**no, "prepare": "locked"}, core.config_from_raw(no))
            == "ERROR: druid run is not available on an adopted project (prepare: locked); "
               "use druid submit")
    infasta = cfg.params["infasta"]
    (run / "input.fasta").unlink()
    assert step1run.refusal(raw, cfg) == f"ERROR: run prepare first (no {infasta})"


def test_refusal_blockers_only_before_the_lock(proj):  # noqa: F811
    root, prot = proj
    (root / "data" / "input.fasta").write_text(">p\nM\n")
    raw = paths.read_raw()
    cfg = core.config_from_raw(raw)
    assert not setup_state.species_locked(raw, cfg)
    (prot / "Aaa_long.pep.fasta").unlink()                         # the ticked proteome moved
    msg = step1run.refusal(raw, cfg)
    assert msg.startswith("ERROR: Setup has blockers: ") and "Aaa: no proteome file" in msg
    assert step1run.refusal({**raw, "species_locked": True}, cfg) == ""
