# phylocli TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `phylo tui` — a Textual full-screen view of step2 progress (stages, HGs, arrays, HG detail) that selects failed HGs and resubmits them with bumped, editable resources after a dry run and a confirmation.

**Architecture:** Extract the data logic of `phylocli/phylo.py` into a new print-free `phylocli/model.py`; the CLI commands become printers over it (output byte-identical, pinned by the existing tests) and a new `phylocli/tui.py` (Textual, imported only by `phylo tui`) consumes the same functions.

**Tech Stack:** Python ≥ 3.9, typer + rich (existing), Textual (optional), pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-phylocli-tui-design.md`

**Repo / branch:** worktree `~/Documents/projects/phylogenies/phylocli-wt`, branch `phylocli` (HEAD `8fa45ec`). All paths below are relative to it. Session `phylogenies-8a` owns the branch: implementers do NOT commit — each task ends by listing its files; the controller sends the list to `phylogenies-8a`, which commits.

## Global Constraints

- CLI output text and exit codes of `status`, `missing`, `submit`, `jobs` (and hidden `queue`, `_run`) stay byte-identical; the existing 118 tests must pass **unmodified**.
- Python 3.9-safe: every module starts with `from __future__ import annotations`; no `match`, no `X | Y` outside annotations, no `glob(root_dir=)`.
- Textual is imported only inside `phylocli/tui.py`; `phylo.py` imports it lazily in the `tui` command. Every other command must run without Textual installed.
- `phylo.py` must keep the module-level names tests use: `app`, `run_one`, `_preflight`, `_chunks`.
- Test commands (both must pass at the end of every task):
  - `python3 -m pytest phylocli/tests -q -p no:cacheprovider`  (mambaforge)
  - `/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-phylogenies/3dad6ea4-c859-4fe6-b319-93a358944ac8/scratchpad/py39/bin/python -m pytest phylocli/tests -q -p no:cacheprovider`  (3.9 venv; below: `$PY39`)
- Edit with Edit/Write tools, never `sed`.

## Review Focus

1. **`squeue`/`sacct` hanging** (cluster controller slow) — the CLI must fail with a message, not hang forever; the TUI must not freeze. → Task 1 adds `timeout=60` + `ModelError`; test with a sleeping fake `squeue`.
2. **HGs change state between dry run and `y`** (finished, or queued by another submission) — the confirm step must recompute the selection and skip them, not double-submit. → Task 7 test: queue one HG via `FAKE_SQUEUE` after the dry run, confirm, assert it is skipped.
3. **Unparseable resource text in the dialog** (`abc`, `0`, empty) — inline error, nothing submitted. → Task 7 test.
4. **`r` with nothing selected** — notification "nothing selected", no dialog. → Task 7 test.
5. **Stage not applicable** (`gxsup` with `gxsup: false`) — stages table shows `n/a`, resubmit refuses with the CLI's `not_applicable` message. → Task 2 test (`stage_rows`) and Task 5 test (`plan`).

---

## File Structure

| file | responsibility |
|---|---|
| `phylocli/model.py` (new) | data only: SLURM queries (`squeue`, `sacct`), live HGs, stage counts, HG rows, array rows, `bump`, submission select / plan / write / sbatch, preflight. Raises `ModelError(msg, code)`; never prints. |
| `phylocli/phylo.py` (modify) | typer commands; formats `model.*` results exactly as today; maps `ModelError` → `_fail(msg, code)`; adds `tui` command. |
| `phylocli/core.py` (modify) | `group()` gains `per_hg`. |
| `phylocli/tui.py` (new) | Textual app `PhyloApp`, `ResubmitScreen`, `LogScreen`. |
| `phylocli/tests/test_model.py` (new) | model tests (reuse the `cli` fixture from `test_cli.py`). |
| `phylocli/tests/test_tui.py` (new) | Textual pilot tests, skipped without Textual. |
| `phylocli/README.md` (modify) | `phylo tui` section. |
| `docs/superpowers/specs/2026-10-08-phylocli-tui-design.md` (modify) | `l` = log pop-up (see Task 8). |

Fixture facts (from `phylocli/tests/conftest.py`, `results_tree`): expected HGs `tfs.A.HG1`, `tfs.A.HG11` (3 seqs each), `tfs.C_x.HG1` (600 seqs); `tfs.B.HG2` (1 seq) is not expected. `tfs.A.HG1` has align + tree + possvm_prev done; `tfs.A.HG11` has possvm done. Fake `sbatch` echoes `12345` and logs args to `bin/calls.txt`; fake `squeue` prints `$FAKE_SQUEUE`; fake `sacct` prints `$FAKE_SACCT` (`%b`, so `\\n` in the env value is a newline).

---

### Task 1: `model.py` — SLURM queries and live HGs moved out of `phylo.py`

**Files:**
- Create: `phylocli/model.py`
- Modify: `phylocli/phylo.py:160-231` (`_squeue`, `_jobs_map`, `_nf_job`, `_live`, `live_hgs`) and `:577-620` (`_category`, `_task_states`, `_submissions`)
- Test: `phylocli/tests/test_model.py`

**Interfaces:**
- Produces:
  - `class ModelError(Exception)` with `.code: int` (`ModelError(msg, code=1)`)
  - `SLURM_TIMEOUT = 60`
  - `squeue(fmt: str, array_tasks: bool = False) -> list[str] | None`
  - `live(expected: set) -> dict[str, set[str]] | None`
  - `live_hgs(stage: str, allow_no_squeue: bool = False, expected: set | None = None) -> set[str]`
  - `category(state: str) -> str` (`done|failed|running|pending`)
  - `task_states(job_ids: list[str]) -> dict[str, dict[int, str]] | None`
  - `submissions(stage: str | None, last: int) -> list[tuple[Path, str, str, Path]]`

- [ ] **Step 1: Write the failing tests** — `phylocli/tests/test_model.py`:

```python
"""phylocli/model.py: the print-free data layer shared by the CLI and the TUI."""
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest phylocli/tests/test_model.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'phylocli.model'`

- [ ] **Step 3: Create `phylocli/model.py`** — the bodies are moved verbatim from `phylo.py`, with `_fail(...)` replaced by `raise ModelError(...)` and a timeout added:

```python
"""Data layer of phylocli: everything the CLI (phylo.py) and the TUI (tui.py) show or submit,
computed without printing. Errors are raised as ModelError(msg, code); phylo.py turns them
into the same message + exit code it always printed."""
from __future__ import annotations

import collections
import shutil
import subprocess
from pathlib import Path

from phylocli import core, history
from phylocli.common import FAILED_STATES, RUNNING_STATES, expand_indices, ids_path, runs_dir

SLURM_TIMEOUT = 60  # seconds; a stuck slurmctld must not hang the CLI or freeze the TUI


