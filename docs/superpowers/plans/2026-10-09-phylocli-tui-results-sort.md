# phylocli TUI Results window + overview sort/hide — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `o` opens a third TUI window, **Results** (panes `Results` / `OGs` / `species tree`), showing each HG's POSSVM ortholog groups with call, support and species coverage on the species tree; in the overview, `s` sorts and `h` hides rows by the highlighted column.

**Architecture:** `model.py` gains print-free readers for `ortholog_groups.csv` (`read_ogs`, `group_ogs`, one directory listing per load). A new pure module `phylocli/species_tree.py` parses the binary species tree (ete3, imported inside `load`) and draws it as text. `tui.py` adds a `results` view next to `overview` / `hgs`; all file reads run in a worker of its own group (`"results"`), so the existing `load_bg` refresh and this load never cancel each other. Sort/hide is a pure function `ov_order(rows, sort, hide)` over the in-memory `ov_rows`, keyed by column NAME.

**Tech Stack:** Python ≥ 3.9, Textual 8.2.8 (optional), ete3 3.1.3 (lazy), pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-phylocli-tui-og-explorer-sort-design.md` — Part A (Results window, amended 09/10/2026) and Part B (overview sort and filter).

**Repo / branch:** worktree `~/Documents/projects/phylogenies/phylocli-wt`, branch `phylocli`. Spec commit `1d76050` (195 tests). ⚠ The step1 plan (`docs/superpowers/plans/2026-10-08-phylocli-step1.md`) is being implemented in the same worktree while this plan was written. **Rebased 09/10/2026 onto HEAD `a0fb496` (253 tests)**, where `tui.py` has: `TUI_STAGES = core.STAGES` (search, cluster first); `OV_COLUMNS = [*FAMILY_STAGES, None, *HG_STAGES]` with a `│` separator column (`None`), `OV_TOP`, a two-row header with unkeyed `Text` labels; `ov_column(stage)` and `stage_at_column(col)` (the one column↔stage mapping; None for group, HGs and `│`); `_set_units` (the `#hgs`/`#arrays` columns are built there, not in `on_mount`); family rows in the HG view at search/cluster (`r.hg` is then a family id, `model.fam_group_key`); `_ov_inputs = (exp, states, fams, fstates)`; `GroupRow.n_fams`, and `per_stage` for search/cluster counts families. No key added since uses `o`, `p`, `s` or `h`. Locate code by function name, not line number; never revert step1's code; `git add` only the files a task lists. This whole plan was applied to a scratch copy of `a0fb496` and both suites passed (288 = 253 + 35, 09/10/2026).

## File Structure

| file | change | responsibility |
|---|---|---|
| `phylocli/model.py` | append | `OG`, `HGOgs`, `read_ogs`, `group_ogs`, `species_of`, `og_coverage`, `hg_sort_key`, `default_source` (no Textual, no ete3) |
| `phylocli/species_tree.py` | create | `load(path)` (ete3 imported inside), `render(tree, counts) -> list[str]` (pure) |
| `phylocli/tui.py` | modify | Results view (compose, CSS, bindings, worker, panes); overview `s`/`h` (`ov_order`, title) |
| `phylocli/README.md` | modify | `## phylo tui`: Results window, `o`/`p`, `s`/`h` |
| `phylocli/tests/test_model.py` | append | readers + shared fixture data (`OG_HEAD`, `write_results`) |
| `phylocli/tests/test_species_tree.py` | create | render/load |
| `phylocli/tests/test_tui.py` | append | Results window and overview sort/hide pilot tests |

## Global Constraints

- CLI output text and exit codes of every `phylo` command stay byte-identical. **No existing test is modified** (the spec changes no existing expectation). `test_panes_are_named_top_left` iterates `PANE_TITLES`, so the three new entries are covered by it unchanged.
- Python 3.9-safe (`from __future__ import annotations`; no `match`; no `X | Y` outside annotations; annotations in `tui.py` written as strings, as the file already does).
- Textual is imported only in `tui.py`. `species_tree.py` imports ete3 only inside `load()`; importing the module never imports ete3. `model.py` imports neither.
- No file or SLURM access on a key press (`o`, `p`, `s`, `h`, `esc`, `tab`, cursor moves). File reads go in workers: `load_bg` (existing) and `_load_results` (new, `group="results"`), following the `_collect` / `_apply` pattern (worker builds a snapshot dict, `call_from_thread` applies it, exceptions never escape the worker).
- Overview sort/hide is keyed by column **name**, never by column index: column 0 = `group`, 1 = `HGs`, every other column goes through step1's `stage_at_column(col)`; the `│` separator (None) does nothing. Sort/hide state stores the stage name, so it survives any later column change. Family stages (search, cluster) sort and hide on their `per_stage` family counts.
- `ov_rows` keeps its current meaning (the rows as computed by `model.group_rows`); the displayed order lives in a new `ov_shown`. Existing tests read `ov_rows`.
- Test commands (both must pass, output clean):
  `python3 -m pytest phylocli/tests -q -p no:cacheprovider` and
  `/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-phylogenies/3dad6ea4-c859-4fe6-b319-93a358944ac8/scratchpad/py39/bin/python -m pytest phylocli/tests -q -p no:cacheprovider`.
  Baseline 253 at `a0fb496`. Record **N0 = the passed count before you start each task**; each task states its delta (Task 1 +8, Task 2 +6, Task 3 +13, Task 4 +8; 288 total from 253 if nothing else lands).
