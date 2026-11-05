# druid

`druid` reports step1 + step2 progress (per stage) of the gene-family phylogeny pipeline and
submits one SLURM job array per resource group for a single stage, without Nextflow. It grew out
of `phylocli` (the phylohpc `phylocli` branch) and needs neither phylohpc nor phylocli: the stage
scripts in `druid/stages/` are the step1.nf / step2.nf process bodies, and the helpers they call
are vendored. One install serves many projects; a project is a directory with a `druid.yaml`, and
druid never writes outside it (see Write boundary).

## TL;DR: new project to step 1

```bash
conda activate phylo                       # on the cluster (login1)
druid init /no_backup/<lab>/$USER/myproject   # e.g. /no_backup/asebe/$USER/myproject; opens Setup
```

`/no_backup` is split by lab, then user: use your own lab directory (`ls /no_backup`).

In **Setup** (`tab` moves between panes, `enter` selects, `esc` / `q` back, `:q!` quits):

1. **Project**: type a `job_prefix` (e.g. `chromo`), `enter`. Jobs are named `chromo-search`, ….
2. **Species**: type prefixes (`Mlei, Hsap Nvec`) or any filter, `enter` ticks all shown.
   In the list: `space` one, `a` ticks all shown, `A` unticks all shown (same in Families).
3. **Analyses**: GeneRax / origins on or off (both off: no species tree needed).
4. **Tree** (only if a switch is on): place ticked species missing from the tree.
5. **Families**: filter, `a` ticks all shown (`space` / `enter` one at a time).
6. **Parameters** (optional; the defaults run): the stage settings, grouped by stage. Clustering
   (MCL inflation default, recluster size, domain expand, cpus), Alignment (MAFFT: linsi · einsi ·
   ginsi · auto), Phylogeny (fasttree / iqtree2 / iqtree3, IQ-TREE model, min seqs / min distinct),
   GeneRax (substitution model, SPR radius, cpus; greyed when GeneRax is off), POSSVM (reference
   species from the ticked ones, reference gene-names file). Lists: `enter` opens, `↑↓ enter`
   picks; numbers and the path: type, `enter` writes (a bad value is refused, nothing written).
   A value in `druid.yaml` outside the lists is shown as `custom: <value>` and kept. From the first
   job on, everything but the cpus is read-only (it would change every output). A family's own
   `inflation` (Families, `e`) overrides the default.
7. `P` prepares (`data/input.fasta`, trees, `species_info.tsv`), then `S` launches step 1:
   `enter` dry run, `y` submits search + linked cluster.

Or from the shell, after Setup: `druid prepare`, `druid run -n` (dry run), `druid run`.
Step 2 (align → possvm) is submitted by hand afterwards: `druid submit <stage> --missing`.
Reopen the project with `druid --project /no_backup/<lab>/$USER/myproject tui`.

## Contents

