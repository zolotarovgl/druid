# phylocli orthogroup origin (Dollo MRCA) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Results window's `OGs` pane shows each orthogroup's origin. The origin is the MRCA of its member species on `data/species_tree.newick` (strict Dollo). The column is sortable by depth and matched by `/`. The `species` pane title shows the origin too.

**Architecture:**
- A standard-library-only module `workflow/og_origin.py` does the work: a newick parser plus `OriginTree.origin(species) -> Origin(label, depth) | None`. step4 will later import it unchanged.
- `phylocli/model.py` reads the tree (`params.ORIGIN_TREE`) and maps OG ids to origins.
- `phylocli/tui.py`'s Results worker reads the tree once, off the UI thread, and computes the origins for the loaded rows. The pane shows them.

**Tech Stack:** Python ≥ 3.9, Textual 8.2.8 (`tui.py` only), pytest.

**Spec:** `docs/superpowers/specs/2026-10-11-phylocli-og-origin-design.md`

**Repo / branch:** worktree `~/Documents/projects/phylogenies/phylocli-wt`, branch `phylocli`, plan based on HEAD `90047c3` (360 tests).
- **Checked 11/10/2026:** the `og_origin.py` code of Task 1, run on the v3 tree, gives the exact values its tests assert.
- The prototype is at `/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-2022-Mlei/0a22b1f8-b83b-4910-996d-6e5ecad4a2e0/scratchpad/origin/`.

## Global Constraints

- `workflow/og_origin.py` imports only `__future__`, `collections`, `typing` (no ete3 / pandas / phylocli). Python 3.9-safe (`from __future__ import annotations`; no `match`; no `X | Y` outside annotations).
- Origin = MRCA of the member species that are tips of the origin tree. Species not on the tree are ignored. No member on the tree → `None`, shown `–`. Unreadable tree → every origin shown `?`, plus one notification per session (`_notify_once`).
- Label = node name. An unlabelled node is `~<nearest labelled ancestor>`. The unlabelled root is `root`. An unlabelled node with no labelled ancestor is `~root`. Depth = edges from the root (root = 0).
- Origin tree = `params.ORIGIN_TREE`, default `data/species_tree.newick` (relative to the repo root; added to `core.PATH_PARAMS`). `params.SPECIES_TREE` (binary) is unchanged and still drives the species pane.
- Species code = `model.species_of` (text before the first `_`), already in `Member.species`.
- Textual only in `tui.py`. The tree is read and origins are computed only in the Results worker thread, never on the UI thread.
- CLI output unchanged. Existing tests are unmodified, except the two lines of `test_o_on_overview_opens_results_for_that_group` named in Task 3: the new column and the new species title change exactly what they pin.
- Edit with the Edit/Write tools only. TDD: record the RED run.
- Both suites must pass before each commit:
  - `python3 -m pytest phylocli/tests -q -p no:cacheprovider`
  - `/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-phylogenies/3dad6ea4-c859-4fe6-b319-93a358944ac8/scratchpad/py39/bin/python -m pytest phylocli/tests -q -p no:cacheprovider`
- One commit per task on `phylocli`. Each message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Decisions taken while planning (spec silent or ambiguous)

1. **`members` gets no origin column.** Every row of `members` belongs to the highlighted OG, so the column would be one constant value. The origin goes into the `species` pane title instead: `species · HG1.0 · origin root`. The species pane is where the tree coverage already sits. The spec's members `/` match is dropped for the same reason. Grygoriy can overrule; the change is small.
2. **The `origin` column is last** in `OGs`, after `name`. Existing tests read cells by index (`[4]` = name), and appending keeps them valid.
3. **No new `OG` field.** Origins live in an app-level dict `{og.id: Origin | None}` (`self._origins`). The worker computes it for the rows it delivers, including rows taken from the Results-tab cache, so the cached `HGOgs` objects are never mutated.

## Review Focus

