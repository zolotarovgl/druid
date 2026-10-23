# druid sub-project 2 — Setup tab + prepare: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a new druid project can be set up from the TUI (sources, species, analyses, tree placement, search type, families, config) and `druid prepare` builds its inputs.

**Architecture:** pure modules (`yamledit`, `setup_state`, `sptree`, `families`, `prepare`) hold all logic and every write; a new `druid/setup_tui.py` Screen is a thin view over them, reached from the main TUI's tab bar. Every write goes through `druid.paths`. Trees are rebuilt from a base tree + a placements file on each prepare, so re-running prepare is reproducible.

**Tech Stack:** Python 3.9, Textual >= 8.2 < 9, ete3 3.1.3, PyYAML, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-23-druid-sub2-setup-prepare-design.md` (parent: `docs/superpowers/specs/2026-10-14-druid-standalone-design.md`, "Write boundary").

## Global Constraints

- druid writes only inside the project directory; every write goes through `druid.paths` (`write_text`, `replace`, `mkdir`, `copy2`, `mkstemp`, ...). Proteome dirs, taxonomy tables, custom trees, `hmm_dir`, `DRUID_HOME` are read-only.
- Every new write site passes the AST lint `tests/test_write_boundary.py` (exemption: `from druid import paths` only, never rebound).
- Python 3.9 syntax; Textual >= 8.2, < 9; no new dependencies (no ruamel).
- Headers in `data/input.fasta` all start with `<prefix>_`. A proteome source file is never modified.
- `prepare: locked` (adopted v3) → prepare refuses; Setup is read-only; nothing is written.
- Species lock: `species_locked: true` in `druid.yaml`, or inferred (any `runs_dir/*/jobs.tsv`, or a non-empty `outdir`). Inferred-locked projects never get the flag written.
- Taxonomy table format (Xavi's, no header): col 1 prefix, col 2 Latin name, col 6 taxonomy string (`, `-separated).
- Families CSV columns (tab-separated, `helper/hmmsearch.py:195`): `class_name hmms inflation min_seqs threshold pref1 pref2` (pref1 = category, pref2 = id prefix).
- Tests run with the repo's existing pytest setup (`tests/conftest.py` autouse fixture); the local interpreter is py3.9.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A proteome file without a trailing newline, with CRLF line ends or blank lines → `input.fasta` never joins one file's last sequence line with the next file's header; CR stripped. (Task 5 test `test_concat_no_trailing_newline_crlf`.)
2. A ticked species whose proteome file is gone or unreadable at prepare time → prepare refuses before writing anything; old `input.fasta` intact. (Task 5 `test_missing_file_blocks_and_keeps_old`.)
3. Placing a species as sister of the **root** → valid: a new root with two children. (Task 4 `test_add_sister_of_root`.)
4. Opening Setup on adopted v3 (`prepare: locked`, no `sources` / `taxonomy` / `species` keys) → all sections read-only, `druid.yaml` byte-identical after open/close. (Task 7 `test_setup_on_locked_project_writes_nothing`.)
5. Unticking a species that has a placement, or whose tips another placement referenced → the stale placement is dropped from the tree build with a note, never a crash. (Task 4 `test_build_trees_drops_stale_placements`.)

---

### Task 1: Shipped taxonomy table, template keys, init copies

**Files:**
- Create: `druid/data/genome_sources.tsv` — byte copy of `/home/grygoriyzolotarov/ant/xgraubove/genomes/genome_sources_2025-10-13.tsv` (md5 `4f010d40e071fc13a9e15cdadf423b3e`, 476 rows). Read it, never write there.
- Modify: `druid/data/SOURCE` (add a row: file, source path, md5, date `23/10/2026`)
- Modify: `druid/templates/druid.yaml`, `druid/project.py`
- Test: `tests/test_project.py`

**Interfaces:**
- Produces: template keys `taxonomy: data/genome_sources.tsv` (the default source's table), `sources: []` (custom sources, see Task 3), `params.origins: true`; `init` copies `genome_sources.tsv`, `species_tree.binary.newick` → `data/base_tree.binary.newick`, `species_tree.newick` → `data/base_tree.newick` (in addition to the existing copies).

- [ ] **Step 1: failing tests** — `test_init_copies_taxonomy_and_base_trees`: after `project.init(d, "23/10/2026")`, `d/data/genome_sources.tsv` equals the shipped bytes; `d/data/base_tree.binary.newick` == shipped `species_tree.binary.newick`; same for `base_tree.newick`. `test_template_new_keys`: `yaml.safe_load(d/druid.yaml)` has `taxonomy == "data/genome_sources.tsv"`, `sources == []`, `params["origins"] is True`, and `core.config_from_raw` accepts it. `test_shipped_taxonomy_md5`: md5 of `druid/data/genome_sources.tsv` == `4f010d40e071fc13a9e15cdadf423b3e`.
- [ ] **Step 2:** run `pytest tests/test_project.py -q` → the three fail.
- [ ] **Step 3:** copy the file (read-only source), add the SOURCE row, add the keys to the template (one comment line each, house style), extend `ShippedData`/`init` copies.
- [ ] **Step 4:** `pytest tests/test_project.py tests/test_write_boundary.py -q` → PASS.
- [ ] **Step 5: commit** `data: ship Xavi's genome_sources (25/10/13) as the default taxonomy; init copies it and the base trees`.

### Task 2: `druid/yamledit.py` — comment-preserving key writes

**Files:** Create `druid/yamledit.py`; Test `tests/test_yamledit.py`.

**Interfaces:**
- Produces:
  - `set_key(text: str, key: tuple, value) -> str` — `key` is `("species",)` (top-level, any YAML value; replaces the key's whole block: the key line plus following indented / `- ` lines) or `("params", "run_generax")` (one level under a top-level mapping, scalar only; replaces the value in place and keeps the line's trailing `# comment`). A missing key is appended (top-level at end of file; nested at the end of its parent block). Values rendered with `yaml.safe_dump(..., default_flow_style=False, sort_keys=False)`; scalars inline.
  - `update_config(changes: dict) -> Path` — `changes` maps key tuples to values; applies `set_key` to `paths.config_file()` text, checks `yaml.safe_load(new)` equals the old mapping with only those keys changed, validates with `core.config_from_raw`, writes via `paths.write_text`. Raises `core.ConfigError` and writes nothing on any check failing.

- [ ] **Step 1: failing tests** on the real template text: `test_set_top_list_keeps_comments` (set `species` to `["Mlei","Hsap"]`; every `#` line of the template still present; loaded `species` equal); `test_set_nested_scalar_keeps_inline_comment` (`params.run_generax` → `False`; the line keeps its comment if it had one; loaded value `False`); `test_append_missing_top_and_nested` (`species_locked`, `params.origins` absent → appended, loaded values right); `test_other_keys_unchanged` (loaded mapping minus changed keys == before); `test_update_config_refuses_invalid` (a change making `outdir` outside the project → `ConfigError`, file bytes unchanged).
- [ ] **Step 2:** run → FAIL (module missing).
- [ ] **Step 3:** implement; line-based, no YAML round-trip of the whole file.
- [ ] **Step 4:** `pytest tests/test_yamledit.py tests/test_write_boundary.py -q` → PASS.
- [ ] **Step 5: commit** `yamledit: set druid.yaml keys without losing comments`.

### Task 3: `druid/setup_state.py` — sources, candidates, selection, lock, blockers

**Files:** Create `druid/setup_state.py`; Modify `druid/model.py` (`sbatch_all`), `druid/doctor.py` (proteomes check); Test `tests/test_setup_state.py`, `tests/test_doctor.py`.

**Interfaces:**
- Consumes: `yamledit.update_config` (Task 2); template keys (Task 1).
- Produces:
  - `@dataclass(frozen=True) Source(name: str, proteomes_dir: Path, glob: str, taxonomy: Path)`; `sources(raw, root) -> list[Source]` — first the default source `name="default"` from `proteomes_dir` / `proteome_glob` / `taxonomy` (missing `taxonomy` → the shipped `DRUID_HOME/druid/data/genome_sources.tsv`), then each `raw["sources"]` entry `{name, proteomes_dir, proteome_glob, taxonomy}` (relative paths resolve against the project).
  - `read_taxonomy(path) -> dict[str, tuple[str, str]]` — prefix → (Latin name, taxonomy string); short rows skipped.
  - `@dataclass(frozen=True) Candidate(sp: str, name: str, taxonomy: str, source: str, path: Path)`; `candidates(srcs) -> tuple[list[Candidate], list[str]]` — every proteome file matching the glob whose prefix (the `{sp}` part) has a taxonomy row; second value = custom-source files with no row ("<source>: <file>"), default-source files without a row are silently dropped.
  - `selected(raw) -> list[tuple[str, str]]` — `species:` entries as `(sp, source)`: a plain string `"Mlei"` = `("Mlei", "default")`; a mapping `{sp: Abcd, source: mine}`.
  - `species_value(sel: list[tuple[str,str]]) -> list` — inverse (default-source species as plain strings).
  - `species_locked(raw, cfg) -> bool` (flag, or inferred: any `paths.runs_dir()/*/jobs.tsv`, or `cfg.outdir` exists and is non-empty).
  - `lock_species(raw, cfg) -> bool` — if `prepare != "locked"` and not `species_locked`: `update_config({("species_locked",): True})`, return True; else False (never writes an inferred-locked or adopted project).
  - `blockers(raw, cfg, root) -> list[str]` — human-readable, in this order: no species ticked; a prefix ticked from two sources; a ticked species whose file is missing; custom-source files with no taxonomy row; (GeneRax or origins on) ticked species not on the tree and not placed (uses `sptree`, Task 4 — until Task 4 lands, this check is added in Task 4); no families in `params.genefam_info`.
- `model.sbatch_all` calls `setup_state.lock_species(raw, cfg)` once before the first `sbatch` of a real (non-dry) submit; read the raw/cfg it needs via `paths.read_raw()` / `core.config_from_raw`.
- `doctor` proteomes check resolves each `selected` species against its own source (same message shape: `"N/M species have a file"`).

- [ ] **Step 1: failing tests** (tmp project from `project.init`, fake proteome dirs with `Aaa_long.pep.fasta`, a 6-column taxonomy tsv): `test_sources_default_and_custom`; `test_candidates_hide_rowless_default_list_rowless_custom`; `test_selected_roundtrip_plain_and_mapping`; `test_species_locked_flag_runs_outdir` (each of the three makes it True); `test_lock_species_writes_flag_once` (second call returns False, file unchanged); `test_lock_species_never_writes_adopted` (raw `prepare: locked` → False, bytes unchanged); `test_lock_species_never_writes_inferred` (a `runs/x/jobs.tsv` → False, bytes unchanged); `test_blockers_messages` (each condition alone yields exactly its message); `test_sbatch_all_locks_before_first_sbatch` (fake `_slurm` asserts the flag is already in `druid.yaml` when called); `test_dry_run_does_not_lock`; doctor: `test_doctor_proteomes_per_source`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `pytest tests/test_setup_state.py tests/test_doctor.py tests/test_model.py tests/test_write_boundary.py -q` → PASS.
- [ ] **Step 5: commit** `setup_state: sources, candidates, selection, species lock (set at first submit), blockers`.

### Task 4: `druid/sptree.py` — prune, place, carry to the origin tree

**Files:** Create `druid/sptree.py`; Modify `druid/setup_state.py` (tree blocker); Test `tests/test_sptree.py`.

**Interfaces:**
- Consumes: `setup_state.selected`, `Source` (Task 3).
- Produces:
  - `prune(newick: str, keep: set[str]) -> str` — ete3 `format=1`, `preserve_branch_length=True`, internal names kept; tips not in `keep` removed.
  - `tips(newick) -> set[str]`; `has_polytomy(newick) -> bool`.
  - `add_sister(newick: str, tipset: frozenset, new: str) -> str` — the node whose tip set == `tipset` gets a new unnamed parent with children (that node, `new`); the new parent takes the node's branch length, the node and `new` get length 1. `tipset` == all tips → new root. `ValueError` if no node has exactly that tip set or `new` is already a tip.
  - `carry_to_origin(newick: str, tipset: frozenset, new: str) -> str` — if a node has exactly `tipset`: same as `add_sister`; else add `new` (length 1) as one more child of the smallest node whose tips ⊇ `tipset`.
  - `@dataclass(frozen=True) Placement(sp: str, tipset: frozenset)`; `read_placements(path) -> list[Placement]` (tsv `sp<TAB>tip1,tip2,...`; missing file = `[]`); `write_placements(path, pl) -> Path` via `paths.write_text`. File: `data/placements.tsv`.
  - `build_trees(base_binary: str, base_origin: str, species: list[str], pl: list[Placement]) -> tuple[str, str, list[str]]` — prune both to `species`, apply placements in file order (skipping, with a note, any whose `sp` is not ticked or whose `tipset` is not within the tips present at that point), return (binary, origin, notes).
  - `missing(base_binary, species, pl) -> list[str]` — ticked species absent from the built binary tree.
  - Tree base: `raw["tree_source"]` (custom route: one user tree, used for both) if set, else `data/base_tree.binary.newick` + `data/base_tree.newick`.
- `setup_state.blockers` gains: (GeneRax or origins on) `missing(...)` non-empty → `"N ticked species not on the tree: A, B, ..."`; GeneRax on and `tree_source` set and `has_polytomy` → `"tree_source has polytomies; GeneRax needs a binary tree"`.

- [ ] **Step 1: failing tests** on small newicks (`((A:1,B:1)AB:2,(C:1,D:1)CD:2)R;`): `test_prune_keeps_internal_names_and_lengths`; `test_add_sister_of_tip` (`X` sister of `A` → `A`,`X` share a parent under `AB`; tree binary); `test_add_sister_of_internal` (sister of `{A,B}` → parent of `AB` has children `AB`,`X`); `test_add_sister_of_root`; `test_add_sister_rejects_unknown_tipset_and_duplicate`; `test_carry_to_origin_exact_clade` and `test_carry_to_origin_inside_polytomy` (origin `(A,B,C,D)R;`, tipset `{A,B}` → `X` becomes a 5th child of `R`); `test_placements_roundtrip`; `test_build_trees_drops_stale_placements` (note mentions the species); `test_blocker_tree_missing_and_polytomy`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement with ete3.
- [ ] **Step 4:** `pytest tests/test_sptree.py tests/test_setup_state.py tests/test_write_boundary.py -q` → PASS.
- [ ] **Step 5: commit** `sptree: prune and place species (sister of a node), carried to the origin tree`.

### Task 5: `druid/prepare.py` + `druid prepare`

**Files:** Create `druid/prepare.py`; Modify `druid/cli.py` (command `prepare`); Test `tests/test_prepare.py`, `tests/test_cli.py`.

**Interfaces:**
- Consumes: Tasks 3–4.
- Produces:
  - `class PrepareError(RuntimeError)`.
  - `run(raw, cfg, root) -> list[Path]` — refuses (`PrepareError`, nothing written) if `raw.get("prepare") == "locked"`, `species_locked`, or `blockers` non-empty (message lists them). Writes via `paths.mkstemp` + `paths.replace` (so an interrupted run keeps the old files):
    - `params.infasta` (`data/input.fasta`): selected species in `species:` order; per file, lines with `\r` stripped, blank lines dropped, a newline guaranteed at file end; a header not starting with `<sp>_` becomes `><sp>_<rest>`; headers already prefixed untouched.
    - when GeneRax or origins is on: `params.SPECIES_TREE`, `params.ORIGIN_TREE` from `sptree.build_trees` (+ the notes returned to the caller).
    - `data/species_info.tsv` (`model.species_info_path` target): one row per selected species `sp<TAB>Latin name<TAB>clade`; clade = the shipped `druid/data/species_info.tsv` column 3 for that prefix if present, else the first `, `-element of its taxonomy string that is a column-3 value in the shipped file, else `Other`.
  - CLI `druid prepare`: prints each written path and each note; `PrepareError` → `ERROR: ...`, exit 2 (same `_fail` path as the other commands).

- [ ] **Step 1: failing tests**: `test_prepare_concat_order_and_prefix` (a custom source file with `>XP_1` headers → `>Abcd_XP_1` in `input.fasta`; source bytes and mtime unchanged); `test_already_prefixed_untouched`; `test_concat_no_trailing_newline_crlf`; `test_missing_file_blocks_and_keeps_old`; `test_refuses_locked_and_species_locked` (no file changes); `test_trees_written_only_when_switch_on`; `test_species_info_clade_rules` (shipped row; taxonomy match `Ctenophora`; `Other`); `test_source_dirs_read_only` (`chmod -R a-w` on the proteome dir and taxonomy file, prepare succeeds, every new file under the project); `test_cli_prepare_error_exit_2`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `pytest tests/test_prepare.py tests/test_cli.py tests/test_write_boundary.py -q` → PASS.
- [ ] **Step 5: commit** `prepare: build input.fasta (prefixing only in the copy), trees, species_info; druid prepare`.

### Task 6: `druid/families.py` — library, project file, custom HMM rows

**Files:** Create `druid/families.py`; Test `tests/test_families.py`.

**Interfaces:**
- Produces:
  - `COLS = ("class_name", "hmms", "inflation", "min_seqs", "threshold", "pref1", "pref2")`; `@dataclass Row` with those fields (str).
  - `library() -> list[Row]` (`DRUID_HOME/druid/data/families_library.csv`, 356 rows); `read(path) -> list[Row]`; `write(path, rows) -> Path` (tab-separated, `paths.write_text`).
  - `hmm_rows(hmm_dir: Path) -> list[Row]` — one row per `*.hmm` (stem = `class_name` = `hmms`), defaults `inflation 1.1`, `min_seqs 3`, `threshold "GA"` if the file has a line starting `GA ` else `"1e-5"` (Ruling — see handoff), `pref1 "custom"`, `pref2 "cus"`. Never writes into `hmm_dir`.
  - `ticked_ids(rows) -> set[str]` — `<pref2>.<class_name>` (= `core.parse_genefam` ids).

- [ ] **Step 1: failing tests**: `test_library_356_rows_parse_like_core` (ids == `core.parse_genefam` on the same file); `test_write_read_roundtrip`; `test_hmm_rows_defaults_ga_and_evalue`; `test_hmm_dir_untouched` (read-only dir, mtimes unchanged).
- [ ] **Step 2–4:** run → FAIL; implement; `pytest tests/test_families.py tests/test_write_boundary.py -q` → PASS.
- [ ] **Step 5: commit** `families: library, project file, default rows for custom HMMs`.

### Task 7: Setup screen — frame, Source, Species, Analyses, Config, tab hookup

**Files:** Create `druid/setup_tui.py`; Modify `druid/tui.py` (tab bar `Jobs │ Results │ Setup`, `tab` cycles the three, Setup pushes `SetupScreen`, `tab`/`esc` in Setup pops back to Jobs and reloads `raw`/`cfg`; `druid tui` on a project with no species and not locked opens on Setup); Test `tests/test_setup_tui.py`.

**Interfaces:**
- Consumes: Tasks 2, 3, 6.
- Produces: `class SetupScreen(Screen)` with `SECTIONS = ("Source", "Species", "Analyses", "Tree", "Search", "Families", "Config")`; left `ListView` (each item shows a ✓ / ! / count mark), right `ContentSwitcher` (one widget per section, ids `#sec-<name lower>`), bottom `Static#blockers` = `setup_state.blockers(...)` joined, refreshed after every change.
  - Source: lists `setup_state.sources`; add a custom source (Input fields: name, dir, glob, taxonomy path) → `update_config({("sources",): ...})`.
  - Species: `Input#sp-filter` (matches any column) + a table of `candidates` with a tick column, `space` toggles, `a` ticks all shown, count line `N ticked / M`; each change → `update_config({("species",): species_value(...)})`. Read-only with a reason line when `species_locked` or `prepare: locked`.
  - Analyses: two `Switch`es → `params.run_generax`, `params.origins`.
  - Config: shows `druid.yaml`; `e` suspends the app, runs `$EDITOR` (fallback `nano`) on it, then re-validates with `core.config_from_raw`; an error shows in `#blockers` as `ERROR: ...`.
