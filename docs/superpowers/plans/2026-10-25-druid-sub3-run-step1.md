# druid sub-project 3 — `druid run` (linked search → cluster) + job_prefix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command / TUI key submits step 1 — `search` plus a per-task-linked `cluster` — for every family not yet done; every job is named `<job_prefix>-<stage>`.

**Architecture:** A new `druid/step1run.py` plans the run from `core.family_done` + `model.live_hgs`, builds the search / linked-cluster / cluster-only `model.Plan`s, writes them with `model.write_run` and queues them through `model.sbatch_all` (extended with an `aftercorr` dependency). `druid run` (cli) and a TUI `RunScreen` both call it. `job_prefix` lives in `druid.yaml`; druid recognises its jobs by job id from `runs/*/jobs.tsv`, not by name.

**Tech Stack:** Python 3.9, Typer, Textual 8.2, SLURM 25.11.5 (CRG).

**Spec:** `docs/superpowers/specs/2026-10-25-druid-sub3-run-step1-design.md` (parent `docs/superpowers/specs/2026-10-14-druid-standalone-design.md`).

## Global Constraints

- Python 3.9 (CRG `phylo` env): no `match`, no `X | Y` at runtime outside `from __future__ import annotations`, no 3.10-only stdlib args.
- Textual >= 8.2, < 9; no new dependencies.
- Every write goes through `druid.paths`; every new write site passes `tests/test_write_boundary.py`.
- Tests use fake `sbatch` / `squeue` / `sacct` on PATH (pattern: `tests/test_cli.py:38-53`); no real job is submitted.
- Linked cluster arrays use exactly `--dependency=aftercorr:<search job id>` and `--kill-on-invalid-dep=yes` on the sbatch command line.
- `job_prefix`: letters, digits and `_`, 1–20 characters, first a letter (regex `^[A-Za-z][A-Za-z0-9_]{0,19}$`).
- Job name `<job_prefix>-<stage>`; adopted projects (`prepare: locked`) without a prefix keep `phylo-<stage>`.
- Refusal text when the prefix is missing: `ERROR: set job_prefix in Setup (druid.yaml job_prefix)`; exit 2.
- No-hits run-time message: `no hits: nothing to cluster for <id>`; exit 0.
- Cascade-cancel label: `cancelled: search failed`.
- Local tests: `python3 -m pytest -q -p no:cacheprovider`; Edit/Write for code edits, never sed.

## Review Focus

1. `druid run` twice while the first run's arrays are still queued → the second submits nothing for those families (Task 5 test `test_run_twice_skips_queued`).
2. More than `MAX_ARRAY` families → several search arrays, each with its own cluster array of identical ids order and size (Task 5 test `test_chunks_pair_exactly`).
3. sbatch of a cluster array fails after its search array was queued → the error names the queued search job id and says the next `druid run` will cluster those families (Task 5 test `test_cluster_sbatch_fails_after_search`).
4. A family with stale HG FASTAs (cluster `output_exists`) → dropped from both arrays with a note; the rest go (Task 5 test `test_stale_family_dropped_from_both`).
5. No `squeue` on PATH without `-n` → refused like `submit` (Task 6 test `test_run_refuses_without_squeue`).

---

### Task 1: `job_prefix` in the config and the job name

**Files:**
- Modify: `druid/core.py` (`Config`, `config_from_raw`), `druid/model.py` (`SBATCH`, `write_run`), `druid/cli.py` (`submit`), `druid/tui.py` (`ResubmitScreen._build`), `druid/templates/druid.yaml`
- Test: `tests/test_core.py`, `tests/test_model.py`, `tests/test_cli.py`; fixtures in `tests/conftest.py` and any test that builds a submittable project get `job_prefix: t`

**Interfaces:**
- Produces: `core.JOB_PREFIX_RE`; `core.job_prefix_error(v) -> str` ("" = valid); `Config.job_prefix: "str | None" = None`; `model.job_name(cfg, stage) -> str`; `model.require_prefix(raw: dict, cfg) -> None` raising `ModelError(<refusal text>, 2)` unless `cfg.job_prefix` or `raw.get("prepare") == "locked"`.

