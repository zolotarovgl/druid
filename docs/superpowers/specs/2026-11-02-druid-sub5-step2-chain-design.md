# druid sub-project 5 — step 2 as one chain: a driver job, druid's own retries, no Nextflow

Date: 02/11/2026 · Branch: `main` · Status: direction agreed in chat with Grygoriy (option B,
"B", 02/11/2026); this document awaits his review.
Supersedes, for druid, `2026-10-09-phylocli-chains-design.md` (phylocli, never built); that
spec's mechanics are reused here, renamed and adjusted to the decisions below.
Parent: `2026-10-14-druid-standalone-design.md`.

## Why
Step 1 is one command (`druid run`, sub-project 3). Step 2 is still six manual
`druid submit <stage> --missing` rounds. Grygoriy wants the whole step-2 chain submitted at once,
with failed tasks retried with more resources.

Rejected, with the reason:
- **Nextflow** (phylohpc `step2.nf`): its `work/` keeps every task's files and blows up storage
  (v3 `work/`, 802 GB, filled the lab quota on 12/10/2026). Grygoriy: "in the future we will
  abandon the nextflow once we find a way to re-try the jobs ourselves".
- **SLURM dependencies alone**: `aftercorr` chains stages per task, but SLURM has no per-task
  "run only if the corresponding task failed". Retries would need pre-submitted retry arrays for
  every stage x attempt (~33k mostly no-op tasks for 1,849 HGs), each waiting for the slowest HG
  of the previous attempt, and the bump could not follow why a task failed.

## Goals
- One command, `druid chain`, and one TUI action take the step-2 HGs through
  align -> tree -> (possvm_prev || generax) -> gxsup -> possvm, unattended.
- Failed tasks are retried with more memory or more time, according to how they failed.
- Results go straight into `results/` exactly as `druid submit` writes them today: no work dir,
  no copies.
- Everything the chain writes is inside the project directory (write boundary unchanged).

## Non-goals
- Step 1 in the chain (step 1 stays `druid run`; Grygoriy reviews the clustering before step 2).
- The `REPORT` step / `report_step2.html` (Grygoriy: "drop it for now").
- Resource prediction; Nextflow compatibility; a Setup "Work dir" section (it existed only for
  Nextflow, see Rulings).

## Anti-goals
- Resubmitting an HG that is queued, running or done (by druid, a chain, or Nextflow).
- Retrying a deterministic failure in a loop (burns cluster time, hides the error).
- Any write outside the project; anything touching `proteomes_dir` or its sources.

## §1 How it runs
- **Command**: `druid chain [<selection>] [--from STAGE] [--to STAGE] [--attempts N] [-n]`.
  - Default selection (Grygoriy, 02/11/2026: option 1): every clustered HG passing `min_seqs` and
    `min_distinct` (`core.expected_hgs`). Optional narrowing exactly as `submit`: HG ids,
    `--ids FILE`, `-f FAMILY`.
  - `--from` defaults to each HG's first not-done applicable stage; `--to` defaults to `possvm`.
  - `-n` prints the plan — HGs per starting stage, attempt-1 resources per stage, the retry rules
    in force — and submits nothing. Without `-n` it asks `y`, then submits only the driver.
  - Refuses, like `druid run`: no `job_prefix`, an adopted project (`prepare: locked`), nothing to
    do (exit 0, "nothing to submit"), a chain already running in this project (one at a time).
- **TUI**: `C` on the Jobs tab opens the same dry-run -> `y` dialog for the default selection
  (the `RunScreen` pattern of `S`); refused while a prepare or another chain runs.
- **Driver**: one SLURM job `<job_prefix>-chain`, 1 cpu, 1 GB, `-p genoa64`, `--qos=pipelines`
  (no wall-time limit on this cluster, `sacctmgr`, 02/11/2026; same settings as v3
  `submit_nf.sh`), `--no-requeue`, running `druid _chain <chain dir>`. It submits stage arrays
  through the existing `model` select / plan / write / `sbatch_all` path, so every array is a
  normal druid run under `runs/` with its `jobs.tsv`, polls `sacct` every 60 s, retries, and
  advances HGs per §3.
- **State**: `runs/chains/<YYYYmmdd-HHMMSS>/chain.json` — the selection and options, and per HG:
  current stage, attempt, last job id / task, last state, the resources of every attempt.
  Written atomically (tmp + rename) after every change. Driver log: `driver.log` beside it.
- **Resume**: `druid chain --resume [<dir>]` resubmits a driver on a saved `chain.json` (after a
  node failure or a cancelled driver). Arrays still queued are adopted, not resubmitted.
- **Cancel**: `druid chain --cancel [<dir>]` (asks `y`) `scancel`s the driver and the chain's
  queued / running arrays, and marks the chain cancelled.

## §2 Retries
Agreed: resources and retry rules live in druid, not in a workflow engine.
- **Attempt 1** uses `core.resources()` as `druid submit` does today (resources.tsv row, else the
  stage default).
- **Retried**: resource failures only — `OUT_OF_MEMORY` / exit 137 -> memory x factor;
  `TIMEOUT` / exit 140 -> time x factor; `NODE_FAIL`, `PREEMPTED`, `BOOT_FAIL` -> unchanged.
