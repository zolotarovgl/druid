# druid sub-project 3 — `druid run`: linked search → cluster (step 1) + job-name prefix (design)

Grygoriy, 25/10/2026. Parent spec: `docs/superpowers/specs/2026-10-14-druid-standalone-design.md`
(row 5 / sub-project 3). Sub-project 2 (Setup tab, `prepare`) is done (`676fb13`).

## Intent

After Setup and `prepare`, one command (and one TUI key) launches **step 1** — `search` and
`cluster` for every family not yet done — and the user comes back when both have run. Step 2
(align → possvm) stays manual: "the user will then have to submit the step2 after exploring the
filtering etc" (Grygoriy). The simplest chain is linked search → cluster jobs, "more so because
some search jobs will NOT result in any proteins found" (Grygoriy).

Each project's SLURM jobs carry a prefix the user sets, so jobs can be told apart in the queue
(Grygoriy, 23/10/2026: "the user should specify the prefixes so the jobs can be identified").

## Goals

1. `druid run` (CLI) and a TUI key: submit `search` for the families not yet searched, and for
   each one a `cluster` task that starts when that family's search task has finished OK.
2. Families searched with hits but not clustered get `cluster` only (no dependency).
3. A family whose search finds nothing: its cluster task exits 0 as "no hits", publishes nothing,
   and the family counts as done for cluster (as `core.family_done` already does: `no_hits`).
4. `job_prefix` in `druid.yaml`, **required** by Setup (Grygoriy: "setup should require it");
   every job druid submits is named `<job_prefix>-<stage>`.

## Non-goals

- Step 2 chaining, the driver job of `2026-10-09-phylocli-chains-design.md`, automatic retries
  (Grygoriy, 25/10/2026: no automatic retries for step 1; a failed family is resubmitted by hand,
  `r` on the Jobs tab or `druid submit`).
- A `druid run --cancel`; `scancel` by hand is enough for now.
- Changing how `druid submit` works for a single stage, beyond the job name.

## Anti-goals (a failure even if it works)

- A family submitted twice (already queued for that stage, by druid or by Nextflow `nf-` jobs).
- A cluster task that starts on a missing or partial search output.
- A cluster task left PENDING forever because its search task failed.
- Another project's jobs (or another user's) counted as this project's.
- Any write outside the project directory (parent spec "Write boundary").

## How it runs

### Selection (my calls, from the existing `model.select` rules)
For the ticked families (`params.genefam_info`), optionally narrowed by `--fam`:
- **search+cluster**: no `<id>.domains.fasta` yet and not queued for search or cluster.
- **cluster only**: `domains.fasta` non-empty, no `_cluster.tsv`, not queued for cluster.
- **nothing**: no-hits families (done), clustered families (done), queued ones (skipped; counted).
The dry run and the confirm box print these counts and the arrays.

### Linking
- The search arrays are planned and written exactly as `druid submit search --missing` does
  (resource groups, ≤ 1000 per array, `genefam.csv` snapshot in the run dir).
- For each search array, a cluster array with **the same ids file order and size**, submitted with
  `--dependency=aftercorr:<search job id>` and `--kill-on-invalid-dep=yes`: cluster task *i*
  starts when search task *i* completed with exit 0; if search task *i* fails, cluster task *i* is
  cancelled by SLURM instead of waiting. Cluster resources: the step-1 cluster defaults (family
  ids have no `resources.tsv` rows), with any `--mem/--time/--cpus` override applying to both.
- Planning the linked cluster arrays skips only the "input missing" check for families in the
  paired search array (their input does not exist yet); every other check stays.
- *My call:* a family that fails any other check (e.g. stale HG FASTAs without `_cluster.tsv`:
  `output_exists`) is **dropped from both arrays before planning**, with a note naming it, like
  queued families — the run goes ahead for the rest and the pairing stays exact.
- *My call:* a cluster task cancelled because its search task failed is shown as
  `cancelled: search failed` (not a cluster failure; the search failure is the one to fix). The
  next `druid run` picks the family up again (no `domains.fasta`: search + cluster).
