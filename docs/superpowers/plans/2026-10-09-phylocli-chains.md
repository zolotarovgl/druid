# phylocli chains — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `phylo chain <selection>` (and `C` in the TUI) takes HGs through align → tree → (possvm_prev ∥ generax) → gxsup → possvm with one SLURM driver job that polls sacct, retries resource failures with more resources, advances HGs stage by stage once their output exists, and hands over to a successor before its own time limit.

**Architecture:** A new print-free module `phylocli/chain.py` holds everything: the stage graph, the per-(HG, stage) state in `runs/chains/<date>_<name>/chain.json` (atomic writes), resource fitting (qos from time, caps), the single-step function `_chain_step(state, now) -> state` (no clock, no sleep: the driver loop `run_driver` injects both) and the status / cancel / resume helpers. Stage arrays are submitted only through the existing `model.select` → `model.plan` → `model.write_run` → `model.sbatch_all`. `phylo.py` gains the `chain` command and the hidden `_chain` (the driver's entry point); `tui.py` gains `C`, a `ChainScreen` dialog, chain rows in pane `3 Arrays` and a `chain:<stage> aN` state cell — last, since two other plans also edit `tui.py`.

**Tech Stack:** Python ≥ 3.9, typer + rich (CLI), Textual 8.2.8 (optional, `tui.py` only), pytest. SLURM: sbatch / squeue / sacct / scancel.

**Spec:** `docs/superpowers/specs/2026-10-09-phylocli-chains-design.md` (all sections approved by Grygoriy 09/10/2026).

**Repo / branch:** worktree `~/Documents/projects/phylogenies/phylocli-wt`, branch `phylocli`. **Plan based on HEAD `d1904c7`** (09/10/2026: step1 Tasks 1–3 committed — `core.FAMILY_STAGES`, `core.HG_STAGES`, `core.STAGES = FAMILY_STAGES + HG_STAGES`, `tui.TUI_STAGES`; step1 Task 4 was uncommitted in the worktree, editing `model.py` / `history.py`). Code below names functions, never line numbers: rebase onto whatever has landed. **Checked 09/10/2026:** the code of all five tasks, applied to a copy of `d1904c7`, passes the full suite on both interpreters (224 → 298 tests: +24, +12, +20, +11, +5). The Results-window plan (`docs/superpowers/plans/2026-10-09-phylocli-tui-results-sort.md`) also edits `tui.py` (keys `o`, `p`, `s`, `h`); `C` does not collide.

## Global Constraints

- **Chains cover the six HG stages only** (spec "Out of scope": no `search` / `cluster`). `chain.CHAIN_STAGES` is the literal `("align", "tree", "possvm_prev", "generax", "gxsup", "possvm")` and equals `core.HG_STAGES`; chain code never iterates `core.STAGES` (which step1 extends with family stages). `--from` / `--to` / the TUI stage outside `CHAIN_STAGES` → `ModelError` code 2 "chains run the HG stages only". This keeps the plan valid before and after the remaining step1 tasks land.
- Existing CLI output text and exit codes unchanged; **existing tests unmodified** (new tests go into the new `phylocli/tests/test_chain.py` and are appended to `test_tui.py`; new TUI tests import `chain` inside the test function, so the top of `test_tui.py` is not touched).
- Python 3.9-safe (`from __future__ import annotations`; no `match`; no `X | Y` outside annotations). Textual imported only in `tui.py`; `chain.py` imports neither typer nor textual.
- **Every stage submission goes through `model.select`** (skips HGs queued in SLURM — phylocli arrays or Nextflow jobs — and HGs without inputs) and then `model.plan` (whose `core.validate` refuses HGs whose output exists). The chain additionally marks HGs done from output files before selecting, so finished HGs are never resubmitted. No other code path calls `sbatch` for an array; the driver job is submitted only by `chain.submit_driver`.
- Cluster facts (measured 09/10/2026, `sacctmgr`): qos max wall **normal 12 h (720 min), long 1 day (1440), vlong 2 days (2880)**; MaxArraySize 60000 (`model.MAX_ARRAY` = 1000 stays as is — not this plan's business).
- Driver job: name `phylo-chain`, 1 cpu, `--mem=500M`, qos `long`, `--time=1440`; polls every 60 s (`options.poll_s`); submits its successor `HANDOVER_S` = 1800 s (30 min) before its own limit with `--dependency=afterany:<own job id>` and exits.
- Retried (resource failures): states `OUT_OF_MEMORY`, `TIMEOUT`, `NODE_FAIL`, `PREEMPTED`, `BOOT_FAIL`, or exit 137 / 140 — via `model.bump()` (OOM / 137 → memory ×2; TIMEOUT / 140 → time ×2; node / preempt / boot → unchanged), up to `--attempts` (default 3). Everything else (exit 1, 65, 10, `CANCELLED`, `DEADLINE`, …) is **not** retried.
- Caps: memory ≤ `chain_max_mem` (top-level key in `phylocli/config.yaml`, default `64G`; NOT under `params:`, whose keys are exported to stage scripts and are the `--set` keys); time ≤ 2880 min; qos = the smallest of normal / long / vlong that holds the time, never below the stage default's qos. Over a cap → `failed:cap`.
- Batching (first attempts of one stage): submit when ≥ `batch_min` (50) are eligible, or `batch_wait_s` (300 s) after the first became eligible, or when no HG of the chain is still `blocked` at that stage. Retries are submitted on the poll that found them.
- `chain.json` is written atomically (tmp + fsync + `os.replace`) after every change; `"version": 1`.
- **No test sleeps or reads the real clock**: tests call `chain._chain_step(state, now)` with `now = T0 + …` and `chain.run_driver(dir, clock=…, sleep=…, job_id=…, max_steps=…)`.
- Test commands (both must pass): `python3 -m pytest phylocli/tests -q -p no:cacheprovider` and `/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-phylogenies/3dad6ea4-c859-4fe6-b319-93a358944ac8/scratchpad/py39/bin/python -m pytest phylocli/tests -q -p no:cacheprovider`. Test counts are given as deltas (the baseline moves while step1 lands).
- Commit on `phylocli` after each task, message ending with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Edit with the Edit/Write tools only (never `sed` / string-replace scripts).
- Dates in docs as dd/mm/yyyy.
- A controller smoke test on the cluster (2–3 small HGs) needs Grygoriy's go; it is **not** a task of this plan.

## Decisions taken while planning (spec silent or ambiguous)

1. **State per (HG, stage) record**: `blocked` → `eligible` → `queued` → `done`, plus `external` (queued by someone else; watched, taken back when it leaves the queue without output — attempt not counted) and `failed` with a `reason` (shown as `failed:<reason>`: `oom` / `time` / `node` after the last attempt, `cap`, `no_inputs`, `no_output`, `upstream`, `cancelled`, or `history.reason()` text such as `exit 1`, `stage produced no output`, `GeneRax parse error`).
2. The chain's stages are the applicable `CHAIN_STAGES` from `--from` to `--to` **in pipeline order**, so `--to possvm` includes `possvm_prev`. Stages before `--from` are not tracked (treated as satisfied; a missing input then stops the HG as `failed:no_inputs`). `--from` default = each HG's first not-done stage (done stages are recorded `done` at creation).
3. Attempt-1 resources are the step2 defaults (`core.resources`, resources.tsv) **passed through the same qos fit and caps** — a resources.tsv tree time of 19 h at qos normal is submitted under `long`, never rejected by SLURM. `phylo submit` is unchanged.
4. A task `COMPLETED` in sacct whose output is not visible yet waits `no_output_grace_s` (600 s; NFS lag) before `failed:no_output`.
5. `-f FAMILY` alone is a selection (every expected HG of the family); combined with ids / `--ids` / `--missing` it filters, as in `submit`. `--name NAME` (not in the spec) names the chain dir; default = the single family of the HGs, else `chain`.
6. `--status`, `--cancel`, `--resume` are flags; the chain is the positional argument (its dir or its name under `runs/chains/`). `--status` without it lists the 10 newest chains. A running chain whose driver and successor are both absent from `squeue` is shown as **`stalled`** with the `--resume` hint.
7. Cancel writes a `cancelled` marker file in the chain dir **first**; `load()`, `save()` and `_chain_step()` honour it, so a driver that was mid-step cannot save the chain back to `running`.
8. A driver started outside SLURM (no `SLURM_JOB_ID`) has no time limit and never hands over. A driver refuses to start (exit 1) while the recorded driver or successor of the chain is still in `squeue`.
9. TUI: HGs a running chain owns are left out of `r` (resubmit) and `C` with a warning (`select` alone would not stop a resubmit while the HG waits in a chain's batch, unqueued); the state cell shows `chain:<stage> aN` unless the HG is done at the viewed stage.
10. Only active records (`blocked` / `eligible` / `queued` / `external`) are marked done from output files; a stopped HG stays stopped even if its output appears later (rerun with a new chain).

## Review Focus

1. **A task `COMPLETED` in sacct whose published output is not yet visible** (NFS lag on the mount) — expected: the HG keeps waiting for `no_output_grace_s`, advances if the output shows up, and only then stops as `failed:no_output`; never stopped on the first poll. → Task 3 test `test_completed_without_output_waits_then_stops`.
2. **A driver restarted from `chain.json`** (successor, node failure, `phylo chain --resume`) — expected: tasks already queued by the chain are watched, not resubmitted; and two drivers never run on one chain at once. → Task 3 tests `test_resume_from_saved_state_does_not_resubmit`, `test_second_driver_exits_while_first_is_queued`; Task 4 test `test_chain_resume`.
3. **`--cancel` while the driver is mid-step** — the driver still holds a `running` state in memory and saves it after the cancel. Expected: the chain stays cancelled and no new array is submitted. → Task 4 test `test_cancel_wins_over_a_driver_mid_step`.
4. **Attempt-1 resources already over a qos limit or a cap** (resources.tsv: tree 19 h at qos normal; memory above `chain_max_mem`) — expected: submitted under the qos its time needs; over every cap → `failed:cap` without any sbatch. → Task 2 tests `test_attempt1_time_gets_the_qos_it_needs`, `test_attempt1_over_cap_stops_without_submitting`.
5. **Transient SLURM failures** (sbatch error such as `QOSMaxSubmitJobPerUserLimit`, sacct unavailable or timing out, an exception inside a step) — expected: logged, HGs stay eligible / queued and are handled on the next poll; the driver does not exit. → Task 2 test `test_sbatch_failure_keeps_hgs_eligible`; Task 3 tests `test_sacct_unavailable_keeps_waiting`, `test_step_error_is_logged_and_the_driver_goes_on`.

(Also pinned, not in the top five: an HG a chain owns but has not yet submitted is not resubmitted by hand from the TUI → Task 5 test `test_chain_owned_hgs_show_chain_state_and_are_not_resubmitted`.)

---

## File Structure

| file | change | responsibility |
|---|---|---|
| `phylocli/chain.py` | create | stage graph (`CHAIN_STAGES`, `parents`, `stage_slice`), resources (`qos_for`, `fit`, `classify`, `retry_res`, `max_mem_mb`), state file (`create`, `new_state`, `save`, `load`, `resolve`), the step (`_chain_step` and helpers), driver (`DRIVER_SBATCH`, `submit_driver`, `run_driver`), CLI/TUI helpers (`prepare`, `plan_lines`, `default_name`, `start`, `cancel`, `check_no_driver`, `status_text`, `active`, `owned`, `array_table`) |
| `phylocli/model.py` | append | `task_results(job_ids)` — `{(job, task): (state, exit)}` from one sacct call |
| `phylocli/config.yaml` | modify | top-level `chain_max_mem: 64G` |
| `phylocli/phylo.py` | modify | `chain` command, hidden `_chain` command |
| `phylocli/tui.py` | modify | `C` binding, `action_chain`, `ChainScreen`, chain rows in pane 3, `_state_cell`, resubmit skips chain-owned HGs |
| `phylocli/README.md` | modify | `## phylo chain` section; `C` in `## phylo tui` |
| `phylocli/tests/test_chain.py` | create | everything chain (fixture `ch`: counting fake `sbatch`, fake `scancel`) |
| `phylocli/tests/test_tui.py` | append | `C` dialog, chain state cell, arrays pane |

Fixture facts (`conftest.py` `results_tree` + `test_cli.py` `cli`): expected HGs `tfs.A.HG1` (align, tree, possvm_prev done; generax not), `tfs.A.HG11` (nothing done — its possvm csv is empty; resources.tsv row: tree 800 MB / 1140 min), `tfs.C_x.HG1` (600 seqs → tree qos `long`; nothing done). `run_generax: true`, `gxsup: true`. The `cli` fixture's fake `sbatch` always prints `12345`, `squeue` prints `$FAKE_SQUEUE`, `sacct` prints `$FAKE_SACCT` through `printf %b` (so tests write `\\n`); fake `python`, `mafft`, `clipkit`, `iqtree2`, `generax`, `mpirun`. There is no fake `scancel`. The `ch` fixture (Task 1) replaces `sbatch` with one that prints `101`, `102`, … and adds a recording `scancel`.

---

### Task 1: `chain.py` foundation — stage graph, resources, state file; `model.task_results`

**Files:**
- Create: `phylocli/chain.py`
- Modify: `phylocli/model.py` (append `task_results` at the end), `phylocli/config.yaml` (one line)
- Test: `phylocli/tests/test_chain.py` (create)

**Interfaces:**
- Consumes: `core.applicable`, `core.Res`, `core.report_status.done_by_stage`, `core.parse_mem_mb`, `model.bump(att, res)`, `model.ModelError(msg, code)`, `history._sacct(job_ids)` (→ `{(job, i): {"state", "exit", ...}}` or `None`), `history._exit(s)`, `common.runs_dir()`, `fmt_mem`, `fmt_time`.
- Produces:
  - constants `CHAIN_STAGES`, `PARENTS`, `QOS_MAXWALL`, `NODE_STATES`, `TERMINAL`, `ACTIVE`, `DEFAULTS` (`attempts`, `max_mem_mb`, `batch_min`, `batch_wait_s`, `poll_s`, `max_running`, `no_output_grace_s`), `DEFAULT_MAX_MEM`, `DRIVER_TIME_MIN`, `HANDOVER_S`, `STATE_VERSION`
  - `parents(cfg, stage) -> list[str]`; `stage_slice(cfg, from_=None, to="possvm") -> list[str]` (ModelError code 2)
  - `qos_for(minutes, floor="normal") -> str | None`; `fit(res, max_mem_mb) -> (Res | None, why: str)`; `classify(state, exit_) -> "oom" | "time" | "node" | None`; `retry_res(last: dict, kind, default: Res) -> Res`; `max_mem_mb(raw: dict) -> int`
  - `chains_dir() -> Path`; `new_chain_dir(name, now) -> Path`; `new_state(cfg, hgs, stages, opts, d, name, now) -> dict`; `create(cfg, raw, hgs, stages, opts, name, now) -> dict`; `save(state)`; `load(d) -> dict` (ModelError code 1); `resolve(arg) -> Path`
  - internal, used by later tasks: `_rec`, `_stop(r, reason, note="")`, `_promote(state, cfg, now)`, `_log(state, now, msg)`, `_cancelled(d)`, `_mark_cancelled(state)`, `label(r)`, `summary(state) -> {stage: {label: n}}`
  - record dict: `{"state", "reason", "note", "attempt", "res", "since", "job", "task", "completed_at", "attempts": [...]}`; state dict: `{"version", "dir", "name", "created", "status", "stages", "options", "driver", "jobs", "summary", "hgs": {hg: {stage: record}}}`
  - `model.task_results(job_ids: list[str]) -> dict | None` — `{(job id, task index): (state, exit)}`, exit `"-"` when unknown

- [ ] **Step 1: Write the failing tests** — create `phylocli/tests/test_chain.py`:

```python
"""phylo chain: chain.py (state, retries, advancing, driver loop) and the `chain` command.
Uses the `cli` fixture's fake squeue / sacct; no test sleeps or reads the real clock."""
import collections
import dataclasses
import json
import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from phylocli import chain, core, history, model
from phylocli import phylo as cli_mod
from phylocli.tests.test_cli import _state, cli  # noqa: F401  (fixture)

T0 = 1_791_504_000.0           # 09/10/2026 00:00 UTC: the injected clock
A1, H11, C = "tfs.A.HG1", "tfs.A.HG11", "tfs.C_x.HG1"


@pytest.fixture
def ch(cli):
    """cli + an sbatch that hands out job ids 101, 102, ... and a scancel that records its args."""
    b = _state["bin"]
    (b / "sbatch").write_text(
        f'#!/bin/sh\necho "$@" >> {b}/calls.txt\n'
        f'n=$(cat {b}/jid 2>/dev/null || echo 100); n=$((n + 1)); echo $n > {b}/jid; echo $n\n')
    (b / "scancel").write_text(f'#!/bin/sh\necho "$@" >> {b}/scancel.txt\n')
    for p in (b / "sbatch", b / "scancel"):
        p.chmod(0o755)
    return cli


def _cfg():
    return core.load_config(os.environ["PHYLOCLI_CONFIG"])


def _raw():
    return yaml.safe_load(Path(os.environ["PHYLOCLI_CONFIG"]).read_text())


def _new(hgs, from_=None, to="possvm", **opts):
    """A chain named 't' over `hgs`, created at T0 (no driver submitted)."""
    cfg = _cfg()
    return chain.create(cfg, _raw(), hgs, chain.stage_slice(cfg, from_, to), opts, "t", T0)


def _log_text(st):
    return (Path(st["dir"]) / "driver.log").read_text()


def test_chain_stages_are_the_hg_stages():
    assert list(chain.CHAIN_STAGES) == core.HG_STAGES
    assert not set(chain.CHAIN_STAGES) & set(core.FAMILY_STAGES)


def test_parents_and_stage_slice(results_tree):
    cfg, _ = results_tree
    assert chain.stage_slice(cfg) == list(chain.CHAIN_STAGES)
    assert chain.stage_slice(cfg, "tree", "generax") == ["tree", "possvm_prev", "generax"]
    assert chain.parents(cfg, "possvm") == ["gxsup"] and chain.parents(cfg, "possvm_prev") == ["tree"]
    nogx = dataclasses.replace(cfg, params={**cfg.params, "gxsup": False})
    assert chain.parents(nogx, "possvm") == ["generax"] and "gxsup" not in chain.stage_slice(nogx)
    nogr = dataclasses.replace(cfg, params={**cfg.params, "run_generax": False})
    assert chain.parents(nogr, "possvm") == ["tree"]
    assert chain.stage_slice(nogr) == ["align", "tree", "possvm"]
    with pytest.raises(model.ModelError, match="does not run"):
        chain.stage_slice(nogr, None, "generax")


@pytest.mark.parametrize("from_,to,msg", [("generax", "tree", "comes after"),
                                          (None, "search", "HG stages only"),
                                          ("cluster", "possvm", "HG stages only")])
def test_stage_slice_errors(results_tree, from_, to, msg):
    cfg, _ = results_tree
    with pytest.raises(model.ModelError) as e:
        chain.stage_slice(cfg, from_, to)
    assert msg in str(e.value) and e.value.code == 2


def test_qos_for_and_fit():
    assert [chain.qos_for(m) for m in (30, 720, 721, 1440, 1441, 2880)] == \
        ["normal", "normal", "long", "long", "vlong", "vlong"]
    assert chain.qos_for(2881) is None and chain.qos_for(30, "long") == "long"
    r = core.Res(4, 4096, 1140, "normal", None)
    assert chain.fit(r, 65536) == (dataclasses.replace(r, qos="long"), "")
    res, why = chain.fit(dataclasses.replace(r, mem_mb=70000), 65536)
    assert res is None and "chain_max_mem" in why
    res, why = chain.fit(dataclasses.replace(r, time_min=3000), 65536)
    assert res is None and "vlong" in why


@pytest.mark.parametrize("state,exit_,kind", [
    ("OUT_OF_MEMORY", "0", "oom"), ("FAILED", "137", "oom"), ("TIMEOUT", "0", "time"),
    ("FAILED", "140", "time"), ("NODE_FAIL", "0", "node"), ("PREEMPTED", "0", "node"),
    ("BOOT_FAIL", "0", "node"), ("FAILED", "1", None), ("FAILED", "65", None),
    ("FAILED", "10", None), ("CANCELLED", "0", None), ("DEADLINE", "0", None)])
def test_classify(state, exit_, kind):
    assert chain.classify(state, exit_) == kind


def test_retry_res_uses_bump():
    d = core.Res(4, 4096, 240, "normal", None)
    last = {"cpus": 4, "mem_mb": 8192, "time_min": 240, "qos": "normal", "signal": None}
    assert chain.retry_res(last, "oom", d).mem_mb == 16384
    t = chain.retry_res(last, "time", d)
    assert (t.mem_mb, t.time_min) == (8192, 480)
    assert chain.retry_res(last, "node", d) == dataclasses.replace(d, mem_mb=8192)


def test_max_mem_mb_from_config():
    assert chain.max_mem_mb({}) == 65536 and chain.max_mem_mb({"chain_max_mem": "800M"}) == 800
    raw = yaml.safe_load((core.ROOT / "phylocli/config.yaml").read_text())
    assert chain.max_mem_mb(raw) == 65536 and "chain_max_mem" not in raw["params"]


def test_task_results_state_and_exit(cli, monkeypatch):
    monkeypatch.setenv("FAKE_SACCT", "201_0|OUT_OF_MEMORY|4100M|00:03:00|0:125\\n"
                                     "201_1|FAILED|1M|00:00:05|137:0\\n"
                                     "201_[2-3]|PENDING||00:00:00|0:0\\n")
    assert model.task_results(["201"]) == {("201", 0): ("OUT_OF_MEMORY", "125"),
                                           ("201", 1): ("FAILED", "137"),
                                           ("201", 2): ("PENDING", "-"),
                                           ("201", 3): ("PENDING", "-")}
    assert model.task_results([]) == {}


def test_create_initial_records(ch):
    st = _new([A1, C])
    d = Path(st["dir"])
    assert d.parent == _state["runs"] / "chains" and d.name.endswith("_t")
    assert (d / "config.yaml").is_file() and chain.load(d)["hgs"] == st["hgs"]
    assert {s: r["state"] for s, r in st["hgs"][A1].items()} == {
        "align": "done", "tree": "done", "possvm_prev": "done", "generax": "eligible",
        "gxsup": "blocked", "possvm": "blocked"}
    assert {s: r["state"] for s, r in st["hgs"][C].items()} == {
        "align": "eligible", **{s: "blocked" for s in chain.CHAIN_STAGES[1:]}}
    assert st["hgs"][C]["align"]["since"] == T0
    assert st["status"] == "running" and st["options"]["batch_min"] == 50
    assert "created: 2 HGs" in _log_text(st)


def test_save_is_atomic(ch, monkeypatch):
    st = _new([C])
    p = Path(st["dir"]) / "chain.json"
    before = p.read_text()
    st["status"] = "finished"

    def boom(*_a):
        raise OSError("disk full")
    with monkeypatch.context() as m:
        m.setattr(chain.os, "replace", boom)
        with pytest.raises(OSError):
            chain.save(st)
    assert p.read_text() == before and json.loads(before)["status"] == "running"
    chain.save(st)
    assert chain.load(st["dir"])["status"] == "finished"


def test_load_errors(ch, tmp_path):
    with pytest.raises(model.ModelError) as e:
        chain.load(tmp_path / "nope")
    assert e.value.code == 1
    st = _new([C])
    p = Path(st["dir"]) / "chain.json"
    p.write_text(json.dumps({**json.loads(p.read_text()), "version": 99}))
    with pytest.raises(model.ModelError, match="version"):
        chain.load(st["dir"])
```

- [ ] **Step 2: Run to verify they fail** — `python3 -m pytest phylocli/tests/test_chain.py -q -p no:cacheprovider` — Expected: collection error `ImportError: cannot import name 'chain' from 'phylocli'`.

- [ ] **Step 3: Implement** — append to `phylocli/model.py` (at the end of the file):

```python
def task_results(job_ids: list[str]) -> dict | None:
    """{(array job id, task index): (SLURM state, exit code)} from one sacct call (the same parse
    `status HG` uses); exit is '-' when sacct has none yet. None when sacct is missing or failed:
    the chain driver then keeps waiting."""
    recs = history._sacct(job_ids)
    if recs is None:
        return None
    return {k: (v["state"], history._exit(v["exit"]) if v["exit"] else "-")
            for k, v in recs.items()}
```

In `phylocli/config.yaml`, directly below the line `qos: normal`, add:

```yaml
chain_max_mem: 64G   # phylo chain: a retry needing more memory stops as failed:cap (top level: params: go to the stage scripts)
```

Create `phylocli/chain.py`:

```python
"""phylo chain: take HGs through the step2 stages end to end with one driver job, retrying
resource failures with more resources (spec: docs/superpowers/specs/2026-10-09-phylocli-chains-design.md).

The driver (`phylo _chain <dir>`, SLURM job `phylo-chain`) loops: _chain_step(state, now) reads the
output files and sacct, retries / stops / advances HGs and submits stage arrays through
model.select -> plan -> write_run -> sbatch_all; then it sleeps poll_s. Everything it knows is in
<dir>/chain.json (written atomically); its log is <dir>/driver.log. HG stages only: the step1
family stages (search, cluster) are out of scope."""
from __future__ import annotations

import collections
import dataclasses
import json
import os
import re
import shutil
import time
import types
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from phylocli import core, history, model
from phylocli.common import FAILED_STATES, ROOT, fmt_mem, fmt_time, runs_dir

CHAIN_STAGES = ("align", "tree", "possvm_prev", "generax", "gxsup", "possvm")   # = core.HG_STAGES
PARENTS = {"align": (), "tree": ("align",), "possvm_prev": ("tree",), "generax": ("tree",),
           "gxsup": ("generax",), "possvm": ("gxsup",)}
QOS_MAXWALL = (("normal", 720), ("long", 1440), ("vlong", 2880))   # minutes; sacctmgr 09/10/2026
NODE_STATES = {"NODE_FAIL", "PREEMPTED", "BOOT_FAIL"}
TERMINAL = FAILED_STATES | {"COMPLETED"}
ACTIVE = ("blocked", "eligible", "queued", "external")
DEFAULTS = {"attempts": 3, "max_mem_mb": 65536, "batch_min": 50, "batch_wait_s": 300,
            "poll_s": 60, "max_running": 50, "no_output_grace_s": 600}
DEFAULT_MAX_MEM = "64G"
DRIVER_TIME_MIN = 1440      # qos long = 1 day
HANDOVER_S = 1800           # the successor is queued 30 min before the driver's own limit
STATE_VERSION = 1


# ---- stage graph ---------------------------------------------------------------------------

def parents(cfg: core.Config, stage: str) -> list[str]:
    """The applicable stages whose output `stage` reads. A stage that does not run under this
    config is skipped over: possvm reads generax's tree when gxsup is off, tree's without GeneRax."""
    out: list[str] = []
    for p in PARENTS[stage]:
        out.extend([p] if core.applicable(cfg, p) else parents(cfg, p))
    return out


def stage_slice(cfg: core.Config, from_: str | None = None, to: str = "possvm") -> list[str]:
    """Applicable chain stages from `from_` (default: the first) to `to`, in pipeline order."""
    for s in (from_, to):
        if s is not None and s not in CHAIN_STAGES:
            raise model.ModelError(f"chains run the HG stages only ({', '.join(CHAIN_STAGES)}); "
                                   f"got {s!r}", 2)
    for flag, s in (("--from", from_), ("--to", to)):
        if s is not None and not core.applicable(cfg, s):
            raise model.ModelError(f"{flag} {s}: stage does not run with run_generax="
                                   f"{cfg.params.get('run_generax')}, gxsup={cfg.params.get('gxsup')}",
                                   2)
    lo = CHAIN_STAGES.index(from_) if from_ else 0
    hi = CHAIN_STAGES.index(to)
    if lo > hi:
        raise model.ModelError(f"--from {from_} comes after --to {to}", 2)
    return [s for s in CHAIN_STAGES[lo:hi + 1] if core.applicable(cfg, s)]


# ---- resources -----------------------------------------------------------------------------

def qos_for(minutes: int, floor: str = "normal") -> str | None:
    """Smallest qos whose max wall time holds `minutes`, never below `floor`; None if none does."""
    names = [q for q, _ in QOS_MAXWALL]
    start = names.index(floor) if floor in names else 0
    for q, limit in QOS_MAXWALL[start:]:
        if minutes <= limit:
            return q
    return None


def fit(res: core.Res, max_mem_mb: int) -> tuple[core.Res | None, str]:
    """(res with the qos its time needs, "") or (None, why) when it is over the chain's caps."""
    q = qos_for(res.time_min, res.qos)
    if q is None:
        name, limit = QOS_MAXWALL[-1]
        return None, f"time {fmt_time(res.time_min)} > {fmt_time(limit)} ({name})"
    if res.mem_mb > max_mem_mb:
        return None, f"memory {fmt_mem(res.mem_mb)} > chain_max_mem {fmt_mem(max_mem_mb)}"
    return dataclasses.replace(res, qos=q), ""


def classify(state: str, exit_: str) -> str | None:
    """'oom' / 'time' / 'node' for a resource failure the chain retries; None for anything else
    (exit 1, 65 no output, 10 GeneRax parse error, CANCELLED, ...: deterministic or deliberate)."""
    if state == "OUT_OF_MEMORY" or exit_ == "137":
        return "oom"
    if state == "TIMEOUT" or exit_ == "140":
        return "time"
    if state in NODE_STATES:
        return "node"
    return None


def retry_res(last: dict, kind: str, default: core.Res) -> core.Res:
    """Resources of the next attempt: model.bump() of the last request (OOM -> memory x2,
    time -> time x2, node -> unchanged), never below the step2 default `default`."""
    att = types.SimpleNamespace(
        status={"oom": "OUT_OF_MEMORY", "time": "TIMEOUT"}.get(kind, "NODE_FAIL"), exit="-",
        mem=f"{last['mem_mb']}M", time=f"{last['time_min']}m")
    return model.bump(att, default)


def max_mem_mb(raw: dict) -> int:
    return core.parse_mem_mb(str(raw.get("chain_max_mem") or DEFAULT_MAX_MEM))


# ---- state file ----------------------------------------------------------------------------

def chains_dir() -> Path:
    return runs_dir() / "chains"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "chain"


def new_chain_dir(name: str, now: float) -> Path:
    base = chains_dir() / f"{datetime.fromtimestamp(now):%Y%m%d-%H%M%S}_{_safe(name)}"
    d, k = base, 1
    while True:
        try:
            d.mkdir(parents=True)
            return d
        except FileExistsError:
            k += 1
            d = base.with_name(f"{base.name}-{k}")


def _rec(state: str) -> dict:
    return {"state": state, "reason": "", "note": "", "attempt": 1, "res": None, "since": None,
            "job": None, "task": None, "completed_at": None, "attempts": []}


def _stop(r: dict, reason: str, note: str = "") -> None:
    r.update(state="failed", reason=reason, note=note)


def label(r: dict) -> str:
    return f"failed:{r['reason']}" if r["state"] == "failed" else r["state"]


def summary(state: dict) -> dict:
    """{stage: {label: n HGs}}, e.g. {"tree": {"done": 40, "failed:oom": 2}}."""
    out = {}
    for st in state["stages"]:
        c = collections.Counter(label(recs[st]) for recs in state["hgs"].values())
        out[st] = dict(sorted(c.items()))
    return out


def _promote(state: dict, cfg: core.Config, now: float) -> None:
    """blocked -> eligible once every tracked parent is done; -> failed:upstream once one is
    stopped. Stages are visited in pipeline order, so a stop reaches every later stage in one pass.
    Parents before --from are not tracked and count as satisfied."""
    for recs in state["hgs"].values():
        for st in state["stages"]:
            r = recs[st]
            if r["state"] != "blocked":
                continue
            ps = [p for p in parents(cfg, st) if p in recs]
            if any(recs[p]["state"] == "failed" for p in ps):
                _stop(r, "upstream")
            elif all(recs[p]["state"] == "done" for p in ps):
                r.update(state="eligible", since=now)


def new_state(cfg: core.Config, hgs, stages: list, opts: dict, d: Path, name: str,
              now: float) -> dict:
    """Per HG and stage: done (output exists), eligible (every tracked parent done) or blocked."""
    done = core.report_status.done_by_stage(str(cfg.outdir), set(hgs))
    state = {"version": STATE_VERSION, "dir": str(d), "name": name, "created": now,
             "status": "running", "stages": list(stages), "options": {**DEFAULTS, **opts},
             "driver": {}, "jobs": [], "summary": {},
             "hgs": {hg: {st: _rec("done" if hg in done[st] else "blocked") for st in stages}
                     for hg in sorted(hgs)}}
    _promote(state, cfg, now)
    return state


def _log(state: dict, now: float, msg: str) -> None:
    with open(Path(state["dir"]) / "driver.log", "a") as fh:
        fh.write(f"{datetime.fromtimestamp(now):%Y-%m-%d %H:%M:%S} {msg}\n")


def create(cfg: core.Config, raw: dict, hgs, stages: list, opts: dict, name: str,
           now: float) -> dict:
    """New chain dir with config.yaml (the config copy every array of the chain is built from)
    and chain.json. Submits nothing."""
    d = new_chain_dir(name, now)
    (d / "config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    state = new_state(cfg, hgs, stages, opts, d, name, now)
    save(state)
    _log(state, now, f"created: {len(state['hgs'])} HGs, stages {' '.join(stages)}")
    return state


def _cancelled(d) -> bool:
    return (Path(d) / "cancelled").exists()


def _mark_cancelled(state: dict) -> None:
    state["status"] = "cancelled"
    for recs in state["hgs"].values():
        for r in recs.values():
            if r["state"] in ACTIVE:
                _stop(r, "cancelled")
    state["summary"] = summary(state)


def save(state: dict) -> None:
    """Atomic: chain.json.tmp, fsync, rename over chain.json. Once the `cancelled` marker exists,
    a running state is saved as cancelled (a driver mid-step must not resurrect the chain)."""
    d = Path(state["dir"])
    if state["status"] == "running" and _cancelled(d):
        _mark_cancelled(state)
    tmp = d / "chain.json.tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, d / "chain.json")


def load(d) -> dict:
    p = Path(d) / "chain.json"
    if not p.is_file():
        raise model.ModelError(f"no chain at {d} (no chain.json)", 1)
    state = json.loads(p.read_text())
    if state.get("version") != STATE_VERSION:
        raise model.ModelError(f"{p}: unknown chain.json version {state.get('version')!r}", 1)
    state["dir"] = str(Path(d))                 # the dir as seen from here (mounts)
    if state["status"] == "running" and _cancelled(d):
        _mark_cancelled(state)
    return state


def resolve(arg: str) -> Path:
    """A chain given as its dir or as its name under runs/chains/."""
    for p in (Path(arg), chains_dir() / str(arg)):
        if (p / "chain.json").is_file():
            return p
    raise model.ModelError(f"no chain at {arg} (looked in . and {chains_dir()})", 1)
```

(`shutil`, `time` and `dataclass` are used from Task 2 on; keep the imports.)

- [ ] **Step 4: Run to verify they pass** — `python3 -m pytest phylocli/tests/test_chain.py -q -p no:cacheprovider` — Expected: PASS (24 tests). Then both full suites — Expected: baseline **+24**, no failures.

- [ ] **Step 5: Commit**

```bash
git add phylocli/chain.py phylocli/model.py phylocli/config.yaml phylocli/tests/test_chain.py
git commit -m "phylocli chain: stage graph, qos fit and caps, atomic chain.json; model.task_results

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `_chain_step` — advancing, batching, submitting through `model.select`

**Files:**
- Modify: `phylocli/chain.py` (append)
- Test: `phylocli/tests/test_chain.py` (append)

**Interfaces:**
- Consumes: Task 1 (`create`, `save`, `load`, `_promote`, `_stop`, `_log`, `_cancelled`, `_mark_cancelled`, `summary`, `fit`, `ACTIVE`), `model.select(cfg, stage, hgs)` (→ `Selection(selected, notes, queued)`; ModelError when squeue fails), `model.plan(cfg, stage, sel, per_hg=…)` (→ `Plan(stage, groups, notes, errors)`), `model.write_run(cfg, raw, p, dry_run=False, max_running=…)` (→ `Written(run_dir, arrays=[(res, ids, ids_file, script)])`), `model.sbatch_all(w)` (→ `(job ids, err | None)`), `model.live(expected)`, `model.show`, `core.resources`, `core.load_resources_tsv`.
- Produces:
  - `_chain_step(state: dict, now: float) -> dict` (this task's version; Task 3 replaces its body)
  - `_load_cfg(state) -> (Config, raw dict)`, `_mark_done(state, done, now)`, `_check_external(state, now)`, `_flush(state, cfg, raw, stage, now)`, `_submit(state, cfg, raw, stage, hgs, now, again=True)`, `_maybe_finish(state, now)`
  - after a submission a record holds `state="queued"`, `job`, `task` and `attempts[-1] = {"attempt", "job", "task", "run", "cpus", "mem_mb", "time_min", "qos", "end": None, "exit": None}`; `state["jobs"]` lists every array job id the chain submitted
  - on finishing: `state["status"] = "finished"`, `state["finished"]`, `state["summary"]`

- [ ] **Step 1: Write the failing tests** (append to `test_chain.py`):

```python
def _calls():
    p = _state["bin"] / "calls.txt"
    return p.read_text().splitlines() if p.exists() else []


def _submitted(stage=None):
    """[(stage, script text)] of the array scripts sbatch'ed so far, in order."""
    out = []
    for line in _calls():
        s = Path(line.split()[-1])
        if s.name.startswith("array_"):
            st = history.RUN_RE.match(s.parent.name).group(7)
            if stage in (None, st):
                out.append((st, s.read_text()))
    return out


PUBLISHED = {"align": ["align/{}.aln.fasta"],
             "tree": ["gene_trees/{}.treefile", "gene_trees/{}.log"],
             "possvm_prev": ["possvm_prev/{}.treefile.ortholog_groups.csv"],
             "generax": ["generax/{}.generax.tree"],
             "gxsup": ["generax_support/{}.generax.support.tree"],
             "possvm": ["possvm/{}.generax.support.tree.ortholog_groups.csv"]}


def _publish(stage, hg):
    """What a finished stage leaves in the outdir (non-empty: report_status counts it done)."""
    for f in PUBLISHED[stage]:
        p = _cfg().outdir / f.format(hg)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n")


def _states(st, hg):
    return {s: r["state"] for s, r in st["hgs"][hg].items()}


def test_step_submits_the_eligible_stage(ch):
    st = chain._chain_step(_new([C]), T0)
    r = st["hgs"][C]["align"]
    assert (r["state"], r["job"], r["task"], r["attempt"]) == ("queued", "101", 0, 1)
    assert st["jobs"] == ["101"] and r["attempts"][0]["mem_mb"] == 4096
    [(stage, text)] = _submitted()
    assert stage == "align" and "#SBATCH --mem=4096M" in text and "#SBATCH --qos=normal" in text
    run = next(_state["runs"].glob("*_align"))
    assert (run / "jobs.tsv").read_text().startswith("101\t")     # live() and `jobs` see it
    assert chain.load(st["dir"])["hgs"] == st["hgs"]                # saved
    assert "align: submitted 101" in _log_text(st)
    chain._chain_step(st, T0 + 60)
    assert len(_submitted()) == 1                                   # queued: not submitted again


def test_next_stage_only_after_output(ch):
    st = chain._chain_step(_new([C]), T0)
    st = chain._chain_step(st, T0 + 60)
    assert _states(st, C)["tree"] == "blocked" and len(_submitted()) == 1
    _publish("align", C)
    st = chain._chain_step(st, T0 + 120)
    assert _states(st, C)["align"] == "done" and _states(st, C)["tree"] == "queued"
    assert [s for s, _t in _submitted()] == ["align", "tree"]
    assert "#SBATCH --qos=long" in _submitted("tree")[0][1]          # 600 seqs


def test_possvm_prev_and_generax_both_follow_tree(ch):
    _publish("align", C)
    _publish("tree", C)
    st = chain._chain_step(_new([C]), T0)
    assert sorted(s for s, _t in _submitted()) == ["generax", "possvm_prev"]
    assert _states(st, C)["gxsup"] == "blocked" and _states(st, C)["possvm"] == "blocked"


def test_first_attempts_wait_for_a_batch(ch):
    st = chain._chain_step(_new([A1, C]), T0)        # A1 eligible at generax; C's generax blocked
    assert [s for s, _t in _submitted()] == ["align"]
    st = chain._chain_step(st, T0 + 299)
    assert [s for s, _t in _submitted()] == ["align"]
    chain._chain_step(st, T0 + 300)                  # batch_wait_s after A1 became eligible
    assert [s for s, _t in _submitted()] == ["align", "generax"]


def test_batch_min_reached_submits_at_once(ch):
    chain._chain_step(_new([A1, C], batch_min=1), T0)
    assert [s for s, _t in _submitted()] == ["align", "generax"]


def test_hg_queued_elsewhere_is_skipped_then_taken_back(ch, monkeypatch):
    monkeypatch.setenv("FAKE_SQUEUE", "999|nf-ALN_(tfs.C_x.HG1)\n")
    st = chain._chain_step(_new([C]), T0)
    assert _states(st, C)["align"] == "external" and _submitted() == []
    assert "queued outside this chain" in _log_text(st)
    st = chain._chain_step(st, T0 + 60)
    assert _states(st, C)["align"] == "external"
    monkeypatch.setenv("FAKE_SQUEUE", "")
    st = chain._chain_step(st, T0 + 120)             # left the queue without output
    assert _states(st, C)["align"] == "queued" and st["hgs"][C]["align"]["attempt"] == 1
    assert len(_submitted()) == 1


def test_output_present_is_never_resubmitted(ch):
    st = _new([C])                                   # align eligible
    _publish("align", C)                             # finished meanwhile (by hand, Nextflow)
    st = chain._chain_step(st, T0)
    assert _states(st, C)["align"] == "done" and [s for s, _t in _submitted()] == ["tree"]


def test_missing_inputs_stop_the_hg_and_its_later_stages(ch):
    st = chain._chain_step(_new([C], from_="tree"), T0)       # no alignment
    s = st["hgs"][C]
    assert (s["tree"]["state"], s["tree"]["reason"]) == ("failed", "no_inputs")
    assert all((s[x]["state"], s[x]["reason"]) == ("failed", "upstream")
               for x in ("possvm_prev", "generax", "gxsup", "possvm"))
    assert _submitted() == [] and st["status"] == "finished"
    assert st["summary"]["tree"] == {"failed:no_inputs": 1}


def test_finished_chain_writes_summary_and_stops(ch):
    for s in ("generax", "gxsup", "possvm"):
        _publish(s, A1)
    st = chain._chain_step(_new([A1]), T0)
    assert st["status"] == "finished" and st["summary"]["possvm"] == {"done": 1}
    assert "finished:" in _log_text(st)
    before = (Path(st["dir"]) / "chain.json").read_text()
    assert chain._chain_step(st, T0 + 60) is st and _submitted() == []
    assert (Path(st["dir"]) / "chain.json").read_text() == before


def test_attempt1_time_gets_the_qos_it_needs(ch):
    _publish("align", H11)                           # resources.tsv: tree 1140 min, HG at qos normal
    st = chain._chain_step(_new([H11], to="tree"), T0)
    [(stage, text)] = _submitted()
    assert stage == "tree" and "#SBATCH --qos=long" in text and "#SBATCH --time=1140\n" in text
    assert st["hgs"][H11]["tree"]["res"]["qos"] == "long"


def test_attempt1_over_cap_stops_without_submitting(ch):
    st = chain._chain_step(_new([C], max_mem_mb=1000), T0)    # align needs 4096 MB
    r = st["hgs"][C]["align"]
    assert (r["state"], r["reason"]) == ("failed", "cap") and "chain_max_mem" in r["note"]
    assert _submitted() == []


def test_sbatch_failure_keeps_hgs_eligible(ch):
    b = _state["bin"]
    good = (b / "sbatch").read_text()
    (b / "sbatch").write_text("#!/bin/sh\necho 'sbatch: error: QOSMaxSubmitJobPerUserLimit' >&2\nexit 1\n")
    st = chain._chain_step(_new([C]), T0)
    assert _states(st, C)["align"] == "eligible" and st["jobs"] == []
    assert "QOSMaxSubmitJobPerUserLimit" in _log_text(st)
    (b / "sbatch").write_text(good)
    st = chain._chain_step(st, T0 + 60)
    assert _states(st, C)["align"] == "queued"
```

- [ ] **Step 2: Run to verify they fail** — `python3 -m pytest phylocli/tests/test_chain.py -q -p no:cacheprovider` — Expected: the 12 new tests FAIL with `AttributeError: module 'phylocli.chain' has no attribute '_chain_step'`.

- [ ] **Step 3: Implement** (append to `chain.py`):

```python
# ---- one driver step -----------------------------------------------------------------------

def _load_cfg(state: dict) -> tuple[core.Config, dict]:
    raw = yaml.safe_load((Path(state["dir"]) / "config.yaml").read_text())
    return core.config_from_raw(raw), raw


def _mark_done(state: dict, done: dict, now: float) -> None:
    """A record not yet done or stopped whose output now exists is done: output files are the
    truth (a task may still show RUNNING in sacct while its outputs are published)."""
    n = collections.Counter()
    for hg, recs in state["hgs"].items():
        for st, r in recs.items():
            if r["state"] in ACTIVE and hg in done.get(st, set()):
                r["state"] = "done"
                n[st] += 1
    for st, k in n.items():
        _log(state, now, f"{st}: {k} HGs done")


def _check_external(state: dict, now: float) -> None:
    """HGs select() found queued by someone else: eligible again once they left the queue
    without output (an output was already seen by _mark_done)."""
    ext = [(hg, st, r) for hg, recs in state["hgs"].items() for st, r in recs.items()
           if r["state"] == "external"]
    if not ext:
        return
    try:
        lv = model.live(set(state["hgs"]))
    except model.ModelError as e:
        _log(state, now, f"squeue failed ({e}): HGs queued elsewhere are re-checked next poll")
        return
    if lv is None:
        return
    for hg, st, r in ext:
        if hg not in lv.get(st, set()):
            r.update(state="eligible", since=now)
            _log(state, now, f"{st}: {hg} left the queue without output: eligible again")


def _submit(state: dict, cfg: core.Config, raw: dict, stage: str, hgs: list, now: float,
            again: bool = True) -> None:
    """model.select -> plan -> write_run -> sbatch_all for these eligible HGs; every outcome is
    recorded (queued with job/task, external, done, or stopped)."""
    recs = {hg: state["hgs"][hg][stage] for hg in hgs}
    table = core.load_resources_tsv(Path(cfg.params["resources_tsv"]))
    per = {}
    for hg in hgs:
        r = recs[hg]
        if r["res"] is None:                       # attempt 1: step2 default, qos from its time
            res, why = fit(core.resources(cfg, stage, hg, table), state["options"]["max_mem_mb"])
            if res is None:
                _stop(r, "cap", why)
                _log(state, now, f"{stage}: {hg} stopped (cap: {why})")
                continue
            r["res"] = dataclasses.asdict(res)
        per[hg] = {k: r["res"][k] for k in ("cpus", "mem_mb", "time_min", "qos")}
    hgs = [hg for hg in hgs if hg in per]
    if not hgs:
        return
    try:
        sel = model.select(cfg, stage, hgs)
    except model.ModelError as e:
        _log(state, now, f"{stage}: select failed ({e}); {len(hgs)} HGs wait for the next poll")
        return
    for hg in sorted(set(hgs) - set(sel.selected)):
        if hg in sel.queued:
            recs[hg]["state"] = "external"
            _log(state, now, f"{stage}: {hg} is queued outside this chain: skipped, watched")
        else:
            _stop(recs[hg], "no_inputs")
            _log(state, now, f"{stage}: {hg} stopped (inputs missing)")
    if not sel.selected:
        return
    p = model.plan(cfg, stage, sel, per_hg={hg: per[hg] for hg in sel.selected})
    if p.errors:                                   # state moved between select and validate
        for kind, bad in p.errors.items():
            for hg in bad:
                if kind == "output_exists":
                    recs[hg]["state"] = "done"
                elif kind == "queued":
                    recs[hg]["state"] = "external"
                else:
                    _stop(recs[hg], "no_inputs" if kind == "input_missing" else kind)
            _log(state, now, f"{stage}: {kind} ({len(bad)}): {model.show(bad)}")
        left = [hg for hg in sel.selected if recs[hg]["state"] == "eligible"]
        if left and again:
            _submit(state, cfg, raw, stage, left, now, again=False)
        return
    if _cancelled(state["dir"]):
        return
    w = model.write_run(cfg, raw, p, dry_run=False, max_running=state["options"]["max_running"])
    jids, err = model.sbatch_all(w)
    for jid, (res, ids_, _f, _s) in zip(jids, w.arrays):
        state["jobs"].append(jid)
        for i, hg in enumerate(ids_):
            r = recs[hg]
            r.update(state="queued", job=jid, task=i, completed_at=None)
            r["attempts"].append({"attempt": r["attempt"], "job": jid, "task": i,
                                  "run": w.run_dir.name, "cpus": res.cpus, "mem_mb": res.mem_mb,
                                  "time_min": res.time_min, "qos": res.qos, "end": None,
                                  "exit": None})
        _log(state, now, f"{stage}: submitted {jid}: {len(ids_)} HGs ({res.cpus} cpus, "
                         f"{fmt_mem(res.mem_mb)}, {fmt_time(res.time_min)}, {res.qos})")
    if err:
        _log(state, now, f"{stage}: {err}; the HGs not submitted stay eligible")
    save(state)


def _flush(state: dict, cfg: core.Config, raw: dict, stage: str, now: float) -> None:
    """Submit the stage's eligible HGs that are due: retries at once (one batch per poll); first
    attempts when >= batch_min, batch_wait_s after the first became eligible, or when no HG of
    the chain is still blocked at this stage."""
    o = state["options"]
    recs = [(hg, rs[stage]) for hg, rs in sorted(state["hgs"].items()) if stage in rs]
    elig = [(hg, r) for hg, r in recs if r["state"] == "eligible"]
    if not elig:
        return
    retry = [hg for hg, r in elig if r["attempt"] > 1]
    fresh = [(hg, r) for hg, r in elig if r["attempt"] == 1]
    due = bool(fresh) and (len(fresh) >= o["batch_min"]
                           or now - min(r["since"] for _hg, r in fresh) >= o["batch_wait_s"]
                           or not any(r["state"] == "blocked" for _hg, r in recs))
    todo = retry + ([hg for hg, _r in fresh] if due else [])
    if todo:
        _submit(state, cfg, raw, stage, todo, now)


def _maybe_finish(state: dict, now: float) -> None:
    if any(r["state"] in ACTIVE for recs in state["hgs"].values() for r in recs.values()):
        return
    state.update(status="finished", finished=now, summary=summary(state))
    _log(state, now, "finished: " + "; ".join(
        f"{st} " + ", ".join(f"{k} {n}" for k, n in c.items())
        for st, c in state["summary"].items()))


def _chain_step(state: dict, now: float) -> dict:
    """One driver iteration at time `now` (no sleeping, no clock): mark stages done from output
    files, re-check HGs queued by others, unblock next stages, submit what is due, finish when
    nothing is left. Writes chain.json before returning (unless the chain is not running)."""
    if state["status"] == "running" and _cancelled(state["dir"]):
        _mark_cancelled(state)
    if state["status"] != "running":
        return state
    cfg, raw = _load_cfg(state)
    done = core.report_status.done_by_stage(str(cfg.outdir), set(state["hgs"]))
    _mark_done(state, done, now)
    _check_external(state, now)
    _promote(state, cfg, now)
    for st in state["stages"]:
        _flush(state, cfg, raw, st, now)
    _promote(state, cfg, now)                    # a stop in _submit reaches later stages now
    _maybe_finish(state, now)
    save(state)
    return state
```

- [ ] **Step 4: Run to verify they pass** — `python3 -m pytest phylocli/tests/test_chain.py -q -p no:cacheprovider` — Expected: PASS. Both full suites — Expected: Task 1 count **+12**, no failures.

- [ ] **Step 5: Commit**

```bash
git add phylocli/chain.py phylocli/tests/test_chain.py
git commit -m "phylocli chain: _chain_step advances HGs after output, batches arrays, submits via model.select

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: retries from sacct, time-limit handover, the driver loop

**Files:**
- Modify: `phylocli/chain.py` (append new functions; **replace** `_chain_step` from Task 2 with the version below)
- Test: `phylocli/tests/test_chain.py` (append)

**Interfaces:**
- Consumes: Task 2 (`_load_cfg`, `_mark_done`, `_check_external`, `_flush`, `_maybe_finish`), Task 1 (`classify`, `retry_res`, `fit`, `_stop`, `load`, `save`), `model.task_results` (Task 1), `model.squeue(fmt)`, `model._slurm(cmd)`, `history.reason(state, exit)`.
- Produces:
  - `DRIVER_SBATCH` (template), `submit_driver(state, dependency: str | None = None) -> str` (ModelError code 1)
  - `run_driver(d, clock=time.time, sleep=time.sleep, job_id=None, max_steps=None, resumed=False) -> int` (0 = finished / cancelled / handed over / max_steps; 1 = another driver is alive)
  - `_queued_ids() -> set[str] | None` (job ids in `squeue --me`; None without squeue)
  - `_chain_step(state, now) -> dict` (final), `_poll(state, cfg, now)`, `_handover(state, cfg, now) -> bool`
  - `state["driver"]` = `{"job", "started", "limit_min", "successor"}` once a driver runs

- [ ] **Step 1: Write the failing tests** (append to `test_chain.py`):

```python
@pytest.mark.parametrize("line,mem,time_", [
    ("OUT_OF_MEMORY|4100M|00:03:00|0:125", 8192, 240),
    ("FAILED|4100M|00:03:00|137:0", 8192, 240),
    ("TIMEOUT|10M|04:00:00|0:0", 4096, 480),
    ("NODE_FAIL|10M|00:01:00|0:0", 4096, 240)])
def test_resource_failure_is_retried(ch, monkeypatch, line, mem, time_):
    st = chain._chain_step(_new([C]), T0)                           # align -> 101
    monkeypatch.setenv("FAKE_SACCT", f"101_0|{line}\\n")
    st = chain._chain_step(st, T0 + 60)
    r = st["hgs"][C]["align"]
    assert (r["state"], r["attempt"], r["job"]) == ("queued", 2, "102")
    assert (r["res"]["mem_mb"], r["res"]["time_min"]) == (mem, time_)
    assert r["attempts"][0]["end"] == line.split("|")[0]
    _stage, text = _submitted()[-1]
    assert f"#SBATCH --mem={mem}M" in text and f"#SBATCH --time={time_}\n" in text


@pytest.mark.parametrize("line,reason", [
    ("FAILED|1M|00:00:05|1:0", "exit 1"),
    ("FAILED|1M|00:00:05|65:0", "stage produced no output"),
    ("FAILED|1M|00:00:05|10:0", "GeneRax parse error"),
    ("CANCELLED by 1000|1M|00:00:05|0:15", "cancelled")])
def test_other_failures_are_not_retried(ch, monkeypatch, line, reason):
    st = chain._chain_step(_new([C]), T0)
    monkeypatch.setenv("FAKE_SACCT", f"101_0|{line}\\n")
    st = chain._chain_step(st, T0 + 60)
    s = st["hgs"][C]
    assert (s["align"]["state"], s["align"]["reason"]) == ("failed", reason)
    assert s["tree"]["reason"] == "upstream" and len(_submitted()) == 1
    assert st["status"] == "finished" and st["summary"]["align"] == {f"failed:{reason}": 1}


def test_attempts_are_capped(ch, monkeypatch):
    monkeypatch.setenv("FAKE_SACCT", "101_0|OUT_OF_MEMORY|4100M|00:03:00|0:125\\n"
                                     "102_0|OUT_OF_MEMORY|8200M|00:03:00|0:125\\n")
    st = chain._chain_step(_new([C], attempts=2), T0)               # 101
    st = chain._chain_step(st, T0 + 60)                               # OOM -> attempt 2 = 102
    st = chain._chain_step(st, T0 + 120)                              # OOM again: no attempt 3
    r = st["hgs"][C]["align"]
    assert (r["state"], r["reason"], r["attempt"]) == ("failed", "oom", 2)
    assert "after 2 attempts" in r["note"] and len(_submitted()) == 2


def test_retry_over_memory_cap_stops_as_cap(ch, monkeypatch):
    st = chain._chain_step(_new([C], max_mem_mb=6000), T0)
    monkeypatch.setenv("FAKE_SACCT", "101_0|OUT_OF_MEMORY|4100M|00:03:00|0:125\\n")
    st = chain._chain_step(st, T0 + 60)                               # 8192 MB > 6000
    r = st["hgs"][C]["align"]
    assert (r["state"], r["reason"]) == ("failed", "cap") and len(_submitted()) == 1


def test_timeout_escalates_qos_then_caps(ch, monkeypatch):
    _publish("align", H11)
    st = chain._chain_step(_new([H11], to="tree", attempts=5), T0)  # 1140 min, long -> 101
    monkeypatch.setenv("FAKE_SACCT", "101_0|TIMEOUT|10M|19:00:00|0:0\\n")
    st = chain._chain_step(st, T0 + 60)                               # 2280 min -> vlong, 102
    _s, text = _submitted()[-1]
    assert "#SBATCH --qos=vlong" in text and "#SBATCH --time=2280\n" in text
    monkeypatch.setenv("FAKE_SACCT", "102_0|TIMEOUT|10M|38:00:00|0:0\\n")
    st = chain._chain_step(st, T0 + 120)                              # 4560 min: over vlong
    r = st["hgs"][H11]["tree"]
    assert (r["state"], r["reason"]) == ("failed", "cap") and "vlong" in r["note"]


def test_completed_without_output_waits_then_stops(ch, monkeypatch):
    st = chain._chain_step(_new([C]), T0)
    monkeypatch.setenv("FAKE_SACCT", "101_0|COMPLETED|10M|00:01:00|0:0\\n")
    st = chain._chain_step(st, T0 + 60)
    assert _states(st, C)["align"] == "queued"                      # NFS may lag
    st = chain._chain_step(st, T0 + 60 + 599)
    assert _states(st, C)["align"] == "queued"
    st = chain._chain_step(st, T0 + 60 + 600)
    r = st["hgs"][C]["align"]
    assert (r["state"], r["reason"]) == ("failed", "no_output")


def test_completed_output_seen_late_advances(ch, monkeypatch):
    st = chain._chain_step(_new([C]), T0)
    monkeypatch.setenv("FAKE_SACCT", "101_0|COMPLETED|10M|00:01:00|0:0\\n")
    st = chain._chain_step(st, T0 + 60)
    _publish("align", C)
    st = chain._chain_step(st, T0 + 120)
    assert _states(st, C)["align"] == "done" and _states(st, C)["tree"] == "queued"


def test_sacct_unavailable_keeps_waiting(ch, monkeypatch):
    st = chain._chain_step(_new([C]), T0)
    monkeypatch.setattr(model, "task_results", lambda job_ids: None)
    st = chain._chain_step(st, T0 + 3600)
    assert _states(st, C)["align"] == "queued" and "sacct unavailable" in _log_text(st)


def test_successor_submitted_near_time_limit(ch):
    st = _new([C])
    st["driver"] = {"job": "900", "started": T0, "limit_min": 1440, "successor": None}
    limit = T0 + 1440 * 60
    st = chain._chain_step(st, limit - 1801)
    assert st["driver"]["successor"] is None and [s for s, _t in _submitted()] == ["align"]
    st = chain._chain_step(st, limit - 1800)
    assert st["driver"]["successor"] == "102"
    line = _calls()[-1]
    assert "--dependency=afterany:900" in line and line.endswith("driver.sbatch")
    text = (Path(st["dir"]) / "driver.sbatch").read_text()
    for s in ("--job-name=phylo-chain", "--qos=long", "--time=1440", "--mem=500M",
              "--cpus-per-task=1"):
        assert f"#SBATCH {s}" in text
    assert f'_chain "{st["dir"]}" --resume' in text
    st = chain._chain_step(st, limit - 1700)        # handed over: this driver does nothing more
    assert st["driver"]["successor"] == "102" and len(_calls()) == 2


def test_run_driver_steps_without_sleeping(ch):
    st = _new([C])
    clock = iter([T0, T0, T0 + 60, T0 + 120]).__next__
    slept = []
    rc = chain.run_driver(st["dir"], clock=clock, sleep=slept.append, job_id="900", max_steps=3)
    st = chain.load(st["dir"])
    assert rc == 0 and slept == [60, 60]
    assert st["driver"] == {"job": "900", "started": T0, "limit_min": 1440, "successor": None}
    assert st["hgs"][C]["align"]["job"] == "101" and len(_submitted()) == 1


def test_run_driver_does_nothing_for_a_stopped_chain(ch):
    st = _new([C])
    st["status"] = "cancelled"
    chain.save(st)
    assert chain.run_driver(st["dir"], clock=lambda: T0, sleep=lambda s: None, job_id="900") == 0
    assert _calls() == []


def test_second_driver_exits_while_first_is_queued(ch, monkeypatch):
    st = _new([C])
    st["driver"] = {"job": "900"}
    chain.save(st)
    monkeypatch.setenv("FAKE_SQUEUE", "900|phylo-chain\n")

    def no_sleep(_s):
        raise AssertionError("must not loop")
    assert chain.run_driver(st["dir"], clock=lambda: T0, sleep=no_sleep, job_id="901") == 1
    assert _calls() == [] and "another driver (job 900)" in _log_text(st)


def test_resume_from_saved_state_does_not_resubmit(ch):
    st = chain._chain_step(_new([C]), T0)                           # align queued as 101, saved
    _publish("align", C)
    rc = chain.run_driver(st["dir"], clock=iter([T0 + 600, T0 + 600]).__next__,
                          sleep=lambda s: None, job_id="905", max_steps=1, resumed=True)
    st = chain.load(st["dir"])
    assert rc == 0 and [s for s, _t in _submitted()] == ["align", "tree"]
    assert _states(st, C)["align"] == "done" and st["hgs"][C]["tree"]["job"] == "102"
    assert "(resumed)" in _log_text(st)


def test_step_error_is_logged_and_the_driver_goes_on(ch, monkeypatch):
    st = _new([C])
    real, calls = chain._chain_step, []

    def flaky(state, now):
        calls.append(now)
        if len(calls) == 1:
            raise model.ModelError("squeue timed out after 60 s")
        return real(state, now)
    monkeypatch.setattr(chain, "_chain_step", flaky)
    rc = chain.run_driver(st["dir"], clock=iter([T0, T0, T0 + 60]).__next__,
                          sleep=lambda s: None, job_id="900", max_steps=2)
    assert rc == 0 and len(calls) == 2
    assert "step failed" in _log_text(st) and "squeue timed out" in _log_text(st)
    assert chain.load(st["dir"])["hgs"][C]["align"]["state"] == "queued"
```

- [ ] **Step 2: Run to verify they fail** — `python3 -m pytest phylocli/tests/test_chain.py -q -p no:cacheprovider` — Expected: 19 of the 20 new tests FAIL (retries: `AssertionError` — no polling yet; driver tests: `AttributeError: ... 'run_driver'`). `test_completed_output_seen_late_advances` already passes (Task 2's `_mark_done` runs before any poll); it pins that order for the new `_chain_step`.

- [ ] **Step 3: Implement** — append to `chain.py`:

```python
# ---- retries, handover, driver -------------------------------------------------------------

def _poll(state: dict, cfg: core.Config, now: float) -> None:
    """One sacct call for every queued task: retry resource failures (bumped, re-fitted, capped),
    stop everything else; COMPLETED without output waits no_output_grace_s (NFS lag)."""
    queued = [(hg, st, r) for hg, recs in sorted(state["hgs"].items())
              for st, r in recs.items() if r["state"] == "queued"]
    if not queued:
        return
    res = model.task_results(sorted({r["job"] for _hg, _st, r in queued}))
    if res is None:
        _log(state, now, "sacct unavailable: task states not read this poll")
        return
    o = state["options"]
    table = core.load_resources_tsv(Path(cfg.params["resources_tsv"]))
    for hg, st, r in queued:
        s, ex = res.get((r["job"], r["task"]), ("PENDING", "-"))
        if s not in TERMINAL:
            continue
        r["attempts"][-1].update(end=s, exit=ex)
        if s == "COMPLETED":
            if r["completed_at"] is None:
                r["completed_at"] = now
            elif now - r["completed_at"] >= o["no_output_grace_s"]:
                _stop(r, "no_output", f"COMPLETED but no output after {o['no_output_grace_s']} s")
                _log(state, now, f"{st}: {hg} stopped (COMPLETED, no output)")
            continue
        kind = classify(s, ex)
        if kind is None:
            _stop(r, history.reason(s, ex) or s.lower())
            _log(state, now, f"{st}: {hg} stopped ({s}, exit {ex}: not retried)")
            continue
        if r["attempt"] >= o["attempts"]:
            _stop(r, kind, f"after {r['attempt']} attempts")
            _log(state, now, f"{st}: {hg} stopped ({s} after {r['attempt']} attempts)")
            continue
        new, why = fit(retry_res(r["res"], kind, core.resources(cfg, st, hg, table)),
                       o["max_mem_mb"])
        if new is None:
            _stop(r, "cap", why)
            _log(state, now, f"{st}: {hg} stopped (cap: {why})")
            continue
        r.update(state="eligible", attempt=r["attempt"] + 1, res=dataclasses.asdict(new),
                 since=now, job=None, task=None, completed_at=None)
        _log(state, now, f"{st}: {hg} {s} -> attempt {r['attempt']} ({fmt_mem(new.mem_mb)}, "
                         f"{fmt_time(new.time_min)}, {new.qos})")


DRIVER_SBATCH = """#!/usr/bin/env bash
#SBATCH --job-name=phylo-chain
#SBATCH --partition={partition}
#SBATCH --qos=long
#SBATCH --cpus-per-task=1
#SBATCH --mem=500M
#SBATCH --time={time_min}
#SBATCH --output={dir}/driver_%j.out
#SBATCH --error={dir}/driver_%j.err
set -uo pipefail
export PHYLOCLI_CONFIG="{dir}/config.yaml"
export PHYLOCLI_RUNS="{runs}"
python3 "{root}/phylocli/phylo.py" _chain "{dir}" --resume
"""


def submit_driver(state: dict, dependency: str | None = None) -> str:
    """sbatch the driver job (phylo-chain) for this chain; returns its job id."""
    if shutil.which("sbatch") is None:
        raise model.ModelError("sbatch not on PATH: driver not submitted", 1)
    cfg, _raw = _load_cfg(state)
    d = Path(state["dir"])
    script = d / "driver.sbatch"
    script.write_text(DRIVER_SBATCH.format(partition=cfg.partition, time_min=DRIVER_TIME_MIN,
                                           dir=d, runs=runs_dir(), root=ROOT))
    cmd = (["sbatch", "--parsable"]
           + ([f"--dependency=afterany:{dependency}"] if dependency else []) + [str(script)])
    r = model._slurm(cmd)
    jid = r.stdout.strip().split(";")[0]
    if r.returncode != 0 or not jid:
        raise model.ModelError(f"sbatch failed for {script}: {r.stderr.strip()}", 1)
    return jid


def _handover(state: dict, cfg: core.Config, now: float) -> bool:
    """HANDOVER_S before the driver's own time limit, queue its successor (afterany:<own job>)."""
    d = state["driver"]
    if not d.get("job") or not d.get("started") or not d.get("limit_min"):
        return False                                   # not a SLURM job: no time limit
    if now < d["started"] + d["limit_min"] * 60 - HANDOVER_S:
        return False
    try:
        jid = submit_driver(state, dependency=d["job"])
    except model.ModelError as e:
        _log(state, now, f"successor not submitted ({e}); retried next poll")
        return False
    d["successor"] = jid
    _log(state, now, f"time limit near: successor driver {jid} queued (afterany:{d['job']}); exiting")
    return True


def _chain_step(state: dict, now: float) -> dict:
    """One driver iteration at time `now` (no sleeping, no clock): hand over to a successor near
    the time limit; else mark stages done from output files, read sacct for queued tasks (retry /
    stop), re-check HGs queued by others, unblock next stages, submit what is due, finish when
    nothing is left. Writes chain.json before returning (unless the chain is not running)."""
    if state["status"] == "running" and _cancelled(state["dir"]):
        _mark_cancelled(state)
    if state["status"] != "running" or state["driver"].get("successor"):
        return state                                   # handed over: the successor owns it
    cfg, raw = _load_cfg(state)
    if _handover(state, cfg, now):
        save(state)
        return state
    done = core.report_status.done_by_stage(str(cfg.outdir), set(state["hgs"]))
    _mark_done(state, done, now)
    _poll(state, cfg, now)
    _check_external(state, now)
    _promote(state, cfg, now)
    for st in state["stages"]:
        _flush(state, cfg, raw, st, now)
    _promote(state, cfg, now)                    # a stop in _poll / _submit reaches later stages
    _maybe_finish(state, now)
    save(state)
    return state


def _queued_ids() -> set[str] | None:
    """Job ids in `squeue --me` (array tasks folded to their job id); None without squeue."""
    try:
        lines = model.squeue("%i")
    except model.ModelError:
        return None
    if lines is None:
        return None
    return {line.split("|")[0].strip().split("_")[0] for line in lines if line.strip()}


def run_driver(d, clock=time.time, sleep=time.sleep, job_id: str | None = None,
               max_steps: int | None = None, resumed: bool = False) -> int:
    """The driver loop (`phylo _chain DIR`): _chain_step every poll_s until the chain is finished,
    cancelled or handed over. clock / sleep / job_id / max_steps are injected by tests."""
    d = Path(d)
    state = load(d)
    now = clock()
    if state["status"] != "running":
        _log(state, now, f"chain is {state['status']}: driver exits")
        return 0
    job_id = job_id if job_id is not None else os.environ.get("SLURM_JOB_ID")
    prev = state.get("driver") or {}
    others = {j for j in (prev.get("job"), prev.get("successor")) if j and j != job_id}
    q = _queued_ids()
    if q is not None and others & q:
        _log(state, now, f"another driver (job {' '.join(sorted(others & q))}) is still queued "
                         "or running: this one exits")
        return 1
    state["driver"] = {"job": job_id, "started": now,
                       "limit_min": DRIVER_TIME_MIN if job_id else None, "successor": None}
    _log(state, now, f"driver {job_id or '(not a SLURM job)'} started"
                     + (" (resumed)" if resumed else ""))
    save(state)
    steps = 0
    while True:
        state = load(d)                          # picks up --cancel between steps
        if state["status"] != "running":
            return 0
        now = clock()
        try:
            state = _chain_step(state, now)
        except Exception as e:                   # a transient SLURM / NFS error must not end it
            _log(state, now, f"step failed: {e!r}; next try in {state['options']['poll_s']} s")
        if state["status"] != "running" or state["driver"].get("successor"):
            return 0
        steps += 1
        if max_steps is not None and steps >= max_steps:
            return 0
        sleep(state["options"]["poll_s"])
```

Then **delete the Task 2 `_chain_step`** (the one whose docstring starts "One driver iteration at time `now` (no sleeping, no clock): mark stages done") so only the version above remains.

- [ ] **Step 4: Run to verify they pass** — `python3 -m pytest phylocli/tests/test_chain.py -q -p no:cacheprovider` — Expected: PASS, including every Task 2 test. Both full suites — Expected: Task 2 count **+20**, no failures.

- [ ] **Step 5: Commit**

```bash
git add phylocli/chain.py phylocli/tests/test_chain.py
git commit -m "phylocli chain: sacct retries (OOM mem x2, time x2 with qos escalation, caps), handover, driver loop

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `phylo chain` (plan / confirm / driver, `--status`, `--cancel`, `--resume`) and hidden `_chain`

**Files:**
- Modify: `phylocli/chain.py` (append), `phylocli/phylo.py` (import + two commands, placed after `_run` and before `if __name__ == "__main__":`), `phylocli/README.md` (new section after `## Typical loop`)
- Test: `phylocli/tests/test_chain.py` (append)

**Interfaces:**
- Consumes: Tasks 1–3 (`stage_slice`, `fit`, `max_mem_mb`, `create`, `load`, `save`, `resolve`, `submit_driver`, `run_driver`, `_queued_ids`, `_mark_cancelled`, `_log`, `ACTIVE`), `core.expected`, `core.read_ids`, `core.filter_fam`, `core.resources`, `model.preflight(stage)`, `model.group_key(hg, "family")`, `model._slurm`, phylo.py's `_cfg`-style raw loading, `_fail`, `_guard`, `_show`, `FAM_HELP`.
- Produces (used by Task 5):
  - `@dataclass ChainPlan: hgs: list; stages: list; start: dict; done: int; resources: list` — `resources` = `[(stage, Res | None, n HGs)]`, `None` = over the caps
  - `prepare(cfg, hgs, stages, max_mem_mb) -> ChainPlan`; `plan_lines(p, attempts, max_mem_mb) -> list[str]`
  - `default_name(hgs, fam=None) -> str`
  - `start(state, now, new=False) -> str` (driver job id; with `new=True` a failed sbatch marks the chain cancelled)
  - `cancel(state, now) -> list[str]` (the scancelled job ids); `check_no_driver(state)` (ModelError code 1)
  - `hg_counts(state) -> Counter` (`done` / `failed` / `running` / `pending` per HG); `stage_counts(state) -> {stage: Counter}` (`done` / `running` / `pending` / `retrying` / `stopped`); `state_word(state, queued) -> str`; `status_text(arg=None, limit=10) -> str`
  - CLI: `phylo chain HGS... | --ids FILE | -f FAM | --missing [--from S] [--to S] [--attempts N] [--name N] [-n]`, `phylo chain --status [CHAIN]`, `--cancel CHAIN`, `--resume CHAIN`; hidden `phylo _chain DIR [--resume]` (exit = `run_driver`'s return)

- [ ] **Step 1: Write the failing tests** (append to `test_chain.py`):

```python
def _invoke(args, inp=None):
    return CliRunner().invoke(cli_mod.app, args, input=inp)


def _create_cli(*args):
    r = _invoke(["chain", *args], "y\n")
    assert r.exit_code == 0, r.output
    return next((_state["runs"] / "chains").iterdir())


def test_chain_dry_run_prints_the_plan(ch):
    r = _invoke(["chain", "-n", A1, C])
    assert r.exit_code == 0, r.output
    rows = [l.split() for l in r.output.splitlines()]
    assert ["align", "1"] in rows and ["generax", "1"] in rows        # start stage per HG
    assert ["tree", "1", "4", "300", "MB", "30m", "long"] in rows     # C: 600 seqs -> qos long
    assert "chain · 2 HGs · align → possvm · up to 3 attempts" in r.output
    assert "nothing submitted (dry run)" in r.output
    assert _calls() == [] and not (_state["runs"] / "chains").exists()


def test_chain_submits_only_the_driver(ch):
    d = _create_cli(C, A1)
    calls = _calls()
    assert len(calls) == 1 and calls[0].endswith("driver.sbatch") and "--dependency" not in calls[0]
    st = chain.load(d)
    assert st["driver"]["job"] == "101" and sorted(st["hgs"]) == [A1, C]
    assert st["options"]["attempts"] == 3 and st["options"]["max_mem_mb"] == 65536
    assert d.name.endswith("_chain")                   # two families -> default name 'chain'
    assert "driver 101" in _log_text(st)


def test_chain_declined_submits_nothing(ch):
    r = _invoke(["chain", C], "n\n")
    assert r.exit_code == 0 and "nothing submitted" in r.output
    assert _calls() == [] and not (_state["runs"] / "chains").exists()


def test_chain_selection_errors(ch):
    assert _invoke(["chain"]).exit_code == 2
    assert _invoke(["chain", "--missing", C]).exit_code == 2
    r = _invoke(["chain", "-n", "tfs.Z.HG9"])
    assert r.exit_code == 2 and "unknown (1)" in r.output
    r = _invoke(["chain", "-n", "-f", "tfs.C"])
    assert r.exit_code == 1 and "no HGs match" in r.output
    r = _invoke(["chain", "-n", C, "--from", "generax", "--to", "tree"])
    assert r.exit_code == 2 and "comes after" in r.output
    r = _invoke(["chain", "-n", C, "--to", "search"])
    assert r.exit_code == 2 and "HG stages only" in r.output
    assert _invoke(["chain", "--status", "--cancel"]).exit_code == 2
    assert _calls() == []


def test_chain_missing_means_not_done_at_to(ch):
    r = _invoke(["chain", "-n", "--missing", "--to", "tree"])
    assert r.exit_code == 0 and "chain · 2 HGs · align → tree" in r.output   # A1 has its tree


def test_chain_status(ch, monkeypatch):
    d = _create_cli(C, A1)
    r = _invoke(["chain", "--status"])
    assert r.exit_code == 0 and d.name in r.output and "stalled" in r.output   # 101 not in squeue
    assert "0/2 HGs done" in r.output
    monkeypatch.setenv("FAKE_SQUEUE", "101|phylo-chain\n")
    assert "running" in _invoke(["chain", "--status"]).output
    out = _invoke(["chain", "--status", d.name]).output
    rows = {l.split()[0]: l.split()[1:] for l in out.splitlines()
            if l.split() and l.split()[0] in chain.CHAIN_STAGES}
    assert rows["align"] == ["1", "0", "1", "0", "0"]      # done running pending retrying stopped
    assert rows["generax"] == ["0", "0", "2", "0", "0"]


def test_chain_status_lists_stopped_hgs(ch):
    d = _create_cli(C, "--from", "tree")
    chain._chain_step(chain.load(d), T0)                    # no alignment: stopped
    out = _invoke(["chain", "--status", str(d)]).output
    assert "finished" in out and "tfs.C_x.HG1  tree  failed:no_inputs" in out
    assert "(+4 later stages stopped upstream)" in out


def test_chain_cancel(ch):
    d = _create_cli(C)                                      # driver 101
    chain._chain_step(chain.load(d), T0)                    # align array 102
    r = _invoke(["chain", "--cancel", d.name], "y\n")
    assert r.exit_code == 0 and "scancel 101 102" in r.output
    assert (_state["bin"] / "scancel.txt").read_text().split() == ["101", "102"]
    st = chain.load(d)
    assert st["status"] == "cancelled" and st["hgs"][C]["align"]["reason"] == "cancelled"
    assert (d / "cancelled").is_file()
    r = _invoke(["chain", "--cancel", d.name], "y\n")
    assert r.exit_code == 1 and "nothing to cancel" in r.output


def test_cancel_wins_over_a_driver_mid_step(ch):
    st = _new([C])
    stale = json.loads(json.dumps(st))                      # what a running driver holds
    chain.cancel(chain.load(st["dir"]), T0)
    out = chain._chain_step(stale, T0 + 60)                 # the driver's next step
    assert out["status"] == "cancelled" and _submitted() == []
    stale["status"] = "running"
    chain.save(stale)                                       # a save that was already under way
    assert chain.load(st["dir"])["status"] == "cancelled"


def test_chain_resume(ch, monkeypatch):
    d = _create_cli(C)                                      # driver 101
    monkeypatch.setenv("FAKE_SQUEUE", "101|phylo-chain\n")
    r = _invoke(["chain", "--resume", d.name], "y\n")
    assert r.exit_code == 1 and "still queued or running" in r.output and len(_calls()) == 1
    monkeypatch.setenv("FAKE_SQUEUE", "")
    r = _invoke(["chain", "--resume", d.name], "y\n")
    assert r.exit_code == 0 and chain.load(d)["driver"]["job"] == "102"


def test_hidden_chain_command(ch):
    st = _new([C])
    st["status"] = "finished"
    chain.save(st)
    r = _invoke(["_chain", st["dir"], "--resume"])
    assert r.exit_code == 0 and _calls() == []
    help_ = _invoke(["--help"]).output
    assert "chain" in help_ and "_chain" not in help_
```

- [ ] **Step 2: Run to verify they fail** — `python3 -m pytest phylocli/tests/test_chain.py -q -p no:cacheprovider` — Expected: the 11 new tests FAIL (`No such command 'chain'`, exit code 2, or `AttributeError: ... 'cancel'`).

- [ ] **Step 3: Implement** — append to `chain.py`:

```python
# ---- CLI / TUI helpers ---------------------------------------------------------------------

@dataclass
class ChainPlan:
    hgs: list
    stages: list
    start: dict          # stage -> n HGs whose first not-done stage it is
    done: int            # HGs with nothing left to do
    resources: list      # (stage, attempt-1 Res fitted to a qos, or None = over the caps, n HGs)


def prepare(cfg: core.Config, hgs, stages: list, max_mem_mb: int) -> ChainPlan:
    """The dry-run plan of a chain: where each HG starts and the attempt-1 resources per stage."""
    done = core.report_status.done_by_stage(str(cfg.outdir), set(hgs))
    table = core.load_resources_tsv(Path(cfg.params["resources_tsv"]))
    start: collections.Counter = collections.Counter()
    groups: collections.Counter = collections.Counter()
    nothing = 0
    for hg in sorted(hgs):
        todo = [st for st in stages if hg not in done[st]]
        if not todo:
            nothing += 1
            continue
        start[todo[0]] += 1
        for st in todo:
            res, _why = fit(core.resources(cfg, st, hg, table), max_mem_mb)
            groups[(st, res)] += 1
    rows = sorted(groups.items(), key=lambda kv: (stages.index(kv[0][0]), kv[0][1] is None,
                                                  str(kv[0][1])))
    return ChainPlan(sorted(hgs), list(stages), dict(start), nothing,
                     [(st, res, n) for (st, res), n in rows])


def plan_lines(p: ChainPlan, attempts: int, max_mem_mb: int) -> list[str]:
    lines = [f"chain · {len(p.hgs)} HGs · {p.stages[0]} → {p.stages[-1]} · up to {attempts} "
             f"attempts · memory cap {fmt_mem(max_mem_mb)}",
             f"{'start stage':<14} {'HGs':>5}"]
    lines += [f"{st:<14} {p.start[st]:>5}" for st in p.stages if p.start.get(st)]
    if p.done:
        lines.append(f"{'nothing to do':<14} {p.done:>5}")
    lines.append(f"{'stage':<14} {'HGs':>5} {'cpus':>4} {'memory':>8} {'time':>7}  qos (attempt 1)")
    for st, res, n in p.resources:
        if res is None:
            lines.append(f"{st:<14} {n:>5}  over the caps: stops as failed:cap")
        else:
            lines.append(f"{st:<14} {n:>5} {res.cpus:>4} {fmt_mem(res.mem_mb):>8} "
                         f"{fmt_time(res.time_min):>7}  {res.qos}")
    return lines


def default_name(hgs, fam: str | None = None) -> str:
    if fam:
        return fam
    fams = {model.group_key(hg, "family") for hg in hgs}
    return fams.pop() if len(fams) == 1 else "chain"


def start(state: dict, now: float, new: bool = False) -> str:
    """Submit a driver for this chain and record it. `new`: a chain nobody drives yet, marked
    cancelled when the sbatch fails (so it is not listed as stalled forever)."""
    try:
        jid = submit_driver(state)
    except model.ModelError as e:
        if new:
            state.update(status="cancelled", note=f"driver not submitted: {e}")
            save(state)
        _log(state, now, f"driver not submitted: {e}")
        raise
    state["driver"] = {"job": jid, "submitted": now}
    _log(state, now, f"driver {jid} submitted")
    save(state)
    return jid


def check_no_driver(state: dict) -> None:
    q = _queued_ids()
    if q is None:
        raise model.ModelError("squeue not on PATH: cannot check for a running driver", 1)
    d = state["driver"]
    alive = [j for j in (d.get("job"), d.get("successor")) if j and j in q]
    if alive:
        raise model.ModelError(f"driver {alive[0]} of chain {state['name']} is still queued or "
                               "running: nothing submitted", 1)


def cancel(state: dict, now: float) -> list[str]:
    """scancel the driver, its successor and the chain's queued arrays; mark the chain cancelled.
    The `cancelled` marker is written first, so a driver mid-step can no longer save 'running'."""
    d = state["driver"]
    ids = [j for j in (d.get("job"), d.get("successor")) if j]
    ids += sorted({r["job"] for recs in state["hgs"].values() for r in recs.values()
                   if r["state"] == "queued" and r["job"]})
    if ids and shutil.which("scancel") is None:
        raise model.ModelError("scancel not on PATH: nothing cancelled", 1)
    (Path(state["dir"]) / "cancelled").write_text(f"{now}\n")
    if ids:
        try:
            r = model._slurm(["scancel", *ids])
            if r.returncode != 0:
                _log(state, now, f"scancel: {r.stderr.strip()}")
        except model.ModelError as e:
            _log(state, now, str(e))
    _mark_cancelled(state)
    _log(state, now, "cancelled" + (f": scancel {' '.join(ids)}" if ids else ""))
    save(state)
    return ids


def hg_counts(state: dict) -> collections.Counter:
    """Per HG: done (every stage done), failed (a stage stopped), running (a task queued, here or
    elsewhere), else pending."""
    c: collections.Counter = collections.Counter()
    for recs in state["hgs"].values():
        ss = [r["state"] for r in recs.values()]
        c["done" if all(s == "done" for s in ss) else "failed" if "failed" in ss
          else "running" if any(s in ("queued", "external") for s in ss) else "pending"] += 1
    return c


def _bucket(r: dict) -> str:
    if r["state"] == "done":
        return "done"
    if r["state"] == "failed":
        return "stopped"
    if r["attempt"] > 1:
        return "retrying"
    return "running" if r["state"] in ("queued", "external") else "pending"


def stage_counts(state: dict) -> dict:
    return {st: collections.Counter(_bucket(recs[st]) for recs in state["hgs"].values())
            for st in state["stages"]}


def state_word(state: dict, queued: set | None) -> str:
    """running / finished / cancelled, or stalled: running, but neither the driver nor its
    successor is in squeue (resume it)."""
    if state["status"] != "running":
        return state["status"]
    d = state["driver"]
    jobs = [j for j in (d.get("job"), d.get("successor")) if j]
    if queued is not None and not any(j in queued for j in jobs):
        return "stalled"
    return "running"


def _err_log(stage: str, r: dict) -> str:
    if not r["attempts"]:
        return ""
    a = r["attempts"][-1]
    return str(runs_dir() / a["run"] / "logs" / f"{stage}_{a['job']}_{a['task']}.err")


def status_text(arg: str | None = None, limit: int = 10) -> str:
    """`phylo chain --status [CHAIN]`: the newest chains one line each, or one chain in detail."""
    queued = _queued_ids()
    if arg is None:
        files = sorted(chains_dir().glob("*/chain.json"), key=lambda p: p.parent.name,
                       reverse=True)[:limit]
        if not files:
            return f"no chains in {chains_dir()}"
        lines = []
        for f in files:
            st = load(f.parent)
            c = hg_counts(st)
            lines.append(f"{f.parent.name}  {state_word(st, queued)}  driver "
                         f"{st['driver'].get('job') or '-'}  {c['done']}/{len(st['hgs'])} HGs done"
                         f"  {c['failed']} stopped")
        return "\n".join(lines)
    st = load(resolve(arg))
    word, d = state_word(st, queued), st["driver"]
    lines = [f"chain {st['name']} · {word} · driver {d.get('job') or '-'}"
             + (f" → successor {d['successor']}" if d.get("successor") else ""),
             f"dir {st['dir']}"]
    if word == "stalled":
        lines.append(f"the driver is not in squeue: phylo chain --resume {Path(st['dir']).name}")
    lines.append(f"{'stage':<12} {'done':>6} {'running':>8} {'pending':>8} {'retrying':>9} "
                 f"{'stopped':>8}")
    for s, c in stage_counts(st).items():
        lines.append(f"{s:<12} {c['done']:>6} {c['running']:>8} {c['pending']:>8} "
                     f"{c['retrying']:>9} {c['stopped']:>8}")
    stopped = [(hg, s, recs[s]) for hg, recs in sorted(st["hgs"].items()) for s in st["stages"]
               if recs[s]["state"] == "failed"]
    shown = [x for x in stopped if x[2]["reason"] != "upstream"]
    if shown:
        lines.append("stopped:")
        for hg, s, r in shown:
            log = _err_log(s, r)
            lines.append(f"  {hg}  {s}  failed:{r['reason']}"
                         + (f" ({r['note']})" if r["note"] else "") + (f"  log {log}" if log else ""))
    if len(stopped) > len(shown):
        lines.append(f"  (+{len(stopped) - len(shown)} later stages stopped upstream)")
    return "\n".join(lines)
```

In `phylocli/phylo.py`: add `import time` to the top-level imports (after `import sys`), and below the line `from phylocli import model  # noqa: E402` add:

```python
from phylocli import chain as chain_mod  # noqa: E402
```

Then add, after the `_run` command and before `if __name__ == "__main__":`:

```python
@app.command("chain")
def chain_cmd(hgs: list[str] = typer.Argument(None, help="HG ids; with --status / --cancel / "
                                                         "--resume: a chain dir or name"),
              missing_: bool = typer.Option(False, "--missing", help="HGs not done for --to"),
              ids: Path = typer.Option(None, "--ids", help="HG ids file"),
              fam: str = typer.Option(None, "--fam", "-f", help=FAM_HELP),
              from_: str = typer.Option(None, "--from",
                                        help="first stage (default: each HG's first stage not done)"),
              to: str = typer.Option("possvm", "--to", help="last stage"),
              attempts: int = typer.Option(3, "--attempts", min=1,
                                           help="tries per HG and stage (resource failures only)"),
              name: str = typer.Option(None, "--name",
                                       help="chain name (default: the family, else 'chain')"),
              dry_run: bool = typer.Option(False, "--dry-run", "-n",
                                           help="print the plan, submit nothing"),
              status_: bool = typer.Option(False, "--status",
                                           help="the newest chains, or one chain in detail"),
              cancel: bool = typer.Option(False, "--cancel", help="scancel a chain's driver and arrays"),
              resume: bool = typer.Option(False, "--resume",
                                          help="submit a new driver for a stalled chain")):
    """Run HGs through align → tree → (possvm_prev ∥ generax) → gxsup → possvm with one driver
    job, retrying out-of-memory / time-limit / node failures with more resources."""
    import yaml

    if status_ + cancel + resume > 1:
        _fail("give at most one of --status, --cancel, --resume", 2)
    hgs = hgs or []
    if status_:
        if len(hgs) > 1:
            _fail("--status takes at most one chain", 2)
        typer.echo(_guard(chain_mod.status_text)(hgs[0] if hgs else None))
        return
    if cancel or resume:
        verb = "cancel" if cancel else "resume"
        if len(hgs) != 1:
            _fail(f"--{verb} needs one chain (its dir or name)", 2)
        st = _guard(chain_mod.load)(_guard(chain_mod.resolve)(hgs[0]))
        if st["status"] != "running":
            _fail(f"chain {st['name']} is {st['status']}: nothing to {verb}", 1)
        if resume:
            _guard(chain_mod.check_no_driver)(st)
        if not typer.confirm(f"{verb} chain {st['name']} ({st['dir']})?", default=False):
            typer.echo("nothing done")
            return
        if cancel:
            done_ids = _guard(chain_mod.cancel)(st, time.time())
            typer.echo(f"cancelled chain {st['name']}"
                       + (f"; scancel {' '.join(done_ids)}" if done_ids else ""))
        else:
            jid = _guard(chain_mod.start)(st, time.time())
            typer.echo(f"driver {jid} (phylo-chain) for chain {st['dir']}")
        return
    raw = yaml.safe_load(Path(os.environ.get("PHYLOCLI_CONFIG")
                              or core.ROOT / "phylocli/config.yaml").read_text())
    cfg = core.config_from_raw(raw)
    stages = _guard(chain_mod.stage_slice)(cfg, from_, to)
    if (missing_ + (ids is not None) + bool(hgs)) > 1:
        raise typer.BadParameter("give at most one of --missing, --ids FILE, or HG ids")
    if not (missing_ or ids is not None or hgs or fam):
        raise typer.BadParameter("give HG ids, --ids FILE, --fam FAMILY or --missing")
    exp = core.expected(cfg)
    if missing_:
        selected = sorted(exp - core.report_status.done_by_stage(str(cfg.outdir), exp)[to])
    elif ids is not None:
        selected = core.read_ids(ids)
    elif hgs:
        selected = list(dict.fromkeys(hgs))
    else:
        selected = sorted(exp)
    if fam:
        keep = core.filter_fam(selected, fam)
        selected = [hg for hg in selected if hg in keep]
        if not selected:
            _fail(f"no HGs match --fam {fam}", 1)
    unknown = sorted(set(selected) - exp)
    if unknown:
        typer.echo(f"unknown ({len(unknown)}): {_show(unknown)}", err=True)
        typer.echo("nothing submitted", err=True)
        raise typer.Exit(2)
    if not selected:
        typer.echo("nothing to submit")
        raise typer.Exit(0)
    for st_ in stages:
        msg = model.preflight(st_)
        if msg:
            _fail(msg, 78)
    mx = chain_mod.max_mem_mb(raw)
    p = chain_mod.prepare(cfg, selected, stages, mx)
    for line in chain_mod.plan_lines(p, attempts, mx):
        typer.echo(line)
    if dry_run:
        typer.echo("nothing submitted (dry run)")
        return
    if p.done == len(p.hgs):
        typer.echo("nothing to submit")
        return
    if not typer.confirm("submit the chain driver?", default=False):
        typer.echo("nothing submitted")
        return
    now = time.time()
    st = chain_mod.create(cfg, raw, p.hgs, stages, {"attempts": attempts, "max_mem_mb": mx},
                          name or chain_mod.default_name(p.hgs, fam), now)
    jid = _guard(chain_mod.start)(st, now, new=True)
    typer.echo(f"chain {st['dir']}")
    typer.echo(f"driver {jid} (phylo-chain · 1 cpu · 500 MB · qos long, 1 day; "
               f"polls every {st['options']['poll_s']} s)")
    typer.echo(f"follow it: phylo chain --status {Path(st['dir']).name}")


@app.command("_chain", hidden=True)
def _chain_cmd(chain_dir: Path = typer.Argument(...),
               resume: bool = typer.Option(False, "--resume")):
    """The chain driver loop (runs inside the phylo-chain job)."""
    raise typer.Exit(chain_mod.run_driver(chain_dir, resumed=resume))
```

In `phylocli/README.md`: add `phylocli/phylo chain …` to the `## Commands` code block (after the `jobs` line):

```
phylocli/phylo chain [HGS]... [--missing] [--ids PATH] [--fam/-f PREFIX] [--from STAGE] [--to STAGE]
                     [--attempts 3] [--name NAME] [-n/--dry-run]
phylocli/phylo chain --status [CHAIN] | --cancel CHAIN | --resume CHAIN
```

and a new section directly after `## Typical loop`:

```markdown
## phylo chain: stage after stage, with retries (added 09/10/2026)

One SLURM job `phylo-chain` (1 cpu, 500 MB, qos long = 1 day) takes the selected HGs through
align → tree → (possvm_prev ∥ generax) → gxsup → possvm (the HG stages only; step1 is not chained).
`--from` defaults to each HG's first stage not done, `--to` to possvm; `--missing` = HGs not done
for `--to`. `-n` prints the plan (start stage per HG, attempt-1 resources per stage); without it
`phylo chain` asks `y` and then submits only the driver.

Every 60 s the driver reads the output files and sacct. An HG moves on only once its output
exists. A task that ran out of memory (or exit 137), hit its time limit (or exit 140) or lost its
node is resubmitted with memory ×2 / time ×2 / unchanged, up to `--attempts` (3), with the qos its
time needs (normal ≤ 12 h, long ≤ 1 day, vlong ≤ 2 days) and memory ≤ `chain_max_mem`
(config.yaml, 64G); beyond that it stops as `failed:cap`. Anything else (exit 1, 65 no output,
10 GeneRax parse error, cancelled) is not retried: the HG stops as `failed:<reason>`. Arrays go
through the same checks as `submit` (HGs queued elsewhere or finished are skipped, never
duplicated), in batches: ≥ 50 HGs, 5 min after the first became ready, or nothing else of that
stage pending. 30 min before its own limit the driver queues its successor (afterany) and exits.

State: `runs/chains/<date>_<name>/chain.json`; log `driver.log` there. CHAIN = that dir or its
name. `--status` shows `stalled` when neither the driver nor its successor is in squeue:
`--resume CHAIN` submits a new driver (refused while one is queued). `--cancel CHAIN` scancels the
driver and the chain's arrays.
```

- [ ] **Step 4: Run to verify they pass** — `python3 -m pytest phylocli/tests/test_chain.py -q -p no:cacheprovider` — Expected: PASS. Both full suites — Expected: Task 3 count **+11**, no failures (in particular `test_cli.py`, `test_step1.py` unchanged).

- [ ] **Step 5: Commit**

```bash
git add phylocli/chain.py phylocli/phylo.py phylocli/README.md phylocli/tests/test_chain.py
git commit -m "phylocli: phylo chain (plan, confirm, driver; --status/--cancel/--resume) and hidden _chain

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: TUI — `C` dialog, chains in pane 3 Arrays, `chain:<stage> aN` state

**Files:**
- Modify: `phylocli/chain.py` (append `active`, `owned`, `array_table`), `phylocli/tui.py` (`import time`; `from phylocli import chain, core, history, model`; `PhyloApp.BINDINGS`, `__init__`, `_collect`, `_apply`, `_fill_hgs`, new `_state_cell`, `check_action`, `action_resubmit`, new `action_chain`; new class `ChainScreen` after `ResubmitScreen`), `phylocli/README.md` (`## phylo tui`)
- Test: `phylocli/tests/test_chain.py` (append), `phylocli/tests/test_tui.py` (append)

Anchor every edit on the method name, not a line number: step1 Task 6 and the Results-window plan may have changed `tui.py` around these methods. If step1 Task 6 has landed and `self.stage` can be `search` / `cluster`, `C` there shows `stage_slice`'s "chains run the HG stages only" in the dialog — no extra code.

**Interfaces:**
- Consumes: Task 4 (`prepare`, `plan_lines`, `default_name`, `start`, `hg_counts`, `max_mem_mb`, `stage_slice`, `DEFAULTS`), Task 1 (`create`, `load`, `chains_dir`), `model.ArrayRow(run, stage, job, n, counts)`, `model.preflight(stage)`, tui's `_Box`, `_settle`, `_calls` (test helpers already in `test_tui.py`).
- Produces:
  - `chain.active(limit=20) -> list[dict]` (running chains, newest first)
  - `chain.owned(chains) -> {hg: "chain:<stage> a<attempt>"}`
  - `chain.array_table(rows, chains) -> list[(row key, 7 cells)]` — per running chain a driver row (key `chain:<name>`, cells `(driver job | "-", "chain <name>", n HGs, done, running, pending, failed)`) followed by its arrays (stage cell prefixed `└ `), then every other array
  - `tui.ChainScreen(cfg, raw, hgs, from_stage)` with `.submitted: list[str]` and `._shown: str`; `PhyloApp.chains`, `PhyloApp.owned`

- [ ] **Step 1: Write the failing tests** — append to `test_chain.py`:

```python
def test_owned_and_array_table(ch):
    st = chain._chain_step(_new([C, A1], batch_min=1), T0)   # align 101 (C), generax 102 (A1)
    assert chain.owned([st]) == {C: "chain:align a1", A1: "chain:generax a1"}
    rows = [model.ArrayRow(Path("r"), "align", "101", 1, collections.Counter(pending=1)),
            model.ArrayRow(Path("r"), "tree", "55", 3, collections.Counter(done=3)),
            model.ArrayRow(Path("r"), "generax", "102", 1, collections.Counter(running=1))]
    table = chain.array_table(rows, [st])
    assert [k for k, _c in table] == ["chain:t", "101", "102", "55"]
    assert table[0][1] == ("-", "chain t", "2", "0", "2", "0", "0")    # no driver recorded
    assert table[1][1][1] == "└ align" and table[3][1][1] == "tree"


def test_active_lists_running_chains_only(ch):
    a = _new([C])
    b = _new([A1])
    chain.cancel(chain.load(b["dir"]), T0)
    assert [s["dir"] for s in chain.active()] == [a["dir"]]
```

Append to `test_tui.py`:

```python
def test_chain_key_dry_run_then_submit(cli):
    from phylocli import chain

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600, start="hgs")
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a", "C")             # actionable at align: tfs.A.HG11, tfs.C_x.HG1
            await _settle(app, pilot)
            scr = app.screen
            assert isinstance(scr, tui.ChainScreen) and "dry run" in scr._shown
            assert _calls() == []                   # the dry run submits nothing
            await pilot.press("y")
            await _settle(app, pilot)
            assert scr.submitted == ["12345"]
    _run(go())
    st = chain.load(next((_state["runs"] / "chains").iterdir()))
    assert sorted(st["hgs"]) == ["tfs.A.HG11", "tfs.C_x.HG1"] and st["stages"][0] == "align"
    assert st["driver"]["job"] == "12345" and len(_calls()) == 1
    assert _calls()[0].endswith("driver.sbatch")


def test_chain_key_needs_a_selection(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600, start="hgs")
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("C")
            await pilot.pause()
            assert not isinstance(app.screen, tui.ChainScreen)
    _run(go())


def test_chain_owned_hgs_show_chain_state_and_are_not_resubmitted(cli):
    from phylocli import chain
    cfg = _cfg()
    st = chain.create(cfg, tui.load_raw(), ["tfs.C_x.HG1"], chain.stage_slice(cfg), {}, "own",
                      time.time())
    st["driver"] = {"job": "777"}
    chain.save(st)

    async def go():
        app = tui.PhyloApp(cfg, refresh_s=3600, start="hgs")
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert app.owned == {"tfs.C_x.HG1": "chain:align a1"}
            assert "chain:align a1" in str(app.query_one("#hgs").get_row("tfs.C_x.HG1")[3])
            assert app.query_one("#arrays").ordered_rows[0].key.value == "chain:own"
            app.selected = {"tfs.C_x.HG1"}
            await pilot.press("r")
            await pilot.pause()
            assert not isinstance(app.screen, tui.ResubmitScreen)
    _run(go())
```

- [ ] **Step 2: Run to verify they fail** — `python3 -m pytest phylocli/tests/test_chain.py phylocli/tests/test_tui.py -q -p no:cacheprovider` — Expected: the 5 new tests FAIL (`AttributeError: ... 'owned'` / `'active'` / `module 'phylocli.tui' has no attribute 'ChainScreen'`).

- [ ] **Step 3: Implement.**

3a. Append to `chain.py`:

```python
# ---- TUI helpers ---------------------------------------------------------------------------

def active(limit: int = 20) -> list[dict]:
    """Running chains, newest first (the TUI reads them every refresh)."""
    out = []
    for f in sorted(chains_dir().glob("*/chain.json"), key=lambda p: p.parent.name,
                    reverse=True)[:limit]:
        try:
            st = load(f.parent)
        except (model.ModelError, ValueError, OSError):
            continue
        if st["status"] == "running":
            out.append(st)
    return out


def owned(chains: list) -> dict:
    """{hg: "chain:<stage> a<attempt>"} for HGs a running chain still has work for: the first
    stage (pipeline order) that is eligible, queued or queued elsewhere."""
    out = {}
    for st in chains:
        for hg, recs in st["hgs"].items():
            for s in st["stages"]:
                r = recs[s]
                if r["state"] in ("eligible", "queued", "external"):
                    out[hg] = f"chain:{s} a{r['attempt']}"
                    break
    return out


def _array_cells(a, prefix: str = "") -> tuple:
    c = a.counts
    return (a.job, prefix + a.stage, str(a.n), str(c["done"]), str(c["running"]),
            str(c["pending"]), str(c["failed"]))


def array_table(rows: list, chains: list) -> list:
    """Pane 3 rows [(key, cells)]: each running chain's driver (phylo-chain) above its arrays,
    then every other array. `rows` are model.array_rows() rows."""
    out, used = [], set()
    for st in chains:
        c = hg_counts(st)
        out.append((f"chain:{st['name']}", (st["driver"].get("job") or "-", f"chain {st['name']}",
                                             str(len(st["hgs"])), str(c["done"]),
                                             str(c["running"]), str(c["pending"]),
                                             str(c["failed"]))))
        jobs = set(st["jobs"])
        for a in rows:
            if a.job in jobs and a.job not in used:
                used.add(a.job)
                out.append((a.job, _array_cells(a, "└ ")))
    out += [(a.job, _array_cells(a)) for a in rows if a.job not in used]
    return out
```

3b. `tui.py` imports: add `import time` after `import os`; change `from phylocli import core, history, model` to `from phylocli import chain, core, history, model`.

3c. `PhyloApp.BINDINGS`: after `Binding("r", "resubmit", "resubmit"),` add

```python
        Binding("C", "chain", "chain"),
```

3d. `PhyloApp.__init__`: after `self._banner_text = ""` add

```python
        self.chains: list = []                  # running chains (chain.json states)
        self.owned: dict = {}                   # hg -> "chain:<stage> aN"
```

3e. `PhyloApp._collect`: in the `if self.view == "hgs":` branch, replace

```python
            snap["hg"] = dict(atts=atts, by_stage=by_stage, arrays=arrays,
                              sacct_known=sacct_known)
```

with

```python
            snap["hg"] = dict(atts=atts, by_stage=by_stage, arrays=arrays,
                              sacct_known=sacct_known, chains=chain.active())
```

3f. `PhyloApp._apply`: replace the arrays block

```python
        ar = self.query_one("#arrays", DataTable)
        keep_row = ar.cursor_row
        ar.clear()
        for a in snap["arrays"]:
            c = a.counts
            ar.add_row(a.job, a.stage, str(a.n), str(c["done"]), str(c["running"]),
                       str(c["pending"]), str(c["failed"]), key=a.job)
        if snap["arrays"]:
            ar.move_cursor(row=min(keep_row, len(snap["arrays"]) - 1))
```

with

```python
        self.chains = snap.get("chains", [])
        self.owned = chain.owned(self.chains)
        ar = self.query_one("#arrays", DataTable)
        keep_row = ar.cursor_row
        ar.clear()
        table = chain.array_table(snap["arrays"], self.chains)
        for key, cells in table:
            ar.add_row(*cells, key=key)
        if table:
            ar.move_cursor(row=min(keep_row, len(table) - 1))
```

(`snap` is the HG snapshot dict at that point in `_apply`, as for `snap["arrays"]`.)

3g. `PhyloApp._fill_hgs`: in the `t.add_row(...)` call replace the state cell argument `f"[{STATE_STYLE[r.state]}]{r.state}[/]",` with `self._state_cell(r),` and add the method after `_fill_hgs`:

```python
    def _state_cell(self, r) -> str:
        """`chain:<stage> aN` for an HG a running chain owns (unless done at this stage)."""
        own = self.owned.get(r.hg)
        if own and r.state != "done":
            return f"[magenta]{escape(own)}[/]"
        return f"[{STATE_STYLE[r.state]}]{r.state}[/]"
```

3h. `PhyloApp.check_action`: change `if action in ("back", "toggle", "select_all", "resubmit", "log"):` to `if action in ("back", "toggle", "select_all", "resubmit", "chain", "log"):`.

3i. `PhyloApp.action_resubmit`: after the `if not rows: … return` block add

```python
        mine = [r for r in rows if r.hg not in self.owned]
        if len(mine) < len(rows):
            self.notify(f"skipped {len(rows) - len(mine)} HGs a running chain owns",
                        severity="warning")
        rows = mine
        if not rows:
            return
```

and add after `action_resubmit`:

```python
    def action_chain(self) -> None:
        hgs = sorted(self.selected)
        if not hgs:
            self.notify("nothing selected (space / a)", severity="warning")
            return
        mine = [hg for hg in hgs if hg not in self.owned]
        if len(mine) < len(hgs):
            self.notify(f"skipped {len(hgs) - len(mine)} HGs a running chain owns",
                        severity="warning")
        if not mine:
            return
        self.push_screen(ChainScreen(self.cfg, self.raw, mine, self.stage),
                         lambda _jids: (self.selected.clear(), self.load_bg()))
```

3j. New class after `ResubmitScreen` (before `LogScreen`):

```python
class ChainScreen(ModalScreen):
    """`C` in the HG view: dry run of `phylo chain` for the selected HGs from the current stage
    (computed on open, in a worker); `y` creates the chain and submits its driver."""
    BINDINGS = [Binding("y", "submit", "submit driver", priority=True),
                Binding("escape", "cancel", "cancel")]
    CSS = """
    ChainScreen { align: center middle; }
    #cbox { width: 90%; height: auto; border: round $warning; background: $surface; padding: 1; }
    """

    def __init__(self, cfg: core.Config, raw: dict, hgs: list, from_stage: str):
        super().__init__()
        self.cfg, self.raw, self.hgs, self.from_stage = cfg, raw, sorted(hgs), from_stage
        self.submitted: list[str] = []
        self._ready = None                      # (stages, ChainPlan) of a good dry run
        self._busy = True
        self._shown = ""

    def compose(self) -> ComposeResult:
        with _Box(id="cbox"):
            yield Label(f"[b]chain · {len(self.hgs)} HGs from {self.from_stage}[/]  "
                        "y = submit the driver · esc = cancel")
            yield Static("", id="cout")

    def on_mount(self) -> None:
        self.query_one("#cbox").focus()
        self._out("[cyan]working…[/]")
        self._dry_worker()

    def _out(self, text: str) -> None:
        self._shown = text
        try:
            self.query_one("#cout", Static).update(text)
        except Exception:                  # screen already dismissed
            pass

    def _post(self, fn, *args) -> None:
        try:
            self.app.call_from_thread(fn, *args)
        except Exception:
            pass

    def _finish(self, text: str, ready=None, jids: "list | None" = None) -> None:
        self._busy = False
        self._ready = ready
        if jids:
            self.submitted = jids
        self._out(text)

    @work(thread=True, exclusive=True, group="chain")
    def _dry_worker(self) -> None:
        try:
            stages = chain.stage_slice(self.cfg, self.from_stage, "possvm")
            for st in stages:
                msg = model.preflight(st)
                if msg:
                    self._post(self._finish, f"[red]{escape(msg)}[/]")
                    return
            mx = chain.max_mem_mb(self.raw)
            p = chain.prepare(self.cfg, self.hgs, stages, mx)
            lines = ["[cyan]dry run[/] — nothing submitted yet; y to submit the driver"]
            lines += [escape(l) for l in chain.plan_lines(p, chain.DEFAULTS["attempts"], mx)]
            ready = (stages, p) if p.done < len(p.hgs) else None
            if ready is None:
                lines.append("[yellow]nothing to do: every HG is done[/]")
        except Exception as e:             # never let a worker kill the app
            self._post(self._finish, f"[red]{escape(str(e))}[/]")
            return
        self._post(self._finish, "\n".join(lines), ready)

    def action_submit(self) -> None:
        if self._busy or self._ready is None:
            return
        if self.submitted:
            if "already submitted" not in self._shown:
                self._out(self._shown + "\n[yellow]already submitted · esc to close[/]")
            return
        self._busy = True
        self._submit_worker(self._ready)

    @work(thread=True, exclusive=True, group="chain")
    def _submit_worker(self, ready) -> None:
        stages, p = ready
        try:
            mx = chain.max_mem_mb(self.raw)
            st = chain.create(self.cfg, self.raw, p.hgs, stages, {"max_mem_mb": mx},
                              chain.default_name(p.hgs), time.time())
            jid = chain.start(st, time.time(), new=True)
        except Exception as e:             # never let a worker kill the app
            self._post(self._finish, f"[red]{escape(str(e))}[/]")
            return
        self._post(self._finish, f"[green]driver {jid}[/] (phylo-chain) · chain "
                                 f"{escape(st['dir'])}\nfollow it: phylo chain --status",
                   ready, [jid])

    def action_cancel(self) -> None:
        if self._busy:
            self.notify("still working — wait", severity="warning")
            return
        self.dismiss(self.submitted)
```

3k. `phylocli/README.md`, `## phylo tui`: in the "Keys (HG view)" paragraph insert ``` `C` chain the selection from this stage (see `phylo chain`) · ``` after `` `r` resubmit selection · ``, and append the paragraph:

```markdown
Chain (`C`): a dry run of `phylo chain` for the selected HGs from the highlighted stage to possvm;
`y` creates the chain and submits its driver, `esc` closes. HGs a running chain owns show
`chain:<stage> aN` in the state column and are left out of `r` and `C`; pane 3 lists each running
chain's `phylo-chain` driver above its arrays.
```

- [ ] **Step 4: Run to verify they pass** — `python3 -m pytest phylocli/tests/test_chain.py phylocli/tests/test_tui.py -q -p no:cacheprovider` — Expected: PASS. Both full suites — Expected: Task 4 count **+5** (+2 in `test_chain.py`, +3 in `test_tui.py`; an interpreter without Textual skips `test_tui.py` as a module, so there it is +2), no failures.

- [ ] **Step 5: Commit**

```bash
git add phylocli/chain.py phylocli/tui.py phylocli/README.md phylocli/tests/test_chain.py phylocli/tests/test_tui.py
git commit -m "phylocli tui: C chains the selection (dry run, y submits the driver); chains in Arrays pane; chain-owned HGs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (done while writing)

- **Spec coverage.** §1: command and selection (Task 4), `--from` default / `--to` / `-n` / confirm (Task 4, decisions 2, 5), TUI `C` (Task 5), driver job and resources (Task 3 `DRIVER_SBATCH`), submission path (Task 2 `_submit`), 60 s poll (Task 3 `run_driver`), `chain.json` atomic + `driver.log` (Task 1), successor before the limit (Task 3), `--resume` (Tasks 3–4), `--cancel` (Task 4). §2: retried states/exits and `bump` (Tasks 1, 3), others not retried (Task 3), caps and qos escalation (Tasks 1–3), retries batched per poll (Task 2 `_flush`). §3: advance after output (Task 2), graph incl. skipped stages (Task 1 `parents`), batching thresholds (Task 2), skip queued-by-others / done (Task 2), end + summary (Task 2). §4: `--status` list / detail / stalled / stopped reasons (Task 4), Arrays pane + state column (Task 5). Testing list: every item has a named test.
- **Placeholders:** none; every code step carries the code, every test step the test code.
- **Names:** `_chain_step`, `run_driver`, `submit_driver`, `start(state, now, new=False)`, `prepare`, `plan_lines`, `ChainPlan`, `owned`, `array_table`, `active`, `model.task_results` are spelled the same in every task that uses them.
- **Review Focus:** each of the five lines has its test in the owning task (Tasks 2, 3, 4).
