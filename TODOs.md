# druid TODOs

Open work, newest first. Dates dd/mm/yyyy.

- **Watcher job that resubmits automatically** (Grygoriy, 02/11/2026): most TUI use is resubmitting
  jobs; find out whether one watcher job can do it on an interval. Overlaps with sub-project 5's
  `druid chain` driver (polls sacct, retries with more resources, advances stages) — decide whether
  the watcher is that driver or a lighter "resubmit failed/missing every N min" job.
  With it (Grygoriy, 02/11/2026): the job view gets one key that submits every ready (and failed)
  HG of the current stage, without selecting first (today: `a` then `r`, per filter).
- **Gene tree viewer layout** (Grygoriy, 02/11/2026): internal nodes on their own row between their
  children's tips (as PlaceScreen does with gap 0), not the current compact layout (gap -1).
- **Gene tree viewer: orthogroup collapse looks wrong** (Grygoriy, 02/11/2026): check that
  collapsing an OG hides exactly that OG's members (compare with `ortholog_groups.csv`).
  Grygoriy: named OGs (no `like:`) show no Mmus tips. Checked 02/11/2026 on all 2,258 v3 HGs
  (`g` collapse in the vendored model): 2,252 of 2,846 named OGs have all their Mmus tips in the
  collapsed clade(s); 585 whole-HG OGs are not collapsed (root, by design); 9 are not one clade
  (e.g. `adh.immunoglobin.HG7.13`, 20/21 Mmus inside). Not reproduced — need his HG / OG / source.
- **Gene tree viewer: narrower, adjustable width** (Grygoriy, 02/11/2026): the tree takes too much
  width; make the tree/labels split adjustable with keys (and remember it per session).
- **Per-user install** (Grygoriy, 02/11/2026: a shared lab install "is not an option"). First env
  build failed: the cluster miniconda (conda 23.7, no zstandard, `use_only_tar_bz2`) skips `.conda`
  packages, so a user's own conda cannot be relied on — use a standalone micromamba.
- **Installation test** (Grygoriy, 02/11/2026): how easy is it for a new user to install druid?
  Fresh account / clean env on the cluster, follow only the README (clone with submodules, env,
  `~/bin/druid`, `druid doctor`, `druid init`), and record every step that needed outside help.
- **Rename possvm stages for display** (Grygoriy, 02/11/2026, "for later"): show possvm_prev as
  `possvm` and possvm as `possvm_postGR` (GeneRax on); GeneRax off: one `possvm`, no n/a row. Labels
  only — result dirs, job names and run records keep the internal names; the CLI accepts both.
  Also: `druid status` footer says "done = possvm_prev" when possvm_prev is n/a.
  GeneRax off (Grygoriy, 02/11/2026): `druid status`, the TUI overview columns and pane 1 omit
  possvm_prev, generax and gxsup altogether instead of showing n/a rows.
- **Sub-project 5: step 2 as one chain** (`druid chain`, driver job, own retries, no Nextflow) —
  spec `docs/superpowers/specs/2026-11-02-druid-sub5-step2-chain-design.md`, awaiting review.
- **Sub-project 4: counts heatmap** (in progress 11/11/2026) — spec refreshed for druid:
  `docs/superpowers/specs/2026-11-11-druid-counts-heatmap-design.md`.
- **First real `druid run`** on a test project (`/no_backup/asebe/gzolotarov/druid-test-run`,
  prefix `drtest`) — Grygoriy's to run.
- treeview: one pre-existing failing test.
- Plan title typo: stray "a" committed in `676fb13`
  (`docs/superpowers/plans/2026-10-25-druid-sub3-run-step1.md`).
- Clean up `/no_backup/asebe/gzolotarov/druid-aftercorr-test/` (aftercorr test logs, 25/10/2026).