class ModelError(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def _slurm(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=SLURM_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ModelError(f"{cmd[0]} timed out after {SLURM_TIMEOUT} s", 1) from None


def squeue(fmt: str, array_tasks: bool = False) -> list[str] | None:
    if shutil.which("squeue") is None:
        return None
    r = _slurm(["squeue", "--me", "-h"] + (["-r"] if array_tasks else []) + ["-o", fmt])
    if r.returncode != 0:
        raise ModelError(f"squeue failed: {r.stderr.strip()}", 1)
    return r.stdout.splitlines()


def jobs_map() -> dict[str, Path]:
    out = {}
    for f in sorted(runs_dir().glob("*/jobs.tsv")):
        for line in f.read_text().splitlines():
            if "\t" in line:
                jid, ids = line.split("\t", 1)
                out[jid.strip()] = ids_path(f.parent, ids.strip())
    return out


def nf_job(name: str) -> tuple[str, str] | None:
    """(process, tag) from a Nextflow SLURM job name like nf-PHY_(tfs.T-box.HG1). Process
    names contain underscores (PVM_PREV, GR_watcher), so match the known names, longest first."""
    body = name[len("nf-"):]
    for proc in sorted(history.PROC_STAGE, key=len, reverse=True):
        if body.startswith(proc + "_"):
            return proc, body[len(proc) + 1:].strip("()")
    return None


def live(expected: set) -> dict[str, set[str]] | None:
    """stage -> ids pending or running in SLURM right now: tasks of phylocli arrays (`squeue -r`
    lists each array task; task i = line i+1 of its ids file) and Nextflow jobs (named
    nf-<PROCESS>_(<tag>)). None when squeue is not on PATH."""
    lines = squeue("%i|%.300j", array_tasks=True)
    if lines is None:
        return None
    jobs = jobs_map()
    cache: dict[Path, list[str]] = {}
    out: dict[str, set[str]] = collections.defaultdict(set)
    for line in lines:
        if "|" not in line:
            continue
        jid, name = (x.strip() for x in line.split("|", 1))
        if name.startswith("phylo-"):
            master, _, idx = jid.partition("_")
            f = jobs.get(master)
            if f is None or not f.is_file():
                continue
            ids = cache.setdefault(f, core.read_ids(f))
            idxs = ([int(idx)] if idx.isdigit()
                    else expand_indices(idx.strip("[]")) if idx else range(len(ids)))
            out[name[len("phylo-"):]].update(ids[i] for i in idxs if i < len(ids))
        elif name.startswith("nf-"):
            nf = nf_job(name)
            if nf:
                hg = history._resolve_tag(nf[1], expected)
                if hg:
                    out[history.PROC_STAGE[nf[0]]].add(hg)
    return dict(out)


def live_hgs(stage: str, allow_no_squeue: bool = False, expected: set | None = None) -> set[str]:
    lv = live(expected if expected is not None else set())
    if lv is None:
        if allow_no_squeue:
            return set()
        raise ModelError("squeue not on PATH: cannot check for already queued HGs "
                         "(only --dry-run may skip this)", 1)
    return lv.get(stage, set())


def category(state: str) -> str:
    if state == "COMPLETED":
        return "done"
    if state in FAILED_STATES:
        return "failed"
    if state in RUNNING_STATES:
        return "running"
    return "pending"


def task_states(job_ids: list[str]) -> dict[str, dict[int, str]] | None:
    """{array job id: {task index: SLURM state}} from sacct; None if sacct is unavailable."""
    if not job_ids or shutil.which("sacct") is None:
        return None if job_ids else {}
    r = _slurm(["sacct", "-n", "-P", "-X", "-j", ",".join(job_ids), "-o", "JobID,State"])
    if r.returncode != 0:
        raise ModelError(f"sacct failed: {r.stderr.strip()}", 1)
    out: dict[str, dict[int, str]] = {}
    for line in r.stdout.splitlines():
        if "|" not in line:
            continue
        jid, state = line.split("|", 1)
        state = state.split()[0] if state.split() else "UNKNOWN"   # "CANCELLED by 1000"
        master, _, idx = jid.partition("_")
        idxs = expand_indices(idx.strip("[]")) if idx else []
        for i in idxs:
            out.setdefault(master, {})[i] = state
    return out


def submissions(stage: str | None, last: int) -> list[tuple[Path, str, str, Path]]:
    """(run dir, stage, job id, ids file) for the newest `last` real submissions."""
    rows = []
    for f in sorted(runs_dir().glob("*/jobs.tsv"), key=lambda p: p.parent.name, reverse=True):
        st = f.parent.name.split("_", 2)[-1]
        if stage and st != stage:
            continue
        for line in f.read_text().splitlines():
            if "\t" in line:
                jid, ids = line.split("\t", 1)
                rows.append((f.parent, st, jid.strip(), ids_path(f.parent, ids.strip())))
    runs = list(dict.fromkeys(r[0] for r in rows))[:last]
    return [r for r in rows if r[0] in runs]
```

- [ ] **Step 4: Point `phylo.py` at the model** — delete the moved definitions (`_squeue`, `_jobs_map`, `_nf_job`, `_live`, `live_hgs`, `_category`, `_task_states`, `_submissions`) and add, right after the `from phylocli.runner import run_one` line:

```python
from phylocli import model  # noqa: E402


def _guard(fn):
    """Call a model function; a ModelError becomes the CLI's usual message + exit code."""
    def wrapped(*a, **k):
        try:
            return fn(*a, **k)
        except model.ModelError as e:
            _fail(str(e), e.code)
    return wrapped
```

and after `_fail` is defined (below it), the aliases every existing call site uses:

```python
_live = _guard(model.live)
live_hgs = _guard(model.live_hgs)
_task_states = _guard(model.task_states)
_submissions = model.submissions
_category = model.category
```

(`_guard` references `_fail` at call time, so defining `_guard` above `_fail` is fine; the aliases must come after `_fail`.)

- [ ] **Step 5: Run the whole suite on both Pythons**

Run: `python3 -m pytest phylocli/tests -q -p no:cacheprovider` then `$PY39 -m pytest phylocli/tests -q -p no:cacheprovider`
Expected: `123 passed` on both (118 existing + 5 new).

- [ ] **Step 6: Hand off** — files: `phylocli/model.py`, `phylocli/phylo.py`, `phylocli/tests/test_model.py`.

---

### Task 2: `stage_rows` — the numbers behind `status` / `missing`

**Files:**
- Modify: `phylocli/model.py` (append), `phylocli/phylo.py:134-157` (`_summary`)
- Test: `phylocli/tests/test_model.py` (append)

**Interfaces:**
- Consumes: `model.live` (Task 1)
- Produces:
  - `@dataclass StageRow: stage: str; applicable: bool; done: int; running: int; ready: int; blocked: int; total: int`
  - `stage_rows(cfg: core.Config, exp: set[str]) -> tuple[list[StageRow], bool, dict[str, set[str]]]` — (rows, `live_known`, `done` sets per stage incl. `"done"`)

- [ ] **Step 1: Failing tests** (append to `test_model.py`):

```python
import dataclasses

from phylocli import core


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
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_model.py -q -p no:cacheprovider` — Expected: FAIL, `AttributeError: module 'phylocli.model' has no attribute 'stage_rows'`.

- [ ] **Step 3: Implement** (append to `model.py`; add `from dataclasses import dataclass` to the imports):

```python
@dataclass
class StageRow:
    stage: str
    applicable: bool
    done: int = 0
    running: int = 0
    ready: int = 0
    blocked: int = 0
    total: int = 0


def stage_rows(cfg: core.Config, exp: set[str]):
    """(rows, live_known, done-by-stage) — exactly the counts `phylo status` draws."""
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)
    lv = live(core.expected(cfg))
    known = lv is not None
    lv = lv or {}
    rows = []
    for st in core.STAGES:
        if not core.applicable(cfg, st):
            rows.append(StageRow(st, False))
            continue
        todo = exp - done[st]
        running = todo & lv.get(st, set())
        n_ready = len(core.ready_set(cfg, st, todo - running))
        rows.append(StageRow(st, True, len(done[st]), len(running), n_ready,
                             len(todo) - len(running) - n_ready, len(exp)))
    return rows, known, done
```

Then replace the body of `_summary` in `phylo.py` (keep its signature and return value):

```python
def _summary(cfg: core.Config, ids: Path | None, mode: str = "status",
             fam: str | None = None) -> tuple[set[str], dict]:
    exp = _selected(cfg, ids, fam)
    rows, known, done = _guard(model.stage_rows)(cfg, exp)
    if not known:
        typer.echo("squeue not on PATH: running jobs not detected")
    legend = [typer.style(f"{ch} {name}", fg=fg) for (ch, fg), name
              in zip(BAR_STYLES[mode], BAR_NAMES) if ch.strip()]
    typer.echo(f"{'stage':<12} {'done':>6} {'running':>7} {'ready':>6} {'blocked':>8} {'total':>6}  "
               + " ".join(legend))
    for r in rows:
        if not r.applicable:
            typer.echo(f"{r.stage:<12} {'n/a':>6}")
            continue
        typer.echo(f"{r.stage:<12} {r.done:>6} {r.running:>7} {r.ready:>6} {r.blocked:>8} {r.total:>6}  "
                   + _bar(r.done, r.running, r.ready, r.blocked, mode))
    return exp, done
```

- [ ] **Step 4: Run both suites** — Expected: `127 passed` on both.

- [ ] **Step 5: Hand off** — files: `phylocli/model.py`, `phylocli/phylo.py`, `phylocli/tests/test_model.py`.

---

### Task 3: `hg_rows`, `hg_detail`, `array_rows`

**Files:**
- Modify: `phylocli/model.py` (append), `phylocli/phylo.py` (`jobs` table loop, `:656-669`)
- Test: `phylocli/tests/test_model.py` (append)

**Interfaces:**
- Consumes: `live`, `task_states`, `submissions`, `category` (Task 1); `history.attempts`, `history.latest_by_stage`, `history.reason`
- Produces:
  - `@dataclass HGRow: hg: str; state: str; last: history.Attempt | None` — `state ∈ {"done","running","failed","ready","blocked"}`
  - `hg_rows(cfg, stage: str, exp: set[str] | None = None, atts: list | None = None) -> list[HGRow]` (sorted by hg)
  - `@dataclass HGDetail: hg: str; nseq: int; states: dict[str, str]; latest: dict[str, history.Attempt]`
  - `hg_detail(cfg, hg: str, atts: list | None = None) -> HGDetail`
  - `@dataclass ArrayRow: run: Path; stage: str; job: str; n: int; counts: collections.Counter`
  - `array_rows(stage: str | None = None, last: int = 10) -> tuple[list[ArrayRow], bool]` (rows, sacct known)

- [ ] **Step 1: Failing tests** (append):

```python
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
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_model.py -q -p no:cacheprovider` — Expected: FAIL, no attribute `hg_rows`.

- [ ] **Step 3: Implement** (append to `model.py`):

```python
@dataclass
class HGRow:
    hg: str
    state: str
    last: "history.Attempt | None" = None


def _latest_for(atts: list, stage: str) -> dict[str, "history.Attempt"]:
    out: dict = {}
    for a in sorted(atts, key=lambda a: (a.submitted, a.attempt, a.run)):
        if a.stage == stage:
            out[a.hg] = a
    return out


def hg_rows(cfg: core.Config, stage: str, exp: set[str] | None = None,
            atts: list | None = None) -> list[HGRow]:
    """One row per expected HG for `stage`. failed = inputs present, not done, not queued,
    and the latest attempt at this stage ended in a FAILED_STATES state."""
    exp = core.expected(cfg) if exp is None else exp
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)[stage]
    busy = (live(core.expected(cfg)) or {}).get(stage, set())
    todo = exp - done
    ready = core.ready_set(cfg, stage, todo - busy)
    latest = _latest_for(history.attempts(cfg) if atts is None else atts, stage)
    rows = []
    for hg in sorted(exp):
        a = latest.get(hg)
        if hg in done:
            state = "done"
        elif hg in busy:
            state = "running"
        elif hg in ready:
            state = "failed" if a is not None and a.status in FAILED_STATES else "ready"
        else:
            state = "blocked"
        rows.append(HGRow(hg, state, a))
    return rows