1. **The Results window opened from the Results-tab cache** (no second OG read): origins must still be computed. → Task 3, `test_origin_from_results_tab_cache`.
2. **A `config.yaml` without `ORIGIN_TREE`** (an older deployed config): falls back to `data/species_tree.newick` under the repo root. → Task 2, `test_origin_tree_path_default`.
3. **A member species not on the tree** (`Zzz` in the `possvm_prev` fixture): ignored, so the origin is that of the remaining species. → Task 2, `test_og_origins_ignore_species_off_the_tree`.
4. **The tree read on the UI thread** (NFS stall over SSH) must not happen. → Task 3, `test_origin_tree_read_off_the_ui_thread`.
5. **An OG with no species on the tree** (`–`) sorts after every placed OG, in both directions of the first press. → Task 3, `test_origin_sort_by_depth_and_filter`, with the `–` row.

---

## File Structure

| file | change | responsibility |
|---|---|---|
| `workflow/og_origin.py` | create | newick parse, MRCA, origin label/depth (stdlib only) |
| `phylocli/tests/data/species_tree.v3.newick` | create | copy of v3 `data/species_tree.newick` (11/10/2026) |
| `phylocli/tests/test_og_origin.py` | create | tests of `og_origin` |
| `phylocli/core.py` | modify `PATH_PARAMS` | `ORIGIN_TREE` resolved like other paths |
| `phylocli/config.yaml` | modify `params:` | `ORIGIN_TREE: data/species_tree.newick` |
| `phylocli/model.py` | append | `origin_tree_path`, `origin_tree`, `og_origins` |
| `phylocli/tests/conftest.py` | modify fixture | write a fixture origin tree, point `ORIGIN_TREE` at it |
| `phylocli/tests/test_model.py` | append | model tests |
| `phylocli/tui.py` | modify | worker, `_apply_results`, `_fill_ogs`, `_show_og`, `OG_COLS` |
| `phylocli/tests/test_tui.py` | append (+ 2 lines changed) | TUI tests |

---

### Task 1: `workflow/og_origin.py`

**Files:**
- Create: `workflow/og_origin.py`, `phylocli/tests/data/species_tree.v3.newick`, `phylocli/tests/test_og_origin.py`

**Interfaces:**
- Produces:
  - `og_origin.Origin`: a namedtuple `(label: str, depth: int)`.
  - `og_origin.parse_newick(text: str) -> Node`.
  - `og_origin.OriginTree(text: str)`, with `.tips -> frozenset[str]`, `.mrca(species) -> Node | None`, `.label(node) -> str` and `.origin(species: Iterable[str]) -> Origin | None`.
  - `workflow/` is already on `sys.path` once `phylocli.core` is imported (`core.py`: `sys.path.insert(0, str(ROOT / "workflow"))`), so tests and model use `import og_origin`.

- [ ] **Step 1: Copy the fixture tree**

```bash
mkdir -p phylocli/tests/data
cp ~/ant/gzolotarov/projects/2022_scRNAseq_Mlei/Phylogenies_v3/data/species_tree.newick phylocli/tests/data/species_tree.v3.newick
```
(1334 bytes, no trailing newline. `phylocli/tests/data/` must not be gitignored; check with `git check-ignore -v phylocli/tests/data/species_tree.v3.newick`, which must print nothing.)

- [ ] **Step 2: Write the failing tests** — `phylocli/tests/test_og_origin.py`:

```python
"""workflow/og_origin.py: strict Dollo origin (MRCA of the member species) on a species tree."""
import ast
from pathlib import Path

import pytest

from phylocli import core  # noqa: F401  (puts workflow/ on sys.path)
import og_origin  # noqa: E402
from og_origin import Origin, OriginTree, parse_newick  # noqa: E402

V3 = (Path(__file__).parent / "data/species_tree.v3.newick").read_text()


def test_v3_tree_tips_and_unlabelled_nodes():
    t = OriginTree(V3)
    assert len(t.tips) == 59 and {"Mlei", "Hsap", "Cowc", "Mbre"} <= t.tips
    unl, stack = [], [t.root]
    while stack:
        n = stack.pop()
        stack.extend(n.children)
        if n.children and not n.name:
            unl.append(sorted(c.name or "?" for c in n.children))
    assert sorted(unl) == [["?", "Pliv"], ["Choanozoa", "Cowc"], ["Lytvar", "Spur"]]


@pytest.mark.parametrize("species, expected", [
    (["Mlei"], Origin("Mlei", 8)),                                  # one species: its tip
    (["Mlei", "Mlei"], Origin("Mlei", 8)),
    (["Mbre", "Sros"], Origin("Choanoflagellata", 2)),
    (["Hvul", "Turdoh"], Origin("Anthoathecata", 9)),               # inside a 3-way polytomy
    (["Spur", "Pliv"], Origin("~Eleutherozoa", 10)),                # unlabelled node
    (["Spur", "Lytvar"], Origin("~Eleutherozoa", 11)),              # its unlabelled child
    (["Mlei", "Cowc"], Origin("root", 0)),                          # the unlabelled root
    (["Mlei", "Hsap"], Origin("Metazoa", 2)),
    (["Bolinf", "Mlei"], Origin("Ctenophora.Mlei_Bol", 7)),         # dots in labels
    (["Mlei", "Zzz"], Origin("Mlei", 8)),                           # off-tree species ignored
])
def test_origin_on_v3(species, expected):
    assert OriginTree(V3).origin(species) == expected


def test_origin_none_when_no_species_on_the_tree():
    assert OriginTree(V3).origin(["Zzz", "Yyy"]) is None
    assert OriginTree(V3).origin([]) is None


def test_unlabelled_without_labelled_ancestor_is_tilde_root():
    t = OriginTree("((a,b),c);")
    assert t.origin(["a", "b"]) == Origin("~root", 1)
    assert t.origin(["a", "c"]) == Origin("root", 0)


def test_parse_newick_lengths_whitespace_and_errors():
    r = parse_newick(" ((A:1, B:0.5)AB:2,\n C)Top;")
    assert r.name == "Top" and [c.name for c in r.children] == ["AB", "C"]
    assert [c.name for c in r.children[0].children] == ["A", "B"]
    assert parse_newick("A;").name == "A"
    for bad in ["", "((A,B);", "(A,B));", "(A,B);(C,D);"]:
        with pytest.raises(ValueError):
            parse_newick(bad)
    with pytest.raises(ValueError):
        OriginTree("(A,(A,B));")                                    # duplicate tip


def test_deep_tree_has_no_recursion_limit():
    text = "(" * 3000 + "A" + "".join(f",B{i})" for i in range(3000)) + ";"
    assert OriginTree(text).origin(["A"]).depth == 3000


def test_og_origin_imports_only_the_standard_library():
    tree = ast.parse(Path(og_origin.__file__).read_text())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"__future__", "collections", "typing"}
```

- [ ] **Step 3: Run, expect FAIL**: `python3 -m pytest phylocli/tests/test_og_origin.py -q -p no:cacheprovider` → `ModuleNotFoundError: No module named 'og_origin'`.

- [ ] **Step 4: Write `workflow/og_origin.py`**

