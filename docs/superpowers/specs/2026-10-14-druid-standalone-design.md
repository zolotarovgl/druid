# druid — phylocli as a standalone tool (design)

Grygoriy, 14/10/2026. Status: sub-project 1 designed; 2–4 scoped only.

## Goal

A standalone tool, **druid**, grown out of phylocli (the phylohpc `phylocli` branch, which was the
playground for it). After cloning, a user defines the species and gene families in the TUI, edits the
config interactively, and runs the whole pipeline (prepare → search → cluster → align → tree → generax
→ gxsup → possvm) from scratch. phylohpc stays as it is; druid needs neither phylohpc nor phylocli.

Decisions (Grygoriy, 14/10/2026):

| # | decision |
|---|---|
| 1 | druid carries its own copies of every phylohpc helper it uses — independent of phylohpc and phylocli |
| 2 | species tree: the current curated tree ships with druid and is pruned to the selection; a selected species missing from it raises a warning |
| 3 | proteomes: any directory; the only requirement is that each fasta's file name starts with the species prefix. Default: Xavi's `/users/asebe/xgraubove/genomes/data` (601 `<sp>_long.pep.fasta`, 14/10/2026) |
| 4 | one install, many projects: `druid init <dir>` makes a project dir (the phylohpc "results inside the repo" layout is rejected) |
| 5 | whole-pipeline runs: a SLURM driver job (`druid run`) submits each stage's array when the previous one finishes; per-stage manual runs stay |
| 6 | families: a searchable shipped library (the 304 v3 rows) + an add-family form; the project CSV stays hand-editable |
| 7 | environment: `environment.yml` + `druid doctor`; on CRG the existing `phylo` env |
| 8 | v3: `druid adopt <dir>` opens an existing phylohpc project in place; phylocli is frozen and retires once druid covers v3 |
| 9 | **druid never writes outside the project directory** — see "Write boundary" |

## Sub-projects (each: own spec section → plan → SDD)

1. **Repo + project dir** (this spec, detailed below): the split, `init` / `adopt` / `doctor`, the write boundary, `environment.yml`.
2. **Setup screens + `prepare`**: species picker over `proteomes_dir` (taxonomy from a `genome_sources_*.tsv`, warning for species not on the tree), family library + form (Pfam names checked against `pfam_db`, custom `.hmm` accepted), config editor; `prepare` builds `data/input.fasta`, the pruned trees and `species_info.tsv`.
3. **`druid run`**: the driver job, stage chaining, progress and stop in the TUI.
4. **Counts heatmap**: `docs/superpowers/specs/2026-10-14-phylocli-counts-heatmap-design.md`, retargeted to druid.

Sub-projects 2–4 get their own design pass before their plans.

## Sub-project 1

### Repo

- Dev clone: `/home/grygoriyzolotarov/Documents/projects/phylogenies/druid`; remote `github.com/zolotarovgl/druid` (created only after Grygoriy confirms); run clone on the cluster at `~/projects/druid`.
- History: `git filter-repo --subdirectory-filter phylocli` on a fresh clone of phylohpc branch `phylocli` (82 commits touching `phylocli/`, 14/10/2026); then `git mv` into the `druid/` package. phylohpc itself is not modified.
- The two specs (this one, the counts heatmap) are copied into `druid/docs/superpowers/specs/`.

### Layout

```
druid/                 python package
  cli.py               was phylo.py (typer app; entry `druid`)
  core.py model.py tui.py runner.py history.py common.py
  paths.py             NEW: project discovery + the write gate
  stages/*.sh          the 8 stage scripts
  helpers/             vendored from phylohpc workflow/: og_origin.py report_status.py
                       possvm_postprocess.py reroot_to_generax.py remove_gaponly.py drop_small_hgs.py
                       + VENDORED (phylohpc commit, date)
  vendor/treeview/     as now (update_treeview.sh)
  data/                shipped: species_tree.binary.newick, species_tree.newick, species_info.tsv,
                       families_library.csv (= v3 data/gene_families_searchinfo.csv, 304 rows),
                       Mmus_gene_names.csv
submodules/phylogeny   git submodule github.com/zolotarovgl/phylogeny (carries possvm-orthology nested)
bin/druid              wrapper
environment.yml
tests/
```

`phylogeny` stays a submodule (it is a separate repo, not phylohpc code): `git clone --recurse-submodules`.

### Two roots replace `ROOT`

- **`DRUID_HOME`** — the install (stages, helpers, `submodules/phylogeny`, shipped data). Read-only to druid.
- **`PROJECT`** — `druid.yaml`, `data/`, `results/`, `runs/`, `history/`, `.druid/tmp/`. Found by: `--project DIR`, else `$DRUID_PROJECT`, else walking up from the cwd to the first dir with a `druid.yaml` (as git does). No project found → error naming the three ways.
- Stage scripts get `DRUID_HOME` and `PROJECT_DIR`; `${PROJECT_DIR}/phylogeny/main.py` becomes `${DRUID_HOME}/submodules/phylogeny/main.py`, `${PROJECT_DIR}/workflow/X.py` becomes `${DRUID_HOME}/druid/helpers/X.py`.
- `PHYLOCLI_CONFIG` / `PHYLOCLI_RUNS` become `DRUID_PROJECT`; per-project paths come from `druid.yaml`.