- Commit on `phylocli`, message ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Edit with Edit/Write tools only, never sed or python string-replace.
- Dates in docs are `dd/mm/yyyy`.

## Review Focus

1. **Big groups** — `o` on `ALL` or on a 556-HG family (`tfs.zf-C2H2`) over NFS must list each source directory once per load, not once per HG → Task 1 `test_group_ogs_lists_hgs_with_output_one_listing`.
2. **The periodic refresh during a Results load** — `load_bg` is `exclusive=True` in the default worker group; if `_load_results` shared that group, a refresh would cancel it and Results would stay empty forever → Task 3 `test_results_read_in_worker_shows_loading` calls `load_bg()` mid-load.
3. **Real support values other than a plain positive number** — v3 POSSVM writes `-1` (measured 09/10/2026: 10,804 rows in the first 300 `possvm/` files, 2,780 in `possvm_prev/`; root-spanning groups); `NA` was not seen but is accepted. These must parse (no "unparseable row"), display as numbers / `–`, and never get `⚠`, which is for exactly 0 → Task 1 `test_read_ogs_negative_and_na_support`.
4. **ete3 missing in the TUI's env, or an unreadable species tree** — the OG table must still work and the tree pane must say why (`pip install ete3`, or the path and the error) → Task 3 `test_results_without_ete3_still_lists_ogs`.
5. **Sorted or filtered overview** — `enter`, `o` and `esc` act on the row under the cursor by key (not the pre-sort index), and hiding the row under the cursor lands the cursor on a shown row → Task 4 `test_enter_on_sorted_overview_opens_row_under_cursor`.

---

### Task 1: `model` — read POSSVM ortholog groups

**Files:**
- Modify: `phylocli/model.py` (append at the end)
- Test: `phylocli/tests/test_model.py` (append)

**Interfaces:**
- Consumes: `core.Config` (`cfg.outdir: Path`, `cfg.params: dict`), `core.report_status.nonempty_files(d: str) -> set[str]` (existing: names of non-empty files in a directory, empty set when the directory is missing), `ModelError(msg, code=1)`.
- Produces:
  - `OG_SUFFIX = ".ortholog_groups.csv"`, `OG_HEADER: list[str]`
  - `@dataclass OG: id: str` (`<hg>.<n>`, e.g. `tfs.T-box.HG1.0`); `name: str` (after the first `:`, e.g. `like:Tbx2/Tbx3`); `genes: list[str]`; `support: float | None` (`orthogroup_support`; None for `NA`/empty); `ref: str`; `ref_support: str`
  - `@dataclass HGOgs: hg: str; ogs: list[OG]; error: str = ""` (error = a `ModelError` message; then `ogs == []`)
  - `read_ogs(cfg, hg: str, source: str, names: set[str] | None = None) -> list[OG] | None` — sorted by gene count desc, then OG number; None when no non-empty file; `ModelError` for two files / bad header / bad row (message starts `<path>:<line>:`)
  - `group_ogs(cfg, hgs, source: str) -> tuple[list[HGOgs], int]` — rows for HGs with output (sorted by `hg_sort_key`), number without output; one directory listing
  - `species_of(gene: str) -> str`, `og_coverage(og: OG) -> dict[str, int]`, `hg_sort_key(hg: str) -> tuple`, `default_source(cfg) -> str` (`"possvm"` when `<outdir>/possvm/` is a directory, else `"possvm_prev"`)
  - Test helpers (module level in `test_model.py`, imported by `test_tui.py` in Task 3): `OG_HEAD`, `SP4`, `POSSVM_HG1`, `POSSVM_HG11`, `PREV_HG1`, `og_csv(rows) -> str`, `write_results(cfg) -> None`

- [ ] **Step 1: Write the failing tests** (append to `phylocli/tests/test_model.py`):

```python
# ---- ortholog groups (Results window) --------------------------------------------------------
from pathlib import Path  # noqa: E402

OG_HEAD = "gene\torthogroup\torthogroup_support\treference_ortholog\treference_support\n"
SP4 = "((Mlei:1,Bova:1)Cteno:1,(Hsap:1,Nvec:1)Para:1);\n"       # 4-tip species tree, root unnamed
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
    """POSSVM output for tfs.A.HG1 (possvm + possvm_prev) and tfs.A.HG11 (possvm only), and
    the 4-tip species tree.  tfs.C_x.HG1 keeps no output."""
    o = cfg.outdir
    (o / "possvm/tfs.A.HG1.generax.support.tree.ortholog_groups.csv").write_text(og_csv(POSSVM_HG1))
    (o / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv").write_text(og_csv(POSSVM_HG11))
    (o / "possvm_prev/tfs.A.HG1.treefile.ortholog_groups.csv").write_text(og_csv(PREV_HG1))
    Path(cfg.params["SPECIES_TREE"]).write_text(SP4)


def test_read_ogs_parses_and_sorts(cli):
    cfg = _cfg()
    write_results(cfg)
    ogs = model.read_ogs(cfg, "tfs.A.HG1", "possvm")
    assert [(o.id, o.name, len(o.genes), o.support, o.ref, o.ref_support) for o in ogs] == [
        ("tfs.A.HG1.0", "T/Tbx19", 3, 78.4, "T/Tbx19", "98.2/98.2"),
        ("tfs.A.HG1.1", "like:Eomes/Tbr1", 2, 0.0, "NA", "NA")]
    assert ogs[0].genes == ["Mlei_v05_G1", "Mlei_v05_G2", "Hsap_ENSP1"]
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


def test_species_of_and_coverage():
    assert model.species_of("Mlei_v05_G009201") == "Mlei"
    assert model.species_of("Mertsp_Mesp_sb563561") == "Mertsp"
    assert model.species_of("nounderscore") == "nounderscore"
    og = model.OG("x.HG1.0", "n", ["Mlei_a", "Mlei_b", "Hsap_c"], 1.0, "NA", "NA")
    assert model.og_coverage(og) == {"Mlei": 2, "Hsap": 1}


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
```

