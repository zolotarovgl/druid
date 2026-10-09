# phylocli step1 (`search`, `cluster`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** phylocli runs step1 for gene families — `search` (hmmsearch) then `cluster` (diamond + MCL into HGs, small HGs not written) — with the same commands, safety rules and status views (CLI and TUI) as the six step2 stages, and `step1.nf` calls the same stage scripts.

**Architecture:** Two family-level stages are added to the stage table in `core.py` (unit = family id `<pref>.<family>`, parsed from the genefam file); their done/ready rules come from one directory listing of `results/search/` and `results/clusters/`. `stages/search.sh` / `stages/cluster.sh` are the `SEARCH` / `CLUSTER` bodies of `step1.nf`; `cluster.sh` deletes small HG FASTAs with `workflow/drop_small_hgs.py`, which uses the very function `report_status.expected_hgs` uses. `model.py` gives family rows the same `StageRow` / `HGRow` shapes, so `phylo.py` and `tui.py` only learn to print them.

**Tech Stack:** Python ≥ 3.9, typer + rich, Textual (optional), bash stage scripts, pytest. Pipeline tools: `phylogeny/main.py` (hmmsearch/hmmfetch/bedtools; diamond/mcl), samtools, Nextflow 25.04 for `step1.nf`.

**Spec:** `docs/superpowers/specs/2026-10-04-phylocli-step1-design.md` (amended 08/10/2026). Read it with this plan; where this plan decides something the spec leaves open, the decision and its reason are stated in the task and collected in Task 7 Step 4.