```python
"""Origin of an orthogroup on a species tree: the most recent common ancestor (MRCA) of its
member species, i.e. the node of the single gain under Dollo parsimony (one gain, losses
only).  Standard library only, so the step4 workflow can import it unchanged.
Spec: docs/superpowers/specs/2026-10-11-phylocli-og-origin-design.md"""
from __future__ import annotations

from collections import namedtuple
from typing import Iterable, Optional

Origin = namedtuple("Origin", "label depth")     # depth = edges from the root (root = 0)


class Node:
    __slots__ = ("name", "children", "parent", "depth")

    def __init__(self, name: str = "", parent: "Optional[Node]" = None):
        self.name, self.children, self.parent = name, [], parent
        self.depth = 0 if parent is None else parent.depth + 1


def parse_newick(text: str) -> Node:
    """One newick tree: polytomies, branch lengths (dropped), internal labels (kept, dots
    included).  Iterative, so deep trees do not hit the recursion limit.  ValueError on an
    unbalanced or empty tree."""
    s = "".join(text.split())
    n, i = len(s), 0
    root: Optional[Node] = None
    cur: Optional[Node] = None

    def label(i: int):
        j = i
        while j < n and s[j] not in ",();":
            j += 1
        return s[i:j].split(":", 1)[0], j

    while i < n:
        c = s[i]
        if c == ";":
            break
        if c == "(":
            if root is not None and cur is None:
                raise ValueError("newick: text after the end of the tree")
            node = Node(parent=cur)
            if cur is None:
                root = node
            else:
                cur.children.append(node)
            cur, i = node, i + 1
        elif c == ",":
            if cur is None:
                raise ValueError("newick: ',' outside parentheses")
            i += 1
        elif c == ")":
            if cur is None:
                raise ValueError("newick: unbalanced ')'")
            cur.name, i = label(i + 1)
            cur = cur.parent
        else:
            name, i = label(i)
            if cur is None:
                if root is not None:
                    raise ValueError("newick: text after the end of the tree")
                root = Node(name)                 # a one-tip tree
            else:
                cur.children.append(Node(name, cur))
    if root is None:
        raise ValueError("newick: empty tree")
    if cur is not None:
        raise ValueError("newick: unbalanced '('")
    if i < n and s[i + 1:]:                        # anything after the first ';'
        raise ValueError("newick: text after the end of the tree")
    return root


class OriginTree:
    """A species tree to place orthogroups on.  `origin(species)` = Origin(label, depth) of the
    MRCA of the species that are tips; None when none is.  Label: the node's name; an
    unlabelled node = '~' + its nearest labelled ancestor; the unlabelled root = 'root'."""

    def __init__(self, text: str):
        self.root = parse_newick(text)
        self._tip: dict = {}
        stack = [self.root]
        while stack:
            nd = stack.pop()
            if nd.children:
                stack.extend(nd.children)
            elif nd.name:
                if nd.name in self._tip:
                    raise ValueError(f"newick: tip {nd.name} occurs twice")
                self._tip[nd.name] = nd

    @property
    def tips(self) -> frozenset:
        return frozenset(self._tip)

    def mrca(self, species: Iterable[str]) -> Optional[Node]:
        nodes = [self._tip[s] for s in dict.fromkeys(species) if s in self._tip]
        if not nodes:
            return None
        a = nodes[0]
        for b in nodes[1:]:
            while a.depth > b.depth:
                a = a.parent
            while b.depth > a.depth:
                b = b.parent
            while a is not b:
                a, b = a.parent, b.parent
        return a

    @staticmethod
    def label(node: Node) -> str:
        if node.name:
            return node.name
        p = node.parent
        while p is not None and not p.name:
            p = p.parent
        if p is None:
            return "root" if node.parent is None else "~root"
        return "~" + p.name

    def origin(self, species: Iterable[str]) -> Optional[Origin]:
        nd = self.mrca(species)
        return None if nd is None else Origin(self.label(nd), nd.depth)
```

Note on the `(A,B);(C,D);` case: the loop breaks at the first `;`, and the check after the loop rejects any non-empty text after it. Do not let a second tree pass silently.

- [ ] **Step 5: Run, expect PASS** (same command). Then both full suites.
- [ ] **Step 6: Commit**