- **Not retried**: exit 1 from a stage script, 65 (no output), GeneRax exit 10 (parse error),
  `CANCELLED`, "cancelled: search failed"-style upstream cancels. The HG stops as
  `failed:<reason>`, shown in the TUI and `--status`.
- **Rules in `druid.yaml`**, per stage, with defaults:
  ```yaml
  retry:
    attempts: 3          # per stage; --attempts overrides for one chain
    factor: 2            # multiplier on the dimension that failed
    max_mem: 64G
  ```
  Per-stage overrides `retry.<stage>.attempts|factor|max_mem` are allowed.
- **Caps**: memory <= `max_mem`; time <= the qos limit — `normal` 12 h, then `long` 1 day, then
  `vlong` 2 days (qos picked from the bumped time; `vlong` is the ceiling). Beyond a cap the HG
  stops as `failed:cap`.
- Retries of one stage in one poll are batched into one array per resource group, as `submit`
  groups.

## §3 Advancing between stages
- After each poll, HGs whose current stage just finished (output present, per `report_status`)
  move on: `possvm_prev` and `generax` after `tree`; `gxsup` after `generax`; `possvm` after
  `gxsup`. Stages not applicable under the config (`run_generax: false`, `gxsup: false`) are
  skipped (`core.applicable`).
- Newly eligible HGs of a stage are submitted together when the batch reaches 50 HGs, 5 min after
  the first became eligible, or when nothing else of that stage is pending.
- Every submission goes through `model` select, so HGs queued or done meanwhile are skipped and
  recorded, never duplicated.
- The chain ends when every HG is done at `--to` or stopped; the driver writes per-stage counts
  (`done`, `failed:<reason>`) to `chain.json` and `driver.log` and exits 0.

## §4 Seeing a chain
- `druid chain --status [<dir>]`: state (running / finished / cancelled), driver job id, per-stage
  done / running / pending / retrying / stopped, and the stopped HGs with reasons. Without `<dir>`
  the newest chains, one line each.
- TUI Jobs tab: the driver `<job_prefix>-chain` with its chain above its arrays; the HG state
  column shows `chain:<stage> a<attempt>` for HGs a running chain owns.

## Rulings (Claude's calls, for Grygoriy to check)
- **No Setup "Work dir" section.** It was agreed for Nextflow's `work/`; the driver has no work
  dir, so the section and its write-boundary exception are dropped. Reversible if Nextflow comes
  back.
- **Retry by failure type** (old spec) rather than bumping memory and time together every attempt
  (agreed earlier for Nextflow), because the driver can see the failure.
- **3 attempts, factor 2, 64G** as defaults (old spec); v3's Nextflow used up to 10 attempts.
- **Driver on `pipelines`** instead of the old spec's `long` + successor-job scheme: no wall-time
  limit, so the successor logic is not needed.
- **Command `druid chain`, key `C`** (old spec's names); `S` stays step 1.

## Builder notes (from the builder check, 02/11/2026)
- **End of chain**: an HG is done when every applicable leaf stage is done — `possvm`, and
  `possvm_prev` when `run_generax` is on (both are read downstream). (Claude's call.)
- **COMPLETED but no output**: not retried; the HG stops as `failed:no_output`. (Claude's call.)
- **Timeouts under `--signal=B:USR2`**: `tree.sh` / `generax.sh` trap USR2 and `exit 140`
  (`druid/stages/tree.sh:34`, `generax.sh:82`), which `model._is_timeout` already counts.
- **Driver can submit from a compute node**: v3's `submit_nf.sh` runs the Nextflow head on
  `--qos=pipelines` and submits SLURM jobs from there; same pattern. 1 GB is ample.
- **Reuse, don't rewrite**: `model.bump()`, `_is_oom`, `_is_timeout`, `bump_reason`; bumped values
  go through `model.plan(per_hg=...)`. `model.plan()` refuses a batch containing any HG that is
  done / queued / input-missing (`core.validate`), so the driver pre-filters each batch.
- **Next stage**: one function over `core.applicable` (`run_generax: false` -> align, tree,
  possvm; `gxsup: false` -> possvm after generax).
- **Caps**: on retry the generax 1440-min cap in `core.resources` is lifted up to the `vlong`
  ceiling; qos = the higher of the stage's own (`tree` > 500 seqs -> `long`) and the bumped time's.
- **Attempts** count the chain's own submissions only (kept in `chain.json` across `--resume`).
  `NODE_FAIL` / `PREEMPTED` / `BOOT_FAIL` count as an attempt.
- **Batch thresholds** (50 HGs / 5 min) and the poll interval are module constants. The driver
  calls `model.require_prefix`, and its sbatch script exports `DRUID_PROJECT` / `DRUID_CONFIG`
  as the stage SBATCH template does.
- **TUI `C`** offers the default selection only; `--from` / `--to` / `--attempts` are CLI-only.

## Testing
Unit tests with the existing fake `sbatch` / `squeue` / `sacct` fixtures and a single-step driver
function (`chain_step(state) -> state`, clock injected, no sleeping): OOM retry doubles memory;
timeout retry doubles time and escalates qos; exit 1 not retried; cap -> `failed:cap`; advance only
once the output exists; possvm_prev || generax after tree; `run_generax: false` path; batching
thresholds; HGs queued by others skipped; atomic state writes; resume adopts queued arrays;
cancel; refusals (no prefix, locked project, chain already running). Then a cluster smoke test on
2–3 small HGs, Grygoriy's to run.
