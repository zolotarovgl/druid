# Setup › Parameters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit clustering / alignment / phylogeny / GeneRax / POSSVM settings in a Setup › Parameters section (presets + typed numbers, frozen after the first job), dropping nano editing, and make the cluster stage honour each family's own inflation.

**Architecture:** A pure module `druid/params_form.py` holds the field table, presets, parsing and the freeze rule; `setup_tui.SetupScreen` renders it as one section and writes through `yamledit.update_config`. The per-family inflation is injected in `runner.stage_env` from the job's own families snapshot (`cfg.params["genefam_info"]`, the run-dir copy), so there is one source of truth.

**Tech Stack:** Python 3.9-compatible, Textual (existing TUI), pytest (`python3 -m pytest -q -p no:cacheprovider`, ~7 min full suite).

**Spec:** `docs/superpowers/specs/2026-11-04-setup-parameters-design.md`

## Global Constraints

- druid writes only inside the project directory (`paths.*` writers); `REFNAMES` and any typed path are read, never written.
- Every config write goes through `yamledit.update_config({("params", key): value})`; comments and key order survive; on error nothing is written and the ERROR is the bottom line.
- Numbers are written as int / float, never as strings.
- Discrete fields are presets only; a file value matching no preset shows as `custom: <value>` and is never rewritten by opening Setup.
- Frozen = `setup_state.species_locked(raw, cfg)`; `prepare: locked` keeps everything read-only (`LOCKED_ALL`).
- Python 3.9 compatible (no `match`, no `X | Y` at runtime outside `from __future__ import annotations`).
- Edit with Edit/Write, never sed. Never run Nextflow.

## Review Focus

