# Project `proteomes/` implicit source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** druid picks up `<project>/proteomes/<code>.pep` as a source named `project` with no Setup step; a code the default source also offers is taken from the default source.

**Architecture:** All logic lives in `druid/setup_state.py` (`sources()` adds the implicit source; `candidates()` drops shadowed codes; a new `project_notes()` lists shadowed/ignored files; a new `source_taxonomy()` merges the local table over the default one). Consumers (`prepare.py`, `setup_tui.py`) switch to those helpers. Nothing is written to `druid.yaml`.

**Tech Stack:** Python 3, Textual (Setup TUI), pytest.

**Spec:** `docs/superpowers/specs/2026-11-25-project-proteomes-source-design.md`

## Global Constraints

- Source name `project`; directory `<project root>/proteomes`; glob `{sp}.pep`; local taxonomy `proteomes/taxonomy.tsv`.
- Taxonomy format unchanged: no header; col 1 code, col 2 Latin name, col 6 lineage (`read_taxonomy`).
- Local rows win; a code with no local row falls back to the default source's table.
- Default source wins **by code** only (no Latin-name matching).
- Shadow note copy: `{sp}: default source used (proteomes/{file} not offered)`.
- Ignored note copy: `proteomes/{name}: ignored (not <code>.pep)`; a `<code>.pep` that is not a file: `proteomes/{name}: ignored (not a file)`.
- Nothing written to `druid.yaml`; explicit `sources:` entries unchanged; `project` reserved as a new source name in Setup.
- druid never writes into `proteomes/` or the default proteomes dir (read-only sources).
- Full suite before each commit: `python -m pytest -q 2>&1 | tail -1` must report 0 failed.

## Review Focus

