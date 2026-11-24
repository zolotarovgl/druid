# Consensus Species Tree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 205-tip consensus species tree pair (origin + binary) from `latest.newick`, the shipped v3 tree, chromo94 and the planarian clade; ship it as druid's default tree; rename `v3` → `default` / `@v3` → `@all`; file and plot it in Grygoriy's `species_tree/` folder.

**Architecture:** A rebuildable dev script `tools/build_species_tree.py` (outside the `druid/` package, so outside the write-boundary lint) reads frozen inputs from `tools/species_tree/inputs/`, grafts with `druid.sptree.carry_to_origin`, and writes `druid/data/species_tree.newick` + `species_tree.binary.newick`. A test rebuilds and compares byte for byte. The Setup TUI / species-set code only changes names.

**Tech Stack:** Python 3.9-compatible, ete3 3.1.3 (newick `format=1`), pytest, Textual (existing TUI).

**Spec:** `docs/superpowers/specs/2026-11-24-consensus-species-tree-design.md`

## Global Constraints

- Python 3.9 compatible (the cluster `phylo` env).
- Newick read/written with ete3 `format=1`, root name written (`format_root_node=True`), as `druid/sptree.py` does.
- Frozen-input md5s: `latest` `205631b2efb8f8e17a3a94cf858fae70`; v3 origin `95521216cef1137d35a9e95f515033c3`; chromo94 `5a8e45f5fc151b31897b525c3ba74a4c`.
- Planarian clade: `((((Smed,Spol),(Djap,Dugjap)),Gtig),Pnig)`; names Smed *Schmidtea mediterranea*, Spol *Schmidtea polychroa*, Djap *Dugesia japonica*, Gtig *Girardia tigrina*, Pnig *Polycelis nigra*.
- Expected result: 205 unique tips; all branch lengths 1; binary polytomy resolutions length 0.
- Ctenophore source string for SOURCE/README: Whelan et al. 2017, Nat Ecol Evol 1:1737–1746, doi:10.1038/s41559-017-0331-3, Fig. 3.
- Dates in docs and SOURCE as dd/mm/yyyy.
- Before every commit: `python3 -m pytest -q -p no:cacheprovider -rf 2>&1 | grep -E "passed|failed"` — all pass (baseline 826 passed, 1 skipped).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- Nothing under `druid/` may write files except through `druid/paths.py` (`tests/test_write_boundary.py`); the build script lives in `tools/`.

## Review Focus

1. A grafted tip whose sister set never becomes placeable → `ValueError` naming the tip, no endless loop (Task 1 test).
2. The backbone's MRCA of Smed and Dugjap is not exactly `{Smed, Dugjap}` → `ValueError` (Task 1 test).
3. Backbone and v3 ctenophore tip sets differ → `ValueError` listing the difference (Task 1 test).
4. A user types the old `@v3` in the Species filter → the error names `@all`, not "file not found" (Task 3 test).
5. Shipped files drift from what the script builds → the rebuild test fails (Task 2 test).

---

### Task 1: Build script and frozen inputs

**Files:**
- Create: `tools/build_species_tree.py`
- Create: `tools/species_tree/inputs/latest_20251014.newick` (byte copy of `/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-2022-Mlei/0a22b1f8-b83b-4910-996d-6e5ecad4a2e0/scratchpad/sptree/latest.newick`; md5 above)
- Create: `tools/species_tree/inputs/v3_origin.newick` (byte copy of the current `druid/data/species_tree.newick`)
- Create: `tools/species_tree/inputs/planarians.tsv` (`code<TAB>Latin name`, the five rows from Global Constraints)
- Create: `tools/species_tree/README.md` (what the inputs are, their origin paths, md5s, how to rebuild)
- Test: `tests/test_species_tree_build.py`

chromo94 is read from `druid/data/species_tree.chromo94.newick` (shipped, unchanged).