- [ ] **Step 1: Failing tests**

```python
def test_job_prefix_rules():
    assert core.job_prefix_error("chromo") == "" and core.job_prefix_error("a_1") == ""
    for bad in ("", "1abc", "a-b", "a b", "x" * 21, "é"):
        assert core.job_prefix_error(bad)

def test_config_reads_job_prefix(tmp_project):           # existing project fixture
    raw = paths.read_raw(); raw["job_prefix"] = "chromo"
    assert core.config_from_raw(raw).job_prefix == "chromo"
    raw["job_prefix"] = "a-b"
    with pytest.raises(core.ConfigError, match="job_prefix"):
        core.config_from_raw(raw)
    del raw["job_prefix"]
    assert core.config_from_raw(raw).job_prefix is None

def test_sbatch_job_name_uses_prefix(...):               # write_run on a 1-family search plan
    assert "#SBATCH --job-name=chromo-search" in script_text
    # cfg.job_prefix None (adopted): "#SBATCH --job-name=phylo-search"

def test_submit_refuses_without_prefix(...):             # cli submit search --missing, no job_prefix
    assert r.exit_code == 2
    assert "ERROR: set job_prefix in Setup (druid.yaml job_prefix)" in r.output
    # same project with prepare: locked -> not refused for the prefix
```

- [ ] **Step 2: Run — expect FAIL** (`python3 -m pytest -q -p no:cacheprovider tests/test_core.py tests/test_model.py tests/test_cli.py -k "job_prefix or job_name or without_prefix"`)
- [ ] **Step 3: Implement.** Template: add `job_prefix:            # required: your SLURM job names are <job_prefix>-<stage> (Setup › Project)` after `qos:`. `config_from_raw`: empty/None → `None`; anything else must pass `job_prefix_error` or `ConfigError("job_prefix ...")`. `SBATCH`: `--job-name={job_name}`; `write_run` passes `model.job_name(cfg, p.stage)` (`f"{cfg.job_prefix or 'phylo'}-{stage}"`). Call `require_prefix` in `cli.submit` before `_preflight`, and first in `ResubmitScreen._build` (return `(None, str(e))`).
- [ ] **Step 4: Run the whole suite — expect PASS** (fix fixtures that now hit the refusal by adding `job_prefix: t`, never by weakening the refusal).
- [ ] **Step 5: Commit** `job_prefix: druid.yaml key, job names <prefix>-<stage>, submit / resubmit refuse without it (adopted exempt) (tests)`

### Task 2: recognise druid's jobs by job id, not by name

**Files:**
- Modify: `druid/model.py` (`live`, ~line 66-97)
- Test: `tests/test_model.py`

**Interfaces:**
- Produces: `model.run_stage(run_dir: Path) -> "str | None"` (stage from the run dir name via `history.RUN_RE` group 7). `live()` keeps its signature and return.