@dataclass
class HGDetail:
    hg: str
    nseq: int
    states: dict
    latest: dict


def hg_detail(cfg: core.Config, hg: str, atts: list | None = None) -> HGDetail:
    exp = core.expected(cfg)
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)
    lv = live(exp) or {}
    states = {}
    for st in core.STAGES:
        if not core.applicable(cfg, st):
            states[st] = "n/a"
        elif hg in done[st]:
            states[st] = "done"
        elif hg in lv.get(st, set()):
            states[st] = "running"
        elif hg in core.ready_set(cfg, st, [hg]):
            states[st] = "ready"
        else:
            states[st] = "blocked"
    atts = history.attempts(cfg, hg) if atts is None else [a for a in atts if a.hg == hg]
    return HGDetail(hg, core.nseq(cfg, hg), states, history.latest_by_stage(atts))


@dataclass
class ArrayRow:
    run: Path
    stage: str
    job: str
    n: int
    counts: collections.Counter


def array_rows(stage: str | None = None, last: int = 10):
    """(rows, sacct_known): the table `phylo jobs` prints."""
    subs = submissions(stage, last)
    states = task_states(sorted({jid for _r, _s, jid, _f in subs}))
    known = states is not None
    states = states or {}
    rows = []
    for run, st, jid, ids_file in subs:
        n = len(core.read_ids(ids_file)) if ids_file.is_file() else 0
        c = collections.Counter(category(s) for s in states.get(jid, {}).values())
        c["pending"] += max(n - sum(c.values()), 0)        # tasks sacct has not reported yet
        rows.append(ArrayRow(run, st, jid, n, c))
    return rows, known
```

Then in `phylo.py` `jobs()`, replace the table-filling loop (the `for run, st, jid, ids_file in subs:` block that builds `n`, `c`, `cells` and calls `t.add_row`) with a loop over `model.array_rows` — `subs`, `states`, the `--failed` branch and the header stay as they are:

```python
    rows, _known = _guard(model.array_rows)(stage, last)
    for r in rows:
        cells = ([f"[{colour}]{r.counts[col]}[/]" if r.counts[col] else "[dim]0[/]"
                  for col, colour in JOB_COLS] if known else ["?"] * len(JOB_COLS))
        t.add_row(r.run.name.split("_")[0], r.stage, r.job, str(r.n), *cells,
                  _job_bar(r.counts) if known else "")
```

- [ ] **Step 4: Run both suites** — Expected: `131 passed` on both.

- [ ] **Step 5: Hand off** — files: `phylocli/model.py`, `phylocli/phylo.py`, `phylocli/tests/test_model.py`.

---

### Task 4: `bump()` and per-HG resources in `core.group`

**Files:**
- Modify: `phylocli/model.py` (append), `phylocli/core.py:313-325` (`group`)
- Test: `phylocli/tests/test_model.py` (append)

**Interfaces:**
- Consumes: `core.Res`, `core.parse_mem_mb`, `history.Attempt`
- Produces:
  - `parse_duration_min(s: str) -> int | None` — `"30m"`, `"4h"`, `"1h30m"`, `"1d"`, `"2d 3h"`; None if unparseable
  - `bump(att: history.Attempt | None, res: core.Res) -> core.Res`
  - `bump_reason(att) -> str` — `"OOM"`, `"time"`, or `history.reason(...)` / `""`
  - `core.group(cfg, stage, hgs, override=None, per_hg: dict[str, dict] | None = None)`

- [ ] **Step 1: Failing tests** (append):

```python
from phylocli import history


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
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_model.py -q -p no:cacheprovider` — Expected: FAIL, no attribute `parse_duration_min`.

- [ ] **Step 3: Implement.** Append to `model.py` (add `import dataclasses` and `import re`):

```python
def parse_duration_min(s: str) -> int | None:
    """Minutes from fmt_time / Nextflow trace strings: 30m, 4h, 1h30m, 1d, 2d 3h."""
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*(d|h|m)(?![a-z])", str(s), re.I)
    if not parts:
        return None
    mult = {"d": 1440, "h": 60, "m": 1}
    return int(round(sum(float(v) * mult[u.lower()] for v, u in parts)))