**Repo / branch:** worktree `~/Documents/projects/phylogenies/phylocli-wt`, branch `phylocli`, HEAD `9e0ef8c` (re-checked 09/10/2026; `a49885b`…`9e0ef8c` add TUI polish and a spec only — line numbers below are at `9e0ef8c`; `5104b0e` auto-picks the HG view's filter via `_auto_filter` / `_auto_pick_filter` and runs the TUI with `mouse=False`; `f627245` adds the orange focused-pane border; `4867d41` adds the `actionable` filter (failed + ready) as `FILTERS[0]` — the default of `open_group` and `_auto_pick_filter` — with an `ACTIONABLE` branch in `visible()` and a "default view: failed+ready" footer line; line numbers below are at `4867d41`) (plan first written against `a6af91e`; re-checked 09/10/2026 against `446c599`, where the TUI opens on an OVERVIEW — groups × stages with a cell cursor, `enter` opens the HG view of that group at that stage — and `model.py` has `bar_segments`, `group_key`, `GroupRow`, `stage_states`, `group_rows`; see the TUI spec sections "Overview — the first screen" and "HG view"). All paths below are relative to it. The source of truth for step1 behaviour is the cluster copy `~/ant/gzolotarov/projects/2022_scRNAseq_Mlei/Phylogenies_v3` (below: `$V3`) — **read-only for every task**.

**Measured before writing (09/10/2026):**
- `step1.nf` and `nextflow.config` in the worktree are **byte-identical** to `$V3`'s (`diff` empty), as is everything under `phylocli/` and `workflow/report_status.py`. `$V3/data/gene_families_searchinfo.csv` is NEWER than the worktree's (352 vs 304 rows: the 18 SLC families, digestion families, reordering; 353 non-blank rows at the plan check, file changed 09/10/2026 00:16).
- `nextflow.config` already has `min_seqs = 5`, `min_distinct = 4`, `search_dir`, `cluster_dir`: **no `nextflow.config` edit is needed**.
- Duplicate family ids in `$V3`'s genefam file: **`slc.SLC44` AND `neu.Synapsin`** (the spec names only `slc.SLC44`; the two Synapsin rows even differ in their HMM list).
- A family NAME used under two prefixes: `CSD` (`rbp`, `tfs`). `phylogeny/helper/hmmsearch.py` keys rows by name (last row wins) and names outputs after that row's prefix, so `rbp.CSD`'s search wrote `tfs.CSD.*`, and step1.nf published four EMPTY `rbp.CSD.*` files = a false "no hits". See Review Focus 1.
- The 18 SLC families are NOT new any more: all have `search/` + `_cluster.tsv` in `$V3` (04/10/2026). The real check (Controller step C2) therefore compares against those.
- `$V3/results/clusters/`: 317 `_cluster.tsv`, 0 families with HG FASTAs but no tsv; 2 families with hits but no tsv (`adh.immunoglobin`, `sig.Pkinase`) will show as cluster-ready. (Re-measured at the plan check, after the step1.nf run of 09/10/2026 00:17: 351 domains FASTAs (31 empty), 319 `_cluster.tsv`, 0 HG FASTAs without tsv, 0 tsv without domains; only `adh.immunoglobin` has hits but no tsv.) `results/_removed_small_hgs/` does not exist under `$V3/results/` on the mount (spec mentions it; irrelevant to the code).
- Test count at HEAD `446c599` was 183; at `f627245` 188; at `4867d41` 189; at HEAD `9e0ef8c` it is **195**, both interpreters (measured 09/10/2026).
- The worktree's `phylogeny/` submodule is NOT checked out (empty dir), and the worktree's `data/input.fasta` is the 7-species test set, not `$V3`'s 682 MB one: the real check must point at `$V3`'s.

## Global Constraints

- CLI output text and exit codes of `status`, `missing`, `submit`, `jobs` (and hidden `queue`, `_run`) for the six step2 stages stay **byte-identical**, including help text. The only output that changes is what the spec adds: the `search` / `cluster` rows (plus one blank line) at the top of the `status` / `missing` summaries, the genefam warnings on stderr (duplicate ids; a family name under two prefixes), and the new family-id commands.
- All existing tests (195 at `9e0ef8c`) pass **unmodified**, except exactly these nine, whose expectations the spec changes (new `STAGES` order; search/cluster in the overview, which brings rows for groups that have families but no HG yet):
  - `phylocli/tests/test_history.py::test_status_hg_table` (lines 212-213: `core.STAGES` → `core.HG_STAGES`; `status HG` keeps its six HG-stage rows) — Task 2.
  - `phylocli/tests/test_tui.py::test_enter_on_stage_cell_opens_that_stage_with_failed_filter`, `::test_open_group_without_failures_picks_first_nonempty_filter` (`column=2 + core.STAGES.index("align")` → `column=tui.ov_column("align")`) and `::test_stages_panel_shows_group_counts` (`i = core.STAGES.index("align")` → `i = tui.TUI_STAGES.index("align")`) — Task 2: from Task 2 on `core.STAGES` has search/cluster in front while the TUI shows `TUI_STAGES` (HG stages until Task 6), so `core.STAGES` indices point at the wrong column/row; `tui.ov_column(stage)` (new in Task 2; Task 6 makes it skip the `│` separator column) and `TUI_STAGES` indices are right before and after Task 6.
  - `phylocli/tests/test_tui.py::test_open_group_restricts_hgs_and_esc_returns` (`column=3` and `col0 = 3` → `tui.ov_column("tree")`, i.e. the `tree` cell it opens at `9e0ef8c`) — Task 2: after Task 6 a literal 3 is the `cluster` cell and the test's HG assertions would pass vacuously on family rows.
  - `phylocli/tests/test_tui.py::test_refresh_keeps_stage_selection_and_cursor` (line 252: `cursor_row == 1` → `cursor_row == core.STAGES.index("tree")`; the stages panel gains `search`, `cluster` above `align`) — Task 6.
  - `phylocli/tests/test_tui.py::test_overview_is_first_and_reads_no_history` (`["ALL", "tfs"]` → `["ALL", "tfs", "cal", "slc"]`) — Task 6.
  - `phylocli/tests/test_tui.py::test_overview_family_toggle` (`["ALL", "tfs.A", "tfs.C_x"]` → `["ALL", "tfs.A", "tfs.C_x", "cal.Trail", "slc.NEW", "tfs.B"]`) — Task 6.
  - `phylocli/tests/test_tui.py::test_regroup_is_in_memory` (the same two lists) — Task 6.
  - `phylocli/tests/conftest.py` gains three params and three fixture files (additive; no expectation changes) — Task 1.
  - Checked, NOT changed: `test_group_rows_*` call `group_rows` without families (search/cluster cells `None`); `test_refresh_in_hg_view_stays_in_group` relies on the initial stage, which stays `align`.
- `STAGES` order: `search, cluster, align, tree, possvm_prev, generax, gxsup, possvm` (spec).
- Family id = `<pref>.<family>`: `family` = column 1, `pref` = LAST NON-EMPTY field; blank lines skipped; trailing tabs tolerated; duplicate ids are a **warning** naming them, never an error (decided by Grygoriy 09/10/2026: warning; the spec line is amended).
- Config (`phylocli/config.yaml`, under `params:`): `genefam_info: data/gene_families_searchinfo.csv`, `infasta: data/input.fasta`, `pfam_db: /users/asebe/xgraubove/data/pfam/Pfam-A.hmm`, `hmm_dir: null`, `domain_expand: 30`, `s1_ncpu: 4`, `s2_ncpu: 4`, `max_n: 2000`, `s2_inflation: 1.1` (spec).
- Resources: search = cpus `s1_ncpu`, 500 MB, 5 min; cluster = cpus `s2_ncpu`, 300 MB, 10 min; no `resources.tsv` rows; `--mem/--time/--cpus` override as for HG stages (spec).
- Small HGs: `<id>.HG<n>.fasta` is written only with ≥ `min_seqs` sequences AND ≥ `min_distinct` distinct ones, by the same function `report_status.expected_hgs` uses; `<id>_cluster.tsv` stays complete; numbering unchanged (gaps); per family the script prints `skipped <k> HGs below min_seqs/min_distinct` (spec).
- Python 3.9-safe: every new/changed module starts with `from __future__ import annotations` (except `workflow/report_status.py`, which has none today and needs none); no `match`; no `X | Y` outside annotations; no `glob(root_dir=)`.
- Textual is imported only inside `phylocli/tui.py`. New tests that need it call `pytest.importorskip("textual")` inside the test function, never at module level of `test_step1.py`.
- `phylo.py` keeps the module-level names tests use: `app`, `run_one`, `_preflight`, `_chunks`, `_missing`.
- Test commands (both must pass at the end of every task):
  - `python3 -m pytest phylocli/tests -q -p no:cacheprovider`
  - `/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-phylogenies/3dad6ea4-c859-4fe6-b319-93a358944ac8/scratchpad/py39/bin/python -m pytest phylocli/tests -q -p no:cacheprovider` (below: `$PY39`)
- Implementers commit on branch `phylocli`; every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Edit with the Edit/Write tools, never `sed`.
- **Controller-only steps** (C1-C3, end of the plan), never done inside a task: anything that writes into `$V3` (back up `step1.nf` first; deploy COMMITTED worktree files as an atomic directory swap, C3; the worktree is the source of truth), and the real-data check (needs Grygoriy's go; ≤ 4 threads; measure `uptime` and `top -bn1 | head -12` first and state the cores used; writes only into a scratch OUTDIR, never into `$V3/results`).

## Review Focus

1. **A family that `main.py hmmsearch` cannot resolve to `<ID>`** — a name listed under two prefixes (`rbp.CSD` / `tfs.CSD` in the real file) or a name it does not find. It exits 0 having written nothing named `<ID>.*`; step1.nf's touches then publish an empty "no hits" result. Expected (decided by Grygoriy 09/10/2026: warning): `search` keeps step1.nf's behaviour (exit 0, the four empty files are published) and prints a `WARNING` on stderr naming the family and the id its hits were written under; `status` / `missing` summaries, the TUI banner and `submit search` list every such name collision beforehand. → Task 1 test `test_duplicates_and_name_collisions_are_warnings`, Task 3 test `test_search_name_under_two_prefixes_warns_and_publishes_empty`, Task 5 test `test_name_collision_warnings`.
2. **`hmm_dir` set** — `helper/hmmsearch.py` fetches every model missing from `--hmm_dir` INTO that directory (`fetch_hmm(hmm, pfam_db, hmm_path)`); step1.nf avoided writing the real dir only through `stageInMode 'copy'`, while phylocli symlinks inputs (and array tasks run concurrently). Expected: the configured directory is never written. → Task 3 test `test_search_hmm_dir_is_never_written`.
3. **Every HG of a family is below `min_seqs` / `min_distinct`** — expected: the stage succeeds, `_cluster.tsv` is published, no HG FASTA; step1.nf must not fail with "Missing output file(s)" (its HG-FASTA output becomes `optional: true`). → Task 3 test `test_cluster_all_small_publishes_tsv_only`, Task 7 `step1.nf` edit.
4. **HG FASTAs in `clusters/` without `<id>_cluster.tsv`** (half-cleaned or hand-copied results) — publishing a new clustering would mix two numberings. Expected: `submit cluster` refuses the family as `output_exists`. → Task 2 test `test_validate_family_stages`, Task 5 test `test_submit_family_errors`.
5. **The real genefam file has duplicate ids** (`slc.SLC44`, `neu.Synapsin`; fixing it is out of scope) — expected (decided by Grygoriy 09/10/2026: warning): never an error. The `status` / `missing` summaries, the TUI banner and every family command (`missing search|cluster`, `submit search|cluster`, `status FAMILY`) print a warning naming the duplicates and proceed; each id counts once, and the row that is used is the LAST one, as in `main.py hmmsearch` (it keys rows by name, the last row wins) and step1.nf (which runs such an id twice, each time with that same last row). → Task 1 test `test_duplicates_and_name_collisions_are_warnings`, Task 5 test `test_duplicates_warn_and_proceed`, Task 6 test `test_tui_banner_on_duplicate_ids`.

(Also pinned, not in the top five: a family newly added to the genefam file has no HG yet and must still get its own overview row, or the one thing `search` exists for would be invisible in the TUI → Task 4 `test_group_rows_with_families`, Task 6.)

---

## File Structure

| file | responsibility |
|---|---|
| `phylocli/core.py` (modify) | stage lists (`FAMILY_STAGES`, `HG_STAGES`, `STAGES`), `unit()`, genefam parsing (`parse_genefam`, `family_ids`, `name_collisions`, `family_warnings`, `FamilyError` = missing file only), `family_done`, `hg_fasta_families`, family branches of `stage_inputs` / `publish_patterns` / `ready_set` / `inputs_ready` / `resources` / `validate`. |
| `workflow/report_status.py` (modify) | `passes(path, min_seqs, min_distinct)` — the one HG-size rule; `expected_hgs` uses it. |
| `workflow/drop_small_hgs.py` (new) | deletes small `<ID>.HG*.fasta` in the cwd via `report_status.passes`. |
| `phylocli/stages/search.sh`, `cluster.sh` (new) | `step1.nf` `SEARCH` / `CLUSTER` bodies. |
| `phylocli/runner.py` (modify) | `stage_env`: `None` params → empty string. |
| `phylocli/history.py` (modify) | `SEARCH` / `CLUSTER` processes, step1.nf runs, `family_attempts`. |
| `phylocli/model.py` (modify) | `family_states` (the one family-state function: CLI summary rows AND overview cells), `fam_group_key`, family cells in `group_rows`, family rows in `stage_rows` / `hg_rows`, `live` family tags, `select` / `plan` for family ids, tools + file preflight, genefam snapshot in `write_run`; `stage_states` stays HG-only. |
| `phylocli/phylo.py` (modify) | `missing` / `status` / `submit` for family stages; summary rows; `status FAMILY`. |
| `phylocli/tui.py` (modify) | `TUI_STAGES` (HG-only until Task 6, then all); overview search/cluster columns counted in families, family-only groups; HG view lists families on search/cluster; stages panel totals per unit; banner; unit words. |
| `phylocli/config.yaml` (modify) | step1 params. |
| `phylocli/tests/conftest.py` (modify) | fixture genefam / infasta / Pfam files and params. |
| `phylocli/tests/test_step1.py` (new) | every new test (one section per task). |
| `step1.nf` (modify) | `SEARCH` / `CLUSTER` call the stage scripts; HG FASTA output optional. |
| `phylocli/README.md`, spec (modify) | docs; decisions. |

Fixture facts (`conftest.py` `results_tree`, after Task 1): expected HGs `tfs.A.HG1`, `tfs.A.HG11` (3 seqs each), `tfs.C_x.HG1` (600 seqs); `tfs.B.HG2` (1 seq) not expected; `min_seqs=2`, `min_distinct=1`. Families (fixture genefam `root/gene_families_searchinfo.csv`): `tfs.A`, `tfs.B`, `tfs.C_x`, `slc.NEW`, `cal.Trail` (row with a trailing tab), one blank line. `clusters/` has HG FASTAs for `tfs.A`, `tfs.B`, `tfs.C_x` and **no** `_cluster.tsv`. The `cli` fixture (`test_cli.py`): fake `sbatch` echoes `12345`, fake `squeue` prints `$FAKE_SQUEUE`, fake `sacct` prints `$FAKE_SACCT` (`%b`), fake `python` (records args, `FAKE_PY_FAIL`), fake `mafft clipkit iqtree2 generax mpirun`; it does NOT fake `hmmsearch` etc. — Task 2's `step1_tools()` adds them.

---

### Task 1: Family ids — config params, genefam parsing, duplicates

**Files:**
- Modify: `phylocli/config.yaml`, `phylocli/core.py:20` (`PATH_PARAMS`), `:79-86` (`config_from_raw`), new functions after `read_ids` (`:135`)
- Modify: `phylocli/tests/conftest.py`
- Create: `phylocli/tests/test_step1.py`

**Interfaces:**
- Produces:
  - `core.FamilyError(ValueError)` — the genefam file is missing (nothing else)
  - `core.parse_genefam(path) -> tuple[list[str], list[str]]` — (ids in file order, first occurrence only; duplicated ids sorted)
  - `core.family_ids(cfg: Config, strict: bool = True) -> set[str]` — de-duplicated ids; strict: a missing file raises `FamilyError`, non-strict: `set()`. Duplicates never raise
  - `core.name_collisions(path) -> dict[str, tuple[list[str], str]]` — family name → (prefixes in file order, prefix of the LAST row with that name)
  - `core.family_warnings(cfg, collisions: bool = True) -> list[str]` — `warning: duplicate family ids ...` and (with `collisions`) one `warning: family name <N> is listed under <k> prefixes ...` per colliding name; `[]` without a genefam file
  - config params `genefam_info`, `infasta`, `pfam_db`, `hmm_dir`, `domain_expand`, `s1_ncpu`, `s2_ncpu`, `max_n`, `s2_inflation`; `genefam_info`/`infasta`/`pfam_db`/`hmm_dir` made absolute against the project root when set
  - test module `phylocli/tests/test_step1.py` with `FAMS` (the fixture family set)

- [ ] **Step 1: Fixture** — in `phylocli/tests/conftest.py` add after `ROW = ...`:

```python
GENEFAM = ("A\tPF_A\t1.1\t3\tGA\tTF\ttfs\n"
           "B\tPF_B\t1.1\t3\tGA\tTF\ttfs\n"
           "\n"
           "C_x\tPF_C\t1.1\t3\tGA\tTF\ttfs\n"
           "NEW\tPF_N\t1.1\t3\tGA\tslc\tslc\n"
           "Trail\tPF_T\t1.1\t3\tGA\tcalcium\tcal\t\n")    # trailing tab, like Carb_anhydrase / Slc26
```

and in `results_tree`, after `_w(root / "species.newick", "(a,b);\n")`:

```python
    _w(root / "gene_families_searchinfo.csv", GENEFAM)
    _w(root / "input.fasta", ">p1\nMKV\n")
    _w(root / "Pfam-A.hmm", "HMMER3/f\n")
```

and extend the `base["params"].update(...)` call (keep every existing argument) with

```python
                          genefam_info=str(root / "gene_families_searchinfo.csv"),
                          infasta=str(root / "input.fasta"),
                          pfam_db=str(root / "Pfam-A.hmm"),
```

(Without this the fixture would read the real `data/gene_families_searchinfo.csv` of the worktree.)

- [ ] **Step 2: Write the failing tests** — create `phylocli/tests/test_step1.py`:

```python
"""step1 stages (search, cluster): family ids, stage table, stage scripts, model, CLI, TUI."""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import os
import stat
import sys
from pathlib import Path

import pytest
import yaml

import report_status
from phylocli import core, history, model, runner
from phylocli import phylo as cli_mod
from phylocli.tests.test_cli import _state, calls_txt, cli, dry_dir, runs_dir  # noqa: F401  (fixture)

FAMS = {"tfs.A", "tfs.B", "tfs.C_x", "slc.NEW", "cal.Trail"}


def _cfg():
    return core.load_config(os.environ["PHYLOCLI_CONFIG"])


def _raw():
    return yaml.safe_load(open(os.environ["PHYLOCLI_CONFIG"]).read())


# ---- Task 1: family ids ------------------------------------------------------------------

def test_parse_genefam_trailing_tab_and_blank_lines(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("A\tPF\t1.1\t3\tGA\tTF\ttfs\n\n   \nCarb\tPF\t1.1\t3\tGA\tcalcium\tcal\t\n")
    assert core.parse_genefam(p) == (["tfs.A", "cal.Carb"], [])


def test_parse_genefam_duplicates(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("SLC44\tCholine_transpo\t1.1\t3\tGA\tneural\tslc\n"
                 "Synapsin\tSynapsin\t1.1\t3\tGA\tneural\tneu\n"
                 "SLC44\tCholine_transpo\t1.1\t3\tGA\tneural\tslc\n"
                 "Synapsin\tSynapsin,Synapsin_C\t1.1\t3\tGA\tneural\tneu\n"
                 "CSD\tCSD\t1.1\t3\tGA\tRBP\trbp\n"
                 "CSD\tCSD\t1.1\t3\tGA\tTF\ttfs\n")
    ids, dups = core.parse_genefam(p)
    assert ids == ["slc.SLC44", "neu.Synapsin", "rbp.CSD", "tfs.CSD"]
    assert dups == ["neu.Synapsin", "slc.SLC44"]           # rbp.CSD / tfs.CSD are different ids
    assert core.name_collisions(p) == {"CSD": (["rbp", "tfs"], "tfs")}   # the last CSD row is tfs


def test_family_ids_fixture(results_tree):
    cfg, _ = results_tree
    assert core.family_ids(cfg) == FAMS


def test_duplicates_and_name_collisions_are_warnings(results_tree):
    cfg, root = results_tree
    assert core.family_warnings(cfg) == []
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "A\tPF_A2\t1.1\t3\tGA\tTF\ttfs\n"      # duplicate id tfs.A
                 + "NEW\tPF_N2\t1.1\t3\tGA\tTF\ttfs\n")                   # name NEW: slc and tfs
    assert core.family_ids(cfg) == FAMS | {"tfs.NEW"}          # no error; each id once
    w = core.family_warnings(cfg)
    assert w == [
        f"warning: duplicate family ids in {g} (1): tfs.A; the last row of each is used "
        "(main.py hmmsearch keys rows by name, the last row wins)",
        "warning: family name NEW is listed under 2 prefixes (slc, tfs); hmmsearch keys rows by "
        "name, so slc.NEW's hits are written as tfs.NEW.* and slc.NEW looks like \"no hits\""]
    assert core.family_warnings(cfg, collisions=False) == w[:1]


def test_family_ids_missing_file(results_tree, tmp_path):
    cfg, _ = results_tree
    cfg = dataclasses.replace(cfg, params={**cfg.params, "genefam_info": str(tmp_path / "none.csv")})
    with pytest.raises(core.FamilyError, match="genefam file not found"):
        core.family_ids(cfg)
    assert core.family_ids(cfg, strict=False) == set()


def test_config_step1_params():
    raw = yaml.safe_load((core.ROOT / "phylocli/config.yaml").read_text())
    p = raw["params"]
    assert (p["genefam_info"], p["infasta"], p["pfam_db"], p["hmm_dir"]) == (
        "data/gene_families_searchinfo.csv", "data/input.fasta",
        "/users/asebe/xgraubove/data/pfam/Pfam-A.hmm", None)
    assert (p["domain_expand"], p["s1_ncpu"], p["s2_ncpu"], p["max_n"], p["s2_inflation"]) == \
        (30, 4, 4, 2000, 1.1)
    cfg = core.config_from_raw(raw)
    assert cfg.params["genefam_info"] == str(core.ROOT / "data/gene_families_searchinfo.csv")
    assert cfg.params["infasta"] == str(core.ROOT / "data/input.fasta")
    assert cfg.params["hmm_dir"] is None


def test_set_hmm_dir_and_inflation():
    raw = yaml.safe_load((core.ROOT / "phylocli/config.yaml").read_text())
    notes = core.apply_sets(raw, ["hmm_dir=/x/hmms", "s2_inflation=1.4"])
    assert raw["params"]["hmm_dir"] == "/x/hmms" and raw["params"]["s2_inflation"] == 1.4
    assert notes == ["set hmm_dir=/x/hmms (was None)", "set s2_inflation=1.4 (was 1.1)"]
```

- [ ] **Step 3: Run to verify they fail**

Run: `python3 -m pytest phylocli/tests/test_step1.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'phylocli.core' has no attribute 'parse_genefam'` and `KeyError: 'genefam_info'`.

- [ ] **Step 4: Config** — in `phylocli/config.yaml` change the first comment line to `# Parameters the step1 and step2 stages read. Values = v3 nextflow.config params + the `precise`` (keep the rest of that comment) and append under `params:` (after `min_distinct`):

```yaml
  # step1 (search, cluster): = nextflow.config params + the 24/09/2026 step1 run
  genefam_info: data/gene_families_searchinfo.csv   # family rows; the job reads a copy taken at submit
  infasta: data/input.fasta
  pfam_db: /users/asebe/xgraubove/data/pfam/Pfam-A.hmm
  hmm_dir: null        # optional dir of custom <name>.hmm models (never written: search.sh copies it)
  domain_expand: 30
  s1_ncpu: 4           # search cpus
  s2_ncpu: 4           # cluster cpus
  max_n: 2000          # recluster HGs larger than this
  s2_inflation: 1.1    # MCL inflation
```

- [ ] **Step 5: core** — in `phylocli/core.py`:

replace

```python
PATH_PARAMS = ("REFNAMES", "SPECIES_TREE", "resources_tsv")
```

with

```python
PATH_PARAMS = ("REFNAMES", "SPECIES_TREE", "resources_tsv", "genefam_info", "infasta", "pfam_db",
               "hmm_dir")
```

in `config_from_raw` replace

```python
    for k in PATH_PARAMS:
        if k in params:
            params[k] = _abs(params[k])
```

with

```python
    for k in PATH_PARAMS:
        if params.get(k):                       # hmm_dir may be null
            params[k] = _abs(params[k])
```

and add after `read_ids`:

```python
class FamilyError(ValueError):
    """The genefam file is missing. (Duplicate ids and name collisions are warnings, never errors:
    family_warnings; decided by Grygoriy 09/10/2026.)"""


def parse_genefam(path) -> tuple[list[str], list[str]]:
    """(family ids in file order, duplicated ids sorted) of a gene-family info file.

    Family id = <pref>.<family>: family = column 1, pref = the LAST NON-EMPTY field. This is
    step1.nf's `line.trim().split('\\t')` -> cols[-1]: trimming drops a trailing tab, so a row
    with an empty 8th field still takes column 7. Blank lines are skipped."""
    ids: list[str] = []
    seen: set[str] = set()
    dups: set[str] = set()
    for line in Path(path).read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        cols = line.strip().split("\t")
        fid = f"{cols[-1].strip()}.{cols[0].strip()}"
        if fid in seen:
            dups.add(fid)
        else:
            seen.add(fid)
            ids.append(fid)
    return ids, sorted(dups)


def family_ids(cfg: Config, strict: bool = True) -> set[str]:
    """Family ids of params.genefam_info, each once (a duplicated id is a warning, see
    family_warnings). strict: a missing file raises FamilyError; otherwise set()."""
    p = cfg.params.get("genefam_info")
    path = Path(p) if p else None
    if path is None or not path.is_file():
        if strict:
            raise FamilyError(f"genefam file not found: {p}")
        return set()
    ids, _dups = parse_genefam(path)
    return set(ids)


def name_collisions(path) -> dict[str, tuple[list[str], str]]:
    """Family names listed under more than one prefix: name -> (prefixes in file order, prefix
    of the LAST row with that name). main.py hmmsearch keys rows by name (the last row wins) and
    names its outputs after that row's prefix, so every other prefix's id gets no hits."""
    prefs: dict[str, list[str]] = {}
    last: dict[str, str] = {}
    for line in Path(path).read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        cols = line.strip().split("\t")
        name, pref = cols[0].strip(), cols[-1].strip()
        prefs.setdefault(name, [])
        if pref not in prefs[name]:
            prefs[name].append(pref)
        last[name] = pref
    return {n: (ps, last[n]) for n, ps in prefs.items() if len(ps) > 1}


def family_warnings(cfg: Config, collisions: bool = True) -> list[str]:
    """Warnings about the genefam file -- never errors (decided by Grygoriy 09/10/2026): duplicate
    ids (the last row is used, as main.py and step1.nf do) and, with `collisions`, family names
    listed under several prefixes. [] when there is no genefam file."""
    p = cfg.params.get("genefam_info")
    if not p or not Path(p).is_file():
        return []
    out = []
    _ids, dups = parse_genefam(p)
    if dups:
        out.append(f"warning: duplicate family ids in {p} ({len(dups)}): {' '.join(dups)}; "
                   "the last row of each is used (main.py hmmsearch keys rows by name, the last "
                   "row wins)")
    if collisions:
        for name, (prefs, used) in sorted(name_collisions(p).items()):
            lost = " and ".join(f"{q}.{name}" for q in prefs if q != used)
            out.append(f"warning: family name {name} is listed under {len(prefs)} prefixes "
                       f"({', '.join(prefs)}); hmmsearch keys rows by name, so {lost}'s hits are "
                       f"written as {used}.{name}.* and {lost} looks like \"no hits\"")
    return out
```

- [ ] **Step 6: Run the new tests, then both suites**

Run: `python3 -m pytest phylocli/tests/test_step1.py -q -p no:cacheprovider` → 7 passed.
Run both Global-Constraints commands → `202 passed` on both.

- [ ] **Step 7: Commit**

```bash
git add phylocli/config.yaml phylocli/core.py phylocli/tests/conftest.py phylocli/tests/test_step1.py
git commit -m "phylocli step1: family ids from the genefam file (trailing tab; duplicates and name collisions are warnings), step1 params

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Stage table — family stages, done/ready/inputs/publish/resources/validate, `report_status.passes`

**Files:**
- Modify: `phylocli/core.py` (`STAGES`, `PUBLISH_DIR`, `resources`, `stage_inputs`, `publish_patterns`, `inputs_ready`, `ready_set`, `validate`; new `unit`, `family_done`, `hg_fasta_families`)
- Modify: `workflow/report_status.py:97-108` (`expected_hgs`) + new `passes`
- Modify (HG-only loops keep the six HG stages; line numbers at `9e0ef8c`): `phylocli/model.py:170,240,541`, `phylocli/phylo.py:62-63,181,198`, `phylocli/history.py:290`, `phylocli/tui.py:31-32 (new TUI_STAGES + ov_column after them),69,129,217,221,264,271-272,296,330,370`
- Modify tests (spec-changed indices, see Global Constraints): `phylocli/tests/test_tui.py:581-582,616,694,760`
- Modify test (spec-changed expectation): `phylocli/tests/test_history.py:212-213`
- Test: `phylocli/tests/test_step1.py`

**Interfaces:**
- Consumes: `core.family_ids`, `core.FamilyError` (Task 1)
- Produces:
  - `core.FAMILY_STAGES = ["search", "cluster"]`, `core.HG_STAGES = ["align", "tree", "possvm_prev", "generax", "gxsup", "possvm"]`, `core.STAGES = FAMILY_STAGES + HG_STAGES`
  - `core.unit(stage) -> str` — `"families"` | `"HGs"`
  - `core.family_done(cfg, families) -> dict[str, set[str]]` with keys `search`, `cluster`, `no_hits`, `hits`
  - `core.hg_fasta_families(cfg) -> set[str]` — families with any `<id>.HG*.fasta` in `clusters/`
  - `core.stage_inputs(cfg, "search", fam) -> [genefam, infasta(, hmm_dir)]`, `(cfg, "cluster", fam) -> [outdir/search/<fam>.domains.fasta]`
  - `core.publish_patterns("search", fam) -> ([<fam>.domains.csv, <fam>.domains_ummerged.csv, <fam>.genes.list], <fam>.domains.fasta)`; `("cluster", fam) -> ([<fam>.HG*.fasta], <fam>_cluster.tsv)`
  - `core.resources(cfg, "search"|"cluster", fam, table)`; `core.validate(...)` accepts family ids for family stages (raises `FamilyError` only when the genefam file is missing; duplicates proceed)
  - `report_status.passes(path, min_seqs=2, min_distinct=1) -> bool`
  - test helpers in `test_step1.py`: `step1_outputs(outdir)`, `step1_tools()`

- [ ] **Step 1: Write the failing tests** — append to `phylocli/tests/test_step1.py`:

```python
# ---- Task 2: stage table -----------------------------------------------------------------

def step1_outputs(outdir: Path) -> None:
    """search done for tfs.A (hits, clustered), tfs.B (no hits), tfs.C_x (hits, NOT clustered;
    the fixture's clusters/tfs.C_x.HG1.fasta has no _cluster.tsv). slc.NEW, cal.Trail: nothing."""
    s = outdir / "search"
    s.mkdir(parents=True, exist_ok=True)
    for fam, fasta in (("tfs.A", ">a\nMK\n"), ("tfs.B", ""), ("tfs.C_x", ">c\nMK\n")):
        for suf in (".domains.csv", ".domains_ummerged.csv", ".genes.list"):
            (s / f"{fam}{suf}").write_text("")
        (s / f"{fam}.domains.fasta").write_text(fasta)
    (outdir / "clusters" / "tfs.A_cluster.tsv").write_text("HG1\ta\nHG11\tb\n")


def step1_tools():
    """Fake the step1 tools in the cli fixture's bin (preflight only checks they are on PATH)."""
    for t in ("hmmsearch", "hmmfetch", "bedtools", "samtools", "diamond", "mcl"):
        p = _state["bin"] / t
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR)


def test_stage_table_order_and_units(results_tree):
    cfg, _ = results_tree
    assert core.STAGES == ["search", "cluster", "align", "tree", "possvm_prev", "generax",
                           "gxsup", "possvm"]
    assert core.FAMILY_STAGES == ["search", "cluster"] and core.STAGES[2:] == core.HG_STAGES
    assert [core.unit(s) for s in ("search", "cluster", "align")] == ["families", "families", "HGs"]
    assert all(core.applicable(cfg, st) for st in core.FAMILY_STAGES)


def test_family_done_and_ready(results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    d = core.family_done(cfg, FAMS)
    assert d["search"] == {"tfs.A", "tfs.B", "tfs.C_x"}
    assert d["no_hits"] == {"tfs.B"} and d["hits"] == {"tfs.A", "tfs.C_x"}
    assert d["cluster"] == {"tfs.A", "tfs.B"}                       # _cluster.tsv, or no hits
    assert core.ready_set(cfg, "search", sorted(FAMS) + ["slc.NOPE"]) == FAMS
    assert core.ready_set(cfg, "cluster", FAMS) == {"tfs.A", "tfs.C_x"}
    assert [core.inputs_ready(cfg, "cluster", f) for f in ("tfs.C_x", "tfs.B", "slc.NEW")] == \
        [True, False, False]
    assert core.hg_fasta_families(cfg) == {"tfs.A", "tfs.B", "tfs.C_x"}


def test_family_stage_inputs_and_publish(results_tree):
    cfg, root = results_tree
    assert core.stage_inputs(cfg, "search", "slc.NEW") == [root / "gene_families_searchinfo.csv",
                                                           root / "input.fasta"]
    hm = dataclasses.replace(cfg, params={**cfg.params, "hmm_dir": str(root / "hmms")})
    assert core.stage_inputs(hm, "search", "slc.NEW")[-1] == root / "hmms"
    assert core.stage_inputs(cfg, "cluster", "slc.NEW") == [cfg.outdir / "search/slc.NEW.domains.fasta"]
    assert core.publish_patterns("search", "slc.NEW") == (
        ["slc.NEW.domains.csv", "slc.NEW.domains_ummerged.csv", "slc.NEW.genes.list"],
        "slc.NEW.domains.fasta")
    assert core.publish_patterns("cluster", "slc.NEW") == (["slc.NEW.HG*.fasta"], "slc.NEW_cluster.tsv")
    assert core.publish_dir(cfg, "search") == cfg.outdir / "search"
    assert core.publish_dir(cfg, "cluster") == cfg.outdir / "clusters"


def test_family_resources(results_tree):
    cfg, _ = results_tree
    assert core.resources(cfg, "search", "slc.NEW", {}) == core.Res(4, 500, 5, "normal", None)
    assert core.resources(cfg, "cluster", "slc.NEW", {}) == core.Res(4, 300, 10, "normal", None)
    two = dataclasses.replace(cfg, params={**cfg.params, "s1_ncpu": 2, "s2_ncpu": 8})
    assert (core.resources(two, "search", "x.y", {}).cpus,
            core.resources(two, "cluster", "x.y", {}).cpus) == (2, 8)


def test_validate_family_stages(results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    e = core.validate(cfg, "search", ["tfs.A", "slc.NEW", "slc.NOPE"], set())
    assert (e["unknown"], e["output_exists"], e["input_missing"]) == (["slc.NOPE"], ["tfs.A"], [])
    e = core.validate(cfg, "cluster", ["tfs.A", "tfs.C_x", "slc.NEW"], {"tfs.A"})
    assert e["output_exists"] == ["tfs.A", "tfs.C_x"]     # C_x: HG FASTAs on disk, no _cluster.tsv
    assert e["input_missing"] == ["slc.NEW"] and e["queued"] == ["tfs.A"]


def test_validate_family_duplicates_proceed(results_tree):
    cfg, root = results_tree
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "NEW\tPF_N\t1.1\t3\tGA\tslc\tslc\n")     # duplicate: a warning only
    assert not any(core.validate(cfg, "search", ["slc.NEW"], set()).values())


def test_passes_is_the_expected_hgs_rule(results_tree):
    cfg, _ = results_tree
    clu = cfg.outdir / "clusters"
    (clu / "tfs.D.HG1.fasta").write_text("".join(f">s{i}\nAA\n" for i in range(8)))        # 8 identical
    (clu / "tfs.D.HG2.fasta").write_text("".join(f">s{i}\n{'A' * i}\n" for i in range(1, 6)))
    for ms, md in ((2, 1), (5, 1), (5, 4)):
        exp = report_status.expected_hgs(str(cfg.outdir), min_seqs=ms, min_distinct=md)
        rule = {f.name[:-6] for f in clu.glob("*.HG*.fasta") if report_status.passes(str(f), ms, md)}
        assert exp == rule
    assert report_status.passes(str(clu / "tfs.D.HG2.fasta"), 5, 4)
    assert not report_status.passes(str(clu / "tfs.D.HG1.fasta"), 5, 4)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest phylocli/tests/test_step1.py -q -p no:cacheprovider -k "stage_table or family_done or family_stage or family_resources or validate_family or passes"`
Expected: FAIL — `AttributeError: module 'phylocli.core' has no attribute 'FAMILY_STAGES'` (and `passes`).

- [ ] **Step 3: `report_status.passes`** — in `workflow/report_status.py` add before `expected_hgs`:

```python
def passes(path, min_seqs=2, min_distinct=1):
    """True when step2 runs this HG FASTA: >= min_seqs sequences and >= min_distinct distinct
    ones. The ONE size rule: expected_hgs() and step1's cluster stage (drop_small_hgs.py) both
    call it, so step1 and step2 can never disagree on which HGs exist."""
    return (count_seqs(path, stop=min_seqs) >= min_seqs
            and count_distinct(path, stop=min_distinct) >= min_distinct)
```

and replace the return of `expected_hgs`

```python
    return {f[:-6] for f in nonempty_files(cdir)
            if f.endswith(".fasta") and ".HG" in f
            and count_seqs(os.path.join(cdir, f), stop=min_seqs) >= min_seqs
            and count_distinct(os.path.join(cdir, f), stop=min_distinct) >= min_distinct}
```

with

```python
    return {f[:-6] for f in nonempty_files(cdir)
            if f.endswith(".fasta") and ".HG" in f
            and passes(os.path.join(cdir, f), min_seqs, min_distinct)}
```

- [ ] **Step 4: core stage table** — in `phylocli/core.py` replace

```python
STAGES = ["align", "tree", "possvm_prev", "generax", "gxsup", "possvm"]
PUBLISH_DIR = {"align": "align", "tree": "gene_trees", "possvm_prev": "possvm_prev",
               "generax": "generax", "gxsup": "generax_support", "possvm": "possvm"}
```

with

```python
FAMILY_STAGES = ["search", "cluster"]                 # unit: gene family <pref>.<family> (step1)
HG_STAGES = ["align", "tree", "possvm_prev", "generax", "gxsup", "possvm"]   # unit: HG (step2)
STAGES = FAMILY_STAGES + HG_STAGES
PUBLISH_DIR = {"search": "search", "cluster": "clusters",
               "align": "align", "tree": "gene_trees", "possvm_prev": "possvm_prev",
               "generax": "generax", "gxsup": "generax_support", "possvm": "possvm"}
DOMAINS_SUFFIX = ".domains.fasta"
CLUSTER_SUFFIX = "_cluster.tsv"


def unit(stage: str) -> str:
    """What one id of `stage` is, as printed in notes: 'families' or 'HGs'."""
    return "families" if stage in FAMILY_STAGES else "HGs"
```

add after `family_ids` (from Task 1):

```python
def family_done(cfg: Config, families) -> dict[str, set[str]]:
    """step1 state of these families from ONE listing each of search/ and clusters/:
      search   <id>.domains.fasta exists (it is empty when the family has no hits)
      no_hits  ... exists and is empty
      hits     ... exists and is non-empty (= cluster's input is ready)
      cluster  <id>_cluster.tsv exists, or no_hits (nothing to cluster) -- step1.nf familyIsDone"""
    fams = set(families)
    sizes: dict[str, int] = {}
    sdir = cfg.outdir / "search"
    if sdir.is_dir():
        with os.scandir(sdir) as it:
            for e in it:
                fid = e.name[:-len(DOMAINS_SUFFIX)] if e.name.endswith(DOMAINS_SUFFIX) else None
                if fid in fams:
                    try:
                        sizes[fid] = e.stat().st_size
                    except OSError:
                        pass
    cdir = cfg.outdir / "clusters"
    tsv: set[str] = set()
    if cdir.is_dir():
        tsv = {n[:-len(CLUSTER_SUFFIX)] for n in os.listdir(cdir) if n.endswith(CLUSTER_SUFFIX)} & fams
    no_hits = {f for f, n in sizes.items() if n == 0}
    return {"search": set(sizes), "no_hits": no_hits, "hits": set(sizes) - no_hits,
            "cluster": tsv | no_hits}


def hg_fasta_families(cfg: Config) -> set[str]:
    """Families with at least one <id>.HG*.fasta in clusters/ (one listing)."""
    cdir = cfg.outdir / "clusters"
    if not cdir.is_dir():
        return set()
    return {n[:n.rindex(".HG")] for n in os.listdir(cdir) if n.endswith(".fasta") and ".HG" in n}
```

in `resources`, before the final `else:` add:

```python
    elif stage == "search":                       # step1.nf SEARCH, attempt 1
        cpus, mem, time = int(cfg.params["s1_ncpu"]), 500, 5
    elif stage == "cluster":                      # step1.nf CLUSTER, attempt 1
        cpus, mem, time = int(cfg.params["s2_ncpu"]), 300, 10
```

in `stage_inputs`, at the top of the body (after `o = cfg.outdir`):

```python
    if stage == "search":
        out = [Path(cfg.params["genefam_info"]), Path(cfg.params["infasta"])]
        if cfg.params.get("hmm_dir"):
            out.append(Path(cfg.params["hmm_dir"]))
        return out
    if stage == "cluster":
        return [o / "search" / f"{hg}{DOMAINS_SUFFIX}"]
```

(`pfam_db` is not staged: step1.nf passes `--pfam_db` as a path too; Task 4's preflight checks it exists.)

in `publish_patterns`, at the top of the body:

```python
    if stage == "search":
        return ([f"{hg}.domains.csv", f"{hg}.domains_ummerged.csv", f"{hg}.genes.list"],
                f"{hg}{DOMAINS_SUFFIX}")
    if stage == "cluster":
        return [f"{hg}.HG*.fasta"], f"{hg}{CLUSTER_SUFFIX}"
```

replace `inputs_ready` with

```python
def inputs_ready(cfg: Config, stage: str, hg: str) -> bool:
    """True if every input file the stage reads for this HG exists (families: see ready_set)."""
    if stage in FAMILY_STAGES:
        return hg in ready_set(cfg, stage, [hg])
    return all(p.exists() for p in stage_inputs(cfg, stage, hg))
```

in `ready_set`, insert at the top of the body (before `listings: ...`):

```python
    if stage == "search":            # ready whenever the family has a row in the genefam file
        fams = family_ids(cfg, strict=False)
        return {f for f in hgs if f in fams}
    if stage == "cluster":           # ready when its domains FASTA exists and is non-empty
        return family_done(cfg, hgs)["hits"]
```

replace `validate` with

```python
def validate(cfg: Config, stage: str, hgs: list[str], queued: set[str]) -> dict[str, list[str]]:
    errs = {k: [] for k in ("not_applicable", "unknown", "output_exists", "input_missing", "queued")}
    family = stage in FAMILY_STAGES
    exp = family_ids(cfg) if family else expected(cfg)          # family: FamilyError if no genefam file
    known = []
    for hg in hgs:
        (known if hg in exp else errs["unknown"]).append(hg)
    if not applicable(cfg, stage):
        errs["not_applicable"] = list(known)
    elif family:
        done = family_done(cfg, exp)[stage]
        if stage == "cluster":
            # HG FASTAs without a _cluster.tsv: publishing would mix two clusterings
            done = done | hg_fasta_families(cfg)
        ready = ready_set(cfg, stage, known)
        for hg in known:
            if hg in done:
                errs["output_exists"].append(hg)
            if hg not in ready:
                errs["input_missing"].append(hg)
            if hg in queued:
                errs["queued"].append(hg)
    else:
        done = report_status.done_by_stage(str(cfg.outdir), exp)[stage]
        for hg in known:
            if hg in done:
                errs["output_exists"].append(hg)
            if not inputs_ready(cfg, stage, hg):
                errs["input_missing"].append(hg)
            if hg in queued:
                errs["queued"].append(hg)
    return {k: sorted(v) for k, v in errs.items()}
```

- [ ] **Step 5: Keep the HG-only loops on the six HG stages** (each is an Edit of exactly these lines; line numbers at `9e0ef8c`):
  - `phylocli/model.py:170` (`stage_rows`), `:240` (`hg_detail`) and `:541` (`stage_states` — HG states only, permanently; Task 4 adds `family_states` beside it): `for st in core.STAGES:` → `for st in core.HG_STAGES:`. Leave `group_rows`'s per-stage loop (`:573`) on `core.STAGES`: a stage missing from `states` already yields `None`, which is what the search/cluster cells are until Task 4 passes families.
  - `phylocli/phylo.py:62-63` (`_check_stage`): both `core.STAGES` → `core.HG_STAGES` (Task 5 switches it to all stages once the commands handle families; until then the message stays byte-identical)
  - `phylocli/phylo.py:181` and `:198` (`_hg_status`): `for st in core.STAGES:` → `for st in core.HG_STAGES:`
  - `phylocli/history.py:290`: `m.group(7) not in core.STAGES` → `m.group(7) not in core.HG_STAGES`
  - `phylocli/tui.py`: add after `STATE_STYLE = {...}` (lines 31-32, below `FILTERS` / `ACTIONABLE`)
    ```python
    # Stages the TUI shows (overview columns, stages panel, HG-view data). HG stages only until
    # the step1 TUI task widens it to core.STAGES (search/cluster in front).
    TUI_STAGES = core.HG_STAGES


    def ov_column(stage: str) -> int:
        """Overview column of `stage` (after the group and HGs columns). Task 6 adds the step1/step2
        separator column; tests and code index the overview only through this."""
        return 2 + TUI_STAGES.index(stage)
    ```
    and then:
    - `:69` `self.stage = core.STAGES[0]` → `self.stage = core.HG_STAGES[0]   # opens on align; search/cluster sit before it`
    - `:129` (`_collect`, `by_stage`) `for st in core.STAGES}` → `for st in TUI_STAGES}`
    - `:217` `t.add_columns("group", "HGs", *core.STAGES)` → `t.add_columns("group", "HGs", *TUI_STAGES)`
    - `:221` (`_fill_overview`) `for st in core.STAGES:` → `for st in TUI_STAGES:`
    - `:264` (`_fill_stages`) `for name in core.STAGES:` → `for name in TUI_STAGES:`; `:271-272` both `core.STAGES` → `TUI_STAGES`
    - `:296` (`open_group`) `core.STAGES.index(stage)` → `TUI_STAGES.index(stage)`
    - `:330` (`on_data_table_cell_selected`) `core.STAGES[col - 2]` → `TUI_STAGES[col - 2]`
    - `:370` (`_show_detail`) `for st in core.STAGES:` → `for st in core.HG_STAGES:` (an HG's detail always lists the six HG stages)
    - `:395` stays `core.STAGES` (membership test only).

- [ ] **Step 6: The existing tests this task changes** — (a) `phylocli/tests/test_history.py::test_status_hg_table`, lines 212-213: replace

```python
    rows = {l.split()[0]: l for l in lines if l.split() and l.split()[0] in core.STAGES}
    assert list(rows) == core.STAGES
```

with

```python
    rows = {l.split()[0]: l for l in lines if l.split() and l.split()[0] in core.HG_STAGES}
    assert list(rows) == core.HG_STAGES
```

(Spec: `STAGES` gains `search`/`cluster` in front; `status HG` keeps exactly the six HG-stage rows it printed before.)

(b) `phylocli/tests/test_tui.py` — index the overview with `tui.ov_column(...)` and the stages panel with `tui.TUI_STAGES`, which is what they show (HG stages now, all stages after Task 6), not with `core.STAGES` (search/cluster in front from this task on; `2 + core.STAGES.index("align")` would be column 4 = `possvm_prev`):
  - `test_enter_on_stage_cell_opens_that_stage_with_failed_filter` (line 616) and `test_open_group_without_failures_picks_first_nonempty_filter` (line 760): `ov.move_cursor(row=0, column=2 + core.STAGES.index("align"))   # ALL x align` → `ov.move_cursor(row=0, column=tui.ov_column("align"))   # ALL x align` (Edit with `replace_all`: the two lines are identical)
  - `test_stages_panel_shows_group_counts` (line 694): `i = core.STAGES.index("align")` → `i = tui.TUI_STAGES.index("align")`
  - `test_open_group_restricts_hgs_and_esc_returns` (lines 581-582): replace
    ```python
            app.query_one("#overview").move_cursor(row=1, column=3)    # tfs.A
            col0 = 3
    ```
    with
    ```python
            col0 = tui.ov_column("tree")                            # tfs.A x tree (= 3 before step1)
            app.query_one("#overview").move_cursor(row=1, column=col0)
    ```
    (after Task 6 a literal 3 is the `cluster` cell, and the HG assertions would hold vacuously on family rows; `ov_column` also follows the separator column)

- [ ] **Step 7: Run both suites** — Expected: `209 passed` on both (`test_ready_set_matches_inputs_ready` now also iterates `search`/`cluster` with HG ids: both functions return the empty set, as they must).

- [ ] **Step 8: Commit**

```bash
git add phylocli/core.py workflow/report_status.py phylocli/model.py phylocli/phylo.py \
        phylocli/history.py phylocli/tui.py phylocli/tests/test_history.py phylocli/tests/test_tui.py \
        phylocli/tests/test_step1.py
git commit -m "phylocli step1: search/cluster in the stage table (done/ready/inputs/publish/resources/validate); report_status.passes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Stage scripts `search.sh` / `cluster.sh`, small-HG filter, runner

**Files:**
- Create: `phylocli/stages/search.sh`, `phylocli/stages/cluster.sh`, `workflow/drop_small_hgs.py`
- Modify: `phylocli/runner.py:20-26` (`stage_env`)
- Test: `phylocli/tests/test_step1.py`

**Interfaces:**
- Consumes: `core.stage_inputs`, `core.publish_patterns`, `core.resources` for `search`/`cluster` (Task 2); `report_status.passes` (Task 2)
- Produces:
  - `phylocli/stages/search.sh GENEFAM INFASTA [HMM_DIR]` — env `ID` (`<pref>.<family>`), `CPUS`, `PROJECT_DIR`, `pfam_db`, `domain_expand`; writes `<ID>.domains.{csv,fasta}`, `<ID>.domains_ummerged.csv`, `<ID>.genes.list`; when `main.py hmmsearch` wrote nothing named `<ID>.*` it prints a `WARNING` on stderr (naming the id the hits went to, if any) and still publishes the empty files, as step1.nf does
  - `phylocli/stages/cluster.sh DOMAINS_FASTA` — env `ID`, `CPUS`, `PROJECT_DIR`, `max_n`, `s2_inflation`, `min_seqs`, `min_distinct`; writes `<ID>_cluster.tsv` (complete) and `<ID>.HG<n>.fasta` for passing HGs only
  - `workflow/drop_small_hgs.py ID MIN_SEQS MIN_DISTINCT` — prints `<ID>: skipped <k> HGs below min_seqs/min_distinct (<ms>/<md>); kept <n>`
  - `runner.stage_env`: a `None` param is exported as `""`

Verbatim note: the bodies are step1.nf's `SEARCH` / `CLUSTER` scripts with Nextflow interpolations → env vars / positional args (`${pref}.${family}` → `${ID}`, `${family}` → `${FAMILY}`, `${task.cpus}` → `${CPUS}`, `${params.x}` → `${x}`, `\$` → `$`). Deliberate deviations, each commented in the script or listed here: (1) the CLUSTER loop variable `ID` is renamed `HG` (it would overwrite the family id); (2) search gets the Review-Focus `WARNING` (no exit code change) and the `hmm_dir` copy; (3) both scripts start with `set -euo pipefail`, like the six step2 stage scripts, where step1.nf's SEARCH body had `set -e` and Nextflow runs scripts with `bash -ue` (no `pipefail`) — `pipefail` only matters for `cut | sort -u` in cluster.sh, which cannot fail on a file the line before just wrote; under step1.nf the same scripts now run with `pipefail` too.

- [ ] **Step 1: Write the failing tests** — append to `phylocli/tests/test_step1.py`:

```python
# ---- Task 3: stage scripts -----------------------------------------------------------------

# Stand-in for phylogeny/main.py (the worktree's submodule is not checked out). hmmsearch
# behaves like helper/hmmsearch.py: the row is looked up by NAME (last row wins) and outputs are
# named after THAT row's prefix; an unknown name writes nothing and exits 0.
FAKE_MAIN = r'''
import os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_ARGS"], "a") as fh:
    fh.write(" ".join(a) + "\n")
if a[0] == "hmmsearch":
    mode = os.environ.get("FAKE_HMM", "hits")
    if "--hmm_dir" in a:              # helper/hmmsearch.py fetches missing models INTO hmm_dir
        with open(os.path.join(a[a.index("--hmm_dir") + 1], "fetched.hmm"), "w") as fh:
            fh.write("fetched\n")
    if mode == "notfound":
        sys.exit(0)
    fam, gene = a[5], a[a.index("-g") + 1]
    rows = [l.strip().split("\t") for l in open(gene) if l.strip()]
    out = [r[-1] for r in rows if r[0] == fam][-1] + "." + fam
    if mode == "hits":
        open(out + ".domains.fasta", "w").write(">s1\nMKV\n")
        open(out + ".domains.csv", "w").write("s1\t1\t3\tPF\n")
        open(out + ".domains_ummerged.csv", "w").write("s1\t1\t3\tPF\n")
        open(out + ".genes.list", "w").write("s1\n")
    else:                             # nohits: helper writes an empty genes.list and stops
        open(out + ".genes.list", "w").write("")
elif a[0] == "cluster":               # HG by the first letter of the sequence name: a b c d
    fasta, out = a[a.index("-f") + 1], a[a.index("--out_file") + 1]
    names = [l[1:].split()[0] for l in open(fasta) if l.startswith(">")]
    with open(out, "w") as fh:
        for n in names:
            fh.write(f"HG{'abcd'.index(n[0]) + 1}\t{n}\n")
'''

FAKE_SAMTOOLS = r'''
import sys
assert sys.argv[1] == "faidx"
path, ids = sys.argv[2], sys.argv[3:]
recs, cur = {}, None
for line in open(path):
    line = line.rstrip("\n")
    if line.startswith(">"):
        cur = line[1:].split()[0]
        recs[cur] = []
    elif cur is not None:
        recs[cur].append(line)
if not ids:
    with open(path + ".fai", "w") as fh:
        fh.write("".join(f"{k}\t{len(''.join(v))}\n" for k, v in recs.items()))
else:
    sys.stdout.write("".join(f">{i}\n" + "\n".join(recs[i]) + "\n" for i in ids))
'''

DOMAINS = ("".join(f">a{i}\nMKA\n" for i in range(1, 2))               # HG1: 1 seq
           + "".join(f">b{i}\nMK{'B' * i}\n" for i in range(1, 5))     # HG2: 4 seqs
           + "".join(f">c{i}\nMK{'C' * i}\n" for i in range(1, 6))     # HG3: 5 distinct
           + "".join(f">d{i}\nMKDD\n" for i in range(1, 6)))           # HG4: 5 identical


def stage_project(tmp_path, monkeypatch) -> Path:
    """PROJECT_DIR with the stub main.py and the REAL workflow/ (drop_small_hgs.py,
    report_status.py); PATH with a real `python` and a fake `samtools`. The stage scripts run
    are the real phylocli/stages/*.sh (runner.STAGES_DIR is left alone)."""
    proj = tmp_path / "proj"
    (proj / "phylogeny").mkdir(parents=True)
    (proj / "phylogeny" / "main.py").write_text(FAKE_MAIN)
    (proj / "workflow").symlink_to(core.ROOT / "workflow")
    b = tmp_path / "s1bin"
    b.mkdir()
    (b / "python").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (b / "samtools.py").write_text(FAKE_SAMTOOLS)
    (b / "samtools").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{b}/samtools.py" "$@"\n')
    for n in ("python", "samtools"):
        (b / n).chmod((b / n).stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_ARGS", str(tmp_path / "args.txt"))
    monkeypatch.setattr(runner, "ROOT", proj)              # stage_env: PROJECT_DIR
    return proj


def _spy_replace(monkeypatch) -> list:
    order, real = [], os.replace
    monkeypatch.setattr(runner.os, "replace", lambda a, b: (order.append(Path(b).name), real(a, b)))
    return order


def test_stage_env_none_is_empty(results_tree):
    cfg, _ = results_tree
    env = runner.stage_env(cfg, "search", "slc.NEW", 4)
    assert env["hmm_dir"] == "" and env["pfam_db"].endswith("Pfam-A.hmm") and env["ID"] == "slc.NEW"


def test_search_publishes_marker_last(results_tree, tmp_path, monkeypatch):
    cfg, root = results_tree
    stage_project(tmp_path, monkeypatch)
    order = _spy_replace(monkeypatch)
    assert runner.run_one(cfg, "search", "slc.NEW", tmp_path / "work") == 0
    assert order == ["slc.NEW.domains.csv", "slc.NEW.domains_ummerged.csv", "slc.NEW.genes.list",
                     "slc.NEW.domains.fasta"]
    assert (tmp_path / "args.txt").read_text().split() == [
        "hmmsearch", "-f", "input.fasta", "-g", "gene_families_searchinfo.csv", "NEW", "-o", ".",
        "--pfam_db", str(root / "Pfam-A.hmm"), "--domain_expand", "30", "--ncpu", "4"]
    assert core.family_done(cfg, {"slc.NEW"})["hits"] == {"slc.NEW"}
    assert not (tmp_path / "work" / "slc.NEW").exists()


def test_search_trailing_tab_family(results_tree, tmp_path, monkeypatch):
    cfg, _ = results_tree
    stage_project(tmp_path, monkeypatch)
    assert runner.run_one(cfg, "search", "cal.Trail", tmp_path / "work") == 0
    assert (cfg.outdir / "search/cal.Trail.domains.fasta").read_text() == ">s1\nMKV\n"


def test_search_no_hits_publishes_empty_marker(results_tree, tmp_path, monkeypatch):
    cfg, _ = results_tree
    stage_project(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_HMM", "nohits")
    assert runner.run_one(cfg, "search", "slc.NEW", tmp_path / "work") == 0
    d = core.family_done(cfg, {"slc.NEW"})
    assert d["no_hits"] == {"slc.NEW"} and d["cluster"] == {"slc.NEW"}


def test_search_name_under_two_prefixes_warns_and_publishes_empty(results_tree, tmp_path, monkeypatch,
                                                                   capfd):
    cfg, root = results_tree
    stage_project(tmp_path, monkeypatch)
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "Dup\tPF_D\t1.1\t3\tGA\tRBP\trbp\nDup\tPF_D\t1.1\t3\tGA\tTF\ttfs\n")
    assert runner.run_one(cfg, "search", "rbp.Dup", tmp_path / "work") == 0   # hits went to tfs.Dup.*
    err = capfd.readouterr().err
    assert "WARNING: family name Dup" in err and "rbp.Dup's hits are written as tfs.Dup.*" in err
    s = cfg.outdir / "search"
    assert (s / "rbp.Dup.domains.fasta").read_text() == ""                   # step1.nf behaviour
    assert core.family_done(cfg, {"rbp.Dup"})["no_hits"] == {"rbp.Dup"}
    assert not list(s.glob("tfs.Dup.*"))                                      # not this task's id
    monkeypatch.setenv("FAKE_HMM", "notfound")                                # name not found at all
    assert runner.run_one(cfg, "search", "slc.NEW", tmp_path / "work") == 0
    assert "WARNING: main.py hmmsearch wrote nothing named slc.NEW.*" in capfd.readouterr().err
    assert core.family_done(cfg, {"slc.NEW"})["no_hits"] == {"slc.NEW"}


def test_search_hmm_dir_is_never_written(results_tree, tmp_path, monkeypatch):
    cfg, root = results_tree
    stage_project(tmp_path, monkeypatch)
    hmms = root / "hmms"
    hmms.mkdir()
    (hmms / "PF_N.hmm").write_text("HMMER3/f\n")
    cfg = dataclasses.replace(cfg, params={**cfg.params, "hmm_dir": str(hmms)})
    assert runner.run_one(cfg, "search", "slc.NEW", tmp_path / "work") == 0
    assert sorted(p.name for p in hmms.iterdir()) == ["PF_N.hmm"]       # fetched.hmm went to the copy
    assert "--hmm_dir hmm_dir.work" in (tmp_path / "args.txt").read_text()


def _cluster_cfg(results_tree, domains: str):
    cfg, _ = results_tree
    cfg = dataclasses.replace(cfg, params={**cfg.params, "min_seqs": 5, "min_distinct": 4})
    (cfg.outdir / "search").mkdir(exist_ok=True)
    (cfg.outdir / "search/slc.NEW.domains.fasta").write_text(domains)
    return cfg


def test_cluster_drops_small_hgs_keeps_full_tsv(results_tree, tmp_path, monkeypatch, capfd):
    cfg = _cluster_cfg(results_tree, DOMAINS)
    stage_project(tmp_path, monkeypatch)
    order = _spy_replace(monkeypatch)
    assert runner.run_one(cfg, "cluster", "slc.NEW", tmp_path / "work") == 0
    assert "slc.NEW: skipped 3 HGs below min_seqs/min_distinct (5/4); kept 1" in capfd.readouterr().out
    assert order == ["slc.NEW.HG3.fasta", "slc.NEW_cluster.tsv"]          # marker last
    clu = cfg.outdir / "clusters"
    tsv = (clu / "slc.NEW_cluster.tsv").read_text().splitlines()
    assert len(tsv) == 15 and sorted({l.split("\t")[0] for l in tsv}) == ["HG1", "HG2", "HG3", "HG4"]
    assert sorted(p.name for p in clu.glob("slc.NEW.HG*.fasta")) == ["slc.NEW.HG3.fasta"]
    assert (clu / "slc.NEW.HG3.fasta").read_text().count(">") == 5
    # step2 sees exactly the files on disk
    assert {h for h in core.expected(cfg) if h.startswith("slc.NEW.")} == {"slc.NEW.HG3"}
    assert [h for h in cli_mod._missing(cfg, "align", None) if h.startswith("slc.NEW.")] == ["slc.NEW.HG3"]


def test_cluster_all_small_publishes_tsv_only(results_tree, tmp_path, monkeypatch):
    cfg = _cluster_cfg(results_tree, DOMAINS.split(">c1")[0])                  # HG1 + HG2 only
    stage_project(tmp_path, monkeypatch)
    assert runner.run_one(cfg, "cluster", "slc.NEW", tmp_path / "work") == 0
    assert (cfg.outdir / "clusters/slc.NEW_cluster.tsv").is_file()
    assert not list((cfg.outdir / "clusters").glob("slc.NEW.HG*.fasta"))
    assert core.family_done(cfg, {"slc.NEW"})["cluster"] == {"slc.NEW"}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest phylocli/tests/test_step1.py -q -p no:cacheprovider -k "stage_env or search_ or cluster_"`
Expected: FAIL — `env["hmm_dir"] == "None"`, and `bash: .../phylocli/stages/search.sh: No such file or directory` (rc 127).

- [ ] **Step 3: `stage_env`** — in `phylocli/runner.py` replace

```python
        env[str(k)] = ("true" if v else "false") if isinstance(v, bool) else str(v)
```

with

```python
        if isinstance(v, bool):
            env[str(k)] = "true" if v else "false"
        else:
            env[str(k)] = "" if v is None else str(v)       # hmm_dir: null -> "" (not "None")
```

- [ ] **Step 4: `phylocli/stages/search.sh`**

```bash
#!/usr/bin/env bash
# step1.nf SEARCH, one family. Args: GENEFAM INFASTA [HMM_DIR]. Env: ID=<pref>.<family>, CPUS,
# PROJECT_DIR, pfam_db, domain_expand.
set -euo pipefail
export PYTHONNOUSERSITE=1
GENEFAM="$1"
INFASTA="$2"
HMMDIR="${3:-}"
PREF="${ID%%.*}"
FAMILY="${ID#*.}"

# helper/hmmsearch.py fetches every model missing from --hmm_dir INTO that directory. Work on a
# copy so the configured directory is never written (step1.nf got this from stageInMode 'copy';
# phylocli symlinks its inputs and runs many families at once).
if [[ -n "${HMMDIR}" ]]; then
    rm -rf hmm_dir.work
    cp -rL "${HMMDIR}" hmm_dir.work
    HMMDIR=hmm_dir.work
fi

echo "Running hmmsearch for ${FAMILY}"

python ${PROJECT_DIR}/phylogeny/main.py hmmsearch \
	-f ${INFASTA} \
	-g ${GENEFAM} \
	${FAMILY} \
	-o . \
	--pfam_db ${pfam_db} \
	${HMMDIR:+--hmm_dir ${HMMDIR}} \
	--domain_expand ${domain_expand} \
	--ncpu ${CPUS}

# main.py hmmsearch looks the family up by NAME (column 1; the last row wins) and names its
# outputs after THAT row's prefix; for a name it cannot find it logs an error and exits 0. Either
# way nothing named ${ID}.* exists here, and the touches below publish an empty "no hits" result
# (measured: rbp.CSD, whose hits were written as tfs.CSD.*). Kept as step1.nf does it (decided by
# Grygoriy 09/10/2026: warning, not failure) -- but say so.
if ! compgen -G "${ID}.*" > /dev/null; then
    other=""
    for f in *."${FAMILY}".genes.list; do
        [[ -e "$f" ]] || continue
        other+="${other:+, }${f%.genes.list}.*"
    done
    if [[ -n "$other" ]]; then
        echo "WARNING: family name ${FAMILY} is listed under more than one prefix in ${GENEFAM};" \
             "hmmsearch keys rows by name, so ${ID}'s hits are written as ${other} and ${ID}" \
             "is published empty (looks like \"no hits\")" >&2
    else
        echo "WARNING: main.py hmmsearch wrote nothing named ${ID}.* (family ${FAMILY} not found" \
             "in ${GENEFAM}?); ${ID} is published empty (looks like \"no hits\")" >&2
    fi
fi

touch ${ID}.domains.fasta
touch ${ID}.domains.csv
touch ${ID}.domains_ummerged.csv
touch ${ID}.genes.list
```

- [ ] **Step 5: `phylocli/stages/cluster.sh`**

```bash
#!/usr/bin/env bash
# step1.nf CLUSTER, one family. Arg: DOMAINS_FASTA. Env: ID=<pref>.<family>, CPUS, PROJECT_DIR,
# max_n, s2_inflation, min_seqs, min_distinct.
set -euo pipefail
export PYTHONNOUSERSITE=1
DOMAINS="$1"

echo "Clustering: ${DOMAINS}"

python ${PROJECT_DIR}/phylogeny/main.py cluster \
	-f ${DOMAINS} \
	--out_file ${ID}_cluster.tsv \
	-c ${CPUS} \
	-m ${max_n} \
	-i ${s2_inflation}

# (step1.nf named the loop variable ID; renamed HG here, ID is the family id)
samtools faidx ${DOMAINS}
while read -r HG; do
	[ -n "$HG" ] || continue
	xargs samtools faidx ${DOMAINS} < <(awk -v ID="$HG" '$1==ID { print $2 }' ${ID}_cluster.tsv) > ${ID}.${HG}.fasta
done < <(cut -f 1 ${ID}_cluster.tsv | sort -u)

# Guarantee structural outputs
touch ${ID}_cluster.tsv

# Small HGs are not written (spec, 08/10/2026): delete the HG FASTAs step2 would skip, by the
# rule report_status.expected_hgs uses. ${ID}_cluster.tsv stays complete (every HG and member).
python ${PROJECT_DIR}/workflow/drop_small_hgs.py ${ID} ${min_seqs} ${min_distinct}
```

- [ ] **Step 6: `workflow/drop_small_hgs.py`**

```python
#!/usr/bin/env python3
"""Delete the <ID>.HG*.fasta files in the current directory that step2 would skip.

Called by phylocli/stages/cluster.sh after the HG FASTAs are written and BEFORE anything is
published (phylocli and step1.nf CLUSTER alike): an HG is kept only with >= MIN_SEQS sequences
and >= MIN_DISTINCT distinct ones -- report_status.passes, the rule expected_hgs applies -- so
step1 and step2 can never disagree. <ID>_cluster.tsv is not touched: it stays the complete MCL
membership record, and HG numbering keeps its gaps.

Usage:  drop_small_hgs.py ID MIN_SEQS MIN_DISTINCT
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_status  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        sys.exit(__doc__.strip().splitlines()[-1])
    fam, min_seqs, min_distinct = argv[1], int(argv[2]), int(argv[3])
    files = sorted(glob.glob(glob.escape(fam) + ".HG*.fasta"))
    small = [f for f in files if not report_status.passes(f, min_seqs, min_distinct)]
    for f in small:
        os.remove(f)
    print(f"{fam}: skipped {len(small)} HGs below min_seqs/min_distinct "
          f"({min_seqs}/{min_distinct}); kept {len(files) - len(small)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 7: Run the new tests, then both suites**

Run: `python3 -m pytest phylocli/tests/test_step1.py -q -p no:cacheprovider` → all pass.
Run both Global-Constraints commands → `217 passed` on both.

- [ ] **Step 8: Commit**

```bash
git add phylocli/stages/search.sh phylocli/stages/cluster.sh workflow/drop_small_hgs.py \
        phylocli/runner.py phylocli/tests/test_step1.py
git commit -m "phylocli step1: stages/search.sh + cluster.sh (step1.nf bodies), small HGs not written, hmm_dir never written, unresolvable family warns

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Data layer — history, family rows, `select` / `plan`, preflight, genefam snapshot

**Files:**
- Modify: `phylocli/history.py` (`PROC_STAGE`, `nf_runs`, `_nf_rows`, `_nextflow_attempts`, `_phylocli_attempts`; new `family_attempts`)
- Modify: `phylocli/model.py` (`live`, `StageRow`, `stage_rows`, `hg_rows`, `select`, `plan`, `TOOLS`, `preflight`, `write_run`)
- Test: `phylocli/tests/test_step1.py`

**Interfaces:**
- Consumes: Task 1-2 `core.*`; Task 2 `step1_outputs`, `step1_tools`
- Produces:
  - `history.PROC_STAGE["SEARCH"] == "search"`, `["CLUSTER"] == "cluster"`
  - `history.nf_runs(nextflow_dir, script="step2.nf")`
  - `history.family_attempts(cfg, fam: str | None = None, warn=None) -> list[Attempt]` (step1.nf Nextflow runs + phylocli `search`/`cluster` runs; `Attempt.hg` = family id); `history.attempts` is unchanged (step2 only)
  - `model.StageRow` gains `no_hits: int = 0`
  - `model.family_states(cfg, fams, lv: dict) -> dict` — `{"search"|"cluster": {family id: 0 done / 1 running / 2 ready / 3 blocked}}` from output files + squeue only; `{}` for no families. The ONE family-state function: the CLI summary rows and the overview cells both count it (as `stage_states` is for HGs)
  - `model.fam_group_key(fam, by) -> str` — `category`: first id part; `family`: the family id itself
  - `model.GroupRow` gains `n_fams: int = 0`
  - `model.group_rows(cfg, exp, by="category", done=None, lv=None, states=None, fams=None, fstates=None)` — with `fams`, the `search`/`cluster` cells count FAMILIES (ALL = all families, a category row = that category's families, a family row = that family) and groups that have families but no HG get a row; `GroupRow.total` stays the HG count. Without `fams`: exactly as at `446c599` (search/cluster cells `None`)
  - `model.stage_rows(cfg, exp, fams: set | None = None)` — `fams` non-empty: `search`, `cluster` rows first, counted from `family_states`
  - `model.hg_rows(cfg, stage, ...)` — family stages return one `HGRow` per family (`hg` = family id); default attempts = `history.family_attempts`
  - `model.select` / `model.plan` accept family ids for family stages; duplicates proceed (a warning, printed by the CLI / TUI); a missing genefam file → `ModelError(code=1)`
  - `model.TOOLS["search"] == ["hmmsearch", "hmmfetch", "bedtools"]`, `["cluster"] == ["samtools", "diamond", "mcl"]`
  - `model.preflight(stage, cfg=None) -> str | None` (with `cfg`, search also checks `genefam_info`, `infasta`, `pfam_db` files and `hmm_dir`)
  - `model.write_run` for `search`: copies the genefam file to `<run_dir>/genefam.csv` and records that path as `params.genefam_info` in the run's `config.yaml`; the caller's `raw` is not mutated

- [ ] **Step 1: Write the failing tests** — add to the imports at the top of `phylocli/tests/test_step1.py`:

```python
from phylocli.tests.test_history import hist  # noqa: E402,F401  (fixture)
```

and append:

```python
# ---- Task 4: data layer ------------------------------------------------------------------

S1_LOG = ("SEARCH\ttfs.A\tFAILED\t137\t1\t4\t500 MB\t5m\t-\t2m\t/w/s1/1\t2026-09-20 10:01:00.000\n"
          "SEARCH\ttfs.A\tCOMPLETED\t0\t2\t4\t1 GB\t15m\t300 MB\t3m\t/w/s1/2\t2026-09-20 10:05:00.000\n"
          "CLUSTER\ttfs.A\tCOMPLETED\t0\t1\t4\t300 MB\t10m\t100 MB\t1m\t/w/s1/3\t2026-09-20 10:10:00.000\n"
          "CLUSTER\ttfs.ZZ\tCOMPLETED\t0\t1\t4\t300 MB\t10m\t100 MB\t1m\t/w/s1/4\t2026-09-20 10:11:00.000\n")
SACCT_S1 = ("12345_0|OUT_OF_MEMORY||00:03:00|0:125\\n12345_0.batch|OUT_OF_MEMORY|512000K|00:03:00|0:125\\n"
            "12345_1|COMPLETED||00:01:00|0:0\\n")


def test_family_attempts_read_step1_runs(hist):
    _cli, cfg, _calls, tmp = hist
    (tmp / "nflog/run_s1.tsv").write_text(S1_LOG)
    atts = history.family_attempts(cfg, "tfs.A")
    assert [(a.stage, a.attempt, a.status, a.run) for a in atts] == [
        ("search", 1, "FAILED", "run_s1"), ("search", 2, "COMPLETED", "run_s1"),
        ("cluster", 1, "COMPLETED", "run_s1")]
    assert history.latest_by_stage(atts)["search"].mem == "1 GB"
    assert not any(a.hg == "tfs.ZZ" for a in history.family_attempts(cfg))   # not in the genefam file
    assert all(a.stage in core.HG_STAGES for a in history.attempts(cfg))     # step2 history unchanged


def test_live_family_tags(cli, monkeypatch):
    monkeypatch.setenv("FAKE_SQUEUE", "999|nf-SEARCH_(slc.NEW)\n998|nf-CLUSTER_(tfs.C_x)\n")
    assert model.live(set()) == {"search": {"slc.NEW"}, "cluster": {"tfs.C_x"}}


def test_stage_rows_with_families(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    rows, _known, _d = model.stage_rows(_cfg(), core.expected(_cfg()), FAMS)
    assert [r.stage for r in rows] == core.STAGES
    by = {r.stage: r for r in rows}
    assert (by["search"].done, by["search"].ready, by["search"].blocked, by["search"].total) == (3, 2, 0, 5)
    assert (by["cluster"].done, by["cluster"].ready, by["cluster"].blocked, by["cluster"].no_hits) == \
        (2, 1, 2, 1)
    assert [r.stage for r in model.stage_rows(_cfg(), core.expected(_cfg()))[0]] == core.HG_STAGES


def test_family_states(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    fs = model.family_states(_cfg(), FAMS, {})
    assert fs["search"] == {"tfs.A": 0, "tfs.B": 0, "tfs.C_x": 0, "slc.NEW": 2, "cal.Trail": 2}
    assert fs["cluster"] == {"tfs.A": 0, "tfs.B": 0, "tfs.C_x": 2, "slc.NEW": 3, "cal.Trail": 3}
    assert model.family_states(_cfg(), FAMS, {"search": {"slc.NEW"}})["search"]["slc.NEW"] == 1
    assert model.family_states(_cfg(), set(), {}) == {}


def test_group_rows_with_families(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    exp = core.expected(_cfg())
    rows, _k = model.group_rows(_cfg(), exp, "category", fams=FAMS)
    by = {r.group: r for r in rows}
    assert list(by) == ["ALL", "tfs", "cal", "slc"]            # cal, slc: families, no HG yet
    srows = {s.stage: s for s in model.stage_rows(_cfg(), exp, FAMS)[0]}
    for st in core.STAGES:                                     # ALL == the CLI summary, all 8 stages
        s = srows[st]
        assert by["ALL"].per_stage[st] == (s.done, s.running, s.ready, s.blocked)
    assert (by["ALL"].total, by["ALL"].n_fams) == (3, 5)
    assert (by["tfs"].total, by["tfs"].n_fams, by["tfs"].per_stage["search"]) == (3, 3, (3, 0, 0, 0))
    assert (by["slc"].total, by["slc"].per_stage["search"], by["slc"].per_stage["align"]) == \
        (0, (0, 0, 1, 0), (0, 0, 0, 0))
    fam = {r.group: r for r in model.group_rows(_cfg(), exp, "family", fams=FAMS)[0]}
    assert list(fam) == ["ALL", "tfs.A", "tfs.C_x", "cal.Trail", "slc.NEW", "tfs.B"]
    assert (fam["tfs.B"].total, fam["tfs.B"].per_stage["cluster"]) == (0, (1, 0, 0, 0))   # no hits
    for st in core.FAMILY_STAGES:                              # family rows sum to ALL
        assert tuple(sum(r.per_stage[st][i] for g, r in fam.items() if g != "ALL")
                     for i in range(4)) == fam["ALL"].per_stage[st]


def test_select_and_plan_family_ids(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    sel = model.select(_cfg(), "cluster", ["slc.NEW", "tfs.C_x"])
    assert sel.selected == ["tfs.C_x"] and sel.notes == ["skipped 1 families without inputs"]
    assert model.plan(_cfg(), "cluster", sel).errors == {"output_exists": ["tfs.C_x"]}
    with pytest.raises(model.ModelError) as e:
        model.select(_cfg(), "search", ["slc.NOPE"])
    assert e.value.code == 2 and "unknown (1): slc.NOPE" in str(e.value)
    p = model.plan(_cfg(), "search", model.select(_cfg(), "search", ["slc.NEW"]))
    assert p.groups == [(core.Res(4, 500, 5, "normal", None), ["slc.NEW"])]
    assert p.notes == ["resources: step1 defaults for 1 families"]


def test_select_family_duplicates_proceed(cli, results_tree, tmp_path):
    _, root = results_tree
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "B\tPF_B\t1.1\t3\tGA\tTF\ttfs\n")
    sel = model.select(_cfg(), "search", ["slc.NEW", "tfs.B"])
    assert sel.selected == ["slc.NEW", "tfs.B"]
    gone = dataclasses.replace(_cfg(), params={**_cfg().params, "genefam_info": str(tmp_path / "x")})
    with pytest.raises(model.ModelError) as e:
        model.select(gone, "search", ["slc.NEW"])
    assert e.value.code == 1 and "genefam file not found" in str(e.value)


def test_preflight_family_tools_and_files(cli, results_tree, monkeypatch, tmp_path):
    cfg, _ = results_tree
    monkeypatch.setenv("PATH", str(_state["bin"]))
    assert "not on PATH: hmmsearch hmmfetch bedtools" in model.preflight("search", cfg)
    assert "not on PATH: samtools diamond mcl" in model.preflight("cluster", cfg)
    step1_tools()
    assert model.preflight("search", cfg) is None and model.preflight("cluster", cfg) is None
    gone = dataclasses.replace(cfg, params={**cfg.params, "pfam_db": str(tmp_path / "no.hmm")})
    assert model.preflight("search", gone) == f"ERROR: not found: pfam_db={tmp_path / 'no.hmm'}"
    assert model.preflight("align", gone) is None                  # HG stages: same checks as before


def test_write_run_search_snapshots_genefam(cli, results_tree):
    cfg, root = results_tree
    raw = _raw()
    before = copy.deepcopy(raw)
    p = model.plan(cfg, "search", model.Selection(["slc.NEW"], [], set()))
    w = model.write_run(cfg, raw, p, dry_run=True)
    snap = w.run_dir / "genefam.csv"
    src = root / "gene_families_searchinfo.csv"
    assert snap.read_text() == src.read_text()
    assert yaml.safe_load((w.run_dir / "config.yaml").read_text())["params"]["genefam_info"] == str(snap)
    assert raw == before                                           # the caller's raw is not changed
    src.write_text("")                                             # edited after the submission:
    assert core.family_ids(core.load_config(w.run_dir / "config.yaml")) == FAMS   # job reads the copy
    p = model.plan(cfg, "align", model.Selection(["tfs.C_x.HG1"], [], set()))
    w = model.write_run(cfg, _raw(), p, dry_run=True)
    assert not (w.run_dir / "genefam.csv").exists()               # HG stages: no snapshot
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest phylocli/tests/test_step1.py -q -p no:cacheprovider -k "family_attempts or live_family or stage_rows_with or family_states or group_rows_with or select_ or preflight_family or write_run_search"`
Expected: FAIL — `AttributeError: module 'phylocli.history' has no attribute 'family_attempts'`, `TypeError: stage_rows() takes 2 positional arguments but 3 were given`, `AttributeError: ... 'family_states'`, …

- [ ] **Step 3: history** — in `phylocli/history.py`:

replace

```python
PROC_STAGE = {"ALN": "align", "PHY": "tree", "PVM_PREV": "possvm_prev",
              "GR_watcher": "generax", "GXSUP": "gxsup", "PVM": "possvm"}
```

with

```python
PROC_STAGE = {"SEARCH": "search", "CLUSTER": "cluster",                       # step1.nf
              "ALN": "align", "PHY": "tree", "PVM_PREV": "possvm_prev",       # step2.nf
              "GR_watcher": "generax", "GXSUP": "gxsup", "PVM": "possvm"}
```

replace the `nf_runs` signature, docstring and filter

```python
def nf_runs(nextflow_dir: Path) -> list[tuple[str, str, bool]]:
    """(run name, start 'YYYY-mm-dd HH:MM:SS', final) for every step2.nf run; final = safe to
    cache (finished, or not the newest run)."""
```

```python
        if len(c) >= 7 and "step2.nf" in c[6]:
```

with

```python
def nf_runs(nextflow_dir: Path, script: str = "step2.nf") -> list[tuple[str, str, bool]]:
    """(run name, start 'YYYY-mm-dd HH:MM:SS', final) for every run of `script` (step2.nf: the HG
    stages; step1.nf: search / cluster); final = safe to cache (finished, or not the newest run)."""
```

```python
        if len(c) >= 7 and script in c[6]:
```

in `_nf_rows`: signature `def _nf_rows(cfg: core.Config, warn, script: str = "step2.nf") -> list[tuple[str, tuple]]:` and its loop `for run, started, finished in nf_runs(cfg.nextflow_dir, script):`.

in `_nextflow_attempts`: signature `def _nextflow_attempts(cfg: core.Config, hg: str | None, expected: set, warn, script: str = "step2.nf") -> list[Attempt]:` and loop `for run, r in _nf_rows(cfg, warn, script):`.

in `_phylocli_attempts`: signature `def _phylocli_attempts(hg: str | None, stages=None) -> list[Attempt]:`, first body line `stages = core.HG_STAGES if stages is None else stages`, and the filter (Task 2 made it `core.HG_STAGES`) becomes `if not m or m.group(7) not in stages:`.

add after `attempts`:

```python
def family_attempts(cfg: core.Config, fam: str | None = None, warn=None) -> list[Attempt]:
    """Every recorded search / cluster attempt, for one family if given, oldest first: step1.nf
    runs (processes SEARCH / CLUSTER, tag = <pref>.<family>) + phylocli runs of those stages.
    Kept apart from attempts() so `status HG` never starts nextflow for step1 runs."""
    warn = warn or (lambda _msg: None)
    fams = core.family_ids(cfg, strict=False)
    out = (_nextflow_attempts(cfg, fam, fams, warn, script="step1.nf")
           + _phylocli_attempts(fam, core.FAMILY_STAGES))
    return sorted(out, key=lambda a: (a.submitted, a.attempt, a.run))
```

- [ ] **Step 4: model — live, family_states, StageRow, stage_rows, group_rows, hg_rows** — in `phylocli/model.py`:

in `live`, replace

```python
            nf = nf_job(name)
            if nf:
                hg = history._resolve_tag(nf[1], expected)
                if hg:
                    out[history.PROC_STAGE[nf[0]]].add(hg)
```

with

```python
            nf = nf_job(name)
            if nf:
                st = history.PROC_STAGE[nf[0]]
                # step1 tags are the family id itself; step2 tags may carry a prefix (pre_<id>)
                hg = nf[1] if st in core.FAMILY_STAGES else history._resolve_tag(nf[1], expected)
                if hg:
                    out[st].add(hg)
```

in `StageRow` add a last field `no_hits: int = 0` (after `total: int = 0`).

add before `stage_rows` (after `StageRow`):

```python
def family_states(cfg: core.Config, fams, lv: dict) -> dict:
    """search / cluster -> family id -> 0 done / 1 running / 2 ready / 3 blocked, from output
    files and squeue only (no history), like stage_states() for HGs. The one family-state code
    path: the CLI summary rows (stage_rows) and the TUI overview cells (group_rows) count it."""
    fams = set(fams)
    if not fams:
        return {}
    fd = core.family_done(cfg, fams)
    out: dict[str, dict[str, int]] = {}
    for st in core.FAMILY_STAGES:
        d = fd[st]
        todo = fams - d
        running = todo & lv.get(st, set())
        ready = core.ready_set(cfg, st, todo - running)
        out[st] = {f: (0 if f in d else 1 if f in running else 2 if f in ready else 3)
                   for f in fams}
    return out
```

replace the head of `stage_rows` (signature through the `for st in core.STAGES:` line, which Task 2 made `core.HG_STAGES`) so the function reads

```python
def stage_rows(cfg: core.Config, exp: set[str], fams: set | None = None):
    """(rows, live_known, done-by-stage) — exactly the counts `phylo status` draws. `fams` (family
    ids) puts the search / cluster rows first, counted in families from family_states (cluster
    also reports the no-hits families); None or empty: HG stages only. done-by-stage is the HG
    stages' dict."""
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)
    lv = live(core.expected(cfg))
    known = lv is not None
    lv = lv or {}
    rows = []
    if fams:
        fs = family_states(cfg, fams, lv)
        no_hits = len(core.family_done(cfg, fams)["no_hits"])
        for st in core.FAMILY_STAGES:
            c = [0, 0, 0, 0]
            for v in fs[st].values():
                c[v] += 1
            rows.append(StageRow(st, True, c[0], c[1], c[2], c[3], len(fams),
                                 no_hits if st == "cluster" else 0))
    for st in core.HG_STAGES:
        if not core.applicable(cfg, st):
            rows.append(StageRow(st, False))
            continue
        todo = exp - done[st]
        running = todo & lv.get(st, set())
        n_ready = len(core.ready_set(cfg, st, todo - running))
        rows.append(StageRow(st, True, len(done[st]), len(running), n_ready,
                             len(todo) - len(running) - n_ready, len(exp)))
    return rows, known, done
```

replace `hg_rows` with

```python
def _state_rows(ids, done, busy, ready, latest) -> list[HGRow]:
    rows = []
    for hg in sorted(ids):
        a = latest.get(hg)
        if hg in done:
            state = "done"
        elif hg in busy:
            state = "running"
        elif hg in ready:
            state = "failed" if a is not None and a.status in FAILED_STATES else "ready"
        else:
            state = "blocked"
        rows.append(HGRow(hg, state, a))
    return rows


def hg_rows(cfg: core.Config, stage: str, exp: set[str] | None = None,
            atts: list | None = None, done_map: dict | None = None,
            live_map: dict | None = None) -> list[HGRow]:
    """One row per expected HG for `stage`. failed = inputs present, not done, not queued,
    and the latest attempt at this stage ended in a FAILED_STATES state.
    `done_map` / `live_map` (stage -> ids) let a caller that builds several stages compute
    them once; when omitted they are computed here (squeue is called).
    search / cluster: one row per family (`hg` = family id); `exp` and `done_map` are not used,
    and `atts` should be history.family_attempts() (the default)."""
    if stage in core.FAMILY_STAGES:
        fams = core.family_ids(cfg, strict=False)
        done = core.family_done(cfg, fams)[stage]
        busy = (live_map if live_map is not None else (live(set()) or {})).get(stage, set())
        ready = core.ready_set(cfg, stage, fams - done - busy)
        latest = _latest_for(history.family_attempts(cfg) if atts is None else atts, stage)
        return _state_rows(fams, done, busy, ready, latest)
    exp = core.expected(cfg) if exp is None else exp
    done = (done_map if done_map is not None
            else core.report_status.done_by_stage(str(cfg.outdir), exp))[stage]
    busy = (live_map if live_map is not None
            else (live(core.expected(cfg)) or {})).get(stage, set())
    todo = exp - done
    ready = core.ready_set(cfg, stage, todo - busy)
    latest = _latest_for(history.attempts(cfg) if atts is None else atts, stage)
    return _state_rows(exp, done, busy, ready, latest)
```

add after `group_key`:

```python
def fam_group_key(fam: str, by: str) -> str:
    """Group of a FAMILY id (search / cluster rows): category = first id part (slc); family = the
    family id itself (slc.SLC25) -- an HG's family group (group_key(hg, "family")) is the same."""
    return fam.split(".", 1)[0] if by == "category" else fam
```

in `GroupRow` add a last field `n_fams: int = 0` (after `per_stage: dict`).

replace `group_rows` with

```python
def group_rows(cfg: core.Config, exp: set[str], by: str = "category",
               done: dict | None = None, lv: dict | None = None, states: dict | None = None,
               fams: set | None = None, fstates: dict | None = None):
    """(rows, squeue_known): per-group done/running/ready/blocked per stage, from output files
    and squeue only (no attempt history). rows[0] is ALL and equals stage_rows().
    `states` (from stage_states) makes this pure in-memory counting.
    `fams` (family ids) fills the search / cluster cells, counted in FAMILIES: ALL = all
    families, a category row = that category's families, a family row = that one family; a group
    with families but no HG yet (a new genefam row) gets a row too. `fstates` (from
    family_states) keeps that in-memory as well. GroupRow.total stays the HG count, .n_fams the
    families. Without `fams` the search / cluster cells are None (as for a non-applicable stage)."""
    known = True
    fams = set(fams or ())
    if states is None or (fams and fstates is None):
        if lv is None:
            lv = live(exp)
            known = lv is not None
            lv = lv or {}
        if states is None:
            done = core.report_status.done_by_stage(str(cfg.outdir), exp) if done is None else done
            states = stage_states(cfg, exp, done, lv)
        if fams and fstates is None:
            fstates = family_states(cfg, fams, lv)
    fstates = fstates or {}
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for hg in exp:
        groups[group_key(hg, by)].append(hg)
    fgroups: dict[str, list[str]] = collections.defaultdict(list)
    for f in fams:
        fgroups[fam_group_key(f, by)].append(f)

    def row(name: str, hgs, fs) -> GroupRow:
        per = {}
        for st in core.STAGES:
            src, ids = (fstates, fs) if st in core.FAMILY_STAGES else (states, hgs)
            if st not in src:
                per[st] = None
                continue
            c = [0, 0, 0, 0]
            for i in ids:
                c[src[st][i]] += 1
            per[st] = tuple(c)
        return GroupRow(name, len(hgs), per, len(fs))

    names = sorted(set(groups) | set(fgroups), key=lambda g: (-len(groups.get(g, ())), g))
    rows = [row("ALL", exp, fams)] + [row(g, groups.get(g, []), fgroups.get(g, [])) for g in names]
    return rows, known
```

(Without `fams`: same rows, same order, same `known` as before — `test_group_rows_*` pin it. A family-only group has 0 HGs, so it sorts after every group with HGs, by name.)

- [ ] **Step 5: model — TOOLS and preflight** — replace

```python
TOOLS = {"align": ["mafft", "clipkit"], "tree": ["iqtree2"], "generax": ["generax", "mpirun"],
         "gxsup": ["iqtree2"], "possvm": [], "possvm_prev": []}
```

with

```python
# search: main.py hmmsearch -> helper/hmmsearch.py runs hmmfetch, hmmsearch, bedtools;
# cluster: main.py cluster -> helper/functions.py cluster runs diamond, mcl; cluster.sh: samtools.
TOOLS = {"search": ["hmmsearch", "hmmfetch", "bedtools"], "cluster": ["samtools", "diamond", "mcl"],
         "align": ["mafft", "clipkit"], "tree": ["iqtree2"], "generax": ["generax", "mpirun"],
         "gxsup": ["iqtree2"], "possvm": [], "possvm_prev": []}
```

replace `preflight` with

```python
def _missing_files(stage: str, cfg: "core.Config | None") -> list[str]:
    """search reads these by their configured paths (pfam_db is passed as a path, not staged)."""
    if cfg is None or stage != "search":
        return []
    out = [f"{k}={cfg.params.get(k)}" for k in ("genefam_info", "infasta", "pfam_db")
           if not cfg.params.get(k) or not Path(cfg.params[k]).is_file()]
    h = cfg.params.get("hmm_dir")
    if h and not Path(h).is_dir():
        out.append(f"hmm_dir={h}")
    return out


def preflight(stage: str, cfg: "core.Config | None" = None) -> str | None:
    lost = [t for t in TOOLS[stage] if shutil.which(t) is None]
    files = _missing_files(stage, cfg)
    hint = ("       run 'conda activate phylo' and 'module load OpenMPI' before submitting;\n"
            "       see workflow/environment.yaml.")
    py_err = None
    if stage != "gxsup":  # same `python` + PYTHONNOUSERSITE=1 as the stage scripts
        py = shutil.which("python")
        if py is None:
            py_err = "python: not on PATH"
        else:
            r = subprocess.run([py, "-c", "import ete3, Bio, yaml"], capture_output=True, text=True,
                               env={**os.environ, "PYTHONNOUSERSITE": "1"})
            if r.returncode != 0:
                py_err = (f"{py} (PYTHONNOUSERSITE=1) cannot import ete3, Bio, yaml:\n"
                          f"       {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'exit ' + str(r.returncode)}")
    if not (lost or py_err):
        return f"ERROR: not found: {' '.join(files)}" if files else None
    msg = "ERROR:"
    if lost:
        msg += f" not on PATH: {' '.join(lost)}"
    if py_err:
        msg += f"\n       {py_err}"
    if files:
        msg += f"\n       not found: {' '.join(files)}"
    return msg + "\n" + hint
```

(For the six HG stages `files` is always empty, so the messages are unchanged.)

- [ ] **Step 6: model — select, plan, write_run** — in `select` replace

```python
    exp = core.expected(cfg)
    unknown = sorted(set(hgs) - exp)
```

with

```python
    family = stage in core.FAMILY_STAGES
    if family:
        try:
            exp = core.family_ids(cfg)
        except core.FamilyError as e:
            raise ModelError(str(e), 1) from None
    else:
        exp = core.expected(cfg)
    unknown = sorted(set(hgs) - exp)
```

and replace

```python
    if not all_:
        unready = [hg for hg in selected if not core.inputs_ready(cfg, stage, hg)]
        busy = [hg for hg in selected if hg in queued and hg not in unready]
        if unready:
            notes.append(f"skipped {len(unready)} HGs without inputs")
        if busy:
            notes.append(f"skipped {len(busy)} HGs already queued")
```

with

```python
    if not all_:
        if family:                         # one listing for all families, not one per id
            ok = core.ready_set(cfg, stage, selected)
            unready = [hg for hg in selected if hg not in ok]
        else:
            unready = [hg for hg in selected if not core.inputs_ready(cfg, stage, hg)]
        busy = [hg for hg in selected if hg in queued and hg not in unready]
        unit = core.unit(stage)
        if unready:
            notes.append(f"skipped {len(unready)} {unit} without inputs")
        if busy:
            notes.append(f"skipped {len(busy)} {unit} already queued")
```

in `plan` replace

```python
    errs = core.validate(cfg, stage, sel.selected, sel.queued)
    bad = {k: v for k, v in errs.items() if v}
    notes = list(sel.notes)
    if bad:
        return Plan(stage, [], notes, bad)
    n_rows = core.resources_rows(cfg, sel.selected)
    over_flags = list(over_flags)
    notes.append(f"resources.tsv: row found for {n_rows} of {len(sel.selected)} HGs"
                 + (" (others: step2 defaults)" if n_rows < len(sel.selected) else "")
                 + (f"; overridden by {' '.join(over_flags)}" if over_flags else ""))
```

with

```python
    try:
        errs = core.validate(cfg, stage, sel.selected, sel.queued)
    except core.FamilyError as e:
        raise ModelError(str(e), 1) from None
    bad = {k: v for k, v in errs.items() if v}
    notes = list(sel.notes)
    if bad:
        return Plan(stage, [], notes, bad)
    over_flags = list(over_flags)
    over = f"; overridden by {' '.join(over_flags)}" if over_flags else ""
    if stage in core.FAMILY_STAGES:                  # family ids never have resources.tsv rows
        notes.append(f"resources: step1 defaults for {len(sel.selected)} families{over}")
    else:
        n_rows = core.resources_rows(cfg, sel.selected)
        notes.append(f"resources.tsv: row found for {n_rows} of {len(sel.selected)} HGs"
                     + (" (others: step2 defaults)" if n_rows < len(sel.selected) else "") + over)
```

in `write_run` replace

```python
    import yaml
    run_dir = new_run_dir(p.stage, dry_run)
    (run_dir / "config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
```

with

```python
    import copy
    import yaml
    run_dir = new_run_dir(p.stage, dry_run)
    if p.stage == "search":
        # main.py hmmsearch reads the family's row at run time: the jobs read a copy taken now
        # (the file the ids were validated against), and the run keeps it as the record.
        raw = copy.deepcopy(raw)
        snap = run_dir / "genefam.csv"
        shutil.copy2(cfg.params["genefam_info"], snap)
        raw.setdefault("params", {})["genefam_info"] = str(snap)
    (run_dir / "config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
```

(The copy is named `genefam.csv`, the name step1.nf stages it under, so `-g genefam.csv` is identical in both.)

- [ ] **Step 7: Run both suites** — Expected: `226 passed` on both (`test_status_hg_history` still counts 8 rows: `attempts()` ignores step1 runs).

- [ ] **Step 8: Commit**

```bash
git add phylocli/history.py phylocli/model.py phylocli/tests/test_step1.py
git commit -m "phylocli step1: model rows/select/plan for family ids, SEARCH/CLUSTER history, step1 preflight, genefam snapshot per run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: CLI — `missing` / `status` / `submit` for family stages

**Files:**
- Modify: `phylocli/phylo.py` (`_check_stage`, new `_families` / `_missing_fams`, `_summary`, `_hg_status` → `_print_history` / `_print_latest` / `_family_status`, `status`, `missing`, `_preflight`, `_print_dry_run`, `submit`)
- Test: `phylocli/tests/test_step1.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4
- Produces (CLI behaviour):
  - `missing` / `status` summary: header, then `search`, `cluster` (cluster row ends `  <k> no hits`), a blank line, then the HG rows exactly as before. Family rows are printed only when at least one family is selected (so `--ids` with only HG ids prints what it printed before). Before the table, every `core.family_warnings(cfg)` line (duplicate ids; family names under two prefixes) on stderr; exit code unchanged.
  - `--fam X` on a summary fails (`no HGs match --fam X`, exit 1) only when neither an HG nor a family matches.
  - `missing search|cluster [--ids F] [-f P] [--all]` prints family ids; `--per-fam` → exit 2; no match → `no families match --fam P`, exit 1; genefam file missing → exit 1 with the message; duplicate ids → the duplicate warning on stderr, then the ids (never an error).
  - `status FAMILY [--history]`: the duplicate warning (if any) on stderr, then `FAMILY  (<n> HGs)`, then rows `search`, `cluster` (cluster done shows `done (no hits)` for a no-hits family) with the latest attempt, then `log (<stage>): ...` lines.
  - `submit search|cluster`: the duplicate warning (`search` also the name-collision warnings) on stderr first; notes / dry-run panel / "submitted ..." say `families`; `no families match --fam P`; preflight with files.
  - `_warn_families(cfg, collisions: bool)` prints `core.family_warnings(cfg, collisions)` to stderr
  - `_preflight(stage, cfg=None)`, `_missing_fams(cfg, stage, ids, ready=False, fam=None) -> list[str]`

- [ ] **Step 1: Write the failing tests** — append to `phylocli/tests/test_step1.py`:

```python
# ---- Task 5: CLI -----------------------------------------------------------------------------

def test_summary_family_rows_first(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    out = cli(["missing"]).output.splitlines()
    assert [l.split()[0] if l.strip() else "" for l in out][:5] == ["stage", "search", "cluster", "", "align"]
    rows = {l.split()[0]: l.split()[1:6] for l in out[1:] if l.strip()}
    assert rows["search"] == ["3", "0", "2", "0", "5"]            # done running ready blocked total
    assert rows["cluster"] == ["2", "0", "1", "2", "5"]
    assert out[2].rstrip().endswith("  1 no hits")
    assert rows["align"] == ["1", "0", "2", "0", "3"]             # HG rows: same numbers as before


def test_status_ids_of_hgs_has_no_family_rows(cli, tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("tfs.A.HG1\n")
    lines = cli(["status", "--ids", str(f)]).output.splitlines()
    assert lines[0].split()[0] == "stage" and lines[1].split()[0] == "align"


def test_status_fam_matching_only_families(cli):
    r = cli(["status", "-f", "slc"])
    assert r.exit_code == 0, r.output
    line = next(l for l in r.output.splitlines() if l.split()[:1] == ["search"])
    assert line.split()[1:6] == ["0", "0", "1", "0", "1"]
    assert cli(["status", "-f", "nope"]).exit_code == 1


def test_missing_family_stages(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    assert cli(["missing", "search"]).output.split() == ["cal.Trail", "slc.NEW"]
    assert cli(["missing", "cluster"]).output.split() == ["tfs.C_x"]
    assert cli(["missing", "cluster", "--all"]).output.split() == ["cal.Trail", "slc.NEW", "tfs.C_x"]
    assert cli(["missing", "search", "-f", "slc"]).output.split() == ["slc.NEW"]
    r = cli(["missing", "search", "-f", "tfs.C"])
    assert r.exit_code == 1 and "no families match --fam tfs.C" in r.output
    r = cli(["missing", "cluster", "--per-fam"])
    assert r.exit_code == 2 and "--per-fam" in r.output


def test_missing_search_skips_queued(cli, monkeypatch):
    monkeypatch.setenv("FAKE_SQUEUE", "999|nf-SEARCH_(slc.NEW)\n")
    assert "slc.NEW" not in cli(["missing", "search"]).output.split()
    assert "slc.NEW" in cli(["missing", "search", "--all"]).output.split()


def test_submit_search_missing_dry_run(cli, results_tree):
    cfg, root = results_tree
    step1_outputs(cfg.outdir)
    step1_tools()
    r = cli(["submit", "search", "--missing", "-n"])
    assert r.exit_code == 0, r.output
    assert "families 2 in 1 array(s)" in " ".join(r.output.split())
    assert "resources: step1 defaults for 2 families" in r.output
    run = next(dry_dir().glob("*_search"))
    assert (run / "ids_0.txt").read_text().split() == ["cal.Trail", "slc.NEW"]
    s = (run / "array_0.sbatch").read_text()
    assert "#SBATCH --cpus-per-task=4" in s and "#SBATCH --mem=500M" in s and "#SBATCH --time=5\n" in s
    assert (run / "genefam.csv").read_text() == (root / "gene_families_searchinfo.csv").read_text()
    assert not calls_txt().exists()


def test_submit_cluster_overrides(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    (cfg.outdir / "search/slc.NEW.domains.fasta").write_text(">n\nMK\n")
    step1_tools()
    r = cli(["submit", "cluster", "slc.NEW", "-n", "--mem", "2G", "--time", "1h"])
    assert r.exit_code == 0, r.output
    s = next(dry_dir().glob("*_cluster")).joinpath("array_0.sbatch").read_text()
    assert "#SBATCH --mem=2048M" in s and "#SBATCH --time=60\n" in s and "#SBATCH --cpus-per-task=4" in s


def test_submit_search_real(cli):
    step1_tools()
    r = cli(["submit", "search", "slc.NEW"])
    assert r.exit_code == 0, r.output
    assert "submitted 12345: 1 families (4 cpus, 500M, 5 min)" in r.output
    run = next(runs_dir().glob("*_search"))
    assert yaml.safe_load((run / "config.yaml").read_text())["params"]["genefam_info"] == \
        str(run / "genefam.csv")
    assert any(l.split()[1:3] == ["search", "12345"] for l in cli(["jobs"]).output.splitlines()
               if len(l.split()) > 2)


def test_family_rows_states(cli, results_tree, monkeypatch):
    # here, not in Task 4: it submits through the CLI, which accepts `search` from this task on
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    step1_tools()
    assert cli(["submit", "search", "slc.NEW", "cal.Trail"]).exit_code == 0   # task 0 = cal.Trail
    monkeypatch.setenv("FAKE_SACCT", SACCT_S1)
    assert {r.hg: r.state for r in model.hg_rows(_cfg(), "search")} == {
        "tfs.A": "done", "tfs.B": "done", "tfs.C_x": "done", "cal.Trail": "failed", "slc.NEW": "ready"}
    assert {r.hg: r.state for r in model.hg_rows(_cfg(), "cluster")} == {
        "tfs.A": "done", "tfs.B": "done", "tfs.C_x": "ready", "cal.Trail": "blocked", "slc.NEW": "blocked"}


def test_submit_family_ids_file_set_and_cpus(cli, results_tree, tmp_path):
    step1_tools()
    f = tmp_path / "fams.txt"
    f.write_text("slc.NEW\n\ncal.Trail\n")
    r = cli(["submit", "search", "--ids", str(f), "-n", "--set", "domain_expand=50", "--cpus", "2"])
    assert r.exit_code == 0, r.output
    assert "domain_expand=50" in r.output
    run = next(dry_dir().glob("*_search"))
    assert (run / "ids_0.txt").read_text().split() == ["cal.Trail", "slc.NEW"]
    assert yaml.safe_load((run / "config.yaml").read_text())["params"]["domain_expand"] == 50
    assert "#SBATCH --cpus-per-task=2" in (run / "array_0.sbatch").read_text()
    r = cli(["submit", "cluster", "--ids", str(f), "-n"])          # no domains FASTA yet: both skipped
    assert r.exit_code == 0 and "skipped 2 families without inputs" in r.output
    assert "nothing to submit" in r.output
    r = cli(["submit", "search", "--ids", str(f), "-n", "--set", "s1_ncpu=x"])
    assert r.exit_code == 2 and "s1_ncpu" in r.output


def test_submit_family_errors(cli, results_tree):
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    step1_tools()
    r = cli(["submit", "search", "tfs.A"])
    assert r.exit_code == 2 and "output_exists (1): tfs.A" in r.output and "nothing submitted" in r.output
    r = cli(["submit", "cluster", "slc.NOPE", "-n"])
    assert r.exit_code == 2 and "unknown (1): slc.NOPE" in r.output
    r = cli(["submit", "cluster", "--missing", "-n"])         # NEW/Trail skipped; C_x: stray HG FASTA
    assert r.exit_code == 2 and "output_exists (1): tfs.C_x" in r.output
    r = cli(["submit", "cluster", "--missing", "--all", "-n"])
    assert r.exit_code == 2 and "input_missing (2): cal.Trail slc.NEW" in r.output
    r = cli(["submit", "search", "--missing", "-f", "nope", "-n"])
    assert r.exit_code == 1 and "no families match --fam nope" in r.output
    assert not calls_txt().exists()


def test_submit_search_preflight(cli, monkeypatch):
    monkeypatch.setenv("PATH", str(_state["bin"]))
    r = cli(["submit", "search", "slc.NEW", "-n"])
    assert r.exit_code == 78 and "hmmsearch" in r.output


def test_duplicates_warn_and_proceed(cli, results_tree):
    _, root = results_tree
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "NEW\tPF_N\t1.1\t3\tGA\tslc\tslc\nA\tPF_A\t1.1\t3\tGA\tTF\ttfs\n")
    r = cli(["missing"])
    assert r.exit_code == 0 and "warning: duplicate family ids" in r.output and "slc.NEW tfs.A" in r.output
    firsts = [l.split()[0] for l in r.output.splitlines() if l.strip()]
    assert "search" in firsts and "align" in firsts
    step1_tools()
    r = cli(["missing", "search"])
    assert r.exit_code == 0 and "slc.NEW tfs.A" in r.output
    assert {"cal.Trail", "slc.NEW"} <= set(r.output.splitlines())             # ids still listed
    r = cli(["submit", "search", "slc.NEW", "-n"])
    assert r.exit_code == 0 and "duplicate family ids" in r.output
    assert "families 1 in 1 array(s)" in " ".join(r.output.split())
    r = cli(["status", "slc.NEW"])
    assert r.exit_code == 0 and "duplicate family ids" in r.output
    assert any(l.split()[:1] == ["search"] for l in r.output.splitlines())
    r = cli(["missing", "align"])
    assert r.exit_code == 0 and "duplicate" not in r.output                   # HG commands: silent


def test_name_collision_warnings(cli, results_tree):
    _, root = results_tree
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "NEW\tPF_N2\t1.1\t3\tGA\tTF\ttfs\n")           # NEW under slc and tfs
    msg = ("warning: family name NEW is listed under 2 prefixes (slc, tfs); hmmsearch keys rows by "
           "name, so slc.NEW's hits are written as tfs.NEW.* and slc.NEW looks like \"no hits\"")
    assert msg in cli(["status"]).output and msg in cli(["missing"]).output
    step1_tools()
    r = cli(["submit", "search", "slc.NEW", "tfs.NEW", "-n"])
    assert r.exit_code == 0 and msg in r.output
    assert "family name NEW" not in cli(["missing", "search"]).output   # collisions: summaries, TUI, submit search
    assert "family name NEW" not in cli(["submit", "cluster", "--missing", "-n"]).output


def test_status_family_rows(hist):
    cli, cfg, _calls, tmp = hist
    (tmp / "nflog/run_s1.tsv").write_text(S1_LOG)
    step1_outputs(cfg.outdir)
    r = cli(["status", "tfs.A"])
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0].split()[:3] == ["tfs.A", "(2", "HGs)"]
    rows = {l.split()[0]: l for l in lines if l.split()[:1] in (["search"], ["cluster"])}
    assert list(rows) == ["search", "cluster"]
    assert "done" in rows["search"] and "nextflow" in rows["search"] and "1 GB" in rows["search"]
    assert "done" in rows["cluster"] and "run_s1" in rows["cluster"]
    assert not any(l.split()[:1] == ["align"] for l in lines)
    r = cli(["status", "tfs.B"])
    assert "done (no hits)" in next(l for l in r.output.splitlines() if l.split()[:1] == ["cluster"])
    r = cli(["status", "tfs.A", "--history"])
    assert r.exit_code == 0 and "/w/s1/1/.command.err" in r.output and "killed: out of memory?" in r.output
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest phylocli/tests/test_step1.py -q -p no:cacheprovider -k "summary_family or status_ids or status_fam_matching or missing_family or missing_search or submit_ or family_rows or duplicates_warn or name_collision or status_family"`
Expected: FAIL — e.g. `Invalid value: stage must be one of align, tree, ...` for `missing search`, no `search` row in the summary.

- [ ] **Step 3: `_check_stage`** — Task 2 set it to `core.HG_STAGES`; set both occurrences back to `core.STAGES`.

- [ ] **Step 4: family selection helpers** — add after `_missing`:

```python
def _warn_families(cfg: core.Config, collisions: bool) -> None:
    """genefam warnings on stderr -- duplicates (and, with `collisions`, a name under several
    prefixes) are warnings, never errors (decided by Grygoriy 09/10/2026)."""
    for w in core.family_warnings(cfg, collisions):
        typer.echo(w, err=True)


def _families(cfg: core.Config, ids: Path | None, fam: str | None = None) -> set[str]:
    """Family ids for a family-stage command (no genefam file = exit 1; duplicates proceed)."""
    try:
        fams = core.family_ids(cfg)
    except core.FamilyError as e:
        _fail(str(e), 1)
    if ids is not None:
        fams &= set(core.read_ids(ids))
    if fam:
        fams = core.filter_fam(fams, fam)
        if not fams:
            _fail(f"no families match --fam {fam}", 1)
    return fams


def _missing_fams(cfg: core.Config, stage: str, ids: Path | None, ready: bool = False,
                  fam: str | None = None) -> list[str]:
    fams = _families(cfg, ids, fam)
    out = sorted(fams - core.family_done(cfg, fams)[stage])
    if ready:
        busy = (_live(set()) or {}).get(stage, set())   # family tags need no HG set
        ok = core.ready_set(cfg, stage, [f for f in out if f not in busy])
        out = [f for f in out if f in ok]
    return out
```

- [ ] **Step 5: `_summary`** — replace the whole function with

```python
def _summary_sets(cfg: core.Config, ids: Path | None,
                  fam: str | None) -> tuple[set[str], set[str], list[str]]:
    """(HGs, families, warnings) for the summary: every genefam warning (duplicates, name
    collisions); a missing genefam file is a warning here too, so the HG stages stay visible."""
    exp = core.expected(cfg)
    warn: list[str] = []
    if not cfg.params.get("genefam_info"):
        fams: set[str] = set()
    else:
        try:
            fams = core.family_ids(cfg)
            warn = core.family_warnings(cfg)
        except core.FamilyError as e:
            fams, warn = set(), [f"warning: {e}"]
    if ids is not None:
        keep = set(core.read_ids(ids))
        exp &= keep
        fams &= keep
    if fam:
        exp, fams = core.filter_fam(exp, fam), core.filter_fam(fams, fam)
        if not exp and not fams:
            _fail(f"no HGs match --fam {fam}", 1)
    return exp, fams, warn


def _summary(cfg: core.Config, ids: Path | None, mode: str = "status",
             fam: str | None = None) -> tuple[set[str], dict]:
    exp, fams, warn = _summary_sets(cfg, ids, fam)
    for w in warn:
        typer.echo(w, err=True)
    rows, known, done = _guard(model.stage_rows)(cfg, exp, fams)
    if not known:
        typer.echo("squeue not on PATH: running jobs not detected")
    legend = [typer.style(f"{ch} {name}", fg=fg) for (ch, fg), name
              in zip(BAR_STYLES[mode], BAR_NAMES) if ch.strip()]
    typer.echo(f"{'stage':<12} {'done':>6} {'running':>7} {'ready':>6} {'blocked':>8} {'total':>6}  "
               + " ".join(legend))
    for r in rows:
        if r.stage == core.HG_STAGES[0] and fams:     # families above, HGs below
            typer.echo("")
        if not r.applicable:
            typer.echo(f"{r.stage:<12} {'n/a':>6}")
            continue
        line = (f"{r.stage:<12} {r.done:>6} {r.running:>7} {r.ready:>6} {r.blocked:>8} {r.total:>6}  "
                + _bar(r.done, r.running, r.ready, r.blocked, mode))
        if r.stage == "cluster":
            line += f"  {r.no_hits} no hits"
        typer.echo(line)
    return exp, done
```

(For a config without families, every line is what the old function printed.)

- [ ] **Step 6: `status HG` helpers and `status FAMILY`** — replace the whole `_hg_status` with

```python
def _print_history(con, atts: list) -> None:
    from rich.markup import escape
    from rich.table import Table
    t = Table(box=None, header_style="bold")
    for col in ("stage", "source", "run", "submitted", "att", "status (reason)", "requested",
                "used", "log"):
        t.add_column(col, no_wrap=True)
    for a in atts:
        t.add_row(a.stage, a.source, a.run, a.submitted, str(a.attempt), _status_cell(a),
                  _requested(a), _used(a), escape(a.log))
    con.print(t)


def _print_latest(con, states: dict, latest: dict) -> None:
    """One row per stage of `states` (stage -> rich-markup state, in display order) with its
    latest attempt, then the log of every stage whose latest attempt did not complete."""
    from rich.markup import escape
    from rich.table import Table
    t = Table(box=None, header_style="bold")
    for col in ("stage", "state", "source", "run", "status (reason)", "requested", "used"):
        t.add_column(col)
    for st, state in states.items():
        a = latest.get(st)
        if a is None:
            t.add_row(st, state, "–", "–", "–", "–", "–")
        else:
            t.add_row(st, state, a.source, a.run, _status_cell(a), _requested(a), _used(a))
    con.print(t)
    for st in states:
        a = latest.get(st)
        if a is not None and a.status != "COMPLETED":
            con.print(f"log ({st}): {escape(a.log)}", soft_wrap=True)


def _console():
    from rich.console import Console
    # not a terminal (pipe, file): wide enough that table cells and log paths are not wrapped
    return Console(highlight=False, width=None if sys.stdout.isatty() else 400)


def _hg_status(cfg: core.Config, hg: str, show_history: bool):
    """`status HG`: last attempt per stage, or (--history) every attempt, oldest first."""
    exp = core.expected(cfg)
    if hg not in exp:
        _fail(f"unknown HG id: {hg}", 1)
    con = _console()
    atts = history.attempts(cfg, hg, warn=lambda m: con.print(f"[yellow]{m}[/]"))
    con.print(f"{hg}  ({core.nseq(cfg, hg)} seqs)")
    if show_history:
        _print_history(con, atts)
        return
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)
    live = _live(core.expected(cfg)) or {}
    states = {}
    for st in core.HG_STAGES:
        if not core.applicable(cfg, st):
            states[st] = "n/a"
        elif hg in done[st]:
            states[st] = "[green]done[/]"
        elif hg in live.get(st, set()):
            states[st] = "[cyan]running[/]"
        elif hg in core.ready_set(cfg, st, [hg]):
            states[st] = "[yellow]ready[/]"
        else:
            states[st] = "[bright_black]blocked[/]"
    _print_latest(con, states, history.latest_by_stage(atts))


def _family_status(cfg: core.Config, fam: str, show_history: bool):
    """`status FAMILY`: last search / cluster attempt (step1.nf SEARCH/CLUSTER + phylocli)."""
    _families(cfg, None)                                  # no genefam file: exit 1
    _warn_families(cfg, collisions=False)                 # duplicates: a warning, then proceed
    con = _console()
    atts = history.family_attempts(cfg, fam, warn=lambda m: con.print(f"[yellow]{m}[/]"))
    exp = core.expected(cfg)
    con.print(f"{fam}  ({sum(1 for h in exp if h.rsplit('.', 1)[0] == fam)} HGs)")
    if show_history:
        _print_history(con, atts)
        return
    fd = core.family_done(cfg, [fam])
    live = _live(exp) or {}
    states = {}
    for st in core.FAMILY_STAGES:
        if fam in fd[st]:
            states[st] = "[green]done[/]" + (" (no hits)" if st == "cluster" and fam in fd["no_hits"] else "")
        elif fam in live.get(st, set()):
            states[st] = "[cyan]running[/]"
        elif fam in core.ready_set(cfg, st, [fam]):
            states[st] = "[yellow]ready[/]"
        else:
            states[st] = "[bright_black]blocked[/]"
    _print_latest(con, states, history.latest_by_stage(atts))
```

(The `_hg_status` output is identical to before: same header, same tables, same log lines, same order — pinned by `test_status_hg_table` / `test_status_hg_history`.)

In `status`, replace

```python
        _hg_status(cfg, hg, history_)
        return
```

with

```python
        if hg in core.family_ids(cfg, strict=False):     # a family id is never an HG id
            _family_status(cfg, hg, history_)
        else:
            _hg_status(cfg, hg, history_)
        return
```

- [ ] **Step 7: `missing STAGE` for families** — in `missing`, replace

```python
    _check_stage(stage)
    cfg = _cfg()
    todo = _missing(cfg, stage, ids, ready=not all_, fam=fam)
```

with

```python
    _check_stage(stage)
    cfg = _cfg()
    if stage in core.FAMILY_STAGES:
        if per_fam:
            _fail(f"--per-fam does not apply to {stage}: each row is already a family", 2)
        _warn_families(cfg, collisions=False)
        for f in _missing_fams(cfg, stage, ids, ready=not all_, fam=fam):
            typer.echo(f)
        return
    todo = _missing(cfg, stage, ids, ready=not all_, fam=fam)
```

- [ ] **Step 8: preflight and dry run** — replace `_preflight` with

```python
def _preflight(stage: str, cfg: "core.Config | None" = None):
    msg = model.preflight(stage, cfg)
    if msg:
        _fail(msg, 78)
```

in `_print_dry_run` replace

```python
    body = [f"[bold]run dir[/]  {shown}", f"[bold]HGs[/]      {n} in {len(plan)} array(s)"]
```

with

```python
    unit = core.unit(stage)
    body = [f"[bold]run dir[/]  {shown}",
            f"[bold]{unit}[/]{' ' * (9 - len(unit))}{n} in {len(plan)} array(s)"]
```

and

```python
    for col in ("array", "HGs", "cpus", "memory", "time", "qos", "signal"):
        t.add_column(col, justify="right" if col in ("HGs", "cpus", "memory") else "left")
```

with

```python
    for col in ("array", unit, "cpus", "memory", "time", "qos", "signal"):
        t.add_column(col, justify="right" if col in (unit, "cpus", "memory") else "left")
```

(`"HGs" + 6 spaces` = the old string exactly.)

- [ ] **Step 9: `submit`** — four Edits in `submit`:

```python
    if missing_:
        selected = _missing(cfg, stage, None)
```
→
```python
    if missing_:
        selected = (_missing_fams(cfg, stage, None) if stage in core.FAMILY_STAGES
                    else _missing(cfg, stage, None))
```

```python
    cfg = core.config_from_raw(raw)
    if not core.applicable(cfg, stage):
```
→
```python
    cfg = core.config_from_raw(raw)
    if stage in core.FAMILY_STAGES:                # duplicates (search: also name collisions)
        _warn_families(cfg, collisions=stage == "search")
    if not core.applicable(cfg, stage):
```

```python
        selected = [hg for hg in selected if hg in keep]
        if not selected:
            _fail(f"no HGs match --fam {fam}", 1)
```
→
```python
        selected = [hg for hg in selected if hg in keep]
        if not selected:
            _fail(f"no {core.unit(stage)} match --fam {fam}", 1)
```

`    _preflight(stage)` → `    _preflight(stage, cfg)`

```python
        typer.echo(f"submitted {jid}: {len(ids_)} HGs ({res.cpus} cpus, {res.mem_mb}M, {res.time_min} min)")
```
→
```python
        typer.echo(f"submitted {jid}: {len(ids_)} {core.unit(stage)} ({res.cpus} cpus, {res.mem_mb}M, "
                   f"{res.time_min} min)")
```

- [ ] **Step 10: Run both suites** — Expected: `241 passed` on both. If any pre-existing CLI test fails, the HG-stage output changed: fix the code, never the test.

- [ ] **Step 11: Commit**

```bash
git add phylocli/phylo.py phylocli/tests/test_step1.py
git commit -m "phylocli step1: missing/status/submit for search and cluster (family ids), summary rows, status FAMILY

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: TUI — search / cluster in the overview and the HG view

**Files:**
- Modify: `phylocli/tui.py` (`TUI_STAGES`, `ov_column`, new `OV_COLUMNS` / `OV_TOP` / `OV_SEP` / `stage_at_column`, `compose` (overview `header_height=2`), `_fill_overview`, `on_data_table_cell_selected`, `__init__`, `_collect`, `_apply`, `visible`, `_overview_footer`, `_regroup`, `_fill_stages`, `_fill_hgs`, `_show_detail` → `_detail_text`, `ResubmitScreen.compose`, `_build`, `_dry_worker`)
- Modify tests (spec-changed expectations): `phylocli/tests/test_tui.py` — `test_refresh_keeps_stage_selection_and_cursor`, `test_overview_is_first_and_reads_no_history`, `test_overview_family_toggle`, `test_regroup_is_in_memory`
- Test: `phylocli/tests/test_step1.py`

**Interfaces:**
- Consumes: `model.family_states`, `model.group_rows(..., fams=, fstates=)`, `model.fam_group_key`, `GroupRow.n_fams`, `model.hg_rows` family rows, `history.family_attempts`, `model.preflight(stage, cfg)`, `core.unit`, `core.FAMILY_STAGES` (Tasks 2-4); `TUI_STAGES` (Task 2)
- Produces: `TUI_STAGES = core.STAGES`; `OV_COLUMNS = ["search", "cluster", None, "align", …]` (`None` = the `│` separator); `ov_column(stage) -> int`; `stage_at_column(col) -> str | None` (None for group, HGs and the separator — the ONE column→stage mapping: `enter`, cursor restore and the coming `s` sort of spec `2026-10-09-phylocli-tui-og-explorer-sort-design.md` all go through it); `PhyloApp._ov_inputs = (exp, states, fams, fstates)`; `PhyloApp.hg_count: dict[str, int]` (family id → expected HGs); `PhyloApp._detail_text(hg: str) -> str`; banner carries `core.family_warnings(cfg)` (duplicates and name collisions).

Behaviour (TUI spec "Overview" / "HG view", extended to step1):
- Overview columns: `group`, `HGs`, then `search`, `cluster`, then the six HG stages. **Step1 and step2 are visibly separated** (Grygoriy, 09/10/2026): the header row is labelled `step1 · families` over search/cluster and `step2 · HGs` over the six HG stages, and a one-character `│` separator column sits between cluster and align (it is not a stage: `enter` on it opens the group at the current stage, and the cell-to-stage mapping skips it). **How:** a two-row header from the column labels (`DataTable(header_height=2)`, each label `"<top>\n<stage>"`): the top row reads `step1 ·  families │ step2 ·  HGs` — `step1 ·` over search, `families` over cluster, `step2 ·` over align, `HGs` over tree — so the block names sit exactly over their columns (a separate label line above the table could not follow the column widths). Checked on Textual 8.2.8 (both test interpreters) in a scratch prototype. The separator column's label and cells are `│`. Cursor restore after a refill never lands on the separator (it moves to `align`). Tests: labels, `header_height`, separator cells; `enter` on align opens align; `enter` on the separator opens the current stage. The `search` / `cluster` cells count **families** (`ALL` = all families, a category row = that category's families, a family row (`f`) = that one family), from `model.family_states` — the same function the CLI's `search` / `cluster` summary rows count, so `ALL` equals `phylo status`. **The `HGs` column stays the group's HG count** (expected HGs, the step2 unit), so a family-only group shows `0` there; the footer line says `<n> HGs · <m> families` and that search/cluster count families. Groups that have families but no HG yet get their own row (sorted after every group with HGs). `c` / `f` regroup in memory from `(exp, states, fams, fstates)`.
- `enter` on a `search` / `cluster` cell opens the HG view of that group at that stage: the list panel lists the group's FAMILIES (`hg` = family id), filter auto-picked as for HGs (`_auto_pick_filter`: the first non-empty filter in `FILTERS` order once history has loaded, else `FILTERS[0]`; at `4867d41` `FILTERS[0]` is `actionable` = failed + ready, so a group with any failed or ready family opens on `actionable`); select, `a`, `r` (resubmit with bumped resources, family ids), `l` (log of the latest search/cluster attempt) work unchanged. The list's `seqs` column shows `<k> HGs` for a family.
- Stages panel of the opened group: `search` / `cluster` rows with the family counts (total = the group's families), HG-stage rows with the HG counts (total = its HGs).
- Detail panel: for a family, `<id>  <k> HGs` and the two family stages; for an HG, unchanged (six HG stages).
- The overview still reads no attempt history: `history.family_attempts` is called only in the HG view.

- [ ] **Step 1: Write the failing tests** — append to `phylocli/tests/test_step1.py`:

```python
# ---- Task 6: TUI -----------------------------------------------------------------------------

def _tui():
    pytest.importorskip("textual")
    from phylocli import tui
    return tui


def _calls():
    p = _state["bin"] / "calls.txt"
    return p.read_text().splitlines() if p.exists() else []


def test_tui_overview_family_cells_and_open(cli, results_tree, monkeypatch):
    tui = _tui()
    cfg, _ = results_tree
    step1_outputs(cfg.outdir)
    step1_tools()
    assert cli(["submit", "search", "slc.NEW", "cal.Trail"]).exit_code == 0   # task 0 = cal.Trail
    monkeypatch.setenv("FAKE_SACCT", SACCT_S1)
    app = tui.PhyloApp(_cfg(), refresh_s=3600)
    n0 = len(_calls())

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            ov = app.query_one("#overview")
            assert [str(c.label) for c in ov.columns.values()][:5] == ["\ngroup", "\nHGs", "step1 ·\nsearch",
                                                                    "families\ncluster", "│\n│"]
            rows = {r.group: r for r in app.ov_rows}
            assert list(rows) == ["ALL", "tfs", "cal", "slc"]
            s = {x.stage: x for x in model.stage_rows(_cfg(), core.expected(_cfg()), FAMS)[0]}
            for st in core.FAMILY_STAGES:                         # same numbers as phylo status
                assert rows["ALL"].per_stage[st] == (s[st].done, s[st].running, s[st].ready, s[st].blocked)
            assert (rows["cal"].total, rows["cal"].n_fams) == (0, 1)
            ov.move_cursor(row=2, column=tui.ov_column("search"))             # cal x search
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            app.load_now()                                         # HG view: history now
            await pilot.pause()
            assert app.view == "hgs" and app.group == "cal" and app.stage == "search"
            assert app.filter == "actionable" and [r.hg for r in app.visible()] == ["cal.Trail"]  # failed
            await pilot.press("f")                                 # actionable -> failed: same family
            assert app.filter == "failed" and [r.hg for r in app.visible()] == ["cal.Trail"]
            st = app.query_one("#stages")
            assert str(st.get_cell_at((core.STAGES.index("search"), 5))) == "1"    # cal's families
            assert str(st.get_cell_at((core.STAGES.index("align"), 5))) == "0"     # cal's HGs
            text = app._detail_text("cal.Trail")
            assert "cal.Trail" in text and "0 HGs" in text and "search" in text and "align" not in text
            await pilot.press("a", "r")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, tui.ResubmitScreen) and scr.stage == "search"
            assert [(g[0], g[1].mem_mb, g[2]) for g in scr.groups] == [("OOM", 1000, ["cal.Trail"])]
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "resources: step1 defaults for 1 families" in scr._shown
            assert "array 0: 1 families" in scr._shown
            assert len(_calls()) == n0                             # dry run only
    asyncio.run(go())


def test_tui_overview_step1_step2_separator(cli, monkeypatch):
    tui = _tui()
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_S1)
    app = tui.PhyloApp(_cfg(), refresh_s=3600)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            ov = app.query_one("#overview")
            labels = [str(c.label) for c in ov.columns.values()]
            assert ov.header_height == 2
            assert labels[2:7] == ["step1 ·\nsearch", "families\ncluster", "│\n│", "step2 ·\nalign", "HGs\ntree"]
            sep = tui.ov_column("cluster") + 1
            assert tui.stage_at_column(sep) is None and tui.ov_column("align") == sep + 1
            assert all(str(ov.get_cell_at((i, sep))) == "│" for i in range(ov.row_count))
            ov.move_cursor(row=0, column=tui.ov_column("align"))               # ALL x align
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.view == "hgs" and app.stage == "align"
            await pilot.press("escape")
            await pilot.pause()
            app.stage = "tree"                                                 # the "current" stage
            ov.move_cursor(row=0, column=sep)                                  # ALL x │
            await pilot.pause()
            await pilot.press("enter")                                         # not a stage: no crash
            await pilot.pause()
            assert app.view == "hgs" and app.stage == "tree" and app.group is None
            await pilot.press("escape")
            await pilot.pause()
            ov.move_cursor(row=0, column=sep)
            app.load_now()                                                     # a refill restores...
            await pilot.pause()
            assert ov.cursor_column == tui.ov_column("align")                  # ...never onto │
    asyncio.run(go())


def test_tui_banner_on_duplicate_ids(cli, results_tree):
    tui = _tui()
    _, root = results_tree
    g = root / "gene_families_searchinfo.csv"
    g.write_text(g.read_text() + "NEW\tPF_N\t1.1\t3\tGA\tslc\tslc\n")
    app = tui.PhyloApp(_cfg(), refresh_s=3600)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert "duplicate family ids" in app._banner_text and "slc.NEW" in app._banner_text
            assert app.view == "overview"                              # a warning; the app goes on
            assert app.ov_rows[0].n_fams == 5                       # still counted, de-duplicated
            assert "search" in [str(c.label) for c in app.query_one("#overview").columns.values()]
    asyncio.run(go())
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest phylocli/tests/test_step1.py -q -p no:cacheprovider -k tui`
Expected: FAIL — `AttributeError: module 'phylocli.tui' has no attribute 'stage_at_column'`, the overview's third column is `align`; `AttributeError: 'PhyloApp' object has no attribute '_detail_text'`.

- [ ] **Step 3: `tui.py`** — Edits:

`import collections` at the top of the stdlib imports (before `import os`).

```python
TUI_STAGES = core.HG_STAGES
```
→
```python
TUI_STAGES = core.STAGES
```
(and drop the "until the step1 TUI task" sentence from its comment). Replace the Task 2 `ov_column` and add, right below it:

```python
OV_SEP = "│"
# Overview stage columns: step1 (families) | step2 (HGs); None = the one-character separator column.
OV_COLUMNS = [*core.FAMILY_STAGES, None, *core.HG_STAGES]
# Top header row (Grygoriy, 09/10/2026): block names over the first two columns of each block.
OV_TOP = {core.FAMILY_STAGES[0]: "step1 ·", core.FAMILY_STAGES[1]: "families",
          core.HG_STAGES[0]: "step2 ·", core.HG_STAGES[1]: "HGs"}


def ov_column(stage: str) -> int:
    """Overview column of `stage` (after the group and HGs columns, skipping the separator)."""
    return 2 + OV_COLUMNS.index(stage)


def stage_at_column(col: int) -> "str | None":
    """The stage of an overview column; None for group, HGs and the separator (not a stage).
    The one column->stage mapping: enter, cursor restore and the `s` sort use it."""
    return OV_COLUMNS[col - 2] if 2 <= col < 2 + len(OV_COLUMNS) else None
```

add `from rich.text import Text` next to `from rich.markup import escape`.

in `compose` replace `yield DataTable(id="overview", cursor_type="cell")` with `yield DataTable(id="overview", cursor_type="cell", header_height=2)   # step1/step2 header row`.

replace `_fill_overview` (Task 2 left its columns on `TUI_STAGES`) with

```python
    def _fill_overview(self, rows: list) -> None:
        self.ov_rows = rows
        t = self.query_one("#overview", DataTable)
        keep = self._key_at_cursor(t)
        col = t.cursor_column
        if col >= 2 and stage_at_column(col) is None:      # never restore onto the separator
            col += 1
        if not t.columns:
            t.add_columns(Text("\ngroup"), Text("\nHGs"),
                          *(Text(f"{OV_SEP}\n{OV_SEP}") if st is None
                            else Text(f"{OV_TOP.get(st, '')}\n{st}") for st in OV_COLUMNS))
        t.clear()
        for r in rows:
            cells = []
            for st in OV_COLUMNS:
                if st is None:
                    cells.append(OV_SEP)
                    continue
                c = r.per_stage.get(st)
                if c is None:
                    cells.append("n/a")
                    continue
                n = model.bar_segments(c, self.OV_BAR)
                cells.append("".join(f"[{fg}]{ch * k}[/]"
                                     for (ch, fg), k in zip(self.OV_GLYPHS, n) if k))
            t.add_row(r.group, str(r.total), *cells, key=r.group)
        keys = [r.group for r in rows]
        t.move_cursor(row=keys.index(keep) if keep in keys else 0, column=col)
        self._overview_footer()
```

in `on_data_table_cell_selected` replace

```python
        col = event.coordinate.column
        stage = TUI_STAGES[col - 2] if col >= 2 else None
```

with

```python
        stage = stage_at_column(event.coordinate.column)   # None: group, HGs or │ -> current stage
```

(`open_group(name, None)` keeps the current stage — the HEAD behaviour for the group / HGs columns.)

in `__init__` replace `self._ov_inputs: tuple = (set(), {})` with

```python
        self._ov_inputs: tuple = (set(), {}, set(), {})    # exp, HG states, families, family states
        self.hg_count: dict[str, int] = {}                 # family id -> expected HGs
```

replace `_collect` with

```python
    def _collect(self) -> dict:
        exp = core.expected(self.cfg)
        done_map = core.report_status.done_by_stage(str(self.cfg.outdir), exp)
        lv = model.live(exp)
        known = lv is not None
        lv = lv or {}
        states = model.stage_states(self.cfg, exp, done_map, lv)
        fam_warn, fams = [], set()
        if self.cfg.params.get("genefam_info"):
            try:
                fams = core.family_ids(self.cfg)
                fam_warn = core.family_warnings(self.cfg)      # duplicates, name collisions
            except core.FamilyError as e:    # no genefam file: warn; every stage stays visible
                fam_warn = [f"warning: {e}"]
        fstates = model.family_states(self.cfg, fams, lv)
        by = self.by
        ov_rows, _k = model.group_rows(self.cfg, exp, by, states=states, fams=fams, fstates=fstates)
        hg_count = dict(collections.Counter(model.group_key(h, "family") for h in exp))
        snap = dict(ov_rows=ov_rows, by=by, ov_inputs=(exp, states, fams, fstates), known=known,
                    fam_warn=fam_warn, hg_count=hg_count, when=datetime.now(), hg=None)
        if self.view == "hgs":               # the slow part: attempt history, only in the HG view
            for hg in exp:                   # FASTAs are read here, off the UI thread, once
                if not self.nseq.get(hg):
                    self.nseq[hg] = core.nseq(self.cfg, hg)
            atts = history.attempts(self.cfg)
            fatts = history.family_attempts(self.cfg)
            # every applicable stage from ONE attempts read, ONE done scan, ONE squeue call, so
            # that stage changes and the detail panel need no subprocess on a key press
            by_stage = {st: (model.hg_rows(self.cfg, st, exp,
                                           fatts if st in core.FAMILY_STAGES else atts,
                                           done_map, lv)
                             if core.applicable(self.cfg, st) else [])
                        for st in TUI_STAGES}
            arrays, sacct_known = model.array_rows()
            snap["hg"] = dict(atts=atts + fatts, by_stage=by_stage, arrays=arrays,
                              sacct_known=sacct_known)
        return snap
```

in `_apply` replace

```python
        self._ov_inputs = snap["ov_inputs"]
```

with

```python
        self._ov_inputs = snap["ov_inputs"]
        self.hg_count = snap["hg_count"]
```

and replace

```python
        if not snap["known"]:
            banner.append("squeue not on PATH: running jobs not detected")
```

with

```python
        if not snap["known"]:
            banner.append("squeue not on PATH: running jobs not detected")
        banner += [escape(w) for w in snap["fam_warn"]]
```

replace `visible` (keep `4867d41`'s `actionable` branch) with

```python
    def visible(self) -> list:
        if self.filter == "actionable":
            rows = [r for r in self.rows if r.state in ACTIONABLE]
        else:
            rows = [r for r in self.rows if r.state == self.filter]
        if self.group is not None:          # search / cluster list families, the rest HGs
            key = model.fam_group_key if self.stage in core.FAMILY_STAGES else model.group_key
            rows = [r for r in rows if key(r.hg, self.by) == self.group]
        return rows
```

in `_overview_footer` replace

```python
            f"[b]{escape(r.group)}[/] {r.total} HGs · done/running/ready/blocked: "
            + " · ".join(parts)
            + "\n█ done ▒ running ▓ ready/failed ░ blocked · enter: open · c/f: category/family"
            + " · default view: failed+ready")
```

with

```python
            f"[b]{escape(r.group)}[/] {r.total} HGs · {r.n_fams} families · "
            "done/running/ready/blocked: " + " · ".join(parts)
            + "\n█ done ▒ running ▓ ready/failed ░ blocked · search/cluster count families · "
              "enter: open · c/f: category/family"
            + " · default view: failed+ready")
```

in `_regroup` replace

```python
        exp, states = self._ov_inputs
        rows, _k = model.group_rows(self.cfg, exp, self.by, states=states)   # in-memory only
```

with

```python
        exp, states, fams, fstates = self._ov_inputs
        rows, _k = model.group_rows(self.cfg, exp, self.by, states=states,   # in-memory only
                                    fams=fams, fstates=fstates)
```

in `_fill_stages` replace

```python
                st.add_row(name, str(c[0]), str(c[1]), str(c[2]), str(c[3]), str(row.total),
                           key=name)
```

with

```python
                total = row.n_fams if name in core.FAMILY_STAGES else row.total   # families / HGs
                st.add_row(name, str(c[0]), str(c[1]), str(c[2]), str(c[3]), str(total), key=name)
```

in `_fill_hgs` replace

```python
        for r in self.visible():
            n = self.nseq.get(r.hg, 0)
            a = r.last
            t.add_row("●" if r.hg in self.selected else " ", r.hg, str(n),
```

with

```python
        fam_stage = self.stage in core.FAMILY_STAGES
        for r in self.visible():
            n = f"{self.hg_count.get(r.hg, 0)} HGs" if fam_stage else str(self.nseq.get(r.hg, 0))
            a = r.last
            t.add_row("●" if r.hg in self.selected else " ", r.hg, n,
```

replace `_show_detail` (Task 2 left its loop on `core.HG_STAGES`) with

```python
    def _detail_text(self, hg: str) -> str:
        """Detail panel for `hg`: an HG (six HG stages), or a family on search / cluster."""
        if self.stage in core.FAMILY_STAGES:
            head, stages = f"[b]{hg}[/]  {self.hg_count.get(hg, 0)} HGs", core.FAMILY_STAGES
        else:
            head, stages = f"[b]{hg}[/]  {self.nseq.get(hg, 0)} seqs", core.HG_STAGES
        latest = history.latest_by_stage([a for a in self.atts if a.hg == hg])
        lines = [head, ""]
        for st in stages:
            rs = next((r for r in self.by_stage.get(st, []) if r.hg == hg), None)
            s_ = rs.state if rs else "n/a"
            a = latest.get(st)
            extra = (f"  {a.status} ({history.reason(a.status, a.exit)})  req {a.cpus}/{a.mem}/{a.time}"
                     f"  used {a.peak_rss}/{a.realtime}" if a else "")
            lines.append(f"{st:<12} [{STATE_STYLE.get(s_, 'white')}]{s_:<8}[/]{extra}")
        a = latest.get(self.stage)
        if a is not None:
            lines += ["", f"log: {a.log}"]
        return "\n".join(lines)

    def _show_detail(self) -> None:
        hg = self._cursor_hg()
        self.query_one("#detail", Static).update("" if hg is None else self._detail_text(hg))
```

in `ResubmitScreen.compose` replace `yield Label(f"{len(hgs)} HGs · {why or 'other'} · mem ")` with `yield Label(f"{len(hgs)} {core.unit(self.stage)} · {why or 'other'} · mem ")`; in `_build` replace `msg = model.preflight(self.stage)` with `msg = model.preflight(self.stage, self.cfg)`; in `_dry_worker` replace `lines.append(f"array {k}: {len(ids_)} HGs · {res.cpus} cpus · {fmt_mem(res.mem_mb)}"` with `lines.append(f"array {k}: {len(ids_)} {core.unit(self.stage)} · {res.cpus} cpus · {fmt_mem(res.mem_mb)}"`. Change the module docstring to `"""phylo tui: interactive view of step1 + step2 progress (Textual). Imported only by `phylo tui`."""`.

- [ ] **Step 4: The existing TUI tests this task changes** (spec: search/cluster sit before align; groups with families but no HG get rows) — in `phylocli/tests/test_tui.py`:
  - `test_refresh_keeps_stage_selection_and_cursor` (line 252): `assert app.query_one("#stages").cursor_row == 1` → `assert app.query_one("#stages").cursor_row == core.STAGES.index("tree")`
  - `test_overview_is_first_and_reads_no_history` and `test_regroup_is_in_memory` (Edit with `replace_all`, both lines are identical): `            assert [r.group for r in app.ov_rows] == ["ALL", "tfs"]` → `            assert [r.group for r in app.ov_rows] == ["ALL", "tfs", "cal", "slc"]`
  - `test_regroup_is_in_memory`: `            assert [r.group for r in app.ov_rows] == ["ALL", "tfs.A", "tfs.C_x"]` → `            assert [r.group for r in app.ov_rows] == ["ALL", "tfs.A", "tfs.C_x", "cal.Trail", "slc.NEW", "tfs.B"]`
  - `test_overview_family_toggle`: `assert app.by == "family" and [r.group for r in app.ov_rows] == ["ALL", "tfs.A", "tfs.C_x"]` → `assert app.by == "family" and [r.group for r in app.ov_rows] == ["ALL", "tfs.A", "tfs.C_x", "cal.Trail", "slc.NEW", "tfs.B"]`

  No other existing test changes (see Global Constraints for the ones checked). `test_regroup_is_in_memory` keeps its point: `core.ready_set` raising on regroup proves `family_states` is not recomputed either.

- [ ] **Step 5: Run both suites** — Expected: `244 passed` on both.

- [ ] **Step 6: Commit**

```bash
git add phylocli/tui.py phylocli/tests/test_tui.py phylocli/tests/test_step1.py
git commit -m "phylocli tui: search/cluster columns in the overview (counted in families), family lists in the HG view, duplicate-id banner

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `step1.nf` calls the stage scripts; docs

**Files:**
- Modify: `step1.nf:107-127` (SEARCH `script:`), `:143-169` (CLUSTER `output:` + `script:`)
- Modify: `phylocli/README.md`, `docs/superpowers/specs/2026-10-04-phylocli-step1-design.md` (append decisions)
- Test: `phylocli/tests/test_step1.py`

**Interfaces:**
- Consumes: `phylocli/stages/search.sh`, `cluster.sh` (Task 3) and their env contract
- Produces: `step1.nf` whose family-skip logic, process names, tags, resources and published outputs are unchanged; CLUSTER's HG-FASTA output is `optional: true`.

- [ ] **Step 1: Write the failing test** — append to `phylocli/tests/test_step1.py`:

```python
# ---- Task 7: step1.nf ------------------------------------------------------------------------

def test_step1_nf_calls_stage_scripts():
    nf = (core.ROOT / "step1.nf").read_text()
    assert "exec bash ${projectDir}/phylocli/stages/search.sh genefam.csv input.fasta" in nf
    assert "exec bash ${projectDir}/phylocli/stages/cluster.sh ${domains_fasta}" in nf
    assert "min_seqs=${params.min_seqs} min_distinct=${params.min_distinct}" in nf
    assert 'path("${pref}.${family}.*.fasta", optional: true)' in nf
    assert "python ${projectDir}/phylogeny/main.py" not in nf          # bodies live in the scripts
    assert "def familyIsDone" in nf and "stageInMode 'copy'" in nf      # skip logic / staging kept
```

Run: `python3 -m pytest phylocli/tests/test_step1.py -q -p no:cacheprovider -k step1_nf` → FAIL.

- [ ] **Step 2: `step1.nf`** — replace the SEARCH `script:` block (from `  script:` through the closing `"""` before `}`) with

```groovy
  script:
  // body: phylocli/stages/search.sh (shared with phylocli, 09/10/2026)
  """
  ID=${pref}.${family} CPUS=${task.cpus} PROJECT_DIR=${projectDir} \\
  pfam_db="${params.pfam_db}" domain_expand=${params.domain_expand} \\
  exec bash ${projectDir}/phylocli/stages/search.sh genefam.csv input.fasta ${params.hmm_dir ? 'custom_hmms' : ''}
  """
```

in CLUSTER replace

```groovy
    output:
    path("${pref}.${family}_cluster.tsv")
    path("${pref}.${family}.*.fasta")
```

with

```groovy
    output:
    path("${pref}.${family}_cluster.tsv")
    // optional: HGs below min_seqs/min_distinct are not written, and a family can have none left
    path("${pref}.${family}.*.fasta", optional: true)
```

and replace its `script:` block (from `	script:` through the closing `"""`) with

```groovy
    script:
    // body: phylocli/stages/cluster.sh (shared with phylocli, 09/10/2026)
    """
    ID=${pref}.${family} CPUS=${task.cpus} PROJECT_DIR=${projectDir} \\
    max_n=${params.max_n} s2_inflation=${params.s2_inflation} \\
    min_seqs=${params.min_seqs} min_distinct=${params.min_distinct} \\
    exec bash ${projectDir}/phylocli/stages/cluster.sh ${domains_fasta}
    """
```

Nothing else in `step1.nf` changes (`familyIsDone`, `todo_ch`, `nonempty`, tags, `cpus/memory/time`, `errorStrategy`, `publishDir`, `stageInMode 'copy'`). `nextflow.config` is NOT edited (`min_seqs`/`min_distinct` are already there).

- [ ] **Step 3: README** — in `phylocli/README.md`:

replace the intro

```
`phylo` reports step2 progress (per category, per stage) and submits one SLURM job array per
resource group for a single stage, without Nextflow. The stage scripts in `stages/` are the
step2.nf process bodies; step2.nf now calls the same scripts (created 30/09/2026).
```

with

```
`phylo` reports step1 + step2 progress (per stage) and submits one SLURM job array per
resource group for a single stage, without Nextflow. The stage scripts in `stages/` are the
step1.nf / step2.nf process bodies; both pipelines call the same scripts (step2 30/09/2026,
step1 09/10/2026).
```

replace the `submit checks the tools ...` sentence's first line

```
`submit` checks the tools the stage needs (mafft/clipkit, iqtree2, generax/mpirun) and, for
```

with

```
`submit` checks the tools the stage needs (hmmsearch/hmmfetch/bedtools, samtools/diamond/mcl,
mafft/clipkit, iqtree2, generax/mpirun; for `search` also that `genefam_info`, `infasta`,
`pfam_db` exist) and, for
```

in the Commands block replace `phylocli/phylo status HG [--history]` with `phylocli/phylo status HG|FAMILY [--history]`, and replace

```
STAGE is one of `align tree possvm_prev generax gxsup possvm`. `submit` takes exactly one of:
HG ids, `--ids FILE`, or `--missing`.
```

with

```
STAGE is one of `search cluster align tree possvm_prev generax gxsup possvm`. `search` and
`cluster` (step1) work on FAMILY ids `<pref>.<family>` (genefam column 1 and its last non-empty
field, e.g. `slc.SLC25`), the others on HG ids. `submit` takes exactly one of: ids,
`--ids FILE`, or `--missing`.
```

in the examples block, after the line `phylocli/phylo jobs 29318676 ...`, insert

```
phylocli/phylo missing search                     # families never searched (new genefam rows)
phylocli/phylo submit search --missing -n         # dry run; then without -n
phylocli/phylo missing cluster                    # searched, with hits, not clustered
phylocli/phylo submit cluster --missing
phylocli/phylo status slc.SLC25                   # one family: search / cluster state + latest job
```

append to `## Rules`:

```
- `search` / `cluster`: done = `search/<id>.domains.fasta` exists / `clusters/<id>_cluster.tsv`
  exists (or the domains FASTA is empty: "no hits", counted as done). `search` is always ready;
  `cluster` is ready when the domains FASTA is non-empty. HG FASTAs in `clusters/` without a
  `_cluster.tsv` count as existing output (two clusterings must not mix). `--per-fam` is an error.
- A duplicated family id in the genefam file is a warning, never an error: the summaries, the
  TUI banner and every search/cluster command print it and go on; the last row of the id is used,
  as `main.py hmmsearch` and step1.nf do (09/10/2026: `slc.SLC44`, `neu.Synapsin`).
- A family NAME under two prefixes (`rbp.CSD` / `tfs.CSD`): `main.py hmmsearch` keys rows by name
  (the last row wins), so `rbp.CSD`'s hits are written as `tfs.CSD.*` and `rbp.CSD` is published
  empty ("no hits"), as in step1.nf. `search` prints a `WARNING` saying so; the summaries, the TUI
  banner and `submit search` list every such name beforehand.
- `cluster` writes `<id>.HG<n>.fasta` only for HGs with >= `min_seqs` sequences and >=
  `min_distinct` distinct ones (the rule step2 uses); `<id>_cluster.tsv` stays complete, so HG
  numbers have gaps. It prints `skipped <k> HGs below min_seqs/min_distinct`.
```

append to `## Runs and logs`:

```
A `search` submission copies the genefam file to `runs/<run>/genefam.csv` and its `config.yaml`
points there: the jobs search the rows that were validated, even if the file is edited while
they wait in the queue.
```

in `## config.yaml` replace `` `phylocli/config.yaml` holds `outdir`, `partition`, `qos` and the step2 parameters the stages `` with `` `phylocli/config.yaml` holds `outdir`, `partition`, `qos`, the step1 parameters (`genefam_info`, `infasta`, `pfam_db`, `hmm_dir`, `domain_expand`, `s1_ncpu`, `s2_ncpu`, `max_n`, `s2_inflation`) and the step2 parameters the stages ``.

append to `## Nextflow caveat and backup`:

```
`step1.nf` `SEARCH` / `CLUSTER` call `phylocli/stages/search.sh` / `cluster.sh` (09/10/2026;
original: `step1.nf.bak-<date of the copy>`). step1.nf decides completeness from the published
outputs, not the resume cache, so the changed script text costs no rerun.
```

in `## phylo tui`, after the paragraph ending `attempt history is read only once an HG view is open.`, insert the paragraph

```
`search` and `cluster` are the first two columns and count FAMILIES (`ALL` = all families, a
category row = its families, a family row = that family); the `HGs` column stays the group's HG
count, so a family added to the genefam file shows as its own row with 0 HGs until `cluster`
has run. `enter` on a search/cluster cell lists that group's families (select, resubmit and log
work on family ids); the stages panel then counts families for search/cluster and HGs for the
other stages.
```

and replace `HG view panels: stages (top left) · HGs of the highlighted stage (top right)` with `HG view panels: stages (top left) · HGs — or families, for search / cluster — of the highlighted stage (top right)`.

- [ ] **Step 4: Record the decisions in the spec** — append to `docs/superpowers/specs/2026-10-04-phylocli-step1-design.md`:

```markdown
## Implementation decisions (plan 2026-10-08-phylocli-step1.md, 09/10/2026)
- Duplicate family ids (decided by Grygoriy 09/10/2026: warning): never an error. The
  summaries, the TUI banner and every search/cluster command (`missing`, `submit`, `status
  FAMILY`) print a warning naming them and proceed; each id counts once and its LAST row is used,
  as main.py hmmsearch (keys rows by name, the last row wins) and step1.nf do. The real file has
  two: `slc.SLC44` and `neu.Synapsin`.
- "Stage the CURRENT file": `submit search` snapshots the genefam file into the run dir
  (`genefam.csv`, the name step1.nf stages it under) and the run's `config.yaml` points there.
- `pfam_db` is checked by preflight, not staged (step1.nf passes it as a path too); search is
  ready whenever the family has a row.
- A family name under two prefixes (decided by Grygoriy 09/10/2026: warning): `search.sh`
  keeps step1.nf's behaviour (the empty files are published) and prints `WARNING: family name
  <N> is listed under more than one prefix ...` naming the id its hits were written under; the
  summaries, the TUI banner and `submit search` print `warning: family name CSD is listed under 2
  prefixes (rbp, tfs); hmmsearch keys rows by name, so rbp.CSD's hits are written as tfs.CSD.*
  and rbp.CSD looks like "no hits"`. `search.sh` copies `hmm_dir` before use because `main.py`
  fetches missing models into it.
- `cluster` counts HG FASTAs without a `_cluster.tsv` as existing output.
- `status` (summary) shows the family rows too (it draws the same `stage_rows` as `missing`);
  `status HG` keeps its six HG rows; the TUI HG view still opens on `align` when no stage cell
  was chosen.
- TUI overview: `search` / `cluster` cells count families (from `model.family_states`, the same
  function as the CLI summary rows); the `HGs` column stays the HG count (step2's unit) and the
  footer adds the family count; a group with families but no HG yet gets a row (0 HGs), because
  a newly added family is exactly what `search` is for and would otherwise be invisible.
- Tools: search = hmmsearch, hmmfetch, bedtools (helper/hmmsearch.py); cluster = samtools,
  diamond, mcl. step1.nf CLUSTER's HG-FASTA output is `optional: true`.
- The 18 SLC families already have search + cluster outputs in v3 (04/10/2026), so the real
  check compares against those instead of "nothing (new)".
```

- [ ] **Step 5: Run both suites** — Expected: `245 passed` on both.

- [ ] **Step 6: Commit**

```bash
git add step1.nf phylocli/README.md docs/superpowers/specs/2026-10-04-phylocli-step1-design.md \
        phylocli/tests/test_step1.py
git commit -m "step1.nf: SEARCH/CLUSTER call phylocli/stages/{search,cluster}.sh (HG FASTAs optional); phylocli step1 docs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Controller steps (not part of any task)

### C1: `step1.nf -preview` locally (after Task 7, no go needed — writes only to scratch)

```bash
WT=~/Documents/projects/phylogenies/phylocli-wt
SCR=<controller scratchpad>/step1_preview; mkdir -p "$SCR" && cd "$SCR"
nextflow run "$WT/step1.nf" -preview --genefam_info "$WT/data/gene_families_searchinfo.csv"
```

Expected: no compile error; the run lists the families as to-do (no `results/` in `$SCR`) and executes nothing. `.nextflow/` and `.nextflow.log` land in `$SCR`, not in the worktree.

### C2: Real check (needs Grygoriy's go; ≤ 4 threads)

1. Measure: `uptime; top -bn1 | head -12; ps -eo pid,etime,pcpu,cmd --sort=-pcpu | head -10`. Pick `T` ≤ 4 (less if `%Cpu(s)` idle is low) and say "running search/cluster on T threads; measured X % idle, …".
2. Layout (read-only use of `$V3`; `PYTHONDONTWRITEBYTECODE=1` so no `__pycache__` is written into `$V3/phylogeny/helper` on the mount):

```bash
V3=~/ant/gzolotarov/projects/2022_scRNAseq_Mlei/Phylogenies_v3
WT=~/Documents/projects/phylogenies/phylocli-wt
SCR=<controller scratchpad>/step1_real; mkdir -p "$SCR/project" "$SCR/results/search" "$SCR/results/clusters"
ln -s "$V3/phylogeny" "$SCR/project/phylogeny"; ln -s "$WT/workflow" "$SCR/project/workflow"
export PATH=~/mambaforge/envs/phylo/bin:$PATH PYTHONDONTWRITEBYTECODE=1     # phylo env: ete3/Bio/yaml, hmmsearch, diamond, mcl
which hmmsearch hmmfetch bedtools samtools diamond mcl && PYTHONNOUSERSITE=1 python -c "import ete3, Bio, yaml"
```

3. Run (families: `slc.SLC41` — new SLC, 74 seqs, 3 HGs in v3's tsv of which 1 FASTA; `neu.CASKin` — older, 5 seqs, 1 HG):

```bash
cd "$WT" && python3 - "$SCR" "$V3" T <<'EOF'
import sys, yaml
from pathlib import Path
scr, v3, t = sys.argv[1], sys.argv[2], int(sys.argv[3])
sys.path.insert(0, ".")
from phylocli import core, runner
raw = yaml.safe_load(open("phylocli/config.yaml"))
raw["outdir"] = f"{scr}/results"
raw["params"].update(genefam_info=f"{v3}/data/gene_families_searchinfo.csv", infasta=f"{v3}/data/input.fasta",
                     pfam_db=str(Path.home() / "ant/gzolotarov/databases/Pfam/Pfam-A.hmm"),
                     s1_ncpu=t, s2_ncpu=t, min_seqs=5, min_distinct=4)
cfg = core.config_from_raw(raw)
runner.ROOT = Path(scr) / "project"
for fam in ("slc.SLC41", "neu.CASKin"):
    for st in ("search", "cluster"):
        print(fam, st, runner.run_one(cfg, st, fam, Path(scr) / "work"))
EOF
```

4. Compare (numbers go in the report):

```bash
for f in slc.SLC41 neu.CASKin; do
  diff <(grep '>' $SCR/results/search/$f.domains.fasta | sort) <(grep '>' $V3/results/search/$f.domains.fasta | sort) && echo "$f domains: same"
  python3 - "$SCR/results/clusters/${f}_cluster.tsv" "$V3/results/clusters/${f}_cluster.tsv" <<'EOF'
import sys, collections
def groups(p):
    g = collections.defaultdict(set)
    for l in open(p):
        if l.strip():
            hg, m = l.split("\t")[:2]; g[hg].add(m.strip())
    return {frozenset(v) for v in g.values()}
a, b = groups(sys.argv[1]), groups(sys.argv[2])
print(f"HGs {len(a)} vs v3 {len(b)}; identical membership: {a == b}")
EOF
  ls $SCR/results/clusters | grep "^$f\.HG"; ls $V3/results/clusters | grep "^$f\.HG"
done
```

Expected: identical domains, identical HG membership, and the same HG FASTAs as v3 (SLC41: HG1 only). If the domains differ, first suspect the Pfam release (the local `Pfam-A.hmm` is from 03/10/2025; the cluster's `/users/asebe/xgraubove/data/pfam/Pfam-A.hmm` may differ) and isolate `cluster`: copy `$V3/results/search/<id>.domains.fasta` into `$SCR/results/search/`, delete `$SCR/results/clusters/<id>*`, rerun only `cluster`, compare again. Nothing is written under `$V3`.

### C3: Deploy to v3 (needs Grygoriy's go)

Array tasks import `phylocli/*.py` when they start, so a file-by-file copy can hand a task that starts mid-copy a mix of old and new modules. Swap the whole directory in one `mv` instead.

1. Preconditions: `git -C $WT status` clean and the plan's last commit is HEAD; `squeue --me -h -o "%i %j"` shows no `phylo-*` task about to start, or accept that queued tasks pick up the new tree (they read their run's `config.yaml`, which old code also wrote); **no step1.nf run active**: `tail -1 $V3/.nextflow/history` does not end a step1.nf line with status `-`, and `squeue --me` shows no `nf-SEARCH_*` / `nf-CLUSTER_*` job.
2. Stage the new tree next to the old one, committed files only:
   ```bash
   D=<yyyymmdd of the copy>; S=<controller scratchpad>/deploy-$D
   mkdir -p $S && git -C $WT archive HEAD phylocli workflow/report_status.py workflow/drop_small_hgs.py step1.nf | tar -x -C $S
   cp -r $S/phylocli $V3/phylocli.new
   ```
3. Swap (keeps `runs/` and `history/`, which only exist in the live tree):
   ```bash
   cd $V3
   mv phylocli/runs phylocli.new/runs && mv phylocli/history phylocli.new/history
   mv phylocli phylocli.old-$D && mv phylocli.new phylocli
   ```
   (`runs/` is moved, not copied: `jobs.tsv` paths of running arrays resolve through the run dir name, `common.ids_path`.) Rollback: the same two `mv`s the other way round, moving `runs/` / `history/` back.
4. `cp step1.nf step1.nf.bak-$D` (spec names `step1.nf.bak-20261004`; use the actual date), then `cp $S/step1.nf step1.nf` and `cp $S/workflow/{report_status,drop_small_hgs}.py workflow/` (only after step 1's "no step1.nf run active" check). `nextflow.config` is unchanged and not copied.
5. On the login node in v3: `nextflow run step1.nf -preview` (expect every family "skip (already complete)" except the cluster-ready ones), `phylocli/phylo missing` (expect the family rows, `warning: duplicate family ids ... (2): neu.Synapsin slc.SLC44; the last row of each is used ...` and `warning: family name CSD is listed under 2 prefixes (rbp, tfs); ...`), `phylocli/phylo missing cluster` (expect `adh.immunoglobin` — `sig.Pkinase` was clustered by the 09/10/2026 00:17 step1.nf run; re-measure first — large families; 300 MB / 10 min will likely need `--mem/--time`).
6. Tell Grygoriy: the duplicate rows and the `CSD` name collision stay warnings until `data/gene_families_searchinfo.csv` is fixed (out of scope here); `rbp.CSD`'s "no hits" in `results/search/` is false (its hits are in `tfs.CSD.*`).

---

## Self-review (09/10/2026)

**Spec coverage**

| spec item | task |
|---|---|
| family id = col 1 + last non-empty field; blank lines; trailing tabs | T1 (`parse_genefam`, tests) |
| duplicate ids (spec amended: a warning, decided by Grygoriy 09/10/2026); name under two prefixes warned | T1 (`family_warnings`, `name_collisions`), T2/T4 (validate/select proceed), T3 (`search.sh` WARNING), T5 (every family command + summaries), T6 (banner) |
| HG ids stay the step2 unit | T2 (`HG_STAGES`, HG loops untouched) |
| stage table: done / ready / inputs / publish dir / marker order | T2 (core), T3 (publish-order tests) |
| scripts = step1.nf bodies; step1.nf calls them; skip logic unchanged; backup | T3, T7, C3 |
| search stages the CURRENT genefam file, recorded in the run config | T4 (`write_run` snapshot) |
| small clusters not written; same rule as `count_seqs`/`count_distinct`; tsv complete; message; step1.nf reads `params.min_seqs/min_distinct` | T2 (`passes`), T3 (`drop_small_hgs.py`, tests), T7 |
| config values | T1 |
| resources + `--mem/--time/--cpus`; `--ids`, `--set` for family ids | T2, T5 (`test_submit_cluster_overrides`, `test_submit_family_ids_file_set_and_cpus`) |
| `STAGES` order | T2 |
| `missing` summary: families, blank line, HG stages, cluster "no hits" | T4 (`stage_rows`), T5 |
| `missing search|cluster [-f] [--all]`; `--per-fam` error | T5 |
| `submit` rules for family ids | T4, T5 |
| `status <family id>` (Nextflow SEARCH/CLUSTER + phylocli) | T4 (`family_attempts`), T5 |
| `jobs` unchanged | T5 (`test_submit_search_real` checks the row) |
| data layer: `stage_rows`, `hg_rows`, `select`/`plan` (+ `family_states`, families in `group_rows`) | T4 |
| TUI (overview at `446c599`): search/cluster columns first, counted in families from the CLI's code path; family-only groups; `enter` lists families; stages panel per unit; detail with HG count | T6 |
| tool preflight | T4, T5 |
| tests on fixtures, both interpreters; cluster fixture 1/4/5/5-identical | T1-T7 |
| real check; `step1.nf -preview` | C1, C2, C3 |
| out of scope: genefam file not edited | C3 step 4 (reported only) |

**Placeholder scan:** no TBD/TODO; every code step shows the code; the only `<…>` are controller-side values (scratchpad path, copy date, thread count T) that must be filled at run time.

**Type consistency:** `ov_column(stage)`, `stage_at_column(col)`, `OV_COLUMNS`, `family_ids(cfg, strict)` (strict = missing file only), `name_collisions(path)`, `family_warnings(cfg, collisions=True)`, `_warn_families(cfg, collisions)`, `family_done(cfg, families)` (keys `search/cluster/no_hits/hits`), `hg_fasta_families(cfg)`, `unit(stage)`, `stage_rows(cfg, exp, fams=None)`, `StageRow.no_hits`, `family_states(cfg, fams, lv)`, `fam_group_key(fam, by)`, `group_rows(..., fams=None, fstates=None)`, `GroupRow.n_fams`, `TUI_STAGES`, `_ov_inputs = (exp, states, fams, fstates)`, `family_attempts(cfg, fam=None, warn=None)`, `preflight(stage, cfg=None)`, `_preflight(stage, cfg=None)`, `_missing_fams(cfg, stage, ids, ready=False, fam=None)`, `_detail_text(hg)` — same names and arguments in every task that uses them.

**Expected test counts:** 195 at HEAD `9e0ef8c` → 202 (T1) → 209 (T2) → 217 (T3) → 226 (T4) → 241 (T5) → 244 (T6) → 245 (T7). If a count differs only because a test was split or merged, the suite still must be all-pass on both interpreters.

---

## Changelog (plan check 09/10/2026)

Factual staleness only (HEAD `446c599` → `f627245`); no design decision changed.
- Header: HEAD `f627245`; what `5104b0e` / `f627245` changed; line numbers are at `f627245`.
- Measured facts: test baseline 183 → **188**; `$V3` genefam file 353 non-blank rows; `$V3/results` 319 `_cluster.tsv`, only `adh.immunoglobin` has hits without a tsv (`sig.Pkinase` clustered 09/10/2026 00:17); C3 step 3 updated to match.
- Global Constraints: "183 at `446c599`" → "188 at `f627245`".
- Expected counts: T1 195, T2 202, T3 210, T4 220, T5 232, T6 234, T7 235 (per-task deltas unchanged: +7 +7 +8 +10 +12 +2 +1).
- Task 2 `tui.py` line refs: 64→65, 121→123, 202→207, 206→211, 248→253, 255-256→260-261, 267→285, 298→318, 338→358, 363→383; `TUI_STAGES` goes after lines 28-29. `model.py` / `phylo.py` / `history.py` refs re-checked, unchanged.
- Task 3: `runner.py:21-27` → `:20-26`.
- Task 6 Behaviour: the HG view's filter on `enter` is auto-picked (`_auto_pick_filter`, `5104b0e`), not fixed to `failed`.
- NOT fixed here (findings for the plan author): Task 2 breaks three existing TUI tests until Task 6; Task 4's `test_family_rows_states` needs `submit search` (only enabled in Task 5); uncommitted `actionable`-filter edits in the worktree's `tui.py` / `test_tui.py` move Task 6's anchors.

### Changelog (plan author, 09/10/2026, against HEAD `4867d41`, baseline 189)

- C1: Task 2 now also edits `test_enter_on_stage_cell_opens_that_stage_with_failed_filter`, `test_open_group_without_failures_picks_first_nonempty_filter`, `test_stages_panel_shows_group_counts` to index with `tui.TUI_STAGES` (right before and after Task 6); listed in Global Constraints.
- C2: `test_family_rows_states` moved from Task 4 to Task 5 (it submits `search` through the CLI, accepted only from Task 5).
- I3: Task 6 rebased on `4867d41`: `visible()` keeps the `actionable` branch, the footer keeps "default view: failed+ready", the family TUI test expects `actionable` on open then `f` → `failed`; Task 2 tui line refs moved to `4867d41`.
- I4: C3 is an atomic directory swap (`git archive` → `phylocli.new`, move `runs/` + `history/`, two `mv`s, rollback), with squeue and "no step1.nf run active" checks before `step1.nf` is replaced.
- M6: `set -euo pipefail` listed as a deliberate deviation in Task 3.
- M7: `test_open_group_restricts_hgs_and_esc_returns` uses `2 + tui.TUI_STAGES.index("tree")` (the cell it opens today) in Task 2; Task 5 adds `test_submit_family_ids_file_set_and_cpus` (`--ids`, `--set`, `--cpus`, bad `--set`).
- I5: duplicates handling and the `rbp.CSD` refusal were left for Grygoriy; resolved in the next entry (both: warning).
- Counts: 189 → T1 196, T2 203, T3 211, T4 220 (+9), T5 234 (+14), T6 236, T7 237.

### Changelog (plan author, 09/10/2026: Grygoriy's two decisions)

- Duplicate family ids — decided by Grygoriy 09/10/2026: warning. Never an error anywhere: `family_ids` no longer raises on duplicates (`FamilyError` = missing genefam file only); new `core.family_warnings` / `core.name_collisions`; the summaries, the TUI banner and every family command (`missing search|cluster`, `submit search|cluster`, `status FAMILY`) print the warning and proceed; the last row is used, as main.py / step1.nf do. Tests: `test_family_ids_strict_lists_duplicates` → `test_duplicates_and_name_collisions_are_warnings` (T1), `test_validate_family_duplicates_raise` → `..._proceed` (T2), `test_select_family_duplicates_is_error` → `..._proceed` (T4), `test_duplicates_warn_in_summary_and_refuse_family_commands` → `test_duplicates_warn_and_proceed` (T5); `test_parse_genefam_duplicates` also checks `name_collisions`.
- Family name under two prefixes (`CSD`) — decided by Grygoriy 09/10/2026: warning. `search.sh` keeps step1.nf's empty result and prints a `WARNING` naming the id the hits went to; the summaries, the TUI banner and `submit search` list each collision. Tests: `test_search_family_main_py_cannot_resolve_fails` → `test_search_name_under_two_prefixes_warns_and_publishes_empty` (T3); new `test_name_collision_warnings` (T5).
- The spec's duplicate line is amended (warning) and a name-collision line added.
- Counts: 189 → T1 196, T2 203, T3 211, T4 220, T5 235 (+15), T6 237, T7 238.

### Changelog (plan author, 09/10/2026: overview step1/step2 separation)

- Task 6 implements Grygoriy's step1/step2 separation: a two-row overview header from the column labels (`header_height=2`; `step1 ·` / `families` over search / cluster, `step2 ·` / `HGs` over align / tree), and a `│` separator column between cluster and align. `OV_COLUMNS` + `stage_at_column` are the one column→stage mapping (enter, cursor restore, the coming `s` sort); `enter` on the separator opens the current stage; a refill never restores the cursor onto it. New test `test_tui_overview_step1_step2_separator`; the family overview test checks the labels.
- Task 2 adds `tui.ov_column(stage)` and the three changed TUI tests use it (separator-proof), instead of `2 + TUI_STAGES.index(...)`.
- HEAD `9e0ef8c`, baseline 195; Task 2 line refs moved (`phylo.py` 181/198, `tui.py` +3…+7).
- Counts: 195 → T1 202, T2 209, T3 217, T4 226, T5 241, T6 244 (+3), T7 245.