- Tree, Search, Families sections exist as placeholders here (filled in Task 8).

- [ ] **Step 1: failing pilot tests** (`App.run_test`, tmp project + fake source): `test_tab_cycles_to_setup_and_back`; `test_fresh_project_opens_on_setup`; `test_species_filter_tick_writes_species`; `test_species_readonly_when_locked`; `test_analyses_switches_write_params`; `test_add_custom_source`; `test_blockers_line_updates`; `test_setup_on_locked_project_writes_nothing` (adopted-style `druid.yaml`, open every section, toggle attempts, close → bytes identical).
- [ ] **Step 2–4:** run → FAIL; implement; `pytest tests/test_setup_tui.py tests/test_tui.py tests/test_write_boundary.py -q` → PASS.
- [ ] **Step 5: commit** `tui: Setup tab — sources, species picker, analyses switches, config`.

### Task 8: Setup screen — Tree placement, Search, Families, prepare key, origins off

**Files:** Modify `druid/setup_tui.py`, `druid/tui.py` (Results: when `params.origins` is false, `ORIGIN_TREE` is not loaded and no origin column/text is shown); Test `tests/test_setup_tui.py`, `tests/test_tui.py`.

**Interfaces:**
- Consumes: Tasks 4, 5, 6, 7.
- Produces:
  - Tree (shown only when a switch is on, else "not needed: GeneRax and origins are off"): list of `sptree.missing(...)`; `enter` on one pushes `PlaceScreen(TreeScreen)` on the current built binary tree (`write_guard=paths.writable`) with an extra binding `p` "place here" that `dismiss`es with the cursor node's tip set; the Setup screen appends `Placement(sp, tipset)` and writes `data/placements.tsv`. `PlaceScreen` lives in `setup_tui.py` (the vendored treeview is not edited). Custom route: an Input sets `tree_source`.
  - Search: three `RadioButton`s — gene family file (default; optional path to the user's own CSV, else the library), custom HMMs (an Input sets `params.hmm_dir`), custom query sequences (disabled, label "not available yet").
  - Families: table of the rows (library, or the user's CSV, plus `families.hmm_rows(hmm_dir)` when custom HMMs), all ticked on first open, `space` toggles, filter Input; `enter` on a row opens an edit form for `inflation min_seqs threshold pref1 pref2`; every change → `families.write(params.genefam_info, ticked rows)`. When `data/families.csv` already has rows, those are the ticked set (and their edited values win). Stays editable after the species lock.
  - `P` (prepare) on any section: runs `prepare.run` in a worker; written paths / notes / `ERROR:` in `#blockers`.

- [ ] **Step 1: failing pilot tests**: `test_tree_section_hidden_when_switches_off`; `test_place_as_sister_writes_placements` (drive `PlaceScreen`: cursor to a node, `p` → `placements.tsv` row with that tip set; the species leaves the missing list); `test_search_custom_hmm_rows_appear_with_defaults`; `test_query_sequences_disabled`; `test_families_all_ticked_untick_writes_csv`; `test_family_row_edit_persists`; `test_families_editable_after_lock`; `test_prepare_key_runs_and_reports`; `test_results_no_origin_when_origins_off` (in `tests/test_tui.py`).
- [ ] **Step 2–4:** run → FAIL; implement; `pytest tests/ -q -p no:cacheprovider` (full suite) → PASS.
- [ ] **Step 5: commit** `tui: Setup tab — tree placement, search type, families, prepare`.

### Task 9 (controller, not dispatched): cluster acceptance

Runs on login1 in the `phylo` env, ≤ 60 tests per pytest chunk (login1 kills CPU-bound processes after ~100 s); nothing written outside a fresh scratch project under `/no_backup/asebe/gzolotarov/`.

- [ ] Push `main` to `login1.hpc.crg.es:projects/druid`; full suite in chunks → all pass.
- [ ] `S=$(mktemp -d /no_backup/asebe/gzolotarov/druid-sub2.XXXXXX); druid init $S/p`; record `find /users/asebe/xgraubove/genomes/data /users/asebe/xgraubove/genomes/genome_sources_2025-10-13.tsv -newer $S -print | wc -l` = 0 baseline.
- [ ] In the TUI (headless pilot script in the scratchpad): tick `Mlei Hsap Nvec` + 2 species not on the shipped tree, GeneRax on, place both, keep all families, `P`. Check: `input.fasta` headers all start with their prefix (`grep -c '^>' ` per species equals each source file's count); trees have 5 tips and are binary; `species_info.tsv` 5 rows; the `find -newer` count still 0; `druid --project $S/p doctor` proteomes `5/5`.
- [ ] Open Setup on v3 (`druid --project $V3 tui`, pilot, open every section, quit) → `md5sum $V3/druid.yaml` = `64a5194ff7806842196f65dc9c902e16`.
