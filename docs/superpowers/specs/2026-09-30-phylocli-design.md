# phylocli — status and per-stage SLURM submission for step2, without Nextflow

Date: 30/09/2026 · Status: design approved in chat ("approve all"), awaiting spec review

## Goal

A Typer CLI, run on the cluster login node from `Phylogenies_v3/`, that

1. shows how many HGs have finished each step2 stage (what `workflow/report_status.py` prints), and
2. submits SLURM jobs for one stage over a set of HGs (typically the missing ones) **without
   running Nextflow**, and
3. **refuses** to submit a job whose outputs already exist.

Success = `phylo submit tree --missing` queues exactly the HGs that `phylo status` counts as
missing for `tree`, each with the resources Nextflow would have given it, and the outputs land
in the same `results/` paths step2.nf publishes to, so `status` then counts them as done.

## Decisions (from the 29–30/09/2026 discussion)

| Question | Decision |
|---|---|
| Job unit | One stage, many HGs (no whole-chain jobs, no automatic dependency chains) |
| Stage logic | Shared per-stage shell scripts, called by BOTH step2.nf and the CLI |
| Where | Directly in the v3 working copy, incl. editing v3's `step2.nf`; nothing pushed to GitHub |
| SLURM | Job arrays, one per group of HGs with identical (cpus, mem, time) |
| Docs | Dedicated `phylocli/README.md` |

## Layout

```
Phylogenies_v3/
  phylocli/
    README.md          usage, one example per command, the safety rules, the resume caveat
    phylo              executable wrapper: exec python3 "$(dirname "$0")/phylo.py" "$@"
    phylo.py           Typer app (status / missing / submit / queue)
    config.yaml        step2 parameters the stages need (see "Parameters")
    stages/
      align.sh  tree.sh  possvm_prev.sh  generax.sh  gxsup.sh  possvm.sh
    runs/              created on submit: one dir per submission (id lists, sbatch scripts, logs)
  workflow/report_status.py   unchanged; phylo.py imports STAGES / expected-HG logic from it
  step2.nf                    process `script:` blocks replaced by calls to phylocli/stages/*.sh
```

## Stages

Each stage script processes ONE HG: `stages/<stage>.sh <HG_ID>`. Inputs are read from, and
outputs written to, the same `results/` paths step2.nf uses. The body of each script is the
current v3 `step2.nf` process body moved verbatim (IQ-TREE checkpoint stash in PHY, GeneRax
resume in GR_watcher, possvm_postprocess in PVM/PVM_PREV, model reuse in GXSUP), with Nextflow
interpolations (`${id}`, `${task.cpus}`, `${params.X}`) turned into shell variables.

| Stage (status column) | step2 process | Needs (results/…) | Publishes to | cpus |
|---|---|---|---|---|
| align       | ALN        | clusters/<id>.fasta (≥ 2 seqs)             | align/        | 4 |
| tree        | PHY        | align/<id>.aln.fasta                       | gene_trees/   | 4 |
| possvm_prev | PVM_PREV   | gene_trees/<id>.treefile + alignment       | possvm_prev/  | 1 |
| generax     | GR_watcher | tree + alignment + SPECIES_TREE            | generax/      | NCPU_GENERAX |
| gxsup       | GXSUP      | generax/<id>.generax.tree + aln + PHY log  | generax_support/ | 2 |
| possvm      | PVM        | gxsup tree (or generax tree if gxsup off; or IQ-TREE tree if run_generax off) | possvm/ | 1 |

Interface (same as a Nextflow task): a stage script runs in a work directory, takes its
input files as positional arguments, reads parameters from env vars (`ID`, `CPUS`,
`PROJECT_DIR`, `OUTDIR`, step2 params), and leaves its outputs in the cwd.

- Nextflow: each process keeps its `input:`/`output:`/resources/publishDir and its "existing
  result" shortcut; the fresh-run branch of its `script:` becomes
  `ID=${id} CPUS=${task.cpus} ... bash ${projectDir}/phylocli/stages/<stage>.sh <inputs>`.
- CLI: a hidden `phylo _run STAGE ID` (the SLURM array task) creates `runs/<run>/work/<id>/`,
  symlinks the inputs from `results/`, runs the stage script, and only on exit 0 copies the
  stage's publish set (the same files step2.nf's publishDir publishes) into `results/<dir>/`,
  then deletes the work dir. A failed or killed job never leaves a partial file in
  `results/` that `status` would count as done; its work dir is kept for debugging.
  SLURM's warning signal (USR2, as step2 requests for PHY and GR_watcher) is forwarded to the
  stage so its checkpoint stash still runs.