### Write boundary

**druid writes only inside `PROJECT`.** Everything else — the proteome directory (Xavi's above all),
`pfam_db`, `hmm_dir`, the druid install, other projects — is read-only.

- One gate: `paths.writable(p) -> Path` resolves `p` (symlinks followed) and raises `OutsideProject` unless it lies under the resolved `PROJECT`. Every write in druid goes through it: config, runs, history cache, publish, treeview `w`, `init`, `adopt`.
- Stage work dirs: `PROJECT/runs/work/`; SLURM logs under `PROJECT/runs/`; temp files (incl. the `nextflow -log` temp in `history.py`) in `PROJECT/.druid/tmp/` — never `/tmp`.
- Proteomes are only read, by `prepare` (sub-project 2), which concatenates them into `PROJECT/data/input.fasta`. Stages never receive a proteome path, so no tool can write back through a symlink.
- `pfam_db`: `doctor` checks that `.h3m .h3i .h3f .h3p` exist; it never runs `hmmpress` (that writes next to `Pfam-A.hmm`). Missing → it says so.
- `hmm_dir`: `search.sh` already copies it; unchanged.
- treeview `w` (embedded): the prompt is prefilled inside `PROJECT`; a path outside it is refused.
- The publish step (`runner.publish`) writes only into `results/` under `PROJECT`; inputs symlinked into a work dir are never opened for writing (`_copy_atomic` copies *into* the dest only).

### Commands

- **`druid init <dir>`** — refuses a non-empty dir. Writes `druid.yaml` (phylocli's current params, plus `proteomes_dir: /users/asebe/xgraubove/genomes/data`, `proteome_glob: "{sp}_long.pep.fasta"`, `species: []`, `families: data/families.csv`; `pfam_db` default Xavi's), copies the shipped trees and `species_info.tsv` into `data/` (a project stays frozen when druid updates), and an empty `data/families.csv`.
- **`druid adopt <dir>`** — for an existing phylohpc project (v3). Writes only `<dir>/druid.yaml`, generated from `<dir>/phylocli/config.yaml` and mapped to the phylohpc layout: `runs_dir: phylocli/runs` (history stays one), `nextflow_dir: .`, `families: data/gene_families_searchinfo.csv`, helpers from `DRUID_HOME`. Sets **`prepare: locked`**: druid never rebuilds a curated `input.fasta` (v3 `PROVENANCE.md`: rebuilding from xgraubove breaks the 11 diverged species' ids and exits 0). On v3 the `druid.yaml` write follows the usual deploy: backup, per-file copy, md5 check.
- **`druid doctor`** — checks: every tool the stage scripts call on PATH with its version (hmmsearch, mafft, iqtree2, generax, clipkit, …, the list read from the stage scripts), python packages (textual >= 8.2, < 9; ete3 3.1.3; rich 14–15; typer; pyyaml), `submodules/phylogeny` present, `pfam_db` readable and pressed, `proteomes_dir` readable, `sbatch` on PATH, species tree parses. Prints one line per check; exits non-zero on any failure.
- All existing `phylo` subcommands and the TUI keep their behaviour under `druid`.

### Environment

`environment.yml` pinned from the CRG `phylo` env (read-only: `conda env export`; nothing is installed into `phylo`). Python 3.9 compatible code throughout (the env's version).

### Tests

- The 402 phylocli tests move over, imports renamed; fixtures build a temporary project via `druid init` instead of relying on `ROOT`.
- New: `paths` discovery order; `writable` refuses outside paths, a symlink pointing out, and `..` escapes.
- New: a sandbox run of one HG through align with the proteome dir and `DRUID_HOME` made read-only (`chmod -R a-w`), asserting their content/mtimes are unchanged and every new file is under `PROJECT`.
- New: a lint test failing on any write call (`open(..., "w"/"a")`, `write_text`, `shutil.copy*`, `os.replace`, `mkdir`) outside `paths`-gated sites.
- treeview tests stay in the treeview repo.

### Acceptance (v3, read-only except `druid.yaml`)

- `druid status` output equals `phylo status` for 5 families and 5 HGs, `tfs.T-box.HG1` among them.
- TUI overview counts equal phylocli's.
- `druid doctor` passes in the `phylo` env.
- No Nextflow previews are run in v3.

### Not in sub-project 1

Setup screens, `prepare`, `druid run` (sub-projects 2–3): after sub-project 1, `init` makes a project
that cannot run yet. Counts heatmap (4). phylocli gets no further changes.
