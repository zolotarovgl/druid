# phylocli TUI Results window + overview sort/hide — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `o` opens a third TUI window, **Results**, with four panes (`Results` / `OGs` / `members` / `species`): the HGs of a group, the POSSVM ortholog groups of the highlighted HG with call and support, the annotation-file rows of the highlighted OG (filterable with `/`) and its per-phylum species counts. In the overview, `s` sorts and `h` hides rows by the highlighted column.

**Architecture:** `model.py` gains print-free readers: `read_ogs` / `group_ogs` (one directory listing per load) produce `OG`s whose `genes` are `Member` rows; `species_universe` (tip names of the species tree by regex, no ete3), `phyla` (`species_info.tsv`) and `og_species_stats` give the per-phylum counts. `tui.py` adds a `results` view next to `overview` / `hgs`; every file read runs in a worker of its own group (`"results"`), so the existing `load_bg` refresh and this load never cancel each other; cursor moves and the filter work on the in-memory snapshot. Sort/hide is a pure function `ov_order(rows, sort, hide)` over the in-memory `ov_rows`, keyed by column name.

**Tech Stack:** Python ≥ 3.9, Textual 8.2.8 (optional), pytest. No ete3.

**Spec:** `docs/superpowers/specs/2026-10-09-phylocli-tui-og-explorer-sort-design.md` — Part A (Results window; amended 09/10/2026: no species-tree drawing, members + species panes, commit `8beca66`) and Part B (overview sort and filter).

**Repo / branch:** worktree `~/Documents/projects/phylogenies/phylocli-wt`, branch `phylocli`, HEAD `8beca66` (code = `a0fb496`, 253 tests). Step1 is built; `tui.py` there has: `TUI_STAGES = core.STAGES` (search, cluster first); `OV_COLUMNS = [*FAMILY_STAGES, None, *HG_STAGES]` with a `│` separator column (`None`), `OV_TOP`, a two-row header with unkeyed `Text` labels; `ov_column(stage)` and `stage_at_column(col)` (the one column↔stage mapping; None for group, HGs and `│`); `_set_units` (the `#hgs`/`#arrays` columns are built there, not in `on_mount`); family rows in the HG view at search/cluster (`r.hg` is then a family id); `_ov_inputs = (exp, states, fams, fstates)`; `GroupRow.n_fams`, and `per_stage` for search/cluster counts families. No existing binding uses `o`, `p`, `/`, `s` or `h` (BINDINGS: escape, c, f, space, a, r, l, R, q). Locate code by function name, not line number; never revert step1's code; `git add` only the files a task lists. This whole plan was applied to a scratch copy of `a0fb496` and both suites passed (286 = 253 + 33, 09/10/2026).

## File Structure

| file | change | responsibility |
|---|---|---|
| `phylocli/model.py` | append | `OG`, `Member`, `HGOgs`, `PhylumRow`, `read_ogs`, `group_ogs`, `species_of`, `hg_sort_key`, `default_source`, `species_universe`, `species_info_path`, `phyla`, `og_species_stats`, `og_outside` (no Textual) |
| `phylocli/tui.py` | modify | Results view (compose, CSS, bindings, worker, four panes, `/` filter); overview `s`/`h` (`ov_order`, title) |
| `phylocli/README.md` | modify | `## phylo tui`: Results window, `o`/`p`/`/`, `s`/`h` |
| `phylocli/tests/test_model.py` | append | readers + shared fixture data (`OG_HEAD`, `SP4`, `SPINFO`, `write_results`) |
| `phylocli/tests/test_tui.py` | append | Results window and overview sort/hide pilot tests |

## Global Constraints

- CLI output text and exit codes of every `phylo` command stay byte-identical. **No existing test is modified** (the spec changes no existing expectation). `test_panes_are_named_top_left` iterates `PANE_TITLES`, so the four new entries are covered by it unchanged.
- Python 3.9-safe (`from __future__ import annotations`; no `match`; no `X | Y` outside annotations; annotations in `tui.py` written as strings, as the file already does).
- Textual is imported only in `tui.py`. Nothing in this plan imports ete3: the species universe is the tip names of `params.SPECIES_TREE`, read with a regex.
- No file or SLURM access on a key press (`o`, `p`, `/`, typing in the filter, `s`, `h`, `esc`, `tab`, cursor moves). File reads go in workers: `load_bg` (existing) and `_load_results` (new, `group="results"`), following the `_collect` / `_apply` pattern (worker builds a snapshot dict, `call_from_thread` applies it, exceptions never escape the worker). The species universe and the phyla are read once per session (cached on the app after the first successful read).
- `species_info.tsv` is found next to the species tree (`Path(params.SPECIES_TREE).parent / "species_info.tsv"`, i.e. `data/species_info.tsv`), overridable by an optional `params.species_info`; no change to `config.yaml`, `core.PATH_PARAMS` or `conftest.py`.
- Overview sort/hide is keyed by column **name**, never by column index: column 0 = `group`, 1 = `HGs`, every other column goes through step1's `stage_at_column(col)`; the `│` separator (None) does nothing. Sort/hide state stores the stage name, so it survives any later column change. Family stages (search, cluster) sort and hide on their `per_stage` family counts.
- `ov_rows` keeps its current meaning (the rows as computed by `model.group_rows`); the displayed order lives in a new `ov_shown`. Existing tests read `ov_rows`.
- Test commands (both must pass, output clean):
  `python3 -m pytest phylocli/tests -q -p no:cacheprovider` and
  `/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-phylogenies/3dad6ea4-c859-4fe6-b319-93a358944ac8/scratchpad/py39/bin/python -m pytest phylocli/tests -q -p no:cacheprovider`.
  Baseline 253 at `a0fb496`. Record **N0 = the passed count before you start each task**; each task states its delta (Task 1 +11, Task 2 +14, Task 3 +8; 286 total from 253 if nothing else lands).
- Commit on `phylocli`, message ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Edit with Edit/Write tools only, never sed or python string-replace.
- Dates in docs are `dd/mm/yyyy`.

## Review Focus

1. **Big groups** — `o` on `ALL` or on a 556-HG family (`tfs.zf-C2H2`) over NFS must list each source directory once per load, not once per HG → Task 1 `test_group_ogs_lists_hgs_with_output_one_listing`.
2. **The periodic refresh during a Results load** — `load_bg` is `exclusive=True` in the default worker group; if `_load_results` shared that group, a refresh would cancel it and Results would stay empty forever → Task 2 `test_results_read_in_worker_shows_loading` calls `load_bg()` mid-load.
3. **Real support values other than a plain positive number** — v3 POSSVM writes `-1` (measured 09/10/2026: 10,804 rows in the first 300 `possvm/` files, 2,780 in `possvm_prev/`; root-spanning groups); `NA` was not seen but is accepted. These must parse (no "unparseable row"), display as numbers / `–`, and never get `⚠`, which is for exactly 0 → Task 1 `test_read_ogs_negative_and_na_support`.
4. **Species files missing or ragged** — no species tree or no `species_info.tsv`: OGs and members must still work and the species pane must name the file and the error (Task 2 `test_results_without_species_files_still_lists_ogs`). The real `species_info.tsv` (189 rows) has rows with a trailing tab (`Lpol`) and rows with no phylum column (`Dicjap`, `Clim`; measured 09/10/2026): they parse, the latter as `unknown` (Task 1 `test_phyla_from_species_info`).
5. **Sorted or filtered overview** — `enter`, `o` and `esc` act on the row under the cursor by key (not the pre-sort index), and hiding the row under the cursor lands the cursor on a shown row → Task 3 `test_enter_on_sorted_overview_opens_row_under_cursor`.

---

### Task 1: `model` — POSSVM ortholog groups, members and species stats

**Files:**
- Modify: `phylocli/model.py` (append at the end)
- Test: `phylocli/tests/test_model.py` (append)

