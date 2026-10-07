# phylocli

`phylo` reports step2 progress (per category, per stage) and submits one SLURM job array per
resource group for a single stage, without Nextflow. The stage scripts in `stages/` are the
step2.nf process bodies; step2.nf now calls the same scripts (created 30/09/2026).

## Setup

Run from `Phylogenies_v3` (cluster: `/users/asebe/gzolotarov/projects/2022_scRNAseq_Mlei/Phylogenies_v3`).

```
conda activate phylo
module load OpenMPI                 # mpirun for generax
python -c "import typer"           # typer must be in the phylo env; if it fails:
mamba install -n phylo typer
PYTHONNOUSERSITE=1 python -c "import ete3, Bio, yaml"   # self-check, same env the jobs use
phylocli/phylo --help
```

`submit` checks the tools the stage needs (mafft/clipkit, iqtree2, generax/mpirun) and, for
every stage except `gxsup`, that `PYTHONNOUSERSITE=1 python -c "import ete3, Bio, yaml"` works
(the `python` the stage scripts use). On failure it names the interpreter and the import error,
and exits 78 with nothing written. Arrays are split into chunks of at most 1000 HGs (SLURM
MaxArraySize), each chunk its own `ids_<k>.txt` / `array_<k>.sbatch` / sbatch call.

## Commands

```
phylocli/phylo status [--ids PATH] [--fam/-f PREFIX]
phylocli/phylo status HG [--history]
phylocli/phylo missing [STAGE] [--ids PATH] [--fam/-f PREFIX] [--all] [--per-fam]
phylocli/phylo submit STAGE [HGS]... [--missing] [--ids PATH] [--fam/-f PREFIX] [--all] [-n/--dry-run]
                            [--max-running INTEGER] [--partition TEXT] [--qos TEXT]
                            [--mem 16G] [--time 24h] [--cpus 8] [--set KEY=VALUE]...
phylocli/phylo jobs [--stage TEXT] [--last N] [--failed]
```

STAGE is one of `align tree possvm_prev generax gxsup possvm`. `submit` takes exactly one of:
HG ids, `--ids FILE`, or `--missing`. `--fam` takes a category (`tfs`) or a family
(`tfs.T-box`), matched on whole dot-separated id parts (`tfs.T-box` does not match `tfs.T-box2`).

```
phylocli/phylo status                                   # per stage: done / running / ready / blocked bars; "N/M HGs done"
# running = pending or running in SLURM now (squeue): phylocli array tasks AND Nextflow jobs (nf-<PROCESS>_(<HG>));
# running HGs are not counted as ready, `missing STAGE` leaves them out and `submit` skips them (07/10/2026)
phylocli/phylo status -f tfs.T-box                      # same, one family only
phylocli/phylo status dig.CathepsinC1.HG1               # one HG: state per stage + latest job (requested vs used)
phylocli/phylo status dig.CathepsinC1.HG1 --history     # one HG: every attempt, oldest first, with .err log paths
phylocli/phylo missing                                  # same counts; bar shows only what is left (ready green)
phylocli/phylo missing tree -f tfs | head               # tfs HGs ready for a tree
phylocli/phylo missing generax -f tfs --per-fam --all   # per family "missing/total", e.g. tfs.HLH 1/9
phylocli/phylo submit generax --missing -f tfs          # all ready tfs HGs lacking GeneRax
phylocli/phylo submit tree tfs.zf-C2H2.HG1 --mem 32G --time 2d   # override resources for these HGs
phylocli/phylo submit generax dig.CathepsinC1.HG1 --set MAX_SPR=2   # override a config.yaml param
# --set only accepts keys under params: in config.yaml; the submission's config (with the
# overrides) is saved as runs/<run>/config.yaml and the jobs read that copy (02/10/2026).
phylocli/phylo missing tree | head                      # HGs without a tree that have an alignment
phylocli/phylo missing tree --all | wc -l               # every HG without a tree
phylocli/phylo submit tree --missing -n                 # dry run: show groups, resources, run dir
phylocli/phylo submit tree tfs.FAR_FHY3.HG1 tfs.Runt_Runx.HG1
phylocli/phylo submit align --ids ids.new.txt
phylocli/phylo jobs                               # pending/running/done/failed per submission
phylocli/phylo jobs --failed                      # failed HGs + state + .err log
phylocli/phylo jobs 29318676                      # one array: task | HG | state | log (--failed, --running)
```

## `status HG`: job history (added 02/10/2026)

Per stage: state from `results/` (done / ready / blocked) and the LATEST attempt (by submit
time) with its status and reason (137 -> "killed: out of memory?", 140 -> "time limit (SIGUSR2
warning)", 65 -> "stage produced no output", SLURM OUT_OF_MEMORY / TIMEOUT / CANCELLED, else
"exit N"), requested `cpus/mem/time` and used `peak RSS/realtime`. A `log (<stage>): ...` line is
printed for every stage whose latest attempt did not complete. `--history` lists all attempts
(Nextflow attempt number in `att`). `--ids` / `--fam` cannot be combined with an HG.