def _is_oom(att) -> bool:
    return att.status == "OUT_OF_MEMORY" or att.exit == "137"


def _is_timeout(att) -> bool:
    return att.status == "TIMEOUT" or att.exit == "140"


def bump_reason(att) -> str:
    if att is None:
        return ""
    if _is_oom(att):
        return "OOM"
    if _is_timeout(att):
        return "time"
    return history.reason(att.status, att.exit)


def bump(att, res: core.Res) -> core.Res:
    """Resources for a resubmit: start from max(last request, current default); OOM doubles
    memory, a time limit doubles time, anything else resubmits unchanged."""
    if att is None:
        return res
    try:
        mem = core.parse_mem_mb(att.mem)
    except ValueError:
        mem = res.mem_mb
    t = parse_duration_min(att.time) or res.time_min
    base = dataclasses.replace(res, mem_mb=max(mem, res.mem_mb), time_min=max(t, res.time_min))
    if _is_oom(att):
        return dataclasses.replace(base, mem_mb=base.mem_mb * 2)
    if _is_timeout(att):
        return dataclasses.replace(base, time_min=base.time_min * 2)
    return base
```

Replace `core.group` with:

```python
def group(cfg: Config, stage: str, hgs: list[str],
          override: dict | None = None, per_hg: dict | None = None) -> dict[Res, list[str]]:
    """Group HGs by resources. `override` (keys cpus / mem_mb / time_min) replaces the
    per-HG value from resources.tsv or the step2 default for every HG; `per_hg`
    ({hg: {mem_mb: .., time_min: .., cpus: ..}}) then applies to single HGs."""
    table = load_resources_tsv(Path(cfg.params["resources_tsv"]))
    over = {k: v for k, v in (override or {}).items() if v is not None}
    out: dict[Res, list[str]] = {}
    for hg in sorted(hgs):
        res = resources(cfg, stage, hg, table)
        if over:
            res = dataclasses.replace(res, **over)
        mine = {k: v for k, v in (per_hg or {}).get(hg, {}).items() if v is not None}
        if mine:
            res = dataclasses.replace(res, **mine)
        out.setdefault(res, []).append(hg)
    return out
```

- [ ] **Step 4: Run both suites** — Expected: `136 passed` on both.

- [ ] **Step 5: Hand off** — files: `phylocli/model.py`, `phylocli/core.py`, `phylocli/tests/test_model.py`.

---

### Task 5: submission pipeline in the model; `submit` becomes a printer

**Files:**
- Modify: `phylocli/model.py` (append), `phylocli/phylo.py:32-57` (`MAX_ARRAY`, `SBATCH` move), `:353-375` (`_preflight`), `:409-553` (`_chunks`, `_new_run_dir`, `submit`)
- Test: `phylocli/tests/test_model.py` (append)

**Interfaces:**
- Consumes: `live_hgs` (Task 1), `core.group(per_hg=)` (Task 4)
- Produces:
  - `MAX_ARRAY`, `SBATCH`, `TOOLS` (moved verbatim), `chunks(ids, n=MAX_ARRAY)`, `new_run_dir(stage, dry_run=False) -> Path`
  - `preflight(stage: str) -> str | None` — the full error message (without exiting), None when OK
  - `@dataclass Selection: selected: list[str]; notes: list[str]; queued: set[str]`
  - `select(cfg, stage, hgs: list[str], all_: bool = False, dry_run: bool = False) -> Selection` — raises `ModelError(<"unknown (n): ...\nnothing submitted">, 2)` for unknown ids
  - `@dataclass Plan: stage: str; groups: list[tuple[core.Res, list[str]]]; notes: list[str]; errors: dict[str, list[str]]`
  - `plan(cfg, stage, sel: Selection, override=None, per_hg=None, over_flags: list[str] = ()) -> Plan`
  - `@dataclass Written: run_dir: Path; arrays: list[tuple[core.Res, list[str], Path, Path]]` (res, ids, ids_file, script)
  - `write_run(cfg, raw: dict, p: Plan, dry_run: bool, max_running: int = 50, partition=None, qos=None) -> Written`
  - `sbatch_all(w: Written) -> tuple[list[str], str | None]` — (submitted job ids, failure message or None); appends `jobs.tsv` per success

- [ ] **Step 1: Failing tests** (append):

```python
import yaml


def _raw():
    return yaml.safe_load(open(os.environ["PHYLOCLI_CONFIG"]).read())


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
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_model.py -q -p no:cacheprovider` — Expected: FAIL, no attribute `select`.

- [ ] **Step 3: Implement in `model.py`.** Move `TOOLS`, `MAX_ARRAY`, `SBATCH` verbatim from `phylo.py` (add `import os, tempfile`, `from datetime import datetime`, `from phylocli.common import ROOT`). Then append:

```python
def chunks(ids: list[str], n: int = MAX_ARRAY) -> list[list[str]]:
    return [ids[i:i + n] for i in range(0, len(ids), n)]


def new_run_dir(stage: str, dry_run: bool = False) -> Path:
    # A dry run writes its scripts under the system temp dir, so runs/ only holds real
    # submissions (queue and the already-queued check read runs/*/jobs.tsv).
    root = Path(tempfile.gettempdir()) / "phylocli-dryrun" if dry_run else runs_dir()
    base = root / f"{datetime.now():%Y%m%d-%H%M%S}_{stage}"
    d, k = base, 1
    while True:
        try:
            d.mkdir(parents=True)
            break
        except FileExistsError:
            k += 1
            d = base.with_name(f"{base.name}-{k}")
    (d / "logs").mkdir()
    return d


def preflight(stage: str) -> str | None:
    lost = [t for t in TOOLS[stage] if shutil.which(t) is None]
    hint = ("       run 'conda activate phylo' and 'module load OpenMPI' before submitting;\n"
            "       see workflow/environment.yaml.")
    py_err = None
    if stage != "gxsup":  # same `python` + PYTHONNOUSERSITE=1 as the stage scripts
        py = shutil.which("python")
        if py is None:
            py_err = "python: not on PATH"
        else:
            r = subprocess.run([py, "-c", "import ete3, Bio, yaml"], capture_output=True, text=True,
                               env={**os.environ, "PYTHONNOUSERSITE": "1"})
            if r.returncode != 0:
                py_err = (f"{py} (PYTHONNOUSERSITE=1) cannot import ete3, Bio, yaml:\n"
                          f"       {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'exit ' + str(r.returncode)}")
    if not (lost or py_err):
        return None
    msg = "ERROR:"
    if lost:
        msg += f" not on PATH: {' '.join(lost)}"
    if py_err:
        msg += f"\n       {py_err}"
    return msg + "\n" + hint


SHOW = 20


def show(ids: list[str]) -> str:
    s = " ".join(ids[:SHOW])
    return s + (f" ... and {len(ids) - SHOW} more" if len(ids) > SHOW else "")


@dataclass
class Selection:
    selected: list
    notes: list
    queued: set


def select(cfg: core.Config, stage: str, hgs: list[str], all_: bool = False,
           dry_run: bool = False) -> Selection:
    """The submit command's selection rules: unknown ids are an error; by default HGs
    without inputs or already queued are skipped with a note."""
    exp = core.expected(cfg)
    unknown = sorted(set(hgs) - exp)
    if unknown:
        raise ModelError(f"unknown ({len(unknown)}): {show(unknown)}\nnothing submitted", 2)
    queued = live_hgs(stage, allow_no_squeue=dry_run, expected=exp)
    notes: list[str] = []
    selected = list(hgs)
    if not all_:
        unready = [hg for hg in selected if not core.inputs_ready(cfg, stage, hg)]
        busy = [hg for hg in selected if hg in queued and hg not in unready]
        if unready:
            notes.append(f"skipped {len(unready)} HGs without inputs")
        if busy:
            notes.append(f"skipped {len(busy)} HGs already queued")
        drop = set(unready) | set(busy)
        selected = [hg for hg in selected if hg not in drop]
    return Selection(selected, notes, queued)


