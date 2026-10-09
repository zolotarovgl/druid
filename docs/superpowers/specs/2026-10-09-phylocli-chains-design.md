# phylocli chains — run step2 end to end with retries, like Nextflow

Date: 09/10/2026 · Branch: `phylocli` · Status: §1 approved in chat (Grygoriy: "go with the
driver"); §2–§4 written from the agreed direction, awaiting review.

## Goal
One command (or one TUI action) takes a selection of HGs through
align → tree → (possvm_prev ∥ generax) → gxsup → possvm without anyone watching, retrying
failures with more resources, the way Nextflow's head job does — while keeping phylocli's safety
rules (dry run first, never resubmit queued or finished HGs).

Why a driver job and not pre-submitted dependencies (decided 09/10/2026): retry resources depend
on how the attempt failed (OOM → mem, timeout → time), which is known only after it ran;
pre-submitting retry arrays for every HG × stage × attempt (~33k tasks for 1,849 HGs) floods the
queue with no-ops; `afterok`/`afterany` either cancel or blindly start downstream stages.

## §1 How it runs (approved)
- **Command**: `phylo chain <selection> [--from STAGE] [--to STAGE] [--attempts 3] [-n]`;
  selection = HG ids | `--ids FILE` | `-f FAMILY` | `--missing` (HGs not done for `--to`), exactly
  as `submit`. `--from` defaults to each HG's first not-done applicable stage; `--to` to `possvm`.
  `-n` prints the plan (HGs per starting stage, attempt-1 resources per stage) and submits nothing.
  Without `-n` it asks for confirmation (`y`), then submits only the driver.
- **TUI**: `C` on a selection in pane `2 HGs` opens the same dry-run → `y` dialog for a chain from
  the current stage.
- **Driver**: one SLURM job `phylo-chain` (1 cpu, 500 MB, qos `long` = 1 day on this cluster,
  measured 09/10/2026 via `sacctmgr`) running `phylo _chain <chain dir>`. It submits stage arrays
  through the existing `model.select` / `plan` / `write_run` / `sbatch_all` path, polls `sacct`
  every 60 s, retries, and advances HGs stage by stage per the dependency graph above.
- **State**: `runs/chains/<YYYYmmdd-HHMMSS>_<name>/chain.json` — per HG: current stage, attempt,
  last job id/task, last state, resources of each attempt; plus the selection and options.
  Written atomically (tmp + rename) after every change; the driver's log is `driver.log` there.
- **Wall time**: 30 min before its own limit the driver submits its successor
  (`_chain --resume`, `--dependency=afterany:<own id>`) and exits cleanly; a chain therefore runs
  for days. `phylo chain --resume <dir>` does the same by hand (e.g. after a node failure).
- **Cancel**: `phylo chain --cancel <dir>` (asks `y`) `scancel`s the driver and the chain's
  arrays and marks the chain cancelled.

## §2 Retries
- An HG task that ends in a **resource failure** — `OUT_OF_MEMORY`, `TIMEOUT`, `NODE_FAIL`,
  `PREEMPTED`, `BOOT_FAIL`, or exit 137/140 — is retried at the same stage with `model.bump()`
  (OOM / 137 → memory ×2; TIMEOUT / 140 → time ×2; node/preempt → unchanged), until `--attempts`.
- **Other failures are not retried** (exit 1 from a stage script, 65 "no output", 10 GeneRax parse
  error, CANCELLED): they are deterministic or deliberate, so a retry only burns cluster time. The
  HG stops there, marked `failed:<reason>`, visible in the TUI and `--status`.
- **Caps**: memory ≤ `chain_max_mem` (config, default 64G); time ≤ the qos limit — `normal`
  12 h, then `long` 1 day, then `vlong` 2 days (qos chosen from the bumped time; `vlong` is the
  ceiling). An HG that would need more is stopped as `failed:cap`.
- Retried HGs of one stage are batched into one array per poll (resource-grouped as `submit`
  does), not one job each.

## §3 Advancing between stages
- After each poll the driver collects HGs whose current stage just finished (output present,
  per `report_status`) and moves them to the next stage(s): `possvm_prev` and `generax` both
  after `tree`; `gxsup` after `generax`; `possvm` after `gxsup` (stages not applicable under the
  config are skipped, e.g. `run_generax: false`).
- Newly eligible HGs of a stage are submitted together when the batch is ≥ 50 HGs, or 5 min after
  the first one became eligible, or when nothing else of that stage is pending — so a chain makes
  few, reasonably sized arrays instead of many tiny ones.
- Every submission goes through `model.select`, so HGs queued meanwhile by someone else (phylocli
  or Nextflow) or already done are skipped and recorded as such, never duplicated.
- The chain ends when every HG is done at `--to` or stopped; the driver writes a summary
  (`done`, `failed:<reason>` counts per stage) to `chain.json` and `driver.log` and exits.

## §4 Seeing a chain
- `phylo chain --status [<dir>]`: per chain — state (running / finished / cancelled), driver job,
  per-stage counts done / running / pending / retrying / stopped, and the stopped HGs with reasons.
  Without `<dir>`: the newest chains, one line each.
- TUI: pane `3 Arrays` lists the driver (`phylo-chain`) with its chain name above its arrays; the
  HG list's state column shows `chain:<stage> a2` for HGs a running chain owns (so they are not
  resubmitted by hand: `select` already skips them as queued).
- The driver's own resource use is negligible; its job is visible in `squeue` as `phylo-chain`.

## Testing
Unit tests with the fake `sbatch`/`squeue`/`sacct` (existing fixtures) and a driver loop that can
run a single step (`_chain_step(state) -> state`) without sleeping: retry on OOM with doubled
memory, no retry on exit 1, cap → `failed:cap`, qos escalation, advance to next stage only after
output exists, possvm_prev ∥ generax after tree, batching thresholds, skip HGs queued by others,
atomic state writes, successor submission near the time limit (clock injected), resume from a
saved `chain.json`, cancel. A controller smoke test on the cluster with 2–3 small HGs before use.

## Out of scope
Chains over step1 (`search`/`cluster`) until step1 is built; Nextflow-style caching of work dirs;
resource prediction (the resource pre-training is separate future work).