- [TL;DR: new project to step 1](#tldr-new-project-to-step-1)
- [Install](#install)
- [Projects](#projects)
- [Write boundary](#write-boundary)
- [Commands](#commands)
- [Rules](#rules)
- [Runs and logs](#runs-and-logs)
- [druid.yaml](#druidyaml)
- [Environment variables](#environment-variables)
- [Typical loop](#typical-loop)
- [druid tui](#druid-tui)
- [Nextflow caveat](#nextflow-caveat-phylohpc-projects)
- [Tests](#tests)
- [Layout](#layout)

## Install

```
git clone --recurse-submodules https://github.com/zolotarovgl/druid     # or, in a clone: git submodule update --init --recursive
conda env create -f environment.yml          # name: druid; on CRG you can use the existing `phylo` env instead
conda activate druid                         # CRG: conda activate phylo
module load OpenMPI                          # CRG: mpirun for generax, if the env has none (the `phylo` env has none)
bin/druid doctor                             # checks everything below; reads only, fixes nothing
```

`environment.yml` was exported read-only from the CRG `phylo` env on 14/10/2026
(`conda env export -n phylo --no-builds`); nothing was installed into `phylo`. That env's
`openmpi 4.1.3` conda package has an empty file list (no `mpirun`), hence `module load OpenMPI`; a
fresh env from `environment.yml` is expected to provide `mpirun`, but this is unverified. Code is Python 3.9
compatible (that env's version). Put `bin/druid` on your `PATH` (or call it by path); it resolves
its own install through symlinks.

`druid doctor` prints `OK   name  detail` or `FAIL name  detail` per check and exits 1 on any FAIL:
every tool the stages call, on PATH with its version (`hmmsearch hmmfetch bedtools samtools mafft
clipkit iqtree2 diamond mcl generax mpirun sbatch squeue sacct`), the python packages (textual
>= 8.2 < 9, ete3 >= 3.1.3, rich 14-15, typer, PyYAML, Biopython), `submodules/phylogeny` with its
nested `possvm-orthology` and, when a project is found, its `druid.yaml`, `pfam_db` (readable
and pressed: `.h3m .h3i .h3f .h3p`), `proteomes_dir` (one file per species) and the species
tree. Without a project (none found by walking up from the cwd) it prints `SKIP project ...` and still
checks the rest; a project you named with `--project` / `$DRUID_PROJECT` that has no `druid.yaml`
is `FAIL project` (exit 1). A `druid.yaml`
that cannot be loaded (bad YAML, a write target outside the project) is one `FAIL config` line.
It never runs `hmmpress`: a missing index is reported, and the owner of `Pfam-A.hmm` presses it.

`submit` runs its own preflight: it checks the tools the stage needs (search: hmmsearch, hmmfetch,
bedtools, samtools, and that `genefam_info`, `infasta`, `pfam_db` exist; cluster: samtools,
diamond, mcl; align: mafft, clipkit; tree and gxsup: iqtree2; generax: generax, mpirun) and, for
every stage except `gxsup`, that `PYTHONNOUSERSITE=1 python -c "import ete3, Bio, yaml"` works
(the `python` the stage scripts use). On failure it names the interpreter and the import error,
and exits 78 with nothing written. Arrays are split into chunks of at most 1000 HGs (SLURM
MaxArraySize), each chunk its own `ids_<k>.txt` / `array_<k>.sbatch` / sbatch call.

## Projects

```
druid init DIR       # (--no-tui: stay in the shell, otherwise opens the TUI on DIR) new or empty directory: druid.yaml + data/ (shipped trees, species_info.tsv, Mmus names, empty families.csv)
druid adopt DIR      # an existing phylohpc project (has phylocli/config.yaml): writes only DIR/druid.yaml
```

`init` refuses a non-empty directory. `adopt` refuses a directory that already has a `druid.yaml`,
one without `phylocli/config.yaml`, and a config that is not a valid YAML mapping; each is one
`ERROR:` line, exit 2, nothing written. `adopt` maps the old config onto the phylohpc layout
(`runs_dir: phylocli/runs`, `nextflow_dir: .`; the run history stays one) and sets
`prepare: locked`: `data/input.fasta` is curated, and druid never rebuilds it (rebuilding from the
xgraubove proteomes breaks 11 species' ids and exits 0; v3 `PROVENANCE.md`).

The project is found in this order (`druid/paths.py`):

1. `--project DIR` / `-P DIR`, given before the subcommand: `druid -P DIR status`
2. `$DRUID_PROJECT`
3. the nearest directory at or above the cwd that has a `druid.yaml`

An explicit choice (1 or 2) whose directory has no `druid.yaml` is an error, not a fallback.
With no project, every command except `init`, `adopt` and `doctor` exits 2 and says how to pick one.

## Write boundary

**druid writes only inside the project directory.** Config copies, runs, work dirs, logs, the
history cache, publish into `results/`, temp files (`<project>/.druid/tmp/`, never `/tmp`), the
treeview `w` prompt, `init` and `adopt` all go through one gate (`paths.writable`), which resolves
symlinks and refuses a path outside the project. A config whose `outdir`, `runs_dir`, `infasta`
or `genefam_info` points outside is refused when it is loaded (`ERROR: ...`, exit 2, like any
unreadable, malformed or incomplete `druid.yaml`; `adopt` runs that check before it writes). A lint test
(`tests/test_write_boundary.py`) fails on any write call in `druid/*.py` outside `paths.py`.

This binds druid's own files. The external tools a stage runs (mafft, iqtree2, diamond, ...) may
still use `$TMPDIR` (for example `/tmp`) for their own scratch; druid does not redirect them.

Read-only, always: the proteome directories (above all `/users/asebe/xgraubove/...`), `pfam_db`,
`hmm_dir`, the druid install (`DRUID_HOME`) and other projects. Stages never receive a proteome
path. **druid never runs `hmmpress`** (it writes next to `Pfam-A.hmm`); `druid doctor` only tells
you the index is missing.

## Commands

```
druid [-P DIR] init DIR
druid [-P DIR] adopt DIR
druid [-P DIR] doctor
druid status [--ids PATH] [--fam/-f PREFIX]
druid status HG|FAMILY [--history]
druid missing [STAGE] [--ids PATH] [--fam/-f PREFIX] [--all] [--per-fam]
druid submit STAGE [HGS]... [--missing] [--ids PATH] [--fam/-f PREFIX] [--all] [-n/--dry-run]
                   [--max-running INTEGER] [--partition TEXT] [--qos TEXT]
                   [--mem 16G] [--time 24h] [--cpus 8] [--set KEY=VALUE]...
druid run [--fam/-f PREFIX] [-n/--dry-run] [--max-running INTEGER] [--partition TEXT] [--qos TEXT]
          [--mem 16G] [--time 24h] [--cpus 8]
druid jobs [--stage TEXT] [--last N] [--failed]
druid tui [--refresh 30]
```

STAGE is one of `search cluster align tree possvm_prev generax gxsup possvm`. `search` and
`cluster` (step1) work on FAMILY ids `<pref>.<family>` (genefam column 1 and its last non-empty
field, e.g. `slc.SLC25`), the others on HG ids. `submit` takes exactly one of: ids,
`--ids FILE`, or `--missing`. `--fam` takes a category (`tfs`) or a family
(`tfs.T-box`), matched on whole dot-separated id parts (`tfs.T-box` does not match `tfs.T-box2`).

`druid run` is step 1 in one command (25/10/2026): it submits a `search` array for the families
not yet searched, a `cluster` array for each of those that waits on its search task (task by task,
`--dependency=aftercorr`; a cluster task whose search task fails is cancelled and shows as
`cancelled: search failed`, not as a cluster failure), and cluster-only arrays for families
already searched. Families already done, queued, without hits or failing a check are skipped
with a note. `-n` writes the scripts and prints the arrays without submitting. Step 2 (align,
tree, ...) stays manual: `druid submit` once the clusters exist.

Every SLURM job is named `<job_prefix>-<stage>`; `job_prefix` is required (see `druid.yaml`), and
`submit` / `run` refuse without it.

```
druid status                                   # per stage: done / running / ready / blocked bars; "N/M HGs done"
# running = pending or running in SLURM now (squeue): druid array tasks AND Nextflow jobs (nf-<PROCESS>_(<HG>));
# running HGs are not counted as ready, `missing STAGE` leaves them out and `submit` skips them (07/10/2026)
druid status -f tfs.T-box                      # same, one family only
druid status dig.CathepsinC1.HG1               # one HG: state per stage + latest job (requested vs used)
druid status dig.CathepsinC1.HG1 --history     # one HG: every attempt, oldest first, with .err log paths
druid missing                                  # same counts; bar shows only what is left (ready green)
druid missing tree -f tfs | head               # tfs HGs ready for a tree
druid missing generax -f tfs --per-fam --all   # per family "missing/total", e.g. tfs.HLH 1/9
druid submit generax --missing -f tfs          # all ready tfs HGs lacking GeneRax
druid submit tree tfs.zf-C2H2.HG1 --mem 32G --time 2d   # override resources for these HGs
druid submit generax dig.CathepsinC1.HG1 --set MAX_SPR=2   # override a druid.yaml param
# --set only accepts keys under params: in druid.yaml; the submission's config (with the
# overrides) is saved as runs/<run>/config.yaml and the jobs read that copy (02/10/2026).
druid missing tree | head                      # HGs without a tree that have an alignment
druid missing tree --all | wc -l               # every HG without a tree
druid submit tree --missing -n                 # dry run: show groups, resources, run dir
druid submit tree tfs.FAR_FHY3.HG1 tfs.Runt_Runx.HG1
druid submit align --ids ids.new.txt
druid jobs                                     # pending/running/done/failed per submission
druid jobs --failed                            # failed HGs + state + .err log
druid jobs 29318676                            # one array: task | HG | state | log (--failed, --running)
druid missing search                           # families never searched (new genefam rows)
druid submit search --missing -n               # dry run; then without -n
druid missing cluster                          # searched, with hits, not clustered
druid submit cluster --missing
druid status slc.SLC25                         # one family: search / cluster state + latest job
```

### `status HG`: job history (added 02/10/2026)

Per stage: state from `results/` (done / ready / blocked) and the LATEST attempt (by submit
time) with its status and reason (137 -> "killed: out of memory?", 140 -> "time limit (SIGUSR2
warning)", 65 -> "stage produced no output", SLURM OUT_OF_MEMORY / TIMEOUT / CANCELLED, else
"exit N"), requested `cpus/mem/time` and used `peak RSS/realtime`. A `log (<stage>): ...` line is
printed for every stage whose latest attempt did not complete. `--history` lists all attempts
(Nextflow attempt number in `att`). `--ids` / `--fam` cannot be combined with an HG.

Sources (code: `druid/history.py`):
- **Nextflow**: every `step2.nf` run (and, for the search / cluster rows, every `step1.nf` run) in `<nextflow_dir>/.nextflow/history` (config key
  `nextflow_dir`, default = project root), read with `nextflow -log <temp file> log <run> -f ...`
  run in that directory (the temp `-log` file, under `<project>/.druid/tmp/`, keeps `.nextflow.log`
  from being written into the project; `NXF_VER` defaults to 25.04.2). One attempt per task try;
  CACHED rows are skipped. Needs `nextflow` on PATH, otherwise a yellow warning and only druid
  jobs are shown. Log = `<workdir>/.command.err`. Note `nextflow log` itself may touch empty dirs
  in `.nextflow/plr/`. A project with no Nextflow history simply has none of these.
- **druid**: `<runs_dir>/*/jobs.tsv` + `ids_<k>.txt` + `array_<k>.sbatch` (requested), one `sacct`
  call for state / MaxRSS / elapsed (no `sacct`: state "unknown"). Log =
  `<runs_dir>/<run>/logs/<stage>_<job>_<task>.err`.
- **Cache**: parsed attempts of FINISHED Nextflow runs are stored in `<runs_dir>/../history/nf_<run>.tsv`
  (`$DRUID_HISTORY` overrides the dir; it must be inside the project) and read instead of calling
  nextflow again; runs still marked running (`-`) are re-queried every time. The first call on a
  long history is slow (one nextflow start per run, ~2.5 min for 25 runs on 02/10/2026); later
  calls ~30 s (the still-"running" runs). Delete a cache file to force a re-read.

## Rules

- Never run `step1.nf` while `phylo-search` / `phylo-cluster` arrays are queued or running, and never
  submit search / cluster while a `step1.nf` run is active: both publish to `search/` and
  `clusters/`, so two clusterings of one family can mix. `submit search|cluster` prints a warning
  on stderr when a `step1.nf` run looks active (history status `-`); it still proceeds.
- Output for the stage already exists -> error, nothing submitted (no `--force`), always.
- Unknown HG id, or stage not applicable (`generax`/`gxsup`/`possvm_prev` with
  `run_generax: false`) -> error, nothing submitted.
- HGs whose stage inputs do not exist yet, or that are already queued/running in an earlier
  `phylo-<stage>` array, are SKIPPED by default ("skipped N HGs without inputs" / "... already
  queued"), and the rest is submitted. With `--all` (strict) they are errors instead and the
  whole submission is refused.
- Errors list the offending ids per reason and end with "nothing submitted".
- `search` / `cluster`: done = `search/<id>.domains.fasta` exists / `clusters/<id>_cluster.tsv`
  exists (or the domains FASTA is empty: "no hits", counted as done). `search` is always ready;
  `cluster` is ready when the domains FASTA is non-empty. HG FASTAs in `clusters/` without a
  `_cluster.tsv` count as existing output (two clusterings must not mix). `--per-fam` is an error.
- A duplicated family id in the genefam file is a warning, never an error: the summaries, the
  TUI banner and every search/cluster command print it and go on; the last row of the id is used,
  as `main.py hmmsearch` and step1.nf do (09/10/2026: `slc.SLC44`, `neu.Synapsin`).
- A family NAME under two prefixes (`rbp.CSD` / `tfs.CSD`): `main.py hmmsearch` keys rows by name
  (the last row wins), so `rbp.CSD`'s hits are written as `tfs.CSD.*` and `rbp.CSD` is published
  empty ("no hits"), as in step1.nf. `search` prints a `WARNING` saying so; the summaries, the TUI
  banner and `submit search` list every such name beforehand.
- `cluster` writes `<id>.HG<n>.fasta` only for HGs with >= `min_seqs` sequences and >=
  `min_distinct` distinct ones (the rule step2 uses); `<id>_cluster.tsv` stays complete, so HG
  numbers have gaps. It prints `skipped <k> HGs below min_seqs/min_distinct`.

`missing STAGE` lists the HGs not done for STAGE whose inputs exist, i.e. the ones that can
run now; `--all` lists every HG not done (30/09/2026). Stage order: `align`, `tree`, then
`possvm_prev` and `generax`, then `gxsup`, then `possvm`.

## Runs and logs

Each submission creates `<runs_dir>/<YYYYmmdd-HHMMSS>_<stage>/` (`runs_dir` is `runs` in a new
project, `phylocli/runs` in an adopted one) with `ids_<k>.txt` (one per resource group),
`array_<k>.sbatch`, `jobs.tsv` (job id -> ids file, used by `jobs` and the queued check), `work/`
(per-HG scratch) and `logs/<stage>_<arrayjob>_<task>.{out,err}`. A dry run (`-n`) does not touch
the runs dir: its scripts go to `<project>/.druid/tmp/dryrun/<ts>_<stage>/` (path printed at the
end), so the runs dir only holds real submissions (30/09/2026).
Jobs are named `phylo-<stage>`, partition `genoa64`, QoS `normal` (`long` for `tree` with more
than 500 sequences). Resources: the HG's `resources.tsv` row if it has one, else step2's attempt-1 defaults;
`submit` prints how many selected HGs had a row. `--mem/--time/--cpus` override that for every
selected HG. No retry ladder. Outputs are
published to `results/<dir>/` only on success (marker file last).
A `search` or `cluster` submission copies the genefam file to `<run>/genefam.csv` and its run-dir
`config.yaml` points there: the jobs search the rows that were validated, and cluster with the
family's `inflation` as it was, even if the file is edited while they wait in the queue. (The configuration copy inside a run directory is always
named `config.yaml`; the project's own file is `druid.yaml`.)

## druid.yaml

`<project>/druid.yaml` holds `outdir`, `runs_dir`, `nextflow_dir`, `partition`, `qos`, `prepare`
(`auto`, or `locked` for an adopted project), `proteomes_dir` / `proteome_glob` / `species`, and
`params:` with the step1 parameters (`genefam_info`, `infasta`, `pfam_db`, `hmm_dir`,
`domain_expand`, `s1_ncpu`, `s2_ncpu`, `max_n`, `s2_inflation`) and the step2 parameters the
stages read (`MAFFT_OPT`, `TREE_METHOD`, `IQTREE2_MODEL`, `SUBS_MODEL`, `SPECIES_TREE`,
`ORIGIN_TREE`, `MAX_SPR`, `NCPU_GENERAX`, `REFNAMES`, `REFSPECIES`, `run_generax`, `gxsup`,
`resources_tsv`, `min_seqs`, `min_distinct`). `job_prefix` is required (Setup › Project in the
TUI, or `job_prefix:` in the file): 1-20 characters, letters, digits and `_`, starting with a
letter; jobs are named `<job_prefix>-<stage>`, and `druid jobs` / the TUI show only the jobs of
this project's own runs. An adopted project keeps its old `phylo-<stage>` names.
GeneRax runs with the substitution model IQ-TREE selected for the family (the
`Best-fit model:` line of `gene_trees/<HG>.log`, e.g. `WAG+F+I+G4`); `SUBS_MODEL` is used only
when there is none (FastTree, a fixed IQ-TREE model). Until 05/11/2026 GeneRax always ran with
`SUBS_MODEL`, so GeneRax trees made before then used LG for every family. Relative paths are relative to the project. Values
mirror `nextflow.config` + the `precise` profile and the 24/09/2026 run
(`-profile slurm,precise --run_generax`). `proteomes_dir`, `pfam_db` and `hmm_dir` are read-only
inputs and may point anywhere; everything druid writes (`outdir`, `runs_dir`, `infasta`,
`genefam_info`) must be inside the project. The template is `druid/templates/druid.yaml`.

The `inflation` column of the families file overrides `params.s2_inflation` for that family's
`cluster` run (blank = the default). Before 04/11/2026 the column was ignored, so families whose
value differs from the default cluster differently on their next cluster run.

## Environment variables

| variable | effect |
|---|---|
| `DRUID_PROJECT` | the project directory (used after `--project`, before the cwd search) |
| `DRUID_CONFIG` | read this file instead of `<project>/druid.yaml` |
| `DRUID_HISTORY` | the Nextflow history cache dir (default `<runs_dir>/../history`); must be inside the project |

## Typical loop

```
druid status
druid submit tree --missing -n           # check (dry run)
druid submit tree --missing
druid jobs
druid status                             # after the array finishes
```

Check `<runs_dir>/<ts>_<stage>/logs/*.err` for any HG that is still missing afterwards.

## druid tui

Full-screen view (Textual, textual >= 8.2, < 9, tested on 8.2.8: the header cursor and sort
arrows use only DataTable's public API, re-rendering a relabelled header through
`notify_style_update()`).

    druid tui [--refresh 30]

It opens on an overview: one row per category (`ALL` first), one bar per stage
(done / running / ready / blocked). `f` regroups by family, `c` back to category; `←→` picks
the stage column and `enter` opens the HG panels for that row at that stage (filter `failed`);
`esc` returns to the overview. The overview reads output files and squeue only; the slow
attempt history is read only once an HG view is open.

`s` sorts the overview by the highlighted column — a stage: most ready/failed first, ties by
running (on search/cluster: families); `group`: by name; `HGs`: by size — and `s` again
reverses. `h` shows only the rows with something to do (ready, failed or running) at the
highlighted stage (on search/cluster: families); `h` again shows all.
`ALL` stays on top, the pane title shows the state, and both survive refreshes and `c`/`f`.

`o` opens the **Results** window for the overview row under the cursor (`ALL` included); in the
HG view, for the highlighted HG's category/family (that HG highlighted) or, on search/cluster,
for the highlighted family's HGs. Four panes, `tab` between them: **Results** (every HG of the group
that is clustered, from the moment its cluster FASTA exists: `source` = `possvm`, `prev`
(possvm_prev only), `cluster` (not split yet: one row `(not split: no possvm yet)` in OGs holding
all its genes, read from the FASTA only when the HG is highlighted, so its `genes` cell in the HG list shows `–`) or `small` (below `min_seqs` / `min_distinct`, never reaches step 2); OGs, genes,
OGs with support 0 `⚠`; the footer counts the HGs without output). The Results tab's columns:
group, HGs, `with OGs` (possvm or possvm_prev), `cluster only`, OGs, genes, `⚠ sup 0`, **OGs** (the ortholog groups of the highlighted HG, largest first: OG, genes, spp,
support, name; no reference orthologs here: each gene has its own, shown in members), **members** (the highlighted
OG's rows of `*.ortholog_groups.csv`: gene, species, reference ortholog and support; `/` filters,
`enter` keeps the filter, `esc` clears it) and **species** (per phylum `k/m spp  n genes` with
the species and their counts, absent phyla last; the universe is the tips of
`params.SPECIES_TREE`, phyla from `data/species_info.tsv`). `p` cycles the source: `auto` (default; per HG
`possvm/` if it has output, else `possvm_prev/`, else the cluster FASTA) → `possvm/` (post-GeneRax)
→ `possvm_prev/` (raw IQ-TREE) → `auto`; a forced source lists only the HGs that have it. The Results tab's counts cover the expected HGs only; HGs below `min_seqs` / `min_distinct` are listed in the window as `small`. `esc` goes back. Support `0.0 ⚠` is the GeneRax bug
case: check `possvm_prev`. Files are read in the background.

`t` (in a group's Results) opens the gene tree of the highlighted HG in the embedded
treeview (vendored, below), from the HG's own source (`possvm` or `possvm_prev`; the border title says
which; a cluster-only HG has no tree): on the HGs pane the whole tree; on the OGs pane the OG's MRCA with its members bold
and underlined (`n`/`N` step through them; members missing from the tree are reported); on the
members pane that member's tip. The `*.ortholog_groups.csv` columns show as metadata (`t` in the
tree, `c` cycles the colouring). `esc` returns to Results unchanged (first `esc` clears the
underline/search). Not in the header row of a table: `↓` first. A missing tree is a warning, never a crash.
HGs with no tree to open (cluster only, or a csv without its tree file) are dimmed in the HGs pane.
In the tree, `<` `>` make the branches narrower / wider; the width holds for the trees opened later
in the session.
The tree opens with branch lengths to scale and collapsed by orthogroup (14/10/2026); the OG or
member it opens on stays expanded (`e` expands all, `l` drops the lengths). The tree's `w`
(write) prompt is prefilled inside the project and refuses a path outside it.

`?` lists every key, in druid and in the tree (`esc`, `?` or `q` closes it); the help line at
the top of each is one line (`… · ? keys`).

`search` and `cluster` are the first two columns and count FAMILIES (`ALL` = all families, a
category row = its families, a family row = that family); the `HGs` column stays the group's HG
count, so a family added to the genefam file shows as its own row with 0 HGs until `cluster`
has run. `enter` on a search/cluster cell lists that group's families (select, resubmit and log
work on family ids); the stages panel then counts families for search/cluster and HGs for the
other stages.

HG view panels: stages (top left) · HGs — or families, for search / cluster — of the highlighted stage (top right) · latest arrays
(bottom left) · details of the highlighted HG (bottom right). Refreshes in the background.

Keys (HG view): `↑↓` move · `tab` panel · `esc` overview · `f` filter (failed → ready → running → blocked → done) ·
`space` select · `a` select all shown · `A` unselect all shown · `r` resubmit selection · `x` submit every ready / failed HG of the stage · `l` last log · `o` results · `R` refresh ·
`S` run step 1 (`druid run`: `enter` dry run, `y` submit; also in Setup, which refuses while prepare is
running) · `q` quit. On the Jobs tab, `x` opens one box for every ready / failed HG and family of
every stage (one row per stage and resource reason; `enter` dry run, `y` submits one run per stage).

Resubmit: one row per resource group, pre-filled with the automatic bump (out of memory →
memory ×2, time limit → time ×2, other failures unchanged); memory and time are editable.
`enter` = dry run (nothing submitted), `y` = submit (the selection is re-checked first, so HGs
queued or finished meanwhile are skipped), `esc` = cancel.

### Vendored treeview

`druid/vendor/treeview/` is a generated copy of the treeview repo, imported as `treeview`.
Never edit it in place: change treeview, commit it there, then run

    TREEVIEW_REMOTE_REPO=host:path/to/treeview bash druid/vendor/update_treeview.sh

It copies the bytes of the repo's HEAD commit (`git archive`, tests excluded; refuses a dirty
repo) and records `source`, `commit` and `date` in `druid/vendor/treeview/VENDORED`. After
re-vendoring run `pytest tests/test_vendor.py`. Env: `TREEVIEW_REMOTE_REPO` (`host:path`,
git runs over ssh, or a local path), `VENDOR_DEST` (directory that gets `treeview/`).

## Nextflow caveat (phylohpc projects)

Only relevant to an adopted phylohpc project that still has Nextflow runs. In phylohpc,
`step2.nf` process script strings were replaced by calls to the stage scripts (30/09/2026).
Nextflow task hashes include the script text, so `nextflow run ... -resume` will NOT reuse
tasks cached before the change; they re-run. Fill gaps with `druid submit` instead, or run
Nextflow on a fresh id list. The original is `step2.nf.bak-20260930` (restore with
`cp step2.nf.bak-20260930 step2.nf`).

`step1.nf` `SEARCH` / `CLUSTER` call `search.sh` / `cluster.sh` (09/10/2026;
original: `step1.nf.bak-<date of the copy>`). step1.nf decides completeness from the published
outputs, not the resume cache: done families are skipped, but every task hash changes (the script text
is part of it), so families with hits and no `_cluster.tsv` get SEARCH rerun once. Nextflow hashes the
script text, not the contents of `search.sh` / `cluster.sh`, so later edits to those scripts do not
invalidate `-resume`.

A bare `nextflow run ... -resume` resumes the LATEST session, including one created by `-preview`.
After any preview pass the session id explicitly (e.g. `-resume e063a93b-76ce-4625-b8bf-5d1bee9f91bb`
for v3 step2).

## Tests

```
cd <druid clone>
python -m pytest tests -q -p no:cacheprovider      # Python 3.9 compatible; single process
```

Notable: `tests/test_write_boundary.py` (the write lint and the config refusals),
`tests/test_paths.py` (project discovery, the gate), `tests/test_project.py` (`init` / `adopt`),
`tests/test_doctor.py`, `tests/test_vendor.py` (the vendored treeview).

## Layout

```
bin/druid                 entry point (writes no byte-code into the install)
druid/                    python package
  cli.py                  the typer app (was phylo.py)
  core.py model.py runner.py history.py common.py tui.py
  paths.py                project discovery + the write gate
  project.py              init / adopt
  doctor.py               druid doctor
  stages/*.sh             the 8 stage scripts (search cluster align tree possvm_prev generax gxsup possvm)
  helpers/                vendored phylohpc helpers (og_origin, report_status, possvm_postprocess,
                          reroot_to_generax, remove_gaponly, drop_small_hgs); helpers/VENDORED has the source commit
  vendor/treeview/        the embedded tree viewer (update_treeview.sh)
  data/                   shipped: species trees, species_info.tsv, Mmus_gene_names.csv, families_library.csv
  templates/druid.yaml    what `druid init` writes
submodules/phylogeny      git submodule (zolotarovgl/phylogeny, carries possvm-orthology): main.py hmmsearch / phylogeny / generax
environment.yml           conda env, exported read-only from the CRG `phylo` env on 14/10/2026
docs/superpowers/         specs and plans
tests/
```