@dataclass
class Plan:
    stage: str
    groups: list
    notes: list
    errors: dict


def plan(cfg: core.Config, stage: str, sel: Selection, override: dict | None = None,
         per_hg: dict | None = None, over_flags=()) -> Plan:
    errs = core.validate(cfg, stage, sel.selected, sel.queued)
    bad = {k: v for k, v in errs.items() if v}
    notes = list(sel.notes)
    if bad:
        return Plan(stage, [], notes, bad)
    n_rows = core.resources_rows(cfg, sel.selected)
    over_flags = list(over_flags)
    notes.append(f"resources.tsv: row found for {n_rows} of {len(sel.selected)} HGs"
                 + (" (others: step2 defaults)" if n_rows < len(sel.selected) else "")
                 + (f"; overridden by {' '.join(over_flags)}" if over_flags else ""))
    groups = core.group(cfg, stage, sel.selected, override, per_hg)
    pieces = [(res, c) for res, g in groups.items() for c in chunks(g)]
    return Plan(stage, pieces, notes, {})


@dataclass
class Written:
    run_dir: Path
    arrays: list


def write_run(cfg: core.Config, raw: dict, p: Plan, dry_run: bool, max_running: int = 50,
              partition: str | None = None, qos: str | None = None) -> Written:
    import yaml
    run_dir = new_run_dir(p.stage, dry_run)
    (run_dir / "config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    arrays = []
    for k, (res, ids_) in enumerate(p.groups):
        ids_file = run_dir / f"ids_{k}.txt"
        ids_file.write_text("\n".join(ids_) + "\n")
        script = run_dir / f"array_{k}.sbatch"
        script.write_text(SBATCH.format(
            stage=p.stage, partition=partition or cfg.partition, qos=qos or res.qos,
            cpus=res.cpus, mem_mb=res.mem_mb, time_min=res.time_min,
            n_minus_1=len(ids_) - 1, max_running=max_running, run_dir=run_dir,
            signal_line=f"#SBATCH --signal={res.signal}" if res.signal else "",
            ids_file=ids_file, root=ROOT))
        arrays.append((res, ids_, ids_file, script))
    return Written(run_dir, arrays)


def sbatch_all(w: Written) -> tuple[list[str], str | None]:
    submitted: list[str] = []
    for i, (res, ids_, ids_file, script) in enumerate(w.arrays):
        r = subprocess.run(["sbatch", "--parsable", str(script)], capture_output=True, text=True)
        jid = r.stdout.strip().split(";")[0]
        if r.returncode != 0 or not jid:
            return submitted, (f"sbatch failed for {script}: {r.stderr.strip()}\n"
                               f"submitted job ids: {' '.join(submitted) or 'none'}\n"
                               "not submitted: " + " ".join(str(a[3]) for a in w.arrays[i:]))
        with open(w.run_dir / "jobs.tsv", "a") as fh:
            fh.write(f"{jid}\t{ids_file}\n")
        submitted.append(jid)
    return submitted, None
```

- [ ] **Step 4: Rewire `phylo.py`.** Delete `TOOLS`, `MAX_ARRAY`, `SBATCH`, `_chunks`, `_new_run_dir`, the body of `_preflight`, `SHOW`/`_show`; import them back so existing names keep working:

```python
TOOLS, MAX_ARRAY, SBATCH, SHOW = model.TOOLS, model.MAX_ARRAY, model.SBATCH, model.SHOW
_chunks = model.chunks
_new_run_dir = model.new_run_dir
_show = model.show


def _preflight(stage: str):
    msg = model.preflight(stage)
    if msg:
        _fail(msg, 78)
```

Replace the body of `submit()` from `unknown = sorted(...)` to the end with (everything above it — option parsing, `raw`, `override`, `set_notes`, `cfg`, `applicable` check, `selected`, `--fam` — stays):

```python
    try:
        sel = model.select(cfg, stage, selected, all_=all_, dry_run=dry_run)
    except model.ModelError as e:
        if e.code == 2:                     # unknown ids: same two stderr lines as before
            for line in str(e).splitlines():
                typer.echo(line, err=True)
            raise typer.Exit(2)
        _fail(str(e), e.code)
    sel.notes[:0] = set_notes               # printed plainly on submit, inside the panel on a dry run
    if not sel.selected:
        for note in sel.notes:
            typer.echo(note)
        typer.echo("nothing to submit")
        raise typer.Exit(0)
    _preflight(stage)
    over = [f"{k}={v}" for k, v in (("--mem", mem), ("--time", time), ("--cpus", cpus)) if v]
    p = model.plan(cfg, stage, sel, override, over_flags=over)
    if p.errors:
        for k, v in p.errors.items():
            typer.echo(f"{k} ({len(v)}): {_show(v)}", err=True)
        typer.echo("nothing submitted", err=True)
        raise typer.Exit(2)
    w = model.write_run(cfg, raw, p, dry_run, max_running, partition, qos)
    if dry_run:
        _print_dry_run(stage, w.run_dir, w.arrays, qos, p.notes)
        return
    for note in p.notes:
        typer.echo(note)
    typer.echo(f"run dir: {w.run_dir}")
    jids, err = model.sbatch_all(w)
    for jid, (res, ids_, _f, _s) in zip(jids, w.arrays):
        typer.echo(f"submitted {jid}: {len(ids_)} HGs ({res.cpus} cpus, {res.mem_mb}M, {res.time_min} min)")
    if err:
        for line in err.splitlines():
            typer.echo(line, err=True)
        raise typer.Exit(1)
```

⚠ Ordering detail that tests pin: before this change the `submitted …` line was printed right after each successful `sbatch`; printing them after `sbatch_all` returns gives the same stdout text in the same order (stderr lines still come last). Do not reorder `notes`: `set_notes` first, then the skip notes, then the resources note — exactly as the old code appended them.

- [ ] **Step 5: Run both suites** — Expected: `141 passed` on both. If any of the 118 existing tests fails, the refactor changed output — fix the refactor, never the test.

- [ ] **Step 6: Hand off** — files: `phylocli/model.py`, `phylocli/phylo.py`, `phylocli/tests/test_model.py`.

---

### Task 6: `phylo tui` — Textual app with the four panels and background refresh

**Prerequisite (controller, once, with Grygoriy's OK):** install Textual into both local test envs so the TUI tests run instead of skipping: `python3 -m pip install textual` and `$PY39 -m pip install textual`. Record the installed version in the hand-off message.

**Files:**
- Create: `phylocli/tui.py`
- Modify: `phylocli/phylo.py` (add `tui` command after `jobs`)
- Test: `phylocli/tests/test_tui.py`

**Interfaces:**
- Consumes: `model.stage_rows`, `model.hg_rows`, `model.hg_detail`, `model.array_rows`, `history.attempts`
- Produces:
  - `class PhyloApp(App)`: `__init__(cfg: core.Config, refresh_s: int = 30)`; attributes `stage: str`, `filter: str`, `selected: set[str]`, `rows: list[model.HGRow]`; method `load_now()` (synchronous refresh, used by tests and `R`)
  - `FILTERS = ("failed", "ready", "running", "blocked", "done")`
  - `phylo tui` command

- [ ] **Step 1: Failing tests** — `phylocli/tests/test_tui.py`:

```python
"""phylocli/tui.py (Textual pilot tests; skipped when Textual is not installed)."""
import asyncio
import os

import pytest

pytest.importorskip("textual")

from phylocli import core, tui  # noqa: E402
from phylocli.tests.test_cli import _state, cli  # noqa: E402,F401

SACCT_OOM = ("12345_0|COMPLETED|10M|00:01:00|0:0\\n"
             "12345_1|OUT_OF_MEMORY|4100M|00:03:00|0:125\\n")


def _cfg():
    return core.load_config(os.environ["PHYLOCLI_CONFIG"])


def _run(coro):
    return asyncio.run(coro)


def test_tui_loads_and_filters_failed(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert app.stage == "align" and app.filter == "failed"
            assert [r.hg for r in app.visible()] == ["tfs.C_x.HG1"]
            await pilot.press("f")
            assert app.filter == "ready" and [r.hg for r in app.visible()] == ["tfs.A.HG11"]
    _run(go())


def test_tui_select_all_and_quit(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a")
            assert app.selected == {"tfs.C_x.HG1"}
            await pilot.press("q")
    _run(go())


def test_tui_command_without_textual(cli, monkeypatch):
    import sys

    import phylocli
    # None in sys.modules makes `from textual import ...` raise ModuleNotFoundError(name="textual");
    # phylocli.tui must be forgotten both as a module and as the package attribute.
    monkeypatch.setitem(sys.modules, "textual", None)
    monkeypatch.delitem(sys.modules, "phylocli.tui", raising=False)
    monkeypatch.delattr(phylocli, "tui", raising=False)
    r = cli(["tui"])
    assert r.exit_code == 1 and "pip install textual" in r.output
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider` — Expected: FAIL, `ImportError: cannot import name 'tui'`.

- [ ] **Step 3: Implement `phylocli/tui.py`:**

```python
"""phylo tui: interactive view of step2 progress (Textual). Imported only by `phylo tui`."""
from __future__ import annotations

from datetime import datetime

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.widgets import DataTable, Footer, Header, Static

from phylocli import core, history, model
from phylocli.common import fmt_mem, fmt_time

FILTERS = ("failed", "ready", "running", "blocked", "done")
STATE_STYLE = {"done": "green", "running": "cyan", "ready": "yellow", "failed": "red",
               "blocked": "bright_black"}


class PhyloApp(App):
    TITLE = "phylocli"
    CSS = """
    Grid { grid-size: 2 2; grid-columns: 1fr 1fr; grid-rows: 1fr 1fr; }
    DataTable, #detail { border: round $primary; height: 100%; }
    #banner { height: auto; color: $warning; }
    """
    BINDINGS = [
        Binding("f", "cycle_filter", "filter"),
        Binding("space", "toggle", "select"),
        Binding("a", "select_all", "select all"),
        Binding("r", "resubmit", "resubmit"),
        Binding("l", "log", "log"),
        Binding("R", "refresh", "refresh"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self, cfg: core.Config, refresh_s: int = 30):
        super().__init__()
        self.cfg = cfg
        self.refresh_s = refresh_s
        self.stage = core.STAGES[0]
        self.filter = FILTERS[0]
        self.selected: set[str] = set()
        self.rows: list = []
        self.atts: list = []
        self.nseq: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="banner")
        with Grid():
            yield DataTable(id="stages", cursor_type="row")
            yield DataTable(id="hgs", cursor_type="row")
            yield DataTable(id="arrays", cursor_type="row")
            yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#stages", DataTable).add_columns("stage", "done", "run", "ready", "blk", "total")
        self.query_one("#hgs", DataTable).add_columns(" ", "HG", "seqs", "state", "last", "req", "used")
        self.query_one("#arrays", DataTable).add_columns("job", "stage", "HGs", "done", "run",
                                                          "pend", "fail")
        self.load_bg()
        self.set_interval(self.refresh_s, self.load_bg)

    # ---- data -------------------------------------------------------------------------------
    def _collect(self) -> dict:
        exp = core.expected(self.cfg)
        stages, known, _done = model.stage_rows(self.cfg, exp)
        atts = history.attempts(self.cfg)
        rows = model.hg_rows(self.cfg, self.stage, exp, atts)
        arrays, sacct_known = model.array_rows()
        return dict(stages=stages, known=known, atts=atts, rows=rows, arrays=arrays,
                    sacct_known=sacct_known, when=datetime.now())

    def load_now(self) -> None:
        self._apply(self._collect())

    @work(thread=True, exclusive=True)
    def load_bg(self) -> None:
        try:
            snap = self._collect()
        except model.ModelError as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        self.call_from_thread(self._apply, snap)

    def _apply(self, snap: dict) -> None:
        self.atts, self.rows = snap["atts"], snap["rows"]
        banner = []
        if not snap["known"]:
            banner.append("squeue not on PATH: running jobs not detected")
        if not snap["sacct_known"]:
            banner.append("sacct not on PATH: task states unknown")
        self.query_one("#banner", Static).update(" · ".join(banner))
        self.sub_title = f"{self.stage} · {self.filter} · {snap['when']:%H:%M:%S}"
        st = self.query_one("#stages", DataTable)
        st.clear()
        for r in snap["stages"]:
            if r.applicable:
                st.add_row(r.stage, str(r.done), str(r.running), str(r.ready), str(r.blocked),
                           str(r.total), key=r.stage)
            else:
                st.add_row(r.stage, "n/a", "", "", "", "", key=r.stage)
        ar = self.query_one("#arrays", DataTable)
        ar.clear()
        for a in snap["arrays"]:
            c = a.counts
            ar.add_row(a.job, a.stage, str(a.n), str(c["done"]), str(c["running"]),
                       str(c["pending"]), str(c["failed"]), key=a.job)
        self._fill_hgs()

    def visible(self) -> list:
        return [r for r in self.rows if r.state == self.filter]

    def _fill_hgs(self) -> None:
        t = self.query_one("#hgs", DataTable)
        t.clear()
        for r in self.visible():
            n = self.nseq.setdefault(r.hg, core.nseq(self.cfg, r.hg))
            a = r.last
            t.add_row("●" if r.hg in self.selected else " ", r.hg, str(n),
                      f"[{STATE_STYLE[r.state]}]{r.state}[/]",
                      model.bump_reason(a) if a else "–",
                      f"{a.mem}/{a.time}" if a else "–",
                      f"{a.peak_rss}/{a.realtime}" if a else "–", key=r.hg)
        self._show_detail()

    def _cursor_hg(self) -> str | None:
        t = self.query_one("#hgs", DataTable)
        vis = self.visible()
        return vis[t.cursor_row].hg if vis and 0 <= t.cursor_row < len(vis) else None

    def _show_detail(self) -> None:
        hg = self._cursor_hg()
        box = self.query_one("#detail", Static)
        if hg is None:
            box.update("")
            return
        d = model.hg_detail(self.cfg, hg, self.atts)
        lines = [f"[b]{hg}[/]  {d.nseq} seqs", ""]
        for st, s in d.states.items():
            a = d.latest.get(st)
            extra = (f"  {a.status} ({history.reason(a.status, a.exit)})  req {a.cpus}/{a.mem}/{a.time}"
                     f"  used {a.peak_rss}/{a.realtime}" if a else "")
            lines.append(f"{st:<12} [{STATE_STYLE.get(s, 'white')}]{s}[/]{extra}")
        a = d.latest.get(self.stage)
        if a is not None:
            lines += ["", f"log: {a.log}"]
        box.update("\n".join(lines))

    # ---- events / actions -------------------------------------------------------------------
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "stages" and event.row_key.value in core.STAGES:
            if event.row_key.value != self.stage:
                self.stage = event.row_key.value
                self.selected.clear()
                self.rows = model.hg_rows(self.cfg, self.stage, None, self.atts)
                self._fill_hgs()
        elif event.data_table.id == "hgs":
            self._show_detail()

    def action_cycle_filter(self) -> None:
        self.filter = FILTERS[(FILTERS.index(self.filter) + 1) % len(FILTERS)]
        self._fill_hgs()

    def action_toggle(self) -> None:
        hg = self._cursor_hg()
        if hg:
            self.selected ^= {hg}
            self._fill_hgs()

    def action_select_all(self) -> None:
        self.selected = {r.hg for r in self.visible()}
        self._fill_hgs()

    def action_refresh(self) -> None:
        self.load_bg()

    def action_resubmit(self) -> None:      # Task 7
        self.notify("resubmit: not implemented yet")

    def action_log(self) -> None:           # Task 7
        self.notify("log: not implemented yet")
```

Add to `phylo.py`, after the `jobs` command:

```python
@app.command()
def tui(refresh: int = typer.Option(30, "--refresh", min=5, help="seconds between refreshes")):
    """Interactive view: stages, HGs, arrays; select failed HGs and resubmit them."""
    try:
        from phylocli import tui as tui_mod
    except ModuleNotFoundError as e:
        if (e.name or "").startswith("textual"):
            _fail("textual not installed: pip install textual", 1)
        raise
    tui_mod.PhyloApp(_cfg(), refresh_s=refresh).run()
```

- [ ] **Step 4: Run both suites** — Expected: `144 passed` on both (with Textual installed; without it the 3 TUI tests report `skipped`).

- [ ] **Step 5: Hand off** — files: `phylocli/tui.py`, `phylocli/phylo.py`, `phylocli/tests/test_tui.py`.

---

### Task 7: resubmit dialog (bumped, editable resources → dry run → confirm) and log pop-up

**Files:**
- Modify: `phylocli/tui.py` (add `ResubmitScreen`, `LogScreen`, real `action_resubmit` / `action_log`)
- Test: `phylocli/tests/test_tui.py` (append)

**Interfaces:**
- Consumes: `model.bump`, `model.bump_reason`, `model.select`, `model.plan`, `model.write_run`, `model.sbatch_all`, `model.preflight`, `core.group`, `core.parse_mem_mb`, `core.parse_time_min`
- Produces:
  - `resource_groups(cfg, stage, rows: list[model.HGRow]) -> list[tuple[str, core.Res, list[str]]]` — (reason, bumped Res, hgs), one entry per distinct (reason, Res)
  - `class ResubmitScreen(ModalScreen)`: `__init__(cfg, stage, groups)`; widgets `Input#mem-<i>`, `Input#time-<i>`, `Static#out`; keys `enter` dry run, `y` submit, `escape` cancel; attribute `submitted: list[str]`
  - `class LogScreen(ModalScreen)`: shows the last 200 lines of the attempt's `.err` and the matching `.out`; `escape`/`q` close

- [ ] **Step 1: Failing tests** (append to `test_tui.py`):

```python
def _calls():
    p = _state["bin"] / "calls.txt"
    return p.read_text().splitlines() if p.exists() else []


def _failed_app(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)
    return tui.PhyloApp(_cfg(), refresh_s=3600)


def test_resource_groups_bump_oom(cli, monkeypatch):
    _failed_app(cli, monkeypatch)
    from phylocli import model
    rows = [r for r in model.hg_rows(_cfg(), "align") if r.state == "failed"]
    groups = tui.resource_groups(_cfg(), "align", rows)
    assert [(g[0], g[1].mem_mb, g[2]) for g in groups] == [("OOM", 8192, ["tfs.C_x.HG1"])]


def test_resubmit_dry_run_then_confirm(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    n0 = len(_calls())

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a", "r")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, tui.ResubmitScreen)
            scr.query_one("#mem-0").value = "16G"
            await pilot.press("enter")
            await pilot.pause()
            assert "dry run" in str(scr.query_one("#out").renderable)
            assert len(_calls()) == n0                      # dry run submits nothing
            await pilot.press("y")
            await pilot.pause()
            assert scr.submitted == ["12345"]
    _run(go())
    script = sorted((_state["runs"]).glob("*_align*/array_0.sbatch"))[-1].read_text()
    assert "--mem=16384M" in script


def test_resubmit_escape_submits_nothing(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    n0 = len(_calls())

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a", "r", "enter", "escape")
            await pilot.pause()
            assert not isinstance(app.screen, tui.ResubmitScreen)
    _run(go())
    assert len(_calls()) == n0


def test_resubmit_bad_value_is_inline_error(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    n0 = len(_calls())

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a", "r")
            await pilot.pause()
            scr = app.screen
            scr.query_one("#mem-0").value = "abc"
            await pilot.press("enter", "y")
            await pilot.pause()
            assert "bad memory value" in str(scr.query_one("#out").renderable)
            assert scr.submitted == []
    _run(go())
    assert len(_calls()) == n0


def test_resubmit_nothing_selected(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            assert not isinstance(app.screen, tui.ResubmitScreen)
    _run(go())


def test_confirm_skips_hg_queued_after_dry_run(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a", "r", "enter")
            await pilot.pause()
            scr = app.screen
            monkeypatch.setenv("FAKE_SQUEUE", "12345_1|phylo-align\n")   # queued meanwhile
            await pilot.press("y")
            await pilot.pause()
            assert scr.submitted == [] and "already queued" in str(scr.query_one("#out").renderable)
    _run(go())


def test_log_popup(cli, monkeypatch, tmp_path):
    app = _failed_app(cli, monkeypatch)
    run = sorted(_state["runs"].glob("*_align"))[-1]
    (run / "logs" / "align_12345_1.err").write_text("boom: out of memory\n")

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("l")
            await pilot.pause()
            assert isinstance(app.screen, tui.LogScreen)
            assert "boom: out of memory" in app.screen.text
            await pilot.press("escape")
    _run(go())
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider` — Expected: FAIL, `AttributeError: module 'phylocli.tui' has no attribute 'resource_groups'`.

- [ ] **Step 3: Implement** — add to `tui.py` imports: `from pathlib import Path`, `from textual.screen import ModalScreen`, `from textual.containers import Vertical, Horizontal`, `from textual.widgets import Input, Label`, `import yaml`, `import os`. Then:

```python
def resource_groups(cfg: core.Config, stage: str, rows: list) -> list:
    """[(reason, bumped Res, hgs)] for the selected rows, one entry per distinct pair."""
    table = core.load_resources_tsv(Path(cfg.params["resources_tsv"]))
    out: dict = {}
    for r in sorted(rows, key=lambda r: r.hg):
        res = model.bump(r.last, core.resources(cfg, stage, r.hg, table))
        out.setdefault((model.bump_reason(r.last), res), []).append(r.hg)
    return [(why, res, hgs) for (why, res), hgs in out.items()]


class ResubmitScreen(ModalScreen):
    BINDINGS = [Binding("enter", "dry_run", "dry run"), Binding("y", "submit", "submit"),
                Binding("escape", "cancel", "cancel")]
    CSS = """
    ResubmitScreen { align: center middle; }
    #box { width: 90%; height: auto; border: round $warning; background: $surface; padding: 1; }
    Input { width: 14; }
    """

    def __init__(self, cfg: core.Config, stage: str, groups: list):
        super().__init__()
        self.cfg, self.stage, self.groups = cfg, stage, groups
        self.submitted: list[str] = []
        self._dry_ok = False
        self._shown = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label(f"[b]resubmit · {self.stage}[/]  enter = dry run · y = submit · esc = cancel")
            for i, (why, res, hgs) in enumerate(self.groups):
                with Horizontal():
                    yield Label(f"{len(hgs)} HGs · {why or 'other'} · mem ")
                    yield Input(fmt_mem(res.mem_mb).replace(" ", "").replace("GB", "G")
                                .replace("MB", "M"), id=f"mem-{i}")
                    yield Label(" time ")
                    yield Input(fmt_time(res.time_min), id=f"time-{i}")
            yield Static("", id="out")

    def _per_hg(self) -> dict:
        per: dict = {}
        for i, (_why, _res, hgs) in enumerate(self.groups):
            mem = core.parse_mem_mb(self.query_one(f"#mem-{i}", Input).value)
            t = model.parse_duration_min(self.query_one(f"#time-{i}", Input).value)
            if mem <= 0 or not t:
                raise ValueError(f"bad value in row {i}: memory and time must be > 0")
            for hg in hgs:
                per[hg] = {"mem_mb": mem, "time_min": t}
        return per

    def _build(self, dry_run: bool):
        per = self._per_hg()                                   # ValueError -> caller
        hgs = [hg for _w, _r, g in self.groups for hg in g]
        sel = model.select(self.cfg, self.stage, hgs, dry_run=dry_run)
        if not sel.selected:
            return None, "\n".join(sel.notes + ["nothing to submit"])
        msg = model.preflight(self.stage)
        if msg:
            return None, msg
        p = model.plan(self.cfg, self.stage, sel, per_hg=per)
        if p.errors:
            return None, "\n".join(f"{k} ({len(v)}): {model.show(v)}" for k, v in p.errors.items())
        return p, ""

    def _out(self, text: str) -> None:
        self._shown = text
        self.query_one("#out", Static).update(text)

    def action_dry_run(self) -> None:
        self._dry_ok = False
        try:
            p, err = self._build(dry_run=True)
        except (ValueError, model.ModelError) as e:
            self._out(f"[red]{e}[/]")
            return
        if p is None:
            self._out(f"[red]{err}[/]")
            return
        lines = ["[cyan]dry run[/] — nothing submitted yet; y to submit"] + p.notes
        for k, (res, ids_) in enumerate(p.groups):
            lines.append(f"array {k}: {len(ids_)} HGs · {res.cpus} cpus · {fmt_mem(res.mem_mb)}"
                         f" · {fmt_time(res.time_min)} · {res.qos}")
        self._out("\n".join(lines))
        self._dry_ok = True

    def action_submit(self) -> None:
        if not self._dry_ok:
            if not self._shown:                    # keep an error the dry run already shows
                self._out("[yellow]run the dry run first (enter)[/]")
            return
        try:
            p, err = self._build(dry_run=False)               # recomputed: state may have moved
        except (ValueError, model.ModelError) as e:
            self._out(f"[red]{e}[/]")
            return
        if p is None:
            self._out(f"[red]{err}[/]")
            self._dry_ok = False
            return
        raw = yaml.safe_load(open(os.environ.get("PHYLOCLI_CONFIG")
                                  or core.ROOT / "phylocli/config.yaml").read())
        w = model.write_run(self.cfg, raw, p, dry_run=False)
        jids, err = model.sbatch_all(w)
        self.submitted = jids
        self._dry_ok = False
        self._out((f"[green]submitted {' '.join(jids)}[/] · run dir {w.run_dir}" if jids else "")
                  + (f"\n[red]{err}[/]" if err else ""))

    def action_cancel(self) -> None:
        self.dismiss(self.submitted)


class LogScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", "close"), Binding("q", "close", "close")]
    CSS = "LogScreen { align: center middle; } #log { width: 95%; height: 90%; border: round $primary; background: $surface; }"

    def __init__(self, path: str, n: int = 200):
        super().__init__()
        parts = []
        for p in (Path(path), Path(path).with_suffix(".out")):
            if p.is_file():
                lines = p.read_text(errors="replace").splitlines()[-n:]
                parts.append(f"== {p}\n" + "\n".join(lines))
        self.text = "\n\n".join(parts) or f"no log at {path}"

    def compose(self) -> ComposeResult:
        from textual.containers import VerticalScroll
        with VerticalScroll(id="log"):
            yield Static(self.text, markup=False)

    def action_close(self) -> None:
        self.dismiss()
```

Replace the two placeholder actions in `PhyloApp`:

```python
    def action_resubmit(self) -> None:
        rows = [r for r in self.rows if r.hg in self.selected]
        if not rows:
            self.notify("nothing selected (space / a)", severity="warning")
            return
        groups = resource_groups(self.cfg, self.stage, rows)
        self.push_screen(ResubmitScreen(self.cfg, self.stage, groups),
                         lambda _jids: (self.selected.clear(), self.load_bg()))

    def action_log(self) -> None:
        hg = self._cursor_hg()
        a = next((r.last for r in self.rows if r.hg == hg), None) if hg else None
        if a is None:
            self.notify("no attempt recorded for this HG at this stage", severity="warning")
            return
        self.push_screen(LogScreen(a.log))
```

⚠ Textual's `Input` consumes `enter`/`y` while it has focus. In `ResubmitScreen.on_mount` set focus off the inputs only when the user is not editing: add

```python
    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_dry_run()
```

and in the tests the value is set programmatically, so focus the box before pressing keys: add `def on_mount(self): self.query_one("#box").focus()` with `can_focus=True` on the box (`Vertical(id="box")` → subclass `class _Box(Vertical, can_focus=True): pass` and use `_Box(id="box")`). Run the tests; if a key still lands in an `Input`, the failing assertion shows which one.

- [ ] **Step 4: Run both suites** — Expected: `151 passed` on both.

- [ ] **Step 5: Manual smoke test (controller, with Grygoriy)** — on `login1` in v3 after copying the files: `phylocli/phylo tui`, move to `gxsup`, `f` to failed, `a`, `r`, `enter`, check the dry run, `esc`. Nothing is submitted.

- [ ] **Step 6: Hand off** — files: `phylocli/tui.py`, `phylocli/tests/test_tui.py`.

---

### Task 8: docs

**Files:**
- Modify: `phylocli/README.md` (new section `## phylo tui`), `docs/superpowers/specs/2026-10-08-phylocli-tui-design.md` (keys line)

- [ ] **Step 1: README section** — append:

```markdown
## phylo tui

Full-screen view (Textual, optional: `pip install textual` in the `phylo` env).

    phylocli/phylo tui [--refresh 30]

Panels: stages (top left) · HGs of the highlighted stage (top right) · latest arrays
(bottom left) · details of the highlighted HG (bottom right). Refreshes in the background.

Keys: `↑↓` move · `tab` panel · `f` filter (failed → ready → running → blocked → done) ·
`space` select · `a` select all shown · `r` resubmit selection · `l` last log · `R` refresh ·
`q` quit.

Resubmit: one row per resource group, pre-filled with the automatic bump (out of memory →
memory ×2, time limit → time ×2, other failures unchanged); memory and time are editable.
`enter` = dry run (nothing submitted), `y` = submit (the selection is re-checked first, so HGs
queued or finished meanwhile are skipped), `esc` = cancel.
```

- [ ] **Step 2: Spec** — in the keys line replace ``` `l` open last log in `less` (TUI suspended, resumes on quit) ``` with ``` `l` show the last 200 lines of the last attempt's .err/.out in a pop-up (no `less`: suspending the app needs Textual ≥ 0.48, unverified on the cluster) ```.

- [ ] **Step 3: Hand off** — files: `phylocli/README.md`, `docs/superpowers/specs/2026-10-08-phylocli-tui-design.md`, plus this plan file.