(The fixture, `conftest.results_tree`, already holds `possvm_prev/tfs.A.HG1.treefile.ortholog_groups.csv` = `"x\n"` and an **empty** `possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv`; `report_status` counts an empty file as "not done", so `read_ogs` does too.)

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_model.py -q -p no:cacheprovider` — Expected: FAIL, `AttributeError: module 'phylocli.model' has no attribute 'read_ogs'` (and `'OG'`, `'species_of'`, …).

- [ ] **Step 3: Implement** (append to `phylocli/model.py`; `re`, `collections`, `dataclass`, `Path`, `core` are already imported there):

```python
# ---- POSSVM ortholog groups (TUI Results window) ---------------------------------------------
OG_SUFFIX = ".ortholog_groups.csv"
OG_HEADER = ["gene", "orthogroup", "orthogroup_support", "reference_ortholog", "reference_support"]


@dataclass
class OG:
    id: str                    # <hg>.<n>, e.g. tfs.T-box.HG1.0
    name: str                  # after the first ':', e.g. like:Tbx2/Tbx3
    genes: list
    support: "float | None"    # orthogroup_support; None for NA / empty
    ref: str                   # reference_ortholog (as written, NA included)
    ref_support: str           # reference_support (as written)


@dataclass
class HGOgs:
    hg: str
    ogs: list                  # [OG]; [] when error is set
    error: str = ""


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
            og.genes.append(f[0])
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


def species_of(gene: str) -> str:
    """Species code = the gene id up to the first '_' (Mlei_v05_G1 -> Mlei)."""
    return gene.split("_", 1)[0]


def og_coverage(og: OG) -> dict[str, int]:
    """{species: number of member genes}."""
    return dict(collections.Counter(species_of(g) for g in og.genes))


def default_source(cfg: core.Config) -> str:
    """possvm/ (post-GeneRax) when it exists, else possvm_prev/ (raw IQ-TREE)."""
    return "possvm" if (cfg.outdir / "possvm").is_dir() else "possvm_prev"