**Interfaces:**
- Consumes: `core.Config` (`cfg.outdir: Path`, `cfg.params: dict`; `params["SPECIES_TREE"]` is absolute after `load_config`), `core.ROOT`, `core.report_status.nonempty_files(d: str) -> set[str]` (existing: names of non-empty files in a directory, empty set when the directory is missing), `ModelError(msg, code=1)`.
- Produces:
  - `OG_SUFFIX = ".ortholog_groups.csv"`, `OG_HEADER: list[str]`
  - `@dataclass Member: gene: str; species: str; ref: str; ref_support: str` — one annotation-file row (`species = species_of(gene)`; `ref` / `ref_support` = that row's `reference_ortholog` / `reference_support`, as written)
  - `@dataclass OG: id: str` (`<hg>.<n>`, e.g. `tfs.T-box.HG1.0`); `name: str` (after the first `:`, e.g. `like:Tbx2/Tbx3`); `genes: list[Member]` (file order); `support: float | None` (`orthogroup_support`; None for `NA`/empty); `ref: str`; `ref_support: str` (from the OG's first row)
  - `@dataclass HGOgs: hg: str; ogs: list[OG]; error: str = ""` (error = a `ModelError` message; then `ogs == []`)
  - `@dataclass PhylumRow: phylum: str; covered: int; total: int; n_genes: int; species: list[tuple[str, int]]`
  - `read_ogs(cfg, hg: str, source: str, names: set[str] | None = None) -> list[OG] | None` — sorted by gene count desc, then OG number; None when no non-empty file; `ModelError` for two files / bad header / bad row (message starts `<path>:<line>:`)
  - `group_ogs(cfg, hgs, source: str) -> tuple[list[HGOgs], int]` — rows for HGs with output (sorted by `hg_sort_key`), number without output; one directory listing
  - `species_of(gene) -> str`, `hg_sort_key(hg) -> tuple`, `default_source(cfg) -> str` (`"possvm"` when `<outdir>/possvm/` is a directory, else `"possvm_prev"`)
  - `species_universe(cfg) -> list[str]` — tip names of `params.SPECIES_TREE`, newick order, by regex (FileNotFoundError when missing)
  - `species_info_path(cfg) -> Path`; `phyla(cfg) -> dict[str, str]` — species code → phylum (column 3; missing/empty → `"unknown"`)
  - `og_species_stats(og, universe, phyla) -> list[PhylumRow]` — one row per phylum of the universe (species without a phylum → `"unknown"`): phyla with members first (by `n_genes` desc, then name), then absent ones (by name); `species` = `(code, n)` with n > 0, by n desc then code
  - `og_outside(og, universe) -> list[tuple[str, int]]` — member species not in the universe, by n desc then code
  - Test helpers (module level in `test_model.py`, imported by `test_tui.py` in Task 2): `OG_HEAD`, `SP4`, `SPINFO`, `POSSVM_HG1`, `POSSVM_HG11`, `PREV_HG1`, `og_csv(rows) -> str`, `write_results(cfg) -> None`

Real-data checks done while writing this plan (09/10/2026): the tip regex below returns the same 59 names, in the same order, as ete3's `get_leaf_names()` on `data/species_tree.binary.newick`; all 59 are rows of `data/species_info.tsv` (189 rows, `code\tLatin name\tphylum`).

- [ ] **Step 1: Write the failing tests** (append to `phylocli/tests/test_model.py`):

```python
# ---- ortholog groups (Results window) --------------------------------------------------------
from pathlib import Path  # noqa: E402

OG_HEAD = "gene\torthogroup\torthogroup_support\treference_ortholog\treference_support\n"
SP4 = "((Mlei:1,Bova:1)Cteno:1,(Hsap:1,Nvec:1)Para:1);\n"       # 4 tips; internal names ignored
SPINFO = ("Mlei\tMnemiopsis leidyi\tCtenophora\n"
          "Bova\tBeroe ovata\tCtenophora\n"
          "Hsap\tHomo sapiens\tChordata\t\n"                    # trailing tab, as Lpol in v3
          "Nvec\tNematostella vectensis\n"                      # no phylum column, as Dicjap
          "\n"
          "Zzz\tZz zz\tPorifera\n")                             # not a tip of the species tree
POSSVM_HG1 = [("Mlei_v05_G1", "tfs.A.HG1.0:T/Tbx19", "78.4", "T/Tbx19", "98.2/98.2"),
              ("Mlei_v05_G2", "tfs.A.HG1.0:T/Tbx19", "78.4", "T/Tbx19", "98.2/98.2"),
              ("Hsap_ENSP1", "tfs.A.HG1.0:T/Tbx19", "78.4", "T/Tbx19", "98.2/98.2"),
              ("Hsap_ENSP2", "tfs.A.HG1.1:like:Eomes/Tbr1", "0.0", "NA", "NA"),
              ("Nvec_v1_g3", "tfs.A.HG1.1:like:Eomes/Tbr1", "0.0", "NA", "NA")]
POSSVM_HG11 = [("Bova_x1", "tfs.A.HG11.0:Tbx20", "85.0", "Tbx20", "90.0"),
               ("Mlei_v05_G9", "tfs.A.HG11.0:Tbx20", "85.0", "Tbx20", "90.0")]
PREV_HG1 = [("Mlei_v05_G1", "tfs.A.HG1.0:like:Tbx2/Tbx3", "98.0", "NA", "NA"),
            ("Zzz_q1", "tfs.A.HG1.0:like:Tbx2/Tbx3", "98.0", "NA", "NA")]


def og_csv(rows) -> str:
    return OG_HEAD + "".join("\t".join(r) + "\n" for r in rows)


def write_results(cfg) -> None:
    """POSSVM output for tfs.A.HG1 (possvm + possvm_prev) and tfs.A.HG11 (possvm only), the
    4-tip species tree and species_info.tsv next to it.  tfs.C_x.HG1 keeps no output."""
    o = cfg.outdir
    (o / "possvm/tfs.A.HG1.generax.support.tree.ortholog_groups.csv").write_text(og_csv(POSSVM_HG1))
    (o / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv").write_text(og_csv(POSSVM_HG11))
    (o / "possvm_prev/tfs.A.HG1.treefile.ortholog_groups.csv").write_text(og_csv(PREV_HG1))
    tree = Path(cfg.params["SPECIES_TREE"])
    tree.write_text(SP4)
    (tree.parent / "species_info.tsv").write_text(SPINFO)


def test_read_ogs_parses_and_sorts(cli):
    cfg = _cfg()
    write_results(cfg)
    ogs = model.read_ogs(cfg, "tfs.A.HG1", "possvm")
    assert [(o.id, o.name, len(o.genes), o.support, o.ref, o.ref_support) for o in ogs] == [
        ("tfs.A.HG1.0", "T/Tbx19", 3, 78.4, "T/Tbx19", "98.2/98.2"),
        ("tfs.A.HG1.1", "like:Eomes/Tbr1", 2, 0.0, "NA", "NA")]
    assert [m.gene for m in ogs[0].genes] == ["Mlei_v05_G1", "Mlei_v05_G2", "Hsap_ENSP1"]
    assert ogs[1].genes[0] == model.Member("Hsap_ENSP2", "Hsap", "NA", "NA")
    # tfs.A.HG1 must not pick up tfs.A.HG11's file (HG1 is a prefix of HG11)
    assert [o.id for o in model.read_ogs(cfg, "tfs.A.HG11", "possvm")] == ["tfs.A.HG11.0"]
    assert [o.name for o in model.read_ogs(cfg, "tfs.A.HG1", "possvm_prev")] == ["like:Tbx2/Tbx3"]


def test_read_ogs_none_when_missing_or_empty(cli):
    cfg = _cfg()
    assert model.read_ogs(cfg, "tfs.C_x.HG1", "possvm") is None
    assert model.read_ogs(cfg, "tfs.A.HG11", "possvm") is None     # fixture file is empty = not done
    assert model.read_ogs(cfg, "tfs.A.HG1", "no_such_dir") is None


def test_read_ogs_two_files_is_error(cli):
    cfg = _cfg()
    write_results(cfg)
    (cfg.outdir / "possvm/tfs.A.HG1.generax.tree.ortholog_groups.csv").write_text(og_csv(POSSVM_HG1))
    with pytest.raises(model.ModelError) as e:
        model.read_ogs(cfg, "tfs.A.HG1", "possvm")
    assert "tfs.A.HG1.generax.tree.ortholog_groups.csv" in str(e.value)
    assert "tfs.A.HG1.generax.support.tree.ortholog_groups.csv" in str(e.value)


def test_read_ogs_bad_rows_name_file_and_line(cli):
    cfg = _cfg()
    with pytest.raises(model.ModelError, match=r":1: not a POSSVM"):  # fixture file holds "x\n"
        model.read_ogs(cfg, "tfs.A.HG1", "possvm_prev")
    p = cfg.outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv"
    p.write_text(OG_HEAD + "Mlei_v05_G9\ttfs.A.HG11.0:Tbx20\t85.0\tTbx20\t90.0\nbroken row\n")
    with pytest.raises(model.ModelError, match=r"ortholog_groups\.csv:3: cannot parse row"):
        model.read_ogs(cfg, "tfs.A.HG11", "possvm")
    p.write_text(OG_HEAD + "Mlei_v05_G9\ttfs.A.HG11.0:Tbx20\tlots\tTbx20\t90.0\n")
    with pytest.raises(model.ModelError, match=r":2: bad orthogroup_support 'lots'"):
        model.read_ogs(cfg, "tfs.A.HG11", "possvm")
    p.write_text(OG_HEAD + "Mlei_v05_G9\ttfs.B.HG2.0:Tbx20\t85.0\tTbx20\t90.0\n")   # wrong HG
    with pytest.raises(model.ModelError, match=r":2: cannot parse row"):
        model.read_ogs(cfg, "tfs.A.HG11", "possvm")


def test_read_ogs_negative_and_na_support(cli):
    cfg = _cfg()
    p = cfg.outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv"
    p.write_text(og_csv([("Mlei_v05_G9", "tfs.A.HG11.1:Tbx20", "-1", "Tbx20", "95.3"),
                         ("Hsap_E1", "tfs.A.HG11.0:like:Tbx1", "NA", "NA", "NA")]))
    ogs = model.read_ogs(cfg, "tfs.A.HG11", "possvm")
    assert [(o.id, o.support) for o in ogs] == [("tfs.A.HG11.0", None), ("tfs.A.HG11.1", -1.0)]


def test_species_of():
    assert model.species_of("Mlei_v05_G009201") == "Mlei"
    assert model.species_of("Mertsp_Mesp_sb563561") == "Mertsp"
    assert model.species_of("nounderscore") == "nounderscore"


def test_group_ogs_lists_hgs_with_output_one_listing(cli, monkeypatch):
    cfg = _cfg()
    write_results(cfg)
    (cfg.outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv").write_text(
        OG_HEAD + "bad\n")
    calls = []
    real = core.report_status.nonempty_files
    monkeypatch.setattr(core.report_status, "nonempty_files", lambda d: calls.append(d) or real(d))
    rows, missing = model.group_ogs(cfg, ["tfs.C_x.HG1", "tfs.A.HG11", "tfs.A.HG1"], "possvm")
    assert [r.hg for r in rows] == ["tfs.A.HG1", "tfs.A.HG11"] and missing == 1
    assert len(rows[0].ogs) == 2 and rows[0].error == ""
    assert rows[1].ogs == [] and ":2: cannot parse row" in rows[1].error
    assert len(calls) == 1                                   # one listing for all HGs
    assert sorted(["tfs.A.HG2", "tfs.A.HG10", "tfs.A.HG1"], key=model.hg_sort_key) == \
        ["tfs.A.HG1", "tfs.A.HG2", "tfs.A.HG10"]


def test_default_source(cli):
    import shutil
    cfg = _cfg()
    assert model.default_source(cfg) == "possvm"
    shutil.rmtree(cfg.outdir / "possvm")
    assert model.default_source(cfg) == "possvm_prev"


def test_species_universe_reads_tip_names(cli):
    cfg = _cfg()
    write_results(cfg)
    assert model.species_universe(cfg) == ["Mlei", "Bova", "Hsap", "Nvec"]
    Path(cfg.params["SPECIES_TREE"]).write_text("((A:1,(B:0.5,C:2)x.y:1)Clade_1:1,D);\n")
    assert model.species_universe(cfg) == ["A", "B", "C", "D"]          # clade names skipped
    Path(cfg.params["SPECIES_TREE"]).unlink()
    with pytest.raises(FileNotFoundError):
        model.species_universe(cfg)


def test_phyla_from_species_info(cli):
    cfg = _cfg()
    write_results(cfg)
    assert model.species_info_path(cfg) == Path(cfg.params["SPECIES_TREE"]).parent / "species_info.tsv"
    assert model.phyla(cfg) == {"Mlei": "Ctenophora", "Bova": "Ctenophora", "Hsap": "Chordata",
                                "Nvec": "unknown", "Zzz": "Porifera"}


def test_og_species_stats_per_phylum(cli):
    cfg = _cfg()
    write_results(cfg)
    uni, ph = model.species_universe(cfg), model.phyla(cfg)
    og = model.read_ogs(cfg, "tfs.A.HG1", "possvm")[0]            # Mlei 2, Hsap 1
    rows = model.og_species_stats(og, uni, ph)
    assert [(r.phylum, r.covered, r.total, r.n_genes, r.species) for r in rows] == [
        ("Ctenophora", 1, 2, 2, [("Mlei", 2)]),
        ("Chordata", 1, 1, 1, [("Hsap", 1)]),
        ("unknown", 0, 1, 0, [])]                                  # absent phyla last
    assert model.og_outside(og, uni) == []
    prev = model.read_ogs(cfg, "tfs.A.HG1", "possvm_prev")[0]     # Mlei 1, Zzz 1
    assert model.og_outside(prev, uni) == [("Zzz", 1)]            # in species_info, not a tip
    assert [r.phylum for r in model.og_species_stats(prev, uni, {})] == ["unknown"]
```

(The fixture, `conftest.results_tree`, already holds `possvm_prev/tfs.A.HG1.treefile.ortholog_groups.csv` = `"x\n"`, an **empty** `possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv` (`report_status` counts an empty file as "not done", so `read_ogs` does too) and `params.SPECIES_TREE = <root>/species.newick` = `"(a,b);\n"`, which `write_results` overwrites.)

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_model.py -q -p no:cacheprovider` — Expected: FAIL, `AttributeError: module 'phylocli.model' has no attribute 'read_ogs'` (and `'Member'`, `'species_universe'`, …).

- [ ] **Step 3: Implement** (append to `phylocli/model.py`; `re`, `collections`, `dataclass`, `Path`, `core` are already imported there):

```python
# ---- POSSVM ortholog groups (TUI Results window) ---------------------------------------------
OG_SUFFIX = ".ortholog_groups.csv"
OG_HEADER = ["gene", "orthogroup", "orthogroup_support", "reference_ortholog", "reference_support"]


@dataclass
class Member:
    gene: str
    species: str               # species_of(gene)
    ref: str                   # this row's reference_ortholog (as written, NA included)
    ref_support: str           # this row's reference_support (as written)


@dataclass
class OG:
    id: str                    # <hg>.<n>, e.g. tfs.T-box.HG1.0
    name: str                  # after the first ':', e.g. like:Tbx2/Tbx3
    genes: list                # [Member], file order
    support: "float | None"    # orthogroup_support; None for NA / empty
    ref: str                   # reference_ortholog of the OG's first row
    ref_support: str


@dataclass
class HGOgs:
    hg: str
    ogs: list                  # [OG]; [] when error is set
    error: str = ""


@dataclass
class PhylumRow:
    phylum: str
    covered: int               # species of this phylum with >= 1 member
    total: int                 # species of this phylum in the universe
    n_genes: int
    species: list              # [(code, n)] with n > 0, n desc


def species_of(gene: str) -> str:
    """Species code = the gene id up to the first '_' (Mlei_v05_G1 -> Mlei)."""
    return gene.split("_", 1)[0]


def read_ogs(cfg: core.Config, hg: str, source: str, names: set[str] | None = None):
    """The ortholog groups of one HG, largest first, from
    <outdir>/<source>/<hg>.<tree name>.ortholog_groups.csv.  None when there is no non-empty
    such file (report_status counts an empty one as not done).  `names` = the directory's
    non-empty file names, so that group_ogs lists the directory once for many HGs."""
    d = cfg.outdir / source
    if names is None:
        names = core.report_status.nonempty_files(str(d))
    files = sorted(n for n in names if n.startswith(hg + ".") and n.endswith(OG_SUFFIX))
    if not files:
        return None
    if len(files) > 1:
        raise ModelError(f"{hg}: {len(files)} ortholog_groups.csv files in {d}: {', '.join(files)}")
    path = d / files[0]
    by: dict[str, OG] = {}
    with open(path, errors="replace") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.rstrip("\r\n")
            if ln == 1:
                if line.split("\t") != OG_HEADER:
                    raise ModelError(f"{path}:1: not a POSSVM ortholog_groups.csv header: {line[:80]!r}")
                continue
            if not line.strip():
                continue
            f = line.split("\t")
            og_id, sep, name = f[1].partition(":") if len(f) == 5 else ("", "", "")
            n = og_id[len(hg) + 1:] if og_id.startswith(hg + ".") else ""
            if len(f) != 5 or not sep or not n.isdigit():
                raise ModelError(f"{path}:{ln}: cannot parse row {line[:120]!r}")
            try:
                sup = None if f[2] in ("", "NA") else float(f[2])
            except ValueError:
                raise ModelError(f"{path}:{ln}: bad orthogroup_support {f[2]!r}") from None
            og = by.get(og_id)
            if og is None:
                og = by[og_id] = OG(og_id, name, [], sup, f[3], f[4])
            og.genes.append(Member(f[0], species_of(f[0]), f[3], f[4]))
    return sorted(by.values(), key=lambda o: (-len(o.genes), int(o.id.rsplit(".", 1)[1])))


def hg_sort_key(hg: str) -> tuple:
    """Family, then the HG number as a number (HG2 before HG10)."""
    fam, _, last = hg.rpartition(".")
    m = re.fullmatch(r"HG(\d+)", last)
    return (fam, int(m.group(1)) if m else -1, last)


def group_ogs(cfg: core.Config, hgs, source: str) -> tuple[list[HGOgs], int]:
    """(one HGOgs per HG with output, sorted by HG id; number of HGs without output).
    Lists <outdir>/<source>/ once (NFS); an unreadable file becomes that HG's error."""
    names = core.report_status.nonempty_files(str(cfg.outdir / source))
    rows: list[HGOgs] = []
    missing = 0
    for hg in sorted(hgs, key=hg_sort_key):
        try:
            ogs = read_ogs(cfg, hg, source, names)
        except ModelError as e:
            rows.append(HGOgs(hg, [], str(e)))
            continue
        if ogs is None:
            missing += 1
        else:
            rows.append(HGOgs(hg, ogs))
    return rows, missing


def default_source(cfg: core.Config) -> str:
    """possvm/ (post-GeneRax) when it exists, else possvm_prev/ (raw IQ-TREE)."""
    return "possvm" if (cfg.outdir / "possvm").is_dir() else "possvm_prev"


_NEWICK_TIP = re.compile(r"[(,]\s*([^\s():,;\[\]]+)")    # a name right after '(' or ',' = a tip


def species_universe(cfg: core.Config) -> list[str]:
    """Tip names of params.SPECIES_TREE in newick order (names after ')' are clades: skipped).
    Only the names are read: no tree parsing, no ete3."""
    text = Path(cfg.params["SPECIES_TREE"]).read_text()
    return list(dict.fromkeys(_NEWICK_TIP.findall(text)))


def species_info_path(cfg: core.Config) -> Path:
    """params.species_info if set (relative = to the repo root), else species_info.tsv next to
    the species tree (data/species_info.tsv)."""
    p = cfg.params.get("species_info")
    if p:
        return Path(p) if Path(p).is_absolute() else core.ROOT / p
    return Path(cfg.params.get("SPECIES_TREE", "")).parent / "species_info.tsv"


def phyla(cfg: core.Config) -> dict[str, str]:
    """species code -> phylum from species_info.tsv (code, Latin name, phylum; tab-separated).
    A row without a phylum (2 columns, or an empty 3rd) gives "unknown"."""
    out: dict[str, str] = {}
    with open(species_info_path(cfg), errors="replace") as fh:
        for line in fh:
            f = line.rstrip("\r\n").split("\t")
            code = f[0].strip()
            if not code or code.startswith("#"):
                continue
            out[code] = (f[2].strip() if len(f) > 2 else "") or "unknown"
    return out


def og_species_stats(og: OG, universe, phyla: dict) -> list[PhylumRow]:
    """Per phylum of the universe: species covered / total and member genes; phyla with
    members first (n_genes desc, then name), then the absent ones (by name)."""
    counts = collections.Counter(m.species for m in og.genes)
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for sp in universe:
        groups[phyla.get(sp) or "unknown"].append(sp)
    rows = []
    for ph, sps in groups.items():
        present = sorted(((sp, counts[sp]) for sp in sps if counts[sp]), key=lambda x: (-x[1], x[0]))
        rows.append(PhylumRow(ph, len(present), len(sps), sum(n for _, n in present), present))
    return (sorted((r for r in rows if r.covered), key=lambda r: (-r.n_genes, r.phylum))
            + sorted((r for r in rows if not r.covered), key=lambda r: r.phylum))


def og_outside(og: OG, universe) -> list[tuple[str, int]]:
    """Member species that are not tips of the species tree, with their gene counts."""
    u = set(universe)
    c = collections.Counter(m.species for m in og.genes if m.species not in u)
    return sorted(c.items(), key=lambda x: (-x[1], x[0]))
```

- [ ] **Step 4: Run both suites** — Expected: N0 + 11 passed on both (264 from 253), output clean.

- [ ] **Step 5: Commit** — `git add phylocli/model.py phylocli/tests/test_model.py`; message `phylocli: model.read_ogs/group_ogs (POSSVM ortholog groups, members) and per-phylum species stats` + trailer.

---

### Task 2: TUI Results window (`o`, four panes, `/`, `p`, `esc`)

**Files:**
- Modify: `phylocli/tui.py`, `phylocli/README.md` (`## phylo tui` section)
- Test: `phylocli/tests/test_tui.py` (append)

**Interfaces:**
- Consumes: from Task 1 `model.group_ogs`, `model.HGOgs`, `model.OG`, `model.Member`, `model.PhylumRow`, `model.hg_sort_key`, `model.default_source`, `model.species_universe`, `model.species_info_path`, `model.phyla`, `model.og_species_stats`, `model.og_outside`; existing `model.group_key`, `core.FAMILY_STAGES`; test helpers `OG_HEAD`, `write_results` from `test_model.py`.
- Produces (Task 3 and tests rely on these names):
  - `view ∈ {"overview", "hgs", "results"}`; widgets `#resv` (Vertical, gets class `loading`), `#results` (Horizontal), `#res`, `#ogs`, `#members` (DataTable, row cursor), `#rescol` (Vertical), `#memfilter` (Input, hidden until `/`), `#species_box` (ScrollableContainer) holding `#species` (Static, markup off), `#resfoot` (Static)
  - attributes `res_from`, `res_group`, `res_hgs: list[str]`, `res_source: str | None`, `res_rows: list[model.HGOgs]`, `res_missing: int`, `_res_gen: int`, `_res_note: str`, `_res_foot: str` (footer text as shown), `_species_text: str` (species pane text as shown), `_mem_filter: str`, `_universe: list | None`, `_phyla: dict | None`, `_sp_note: str`
  - module functions `species_lines(stats, outside) -> list[str]`, `_short_og(og_id) -> str`
  - actions `open_results` (`o`), `toggle_source` (`p`), `member_filter` (`/`); methods `_open_results(group, by, focus=None)`, `_reload_results()`, worker `_load_results(hgs, source, gen)` (`group="results"`), `_apply_results(snap)`, `_cur_res()`, `_cur_og()`, `_fill_ogs()`, `_show_og()`, `_fill_members()`, `_results_footer()`

Decisions this task implements (from the spec, where it leaves room):
- `o` on an HG in `2 HGs` opens Results for `model.group_key(hg, self.by)` (spec), with the HG highlighted. `o` on a **family** row (HG view at search/cluster, `r.hg` = a family id such as `tfs.A`) opens Results for that family's HGs (`group_key(h, "family") == fam`), none highlighted; a family with no expected HGs opens on "no ortholog groups yet".
- The HG list of a group comes from the last snapshot in memory (`self._ov_inputs[0]`, the expected HGs), so `o` itself touches no file. The source is decided in the worker (`model.default_source`). `p` before the first load has finished is ignored.
- The species universe and phyla are read by the worker on the first load and kept on the app (`_universe`, `_phyla`); a failed read is retried on the next load and its message (file + error) heads the species pane. Without a universe every member species is listed as "not in species tree"; without phyla every phylum is `unknown`.
- `/` shows and focuses the filter box; the filter is a case-insensitive substring over gene, species, ref, ref support; it updates on every keystroke; `enter` keeps it and returns to `members`; `esc` (while the box is shown) clears and hides it and returns to `members` — only the next `esc` leaves Results. The filter stays across OG moves and is reset when Results is opened.
- An HG whose file cannot be read stays listed with `–`, `–`, `!`; its error (file and line) shows in the species pane and the footer.
- Support display: `0.0 ⚠` for exactly 0, `–` for NA, otherwise one decimal (`-1.0` stays visible).
- Species pane text: per present phylum `"<phylum padded>  k/m spp  n gene(s)"` then `"  sp n · sp n"`; then `absent: A, B`; then `not in species tree: sp n, …`.

- [ ] **Step 1: Write the failing tests** (append to `phylocli/tests/test_tui.py`; add the import below next to the existing `from phylocli.tests.test_cli import ...` line):

```python
from phylocli.tests.test_model import OG_HEAD, write_results  # noqa: E402
```

```python
# ---- Results window ---------------------------------------------------------------------------
def _ov_row(app, group):
    return [r.group for r in app.ov_rows].index(group)


async def _press(pilot, *keys):
    for k in keys:
        await pilot.press(k)
        await pilot.pause()


async def _open_results(app, pilot, group, family=False):
    """Overview -> cursor on `group` -> o -> wait for the Results load."""
    app.load_now()
    await pilot.pause()
    if family:
        await _press(pilot, "f")
    app.query_one("#overview").move_cursor(row=_ov_row(app, group), column=2)
    await pilot.pause()
    await pilot.press("o")
    await app.workers.wait_for_complete()
    await pilot.pause()


def _cells(app, table, row):
    t = app.query_one(table)
    return [str(t.get_cell_at((row, c))) for c in range(len(t.columns))]


def _member_genes(app):
    t = app.query_one("#members")
    return [str(t.get_cell_at((i, 0))) for i in range(t.row_count)]


def test_o_on_overview_opens_results_for_that_group(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert app.view == "results" and app.focused is app.query_one("#res")
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]   # C_x: no output
            assert app.res_missing == 1 and "1 HG without output" in app._res_foot
            assert app.query_one("#res").border_title == "Results · tfs"
            assert _cells(app, "#res", 0) == ["tfs.A.HG1", "2", "5", "1"]
            assert app.query_one("#ogs").border_title == "OGs · tfs.A.HG1 · possvm"
            assert _cells(app, "#ogs", 0) == ["HG1.0", "T/Tbx19", "3", "2", "78.4", "T/Tbx19",
                                              "98.2/98.2"]
            assert _cells(app, "#ogs", 1)[4] == "0.0 ⚠"
            assert app.query_one("#members").border_title == "members · HG1.0 T/Tbx19"
            assert _cells(app, "#members", 2) == ["Hsap_ENSP1", "Hsap", "T/Tbx19", "98.2/98.2"]
            assert app.query_one("#species_box").border_title == "species · HG1.0"
            assert app._species_text.splitlines() == [
                "Ctenophora  1/2 spp  2 genes", "  Mlei 2",
                "Chordata    1/1 spp  1 gene", "  Hsap 1",
                "absent: unknown"]
            assert "2 OGs · possvm · ⚠ = support 0 (GeneRax bug case; check possvm_prev)" \
                in app._res_foot
    _run(go())


def test_o_on_hg_highlights_it_and_esc_returns_to_hg_view(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.open_group("tfs", "align")
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            vis = [r.hg for r in app.visible()]
            assert "tfs.A.HG11" in vis
            app.query_one("#hgs").move_cursor(row=vis.index("tfs.A.HG11"))
            await pilot.pause()
            await pilot.press("o")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and app.res_group == "tfs"
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG11"
            assert app.query_one("#ogs").border_title == "OGs · tfs.A.HG11 · possvm"
            assert _cells(app, "#ogs", 0)[:2] == ["HG11.0", "Tbx20"]
            await _press(pilot, "escape")
            assert app.view == "hgs" and app._cursor_hg() == "tfs.A.HG11"
            assert app.focused is app.query_one("#hgs")
    _run(go())


def test_o_on_family_row_opens_results_for_its_hgs(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.open_group("ALL", "search")                        # rows are families here
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            vis = [r.hg for r in app.visible()]
            assert "tfs.A" in vis                                  # no search output: ready
            app.query_one("#hgs").move_cursor(row=vis.index("tfs.A"))
            await pilot.pause()
            await pilot.press("o")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and app.res_group == "tfs.A"
            assert app.res_hgs == ["tfs.A.HG1", "tfs.A.HG11"]
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
            assert app.query_one("#res").border_title == "Results · tfs.A"
            await _press(pilot, "escape")
            assert app.view == "hgs" and app.stage == "search" and app._cursor_hg() == "tfs.A"
    _run(go())


def test_results_cursor_moves_update_panes_without_file_reads(cli, monkeypatch):
    write_results(_cfg())

    def boom(*a, **k):
        raise AssertionError("file read on a key press")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            for name in ("read_ogs", "group_ogs", "species_universe", "phyla"):
                monkeypatch.setattr(tui.model, name, boom)
            monkeypatch.setattr(core.report_status, "nonempty_files", boom)
            await _press(pilot, "down")                            # Results: tfs.A.HG11
            assert app.query_one("#ogs").border_title == "OGs · tfs.A.HG11 · possvm"
            assert _member_genes(app) == ["Bova_x1", "Mlei_v05_G9"]
            assert app._species_text.splitlines()[:2] == ["Ctenophora  2/2 spp  2 genes",
                                                          "  Bova 1 · Mlei 1"]
            await _press(pilot, "up", "tab")                       # back to HG1, into OGs
            assert app.focused is app.query_one("#ogs")
            await _press(pilot, "down")                            # OG HG1.1: Hsap + Nvec
            assert app.query_one("#members").border_title == "members · HG1.1 like:Eomes/Tbr1"
            assert _member_genes(app) == ["Hsap_ENSP2", "Nvec_v1_g3"]
            assert app._species_text.splitlines() == [
                "Chordata  1/1 spp  1 gene", "  Hsap 1",
                "unknown   1/1 spp  1 gene", "  Nvec 1",
                "absent: Ctenophora"]
    _run(go())


def test_slash_filters_members_and_esc_clears(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert len(_member_genes(app)) == 3
            inp = app.query_one("#memfilter")
            assert not inp.display
            await _press(pilot, "slash")
            assert inp.display and app.focused is inp
            await _press(pilot, "h", "s", "a", "p")               # `p` is text here, not a switch
            assert app.res_source == "possvm" and inp.value == "hsap"
            assert _member_genes(app) == ["Hsap_ENSP1"]
            await _press(pilot, "escape")                          # clears; stays in Results
            assert app.view == "results" and not inp.display and inp.value == ""
            assert len(_member_genes(app)) == 3 and app.focused is app.query_one("#members")
            await _press(pilot, "slash", "M", "L", "E", "I", "enter")   # case-insensitive; enter keeps
            assert app.focused is app.query_one("#members")
            assert _member_genes(app) == ["Mlei_v05_G1", "Mlei_v05_G2"]
            await _press(pilot, "escape", "escape")
            assert app.view == "overview"
    _run(go())


def test_p_switches_source_and_recomputes_results(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
            await pilot.press("p")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_source == "possvm_prev"
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1"] and app.res_missing == 2
            assert app.query_one("#ogs").border_title == "OGs · tfs.A.HG1 · possvm_prev"
            assert _cells(app, "#ogs", 0)[:2] == ["HG1.0", "like:Tbx2/Tbx3"]
            assert app._species_text.splitlines() == [
                "Ctenophora  1/2 spp  1 gene", "  Mlei 1",
                "absent: Chordata, unknown",
                "not in species tree: Zzz 1"]
            await pilot.press("p")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_source == "possvm" and len(app.res_rows) == 2
    _run(go())


def test_esc_from_results_returns_to_overview_cursor_kept(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _press(pilot, "f")
            ov = app.query_one("#overview")
            ov.move_cursor(row=_ov_row(app, "tfs.C_x"), column=3)
            await pilot.pause()
            await pilot.press("o")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and app.res_group == "tfs.C_x"
            await _press(pilot, "escape")
            assert app.view == "overview" and app.focused is ov
            assert (ov.cursor_row, ov.cursor_column) == (_ov_row(app, "tfs.C_x"), 3)
    _run(go())


def test_results_without_output_says_so_and_p_still_works(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs.C_x", family=True)
            assert app.res_rows == []
            assert "no ortholog groups yet (possvm not done)" in app._res_foot
            assert app._species_text == "no ortholog groups yet (possvm not done)"
            await pilot.press("p")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_source == "possvm_prev"
            assert "no ortholog groups yet (possvm_prev not done)" in app._res_foot
    _run(go())


def test_results_read_in_worker_shows_loading(cli, monkeypatch):
    import threading
    write_results(_cfg())
    gate = threading.Event()
    on_main = []
    real = tui.model.read_ogs

    def slow(*a, **k):
        on_main.append(threading.current_thread() is threading.main_thread())
        gate.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(tui.model, "read_ogs", slow)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("o")                                 # cursor on ALL
            await pilot.pause()
            assert app.view == "results" and app.res_group == "ALL"
            assert app.query_one("#resv").has_class("loading")
            assert "loading…" in app._res_foot and app.res_rows == []
            app.load_bg()                                          # a periodic refresh meanwhile
            await pilot.pause()
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not app.query_one("#resv").has_class("loading")
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
    _run(go())
    assert on_main and not any(on_main)


def test_results_bad_row_is_shown_not_a_crash(cli):
    write_results(_cfg())
    p = _cfg().outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv"
    p.write_text(OG_HEAD + "broken row\n")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
            assert _cells(app, "#res", 1) == ["tfs.A.HG11", "–", "–", "!"]
            await _press(pilot, "down")
            assert f"{p}:2:" in app._species_text and f"{p}:2:" in app._res_foot
            assert app.query_one("#ogs").row_count == 0 and _member_genes(app) == []
    _run(go())


def test_results_without_species_files_still_lists_ogs(cli):
    from pathlib import Path
    write_results(_cfg())
    tree = Path(_cfg().params["SPECIES_TREE"])
    info = tui.model.species_info_path(_cfg())
    tree.unlink()
    info.unlink()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert _cells(app, "#ogs", 0)[:2] == ["HG1.0", "T/Tbx19"]
            assert len(_member_genes(app)) == 3
            lines = app._species_text.splitlines()
            assert lines[0].startswith(f"species tree {tree}: ")
            assert f"{info}: " in lines[0] and "phyla shown as unknown" in lines[0]
            assert lines[-1] == "not in species tree: Mlei 2, Hsap 1"
    _run(go())


def test_results_tab_cycles_four_panes_with_orange_border(cli):
    from textual.color import Color
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            panes = ("#res", "#ogs", "#members", "#species_box")
            for pane in panes:
                assert app.focused is app.query_one(pane)
                for other in panes:
                    colour = app.query_one(other).styles.border.top[1]
                    assert (colour == Color.parse("orange")) == (other == pane), (pane, other)
                await _press(pilot, "tab")
            assert app.focused is app.query_one("#res")             # wraps around
            await _press(pilot, "shift+tab")
            assert app.focused is app.query_one("#species_box")
    _run(go())


def test_footer_keys_in_results(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert app.check_action("open_results", ())
            assert not app.check_action("toggle_source", ()) and not app.check_action("member_filter", ())
            await _open_results(app, pilot, "tfs")
            for a in ("toggle_source", "member_filter", "back"):
                assert app.check_action(a, ()), a
            for a in ("open_results", "resubmit", "toggle", "select_all", "log", "by_category",
                      "cycle_filter"):
                assert not app.check_action(a, ()), a
    _run(go())


def test_late_result_of_previous_group_is_dropped(cli, monkeypatch):
    import threading
    write_results(_cfg())
    gate = threading.Event()
    real = tui.model.group_ogs

    def slow(cfg, hgs, source):
        if list(hgs) == ["tfs.C_x.HG1"]:                         # the first open: family tfs.C_x
            gate.wait(10)
        return real(cfg, hgs, source)
    monkeypatch.setattr(tui.model, "group_ogs", slow)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _press(pilot, "f")
            ov = app.query_one("#overview")
            ov.move_cursor(row=_ov_row(app, "tfs.C_x"))
            await pilot.pause()
            await _press(pilot, "o", "escape")                     # first load blocked in the worker
            ov.move_cursor(row=_ov_row(app, "tfs.A"))
            await pilot.pause()
            await _press(pilot, "o")
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_group == "tfs.A"
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
    _run(go())
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider` — Expected: the 14 new tests FAIL (e.g. `NoMatches: No nodes match '#res'`, `AssertionError: assert 'overview' == 'results'`); the existing ones pass.

- [ ] **Step 3: Implement** in `phylocli/tui.py`.

2a. Imports — change the containers line (`Input` is already imported from `textual.widgets`):

```python
from textual.containers import Grid, Horizontal, ScrollableContainer, Vertical, VerticalScroll
```

2b. `PANE_TITLES` — replace with:

```python
PANE_TITLES = {"#overview": "Overview", "#stages": "1 Stages", "#hgs": "2 HGs",
               "#arrays": "3 Arrays", "#detail": "4 Detail",
               "#res": "Results", "#ogs": "OGs", "#members": "members", "#species_box": "species"}
```

2c. Module-level functions — add right after `def stage_at_column(...)`:

```python
def _short_og(og_id: str) -> str:
    """tfs.T-box.HG1.6 -> HG1.6"""
    return ".".join(og_id.rsplit(".", 2)[-2:])


def species_lines(stats: list, outside: list) -> list[str]:
    """The species pane: per phylum with members `k/m spp  n genes` and its species, then the
    absent phyla, then member species that are not tips of the species tree."""
    present = [r for r in stats if r.covered]
    absent = [r for r in stats if not r.covered]
    w = max((len(r.phylum) for r in present), default=0)
    out: list[str] = []
    for r in present:
        out.append(f"{r.phylum.ljust(w)}  {r.covered}/{r.total} spp  "
                   f"{r.n_genes} gene{'' if r.n_genes == 1 else 's'}")
        out.append("  " + " · ".join(f"{sp} {n}" for sp, n in r.species))
    if absent:
        out.append("absent: " + ", ".join(r.phylum for r in absent))
    if outside:
        out.append("not in species tree: " + ", ".join(f"{sp} {n}" for sp, n in outside))
    return out
```

2d. `PhyloApp.CSS` — append these lines inside the string, after `#hgview.loading { opacity: 40%; }`:

```
    #resv { height: 1fr; }
    #results { height: 1fr; }
    #res { width: 1fr; }
    #ogs, #rescol { width: 2fr; }
    #res, #ogs, #rescol { height: 100%; }
    #members, #species_box { height: 1fr; }
    #results DataTable, #species_box { border: round $primary; }
    #results DataTable:focus, #species_box:focus { border: round orange; }
    #memfilter { height: 3; }
    #resv.loading { opacity: 40%; }
    #species { width: auto; }
    #resfoot { height: auto; }
```

2e. `BINDINGS` — insert after `Binding("l", "log", "log"),`:

```python
        Binding("o", "open_results", "results"),
        Binding("p", "toggle_source", "possvm/prev"),
        Binding("slash", "member_filter", "filter members"),
```

2f. `__init__` — append after `self._banner_text = ""`:

```python
        self.res_from = "overview"              # the view esc returns to from Results
        self.res_group = ""
        self.res_hgs: list[str] = []
        self.res_source: "str | None" = None    # None = model.default_source(), in the worker
        self.res_rows: list = []                # [model.HGOgs] of the open group
        self.res_missing = 0
        self._res_focus: "str | None" = None    # HG to put the Results cursor on after a load
        self._res_gen = 0                       # bumped per load / esc: late snapshots dropped
        self._res_note = ""
        self._res_foot = ""
        self._species_text = ""
        self._mem_filter = ""
        self._universe: "list | None" = None    # species tree tips, read once by the worker
        self._phyla: "dict | None" = None       # species -> phylum, read once by the worker
        self._sp_note = ""                      # why the universe / phyla could not be read
```

2g. `compose` — insert after the `with Grid(id="hgview"):` block, before `yield Footer()`:

```python
        with Vertical(id="resv"):
            with Horizontal(id="results"):
                yield DataTable(id="res", cursor_type="row")
                yield DataTable(id="ogs", cursor_type="row")
                with Vertical(id="rescol"):
                    yield Input(placeholder="filter members (enter: keep · esc: clear)",
                                id="memfilter")
                    yield DataTable(id="members", cursor_type="row")
                    with ScrollableContainer(id="species_box"):
                        yield Static("", id="species", markup=False)
            yield Static("", id="resfoot")
```

2h. `on_mount` — insert after the line `self._set_units(force=True)` (step1 builds the `#hgs` / `#arrays` columns there):

```python
        self.query_one("#res", DataTable).add_columns("HG", "OGs", "genes", "⚠")
        self.query_one("#ogs", DataTable).add_columns("OG", "name", "genes", "spp", "support",
                                                       "ref", "ref sup")
        self.query_one("#members", DataTable).add_columns("gene", "sp", "ref.orth", "sup")
        self.query_one("#memfilter").display = False
```

2i. `_show_view` — replace the whole method:

```python
    def _show_view(self) -> None:
        self.query_one("#ov").display = self.view == "overview"
        self.query_one("#hgview").display = self.view == "hgs"
        self.query_one("#resv").display = self.view == "results"
        self.query_one({"overview": "#overview", "hgs": "#hgs", "results": "#res"}[self.view]).focus()
```

2j. `_overview_footer` — its text is split over several string literals; replace the literal `"enter: open · c/f: category/family"` with `"enter: open · o: results · c/f: category/family"`.

2k. `check_action` — replace the whole method:

```python
    def check_action(self, action: str, parameters: tuple) -> "bool | None":
        """Footer shows only the keys of the current view."""
        if action in ("by_category",):
            return self.view == "overview"
        if action in ("toggle", "select_all", "resubmit", "log"):
            return self.view == "hgs"
        if action == "back":
            return self.view in ("hgs", "results")
        if action in ("open_results", "cycle_filter"):
            return self.view in ("overview", "hgs")
        if action in ("toggle_source", "member_filter"):
            return self.view == "results"
        return True
```

2l. `action_back` — replace the whole method:

```python
    def action_back(self) -> None:
        if self.view == "results":
            inp = self.query_one("#memfilter", Input)
            if inp.display:                      # esc with the filter box open: clear it first
                inp.value = ""
                inp.display = False
                self._mem_filter = ""
                self._fill_members()
                self.query_one("#members").focus()
                return
            self._res_gen += 1                   # a load still running is dropped when it lands
            self.view = self.res_from
            self._show_view()
        elif self.view == "hgs":
            self.view = "overview"
            self._show_view()
```

2m. `on_data_table_row_highlighted` — after the `elif t.id == "hgs":` branch (`self._show_detail()`), add:

```python
        elif t.id == "res":
            self._fill_ogs()
        elif t.id == "ogs":
            self._show_og()
```

2n. `action_cycle_filter` — insert at the top of its body:

```python
        if self.view == "results":           # f has no meaning in Results (check_action hides it)
            return
```

2o. New methods — add after `action_log` (still inside `PhyloApp`, before `def resource_groups`):

```python
    # ---- Results window ---------------------------------------------------------------------
    def action_open_results(self) -> None:
        if self.view == "overview":
            group = self._key_at_cursor(self.query_one("#overview", DataTable))
            if group is not None:
                self._open_results(group, self.by)
        elif self.view == "hgs":
            hg = self._cursor_hg()
            if hg is None:
                self.notify("nothing under the cursor", severity="warning")
                return
            if self.stage in core.FAMILY_STAGES:   # a family row (search / cluster): its HGs
                self._open_results(hg, "family")
            else:
                self._open_results(model.group_key(hg, self.by), self.by, focus=hg)

    def _open_results(self, group: str, by: str, focus: "str | None" = None) -> None:
        """Results window for a group of HGs: `group` under grouping `by` (ALL = every HG; a
        family id under "family" = that family's HGs).  The HG list comes from the last
        snapshot in memory (_ov_inputs[0] = expected HGs); the files are read by _load_results."""
        exp = self._ov_inputs[0]
        self.res_hgs = sorted((h for h in exp if group == "ALL" or model.group_key(h, by) == group),
                              key=model.hg_sort_key)
        self.res_from, self.res_group, self._res_focus = self.view, group, focus
        self.res_source, self.res_rows, self.res_missing = None, [], 0
        self._mem_filter = ""
        inp = self.query_one("#memfilter", Input)
        inp.value = ""
        inp.display = False
        self.query_one("#res", DataTable).clear()
        self.query_one("#res").border_title = f"Results · {group}"
        self.view = "results"
        self._show_view()
        self._reload_results()

    def _reload_results(self) -> None:
        """Grey the window and start a load; the #res rows stay (greyed) so the cursor's HG is
        kept across `p`, while the other panes empty until the new source is read."""
        self._res_gen += 1
        self.res_rows = []
        self.query_one("#resv").add_class("loading")
        self._res_note = "loading…"
        self._fill_ogs()
        self._load_results(list(self.res_hgs), self.res_source, self._res_gen)

    @work(thread=True, exclusive=True, group="results")
    def _load_results(self, hgs: list, source: "str | None", gen: int) -> None:
        """Reads the ortholog_groups.csv files (NFS) and, until they have been read once, the
        species tree tips and species_info.tsv: never on the UI thread.  Own worker group:
        load_bg (default group, exclusive) must not cancel it, nor it load_bg."""
        worker = get_current_worker()
        snap = dict(gen=gen, source=source or "possvm", rows=[], missing=0, note="",
                    universe=self._universe, phyla=self._phyla, sp_note="")
        try:
            snap["source"] = source or model.default_source(self.cfg)
            snap["rows"], snap["missing"] = model.group_ogs(self.cfg, hgs, snap["source"])
        except Exception as e:                   # never let a worker kill the app
            snap["note"] = f"cannot read {snap['source']}/: {e}"
        notes = []
        if snap["universe"] is None:
            try:
                snap["universe"] = model.species_universe(self.cfg)
            except Exception as e:
                notes.append(f"species tree {self.cfg.params.get('SPECIES_TREE', '')}: {e}")
        if snap["phyla"] is None:
            try:
                snap["phyla"] = model.phyla(self.cfg)
            except Exception as e:
                notes.append(f"{model.species_info_path(self.cfg)}: {e} (phyla shown as unknown)")
        snap["sp_note"] = "; ".join(notes)
        if worker.is_cancelled:
            return
        self.call_from_thread(self._apply_results, snap)

    def _apply_results(self, snap: dict) -> None:
        if snap["gen"] != self._res_gen:         # superseded: esc, another o, or p meanwhile
            return
        self.query_one("#resv").remove_class("loading")
        self.res_source, self.res_rows, self.res_missing = snap["source"], snap["rows"], snap["missing"]
        self._universe, self._phyla, self._sp_note = snap["universe"], snap["phyla"], snap["sp_note"]
        self._res_note = snap["note"] or ("" if self.res_rows else
                                          f"no ortholog groups yet ({self.res_source} not done)")
        t = self.query_one("#res", DataTable)
        keep = self._res_focus or self._key_at_cursor(t)
        self._res_focus = None
        t.clear()
        for r in self.res_rows:
            if r.error:
                t.add_row(r.hg, "–", "–", "!", key=r.hg)
            else:
                t.add_row(r.hg, str(len(r.ogs)), str(sum(len(o.genes) for o in r.ogs)),
                          str(sum(1 for o in r.ogs if o.support == 0)), key=r.hg)
        keys = [r.hg for r in self.res_rows]
        if keys:
            t.move_cursor(row=keys.index(keep) if keep in keys else 0)
        self._fill_ogs()

    def _cur_res(self):
        key = self._key_at_cursor(self.query_one("#res", DataTable))
        return next((r for r in self.res_rows if r.hg == key), None)

    def _cur_og(self):
        r = self._cur_res()
        if r is None:
            return None
        key = self._key_at_cursor(self.query_one("#ogs", DataTable))
        return next((o for o in r.ogs if o.id == key), None)

    def _fill_ogs(self) -> None:
        """OG table of the HG under the Results cursor (in memory), then its members/species."""
        r = self._cur_res()
        t = self.query_one("#ogs", DataTable)
        t.clear()
        t.border_title = f"OGs · {r.hg if r else '–'} · {self.res_source or '…'}"
        for og in (r.ogs if r else []):
            sup = ("–" if og.support is None else "0.0 ⚠" if og.support == 0
                   else f"{og.support:.1f}")
            t.add_row(_short_og(og.id), escape(og.name), str(len(og.genes)),
                      str(len({m.species for m in og.genes})), sup, escape(og.ref),
                      escape(og.ref_support), key=og.id)
        if t.row_count:
            t.move_cursor(row=0)
        self._show_og()

    def _show_og(self) -> None:
        """members + species panes for the OG under the OGs cursor (in memory, no file access)."""
        r, og = self._cur_res(), self._cur_og()
        self.query_one("#members").border_title = (
            f"members · {_short_og(og.id)} {escape(og.name)}" if og else "members")
        self.query_one("#species_box").border_title = (
            f"species · {_short_og(og.id)}" if og else "species")
        self._fill_members()
        if r is not None and r.error:
            text = r.error
        elif og is None:
            text = self._res_note
        else:
            uni = self._universe or []
            lines = species_lines(model.og_species_stats(og, uni, self._phyla or {}),
                                  model.og_outside(og, uni))
            text = "\n".join(([self._sp_note, ""] if self._sp_note else []) + lines)
        self._species_text = text
        self.query_one("#species", Static).update(text)
        self._results_footer()

    def _fill_members(self) -> None:
        """Annotation rows of the highlighted OG, filtered by the `/` box (case-insensitive
        substring on any column)."""
        og = self._cur_og()
        t = self.query_one("#members", DataTable)
        t.clear()
        q = self._mem_filter.lower()
        for i, m in enumerate(og.genes if og else []):
            cells = (m.gene, m.species, m.ref, m.ref_support)
            if q and not any(q in c.lower() for c in cells):
                continue
            t.add_row(*(escape(c) for c in cells), key=f"{i}:{m.gene}")

    def _results_footer(self) -> None:
        r = self._cur_res()
        head = r.error if r is not None and r.error else self._res_note
        parts = ([f"{len(r.ogs)} OGs"] if r is not None and not r.error else []) + [
            self.res_source or "…", "⚠ = support 0 (GeneRax bug case; check possvm_prev)"]
        if self.res_missing:
            parts.append(f"{self.res_missing} HG{'' if self.res_missing == 1 else 's'} without output")
        lines = ([head] if head else []) + [
            " · ".join(parts), "/: filter members · p: possvm ↔ possvm_prev · tab: pane · esc: back"]
        self._res_foot = "\n".join(lines)
        self.query_one("#resfoot", Static).update(escape(self._res_foot))

    def action_toggle_source(self) -> None:
        if self.view != "results" or self.res_source is None:   # first load still running
            return
        self.res_source = "possvm_prev" if self.res_source == "possvm" else "possvm"
        self._reload_results()

    def action_member_filter(self) -> None:
        if self.view != "results":
            return
        inp = self.query_one("#memfilter", Input)
        inp.display = True
        inp.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "memfilter":        # (the resubmit dialog's Inputs have other ids)
            self._mem_filter = event.value
            self._fill_members()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "memfilter":        # enter: keep the filter, back to the rows
            self.query_one("#members").focus()
```

2p. `phylocli/README.md`, section `## phylo tui` — after the paragraph that ends "…read only once an HG view is open.", insert:

```markdown
`o` opens the **Results** window for the overview row under the cursor (`ALL` included); in the
HG view, for the highlighted HG's category/family (that HG highlighted) or, on search/cluster,
for the highlighted family's HGs. Four panes, `tab` between them: **Results** (the group's HGs
that have POSSVM output: OGs, genes, OGs with support 0 `⚠`; the footer counts the HGs without
output), **OGs** (the ortholog groups of the highlighted HG, largest first: OG, name, genes,
species, orthogroup support, reference ortholog and its support), **members** (the highlighted
OG's rows of `*.ortholog_groups.csv`: gene, species, reference ortholog and support; `/` filters,
`enter` keeps the filter, `esc` clears it) and **species** (per phylum `k/m spp  n genes` with
the species and their counts, absent phyla last; the universe is the tips of
`params.SPECIES_TREE`, phyla from `data/species_info.tsv`). `p` switches `possvm/` (post-GeneRax,
default) ↔ `possvm_prev/` (raw IQ-TREE); `esc` goes back. Support `0.0 ⚠` is the GeneRax bug
case: check `possvm_prev`. Files are read in the background.
```

and in the HG-view keys line replace `` `l` last log · `` with `` `l` last log · `o` results · ``.

- [ ] **Step 4: Run both suites** — Expected: N0 + 14 passed on both (278 from 253), output clean.

- [ ] **Step 5: Commit** — `git add phylocli/tui.py phylocli/tests/test_tui.py phylocli/README.md`; message `phylocli tui: Results window (o): HGs / OGs / members (/ filter) / species per phylum, p possvm <-> possvm_prev, reads in a worker` + trailer.

---

### Task 3: Overview `s` sort and `h` hide

**Files:**
- Modify: `phylocli/tui.py`, `phylocli/README.md`
- Test: `phylocli/tests/test_tui.py` (append)

**Interfaces:**
- Consumes: `model.GroupRow` (`group`, `total`, `per_stage[stage] = (done, running, ready, blocked)` or None; `ready` includes failed HGs whose inputs exist — the overview's `▓ ready/failed`; for `search`/`cluster` the four counts are **families**, `n_fams` the group's family total), step1's `stage_at_column(col) -> str | None` and `ov_column(stage) -> int` (module level in `tui.py`), `PhyloApp._fill_overview`, `_key_at_cursor`, `check_action` (Task 2 version).
- Produces:
  - module function `ov_order(rows: list, sort: tuple | None, hide: str | None) -> list` — `ALL` first; `hide` = stage name; `sort` = `(column name, reversed: bool)`
  - `PhyloApp.ov_sort: tuple | None`, `ov_hide: str | None`, `ov_shown: list[model.GroupRow]` (displayed rows); `ov_rows` unchanged (all rows as computed)
  - `_ov_column() -> str | None` (`"group"`, `"HGs"`, a stage name, or None on `│`); `_ov_title() -> str`; actions `sort` (`s`), `hide` (`h`)

Semantics (spec Part B): on a stage column `s` orders by ready/failed count descending, ties by running count descending, then by name; `n/a` rows last; `s` again reverses the whole order (ties stay by name). On `search`/`cluster` those counts are families, so `h` there hides rows with no actionable family (a group with HGs but no families is `n/a`/zero there and hidden). `group`: by name; `HGs`: by HG count (`total`) descending — the `HGs` column shows `total`, not `n_fams`. `s` on another column starts that column fresh. `h` on a stage column shows only rows with running + ready/failed > 0 there; `h` on the same stage again shows all; on another stage it switches; on `group`/`HGs`/`│` it warns and does nothing; `s` on `│` does nothing. Title: `Overview · sort: tree ▼ · only actionable at tree` (`▲` when reversed).

- [ ] **Step 1: Write the failing tests** (append to `phylocli/tests/test_tui.py`):

```python
# ---- overview sort / hide ---------------------------------------------------------------------
def _sorted_fixture():
    """tfs.C_x.HG1 gets its alignment: at `tree` tfs.C_x has 1 ready, tfs.A 0 (1 done,
    1 blocked); at `align` tfs.A has 1 ready, tfs.C_x is all done."""
    (_cfg().outdir / "align/tfs.C_x.HG1.aln.fasta").write_text(">s\nAA\n")


def _shown(app):
    return [r.group for r in app.ov_shown]


def _pair(app):
    """Order of the two fixture families among the shown rows (robust to extra groups)."""
    return [g for g in _shown(app) if g in ("tfs.A", "tfs.C_x")]


def _col(app, name):
    """Overview column of `name`: group 0, HGs 1, a stage through step1's ov_column."""
    return {"group": 0, "HGs": 1}.get(name) if name in ("group", "HGs") else tui.ov_column(name)


def _to_col(app, name, row=0):
    app.query_one("#overview").move_cursor(row=row, column=_col(app, name))


async def _family_overview(app, pilot):
    app.load_now()
    await pilot.pause()
    await pilot.press("f")
    await pilot.pause()


async def _key(pilot, *keys):
    for k in keys:
        await pilot.press(k)
        await pilot.pause()


def test_ov_order_ties_on_running_then_name_na_last():
    G = tui.model.GroupRow
    rows = [G("ALL", 9, {"tree": (0, 3, 3, 0)}),
            G("b", 3, {"tree": (0, 2, 1, 0)}), G("a", 3, {"tree": (0, 0, 1, 2)}),
            G("c", 2, {"tree": None}), G("d", 1, {"tree": (0, 2, 1, 0)})]

    def order(sort, hide=None):
        return [r.group for r in tui.ov_order(rows, sort, hide)]
    assert order(("tree", False)) == ["ALL", "b", "d", "a", "c"]
    assert order(("tree", True)) == ["ALL", "c", "a", "b", "d"]
    assert order(("HGs", False)) == ["ALL", "a", "b", "c", "d"]
    assert order(("HGs", True)) == ["ALL", "d", "c", "a", "b"]
    assert order(("group", True)) == ["ALL", "d", "c", "b", "a"]
    assert order(None, "tree") == ["ALL", "b", "a", "d"]
    assert order(None) == ["ALL", "b", "a", "c", "d"]


def test_s_sorts_by_stage_then_reverses(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            assert _pair(app) == ["tfs.A", "tfs.C_x"]
            _to_col(app, "tree")
            await _key(pilot, "s")
            assert _shown(app)[0] == "ALL" and _pair(app) == ["tfs.C_x", "tfs.A"]
            assert app.query_one("#overview").border_title == "Overview · sort: tree ▼"
            await _key(pilot, "s")
            assert _shown(app)[0] == "ALL" and _pair(app) == ["tfs.A", "tfs.C_x"]
            assert app.query_one("#overview").border_title == "Overview · sort: tree ▲"
    _run(go())


def test_s_on_group_and_hgs_columns(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            _to_col(app, "HGs")
            await _key(pilot, "s")
            assert _pair(app) == ["tfs.A", "tfs.C_x"]               # 2 HGs before 1
            await _key(pilot, "s")
            assert _pair(app) == ["tfs.C_x", "tfs.A"]
            _to_col(app, "group")
            await _key(pilot, "s")                                  # new column: fresh, by name
            assert _pair(app) == ["tfs.A", "tfs.C_x"]
            assert app.query_one("#overview").border_title == "Overview · sort: group ▼"
            await _key(pilot, "s")
            assert _pair(app) == ["tfs.C_x", "tfs.A"] and _shown(app)[0] == "ALL"
    _run(go())


def test_h_hides_rows_with_nothing_to_do_and_keeps_all(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            _to_col(app, "tree")
            await _key(pilot, "h")
            assert _shown(app)[0] == "ALL" and _pair(app) == ["tfs.C_x"]
            assert app.query_one("#overview").border_title == "Overview · only actionable at tree"
            assert "tfs.A" in [r.group for r in app.ov_rows]        # ov_rows untouched
            _to_col(app, "align")
            await _key(pilot, "h")                                  # another stage: switch
            assert _pair(app) == ["tfs.A"]
            await _key(pilot, "h")                                  # same stage: show all
            assert _pair(app) == ["tfs.A", "tfs.C_x"]
            assert app.query_one("#overview").border_title == "Overview"
            _to_col(app, "HGs")
            await _key(pilot, "h")                                  # not a stage column
            assert app.ov_hide is None and _pair(app) == ["tfs.A", "tfs.C_x"]
    _run(go())


def test_sort_and_hide_survive_refresh_and_regroup(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            _to_col(app, "tree")
            await _key(pilot, "s", "h")
            assert _pair(app) == ["tfs.C_x"]
            app.load_now()
            await pilot.pause()
            assert _pair(app) == ["tfs.C_x"]
            assert (app.ov_sort, app.ov_hide) == (("tree", False), "tree")
            await _key(pilot, "c")
            assert app.by == "category" and _shown(app)[0] == "ALL" and "tfs" in _shown(app)
            await _key(pilot, "f")
            assert _pair(app) == ["tfs.C_x"]
            assert app.query_one("#overview").border_title == \
                "Overview · sort: tree ▼ · only actionable at tree"
    _run(go())


def test_s_and_h_touch_no_files_or_slurm(cli, monkeypatch):
    _sorted_fixture()

    def boom(*a, **k):
        raise AssertionError("file or SLURM access on s/h")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            await app.workers.wait_for_complete()
            monkeypatch.setattr(core, "ready_set", boom)
            monkeypatch.setattr(core.report_status, "done_by_stage", boom)
            monkeypatch.setattr(tui.model, "_slurm", boom)
            assert app.check_action("sort", ()) and app.check_action("hide", ())
            _to_col(app, "tree")
            await _key(pilot, "s", "h")
            assert _pair(app) == ["tfs.C_x"]
            app.open_group("ALL")
            await pilot.pause()
            assert not app.check_action("sort", ()) and not app.check_action("hide", ())
    _run(go())


def test_enter_on_sorted_overview_opens_row_under_cursor(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            _to_col(app, "tree")
            await _key(pilot, "s")
            ov = app.query_one("#overview")
            row = _shown(app).index("tfs.C_x")
            _to_col(app, "tree", row=row)
            await pilot.pause()
            await _key(pilot, "enter")
            assert app.view == "hgs" and app.group == "tfs.C_x" and app.stage == "tree"
            await _key(pilot, "escape")
            assert app.view == "overview" and _shown(app)[ov.cursor_row] == "tfs.C_x"
            _to_col(app, "tree", row=_shown(app).index("tfs.A"))   # hide the row under the cursor
            await _key(pilot, "h")
            assert "tfs.A" not in _shown(app)
            assert app._key_at_cursor(ov) in _shown(app)
    _run(go())


def test_s_h_on_family_stage_count_families_and_skip_separator(cli):
    """search counts FAMILIES: tfs.A's family is searched (done), tfs.C_x's is not (ready)."""
    (_cfg().outdir / "search").mkdir(exist_ok=True)
    (_cfg().outdir / "search/tfs.A.domains.fasta").write_text(">x\nAA\n")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            rows = {r.group: r for r in app.ov_rows}
            assert rows["tfs.A"].per_stage["search"] == (1, 0, 0, 0)
            assert rows["tfs.C_x"].per_stage["search"] == (0, 0, 1, 0)
            _to_col(app, "search")
            await _key(pilot, "s")
            assert _pair(app) == ["tfs.C_x", "tfs.A"]
            assert app.query_one("#overview").border_title == "Overview · sort: search ▼"
            await _key(pilot, "h")
            assert _shown(app)[0] == "ALL" and _pair(app) == ["tfs.C_x"]
            sep = tui.ov_column("align") - 1                        # the │ column
            assert tui.stage_at_column(sep) is None
            app.query_one("#overview").move_cursor(row=0, column=sep)
            await pilot.pause()
            await _key(pilot, "s", "h")                             # no-ops on the separator
            assert (app.ov_sort, app.ov_hide) == (("search", False), "search")
            assert _pair(app) == ["tfs.C_x"]
    _run(go())
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider` — Expected: the 8 new tests FAIL (`AttributeError: module 'phylocli.tui' has no attribute 'ov_order'`, `AttributeError: 'PhyloApp' object has no attribute 'ov_shown'`); the rest pass.

- [ ] **Step 3: Implement** in `phylocli/tui.py`.

3a. Module-level functions — add after `STATE_STYLE = {...}`, before `class PhyloApp`:

```python
def _todo_at(r, stage: str) -> tuple:
    """(ready incl. failed, running) of an overview row at a stage; (-1, -1) when n/a."""
    c = r.per_stage.get(stage)
    return (c[2], c[1]) if c else (-1, -1)


def ov_order(rows: list, sort: "tuple | None", hide: "str | None") -> list:
    """Overview rows as shown: ALL pinned first; `hide` (a stage name) drops rows with nothing
    to do there (ready/failed + running = 0, or n/a); `sort` = (column name, reversed).
    Column names, not indices, so columns added later sort and hide the same way."""
    head = [r for r in rows if r.group == "ALL"]
    rest = [r for r in rows if r.group != "ALL"]
    if hide is not None:
        rest = [r for r in rest if sum(_todo_at(r, hide)) > 0]
    if sort is not None:
        col, rev = sort
        rest.sort(key=lambda r: r.group, reverse=(col == "group" and rev))
        if col == "HGs":
            rest.sort(key=lambda r: r.total, reverse=not rev)
        elif col != "group":
            rest.sort(key=lambda r: _todo_at(r, col), reverse=not rev)
    return head + rest
```

(Python's sort is stable, also with `reverse=True`, so ties keep the name order in both directions.)

3b. `BINDINGS` — insert after `Binding("f", "cycle_filter", "filter / family"),`:

```python
        Binding("s", "sort", "sort"),
        Binding("h", "hide", "only actionable"),
```

3c. `__init__` — append after the line `self._array_rows: list = []`:

```python
        self.ov_sort: "tuple | None" = None     # (column name, reversed); s
        self.ov_hide: "str | None" = None       # stage name; h
        self.ov_shown: list = []                # ov_rows as displayed (sorted / filtered)
```

3d. `_fill_overview` — targeted edits only; **do not replace the method and do not touch its columns**. Step1 owns the column list (`OV_COLUMNS`, the `│` separator, the two-row `Text` headers, the restore-off-the-separator step); column→stage goes through `stage_at_column`. (At `411134d` a whole-method replacement was tried and broke `enter`.) Four Edit calls, each old → new:

1. `        self.ov_rows = rows\n` →
```python
        self.ov_rows = rows                      # as computed; ov_shown is what the table shows
        self.ov_shown = ov_order(rows, self.ov_sort, self.ov_hide)
```
2. `        for r in rows:\n            cells = []\n` → `        for r in self.ov_shown:\n            cells = []\n`
3. `        keys = [r.group for r in rows]\n` → `        keys = [r.group for r in self.ov_shown]\n`
4. after the line `        t.move_cursor(row=keys.index(keep) if keep in keys else 0, column=col)` insert `        t.border_title = self._ov_title()`.

Then add these two methods right after `_fill_overview`:

```python
    def _ov_title(self) -> str:
        parts = ["Overview"]
        if self.ov_sort is not None:
            parts.append(f"sort: {self.ov_sort[0]} {'▲' if self.ov_sort[1] else '▼'}")
        if self.ov_hide is not None:
            parts.append(f"only actionable at {self.ov_hide}")
        return " · ".join(parts)

    def _ov_column(self) -> "str | None":
        """What the highlighted overview column sorts by: "group", "HGs", a stage name, or None
        on the │ separator. Stage columns go through stage_at_column (step1's one mapping)."""
        t = self.query_one("#overview", DataTable)
        if not t.columns:
            return None
        col = t.cursor_column
        return ("group", "HGs")[col] if col < 2 else stage_at_column(col)
```

3e. `_overview_footer` — replace the literal `"enter: open · o: results · c/f: category/family"` (Task 2) with `"enter: open · o: results · c/f: category/family · s: sort · h: only actionable"`.

3f. `check_action` — change its first test to:

```python
        if action in ("by_category", "sort", "hide"):
            return self.view == "overview"
```

3g. New actions — add after `action_by_category`:

```python
    def action_sort(self) -> None:
        col = self._ov_column() if self.view == "overview" else None
        if col is None:                          # no columns yet, or the │ separator
            return
        same = self.ov_sort is not None and self.ov_sort[0] == col
        self.ov_sort = (col, not self.ov_sort[1] if same else False)
        self._fill_overview(self.ov_rows)        # in memory only

    def action_hide(self) -> None:
        col = self._ov_column() if self.view == "overview" else None
        if col in (None, "group", "HGs"):        # not a stage column (incl. the │ separator)
            self.notify("h: move to a stage column first", severity="warning")
            return
        self.ov_hide = None if self.ov_hide == col else col
        self._fill_overview(self.ov_rows)        # in memory only
```

3h. `phylocli/README.md`, section `## phylo tui` — after the overview paragraph (the one ending "…read only once an HG view is open."), insert:

```markdown
`s` sorts the overview by the highlighted column — a stage: most ready/failed first, ties by
running (on search/cluster: families); `group`: by name; `HGs`: by size — and `s` again
reverses. `h` shows only the rows with something to do (ready, failed or running) at the
highlighted stage (on search/cluster: families); `h` again shows all.
`ALL` stays on top, the pane title shows the state, and both survive refreshes and `c`/`f`.
```

- [ ] **Step 4: Run both suites** — Expected: N0 + 8 passed on both (286 from 253), output clean.

- [ ] **Step 5: Commit** — `git add phylocli/tui.py phylocli/tests/test_tui.py phylocli/README.md`; message `phylocli tui: overview s (sort by the highlighted column) and h (only actionable at a stage)` + trailer.

---

## Self-review (done while writing)

- **Spec coverage.** Part A: entry/exit (`o` from the overview any column incl. ALL, from an HG with it highlighted, from a family row; `esc` back with cursor; `R` untouched) → Task 2 tests 1, 2, 3, 7; four panes + `tab`/`shift+tab` + orange → test 12; Results pane columns, sort by HG id, HGs without output counted → test 1 + Task 1 `hg_sort_key`; OG table columns, gene-count order, `0.0 ⚠` / `-1` / `NA` → Task 1 tests 1, 5 + Task 2 test 1; members rows and `/` filter → Task 2 tests 1, 4, 5; species per phylum (`k/m spp  n genes`, species with counts, absent last, outside the universe) → Task 1 test 11 + Task 2 tests 1, 4, 6; members/species follow the OG cursor → test 4; `p` and title → test 6; footer → test 1; data API (`read_ogs` with `Member`, `species_of`, `species_universe` by regex, `phyla` with `unknown`, `og_species_stats`, one file expected, `None` when missing) → Task 1; errors (no output + `p`, bad row with file and line, worker + loading, missing species files) → Task 2 tests 8, 10, 9, 11. Part B: `s` per column type and reversal, `h`, ALL pinned, title, survives refresh and `c`/`f`, in memory, search/cluster in families, `│` no-op → Task 3.
- **Placeholders.** None: every code step carries the code; README text given verbatim.
- **Type consistency.** `read_ogs(cfg, hg, source, names=None)`, `OG.genes: list[Member]`, `group_ogs(cfg, hgs, source) -> (list[HGOgs], int)`, `HGOgs.error: str`, `OG.support: float | None`, `og_species_stats(og, universe, phyla) -> list[PhylumRow]`, `og_outside(og, universe)`, `species_lines(stats, outside)`, `_open_results(group, by, focus=None)`, `ov_order(rows, sort, hide)`, `ov_sort = (name, reversed)`, `ov_hide = stage name` — the same names are used in every task and test.
- **Review Focus.** Each of the five lines has its test in the owning task (Task 1 ×3, Task 2 ×2, Task 3 ×1).