## Parameters

`phylocli/config.yaml` holds the step2 params the stages read (exported as env vars to each
job): `OUTDIR, MAFFT_OPT, TREE_METHOD, IQTREE2_MODEL, SUBS_MODEL, SPECIES_TREE, MAX_SPR,
NCPU_GENERAX, REFNAMES, REFSPECIES, run_generax, gxsup, resources_tsv`, plus SLURM defaults
(`partition: genoa64`, `qos: normal`). Initial values = v3's `nextflow.config` params + the
`precise` profile + the flags of the last successful step2 run in `.nextflow/history`
(24/09/2026: `-profile slurm,precise --run_generax`).

## Resources

Per HG and stage, the same lookup as step2.nf: the `resources.tsv` row for the HG
(`aln_mem/aln_time`, `phy_*`, `gr_*`, `pvm_*`), else step2's in-process defaults (e.g. PHY
300 MB / 30 min, PVM 500 MB / 5 min). QoS as step2: `long` for `tree` when the HG has > 500 sequences, else `normal`. Only attempt-1
resources (no retry ladder). HGs are grouped by identical (cpus, mem, time, qos, signal); each
group becomes one `sbatch --array=0-(n-1)%<max_running>` whose task *i* runs the stage on line
*i* of `runs/<run>/ids_<k>.txt`. Job name `phylo-<stage>`; logs
`runs/<run>/logs/<stage>_%A_%a.{out,err}`, with the HG id echoed as the first log line.

## Commands

```
phylo status   [--ids FILE] [--by-category/--total]
phylo missing  STAGE [--ids FILE]
phylo submit   STAGE (--missing | --ids FILE | ID...) [--dry-run] [--max-running N]
                     [--partition P] [--qos Q]
phylo queue    [--stage STAGE]          # our phylo-* jobs in squeue, with their HG ids
```

`submit` validation — any failure prints the offending HG ids and exits non-zero with
**nothing submitted**:

1. **Output exists** for any selected HG (the rule requested on 29/09/2026). No `--force`.
2. **Input missing** (e.g. `submit tree` for an HG without an alignment).
3. **Already queued/running**: a `phylo-<stage>` job in `squeue` covers that HG
   (looked up via the `runs/*/ids_*.txt` of live array job ids).
4. Stage not applicable under the config (e.g. `generax` with `run_generax: 0`).

`--dry-run` prints the groups (n HGs, cpus, mem, time, qos) and the sbatch scripts it would
write, then exits without submitting.

## Error handling

- `sbatch` failure on group k: report which groups were submitted (job ids) and which were
  not; do not roll back submitted arrays.
- No automatic retries. Failed HGs show as missing in `status`; rerun `submit STAGE --missing`.
- Stage scripts run with `set -euo pipefail`.

## Consequences / caveats

- **Nextflow `-resume` cache**: task hashes include the process script text, so after step2.nf
  switches to the stage scripts a `nextflow -resume` in v3 will re-run tasks it had cached.
  From then on, gaps are filled with `phylo submit`, or Nextflow is run on a fresh id list.
- The stages call v3's own `phylogeny/` and `workflow/possvm_postprocess.py`, so outputs match
  what step2 produces in v3 today (old possvm: -1 root sentinel, no NA).
- Editing v3's tracked `step2.nf` will conflict with a later `git pull` of master there.
- Typer must be in the cluster `phylo` env (`mamba install -n phylo typer` if absent; add to
  `workflow/environment.yaml`).

## Testing

1. Unit (local, no SLURM): expected-HG set, output-exists / input-missing / applicability
   checks, resource lookup and grouping — against a small fixture `results/` tree.
2. `submit --dry-run` on real v3 results: the HG list must equal `phylo missing STAGE`.
3. Stage scripts vs Nextflow: run `stages/possvm_prev.sh` and `stages/tree.sh` for one small
   HG into a scratch OUTDIR and diff against the existing v3 outputs of that HG
   (possvm output is deterministic since possvm 38afc3c).
4. step2.nf after the switch: `nextflow run step2.nf -preview`, then one real HG end-to-end
   through Nextflow into a scratch OUTDIR.
5. One real small `phylo submit` on the cluster (e.g. 2–3 missing `possvm_prev` HGs), then
   `phylo status` shows them done.

## Out of scope

Automatic dependency chains between stages; retries; step1 stages; REPORT; pushing to GitHub.
