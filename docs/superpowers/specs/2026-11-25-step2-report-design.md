# Step-2 HTML report in druid (`druid report`) — design

Approved by Grygoriy, 25/11/2026 (short design, chat: "vendor the report script").

## Intent

The Nextflow step 2 ended with a `REPORT` process that wrote `report_step2.html`, a self-contained
interactive page (species × family heatmap with the species-tree cladogram, family → HG
drill-down, gene-tree explorer with OG labels). druid dropped it when step 2 moved off Nextflow
(chain spec 2026-11-02: "drop it for now"); only its Counts tab was ported (TUI `H`, 11/11/2026).
Grygoriy wants the report back for druid projects.

## Measured (25/11/2026)

- `workflow/report_step2.py` is byte-identical in `phylohpc`, `phylocli-wt` and
  `Phylogenies_v3` (md5 `f3d58a2c…`, 11,585 lines, last commit `f0fc039`, 29/08/2026).
  Standard library only.
- Phylogenies_v3 run (2,258 HGs): `REPORT` took 3 min 9 s, peak RSS 1.9 GB (2 GB limit), output
  95 MB (`reports/trace.step2.txt`).
- Its CLI: `--results_dir --possvm_dir --possvm_prev_dir --search_dir --cluster_dir --family_info
  --species_tree --species_images --species_info --refnames --refsps --align_dir --output`.
- **Correction (26/11/2026):** the script is NOT standard-library only. It needs `ete3` for the
  species tree and every gene tree (`report_step2.py:796`, `:925-928`, `:1014`); each import
  catches the `ImportError`, prints an error and carries on, so without ete3 the job writes a
  report with 0 trees and exits 0. druid refuses unless `python3 -c 'import ete3'` succeeds with
  `PYTHONNOUSERSITE=1` (as the job runs it), and the job repeats that import before the script.
- **Correction (26/11/2026):** `-f <class>.<family>` (e.g. `tfs.T-box`) is not narrowed by the
  filtered family table alone: `load_family_info` maps the class to itself (`:77-84`) and a file is
  kept when its class prefix is in that map (`:101-104`, `:11263-11264`), so every `tfs.*` tree
  stayed. druid passes `--possvm_dir`, `--possvm_prev_dir`, `--search_dir` and `--cluster_dir` as
  symlink views in the run dir (`view/<dir>/`) holding only that family's files; `align/` is read
  per kept tree id and needs none. Whole-project and class-level (`-f tfs`) runs are unchanged.

## Design

- **Vendor** the script as `druid/vendor/report_step2/report_step2.py` with a `VENDORED` file
  (`source`, `commit`, `date`), like treeview. Never edited by hand; refreshed by
  `druid/vendor/update_report.sh` (same approach as `update_treeview.sh`: `git archive` of a clean
  commit of the phylohpc repo).
- **`druid report [-f PREFIX] [-n] [--mem] [--time]`** writes `runs/<timestamp>_report/` with
  `report.sbatch` (+ a filtered family table when `-f`) and submits one SLURM job:
  job name `<job_prefix>-report`, the project's partition/qos, 1 CPU, 4G, 30 min by default.
  `-n` writes the script under the dry-run dir and does not submit. The job runs
  `python3 <druid>/druid/vendor/report_step2/report_step2.py` with:
  `--results_dir <outdir>`, `--possvm_dir <outdir>/possvm`, `--possvm_prev_dir
  <outdir>/possvm_prev`, `--search_dir <outdir>/search`, `--cluster_dir <outdir>/clusters`,
  `--align_dir <outdir>/align`, `--family_info <genefam_info or the -f filtered copy>`,
  `--species_tree <params.SPECIES_TREE>` (the tree the run used, as step2.nf),
  `--species_info data/species_info.tsv`, `--refnames <params.REFNAMES>` and
  `--refsps <params.REFSPECIES>` when set, `--species_images <params.report_images>` when set,
  `--output <outdir>/report_step2.html` (or `report_step2.<PREFIX>.html` with `-f`).
- **TUI**: one key on the Results tab submits `druid report` (whole project) and the Results
  header shows the report's path and age (mtime), or "no report".
- Writes only inside the project (`runs/`, `outdir`). Refuses with a clear message when there
  are no `possvm`/`possvm_prev` outputs yet, or `job_prefix` is unset.

## Approaches

- SLURM job (chosen): 1.9 GB / 3 min for v3 is too heavy for a login node.
- Run in-process on the login node: rejected for that reason.
- Port the report into the TUI: rejected; the HTML is for a browser and for sharing.

## Non-goals

- Generating the report automatically when possvm finishes (waits for chains).
- Shipping species images: `phylohpc/img/phylo` (139 PNGs, 8.4 MB) is not in git and its source
  is unknown; `params.report_images` can point at a directory.
- Changing the report's content.

## Left to the builder

Where the sbatch text lives; the TUI key (a free one on Results); how the job id is shown; tests.