**Interfaces:**
- Produces (in `tools/build_species_tree.py`, importable from tests via `sys.path` insert of `tools/`):
  - `PLANARIANS = "((((Smed,Spol),(Djap,Dugjap)),Gtig),Pnig);"`
  - `build(latest: str, v3: str, chromo: str) -> tuple[str, str, list[str]]` — newick texts in; returns `(origin_newick, binary_newick, report_lines)`.
  - `clades(newick: str, keep: set) -> set[frozenset]` — the non-trivial clades (2 ≤ size < |keep|) of the tree pruned to `keep`.
  - `species_report(tips: list, taxonomy_tsv: Path, extra_names: dict) -> list[str]` — lines for codes sharing a binomial (first two words of col 2, lower-case, punctuation stripped) and codes with no row.
  - CLI: `python3 tools/build_species_tree.py --out-dir DIR` writes `DIR/species_tree.newick` and `DIR/species_tree.binary.newick` and prints the report; `--check DIR` writes nothing and exits 1 if either file differs from a fresh build.
- Consumes: `druid.sptree.carry_to_origin(newick, tipset, new) -> str`.

Build order inside `build` (spec "Build rules"): (1) backbone = latest; replace the subtree at MRCA(`Eupdun`,`Mlei`) by v3's subtree at MRCA(`Eupdun`,`Mlei`) after asserting both have the same 16 tips; (2) graft v3-only tips, then chromo-only tips, in source-tree leaf order; `sister_set` = leaves of the tip's parent in its source tree minus the tip, intersected with tips already placed; empty → retry next pass. Source parent with 2 children → `carry_to_origin(current, sister_set, tip)`. Source parent with >2 children (a polytomy) → if `sister_set` is one tip, `add_sister`; else add the tip as one more child of the current tree's MRCA of `sister_set` — so v3's `(Hvul,Hydrsy,Turdoh)` stays a polytomy instead of gaining a `(Hvul,Hydrsy)` clade; a pass that places nothing → `ValueError(f"cannot place: {names}")`; (3) the node at MRCA(`Smed`,`Dugjap`) must have exactly those two tips, else `ValueError`; replace it with `PLANARIANS`, keeping its name; (4) clear all internal names, then name each node = MRCA in the consensus of a named source clade's tips, precedence v3 > latest > chromo94, a node already named keeps its name; a name already used on another node gets `.2`, `.3` … in preorder; each rename is a report line; (5) every branch length 1, root 0; (6) binary = origin with `resolve_polytomy(recursive=True, default_dist=0.0)`; report the number of polytomies resolved; (7) `species_report` lines appended (taxonomy `druid/data/genome_sources.tsv` + `planarians.tsv`).

- [ ] **Step 1: Write the failing tests** in `tests/test_species_tree_build.py`, reading the frozen inputs and chromo94:

```python
def test_inputs_md5():  # the three md5s from Global Constraints

def test_tips_and_binary():
    o, b, _ = build(LATEST, V3, CHROMO)
    to, tb = tip_list(o), tip_list(b)
    assert len(to) == 205 == len(set(to)) and set(to) == set(tb)
    assert has_polytomy(o) and not has_polytomy(b)

def test_v3_topology_kept():
    o, _, _ = build(LATEST, V3, CHROMO)
    assert clades(o, tips(V3)) == clades(V3, tips(V3))

def test_latest_kept_outside_ctenophores():
    o, _, _ = build(LATEST, V3, CHROMO)
    L = tips(LATEST); cten = tips_under(LATEST, "Eupdun", "Mlei")   # 16 tips
    strip = lambda cs: {c for c in cs if not c < cten}
    assert strip(clades(o, L)) == strip(clades(LATEST, L))

def test_no_conflict_with_chromo94_outside_ctenophores():
    # every clade of o pruned to chromo tips is compatible with chromo's, ignoring clades
    # strictly inside the ctenophores: chromo94 shares latest's ctenophore topology, which
    # Whelan 2017 contradicts (measured 24/11/2026: v3 vs chromo94 conflict only there)

def test_ctenophores_follow_whelan():
    o, _, _ = build(LATEST, V3, CHROMO); c = clades(o, tips(o))
    assert frozenset({"Drygla","Beraby","Berfor","Berova"}) in c
    assert frozenset({"Drygla","Beraby","Berfor","Berova","Bolinf","Bolmic","Mlei"}) in c

def test_planarian_clade():
    # clades {Smed,Spol}, {Djap,Dugjap}, {Smed,Spol,Djap,Dugjap}, +Gtig, +Pnig present;
    # the 6-tip node is named "Tricladida"

def test_names():
    # MRCA(Hsap,Mmus) named "Euarchontoglires"; MRCA(Drygla,Beraby) named "Beroida_Dryodora";
    # no internal name used twice in o

def test_cannot_place_raises():
    # V3 with an extra tip whose only sister is another tip absent everywhere → ValueError "cannot place"

def test_bad_tricladida_raises():
    # LATEST with Dugjap moved out of Tricladida → ValueError

def test_ctenophore_mismatch_raises():
    # V3 with Lampan renamed Lampx → ValueError listing Lampan / Lampx

def test_species_report_lists_duplicates():
    _, _, rep = build(LATEST, V3, CHROMO)
    txt = "\n".join(rep)
    assert "Djap" in txt and "Dugjap" in txt and "Bflo" in txt and "Bflz" in txt
    for code in ("Avas", "Braflo", "Clad", "Halduj"):
        assert code in txt
```

- [ ] **Step 2: Run** `python3 -m pytest -q -p no:cacheprovider tests/test_species_tree_build.py` — Expected: FAIL (module missing).
- [ ] **Step 3: Copy the inputs and implement `tools/build_species_tree.py`** as specified above. Verify the md5 of each copied input before writing code.
- [ ] **Step 4: Run** the test file — Expected: all PASS. Then the full suite (Global Constraints).
- [ ] **Step 5: Commit** — `git add tools/ tests/test_species_tree_build.py` · message `species tree: consensus build script (latest + v3 ctenophores + chromo94 + planarians), frozen inputs`.

---

### Task 2: Ship the consensus pair

**Files:**
- Modify: `druid/data/species_tree.newick`, `druid/data/species_tree.binary.newick` (written by the script)
- Modify: `druid/data/SOURCE`
- Modify: tests whose premise was the 59-tip shipped tree (find them by running the full suite after the swap)
- Test: `tests/test_species_tree_build.py` (add the rebuild test)

**Interfaces:**
- Consumes: Task 1 CLI `--out-dir` / `--check`.
- Produces: shipped files with 205 tips; `SOURCE` rows for both.

- [ ] **Step 1: Add the failing test**

```python
def test_shipped_matches_rebuild():
    r = subprocess.run([sys.executable, str(TOOLS / "build_species_tree.py"), "--check",
                        str(DRUID_HOME / "druid/data")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
```

- [ ] **Step 2: Run it** — Expected: FAIL (shipped files are still v3).
- [ ] **Step 3: Run** `python3 tools/build_species_tree.py --out-dir druid/data` and keep its report output for SOURCE.
- [ ] **Step 4: Rewrite the two v3 rows of `druid/data/SOURCE`**: built 24/11/2026 by `tools/build_species_tree.py` from `tools/species_tree/inputs/` (list the three inputs with md5s), ctenophores per the Whelan citation, 205 tips, new md5s, and one line that the v3 originals are kept as `tools/species_tree/inputs/v3_origin.newick` (origin) and `tests/data/species_tree.v3.newick`. Update the file's header count sentence to match.
- [ ] **Step 5: Run the full suite**; fix each failing test whose premise was the 59-tip tree (e.g. a species assumed absent from the base tree): change the fixture or the expected value, never the product code. List every test changed in the commit message body.
- [ ] **Step 6: Commit** — message `species tree: ship the 205-tip consensus pair as the default tree; SOURCE`.