- [ ] **Step 1: Failing test** `test_live_matches_by_job_id`: runs dir with `20261025-120000_search/jobs.tsv` = `777\tids_0.txt` (ids `a.F1`, `a.F2`) and `20261025-120001_cluster/jobs.tsv` = `888\tids_0.txt` (`a.F1`); `FAKE_SQUEUE` = `777_1|chromo-search\n888_0|renamed-cluster\n999_0|phylo-search\n`; assert `live(set()) == {"search": {"a.F2"}, "cluster": {"a.F1"}}` (999 is not this project's: ignored). Plus an `nf-` line still counted as today.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement:** for a line whose master id is in `jobs_map()`, the stage is `run_stage(ids_file.parent)`; the name is no longer checked for `phylo-`. `nf-` handling unchanged.
- [ ] **Step 4: Run suite — PASS.**
- [ ] **Step 5: Commit** `live: druid's own jobs by job id from runs/*/jobs.tsv (any name), stage from the run dir (tests)`

### Task 3: Setup › Project (job_prefix field) and its blocker

**Files:**
- Modify: `druid/setup_state.py` (`blockers`), `druid/setup_tui.py` (`SECTIONS`, compose, fill, `on_input_submitted`, marks, `on_list_view_selected` target)
- Test: `tests/test_setup_state.py`, `tests/test_setup_tui.py`

**Interfaces:**
- Consumes: `core.job_prefix_error` (Task 1).
- Produces: `SetupScreen.SECTIONS = ("Project", "Source", "Species", "Analyses", "Tree", "Search", "Families", "Config")`; Input id `#job-prefix`.

- [ ] **Step 1: Failing tests**
  - `test_blockers_need_job_prefix`: no prefix → `"no job_prefix (Setup › Project)"` is the **first** blocker; valid prefix → absent; `prepare: locked` → absent.
  - `test_project_section_sets_prefix`: open Setup; section list's first item is `Project`, mark `!`; type `chromo`, enter → `_raw()["job_prefix"] == "chromo"`, mark `✓`, blocker gone; type `a-b`, enter → bottom line `ERROR: job_prefix ...`, file unchanged.
  - `test_prefix_editable_after_species_lock`: `species_locked: true` → `#job-prefix` enabled and a change is written; adopted (`prepare: locked`) → disabled.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.** Section `Project`: one `Input(placeholder="job_prefix: your SLURM job names are <job_prefix>-<stage>", id="job-prefix")` + a note line; write via `self._write({("job_prefix",): value})` after `core.job_prefix_error(value)` passes; disabled only when `_ro_all`. Fix existing tests that rely on section order or on Setup opening on Source.
- [ ] **Step 4: Run suite — PASS.**
- [ ] **Step 5: Commit** `setup: Project section with the required job_prefix (blocker; editable after the species lock) (tests)`

### Task 4: cluster on a no-hits family exits 0

**Files:**
- Modify: `druid/runner.py` (`run_one`)
- Test: `tests/test_runner.py`

- [ ] **Step 1: Failing test** `test_cluster_no_hits_exits_0`: `outdir/search/a.F1.domains.fasta` empty; `run_one(cfg, "cluster", "a.F1", work_root)` returns 0, stdout contains `no hits: nothing to cluster for a.F1`, no `work_root/a.F1`, nothing new in `outdir/clusters`. Non-empty domains file → unchanged behaviour (existing tests).
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** right after the id check: `if stage == "cluster" and hg in core.family_done(cfg, [hg])["no_hits"]:` print and return 0.
- [ ] **Step 4: Run suite — PASS.**
- [ ] **Step 5: Commit** `runner: cluster on a no-hits family prints "no hits", exits 0, publishes nothing (tests)`

### Task 5: `step1run` — plan, write and queue the linked run

**Files:**
- Create: `druid/step1run.py`
- Modify: `druid/model.py` (`sbatch_all`)
- Test: `tests/test_step1run.py` (own fake `sbatch` that prints 101, 102, … from a counter file and logs its args)

**Interfaces:**
- Consumes: `model.select/plan/write_run/sbatch_all/live_hgs/require_prefix/Plan/Written/Selection`, `core.family_ids/filter_fam/family_done/validate/group`.
- Produces:
  - `model.sbatch_all(w, submitted=None, depends: "list | None" = None)` — `depends[i]` (a job id or None) adds `--dependency=aftercorr:<id> --kill-on-invalid-dep=yes` before the script and appends `<jid>\t<depends[i]>` to `w.run_dir/depends.tsv`.
  - `@dataclass RunPlan: search: "model.Plan | None"; linked: "model.Plan | None"; only: "model.Plan | None"; notes: list; counts: dict` — counts keys `search`, `cluster_only`, `no_hits`, `done`, `queued`, `dropped`.
  - `plan_run(cfg, raw, fam: "str | None" = None, dry_run: bool = False, override: "dict | None" = None) -> RunPlan`
  - `@dataclass RunWritten: search: "model.Written | None"; linked: "model.Written | None"; only: "model.Written | None"`
  - `write(cfg, raw, rp, dry_run, max_running=50, partition=None, qos=None) -> RunWritten`
  - `submit(rw) -> "tuple[list[tuple[str, str, int]], str | None]"` — `[(stage, job id, n tasks)]` and an error.
  - `refusal(raw, cfg) -> str` — "" or the `ERROR: …` line (no prefix via `require_prefix`; `prepare: locked` → `ERROR: druid run is not available on an adopted project (prepare: locked); use druid submit`; missing `params.infasta` → `ERROR: run prepare first (no <infasta>)`; species not locked and `setup_state.blockers` non-empty → `ERROR: Setup has blockers: <joined>`).

- [ ] **Step 1: Failing tests**
  - `test_plan_partitions_families`: 5 families: F1 none, F2 hits not clustered, F3 no hits, F4 clustered, F5 queued for search (FAKE_SQUEUE + jobs.tsv) → linked search ids `[F1]`, linked cluster ids `[F1]`, only `[F2]`, counts `{"search": 1, "cluster_only": 1, "no_hits": 1, "done": 1, "queued": 1, "dropped": 0}`.
  - `test_submit_links_each_cluster_array`: after `submit`, fake sbatch log order: search script (→101), cluster script with `--dependency=aftercorr:101 --kill-on-invalid-dep=yes` (→102), then cluster-only script without `--dependency`; linked run dir `depends.tsv` = `102\t101\n`; every run dir has its `jobs.tsv`; species locked once.
  - `test_chunks_pair_exactly` (monkeypatch `model.MAX_ARRAY = 2`, 5 new families): 3 search arrays, 3 cluster arrays; `ids_k.txt` byte-identical between the two run dirs for each k; cluster k depends on search k.
  - `test_run_twice_skips_queued`: second `plan_run` with the first run's jobs in FAKE_SQUEUE → `search is None and linked is None`, counts `queued` = n.
  - `test_cluster_sbatch_fails_after_search`: fake sbatch fails on the 2nd call → error contains `101` and `the next druid run clusters them`; no 3rd call.
  - `test_stale_family_dropped_from_both`: F1 new but has an HG FASTA under `clusters/` without `_cluster.tsv` → F1 in neither array, note names F1, counts `dropped` = 1; F6 (also new) still linked.
  - `test_refusal_cases`: each of the four `refusal` texts; locked species with a moved proteome → `""`.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement.** Selection: `need = fams - st["search"] - queued_search - queued_cluster`; `only = st["hits"] - st["cluster"] - queued_cluster`; validate search on `need` and cluster on `need` ignoring `input_missing`; any family with an error in either → drop from both, note `dropped (<n>): <ids>`; cluster-only through `model.select` + `model.plan` as `submit` does. Linked cluster pieces mirror the search plan's `(res, ids)` pieces: same `ids` lists, `res` from `core.group(cfg, "cluster", ids, override)`, which must give exactly one group (else `ModelError(..., 1)`). Queue order: search array k, then its cluster array k (one-array `model.Written` slices), then the cluster-only arrays; stop at the first failure.
- [ ] **Step 4: Run suite — PASS.**
- [ ] **Step 5: Commit** `step1run: druid run's plan — search + per-task-linked cluster (aftercorr), cluster-only, skips done / no-hits / queued, drops failing families from both (tests)`

### Task 6: `druid run` (CLI)

**Files:**
- Modify: `druid/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `step1run.refusal/plan_run/write/submit` (Task 5), `cli._preflight`, `cli._print_dry_run`.

- [ ] **Step 1: Failing tests**
  - `test_run_dry_run_prints_plan`: `druid run -n` → exit 0, output has the counts line (`search+cluster 1 · cluster only 1 · no hits 1 · done 1 · queued 1`) and one dry-run panel per array; nothing in `runs/`; no sbatch call.
  - `test_run_submits_and_reports`: lines `submitted 101: search 1 families …`, `submitted 102: cluster 1 families (after 101) …`.
  - `test_run_refuses_without_squeue` (no `squeue` on PATH, no `-n`) → exit 1, like `submit`.
  - `test_run_refusals`: each `refusal` text → exit 2, no sbatch call; nothing to do → `nothing to submit`, exit 0.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** `@app.command() def run(fam, dry_run, max_running, partition, qos, mem, time, cpus)` with the same option names, defaults and help as `submit`; `_preflight("search", cfg)` when there is a search plan, `_preflight("cluster", cfg)` when there is a cluster plan.
- [ ] **Step 4: Run suite — PASS.**
- [ ] **Step 5: Commit** `cli: druid run — step 1 in one command (dry run, refusals, linked arrays reported) (tests)`

### Task 7: history shows `cancelled: search failed`

**Files:**
- Modify: `druid/common.py` (`FAILED_STATES`), `druid/history.py` (`STATE_REASON`, `_phylocli_attempts`)
- Test: `tests/test_history.py`

- [ ] **Step 1: Failing test** `test_cascade_cancel_is_search_failed`: search run dir (job 101, ids F1 F2), linked cluster run dir (job 102, same ids, `depends.tsv` `102\t101`); FAKE_SACCT `101_0|COMPLETED 101_1|FAILED 102_0|COMPLETED 102_1|CANCELLED by 0`. `family_attempts` → cluster F2 status `SEARCH_FAILED`, `history.reason("SEARCH_FAILED", "0") == "cancelled: search failed"`, colour red; cluster F1 `COMPLETED`; a CANCELLED cluster task whose search task COMPLETED stays `CANCELLED`; the array cache stores the raw sacct state (re-reading gives the same result).
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement:** add `"SEARCH_FAILED"` to `FAILED_STATES` and `STATE_REASON["SEARCH_FAILED"] = "cancelled: search failed"`; in `_phylocli_attempts`, for a cluster run dir with `depends.tsv`, a task CANCELLED whose same-index task of the recorded search job is in `FAILED_STATES` gets status `SEARCH_FAILED` (applied after the cache read/write).
- [ ] **Step 4: Run suite — PASS.**
- [ ] **Step 5: Commit** `history: a cluster task cancelled by its failed search shows "cancelled: search failed" (tests)`

### Task 8: TUI — `S` runs step 1 (Jobs tab and Setup)

**Files:**
- Modify: `druid/tui.py` (new `RunScreen`, binding on the Jobs screen), `druid/setup_tui.py` (binding, prepare hint)
- Test: `tests/test_tui.py`, `tests/test_setup_tui.py`

**Interfaces:**
- Consumes: `step1run.*` (Task 5).
- Produces: `RunScreen(ModalScreen)` with `Binding("enter", "dry_run")`, `Binding("y", "submit", priority=True)`, `Binding("escape", "cancel")`, body `#out`; `Binding("S", "run_step1", "run step 1")` on the Jobs screen and on `SetupScreen`.

- [ ] **Step 1: Failing tests**
  - `test_S_opens_run_screen_and_submits`: Jobs tab, `S` → `RunScreen`; `enter` → `#out` shows the counts line and the arrays, no sbatch call; `y` → sbatch called (search then linked cluster), `#out` lists the job ids; `esc` closes; a second `y` after submitting does nothing (`already submitted`).
  - `test_S_shows_refusal`: no `job_prefix` → `#out` shows the refusal, `y` submits nothing.
  - `test_prepare_hint_names_S`: after a successful `P` in Setup, bottom line contains `S: run step 1 (search → cluster)`.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** `RunScreen` on the `ResubmitScreen` pattern (worker thread for squeue/sacct/sbatch, `_post` to the UI thread, `_busy`, `_already_submitted`); no Inputs. On close, the Jobs screen reloads.
- [ ] **Step 4: Run suite — PASS.**
- [ ] **Step 5: Commit** `tui: S runs step 1 from Jobs and Setup (dry run, y submits); prepare names it as the next step (tests)`