- Each stage keeps its own run dir and `jobs.tsv`, so the Jobs tab and history read them as
  today; the cluster run dir also records which search job each array depends on.
- If an sbatch fails mid-way, what was queued is reported (job ids) and nothing more is submitted,
  as `sbatch_all` does now; a cluster array is never submitted without its search array.
- The species lock is set by the first sbatch, as now (Ruling J of sub-project 2).

### No hits at run time
- `druid _run cluster <id>` with an empty `<id>.domains.fasta`: prints
  `no hits: nothing to cluster for <id>`, exits 0, publishes nothing, removes its work dir.

### CLI
`druid run [--fam F] [-n] [--max-running N] [--partition P] [--qos Q] [--mem M] [--time T]
[--cpus C]` — options mean what they mean for `druid submit`. `-n` writes the scripts and prints
the plan, submits nothing. Without `-n`, the same confirmation behaviour as `druid submit`.
Refuses (exit 2, `ERROR:` line) when: no `job_prefix`, `params.infasta` missing (prepare never
ran), or nothing to do. *My call:* Setup's other blockers are checked only while the species are
not yet locked; once locked (a run exists), a moved proteome file no longer blocks — input.fasta
is what the stages read. *My call:* an adopted project (`prepare: locked`) is refused by `run`
(`druid submit` per stage stays as it is there).

### TUI
One key, on the Jobs tab and in Setup, opens the same dry-run → `y` confirm box as resubmit (`r`),
showing the counts and arrays; the same code path as the CLI. After a successful prepare, the
Setup bottom line names that key as the next step.

## `job_prefix`

- Top-level `druid.yaml` key, set in Setup (a field; a Setup blocker while empty, so `prepare`,
  `submit` and `run` refuse without it, saying "set job_prefix in Setup"). *My call:* the field
  stays editable after the species lock (an existing project without one must be able to add
  it), and changing it affects only jobs submitted afterwards.
- *My call:* druid recognises its jobs by **job id** (every id in the project's `runs/*/jobs.tsv`,
  as `model.live` already maps them), not by name; the name gives only the stage. So a renamed
  prefix, or old `phylo-` jobs, are never lost, and another project's jobs (ids not in this
  project's `jobs.tsv`) are never counted. *My call:* letters, digits and `_`, 1–20 characters,
  starting with a letter (SLURM-safe; no `-`, which separates it from the stage).
- `SBATCH` job name `<job_prefix>-<stage>` for `submit`, `run` and TUI resubmits.
- *My call:* adopted projects keep `phylo-` and need no prefix (their `druid.yaml` is never written).

## Constraints

- Python 3.9, Textual ≥ 8.2, < 9 (CRG `phylo` env); no new dependencies.
- CRG SLURM 25.11.5: `aftercorr` + `--kill-on-invalid-dep=yes` work **per task** (measured
  25/10/2026, arrays 31114049 → 31114050, logs in `/no_backup/asebe/gzolotarov/druid-aftercorr-test/`):
  search task 1 FAILED after 5 s → cluster task 1 CANCELLED; search task 0 COMPLETED at 40 s →
  cluster task 0 ran and COMPLETED. sacct gives the cancelled task **Reason `None`**, so
  "cancelled: search failed" must be inferred from the paired search task's state (via the
  recorded dependency), not from sacct's Reason.
- A time of 5 min made sbatch switch the qos to `test`; real arrays keep druid's own time/qos.
- Tests use the fake sbatch; no real job is submitted without Grygoriy's ok.
- Every new write site passes `tests/test_write_boundary.py`.

## Left to the builder

- The TUI key letter (consistent with existing bindings), the confirm box layout, where the
  `job_prefix` field sits in Setup.
- How the dependency is recorded in the cluster run dir, and how the Jobs tab shows a cluster
  array waiting on its search (PENDING, reason Dependency) — it must not look failed.