```bash
git add workflow/og_origin.py phylocli/tests/data/species_tree.v3.newick phylocli/tests/test_og_origin.py
git commit -m "og_origin: strict Dollo origin (MRCA of member species) on a newick species tree; stdlib only

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: config + `model.origin_tree` / `model.og_origins`

**Files:**
- Modify: `phylocli/core.py` (`PATH_PARAMS`), `phylocli/config.yaml` (`params:`), `phylocli/tests/conftest.py` (the config fixture that writes `species.newick`)
- Append: `phylocli/model.py`, `phylocli/tests/test_model.py`

**Interfaces:**
- Consumes: `og_origin.OriginTree`, `og_origin.Origin` (Task 1); `model.HGOgs` (`.hg`, `.ogs`, `.error`), `model.OG` (`.id`, `.genes`), `model.Member.species`.
- Produces:
  - `model.origin_tree_path(cfg) -> Path`;
  - `model.origin_tree(cfg) -> og_origin.OriginTree`, which raises `OSError` / `ValueError`;
  - `model.og_origins(rows, tree) -> dict[str, Origin | None]`, keyed by `OG.id`, skipping rows with `.error`.

- [ ] **Step 1: Fixture** — in `phylocli/tests/conftest.py`, next to `_w(root / "species.newick", "(a,b);\n")` add

```python
    _w(root / "origin.newick", "((Mlei:1,Bova:1)Cteno:1,(Hsap:1,Nvec:1)Para:1);\n")
```

and add `ORIGIN_TREE=str(root / "origin.newick"),` to the `base["params"].update(...)` call. Fixture origins: `tfs.A.HG1.0` (Mlei, Mlei, Hsap) → `root`, depth 0; `tfs.A.HG1.1` (Hsap, Nvec) → `Para`, depth 1; `tfs.A.HG11.0` (Bova, Mlei) → `Cteno`, depth 1; `possvm_prev` `tfs.A.HG1.0` (Mlei, Zzz) → `Mlei`, depth 2.

- [ ] **Step 2: Write the failing tests** — append to `phylocli/tests/test_model.py`:

```python
def test_origin_tree_path_default(cli):
    cfg = _cfg()
    assert model.origin_tree_path(cfg) == Path(cfg.params["ORIGIN_TREE"])
    import dataclasses
    bare = dataclasses.replace(cfg, params={k: v for k, v in cfg.params.items() if k != "ORIGIN_TREE"})
    assert model.origin_tree_path(bare) == core.ROOT / "data/species_tree.newick"


def test_config_resolves_origin_tree_relative_to_root():
    raw = {"outdir": "results", "partition": "p", "qos": "q",
           "params": {"ORIGIN_TREE": "data/species_tree.newick"}}
    assert core.config_from_raw(raw).params["ORIGIN_TREE"] == str(core.ROOT / "data/species_tree.newick")


def test_og_origins_on_the_fixture(cli):
    cfg = _cfg()
    write_results(cfg)
    rows, _ = model.group_ogs(cfg, ["tfs.A.HG1", "tfs.A.HG11"], "possvm")
    got = model.og_origins(rows, model.origin_tree(cfg))
    assert {k: (v.label, v.depth) for k, v in got.items()} == {
        "tfs.A.HG1.0": ("root", 0), "tfs.A.HG1.1": ("Para", 1), "tfs.A.HG11.0": ("Cteno", 1)}


def test_og_origins_ignore_species_off_the_tree(cli):
    cfg = _cfg()
    write_results(cfg)
    rows, _ = model.group_ogs(cfg, ["tfs.A.HG1"], "possvm_prev")      # Mlei + Zzz (not a tip)
    assert model.og_origins(rows, model.origin_tree(cfg)) == {"tfs.A.HG1.0": ("Mlei", 2)}


def test_og_origins_none_and_error_rows(cli):
    cfg = _cfg()
    tree = model.origin_tree(cfg)
    og = model.OG("x.HG1.0", "n", [model.Member("Zzz_1", "Zzz", "NA", "NA")], None, "NA", "NA")
    rows = [model.HGOgs("x.HG1", [og], None), model.HGOgs("x.HG2", [], "bad file")]
    assert model.og_origins(rows, tree) == {"x.HG1.0": None}