```

- [ ] **Step 4: Run both suites** — Expected: N0 + 8 passed on both (261 from 253), output clean.

- [ ] **Step 5: Commit** — `git add phylocli/model.py phylocli/tests/test_model.py`; message `phylocli: model.read_ogs/group_ogs (POSSVM ortholog groups) and species_of/og_coverage` + trailer.

---

### Task 2: `phylocli/species_tree.py` — load and draw the species tree

**Files:**
- Create: `phylocli/species_tree.py`
- Test: `phylocli/tests/test_species_tree.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks (counts are `{species: n}` as `model.og_coverage` returns).
- Produces:
  - `load(path) -> ete3.Tree` — reads the file (FileNotFoundError when missing), parses with `format=1` so internal node names (clades) are kept; imports ete3 inside the function (ImportError when ete3 is absent).
  - `render(tree, counts: dict[str, int]) -> list[str]` — one line per node, `├─ ` / `└─ ` connectors, `│  ` / `   ` indents (3 chars per level); tips end in `●n` (n > 0) or `·`; named internal nodes end in `k/m spp` (k of the clade's m tips with ≥ 1 member); unnamed internal nodes are a bare `┐`; marks aligned in one column; species in `counts` (n > 0) but not tips are listed after a blank line as `not in species tree: A, B`.

Real-tree check done while writing this plan (09/10/2026, `data/species_tree.binary.newick`): parses with `format=1` in both venvs, 59 tips, depth 12, renders to 117 lines, 60 characters wide.

- [ ] **Step 1: Write the failing tests** (`phylocli/tests/test_species_tree.py`):

```python
"""phylocli/species_tree.py: the species tree for the TUI Results window (ete3, lazy)."""
import importlib
import sys

import pytest

from phylocli import species_tree

SP4 = "((Mlei:1,Bova:1)Cteno:1,(Hsap:1,Nvec:1)Para:1);\n"


@pytest.fixture
def tree(tmp_path):
    pytest.importorskip("ete3")
    p = tmp_path / "sp.newick"
    p.write_text(SP4)
    return species_tree.load(p)


def test_load_keeps_clade_names(tree):
    assert sorted(tree.get_leaf_names()) == ["Bova", "Hsap", "Mlei", "Nvec"]
    assert [c.name for c in tree.children] == ["Cteno", "Para"]


def test_render_tips_and_clades(tree):
    assert species_tree.render(tree, {"Mlei": 2, "Hsap": 1}) == [
        "┐",
        "├─ Cteno   1/2 spp",
        "│  ├─ Mlei ●2",
        "│  └─ Bova ·",
        "└─ Para    1/2 spp",
        "   ├─ Hsap ●1",
        "   └─ Nvec ·",
    ]


def test_render_lists_species_not_in_tree(tree):
    out = species_tree.render(tree, {"Zzz": 1, "Mlei": 1, "Aaa": 0})
    assert out[1] == "├─ Cteno   1/2 spp" and out[4] == "└─ Para    0/2 spp"
    assert out[-2:] == ["", "not in species tree: Zzz"]        # Aaa has 0 members: not listed


def test_render_unnamed_internal_node(tmp_path):
    pytest.importorskip("ete3")
    p = tmp_path / "t.newick"
    p.write_text("(((A:1,B:1):1,C:1)X:1,D:1);\n")
    assert species_tree.render(species_tree.load(p), {"A": 1}) == [
        "┐",
        "├─ X       1/3 spp",
        "│  ├─ ┐",
        "│  │  ├─ A ●1",
        "│  │  └─ B ·",
        "│  └─ C    ·",
        "└─ D       ·",
    ]


def test_load_missing_file(tmp_path):
    pytest.importorskip("ete3")
    with pytest.raises(FileNotFoundError):
        species_tree.load(tmp_path / "nope.newick")


def test_ete3_is_imported_only_by_load(tmp_path, monkeypatch):
    import phylocli
    monkeypatch.setitem(sys.modules, "ete3", None)          # any `import ete3` now fails
    monkeypatch.delitem(sys.modules, "phylocli.species_tree", raising=False)
    monkeypatch.delattr(phylocli, "species_tree", raising=False)
    mod = importlib.import_module("phylocli.species_tree")  # importing the module is fine
    (tmp_path / "t.newick").write_text(SP4)
    with pytest.raises(ImportError):
        mod.load(tmp_path / "t.newick")
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_species_tree.py -q -p no:cacheprovider` — Expected: FAIL at collection, `ImportError: cannot import name 'species_tree' from 'phylocli'`.

- [ ] **Step 3: Implement** (`phylocli/species_tree.py`):

```python
"""The species tree for the TUI Results window: parse (ete3, imported only inside load())
and draw as text lines with per-species member counts.  Pure functions, no Textual."""
from __future__ import annotations

from pathlib import Path


def load(path):
    """The species tree at `path` (newick) with internal node names kept (format=1)."""
    from ete3 import Tree                     # lazy: only the Results window needs ete3
    return Tree(Path(path).read_text().strip(), format=1)


def _walk(node, counts: dict, lead: str, conn: str, below: str, out: list) -> None:
    """Append (text, mark) for `node` and its subtree.  lead: the ancestors' indent; conn: this
    node's connector; below: what this node adds to its children's indent."""
    if node.is_leaf():
        n = counts.get(node.name, 0)
        out.append((lead + conn + node.name, f"●{n}" if n else "·"))
        return
    if node.name:
        leaves = node.get_leaf_names()
        k = sum(1 for x in leaves if counts.get(x, 0) > 0)
        out.append((lead + conn + node.name, f"{k}/{len(leaves)} spp"))
    else:
        out.append((lead + conn + "┐", ""))
    kids = node.children
    for i, c in enumerate(kids):
        last = i == len(kids) - 1
        _walk(c, counts, lead + below, "└─ " if last else "├─ ", "   " if last else "│  ", out)


def render(tree, counts: dict) -> list[str]:
    """One line per node: tips `●n` (n member genes) or `·`, named clades `k/m spp`, marks in
    one column; species with members that are not tips are listed under the tree."""
    rows: list = []
    _walk(tree, counts, "", "", "", rows)
    width = max((len(t) for t, m in rows if m), default=0)
    out = [f"{t.ljust(width)} {m}" if m else t for t, m in rows]
    tips = set(tree.get_leaf_names())
    extra = sorted(s for s, n in counts.items() if n and s not in tips)
    if extra:
        out += ["", "not in species tree: " + ", ".join(extra)]
    return out
```

- [ ] **Step 4: Run both suites** — Expected: N0 + 6 passed on both (267 from 253), output clean.

- [ ] **Step 5: Commit** — `git add phylocli/species_tree.py phylocli/tests/test_species_tree.py`; message `phylocli: species_tree.load/render (text species tree with member counts; ete3 lazy)` + trailer.

---

### Task 3: TUI Results window (`o`, three panes, `p`, `esc`)

**Files:**
- Modify: `phylocli/tui.py`, `phylocli/README.md` (`## phylo tui` section)
- Test: `phylocli/tests/test_tui.py` (append)

**Interfaces:**
- Consumes: `model.group_ogs`, `model.HGOgs`, `model.OG`, `model.og_coverage`, `model.hg_sort_key`, `model.default_source`, `model.group_key` (existing) from Task 1; `species_tree.load`, `species_tree.render` from Task 2; test helpers `OG_HEAD`, `write_results` from `test_model.py`.
- Produces (Task 4 and tests rely on these names):
  - `view ∈ {"overview", "hgs", "results"}`; widgets `#resv` (Vertical, gets class `loading`), `#results` (Horizontal), `#res` and `#ogs` (DataTable, row cursor), `#sptree_box` (ScrollableContainer) holding `#sptree` (Static, markup off), `#resfoot` (Static)
  - attributes `res_from: str`, `res_group: str`, `res_hgs: list[str]`, `res_source: str | None`, `res_rows: list[model.HGOgs]`, `res_missing: int`, `_res_gen: int`, `_res_note: str`, `_res_foot: str` (footer text as shown), `_tree_text: str` (tree pane text as shown)
  - actions `open_results` (`o`), `toggle_source` (`p`); methods `_open_results(group, by, focus=None)`, `_reload_results()`, worker `_load_results(hgs, source, gen)` (`group="results"`), `_apply_results(snap)`, `_cur_res()`, `_cur_og()`, `_fill_ogs()`, `_show_tree()`, `_results_footer()`

Decisions this task implements (from the spec, where it leaves room):
- `o` on an HG in `2 HGs` opens Results for `model.group_key(hg, self.by)` — the HG's own category/family under the current grouping (equal to the open group whenever one is open; from an `ALL` HG view it avoids reading every HG's file).
- `o` on a **family** row (HG view at search/cluster, where `r.hg` is a family id such as `tfs.A`) opens Results for that family's HGs (`group_key(h, "family") == fam`, the identity `model.fam_group_key` documents), no HG highlighted. A family with no expected HGs opens on "no ortholog groups yet".
- Keys checked against `a0fb496`: no binding uses `o` or `p` (the BINDINGS list is escape, c, f, space, a, r, l, R, q).
- The HG list of a group comes from the last snapshot in memory (`self._ov_inputs[0]`, the expected HGs), so `o` itself touches no file.
- The source is decided in the worker (`model.default_source`), so `o` does not even stat `possvm/`. `p` before the first load has finished is ignored.
- An HG whose file cannot be read stays listed with `–`, `–`, `!`; its error (file and line) shows in the tree pane and the footer.
- Support display: `0.0 ⚠` for exactly 0, `–` for NA, otherwise one decimal (`-1.0` stays visible).

