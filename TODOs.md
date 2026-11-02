# druid TODOs

Open work, newest first. Dates dd/mm/yyyy.

- **Installation test** (Grygoriy, 02/11/2026): how easy is it for a new user to install druid?
  Fresh account / clean env on the cluster, follow only the README (clone with submodules, env,
  `~/bin/druid`, `druid doctor`, `druid init`), and record every step that needed outside help.
- **Rename possvm stages for display** (Grygoriy, 02/11/2026, "for later"): show possvm_prev as
  `possvm` and possvm as `possvm_postGR` (GeneRax on); GeneRax off: one `possvm`, no n/a row. Labels
  only — result dirs, job names and run records keep the internal names; the CLI accepts both.
  Also: `druid status` footer says "done = possvm_prev" when possvm_prev is n/a.
  GeneRax off (Grygoriy, 02/11/2026): `druid status`, the TUI overview columns and pane 1 omit
  possvm_prev, generax and gxsup altogether instead of showing n/a rows.
- **Species tree viewer in Setup** (Grygoriy, 02/11/2026): show the project's species tree
  (Tree section's `SPECIES_TREE` / `ORIGIN_TREE`) during setup, e.g. with the vendored treeview
  widget, so the picked species and tree can be checked before `P`.
- **Sub-project 5: step 2 as one chain** (`druid chain`, driver job, own retries, no Nextflow) —
  spec `docs/superpowers/specs/2026-11-02-druid-sub5-step2-chain-design.md`, awaiting review.
- **Sub-project 4: counts heatmap** — spec `docs/superpowers/specs/2026-10-14-phylocli-counts-heatmap-design.md`.
- **First real `druid run`** on a test project (`/no_backup/asebe/gzolotarov/druid-test-run`,
  prefix `drtest`) — Grygoriy's to run.
- **GitHub remote** for druid (private; Grygoriy creates it). Check first why `.git` is 174 MB.
- `druid doctor`: the mpirun check fails in the `phylo` env.
- treeview: one pre-existing failing test.
- Plan title typo: stray "a" committed in `676fb13`
  (`docs/superpowers/plans/2026-10-25-druid-sub3-run-step1.md`).
- Clean up `/no_backup/asebe/gzolotarov/druid-aftercorr-test/` (aftercorr test logs, 25/10/2026).