def test_origin_tree_unreadable_raises(cli):
    cfg = _cfg()
    Path(cfg.params["ORIGIN_TREE"]).unlink()
    with pytest.raises(OSError):
        model.origin_tree(cfg)
```

Check `model.HGOgs`'s field order before relying on the positional call above (`hg, ogs, error`). If it differs, use keywords. `pytest`, `Path`, `core`, `_cfg` and `write_results` are already available in `test_model.py`; add any import that is missing at the end of the import block, not by editing other tests.

- [ ] **Step 3: Run, expect FAIL**: `... -k "origin"` → `AttributeError: module 'phylocli.model' has no attribute 'origin_tree_path'`.

- [ ] **Step 4: Implement**
  - `phylocli/core.py`: add `"ORIGIN_TREE"` to `PATH_PARAMS`.
  - `phylocli/config.yaml`, under `params:` after `SPECIES_TREE`:

```yaml
  ORIGIN_TREE: data/species_tree.newick   # orthogroup origin (Dollo MRCA); keeps polytomies (Grygoriy, 11/10/2026)
```

  - `phylocli/model.py`: add `import og_origin` after the `from phylocli import core ...` import. `core` puts `workflow/` on `sys.path`. Then append:

```python
# ---- orthogroup origin (Dollo MRCA on the origin tree) ------------------------------------------
def origin_tree_path(cfg: core.Config) -> Path:
    """params.ORIGIN_TREE (already absolute: core.PATH_PARAMS), else data/species_tree.newick
    under the repo root (a config written before the key existed)."""
    p = cfg.params.get("ORIGIN_TREE")
    return Path(p) if p else core.ROOT / "data/species_tree.newick"


def origin_tree(cfg: core.Config) -> "og_origin.OriginTree":
    """The parsed origin tree; OSError / ValueError when it cannot be read or parsed."""
    return og_origin.OriginTree(origin_tree_path(cfg).read_text())


def og_origins(rows, tree) -> dict:
    """{OG id: Origin(label, depth) or None} for every OG of `rows` ([HGOgs]; rows with an
    error are skipped).  Species not on the tree are ignored (og_outside lists them)."""
    return {og.id: tree.origin(m.species for m in og.genes)
            for r in rows if not r.error for og in r.ogs}
```

- [ ] **Step 5: Run, expect PASS**; then both full suites. If a runner test pins the exported params, the new `ORIGIN_TREE` env var shows up there. Do not edit that test: report it as a concern. `runner.py` exports every param, as it does `SPECIES_TREE`.
- [ ] **Step 6: Commit** — `config + model: ORIGIN_TREE (species_tree.newick), origin_tree, og_origins` with the trailer.

---

### Task 3: TUI — `origin` column in `OGs`, species title, sort, filter

**Files:**
- Modify: `phylocli/tui.py`: `OG_COLS`; a new helper `_origin_key`; `PhyloApp.__init__`; `_load_results`; `_apply_results`; `_fill_ogs`; `_show_og`.
- Test: append to `phylocli/tests/test_tui.py`. Change exactly two lines of `test_o_on_overview_opens_results_for_that_group` (see Step 1).

**Interfaces:**
- Consumes: `model.origin_tree(cfg)`, `model.origin_tree_path(cfg)` and `model.og_origins(rows, tree)` (Task 2); `og_origin.Origin` (`.label`, `.depth`).
- Produces: `PhyloApp._origins: dict`, `PhyloApp._otree` (an `OriginTree` or `None`), and `PhyloApp._origin_text(og_id) -> str` (`?` when the tree is unreadable, `–` when there is no species on the tree, else the label).

- [ ] **Step 1: Change the two pinned lines** in `test_o_on_overview_opens_results_for_that_group`:

```python
            assert _cells(app, "#ogs", 0) == ["HG1.0", "3", "2", "78.4", "T/Tbx19", "root"]   # no ref columns; origin last