- [ ] **Step 1: Write the failing tests** (append to `phylocli/tests/test_tui.py`; add the import below next to the existing `from phylocli.tests.test_cli import ...` line):

```python
from phylocli.tests.test_model import OG_HEAD, write_results  # noqa: E402
```

```python
# ---- Results window ---------------------------------------------------------------------------
def _ov_row(app, group):
    return [r.group for r in app.ov_rows].index(group)


async def _open_results(app, pilot, group, family=False):
    """Overview -> cursor on `group` -> o -> wait for the Results load."""
    app.load_now()
    await pilot.pause()
    if family:
        await pilot.press("f")
        await pilot.pause()
    app.query_one("#overview").move_cursor(row=_ov_row(app, group), column=2)
    await pilot.pause()
    await pilot.press("o")
    await app.workers.wait_for_complete()
    await pilot.pause()


def _cells(app, table, row):
    t = app.query_one(table)
    return [str(t.get_cell_at((row, c))) for c in range(len(t.columns))]


def test_o_on_overview_opens_results_for_that_group(cli):
    pytest.importorskip("ete3")
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
            assert "│  ├─ Mlei ●2" in app._tree_text.splitlines()
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
            await pilot.press("escape")
            await pilot.pause()
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
            await pilot.press("escape")
            await pilot.pause()
            assert app.view == "hgs" and app.stage == "search" and app._cursor_hg() == "tfs.A"
    _run(go())


def test_results_cursor_moves_redraw_without_file_reads(cli, monkeypatch):
    pytest.importorskip("ete3")
    write_results(_cfg())

    def boom(*a, **k):
        raise AssertionError("file read on a key press")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            monkeypatch.setattr(tui.model, "read_ogs", boom)
            monkeypatch.setattr(tui.model, "group_ogs", boom)
            monkeypatch.setattr(tui.species_tree, "load", boom)
            monkeypatch.setattr(core.report_status, "nonempty_files", boom)
            await pilot.press("down")                              # Results: tfs.A.HG11
            await pilot.pause()
            assert app.query_one("#ogs").border_title == "OGs · tfs.A.HG11 · possvm"
            assert "│  └─ Bova ●1" in app._tree_text.splitlines()
            await pilot.press("up")                                # back to tfs.A.HG1
            await pilot.pause()
            await pilot.press("tab")                               # into the OGs pane
            await pilot.pause()
            assert app.focused is app.query_one("#ogs")
            await pilot.press("down")                              # OG HG1.1: Hsap + Nvec
            await pilot.pause()
            lines = app._tree_text.splitlines()
            assert "└─ Para    2/2 spp" in lines and "│  ├─ Mlei ·" in lines
    _run(go())


def test_p_switches_source_and_recomputes_results(cli):
    pytest.importorskip("ete3")
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
            assert app._tree_text.splitlines()[-1] == "not in species tree: Zzz"
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
            await pilot.press("f")
            await pilot.pause()
            ov = app.query_one("#overview")
            ov.move_cursor(row=_ov_row(app, "tfs.C_x"), column=3)
            await pilot.pause()
            await pilot.press("o")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and app.res_group == "tfs.C_x"
            await pilot.press("escape")
            await pilot.pause()
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
            assert app._tree_text == "no ortholog groups yet (possvm not done)"
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
            await pilot.press("down")
            await pilot.pause()
            assert f"{p}:2:" in app._tree_text and f"{p}:2:" in app._res_foot
            assert app.query_one("#ogs").row_count == 0
    _run(go())


def test_results_without_ete3_still_lists_ogs(cli, monkeypatch):
    write_results(_cfg())

    def no_ete3(path):
        raise ModuleNotFoundError("No module named 'ete3'", name="ete3")

    def bad(path):
        raise ValueError("bad newick")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            monkeypatch.setattr(tui.species_tree, "load", no_ete3)
            await _open_results(app, pilot, "tfs")
            assert _cells(app, "#ogs", 0)[:2] == ["HG1.0", "T/Tbx19"]
            assert "pip install ete3" in app._tree_text
            await pilot.press("escape")
            await pilot.pause()
            monkeypatch.setattr(tui.species_tree, "load", bad)
            await pilot.press("o")
            await app.workers.wait_for_complete()
            await pilot.pause()
            path = _cfg().params["SPECIES_TREE"]
            assert app._tree_text == f"species tree {path}: bad newick"
    _run(go())


def test_results_tab_cycles_panes_with_orange_border(cli):
    from textual.color import Color
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            panes = ("#res", "#ogs", "#sptree_box")
            for pane in panes:
                assert app.focused is app.query_one(pane)
                for other in panes:
                    colour = app.query_one(other).styles.border.top[1]
                    assert (colour == Color.parse("orange")) == (other == pane), (pane, other)
                await pilot.press("tab")
                await pilot.pause()
            assert app.focused is app.query_one("#res")             # wraps around
            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.focused is app.query_one("#sptree_box")
            assert app.query_one("#sptree_box").border_title == "species tree"
    _run(go())


def test_footer_keys_in_results(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert app.check_action("open_results", ()) and not app.check_action("toggle_source", ())
            await _open_results(app, pilot, "tfs")
            assert app.check_action("toggle_source", ()) and app.check_action("back", ())
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
            await pilot.press("f")
            await pilot.pause()
            ov = app.query_one("#overview")
            ov.move_cursor(row=_ov_row(app, "tfs.C_x"))
            await pilot.pause()
            await pilot.press("o")                                 # blocked in the worker
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            ov.move_cursor(row=_ov_row(app, "tfs.A"))
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_group == "tfs.A"
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
    _run(go())
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider` — Expected: the 13 new tests FAIL (e.g. `NoMatches: No nodes match '#res'`, `AssertionError: assert 'overview' == 'results'`); the existing ones pass.