---

### Task 3: Rename v3 → default, @v3 → @all

**Files:**
- Modify: `druid/setup_state.py:164-200` (`tree_base` returns `"default"`; `SPECIES_SETS = {"all": "data/base_tree.newick", "chromo": CHROMO_TREE}`; messages/docstrings)
- Modify: `druid/setup_tui.py` lines 2, 43-44, 131, 353, 373, 377, 1309-1329 (ids `rb-tree-default`; labels `default, 205 tips` / `default (205)`; `sets: @all (205) · @chromo (94) · …`; messages `tree_source cleared: the default tree`, `species tree: default (205 tips)`; placeholder `(tree_source; empty: the default tree)`)
- Modify: `docs/reference.md` (line 24 and every Setup › Tree / species-set mention of v3 curated / 59)
- Test: `tests/test_setup_state.py:266-289`, `tests/test_setup_tui.py` (every `rb-tree-v3`, `@v3`)

**Interfaces:**
- Consumes: shipped 205-tip tree (Task 2).
- Produces: `setup_state.tree_base(raw, root) -> "default" | "chromo" | "custom"`; `species_set("@all", root)`.

- [ ] **Step 1: Update/write the failing tests**

```python
def test_species_set_all(tmp_path):        # in test_setup_state.py, replacing the @v3 test
    codes, err = ss.species_set("@all", root)
    assert err == "" and len(codes) == 205 == len(set(codes))

def test_species_set_v3_points_to_all(tmp_path):
    codes, err = ss.species_set("@v3", root)
    assert codes == [] and "@all" in err

def test_tree_labels_match_shipped_tip_count():
    n = len(sptree.tips((DRUID_HOME / "druid/data/species_tree.newick").read_text()))
    assert f"{n} tips" in setup_tui.TREE_LABELS["default"]
```
Plus: every `#rb-tree-v3` → `#rb-tree-default`, `"@v3"` → `"@all"` in `tests/test_setup_tui.py`; `tree_base(...) == "default"` where `"v3"` was expected.

- [ ] **Step 2: Run** those files — Expected: FAIL.
- [ ] **Step 3: Implement the renames.** `@v3` (case ignored) returns `([], "@v3 is now @all (every species on the default tree)")` before the file lookup.
- [ ] **Step 4: Run** the files, then the full suite — Expected: PASS. `grep -rn '"v3"\|@v3\|v3 curated\|rb-tree-v3' druid/ docs/reference.md` returns only the `@v3` hint.
- [ ] **Step 5: Commit** — message `Setup: the shipped tree is "default"; @v3 -> @all (205); docs`.

---

### Task 4 (controller, cluster): file and plot in `species_tree/`

Not dispatched: writes into Grygoriy's cluster home, outside the repo. Run by the controller after Task 3.

- [ ] **Step 1:** Back up `/users/asebe/gzolotarov/species_tree/trees/latest.newick` as `latest.newick_backup_241126`; verify the backup's md5 is `205631b2efb8f8e17a3a94cf858fae70`.
- [ ] **Step 2:** Copy the shipped pair to `trees/holozoa_241126_prefixes.newick` and `trees/holozoa_241126_prefixes.binary.newick`; overwrite `trees/latest.newick` with the origin tree; verify md5s equal the shipped files.
- [ ] **Step 3:** Plot locally with the folder's own `plot.R` (cluster R has no ggtree; local ggtree 3.12.0): `Rscript plot.R holozoa_241126_prefixes.newick holozoa_241126_prefixes.pdf`, copy to `figs/`; confirm the PDF opens and shows 205 tips.
- [ ] **Step 4:** Add a `## 24.11.26` README entry: merged inputs, Whelan ctenophore source, planarian clade, the open duplicate codes, druid commit hash.