1. Symlinked `.pep` files (the real project uses symlinks into another user's dir): must be offered; a broken symlink must be listed, not vanish. → Task 1 tests `test_project_source_symlinks`.
2. An explicit `sources:` entry pointing at the same `proteomes/` dir (Grygoriy may have added one by hand): no duplicate candidates. → Task 1 `test_project_source_skipped_when_explicit_same_dir`.
3. `proteomes/taxonomy.tsv` absent: Smed-like codes still get rows from the default table; others are rowless blockers. → Task 1 `test_project_taxonomy_fallback`.
4. Projects without `proteomes/` behave exactly as before (sources list length, candidates). → Task 1 `test_no_proteomes_dir_no_project_source`.
5. `species_info.tsv` for a species ticked from `project` with only a fallback row gets the Latin name. → Task 2 `test_species_info_project_fallback`.

---

### Task 1: implicit source in `setup_state`

**Files:**
- Modify: `druid/setup_state.py` (`Source`, `sources`, `candidates`; new `source_taxonomy`, `project_notes`, constants)
- Test: `tests/test_setup_state.py`

**Interfaces:**
- Produces:
  - constants `PROJECT = "project"`, `PROJECT_DIR = "proteomes"`, `PROJECT_GLOB = "{sp}.pep"`, `PROJECT_TAXONOMY = "taxonomy.tsv"`
  - `Source` gains a last field `fallback_taxonomy: "Path | None" = None` (existing positional constructions keep working)
  - `source_taxonomy(src: Source) -> dict` — `read_taxonomy(fallback)` updated by `read_taxonomy(src.taxonomy)`; just `read_taxonomy(src.taxonomy)` when no fallback
  - `candidates(srcs) -> (cands, rowless)` — same signature; reads rows via `source_taxonomy`; drops `project` candidates whose `sp` is a default-source candidate
  - `project_notes(srcs) -> list[str]` — shadow lines then ignored lines (sorted by file name), `[]` when no `project` source

- [ ] **Step 1: Write the failing tests** (reuse the file's `proj` fixture: default dir `prot` has Aaa, Bbb, Zzz; `data/tax.tsv` rows Aaa, Bbb, Ccc). Helper `_projdir(root, files, tax=None) -> Path` creates and returns `root/"proteomes"` with `>x\nM\n` files and, when `tax` is not None, `taxonomy.tsv` with that text.

```python
def test_no_proteomes_dir_no_project_source(proj):
    root, _ = proj
    raw, _ = _raw()
    assert [s.name for s in ss.sources(raw, root)] == ["default"]

def test_project_source_added_after_default(proj):
    root, _ = proj
    _projdir(root, ["Ccc.pep"])
    raw, _ = _raw()
    a, b = ss.sources(raw, root)[:2]
    assert (b.name, b.proteomes_dir, b.glob, b.taxonomy, b.fallback_taxonomy) == (
        "project", root / "proteomes", "{sp}.pep", root / "proteomes" / "taxonomy.tsv", a.taxonomy)
    assert not (root / "proteomes" / "taxonomy.tsv").exists()          # nothing written
    assert "sources" not in raw or not raw["sources"]

def test_project_taxonomy_fallback(proj):
    root, _ = proj
    _projdir(root, ["Ccc.pep", "Qqq.pep", "Rrr.pep"],
             tax="Qqq\tQqq local\t1\t1\t1\tMetazoa, Q\n")
    raw, _ = _raw()
    cands, rowless = ss.candidates(ss.sources(raw, root))
    proj_c = {c.sp: c for c in cands if c.source == "project"}
    assert set(proj_c) == {"Ccc", "Qqq"}                               # Ccc via fallback, Qqq local
    assert proj_c["Ccc"].name == "Ccc sp" and proj_c["Qqq"].name == "Qqq local"
    assert rowless == ["project: Rrr.pep"]

def test_project_local_row_wins_over_fallback(proj):
    root, _ = proj
    _projdir(root, ["Ccc.pep"], tax="Ccc\tCcc local\t1\t1\t1\tMetazoa, L\n")
    raw, _ = _raw()
    c = [c for c in ss.candidates(ss.sources(raw, root))[0] if c.source == "project"][0]
    assert (c.name, c.taxonomy) == ("Ccc local", "Metazoa, L")

def test_default_source_wins_by_code(proj):
    root, _ = proj
    _projdir(root, ["Aaa.pep", "Ccc.pep", "notes.txt", "Bbb.fasta"], tax="")
    raw, _ = _raw()
    srcs = ss.sources(raw, root)
    cands, _ = ss.candidates(srcs)
    assert [(c.sp, c.source) for c in cands] == [("Aaa", "default"), ("Bbb", "default"), ("Ccc", "project")]
    assert ss.project_notes(srcs) == [
        "Aaa: default source used (proteomes/Aaa.pep not offered)",
        "proteomes/Bbb.fasta: ignored (not <code>.pep)",
        "proteomes/notes.txt: ignored (not <code>.pep)"]                # taxonomy.tsv not listed

def test_project_source_symlinks(proj, tmp_path):
    root, _ = proj
    d = _projdir(root, [])
    real = tmp_path / "elsewhere.pep"; real.write_text(">x\nM\n")
    (d / "Ccc.pep").symlink_to(real)
    (d / "Ddd.pep").symlink_to(tmp_path / "missing.pep")                # broken
    raw, _ = _raw()
    srcs = ss.sources(raw, root)
    assert [c.sp for c in ss.candidates(srcs)[0] if c.source == "project"] == ["Ccc"]
    assert ss.project_notes(srcs) == ["proteomes/Ddd.pep: ignored (not a file)"]

def test_project_source_skipped_when_explicit_same_dir(proj):
    root, _ = proj
    _projdir(root, ["Ccc.pep"])
    yamledit.update_config({("sources",): [{"name": "mine", "proteomes_dir": "proteomes",
                                            "proteome_glob": "{sp}.pep", "taxonomy": "data/tax.tsv"}]})
    raw, _ = _raw()
    assert [s.name for s in ss.sources(raw, root)] == ["default", "mine"]

def test_explicit_source_named_project_wins(proj, tmp_path):
    root, _ = proj
    _projdir(root, ["Ccc.pep"])
    d = _custom(tmp_path)
    yamledit.update_config({("sources",): [{"name": "project", "proteomes_dir": str(d)}]})
    raw, _ = _raw()
    srcs = ss.sources(raw, root)
    assert [s.name for s in srcs] == ["default", "project"]
    assert srcs[1].proteomes_dir == d and srcs[1].fallback_taxonomy is None
    assert ss.project_notes(srcs) == []                                 # notes only for the implicit one
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_setup_state.py -q -k "project or proteomes_dir"`
Expected: FAIL (`fallback_taxonomy` / `project_notes` not defined).

- [ ] **Step 3: Implement in `druid/setup_state.py`**

`sources()`: after building default + explicit entries, insert the implicit source at index 1 when `(root / PROJECT_DIR).is_dir()`, no explicit entry is named `PROJECT`, and no explicit source's `proteomes_dir.resolve()` equals `(root / PROJECT_DIR).resolve()`. Its `fallback_taxonomy` is the default source's `taxonomy`. `candidates()`: read rows with `source_taxonomy(s)`; after the loop drop `project` candidates whose `sp` is among default-source candidates. `project_notes()` identifies the implicit source by `name == PROJECT and fallback_taxonomy is not None` (so a hand-written `project` entry gets no notes); shadow lines use the same default-candidate set; ignored = every directory entry except `taxonomy.tsv` that does not fullmatch the glob, plus glob matches that are not files.

- [ ] **Step 4: Run the tests, then the full suite**

Run: `python -m pytest tests/test_setup_state.py -q` then `python -m pytest -q 2>&1 | tail -1`
Expected: all pass; full suite 0 failed.

- [ ] **Step 5: Commit**

```bash
git add druid/setup_state.py tests/test_setup_state.py
git commit -m "setup_state: <project>/proteomes as implicit source 'project' (default source wins by code)"
```

### Task 2: consumers — prepare, Setup TUI, docs

**Files:**
- Modify: `druid/prepare.py:41-48` (`_species_info_text`)
- Modify: `druid/setup_tui.py` (`_fill_source` ~line 693, `_source_error` ~line 1030)
- Modify: `docs/reference.md` (druid.yaml section, after the `proteomes_dir` / `proteome_glob` / `species` sentence ~line 294)
- Test: `tests/test_prepare.py`, `tests/test_setup_tui.py`

**Interfaces:**
- Consumes: `setup_state.PROJECT`, `PROJECT_DIR`, `source_taxonomy(src)`, `project_notes(srcs)`, `Source.fallback_taxonomy` (Task 1).

- [ ] **Step 1: Write the failing tests**

`tests/test_prepare.py` (use its `proj` fixture; tick a `project` species whose row exists only in the default table):

```python
def test_species_info_project_fallback(proj):
    # root/proteomes/Ccc.pep, no proteomes/taxonomy.tsv; Ccc has a row only in data/tax.tsv
    # tick {sp: Ccc, source: project} (+ the fixture's ticked species), run prepare
    # assert the Ccc line of data/species_info.tsv has Latin name "Ccc sp" (not "Ccc")
```

`tests/test_setup_tui.py` (its `proj` fixture: default `prot` has Aaa, Bbb; tax rows Aaa, Bbb, Ccc):

```python
def test_project_source_listed_with_notes(proj):
    # root/proteomes: Aaa.pep, Ccc.pep, x.txt
    # Setup › Source: #src-list contains "project:", "Aaa: default source used (proteomes/Aaa.pep not offered)",
    #   "proteomes/x.txt: ignored (not <code>.pep)", and the project taxonomy line names both tables
    # #sp-table row_count == 3 (Aaa, Bbb default; Ccc project)

def test_project_name_reserved_without_dir(proj):
    # no root/proteomes; add source named "project" (dir = mine) -> nothing written, "ERROR:" in #blockers
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_prepare.py tests/test_setup_tui.py -q -k "project"`
Expected: FAIL.

- [ ] **Step 3: Implement**

`prepare._species_info_text`: `ss.source_taxonomy(s)` instead of `ss.read_taxonomy(s.taxonomy)`. `setup_tui._fill_source`: for a source with `fallback_taxonomy`, the taxonomy line reads `taxonomy {s.taxonomy} (missing rows: {s.fallback_taxonomy})`; after the source lines append `project_notes(self._srcs)` lines indented 4 spaces. `_source_error`: add `setup_state.PROJECT` to the reserved names. `docs/reference.md`: one paragraph stating the spec's Design bullets (dir, glob, taxonomy + fallback, default wins by code, notes, reserved name, nothing written).

- [ ] **Step 4: Run the tests, then the full suite**

Run: `python -m pytest tests/test_prepare.py tests/test_setup_tui.py -q` then `python -m pytest -q 2>&1 | tail -1`
Expected: all pass; full suite 0 failed.

- [ ] **Step 5: Commit**

```bash
git add druid/prepare.py druid/setup_tui.py docs/reference.md tests/test_prepare.py tests/test_setup_tui.py
git commit -m "Setup/prepare: show the project source's notes, reserve its name, fallback taxonomy in species_info"
```

## After the tasks (controller)

Grygoriy pushes; then a read-only check on the real project over ssh:
`cd /users/asebe/gzolotarov/projects/2026_planaria/Phylogenies && python -c "from druid import setup_state as s, paths; r=paths.read_raw(); x=s.sources(r, paths.project_root()); print([c.sp+'/'+c.source for c in s.candidates(x)[0] if c.source=='project'], s.candidates(x)[1], s.project_notes(x))"`
Expected before `proteomes/taxonomy.tsv` exists: no `project` candidates (Smed shadowed), rowless `project: Djap.pep`, `Gtig.pep`, `Pnig.pep`, `Spol.pep`, note `Smed: default source used (proteomes/Smed.pep not offered)`.