- [ ] **Step 3: Implement** in `phylocli/tui.py`.

3a. Imports — change two lines:

```python
from textual.containers import Grid, Horizontal, ScrollableContainer, Vertical, VerticalScroll
```
```python
from phylocli import core, history, model, species_tree
```

3b. `PANE_TITLES` — replace with:

```python
PANE_TITLES = {"#overview": "Overview", "#stages": "1 Stages", "#hgs": "2 HGs",
               "#arrays": "3 Arrays", "#detail": "4 Detail",
               "#res": "Results", "#ogs": "OGs", "#sptree_box": "species tree"}
```

3c. `PhyloApp.CSS` — append these lines inside the string, after `#hgview.loading { opacity: 40%; }`:

```
    #resv { height: 1fr; }
    #results { height: 1fr; }
    #res { width: 1fr; }
    #ogs, #sptree_box { width: 2fr; }
    #results DataTable, #sptree_box { border: round $primary; height: 100%; }
    #results DataTable:focus, #sptree_box:focus { border: round orange; }
    #resv.loading { opacity: 40%; }
    #sptree { width: auto; }
    #resfoot { height: auto; }
```

(`#sptree { width: auto; }` stops the Static from wrapping the tree lines; the ScrollableContainer scrolls both ways.)

3d. `BINDINGS` — insert after `Binding("l", "log", "log"),`:

```python
        Binding("o", "open_results", "results"),
        Binding("p", "toggle_source", "possvm/prev"),
```

3e. `__init__` — append after `self._banner_text = ""`:

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
        self._tree_text = ""
        self._sptree = None                     # ete3 tree, loaded once by the worker
        self._sptree_err = ""
```

3f. `compose` — insert after the `with Grid(id="hgview"):` block, before `yield Footer()`:

```python
        with Vertical(id="resv"):
            with Horizontal(id="results"):
                yield DataTable(id="res", cursor_type="row")
                yield DataTable(id="ogs", cursor_type="row")
                with ScrollableContainer(id="sptree_box"):
                    yield Static("", id="sptree", markup=False)
            yield Static("", id="resfoot")
```

3g. `on_mount` — insert after the line `self._set_units(force=True)` (step1 builds the `#hgs` / `#arrays` columns there):

```python
        self.query_one("#res", DataTable).add_columns("HG", "OGs", "genes", "⚠")
        self.query_one("#ogs", DataTable).add_columns("OG", "name", "genes", "spp", "support",
                                                       "ref", "ref sup")
```

3h. `_show_view` — replace the whole method:

```python
    def _show_view(self) -> None:
        self.query_one("#ov").display = self.view == "overview"
        self.query_one("#hgview").display = self.view == "hgs"
        self.query_one("#resv").display = self.view == "results"
        self.query_one({"overview": "#overview", "hgs": "#hgs", "results": "#res"}[self.view]).focus()
```

3i. `_overview_footer` — its text is split over several string literals; in the literal `"enter: open · c/f: category/family"` replace it with `"enter: open · o: results · c/f: category/family"`.

3j. `check_action` — replace the whole method:

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
        if action == "toggle_source":
            return self.view == "results"
        return True
```

3k. `action_back` — replace the whole method:

```python
    def action_back(self) -> None:
        if self.view == "results":
            self._res_gen += 1                   # a load still running is dropped when it lands
            self.view = self.res_from
            self._show_view()
        elif self.view == "hgs":
            self.view = "overview"
            self._show_view()
```

3l. `on_data_table_row_highlighted` — after the `elif t.id == "hgs":` branch, add:

```python
        elif t.id == "res":
            self._fill_ogs()
        elif t.id == "ogs":
            self._show_tree()
```

3m. `action_cycle_filter` — insert at the top of its body:

```python
        if self.view == "results":           # f has no meaning in Results (check_action hides it)
            return