1. A druid.yaml value outside the presets (e.g. an adopted project's `MAFFT_OPT: "--auto --reorder"`): opening and leaving Parameters must not change the file (Task 2, Task 3 tests).
2. A typed `1,5` / `abc` / `0` / `-1` for a number: refused with an ERROR line, file unchanged (Task 2 `parse` tests, Task 3 UI test).
3. A family row with an empty inflation field, or a family id absent from the snapshot: the cluster job falls back to `params.s2_inflation`, never an empty `-i` (Task 1).
4. `REFSPECIES` not among the ticked species (species unticked after it was chosen): shown, and a blocker line (Task 2).
5. A frozen project: every F field disabled, E fields (cpus) still write (Task 3).

---

### Task 1: Per-family inflation reaches the cluster stage

**Files:**
- Modify: `druid/families.py` (`hmm_rows`), `druid/runner.py:21` (`stage_env`), `druid/setup_tui.py:38` (`EDIT_COLS["inflation"]`) and the `_hmm_rows` / `_fam_universe` callers, `README.md` (families / cluster paragraph)
- Test: `tests/test_runner.py`, `tests/test_families.py`

**Interfaces:**
- Produces: `families.inflation_of(path, family_id: str) -> str` — the `inflation` field of the first row whose id (`<pref>.<class_name>`, `families._pref`) is `family_id`; `""` when absent, empty, or the file is unreadable.
- Produces: `families.hmm_rows(hmm_dir, inflation: str = "1.1") -> list[Row]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_runner.py
def test_cluster_env_uses_the_familys_inflation(results_tree, tmp_path):
    cfg = ...  # as test_stage_env, with params genefam_info -> a file holding
               # "Fox\tForkhead\t1.6\t3\tGA\ttfs\ttfs\n" and "Sox\tHMG\t\t3\tGA\ttfs\ttfs\n",
               # params s2_inflation 1.1
    assert runner.stage_env(cfg, "cluster", "tfs.Fox", 2)["s2_inflation"] == "1.6"
    assert runner.stage_env(cfg, "cluster", "tfs.Sox", 2)["s2_inflation"] == "1.1"   # blank field
    assert runner.stage_env(cfg, "cluster", "tfs.Nope", 2)["s2_inflation"] == "1.1"  # absent id
    assert runner.stage_env(cfg, "align", "tfs.Fox.HG1", 2)["s2_inflation"] == "1.1" # other stages

# tests/test_families.py
def test_hmm_rows_take_the_default_inflation(tmp_path):
    (tmp_path / "X.hmm").write_text("HMMER3\nGA 10 10;\n")
    assert families.hmm_rows(tmp_path, "1.4")[0].inflation == "1.4"
    assert families.hmm_rows(tmp_path)[0].inflation == "1.1"
```

- [ ] **Step 2: Run them, expect FAIL** — `python3 -m pytest -q -p no:cacheprovider tests/test_runner.py tests/test_families.py`

- [ ] **Step 3: Implement** `inflation_of`, the `hmm_rows` parameter, and in `stage_env` for `stage == "cluster"` override `env["s2_inflation"]` with `inflation_of(cfg.params.get("genefam_info"), hg)` when non-empty. Setup passes `str(params.get("s2_inflation", "1.1"))` to `hmm_rows`. `EDIT_COLS["inflation"]` becomes `"inflation (per family; overrides the default params.s2_inflation)"`. README: one paragraph — the family's `inflation` overrides `params.s2_inflation` (blank = default); before 04/11/2026 the column was ignored, so families whose value ≠ the default cluster differently on their next cluster run.

- [ ] **Step 4: Run the two files plus `tests/test_setup_tui.py`, expect PASS**

- [ ] **Step 5: Commit** — `git commit -m "cluster: per-family inflation overrides params.s2_inflation"`

---

### Task 2: `druid/params_form.py` — fields, presets, parsing, freeze, blockers

**Files:**
- Create: `druid/params_form.py`
- Modify: `druid/setup_state.py` (`blockers`)
- Test: `tests/test_params_form.py`, `tests/test_setup_state.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Field: key: str; group: str; label: str; kind: str  # "number" | "preset" | "species" | "path"; presets: tuple = ()  # (label, value) pairs; num: str = ""  # "int" | "float"; minimum: float = 0; frozen: bool = True`
  - `FIELDS: tuple[Field, ...]` — exactly the spec's Fields table, in its order; groups `"Clustering", "Alignment", "Phylogeny", "GeneRax", "POSSVM"`.
  - `choices(field: Field, current, species: list[str]) -> list[tuple[str, object]]` — presets (or the species for `kind == "species"`), plus `("custom: <current>", current)` appended when `current` is set and not among the values.
  - `parse(field: Field, text: str, root: Path) -> object` — int/float for numbers (≥ `minimum`; float > 0 for `s2_inflation`), the str path for `path` (must be an existing file, resolved against `root`); raises `ValueError` with a one-line message naming the label.
  - `frozen(raw: dict, cfg) -> bool` — `setup_state.species_locked(raw, cfg)`.
- MAFFT preset values (verbatim): linsi `--maxiterate 1000 --localpair`, einsi `--maxiterate 1000 --genafpair --ep 0`, ginsi `--maxiterate 1000 --globalpair`, auto `--auto`. TREE_METHOD `fasttree`, `iqtree2`, `iqtree3`. IQTREE2_MODEL `TEST`, `MFP`, `LG+G4`, `WAG+G4`. SUBS_MODEL `LG`, `LG+G`, `WAG`, `JTT`. Minimums: `max_n` 1, `domain_expand` 0, cpus 1, `min_seqs` 4, `min_distinct` 1, `MAX_SPR` 1. Not frozen: `s1_ncpu`, `s2_ncpu`, `NCPU_GENERAX`.

- [ ] **Step 1: Verify** `submodules/phylogeny/main.py align -m` passes the string to mafft unchanged (read its `align` function); if a preset would be mangled, note it in the report and keep the preset list (do not edit the submodule).

- [ ] **Step 2: Write the failing tests**

```python
def test_fields_cover_the_spec_keys():
    assert [f.key for f in params_form.FIELDS] == ["s2_inflation", "max_n", "domain_expand",
        "s1_ncpu", "s2_ncpu", "MAFFT_OPT", "TREE_METHOD", "IQTREE2_MODEL", "min_seqs",
        "min_distinct", "SUBS_MODEL", "MAX_SPR", "NCPU_GENERAX", "REFSPECIES", "REFNAMES"]
    assert {f.key for f in params_form.FIELDS if not f.frozen} == {"s1_ncpu", "s2_ncpu", "NCPU_GENERAX"}

def test_choices_keep_an_unknown_value_as_custom():
    f = next(f for f in params_form.FIELDS if f.key == "MAFFT_OPT")
    assert params_form.choices(f, "--auto --reorder", [])[-1] == ("custom: --auto --reorder", "--auto --reorder")
    assert ("linsi", "--maxiterate 1000 --localpair") in params_form.choices(f, "--maxiterate 1000 --localpair", [])
    assert not any(l.startswith("custom") for l, _ in params_form.choices(f, "--auto", []))

def test_species_choices_are_the_ticked_species():
    f = next(f for f in params_form.FIELDS if f.key == "REFSPECIES")
    assert params_form.choices(f, "Mmus", ["Aaa", "Mmus"]) == [("Aaa", "Aaa"), ("Mmus", "Mmus")]
    assert params_form.choices(f, "Hsap", ["Aaa"])[-1] == ("custom: Hsap", "Hsap")

@pytest.mark.parametrize("key,text,want", [("s2_inflation", "1.4", 1.4), ("max_n", "2000", 2000),
                                           ("domain_expand", "0", 0)])
def test_parse_numbers(key, text, want, tmp_path): ...  # == want and type(got) is type(want)

@pytest.mark.parametrize("key,text", [("s2_inflation", "0"), ("s2_inflation", "1,5"),
    ("max_n", "abc"), ("max_n", "2.5"), ("min_seqs", "3"), ("s1_ncpu", "-1")])
def test_parse_refuses(key, text, tmp_path): ...  # pytest.raises(ValueError)

def test_parse_path_must_exist(tmp_path):
    (tmp_path / "names.csv").write_text("a\tb\n")
    f = next(f for f in params_form.FIELDS if f.key == "REFNAMES")
    assert params_form.parse(f, "names.csv", tmp_path) == "names.csv"
    with pytest.raises(ValueError): params_form.parse(f, "missing.csv", tmp_path)

# tests/test_setup_state.py
def test_refspecies_not_ticked_is_a_blocker(...):  # REFSPECIES Hsap, ticked Aaa ->
    assert "REFSPECIES Hsap is not a ticked species" in setup_state.blockers(raw, cfg, root)
def test_refnames_missing_is_a_blocker(...):       # REFNAMES -> missing file
    assert any(b.startswith("REFNAMES") and "not found" in b for b in setup_state.blockers(raw, cfg, root))
```

- [ ] **Step 3: Run, expect FAIL** — `python3 -m pytest -q -p no:cacheprovider tests/test_params_form.py tests/test_setup_state.py`

- [ ] **Step 4: Implement** `params_form.py` and the two blocker lines (only when species are ticked; REFNAMES resolved against the project root).

- [ ] **Step 5: Run, expect PASS; then `tests/test_setup_tui.py` (blocker-line test may need the new lines accounted for)**

- [ ] **Step 6: Commit** — `git commit -m "params_form: Setup parameter fields, presets, parsing, freeze"`

---

### Task 3: Setup › Parameters section replaces Config

**Files:**
- Modify: `druid/setup_tui.py` (`SECTIONS`, `compose`, `_marks`, `_refresh`, `_fill_config` → `_fill_params`, bindings, `check_action`, focus, write handlers; delete `_run_editor`, `action_edit_config`, the `e`/`edit_config` binding), module docstring, `README.md` (Setup section), `TODOs.md` (drop any "edit params in Setup" item)
- Test: `tests/test_setup_tui.py` (replace the Config/editor tests at ~482 and ~521)

**Interfaces:**
- Consumes: `params_form.FIELDS`, `choices`, `parse`, `frozen` (Task 2); `yamledit.update_config`; `self._write(changes, done)`.
- Produces: section name `"Parameters"` in `SetupScreen.SECTIONS` at the old `"Config"` position; widget ids `#pa-<key>` (e.g. `#pa-MAFFT_OPT`, `#pa-s2_inflation`), `#pa-reason` (note), `#pa-path` (shows `paths.config_file()`).

- [ ] **Step 1: Write the failing tests** (pilot style of `test_analyses_switches_write_params`)

```python
def test_parameters_preset_writes_param(proj):
    # _section(pilot, scr, "Parameters"); set #pa-TREE_METHOD to "iqtree3"
    assert _raw()["params"]["TREE_METHOD"] == "iqtree3"
    assert "SPECIES_TREE" in paths.config_file().read_text()      # rest of file intact

def test_parameters_number_typed_and_refused(proj):
    # type "1.4" + enter in #pa-s2_inflation -> _raw()["params"]["s2_inflation"] == 1.4 (float)
    # type "abc" + enter -> unchanged 1.4, bottom line starts "ERROR:"

def test_parameters_unknown_value_survives_opening(proj):
    yamledit.update_config({("params", "MAFFT_OPT"): "--auto --reorder"})
    before = paths.config_file().read_text()
    # open Parameters, move through every field with tab, esc
    assert paths.config_file().read_text() == before

def test_parameters_frozen_after_first_job(proj):
    yamledit.update_config({("species_locked",): True})
    # #pa-MAFFT_OPT, #pa-s2_inflation, #pa-REFSPECIES disabled; #pa-reason mentions "first job"
    # #pa-s1_ncpu enabled: typing "8" + enter writes 8

def test_parameters_generax_group_greyed_when_off(proj): ...  # run_generax false -> #pa-SUBS_MODEL disabled

def test_no_config_editor(proj):
    assert "Config" not in setup_tui.SetupScreen.SECTIONS and not hasattr(setup_tui, "_run_editor")
```

- [ ] **Step 2: Run, expect FAIL** — `python3 -m pytest -q -p no:cacheprovider tests/test_setup_tui.py`

- [ ] **Step 3: Implement.** Use `Select` (allow_blank=False) for preset/species fields, `Input` for numbers and the path (write on `Input.Submitted`). Setting a widget's value from the file must not write (`prevent(Select.Changed)`, like the switches). The `Parameters` mark: `"!"` when `self._cfg is None`, else `"✓"`. Keep the old `#sec-config` content's path line as `#pa-path`.

- [ ] **Step 4: Run `tests/test_setup_tui.py`, then the full suite, expect PASS** (728+ passed; the known treeview failure, if present, is pre-existing)

- [ ] **Step 5: Commit** — `git commit -m "Setup: Parameters section replaces the nano Config editor"`
