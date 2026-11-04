# Setup › Parameters: edit stage settings in the TUI (04/11/2026)

## Intent

Today the Setup screen sets only `run_generax` / `origins`; every other stage setting is changed by
opening `druid.yaml` in nano (Setup › Config, `e`). Grygoriy: "cumbersome". Lab members must be able
to set clustering, alignment, phylogeny, GeneRax and POSSVM settings from Setup, picking from lists
for discrete fields and typing numbers for numeric ones.

## Decided (Grygoriy, 04/11/2026)

- **One section, `Parameters`, replaces `Config`** in `SetupScreen.SECTIONS` (layout A of the
  mockup: one scrolling form, a heading per stage group). The nano editing is dropped: the
  `e` / `edit_config` binding, `action_edit_config` and `_run_editor` go, with their tests.
- **Discrete fields are presets only** (no "custom" typed entry for now). Numeric fields are typed.
- **POSSVM**: reference species is chosen from the list; the reference gene-names file is typed as
  a path.
- **Freeze after the initial setup**: from the first submitted job, every setting that affects all
  outputs is read-only in Parameters. Before that, everything is editable.
- **MCL inflation**: `params.s2_inflation` is the *default*; a family's own `inflation` (families
  file column) overrides it. Per-family values stay editable in Families after the freeze.
- `min_seqs`, `min_distinct` and `max_n` freeze too.

## Fields

`key` = the `params:` key written; F = frozen after the first job; E = always editable.

| group | label | key | kind | values / check | |
|---|---|---|---|---|---|
| Clustering | MCL inflation (default) | `s2_inflation` | number | float > 0 | F |
| | recluster HGs above | `max_n` | number | int ≥ 1 | F |
| | domain expand (aa) | `domain_expand` | number | int ≥ 0 | F |
| | search cpus / cluster cpus | `s1_ncpu` / `s2_ncpu` | number | int ≥ 1 | E |
| Alignment | MAFFT | `MAFFT_OPT` | preset | linsi `--maxiterate 1000 --localpair` · einsi `--maxiterate 1000 --genafpair --ep 0` · ginsi `--maxiterate 1000 --globalpair` · auto `--auto` | F |
| Phylogeny | method | `TREE_METHOD` | preset | `fasttree` · `iqtree2` · `iqtree3` | F |
| | IQ-TREE model | `IQTREE2_MODEL` | preset | `TEST` · `MFP` · `LG+G4` · `WAG+G4` | F |
| | min seqs / min distinct | `min_seqs` / `min_distinct` | number | int ≥ 4 / int ≥ 1 | F |
| GeneRax | substitution model | `SUBS_MODEL` | preset | `LG` · `LG+G` · `WAG` · `JTT` | F |
| | max SPR radius | `MAX_SPR` | number | int ≥ 1 | F |
| | cpus | `NCPU_GENERAX` | number | int ≥ 1 | E |
| POSSVM | reference species | `REFSPECIES` | choice | the ticked species (`setup_state.selected`) | F |
| | reference gene names | `REFNAMES` | path | must be an existing file (relative = project root); read, never written | F |

- A value in `druid.yaml` that matches no preset is shown as an extra entry `custom: <value>` so
  opening Setup never changes it; picking a preset replaces it. Same for a `REFSPECIES` that is not
  ticked (shown, marked, and a blocker line: "REFSPECIES <x> is not a ticked species").
- The GeneRax group is shown greyed with a note when `run_generax` is off.
- Writes go through `yamledit.update_config({("params", key): value})` (comments kept; validated;
  nothing written on error), numbers written as int/float, not strings. A bad typed value: the
  ERROR on the bottom line, nothing written, the field keeps the file's value.
- The section's top note shows the `druid.yaml` path (the old Config section's only use besides
  editing).

## Freeze

- Frozen = `setup_state.species_locked(raw, cfg)` (the `species_locked` flag set at the first real
  submit, a run with `jobs.tsv` in `runs_dir`, or results in `outdir`), the same condition the
  species list already uses. An adopted project (`prepare: locked`) stays fully read-only as now.
- Frozen fields are shown with their value, disabled, and the reason note
  ("read-only: set before the first job; changing it would change every output").

## Pipeline change: per-family inflation

Measured 04/11/2026: `cluster.sh` runs `-i ${s2_inflation}` and `runner.stage_env` exports
`params` only, so **the families file's `inflation` column is ignored**; 42 of 356 library
families carry a value other than 1.1 (1.2–2.5). In scope:

- The cluster job of a family gets `s2_inflation` = that family's `inflation`; blank → the
  `params.s2_inflation` default.
- A new family row (Families editor, `hmm_rows`) is pre-filled with `params.s2_inflation`, not the
  hard-coded `"1.1"` in `families.Row`.
- The Families editor note (`EDIT_COLS["inflation"]`) is corrected: per-family overrides the default.
- ⚠ This changes the clusters of any family whose value ≠ `s2_inflation` on its next cluster run;
  the README states it. The per-family `min_seqs` column is out of scope (still unused).

## Non-goals

- Custom typed MAFFT options or models; POSSVM `--sos` / `--min_support_transfer` /
  `--itermidroot` (not in the config); resources (`resources.tsv`); partition / qos.

## Left to the builder

- Widget choice (`Select` vs `RadioSet`, `Input` with on-submit write), focus order, key help.
- Where the per-family inflation is injected (stage_env for `cluster`, step1run, or the job
  script reading the job's families copy) — pick the one with one source of truth.
- Check `main.py align -m` passes MAFFT_OPT to mafft unchanged for each preset.