```

3n. New methods — add after `action_log` (still inside `PhyloApp`):

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
        self.query_one("#res", DataTable).clear()
        self.query_one("#res").border_title = f"Results · {group}"
        self.view = "results"
        self._show_view()
        self._reload_results()

    def _reload_results(self) -> None:
        """Grey the window and start a load; the #res rows stay (greyed) so the cursor's HG is
        kept across `p`, while the OG pane empties until the new source is read."""
        self._res_gen += 1
        self.res_rows = []
        self.query_one("#resv").add_class("loading")
        self._res_note = "loading…"
        self._fill_ogs()
        self._load_results(list(self.res_hgs), self.res_source, self._res_gen)

    @work(thread=True, exclusive=True, group="results")
    def _load_results(self, hgs: list, source: "str | None", gen: int) -> None:
        """Reads the ortholog_groups.csv files (NFS) and, once, the species tree: never on the
        UI thread.  Own worker group: load_bg (default group, exclusive) must not cancel it."""
        worker = get_current_worker()
        snap = dict(gen=gen, source=source or "possvm", rows=[], missing=0, note="",
                    tree=self._sptree, tree_err=self._sptree_err)
        try:
            snap["source"] = source or model.default_source(self.cfg)
            snap["rows"], snap["missing"] = model.group_ogs(self.cfg, hgs, snap["source"])
        except Exception as e:                   # never let a worker kill the app
            snap["note"] = f"cannot read {snap['source']}/: {e}"
        if snap["tree"] is None:
            path = self.cfg.params.get("SPECIES_TREE", "")
            try:
                snap["tree"], snap["tree_err"] = species_tree.load(path), ""
            except ImportError:
                snap["tree_err"] = "species tree needs ete3: pip install ete3 (in the phylo env)"
            except Exception as e:
                snap["tree_err"] = f"species tree {path}: {e}"
        if worker.is_cancelled:
            return
        self.call_from_thread(self._apply_results, snap)

    def _apply_results(self, snap: dict) -> None:
        if snap["gen"] != self._res_gen:         # superseded: esc, another o, or p meanwhile
            return
        self.query_one("#resv").remove_class("loading")
        self.res_source, self.res_rows, self.res_missing = snap["source"], snap["rows"], snap["missing"]
        self._sptree, self._sptree_err = snap["tree"], snap["tree_err"]
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
        """OG table of the HG under the Results cursor (in memory), then its tree."""
        r = self._cur_res()
        t = self.query_one("#ogs", DataTable)
        t.clear()
        t.border_title = f"OGs · {r.hg if r else '–'} · {self.res_source or '…'}"
        for og in (r.ogs if r else []):
            sup = ("–" if og.support is None else "0.0 ⚠" if og.support == 0
                   else f"{og.support:.1f}")
            t.add_row(".".join(og.id.rsplit(".", 2)[-2:]), escape(og.name), str(len(og.genes)),
                      str(len(model.og_coverage(og))), sup, escape(og.ref), escape(og.ref_support),
                      key=og.id)
        if t.row_count:
            t.move_cursor(row=0)
        self._show_tree()

    def _show_tree(self) -> None:
        r, og = self._cur_res(), self._cur_og()
        if r is not None and r.error:
            text = r.error
        elif og is None:
            text = self._res_note
        elif self._sptree is None:
            text = self._sptree_err or "species tree not loaded"
        else:
            text = "\n".join(species_tree.render(self._sptree, model.og_coverage(og)))
        self._tree_text = text
        self.query_one("#sptree", Static).update(text)
        self._results_footer()

    def _results_footer(self) -> None:
        r = self._cur_res()
        head = r.error if r is not None and r.error else self._res_note
        parts = ([f"{len(r.ogs)} OGs"] if r is not None and not r.error else []) + [
            self.res_source or "…", "⚠ = support 0 (GeneRax bug case; check possvm_prev)"]
        if self.res_missing:
            parts.append(f"{self.res_missing} HG{'' if self.res_missing == 1 else 's'} without output")
        lines = ([head] if head else []) + [" · ".join(parts),
                                             "p: possvm ↔ possvm_prev · tab: pane · esc: back"]
        self._res_foot = "\n".join(lines)
        self.query_one("#resfoot", Static).update(escape(self._res_foot))

    def action_toggle_source(self) -> None:
        if self.view != "results" or self.res_source is None:   # first load still running
            return
        self.res_source = "possvm_prev" if self.res_source == "possvm" else "possvm"
        self._reload_results()
```

3o. `phylocli/README.md`, section `## phylo tui` — after the paragraph that ends "…read only once an HG view is open.", insert:

```markdown
`o` opens the **Results** window for the overview row under the cursor (`ALL` included) or, in
the HG view, for the highlighted HG's category/family with that HG highlighted. Three panes,
`tab` between them: **Results** (the group's HGs that have POSSVM output: OGs, genes, OGs with
support 0 `⚠`; the footer counts the HGs without output), **OGs** (the ortholog groups of the
highlighted HG, largest first: OG, name, genes, species, orthogroup support, reference ortholog
and its support) and **species tree** (`params.SPECIES_TREE`; `●n` = n member genes of that
species, `·` = none, `k/m spp` per named clade). `p` switches `possvm/` (post-GeneRax, default)
↔ `possvm_prev/` (raw IQ-TREE); `esc` goes back. Support `0.0 ⚠` is the GeneRax bug case:
check `possvm_prev`. Files are read in the background; the tree needs `ete3`.
```