Sources (code: `history.py`):
- **Nextflow**: every `step2.nf` run in `<nextflow_dir>/.nextflow/history` (config key
  `nextflow_dir`, default = project root), read with `nextflow -log <temp file> log <run> -f ...`
  run in that directory (the temp `-log` file keeps `.nextflow.log` from being written into the
  project; `NXF_VER` defaults to 25.04.2). One attempt per task try; CACHED rows are skipped.
  Needs `nextflow` on PATH, otherwise a yellow warning and only phylocli jobs are shown.
  Log = `<workdir>/.command.err`. Note `nextflow log` itself may touch empty dirs in
  `.nextflow/plr/`.
- **phylocli**: `runs/*/jobs.tsv` + `ids_<k>.txt` + `array_<k>.sbatch` (requested), one `sacct`
  call for state / MaxRSS / elapsed (no `sacct`: state "unknown"). Log =
  `runs/<run>/logs/<stage>_<job>_<task>.err`.
- **Cache**: parsed attempts of FINISHED Nextflow runs are stored in `phylocli/history/nf_<run>.tsv`
  (env `PHYLOCLI_HISTORY` overrides the dir) and read instead of calling nextflow again; runs
  still marked running (`-`) are re-queried every time. The first call on a long history is slow
  (one nextflow start per run, ~2.5 min for 25 runs on 02/10/2026); later calls ~30 s (the
  still-"running" runs). Delete a cache file to force a re-read.

## Rules

- Output for the stage already exists -> error, nothing submitted (no `--force`), always.
- Unknown HG id, or stage not applicable (`generax`/`gxsup`/`possvm_prev` with
  `run_generax: false`) -> error, nothing submitted.
- HGs whose stage inputs do not exist yet, or that are already queued/running in an earlier
  `phylo-<stage>` array, are SKIPPED by default ("skipped N HGs without inputs" / "... already
  queued"), and the rest is submitted. With `--all` (strict) they are errors instead and the
  whole submission is refused.
- Errors list the offending ids per reason and end with "nothing submitted".

`missing STAGE` lists the HGs not done for STAGE whose inputs exist, i.e. the ones that can
run now; `--all` lists every HG not done (30/09/2026). Stage order: `align`, `tree`, then
`possvm_prev` and `generax`, then `gxsup`, then `possvm`.

## Runs and logs

Each submission creates `phylocli/runs/<YYYYmmdd-HHMMSS>_<stage>/` with `ids_<k>.txt` (one
per resource group), `array_<k>.sbatch`, `jobs.tsv` (job id -> ids file, used by `jobs` and
the queued check), `work/` (per-HG scratch) and `logs/<stage>_<arrayjob>_<task>.{out,err}`.
A dry run (`-n`) does not touch `runs/`: its scripts go to `$TMPDIR/phylocli-dryrun/<ts>_<stage>/`
(path printed at the end), so `runs/` only holds real submissions (30/09/2026).
Jobs are named `phylo-<stage>`, partition `genoa64`, QoS `normal` (`long` for `tree` with more
than 500 sequences). Resources: the HG's `resources.tsv` row if it has one, else step2's attempt-1 defaults;
`submit` prints how many selected HGs had a row. `--mem/--time/--cpus` override that for every
selected HG. No retry ladder. Outputs are
published to `results/<dir>/` only on success (marker file last).

## config.yaml

`phylocli/config.yaml` holds `outdir`, `partition`, `qos` and the step2 parameters the stages
read (`MAFFT_OPT`, `TREE_METHOD`, `IQTREE2_MODEL`, `SUBS_MODEL`, `SPECIES_TREE`, `MAX_SPR`,
`NCPU_GENERAX`, `REFNAMES`, `REFSPECIES`, `run_generax`, `gxsup`, `resources_tsv`). Values
mirror `nextflow.config` + the `precise` profile and the 24/09/2026 run
(`-profile slurm,precise --run_generax`). Override the file with `PHYLOCLI_CONFIG=...`, the
runs directory with `PHYLOCLI_RUNS=...`.

## Nextflow caveat and backup

`step2.nf` process script strings were replaced by calls to `phylocli/stages/*.sh` (30/09/2026).
Nextflow task hashes include the script text, so `nextflow run ... -resume` will NOT reuse
tasks cached before the change; they re-run. Fill gaps with `phylo submit` instead, or run
Nextflow on a fresh id list. The original is `step2.nf.bak-20260930` (restore with
`cp step2.nf.bak-20260930 step2.nf`).

## Typical loop

```
phylocli/phylo status
phylocli/phylo submit tree --missing -n           # check (dry run)
phylocli/phylo submit tree --missing
phylocli/phylo jobs
phylocli/phylo status                             # after the array finishes
```

Check `phylocli/runs/<ts>_<stage>/logs/*.err` for any HG that is still missing afterwards.