```
```python
            assert app.query_one("#species_box").border_title == "species · HG1.0 · origin root"
```

- [ ] **Step 2: Write the failing tests** — append to `phylocli/tests/test_tui.py`:

```python
def test_ogs_show_origin(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert [_cells(app, "#ogs", i)[5] for i in range(2)] == ["root", "Para"]
            await _press(pilot, "down")                                   # Results: HG11
            assert _cells(app, "#ogs", 0)[5] == "Cteno"
            assert app.query_one("#species_box").border_title == "species · HG11.0 · origin Cteno"
    _run(go())


def test_origin_sort_by_depth_and_filter(cli):
    from pathlib import Path
    write_results(_cfg())
    p = _cfg().outdir / "possvm/tfs.A.HG1.generax.support.tree.ortholog_groups.csv"
    p.write_text(p.read_text() + "Zzz_9\ttfs.A.HG1.2:lonely\t50.0\tNA\tNA\n")   # off-tree only: –

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            app.query_one("#ogs").focus()
            await pilot.pause()
            await _press(pilot, "up", "right", "right", "right", "right", "right", "enter")
            col = [_cells(app, "#ogs", i)[5] for i in range(3)]
            assert col == ["root", "Para", "–"]                           # oldest first, – last
            await _press(pilot, "enter")                                  # again: reverse
            col = [_cells(app, "#ogs", i)[5] for i in range(3)]
            assert col == ["Para", "root", "–"]                           # – stays last
            await _press(pilot, "down")                                   # leave header mode
            await _press(pilot, "slash", "p", "a", "r", "a", "enter")
            assert app.query_one("#ogs").row_count == 1
            assert _cells(app, "#ogs", 0)[0] == "HG1.1"
    _run(go())


def test_origin_unreadable_tree_shows_question_mark_and_notifies_once(cli, monkeypatch):
    from pathlib import Path
    write_results(_cfg())
    Path(_cfg().params["ORIGIN_TREE"]).unlink()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        seen = []
        orig = app.notify
        monkeypatch.setattr(app, "notify", lambda msg, *a, **k: (seen.append(str(msg)), orig(msg, *a, **k)))
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert _cells(app, "#ogs", 0)[5] == "?"
            assert app.query_one("#species_box").border_title == "species · HG1.0 · origin ?"
            await _press(pilot, "escape", "escape")
            await _open_results(app, pilot, "tfs")                        # second load: no 2nd toast
            assert sum("origin tree" in m for m in seen) == 1
    _run(go())


def test_origin_tree_read_off_the_ui_thread(cli, monkeypatch):
    import threading
    write_results(_cfg())
    on_main = []
    real = tui.model.origin_tree
    monkeypatch.setattr(tui.model, "origin_tree",
                        lambda cfg: (on_main.append(threading.current_thread() is threading.main_thread()),
                                     real(cfg))[1])

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            await _press(pilot, "escape", "escape")
            await _open_results(app, pilot, "tfs")                        # read once per session
            assert _cells(app, "#ogs", 0)[5] == "root"
    _run(go())
    assert on_main == [False]


def test_origin_from_results_tab_cache(cli, monkeypatch):
    write_results(_cfg())
    calls = []
    real = tui.model.group_ogs
    monkeypatch.setattr(tui.model, "group_ogs", lambda *a, **k: (calls.append(1), real(*a, **k))[1])

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _press(pilot, "tab")                                    # Results tab: one read
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one("#rtab").move_cursor(row=0)                     # ALL
            await _press(pilot, "enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and len(calls) == 1
            assert _cells(app, "#ogs", 0)[5] == "root"
    _run(go())
```

Check `_press`'s signature (several keys in one call), the escape count that leaves the Results window, and the Results-tab test helpers against the existing tests near `test_results_tab_*`. Adapt the navigation lines to them, never the assertions.

- [ ] **Step 3: Run, expect FAIL**: `... -k "origin"` → `IndexError` / `list index out of range` on cell `[5]`, plus the two pinned asserts.

- [ ] **Step 4: Implement** in `phylocli/tui.py`:

  - `OG_COLS`: append `SortCol("origin", "origin")`. `OG_KEYS` stays module-level; the origin key needs app state and is added in `_fill_ogs`. Below `OG_KEYS` add:

```python
def _origin_key(o) -> tuple:
    """OGs `origin` sort: oldest (smallest depth) first, then label; no origin (– or ?) last in
    both directions."""
    return (0, o.depth, o.label.lower()) if o is not None else (1, 0, "")
```

    "Last in both directions" needs reverse handling, because `sort_rows` reverses the whole key. In `_fill_ogs`, sort placed and unplaced OGs separately:

```python
        keys = dict(OG_KEYS, origin=(lambda o: _origin_key(self._origins.get(o.id)), False))
        if t.sort_state is not None and t.sort_state[0] == "origin":
            placed = [o for o in ogs if self._origins.get(o.id) is not None]
            ogs = (sort_rows(placed, t.sort_state, keys)
                   + [o for o in ogs if self._origins.get(o.id) is None])
        else:
            ogs = sort_rows(ogs, t.sort_state, keys)
```
    (replacing `ogs = sort_rows(ogs, t.sort_state, OG_KEYS)`).

  - `__init__`, next to `self._universe`:

```python
        self._otree = None                      # og_origin.OriginTree, read once by the worker
        self._otree_err = ""                    # why it could not be read ("" = not tried / ok)
        self._origins: dict = {}                # OG id -> Origin | None, of the loaded rows
```

  - `_load_results`: add `otree=self._otree, origins={}, otree_err=""` to the `snap = dict(...)` call. After the `phyla` block, before `snap["sp_note"] = ...`:

```python
        if snap["otree"] is None:
            try:
                snap["otree"] = model.origin_tree(self.cfg)
            except Exception as e:
                snap["otree_err"] = f"origin tree {model.origin_tree_path(self.cfg)}: {e}"
        if snap["otree"] is not None:
            snap["origins"] = model.og_origins(snap["rows"], snap["otree"])
```

  - `_apply_results`: after the `self._universe, self._phyla, self._sp_note = ...` line:

```python
        self._otree, self._origins = snap["otree"], snap["origins"]
        if snap["otree_err"]:
            self._notify_once(snap["otree_err"])
```
    `_notify_once` dedupes by message. The message names only the path, not a varying error object, so a second failed load stays silent.

  - A new method next to `_cur_og`:

```python
    def _origin_text(self, og_id: str) -> str:
        """`?` while the origin tree is unreadable, `–` for an OG with no species on it."""
        if self._otree is None:
            return "?"
        o = self._origins.get(og_id)
        return "–" if o is None else o.label
```

  - `_fill_ogs`: the filter line becomes

```python
        ogs = [o for o in r.ogs if q in o.id.lower() or q in o.name.lower()
               or q in self._origin_text(o.id).lower()] if r else []
```
    and `t.add_row(...)` gets a 6th cell, `escape(self._origin_text(og.id))`, before `key=og.id`.

  - `_show_og`: the species title becomes

```python
        self.query_one("#species_box").border_title = (
            f"species · {_short_og(og.id)} · origin {self._origin_text(og.id)}" if og else "species")
```

- [ ] **Step 5: Run, expect PASS**; then both full suites.
- [ ] **Step 6: Commit** — `tui Results: OG origin (Dollo MRCA) column, species title, sort by depth, / matches it` with the trailer. In the commit body, list the two changed lines of the existing test.