and in the HG-view keys line replace `` `l` last log · `` with `` `l` last log · `o` results · ``.

- [ ] **Step 4: Run both suites** — Expected: N0 + 13 passed on both (280 from 253), output clean.

- [ ] **Step 5: Commit** — `git add phylocli/tui.py phylocli/tests/test_tui.py phylocli/README.md`; message `phylocli tui: Results window (o): HGs / OGs / species tree, p possvm <-> possvm_prev, reads in a worker` + trailer.

---

### Task 4: Overview `s` sort and `h` hide

**Files:**
- Modify: `phylocli/tui.py`, `phylocli/README.md`
- Test: `phylocli/tests/test_tui.py` (append)

**Interfaces:**
- Consumes: `model.GroupRow` (`group`, `total`, `per_stage[stage] = (done, running, ready, blocked)` or None; `ready` includes failed HGs whose inputs exist — the overview's `▓ ready/failed`; for `search`/`cluster` the four counts are **families**, `n_fams` the group's family total), step1's `stage_at_column(col) -> str | None` and `ov_column(stage) -> int` (module level in `tui.py`), `PhyloApp._fill_overview`, `_key_at_cursor`, `check_action` (Task 3 version).
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

4a. Module-level functions — add after `STATE_STYLE = {...}`, before `class PhyloApp`:

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

4b. `BINDINGS` — insert after `Binding("f", "cycle_filter", "filter / family"),`:

```python
        Binding("s", "sort", "sort"),
        Binding("h", "hide", "only actionable"),
```

4c. `__init__` — append after the line `self._array_rows: list = []`:

```python
        self.ov_sort: "tuple | None" = None     # (column name, reversed); s
        self.ov_hide: "str | None" = None       # stage name; h
        self.ov_shown: list = []                # ov_rows as displayed (sorted / filtered)
```

4d. `_fill_overview` — targeted edits only; **do not replace the method and do not touch its columns**. Step1 owns the column list (`OV_COLUMNS`, the `│` separator, the two-row `Text` headers, the restore-off-the-separator step); column→stage goes through `stage_at_column`. (At `411134d` a whole-method replacement was tried and broke `enter`.) Four Edit calls, each old → new:

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

4e. `_overview_footer` — in the literal `"enter: open · o: results · c/f: category/family"` (Task 3), replace it with `"enter: open · o: results · c/f: category/family · s: sort · h: only actionable"`.

4f. `check_action` — change its first test to:

```python
        if action in ("by_category", "sort", "hide"):
            return self.view == "overview"
```

4g. New actions — add after `action_by_category`:

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

4h. `phylocli/README.md`, section `## phylo tui` — after the overview paragraph (the one ending "…read only once an HG view is open."), insert:

```markdown
`s` sorts the overview by the highlighted column — a stage: most ready/failed first, ties by
running (on search/cluster: families); `group`: by name; `HGs`: by size — and `s` again
reverses. `h` shows only the rows with something to do (ready, failed or running) at the
highlighted stage (on search/cluster: families); `h` again shows all.
`ALL` stays on top, the pane title shows the state, and both survive refreshes and `c`/`f`.
```

- [ ] **Step 4: Run both suites** — Expected: N0 + 8 passed on both (288 from 253), output clean.

- [ ] **Step 5: Commit** — `git add phylocli/tui.py phylocli/tests/test_tui.py phylocli/README.md`; message `phylocli tui: overview s (sort by the highlighted column) and h (only actionable at a stage)` + trailer.

---

## Self-review (done while writing)

- **Spec coverage.** Part A: entry/exit (`o` from overview any column incl. ALL, `o` from `2 HGs` with HG highlighted, `esc` back with cursor, `R` untouched) → Task 3 tests 1, 2, 5; three panes + `tab`/`shift+tab` + orange → test 10; Results pane columns, sort by HG id, HGs without output counted → test 1 + Task 1 `hg_sort_key`; OG table columns, gene-count order, `0.0 ⚠` → Task 1 test 1 + Task 3 test 1; species tree `●n`/`·`/`k/m spp`, redraw on OG move → Task 2 + Task 3 test 3; `p` and title → test 4; footer → test 1; data API (`read_ogs`, `species_of`, `og_coverage`, one file expected, `None` when missing) → Task 1; `species_tree.load/render`, unknown species → Task 2; errors (no output + `p`, bad row with file and line, worker + loading) → tests 6, 8, 7. Part B: `s` per column type and reversal, `h`, ALL pinned, title, survives refresh and `c`/`f`, in memory → Task 4. "With step1 built, works on search/cluster" → `stage_at_column` + family counts, Task 4 `test_s_h_on_family_stage_count_families_and_skip_separator` (also the `│` no-op); `o` on a family row → Task 3 `test_o_on_family_row_opens_results_for_its_hgs`.
- **Placeholders.** None: every code step carries the code; README text given verbatim.
- **Type consistency.** `read_ogs(cfg, hg, source, names=None)`, `group_ogs(cfg, hgs, source) -> (list[HGOgs], int)`, `HGOgs.error: str`, `OG.support: float | None`, `species_tree.render(tree, counts) -> list[str]`, `ov_order(rows, sort, hide)`, `ov_sort = (name, reversed)`, `ov_hide = stage name` — the same names are used in every task and test.
- **Review Focus.** Each of the five lines has its test in the owning task (Task 1 ×2, Task 3 ×2, Task 4 ×1).
