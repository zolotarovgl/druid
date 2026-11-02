# Results tab: every clustered HG, source per HG — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Results tab lists every clustered HG and shows, per HG, possvm if present, else possvm_prev, else the cluster's members.

**Architecture:** `druid/model.py` gains an `"auto"` source for `group_ogs` that lists `possvm/`, `possvm_prev/` and `clusters/` once each and picks per HG; `HGOgs` records which source it holds. `druid/tui.py` makes `"auto"` the default for both the Results tab and the Results window, shows a source column, and counts with-OGs / cluster-only per group.

**Tech Stack:** Python 3.9+, Textual 8.2, pytest (`python3 -m pytest -q -p no:cacheprovider`).

**Spec:** `docs/superpowers/specs/2026-11-02-druid-results-clusters-design.md`

## Global Constraints

- The tab only reads; nothing is written anywhere.
- Each results directory (`possvm/`, `possvm_prev/`, `clusters/`) is listed once per load (NFS), via `core.report_status.nonempty_files`.
- Source names: `"possvm"`, `"possvm_prev"`, `"cluster"`; mode names: `"auto"`, `"possvm"`, `"possvm_prev"`.
- Default mode is `"auto"`; the toggle cycles `auto -> possvm -> possvm_prev -> auto`.
- Cluster-only OG row name: `(not split: no possvm yet)`; its id is `<hg>.all`.
- HGs below `min_seqs` / `min_distinct` are listed; their source column reads `small`.
- Code must stay Python 3.9 compatible (the cluster's `phylo` env).

## Review Focus

1. An HG with possvm_prev only, in a project where other HGs have possvm: shown with its possvm_prev OGs (Task 1 test `test_group_ogs_auto_picks_per_hg`).
2. A cluster FASTA that is empty or has no `>` line: the HG is not listed (no row with 0 members) (Task 1, same test).
3. An unreadable `ortholog_groups.csv` in auto mode: that HG keeps its error row, it does not silently fall back to the cluster (Task 1 test `test_group_ogs_auto_error_does_not_fall_back`).
4. Sorting the OGs pane by `og` with a cluster-only row (`<hg>.all`): no crash (Task 1 test `test_og_sort_key_cluster_row`).
5. Origins never computed for cluster-only rows (Task 1 test in `test_og_origins_skip_cluster_rows`).

---

### Task 1: model — auto source, cluster members, group counts

**Files:**
- Modify: `druid/model.py` (`HGOgs` ~794, `group_ogs` ~874, `og_group_rows` ~981, `og_origins` ~1013)
- Test: `tests/test_model.py`

**Interfaces:**
- Produces:
  - `HGOgs(hg: str, ogs: list, error: str = "", source: str = "")` — `source` in `{"possvm", "possvm_prev", "cluster"}` (set by `group_ogs`).
  - `CLUSTER_OG_NAME = "(not split: no possvm yet)"`
  - `clustered_hgs(cfg: core.Config) -> set[str]` — stems of non-empty `<outdir>/clusters/*.fasta` (one listing).
  - `read_cluster_members(cfg: core.Config, hg: str) -> list[Member]` — gene ids from `>` lines of `<outdir>/clusters/<hg>.fasta` (id = first whitespace-separated token after `>`), species via `species_of`, `ref=""`, `ref_support=""`; `[]` when the file has no `>` line.
  - `group_ogs(cfg, hgs, source, progress=None, cancelled=None)` — `source="auto"` added; existing modes unchanged except rows carry `source`. In auto mode a row per HG with possvm (non-empty csv) else possvm_prev else a non-empty cluster: `HGOgs(hg, [OG(f"{hg}.all", CLUSTER_OG_NAME, members, None, "", "")], source="cluster")`; `missing` = HGs with none of the three. A csv that fails to parse gives the error row with that csv's source (no fall-back).
  - `og_sort_id(og: OG) -> int` — the number after the last `.`, `-1` when not digits; used by `read_ogs`' sort and by the TUI's `OG_KEYS["og"]`.
  - `OGGroupRow` fields: replace `with_output` by `with_ogs` (rows whose source is not `"cluster"`, unreadable included — a hand-built `HGOgs` with `source=""` counts here) and add `cluster_only` (rows with source `"cluster"`); `ogs`/`genes`/`zero` count OG rows only (not the cluster pseudo-OG).
  - `og_origins` skips rows with `source == "cluster"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_model.py` (reuse `write_results`, `og_csv`, `OG_HEAD`; write cluster FASTAs under `cfg.outdir / "clusters"`):

```python
def _clusters(cfg, **hgs):
    d = cfg.outdir / "clusters"
    d.mkdir(parents=True, exist_ok=True)
    for hg, text in hgs.items():
        (d / f"{hg}.fasta").write_text(text)


def test_group_ogs_auto_picks_per_hg(cli):
    cfg = _cfg()
    write_results(cfg)                       # HG1: possvm + prev; HG11: possvm only
    (cfg.outdir / "possvm_prev/tfs.A.HG2.treefile.ortholog_groups.csv").write_text(og_csv(
        [("Mlei_v05_G5", "tfs.A.HG2.0:like:X", "50.0", "NA", "NA")]))
    _clusters(cfg, **{"tfs.A.HG3": ">Mlei_v05_G7 desc\nMA\n>Hsap_ENSP9\nMB\n", "tfs.A.HG4": ""})
    hgs = ["tfs.A.HG1", "tfs.A.HG11", "tfs.A.HG2", "tfs.A.HG3", "tfs.A.HG4", "tfs.C_x.HG1"]
    rows, missing = model.group_ogs(cfg, hgs, "auto")
    assert [(r.hg, r.source) for r in rows] == [("tfs.A.HG1", "possvm"), ("tfs.A.HG2", "possvm_prev"),
                                               ("tfs.A.HG3", "cluster"), ("tfs.A.HG11", "possvm")]
    assert missing == 2                      # HG4 (empty fasta), C_x.HG1 (nothing)
    c = rows[2].ogs
    assert [(o.id, o.name, o.support) for o in c] == [("tfs.A.HG3.all", model.CLUSTER_OG_NAME, None)]
    assert [(m.gene, m.species) for m in c[0].genes] == [("Mlei_v05_G7", "Mlei"), ("Hsap_ENSP9", "Hsap")]
    assert [r.source for r in model.group_ogs(cfg, hgs, "possvm")[0]] == ["possvm", "possvm"]


def test_group_ogs_auto_error_does_not_fall_back(cli):
    cfg = _cfg()
    write_results(cfg)
    (cfg.outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv").write_text(OG_HEAD + "bad\n")
    _clusters(cfg, **{"tfs.A.HG11": ">Bova_x1\nM\n"})
    rows, _ = model.group_ogs(cfg, ["tfs.A.HG11"], "auto")
    assert rows[0].source == "possvm" and rows[0].ogs == [] and "cannot parse row" in rows[0].error


def test_clustered_hgs_one_listing(cli):
    cfg = _cfg()
    _clusters(cfg, **{"tfs.A.HG3": ">a\nM\n", "tfs.A.HG4": ""})
    assert model.clustered_hgs(cfg) == {"tfs.A.HG3"}


def test_og_sort_key_cluster_row():
    assert model.og_sort_id(model.OG("x.HG1.all", "", [], None, "", "")) == -1
    assert model.og_sort_id(model.OG("x.HG1.12", "", [], None, "", "")) == 12


def test_og_origins_skip_cluster_rows():
    class T:
        def origin(self, sps):
            return "o"
    og = model.OG("h.all", model.CLUSTER_OG_NAME, [model.Member("Mlei_1", "Mlei", "", "")], None, "", "")
    assert model.og_origins([model.HGOgs("h", [og], source="cluster")], T()) == {}
```

  And update `test_og_group_rows_sums_per_group`: `with_output` -> `with_ogs`, and add a cluster row:

```python
    rows.append(model.HGOgs("tfs.A.HG3", [model.OG("tfs.A.HG3.all", model.CLUSTER_OG_NAME,
                [model.Member("Mlei_1", "Mlei", "", "")], None, "", "")], source="cluster"))
    exp = exp | {"tfs.A.HG3"}
    # ALL: hgs 4, with_ogs 3, cluster_only 1, ogs 3, genes 7 (the cluster row not counted)
```

  with the ALL tuple asserted as `("ALL", 4, 3, 1, 3, 7, 1, 1)` over `(group, hgs, with_ogs, cluster_only, ogs, genes, zero, unreadable)`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_model.py -k "auto or clustered or og_sort or skip_cluster or og_group_rows"`
Expected: FAIL (`group_ogs` has no auto mode; `clustered_hgs` / `og_sort_id` / `CLUSTER_OG_NAME` undefined).

- [ ] **Step 3: Implement** the Interfaces above in `druid/model.py`. In auto mode list the three directories once each (`nonempty_files`), then per HG try `read_ogs(..., "possvm", names_possvm)`, then possvm_prev, then the cluster FASTA when its name is in the clusters listing. Grep `with_output` in `druid/` and `tests/` and rename every use to `with_ogs` (the TUI's `RT_COLS` is Task 2's; rename the attribute reference there only, so the suite stays green).

- [ ] **Step 4: Run the model tests, then the whole suite**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_model.py` then `python3 -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add druid/model.py druid/tui.py tests/test_model.py
git commit -m "model: auto source per HG (possvm > possvm_prev > cluster), cluster members, with_ogs / cluster_only counts"
```

### Task 2: TUI — auto by default, source column, all clustered HGs, docs

**Files:**
- Modify: `druid/tui.py` (`RES_COLS` ~223, `OG_KEYS` ~234, `RT_COLS` ~254, `_load_rtab` ~1071, `_fill_rtab` ~1110, `_open_results` ~1586, `_load_results` ~1616, `_apply_results`, `_fill_res`, `_fill_ogs`, `action_toggle_source` ~1945, `_possvm_sig` ~138)
- Modify: `README.md` (section `## druid tui`, Results parts)
- Test: `tests/test_tui.py`

**Interfaces:**
- Consumes (Task 1): `group_ogs(..., "auto")`, `HGOgs.source`, `clustered_hgs`, `og_sort_id`, `CLUSTER_OG_NAME`, `OGGroupRow.with_ogs` / `.cluster_only`.
- Produces: `SOURCE_MODES = ("auto", "possvm", "possvm_prev")`; `rt_source` / `res_source` default `"auto"` (no longer `None` -> `default_source`); `RES_COLS` gains `SortCol("source", "source")` after `HG`; `RT_COLS` = group, HGs, `with OGs` (`with_ogs`), `cluster only` (`cluster_only`), OGs, genes, ⚠ sup 0.

- [ ] **Step 1: Write the failing tests** in `tests/test_tui.py`, using the module's existing results fixtures (the `write_results` pattern) plus a cluster FASTA:
  - `test_results_auto_lists_prev_only_and_cluster_only_hgs`: with HG1 possvm, HG2 possvm_prev only, HG3 cluster only, open the Results window on `ALL` -> `#res` rows include all three; the `source` cells read `possvm`, `prev`, `cluster`; highlighting HG3 fills `#ogs` with one row named `CLUSTER_OG_NAME` and `#members` with its genes.
  - `test_results_small_hg_marked`: a clustered HG not in the expected set (below `min_seqs`) is listed with source `small`.
  - `test_source_toggle_cycles_three_modes`: the toggle key in the Results window goes `auto -> possvm -> possvm_prev -> auto` (assert `app.res_source` after each); in `possvm` mode HG2 and HG3 are not listed.
  - `test_results_tab_counts_with_ogs_and_cluster_only`: the Results tab `ALL` row shows `with OGs` and `cluster only` counts matching the fixture; border title contains `auto`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_tui.py -k "auto_lists or small_hg or cycles_three or with_ogs_and_cluster"`
Expected: FAIL.

- [ ] **Step 3: Implement.** `res_hgs` is `expected ∪ clustered_hgs(cfg)` filtered by group; `clustered_hgs` is read in the workers (never on the UI thread) and cached on the app, refreshed by every `_load_rtab` / `_load_results`. The source cell shows `prev` for possvm_prev and `small` for an HG outside the expected set. `_possvm_sig` also tracks finished `cluster` outputs so the caches go stale on a new cluster. `_apply_results`' empty note becomes `no clustered HGs yet` in auto mode. Update the README Results description (source per HG, the toggle's three modes, the new columns).

- [ ] **Step 4: Run the TUI tests, then the whole suite**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_tui.py` then `python3 -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add druid/tui.py tests/test_tui.py README.md
git commit -m "TUI Results: auto source per HG by default, source column, clustered-only HGs listed"
```
