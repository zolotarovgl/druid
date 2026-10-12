# phylocli × treeview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From phylocli's Results window, `t` opens the selected HG's gene tree in a vendored copy of treeview (cursor on the HG root / OG MRCA / member tip), and both apps get a `?` key screen with a one-line help strip.

**Architecture:** Tasks 1–4 change treeview in its own repo (cluster `~/projects/treeview`, branch `main`); Task 5 vendors the result into `phylocli/vendor/treeview/` with a refresh script; Tasks 6–7 wire it into phylocli's TUI. A generic `KeysScreen` lives in treeview (`treeview/keys.py`) and phylocli reuses it from the vendored copy.

**Tech Stack:** Python 3.9, Textual 8.2.8, rich, ete3 3.1.3, pytest.

**Spec:** `/home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt/docs/superpowers/specs/2026-10-12-phylocli-treeview-design.md`

## Global Constraints

- Python 3.9 (cluster `phylo` env 3.9.21). No `match`, no `X | Y` types at runtime (string annotations only, with `from __future__ import annotations`).
- Test interpreter, both repos: `PY=/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-phylogenies/3dad6ea4-c859-4fe6-b319-93a358944ac8/scratchpad/py39/bin/python` (has textual 8.2.8, ete3, typer, yaml, pytest).
- treeview repo: edit files through the mount `/home/grygoriyzolotarov/no_backup/treeview`; run tests there with `cd /home/grygoriyzolotarov/no_backup/treeview && $PY -m pytest treeview/tests -q -p no:cacheprovider`; **commit only via ssh**: `ssh -o BatchMode=yes login1.hpc.crg.es 'cd /no_backup/asebe/gzolotarov/treeview && git add -A treeview && git commit -m "..."'` (git on the mount fails with "dubious ownership"; do not change `safe.directory`).
- phylocli repo: `/home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt`, branch `phylocli`; tests `cd <repo> && $PY -m pytest phylocli/tests -q -p no:cacheprovider`. Never write into v3 (`~/ant/gzolotarov/projects/2022_scRNAseq_Mlei/Phylogenies_v3`); never run Nextflow.
- Edit code with the Edit/Write tools, never `sed -i` or python string-replace.
- Commit only when the parsed pytest summary shows 0 failed (do not chain `pytest ... | tail && git commit`).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never dispatch subagents from inside a task.

## Plan-time rulings (amend the spec; recorded here so implementers follow them)

1. The overview's Results tab rows are **groups**, not HGs (`#rtab` keyed by group). `t` there only notifies `open a group's Results (o), then t`. `t` opens trees from the Results view only.
2. Highlighted tips are drawn **bold underline** (not reverse: reverse is the cursor).
3. The tree file is found from the `.ortholog_groups.csv` name, which is `<HG>.<tree file name>.ortholog_groups.csv` (as `read_ogs` already finds it): tree = csv name minus `.ortholog_groups.csv`. This gives `<HG>.generax.support.tree` in `possvm/` and `<HG>.treefile` in `possvm_prev/`, as the spec's table says, without hard-coding either.
4. From the members pane, `t` focuses the member's tip with **no** highlight (spec table); from the OGs pane it highlights the OG's members.
5. The key-coverage tests check that **every binding of the app appears in the union of its key tables**, plus spot checks per view (not every binding is live in every view).
6. ⚠ `/users/asebe` is out of quota (12/10/2026: every write there fails with "No space left on device"; SIT has not rescanned). Grygoriy, 12/10/2026: "use no_backup". treeview Tasks 1–4 run in a temporary clone at cluster `/no_backup/asebe/gzolotarov/treeview` (origin = `~/projects/treeview`, cloned at b2f33c4; 62 tests pass), mounted locally at `/home/grygoriyzolotarov/no_backup/treeview` (sshfs). When `/users` writes again, the controller pulls it back: `ssh login1.hpc.crg.es 'cd ~/projects/treeview && git pull /no_backup/asebe/gzolotarov/treeview main'`. Task 5 vendors from the clone: `TREEVIEW_SRC=/home/grygoriyzolotarov/no_backup/treeview TREEVIEW_REMOTE_REPO=login1.hpc.crg.es:/no_backup/asebe/gzolotarov/treeview bash phylocli/vendor/update_treeview.sh` (same commits, so `VENDORED` stays valid after the pull-back).

## Review Focus

1. An OG whose members are all missing from the tree (tree from another run): `mrca([])` must be the root and the tree must still open, with a `n of n members not in the tree` notice — Task 6 test.
2. A narrow terminal with metadata columns on: tip names must fit, metadata may scroll — Task 3 test with `show_meta`.
3. `?` pressed while a treeview prompt is open types `?` into the Input instead of opening the key screen — Task 2 test.
4. `q` inside the key screen closes the screen, not the app — Task 2 test (treeview) and Task 7 test (phylocli).
5. `p` between two `t` presses: the second tree must come from the other source, not a cached model — Task 6 test.
6. phylocli's own app keys (`p`, `R`, `o`, `f`, …) pressed while the tree is on screen must not act on the Results view underneath — Task 6 test (`check_action`).

---

### Task 1: treeview model — POSSVM `.csv`, `mrca`, `tip`, `highlight`

**Files:**
- Modify: `treeview/model.py` (`load_meta`, `TreeModel.__init__`, new methods after `ancestors`)
- Modify: `treeview/layout.py` (`node_label`, tip branch)
- Test: `treeview/tests/test_model.py`, `treeview/tests/test_layout.py`

**Interfaces:**
- Produces: `TreeModel.mrca(ids) -> int`; `TreeModel.tip(name: str) -> "int | None"`; `TreeModel.highlight: set` (node ids; tips in it are drawn bold underline by `layout.node_label`).

- [ ] **Step 1: Write the failing tests**

In `treeview/tests/test_model.py`, inside `test_meta_csv_and_bad_files`, after the line `assert model.load_meta(g) == (["grp"], {"A_1": ["x,y"]})` add:

```python
    h = tmp_path / "possvm.ortholog_groups.csv"                   # POSSVM: tab-separated .csv
    h.write_text("gene\torthogroup\tsupport\nA_1\tHG1.0:T/Tbx19\t78.4\n")
    assert model.load_meta(h) == (["orthogroup", "support"], {"A_1": ["HG1.0:T/Tbx19", "78.4"]})
    q = tmp_path / "quoted.csv"                                   # a real CSV still parses as CSV
    q.write_text('id,note\nA_1,"x\ty"\n')
    assert model.load_meta(q) == (["note"], {"A_1": ["x\ty"]})
```

Append to `treeview/tests/test_model.py`:

```python
def test_mrca_and_tip():
    m = model.TreeModel(model.load("((A_1,B_2)X,(C_3,D_4)Y);"))
    a, b, c, d = (m.tip(n) for n in ("A_1", "B_2", "C_3", "D_4"))
    assert m.name[m.mrca([a, b])] == "X" and m.name[m.mrca([d, c])] == "Y"
    assert m.mrca([a, c]) == 0 and m.mrca([]) == 0 and m.mrca([c]) == c
    assert m.tip("nope") is None and m.tip("X") is None          # clades are not tips
    assert m.highlight == set()
```

Append to `treeview/tests/test_layout.py` (it already imports `model` and `layout`; if not, add `from treeview import layout, model`):

```python
def test_highlighted_tip_label_is_bold_underline():
    m = model.TreeModel(model.load("((A_1,B_2)X,C_3);"))
    a = m.tip("A_1")
    assert "underline" not in str(layout.node_label(m, a).spans[0].style)
    m.highlight = {a}
    st = str(layout.node_label(m, a).spans[0].style)
    assert "bold" in st and "underline" in st and m.colour(a) in st
    assert "underline" not in str(layout.node_label(m, m.tip("B_2")).spans[0].style)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/grygoriyzolotarov/no_backup/treeview && $PY -m pytest treeview/tests/test_model.py treeview/tests/test_layout.py -q -p no:cacheprovider`
Expected: FAIL — `cols []` for the POSSVM file, `AttributeError: 'TreeModel' object has no attribute 'tip'`, `highlight`.

- [ ] **Step 3: Implement**

`treeview/model.py`, replace the body of `load_meta` up to `lines = [r for r in lines if any(r)]` with:

```python
    """Tip metadata: (column names, {tip id: [values]}).  A TSV, or a CSV when the name ends in
    `.csv` (any case) and its header has no tab (POSSVM writes tab-separated `.csv`), with a
    header row; the first column is the tip id, the other columns keep their header names.
    Short rows are padded with "", long ones cut to the header; a repeated id keeps its last row.
    OSError when unreadable, ValueError when there is no header."""
    p = Path(path)
    with open(p, newline="", errors="replace") as fh:
        text = fh.read().splitlines()
    head = next((ln for ln in text if ln.strip()), "")
    if p.suffix.lower() == ".csv" and "\t" not in head:
        lines = [[x.strip() for x in r] for r in csv.reader(text)]
    else:
        lines = [[x.strip() for x in ln.split("\t")] for ln in text]
```

(keep the rest of the function as it is). Note: `csv.reader` over `splitlines()` output still handles quoted fields on one line; a quoted field with an embedded newline is not supported (it was not before either: test it is not needed).

In `TreeModel.__init__`, after `self.colour_by = ""` add:

```python
        self.highlight: set = set()      # node ids drawn bold underline (an embedding caller's
        #                                  selection, e.g. phylocli's OG members)
        self._tips = {self.name[i]: i for i in range(k) if not self.children[i]}
```

After `ancestors` add:

```python
    def tip(self, name: str) -> "int | None":
        """Node id of the tip called `name` (exact), None when there is none."""
        return self._tips.get(name)

    def mrca(self, ids) -> int:
        """The deepest node whose subtree holds every id in `ids`; the root when `ids` is empty.
        Uses the preorder layout: the subtree of a is a .. a + size[a] - 1."""
        ids = list(ids)
        if not ids:
            return 0
        a = ids[0]
        for b in ids[1:]:
            while not (a <= b < a + self.size[a]):
                a = self.parent[a]
        return a
```

`treeview/layout.py`, `node_label`, replace the tip branch:

```python
    if m.is_tip(i):
        style = m.colour(i) + (" bold underline" if i in m.highlight else "")
        t.append(_cut(m.name[i], name_width), style=style)
        return t
```

- [ ] **Step 4: Run the whole suite**

Run: `cd /home/grygoriyzolotarov/no_backup/treeview && $PY -m pytest treeview/tests -q -p no:cacheprovider`
Expected: all pass (62 before this task + 2 new = 64; the edited `test_meta_csv_and_bad_files` counts once).

- [ ] **Step 5: Commit (via ssh)**

```bash
ssh -o BatchMode=yes login1.hpc.crg.es 'cd /no_backup/asebe/gzolotarov/treeview && git add -A treeview && git commit -q -m "model: POSSVM tab-separated .csv as --meta; mrca, tip, highlight

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline -1'
```

---

### Task 2: treeview — `?` key screen, one-line help, `c` cycles colour modes

**Files:**
- Create: `treeview/keys.py`
- Modify: `treeview/widget.py` (`HELP`, new `KEYS`, `TreeScreen.BINDINGS`, `action_prompt`, `on_input_submitted`, new `action_cycle_colour`, `action_keys`, `_status`)
- Test: `treeview/tests/test_app.py` (new tests; edit the asserts listed in Step 1)

**Interfaces:**
- Consumes: nothing new.
- Produces (Task 7 imports these from the vendored copy):
  - `treeview.keys.KeysScreen(title: str, groups: list)` — modal; `groups` = `[(group name, [(key label, description), ...]), ...]`; closes on `escape`, `?`, `q`.
  - `treeview.keys.keys_text(groups) -> rich.text.Text`
  - `treeview.keys.key_label(binding_key: str) -> str` — `"up"`→`"↑"`, `"down"`→`"↓"`, `"left"`→`"←"`, `"right"`→`"→"`, `"pageup"`→`"pgup"`, `"pagedown"`→`"pgdn"`, `"plus"`→`"+"`, `"minus"`→`"-"`, `"slash"`→`"/"`, `"escape"`→`"esc"`, `"question_mark"`→`"?"`, `"shift+tab"`→`"shift+tab"`, anything else unchanged.
  - `treeview.keys.missing_keys(bindings, groups) -> list` — the labels of binding keys (each comma-separated key of each `Binding`) that appear in no group's key column; a key column cell is split on spaces into tokens (so `"n N"`, `"+ -"`, `"enter space"` list two keys each, and `"/"` is the slash key).
  - `treeview.widget.KEYS` (the groups list), `treeview.widget.HELP == "? keys · q quit"`.

- [ ] **Step 1: Write the failing tests**

Append to `treeview/tests/test_app.py`:

```python
from treeview import keys as tvkeys                                   # noqa: E402
from treeview.widget import KEYS                                      # noqa: E402


def test_every_binding_is_in_the_key_table():
    bindings = TreeView.BINDINGS + TreeScreen.BINDINGS + TreeApp.BINDINGS
    assert tvkeys.missing_keys(bindings, KEYS) == []
    assert HELP == "? keys · q quit"
    assert tvkeys.key_label("question_mark") == "?" and tvkeys.key_label("v") == "v"


def test_question_mark_opens_and_closes_the_key_screen():
    async def go():
        app = TreeApp(_tbox())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, tvkeys.KeysScreen)
            text = app.screen.query_one("#keys").render().plain
            assert "cycle colour" in text and "Collapse" in text
            for close in ("escape", "question_mark", "q"):       # q closes the list, not the app
                if not isinstance(app.screen, tvkeys.KeysScreen):
                    await pilot.press("question_mark")
                    await pilot.pause()
                await pilot.press(close)
                await pilot.pause()
                assert isinstance(app.screen, TreeScreen) and app.is_running
    asyncio.run(go())


def test_question_mark_in_a_prompt_is_typed():
    async def go():
        app = TreeApp(_tbox())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("slash", "question_mark")
            await pilot.pause()
            assert isinstance(app.screen, TreeScreen)
            assert app.screen.query_one("#prompt").value == "?"
    asyncio.run(go())


def test_c_cycles_species_then_each_column():
    async def go():
        m = _tbox_meta()
        app = TreeApp(m)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            seen = []
            for _ in range(len(m.meta_cols) + 1):
                await pilot.press("c")
                await pilot.pause()
                seen.append((m.colour_by, _status(app)))
            assert [c for c, _ in seen] == m.meta_cols + [""]
            assert seen[0][1] == "colour: orthogroup · 17 values"
            assert seen[-1][1] == "colour: species"
    asyncio.run(go())
```

Edit existing tests in `treeview/tests/test_app.py` (they test the old prompt and the old 4-line HELP):

- In `test_meta_start_status_search_and_colour_by_column`: replace everything from the line `await pilot.press("c"` (the colour prompt part, through `assert _status(app) == "colour by species" and m.colour_by == ""`) with:
  ```python
            await pilot.press("c")
            await pilot.pause()
            assert _status(app) == "colour: orthogroup · 17 values"
            og = model.hash_colour("tfs.T-box.HG1.0:T/Tbx19")
            assert m.colour_by == "orthogroup" and m.colour(tip) == og
  ```
  Keep the assertions before it unchanged; keep any variable (`tip`) they define.
- In `test_t_and_c_without_metadata`: replace
  ```python
            await pilot.press("c", *"orthogroup", "enter")
            await pilot.pause()
            assert _status(app) == "no column: orthogroup"
            for k in ("t metadata columns", "c colour by column"):
                assert k in HELP
  ```
  with
  ```python
            await pilot.press("c")
            await pilot.pause()
            assert _status(app) == "no metadata columns" and m.colour_by == ""
            plain = tvkeys.keys_text(KEYS).plain
            assert "metadata columns" in plain and "cycle colour" in plain
  ```
- Every other `... in HELP` assert (`"contract support < x (polytomies)" in HELP`, `"scroll" in HELP`, `"- down to compact" in HELP`): change to `in tvkeys.keys_text(KEYS).plain` with the substrings `"contract branches with support < x (polytomies)"`, `"scroll"`, `"compact"` respectively. Find them with `grep -n "in HELP" treeview/tests/test_app.py`; there must be none left except the new `HELP == ...` assert.
- In `test_prompt_swallows_command_keys` (it presses command keys inside a prompt and checks nothing changed, including `m.colour_by == ""`): leave it as it is; it must still pass.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/grygoriyzolotarov/no_backup/treeview && $PY -m pytest treeview/tests/test_app.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: treeview.keys`.

- [ ] **Step 3: Implement `treeview/keys.py`**

```python
"""The `?` key screen (Grygoriy, 12/10/2026): a modal list of key groups, shared by treeview and
phylocli (which imports it from its vendored copy).  A key table is
[(group name, [(key label, description), ...]), ...]; `missing_keys` checks that a table lists
every binding, so a new key cannot be left out of `?`."""
from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

_LABELS = {"up": "↑", "down": "↓", "left": "←", "right": "→", "pageup": "pgup",
           "pagedown": "pgdn", "plus": "+", "minus": "-", "slash": "/", "escape": "esc",
           "question_mark": "?"}


def key_label(key: str) -> str:
    """How a Textual binding key is written in a key table."""
    return _LABELS.get(key, key)


def keys_text(groups) -> Text:
    """The table as text: each group's name (bold), then `key  description` lines."""
    t = Text()
    for g, rows in groups:
        if t.plain:
            t.append("\n")
        t.append(g + "\n", style="bold")
        w = max(len(k) for k, _ in rows)
        for k, d in rows:
            t.append(f"  {k:<{w}}  ", style="bold cyan")
            t.append(d + "\n")
    return t


def missing_keys(bindings, groups) -> list:
    """Labels of binding keys found in no group's key column (cells split on spaces)."""
    shown = {tok for _, rows in groups for k, _ in rows for tok in k.split()}
    out = []
    for b in bindings:
        for k in b.key.split(","):
            lab = key_label(k.strip())
            if lab not in shown and lab not in out:
                out.append(lab)
    return out


class KeysScreen(ModalScreen):
    """Every key of the caller, grouped; esc, ? or q closes it."""

    DEFAULT_CSS = """
    KeysScreen { align: center middle; }
    KeysScreen > VerticalScroll { width: auto; max-width: 100%; height: auto; max-height: 90%;
                                  border: round $primary; padding: 0 1; background: $surface; }
    KeysScreen #keys { width: auto; }
    """
    BINDINGS = [Binding("escape,question_mark,q", "close", "close")]

    def __init__(self, title: str, groups, **kwargs):
        super().__init__(**kwargs)
        self.title_text, self.groups = title, groups

    def compose(self):
        with VerticalScroll() as v:
            v.border_title = self.title_text
            yield Static(keys_text(self.groups), id="keys")

    def action_close(self) -> None:
        self.dismiss()
```

- [ ] **Step 4: Implement the widget changes**

`treeview/widget.py`: add `from treeview.keys import KeysScreen` to the imports. Replace the `HELP = (...)` assignment with:

```python
KEYS = [
    ("Move", [("↑ ↓", "move the cursor"), ("pgup pgdn", "page up / down"),
              ("home end", "first / last node"), ("← →", "scroll sideways")]),
    ("Views", [("v", "outline ↔ cladogram"), ("l", "branch lengths to scale (cladogram)"),
               ("+ -", "tip spacing (- below 0: compact cladogram)"),
               ("t", "metadata columns on / off")]),
    ("Collapse", [("enter space", "collapse / expand the clade"),
                  ("s", "contract branches with support < x (polytomies)"),
                  ("m", "collapse single-species clades"), ("e", "expand all")]),
    ("Search", [("/", "search names and metadata"), ("n N", "next / previous hit")]),
    ("Colour", [("c", "cycle colour: species → each metadata column → species")]),
    ("Edit & export", [("r", "rename the clade"), ("w", "write the tree as shown (newick)")]),
    ("Other", [("?", "this list"), ("esc", "close the prompt / clear the search / back"),
               ("q", "quit")]),
]
HELP = "? keys · q quit"
```

(`←`/`→` have no binding of ours — ScrollView scrolls sideways itself — so they are listed without being checked.)

`TreeScreen.BINDINGS`: replace `Binding("c", "prompt('colour')", "colour by")` with `Binding("c", "cycle_colour", "colour")` and add `Binding("question_mark", "keys", "keys")`.

`action_prompt`: remove `"colour": "colour by column"` from the `border_title` dict. `on_input_submitted`: delete the whole `elif self.mode == "colour":` branch.

Add to `TreeScreen`:

```python
    def action_cycle_colour(self) -> None:
        """c: species colour → each metadata column in order → species colour."""
        m = self.model
        if not m.meta_cols:
            self._status("no metadata columns")
            return
        modes = [""] + m.meta_cols
        nxt = modes[(modes.index(m.colour_by) + 1) % len(modes)]
        n = m.set_colour_by(nxt)
        self.tree.rebuild()
        note = f"colour: {nxt} · {n} values" if nxt else "colour: species"
        self.tree.post_message(TreeView.Note(self.tree, note))      # after rebuild's Moved

    def action_keys(self) -> None:
        self.app.push_screen(KeysScreen("treeview keys", KEYS))
```

The `?` typed into an open prompt: the `Input` has focus and consumes printable keys before the screen's bindings, so no extra code is needed; the test proves it.

- [ ] **Step 5: Run the whole suite**

Run: `cd /home/grygoriyzolotarov/no_backup/treeview && $PY -m pytest treeview/tests -q -p no:cacheprovider`
Expected: all pass (64 + 4 new = 68).

- [ ] **Step 6: Commit (via ssh)**

```bash
ssh -o BatchMode=yes login1.hpc.crg.es 'cd /no_backup/asebe/gzolotarov/treeview && git add -A treeview && git commit -q -m "? key screen (keys.py), one-line help, c cycles colour modes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline -1'
```

---

### Task 3: treeview — tip names never off-screen

**Files:**
- Modify: `treeview/layout.py` (`columns`: unscaled step floor; new `fit_width`)
- Modify: `treeview/widget.py` (`TreeView.rebuild`: branch width)
- Test: `treeview/tests/test_layout.py`, `treeview/tests/test_app.py`

**Interfaces:**
- Produces: `layout.fit_width(m, view_width: int, width: int, scaled: bool = False, gap: int = 0, name_width: int = 40) -> int`.

Background (measured 12/10/2026, T-box HG1, 488 tips): at 80 columns the cladogram rows are 89 wide in a 76-column view; at 200 columns 181/196. The unscaled `columns` uses `step = max(2, ...)`, so a deep tree overruns `width`, and `rebuild` passes a fixed `width = view - 40`.

- [ ] **Step 1: Write the failing tests**

Append to `treeview/tests/test_layout.py`:

```python
from pathlib import Path                                             # noqa: E402

D = Path(__file__).parent / "data"


def _tb():
    return model.TreeModel(model.load(D / "tbox_HG1.generax.support.tree"))


def test_fit_width_shrinks_until_rows_fit():
    m = _tb()
    for scaled in (False, True):
        for gap in (0, -1):
            w = layout.fit_width(m, 76, 36, scaled=scaled, gap=gap)
            rows = layout.clado_rows(m, width=w, scaled=scaled, gap=gap)
            assert max(t.cell_len for t, _ in rows) <= 76, (scaled, gap, w)
    assert layout.fit_width(m, 196, 156) == 156                   # fits already: unchanged
```

Append to `treeview/tests/test_app.py`:

```python
def test_tip_names_fit_an_80_column_terminal():
    async def go():
        m = _tbox_meta()
        app = TreeApp(m)
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            tv = app.screen.query_one(TreeView)
            fits = lambda: max(t.cell_len for t, _ in layout.clado_rows(            # noqa: E731
                m, width=tv.branch_width, scaled=tv.scaled, gap=tv.gap)) <= tv.size.width
            assert fits()
            await pilot.press("l")                                 # scaled
            assert fits()
            await pilot.press("l", "minus")                        # compact
            assert tv.gap == -1 and fits()
            await pilot.press("t")                                 # metadata on: names still fit
            await pilot.pause()
            name_ends = [t.plain.rfind(m.name[i]) + len(m.name[i])
                         for t, i in tv.rows if isinstance(i, int) and m.is_tip(i)]
            assert name_ends and max(name_ends) <= tv.size.width
    asyncio.run(go())
```

Add `from treeview import layout` to the imports of `test_app.py` if it is not there. Note: in compact mode rows are `(Text, [stops])`, so the `name_ends` comprehension (which needs `i` to be a node id) only checks the non-compact rows; press `plus` before `t` so the check runs on gap 0: change the line `await pilot.press("t")` to `await pilot.press("plus", "t")`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/grygoriyzolotarov/no_backup/treeview && $PY -m pytest treeview/tests/test_layout.py treeview/tests/test_app.py -q -p no:cacheprovider -k "fit"`
Expected: FAIL — `AttributeError: module 'treeview.layout' has no attribute 'fit_width'`.

- [ ] **Step 3: Implement**

`treeview/layout.py`, in `columns`, unscaled branch: change `step = max(2, (width - 2) // max(top, 1))` to `step = max(1, (width - 2) // max(top, 1))` and update the docstring line to say the step per level is at least 1. Then add after `columns`:

```python
def fit_width(m: TreeModel, view_width: int, width: int, scaled: bool = False, gap: int = 0,
              name_width: int = 40) -> int:
    """The branch width to draw the cladogram with: `width`, made smaller (down to 2) until the
    widest row, labels included, fits in `view_width` columns.  Metadata columns are not counted
    (they scroll).  When even 2 overruns (a very deep tree), 2 is returned and the view scrolls."""
    for _ in range(8):
        rows = _clado_rows(m, width, scaled, gap, name_width)
        over = max(t.cell_len for t, _ in rows) - view_width
        if over <= 0 or width <= 2:
            return width
        width = max(width - over, 2)
    return width
```

`treeview/widget.py`, `TreeView.__init__`: add `self.branch_width = 20                # cladogram branch columns (fit_width)`. In `rebuild`, replace

```python
        width = max((self.size.width or 80) - 40, 20)
```

with

```python
        view_w = self.size.width or 80
        width = max(view_w - 40, 20)
        if self.view == "clado":            # names never off-screen: shorter branches instead
            width = layout.fit_width(m, view_w, width, scaled=self.scaled, gap=self.gap)
        self.branch_width = width
```

- [ ] **Step 4: Run the whole suite**

Run: `cd /home/grygoriyzolotarov/no_backup/treeview && $PY -m pytest treeview/tests -q -p no:cacheprovider`
Expected: all pass (68 + 2 = 70). If an existing layout test pinned a 2-column step at a narrow `width`, it encoded the overflow this task removes: update its expected value to the new drawing and say so in the report (quote the old and new expectation).

- [ ] **Step 5: Check the real terminal case**

Run (headless, prints the widest row at 80 and 200 columns):
```bash
cd /home/grygoriyzolotarov/no_backup/treeview && $PY - <<'EOF'
import asyncio
from treeview import model
from treeview.app import TreeApp
from treeview.widget import TreeView
async def go():
    for W in (80, 200):
        m = model.TreeModel(model.load("treeview/tests/data/tbox_HG1.generax.support.tree"))
        app = TreeApp(m)
        async with app.run_test(size=(W, 20)) as p:
            await p.pause()
            tv = app.screen.query_one(TreeView)
            print(W, tv.size.width, max(t.cell_len for t, _ in tv.rows))
asyncio.run(go())
EOF
```
Expected: `80 76 <n ≤ 76>` and `200 196 181`.

- [ ] **Step 6: Commit (via ssh)**

```bash
ssh -o BatchMode=yes login1.hpc.crg.es 'cd /no_backup/asebe/gzolotarov/treeview && git add -A treeview && git commit -q -m "cladogram: shorter branches so tip names fit the terminal

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline -1'
```

---

### Task 4: treeview — `TreeScreen(focus=, highlight=)`

**Files:**
- Modify: `treeview/widget.py` (`TreeScreen.__init__`, `on_mount`, `_status`, `action_back`)
- Test: `treeview/tests/test_app.py`

**Interfaces:**
- Consumes: `TreeModel.mrca`, `.tip`, `.highlight` (Task 1).
- Produces: `TreeScreen(model, view="clado", title="", path=None, focus: "int | None" = None, highlight=None)`; the highlighted ids become the `n`/`N` hit list; `esc` clears hits and highlight, then (pushed) pops the screen.

- [ ] **Step 1: Write the failing test**

Append to `treeview/tests/test_app.py`:

```python
def test_pushed_screen_focus_highlight_and_esc():
    async def go():
        m = _tbox()
        tips = [i for i in range(len(m)) if m.is_tip(i)][:3]
        anc = m.mrca(tips)
        assert not m.is_tip(anc)
        m.collapsed.add(anc)                       # focus inside a collapsed clade: revealed

        class Host(App):
            def on_mount(self):
                self.push_screen(TreeScreen(m, focus=tips[1], highlight=tips, title="T"))

        app = Host()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            tv = app.screen.query_one(TreeView)
            assert tv.cursor == tips[1] and anc not in m.collapsed
            assert m.highlight == set(tips) and "3 hits (n/N)" in _status(app)
            await pilot.press("n")
            assert tv.cursor == tips[0] and "hit 1/3" in _status(app)
            row = tv.rows[tv.rowof[tips[2]]][0]
            assert any("underline" in str(s.style) for s in row.spans)
            await pilot.press("escape")                       # clears hits + highlight
            await pilot.pause()
            assert m.highlight == set() and isinstance(app.screen, TreeScreen)
            row = tv.rows[tv.rowof[tips[2]]][0]
            assert not any("underline" in str(s.style) for s in row.spans)
            await pilot.press("escape")                       # then leaves
            await pilot.pause()
            assert not isinstance(app.screen, TreeScreen)
    asyncio.run(go())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/grygoriyzolotarov/no_backup/treeview && $PY -m pytest treeview/tests/test_app.py -q -p no:cacheprovider -k pushed_screen_focus`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'focus'`.

- [ ] **Step 3: Implement**

`TreeScreen.__init__` signature and body:

```python
    def __init__(self, model: TreeModel, view: str = "clado", title: str = "",
                 path: Optional[Path] = None, focus: Optional[int] = None, highlight=None,
                 **kwargs):
        super().__init__(**kwargs)
        self.model, self.start_view, self.title_text = model, view, title
        self.path = Path(path) if path is not None else None      # the input file (for `w`)
        self.focus_node = focus                   # the cursor's first node (an embedding caller)
        model.highlight = set(highlight or ())
        self.hits: list = sorted(model.highlight)  # n/N step through the highlighted tips
        self.hit = -1
        self.mode = ""
```

`on_mount`: after `self.query_one(TreeView).focus()` add

```python
        if self.focus_node is not None:           # after the first layout: goto rebuilds
            self.call_after_refresh(self.tree.goto, self.focus_node)
```

`_status`: replace

```python
        if self.hits:
            text += f" · hit {self.hit + 1}/{len(self.hits)}"
```

with

```python
        if self.hits:
            text += (f" · hit {self.hit + 1}/{len(self.hits)}" if self.hit >= 0
                     else f" · {len(self.hits)} hits (n/N)")
```

`action_back`: replace the branch

```python
        elif self.hits:
            self.hits, self.hit = [], -1
            self._status()
```

with

```python
        elif self.hits or self.model.highlight:
            self.hits, self.hit = [], -1
            if self.model.highlight:
                self.model.highlight = set()
                self.tree.rebuild()
            self._status()
```

- [ ] **Step 4: Run the whole suite**

Run: `cd /home/grygoriyzolotarov/no_backup/treeview && $PY -m pytest treeview/tests -q -p no:cacheprovider`
Expected: all pass (71).

- [ ] **Step 5: Commit (via ssh)**

```bash
ssh -o BatchMode=yes login1.hpc.crg.es 'cd /no_backup/asebe/gzolotarov/treeview && git add -A treeview && git commit -q -m "TreeScreen: focus= and highlight= for embedding callers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline -1'
```

---

### Task 5: phylocli — vendor treeview

**Files:**
- Create: `phylocli/vendor/update_treeview.sh` (executable)
- Create (by running the script): `phylocli/vendor/treeview/*.py`, `phylocli/vendor/treeview/VENDORED`
- Modify: `phylocli/core.py:14` (sys.path)
- Test: `phylocli/tests/test_vendor.py`

**Interfaces:**
- Consumes: treeview at the commit of Task 4 (`ssh login1.hpc.crg.es git -C ~/projects/treeview rev-parse HEAD`).
- Produces: `import treeview` / `from treeview.widget import TreeScreen` / `from treeview.keys import KeysScreen, key_label, missing_keys` work in phylocli once `phylocli.core` is imported (it puts `phylocli/vendor` on `sys.path`).

- [ ] **Step 1: Write the failing test**

Create `phylocli/tests/test_vendor.py`:

```python
"""The vendored treeview (spec 2026-10-12, P1)."""
import os
import re
import subprocess
from pathlib import Path

from phylocli import core

VENDOR = core.ROOT / "phylocli/vendor"
SCRIPT = VENDOR / "update_treeview.sh"


def test_vendored_treeview_is_imported_from_vendor():
    import treeview.keys  # noqa: F401
    import treeview.widget  # noqa: F401
    import treeview
    assert Path(treeview.__file__).resolve().is_relative_to(VENDOR.resolve())
    v = (VENDOR / "treeview/VENDORED").read_text()
    assert re.search(r"^commit: [0-9a-f]{40}$", v, re.M)
    assert not (VENDOR / "treeview/tests").exists()


def _src_repo(tmp_path):
    src = tmp_path / "src"
    (src / "treeview/tests").mkdir(parents=True)
    (src / "treeview/__init__.py").write_text("")
    (src / "treeview/model.py").write_text("X = 1\n")
    (src / "treeview/tests/test_x.py").write_text("")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=src, check=True, env=env)
    return src


def test_update_script_copies_without_tests_and_refuses_dirty(tmp_path):
    src = _src_repo(tmp_path)
    dest = tmp_path / "vendor"
    env = dict(os.environ, TREEVIEW_SRC=str(src), TREEVIEW_REMOTE_REPO=str(src),
               VENDOR_DEST=str(dest))
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (dest / "treeview/model.py").read_text() == "X = 1\n"
    assert not (dest / "treeview/tests").exists()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True,
                          text=True).stdout.strip()
    assert f"commit: {head}" in (dest / "treeview/VENDORED").read_text()
    (src / "treeview/model.py").write_text("X = 2\n")                     # uncommitted change
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "uncommitted" in r.stderr
    assert (dest / "treeview/model.py").read_text() == "X = 1\n"         # nothing copied
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt && $PY -m pytest phylocli/tests/test_vendor.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'treeview'`, script missing.

- [ ] **Step 3: Write the script**

`phylocli/vendor/update_treeview.sh`:

```bash
#!/usr/bin/env bash
# Refresh the vendored treeview (spec docs/superpowers/specs/2026-10-12-phylocli-treeview-design.md,
# P1).  Never edit phylocli/vendor/treeview by hand: change treeview, commit it there, run this.
#   TREEVIEW_SRC          the treeview checkout to copy from (default: the cluster repo via the mount)
#   TREEVIEW_REMOTE_REPO  where to run git: host:path (ssh; git on the sshfs mount fails with
#                         "dubious ownership") or a local path
#   VENDOR_DEST           the directory that gets treeview/ (default: next to this script)
set -euo pipefail
SRC="${TREEVIEW_SRC:-$HOME/ant/gzolotarov/projects/treeview}"
REPO="${TREEVIEW_REMOTE_REPO:-login1.hpc.crg.es:projects/treeview}"
DEST="${VENDOR_DEST:-$(cd "$(dirname "$0")" && pwd)}"

_git() {
    if [[ "$REPO" == /* ]]; then
        git -C "$REPO" "$@"
    else
        ssh -o BatchMode=yes "${REPO%%:*}" "git -C ${REPO#*:} $*"
    fi
}

dirty="$(_git status --porcelain)"
if [[ -n "$dirty" ]]; then
    echo "treeview has uncommitted changes; commit them first:" >&2
    echo "$dirty" >&2
    exit 1
fi
commit="$(_git rev-parse HEAD)"
mkdir -p "$DEST/treeview"
rsync -a --delete --exclude tests/ --exclude __pycache__/ --exclude VENDORED \
    "$SRC/treeview/" "$DEST/treeview/"
printf 'source: %s (copied from %s)\ncommit: %s\ndate: %s\n' \
    "$REPO" "$SRC" "$commit" "$(date +%d/%m/%Y)" > "$DEST/treeview/VENDORED"
echo "vendored treeview $commit into $DEST/treeview"
```

`chmod +x phylocli/vendor/update_treeview.sh`.

- [ ] **Step 4: Put `vendor/` on the path**

`phylocli/core.py`, after `sys.path.insert(0, str(ROOT / "workflow"))` add:

```python
sys.path.insert(0, str(ROOT / "phylocli" / "vendor"))   # vendored treeview (vendor/update_treeview.sh)
```

- [ ] **Step 5: Vendor for real**

Run (the temporary `/no_backup` clone, plan-time ruling 6):
`cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt && TREEVIEW_SRC=/home/grygoriyzolotarov/no_backup/treeview TREEVIEW_REMOTE_REPO=login1.hpc.crg.es:/no_backup/asebe/gzolotarov/treeview bash phylocli/vendor/update_treeview.sh && cat phylocli/vendor/treeview/VENDORED && ls phylocli/vendor/treeview`
Expected: `commit:` = the Task 4 commit; files `__init__.py __main__.py app.py keys.py layout.py model.py widget.py VENDORED`, no `tests/`.

- [ ] **Step 6: Run the whole phylocli suite**

Run: `cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt && $PY -m pytest phylocli/tests -q -p no:cacheprovider`
Expected: all pass (387 before + 2 = 389).

- [ ] **Step 7: Commit**

```bash
cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt
git add phylocli/vendor phylocli/core.py phylocli/tests/test_vendor.py
git commit -m "vendor treeview into phylocli/vendor (update_treeview.sh)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: phylocli — `t` opens the HG's tree from Results

**Files:**
- Modify: `phylocli/model.py` (new `hg_tree_files` after `read_ogs`)
- Modify: `phylocli/tui.py` (`PhyloApp.BINDINGS`, new `action_open_tree`, `_load_tree`, `_push_tree`)
- Test: `phylocli/tests/test_model.py`, `phylocli/tests/test_tui.py`

**Interfaces:**
- Consumes: vendored `treeview.model` (`load`, `load_meta`, `load_colours`, `TreeModel` with `.tip`, `.mrca`), `treeview.widget.TreeScreen(model, title=, path=, focus=, highlight=)`; phylocli `model.species_info_path(cfg)`, `model.OG_SUFFIX`, `core.report_status.nonempty_files(str(dir))` (as `read_ogs` uses it), `self._cur_res()`, `self._cur_og()`, `self._key_at_cursor(table)`, `self.res_source`.
- Produces: `model.hg_tree_files(cfg, hg: str, source: str) -> "tuple[Path, Path] | None"` = (tree, ortholog_groups.csv).

- [ ] **Step 1: Write the failing tests**

Append to `phylocli/tests/test_model.py`:

```python
def test_hg_tree_files_from_the_og_csv_name(cli):
    cfg = _cfg()
    write_results(cfg)
    tree, csv = model.hg_tree_files(cfg, "tfs.A.HG1", "possvm")
    assert csv.name == "tfs.A.HG1.generax.support.tree.ortholog_groups.csv"
    assert tree == cfg.outdir / "possvm/tfs.A.HG1.generax.support.tree"
    assert model.hg_tree_files(cfg, "tfs.A.HG1", "possvm_prev")[0].name == "tfs.A.HG1.treefile"
    assert model.hg_tree_files(cfg, "tfs.C_x.HG1", "possvm") is None
```

Append to `phylocli/tests/test_tui.py`:

```python
TREE_HG1 = ("((Mlei_v05_G1:1,Mlei_v05_G2:1)90:1,"
            "(Hsap_ENSP1:1,(Hsap_ENSP2:1,Nvec_v1_g3:1)50:1)70:1);\n")


def _write_trees(cfg):
    (cfg.outdir / "possvm/tfs.A.HG1.generax.support.tree").write_text(TREE_HG1)
    (cfg.outdir / "possvm_prev/tfs.A.HG1.treefile").write_text("(Mlei_v05_G1:1,Zzz_q1:1);\n")


async def _press_t(app, pilot, pane, row):
    t = app.query_one(pane)
    t.focus()
    t.move_cursor(row=row)
    await pilot.pause()
    await pilot.press("t")
    await app.workers.wait_for_complete()
    await pilot.pause()
    await pilot.pause()


def test_t_opens_the_tree_at_the_hg_og_and_member(cli, monkeypatch):
    write_results(_cfg())
    _write_trees(_cfg())

    async def go():
        from treeview.widget import TreeScreen, TreeView
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        notes = []
        orig = app.notify
        monkeypatch.setattr(app, "notify",
                            lambda msg, *a, **k: (notes.append(str(msg)), orig(msg, *a, **k)))
        async with app.run_test(size=(160, 50)) as pilot:
            await _open_results(app, pilot, "tfs")
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG1"
            await _press_t(app, pilot, "#res", 0)                     # HG: whole tree, root
            assert isinstance(app.screen, TreeScreen)
            tv = app.screen.query_one(TreeView)
            m = tv.model
            assert tv.cursor == 0 and m.highlight == set() and m.meta_cols[0] == "orthogroup"
            assert "tfs.A.HG1 · possvm" in tv.border_title
            await pilot.press("escape")
            await pilot.pause()
            assert app.view == "results" and not isinstance(app.screen, TreeScreen)
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG1"     # state kept

            await _press_t(app, pilot, "#ogs", 1)                     # OG: MRCA, members marked
            assert app._cur_og().id == "tfs.A.HG1.1"
            tv = app.screen.query_one(TreeView)
            m = tv.model
            want = {m.tip("Hsap_ENSP2"), m.tip("Nvec_v1_g3")}
            assert m.highlight == want and tv.cursor == m.mrca(want) and m.support[tv.cursor] == 50
            await pilot.press("escape", "escape")                     # clear highlight, leave
            await pilot.pause()

            await _press_t(app, pilot, "#members", 0)                 # member: its tip
            tv = app.screen.query_one(TreeView)
            assert tv.cursor == tv.model.tip("Hsap_ENSP2") and tv.model.highlight == set()
            await pilot.press("escape")
            await pilot.pause()

            app.query_one("#res").focus()
            await pilot.press("p")                                     # possvm_prev: other file
            await app.workers.wait_for_complete()
            await pilot.pause()
            await _press_t(app, pilot, "#res", 0)
            tv = app.screen.query_one(TreeView)
            assert "possvm_prev" in tv.border_title
            assert {tv.model.name[i] for i in range(len(tv.model)) if tv.model.is_tip(i)} == {
                "Mlei_v05_G1", "Zzz_q1"}
            await pilot.press("escape")
            await pilot.pause()
            assert not [n for n in notes if "tree" in n]
    _run(go())


def test_t_missing_tree_and_members_not_in_tree_notify(cli, monkeypatch):
    write_results(_cfg())
    (_cfg().outdir / "possvm/tfs.A.HG1.generax.support.tree").write_text("(x_1:1,y_2:1);\n")

    async def go():
        from treeview.widget import TreeScreen, TreeView
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        notes = []
        orig = app.notify
        monkeypatch.setattr(app, "notify",
                            lambda msg, *a, **k: (notes.append(str(msg)), orig(msg, *a, **k)))
        async with app.run_test(size=(160, 50)) as pilot:
            await _open_results(app, pilot, "tfs")
            await _press_t(app, pilot, "#ogs", 0)                     # 3 members, none in tree
            assert isinstance(app.screen, TreeScreen)
            assert app.screen.query_one(TreeView).cursor == 0       # mrca([]) = root
            assert any("3 of 3 members not in the tree" in n for n in notes)
            await pilot.press("escape")
            await pilot.pause()
            await _press_t(app, pilot, "#res", 1)                     # tfs.A.HG11: no tree file
            assert not isinstance(app.screen, TreeScreen) and app.view == "results"
            assert any("no tree" in n and "tfs.A.HG11" in n for n in notes)
    _run(go())


def test_phylocli_keys_do_nothing_while_the_tree_is_open(cli):
    write_results(_cfg())
    _write_trees(_cfg())

    async def go():
        from treeview.widget import TreeScreen
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test(size=(160, 50)) as pilot:
            await _open_results(app, pilot, "tfs")
            await _press_t(app, pilot, "#res", 0)
            assert isinstance(app.screen, TreeScreen)
            gen = app._res_gen
            await pilot.press("p", "R", "o", "f")          # phylocli keys: must not act underneath
            await pilot.pause()
            assert app.res_source == "possvm" and app._res_gen == gen and app.view == "results"
            assert isinstance(app.screen, TreeScreen)
    _run(go())
```

Check the fixture first: `write_results` gives `tfs.A.HG1` two OGs sorted by size — `tfs.A.HG1.0` (3 genes) at row 0 and `tfs.A.HG1.1` (Hsap_ENSP2, Nvec_v1_g3) at row 1 — and `#members` of OG 1 lists `Hsap_ENSP2` first; adjust the row numbers only if the default sort says otherwise (and say so in the report).

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt && $PY -m pytest phylocli/tests/test_model.py phylocli/tests/test_tui.py -q -p no:cacheprovider -k "hg_tree_files or t_opens or t_missing"`
Expected: FAIL — `AttributeError: module 'phylocli.model' has no attribute 'hg_tree_files'`, no `t` binding.

- [ ] **Step 3: Implement `model.hg_tree_files`**

After `read_ogs` in `phylocli/model.py`:

```python
def hg_tree_files(cfg: core.Config, hg: str, source: str) -> "tuple[Path, Path] | None":
    """(tree, ortholog_groups.csv) of one HG in <outdir>/<source>/.  The csv is found as read_ogs
    finds it (<hg>.<tree file name>.ortholog_groups.csv); the tree is that name without the
    suffix: <hg>.generax.support.tree in possvm/, <hg>.treefile in possvm_prev/.  None when there
    is not exactly one non-empty csv; the tree file may still be missing (the caller says so)."""
    d = cfg.outdir / source
    names = core.report_status.nonempty_files(str(d))
    files = sorted(n for n in names if n.startswith(hg + ".") and n.endswith(OG_SUFFIX))
    if len(files) != 1:
        return None
    return d / files[0][:-len(OG_SUFFIX)], d / files[0]
```

- [ ] **Step 4: Implement the TUI action**

`phylocli/tui.py`, `PhyloApp.BINDINGS`: add `Binding("t", "open_tree", "tree"),` after the `o` binding.

Add to `PhyloApp` (near `action_open_results`):

```python
    def action_open_tree(self) -> None:
        """t in Results: the HG's gene tree in treeview (vendored), from the current p source.
        Cursor in #res -> the root; #ogs -> the OG's MRCA, its members highlighted; #members ->
        that member's tip.  esc in the tree comes back here unchanged."""
        if self.view == "overview" and self.tab == "results":
            self.notify("open a group's Results (o), then t", severity="warning")
            return
        if self.view != "results" or self.res_source is None:
            return
        r = self._cur_res()
        if r is None:
            self.notify("no HG under the cursor", severity="warning")
            return
        pane = getattr(self.focused, "id", None) or "res"
        og = self._cur_og() if pane == "ogs" else None
        gene = None
        if pane == "members":
            key = self._key_at_cursor(self.query_one("#members", DataTable))
            gene = key.split(":", 1)[1] if key else None
        self._load_tree(r.hg, self.res_source, og, gene)

    @work(thread=True, exclusive=True, group="tree")
    def _load_tree(self, hg: str, source: str, og, gene: "str | None") -> None:
        """Reads the newick, its ortholog_groups.csv (as metadata) and species_info.tsv (colours)
        off the UI thread.  Any failure is a warning; the TUI never crashes on a bad tree."""
        notes = []
        try:
            from treeview import model as tvm      # vendored: core puts phylocli/vendor on sys.path
            files = model.hg_tree_files(self.cfg, hg, source)
            if files is None:
                raise FileNotFoundError(f"{hg}: no {source} output")
            path, csv = files
            if not path.is_file():
                raise FileNotFoundError(f"{hg}: no tree {path.name} in {source}/")
            tree = tvm.load(path)
            try:
                cols, meta = tvm.load_meta(csv)
            except (OSError, ValueError) as e:
                cols, meta = None, None
                notes.append(f"{csv.name}: {e} (no metadata)")
            try:
                colours = tvm.load_colours(model.species_info_path(self.cfg))
            except Exception:                  # colours are cosmetic: species hash colours
                colours = {}
            m = tvm.TreeModel(tree, sep="_", colours=colours, meta=meta, meta_cols=cols)
        except Exception as e:                 # missing file, bad newick, ...
            self.call_from_thread(self.notify, f"tree: {e}", severity="warning")
            return
        focus, hl, title = 0, [], f"{hg} · {source}"
        if og is not None:
            ids = [m.tip(g.gene) for g in og.genes]
            hl = [i for i in ids if i is not None]
            if len(hl) < len(ids):
                notes.append(f"{len(ids) - len(hl)} of {len(ids)} members not in the tree")
            focus = m.mrca(hl)
            title += f" · {og.id}"
        if gene is not None:
            i = m.tip(gene)
            if i is None:
                notes.append(f"{gene} not in the tree")
            else:
                focus = i
            title += f" · {gene}"
        self.call_from_thread(self._push_tree, m, focus, hl, title, path, notes)

    def _push_tree(self, m, focus: int, hl: list, title: str, path, notes: list) -> None:
        from treeview.widget import TreeScreen
        self.push_screen(TreeScreen(m, title=title, path=path, focus=focus, highlight=hl))
        for n in notes:
            self.notify(n, severity="warning")
```

In `PhyloApp.check_action` (it exists: "Footer shows only the keys of the current view"), add as its **first** lines:

```python
        if action != "quit" and type(self.screen).__name__ in ("TreeScreen", "KeysScreen"):
            return False                     # the tree / key list owns the keys; q still quits
        if action == "open_tree":
            return self.view == "results" or (self.view == "overview" and self.tab == "results")
```

(by class name, so `check_action` needs no import of the vendored package; `KeysScreen` arrives in Task 7, listing it now is harmless). Check that the `#res`, `#ogs`, `#members` widget ids are exactly `res`, `ogs`, `members` (they are queried as `#res` etc. in `tui.py`). Check that `TreeScreen`'s `q` (app binding) still quits phylocli and `escape` pops back (TreeScreen's `action_back` pops when `len(app.screen_stack) > 1`).

- [ ] **Step 5: Run the whole phylocli suite**

Run: `cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt && $PY -m pytest phylocli/tests -q -p no:cacheprovider`
Expected: all pass (389 + 4 = 393).

- [ ] **Step 6: Real-data check (read-only, headless)**

```bash
cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt && $PY - <<'EOF'
import sys; sys.path.insert(0, "."); sys.path.insert(0, "workflow"); sys.path.insert(0, "phylocli/vendor")
from pathlib import Path
from treeview import model as tvm
V = Path.home() / "ant/gzolotarov/projects/2022_scRNAseq_Mlei/Phylogenies_v3/results"
for src, name in (("possvm", "tfs.T-box.HG1.generax.support.tree"), ("possvm_prev", "tfs.T-box.HG1.treefile")):
    p = V / src / name
    cols, meta = tvm.load_meta(Path(str(p) + ".ortholog_groups.csv"))
    m = tvm.TreeModel(tvm.load(p), meta=meta, meta_cols=cols)
    ogs = {r[0] for r in meta.values()}
    print(src, m.ntips[0], "tips", m.meta_matched, "matched", len(ogs), "OGs", cols[:2])
EOF
```
Expected: `possvm 488 tips 488 matched 17 OGs ['orthogroup', 'orthogroup_support']`; a `possvm_prev` line with its own counts (report them).

- [ ] **Step 7: Commit**

```bash
cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt
git add phylocli/model.py phylocli/tui.py phylocli/tests/test_model.py phylocli/tests/test_tui.py
git commit -m "Results: t opens the HG's gene tree in treeview (root / OG MRCA / member tip)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: phylocli — `?` key screen and one-line help

**Files:**
- Modify: `phylocli/tui.py` (new module-level `KEYS`, `PhyloApp.BINDINGS` `?`, `_help_for`, new `_keys_view`, `action_keys`)
- Test: `phylocli/tests/test_tui.py` (new test; edit `test_strip_with_help_and_no_logo_is_in_every_view`)

**Interfaces:**
- Consumes: vendored `treeview.keys.KeysScreen`, `missing_keys` (Task 2, via Task 5).
- Produces: `tui.KEYS: dict` = `{view key: (title, groups)}` with view keys `"overview"`, `"overview_results"`, `"hgs"`, `"results"`.

- [ ] **Step 1: Write the failing tests**

Append to `phylocli/tests/test_tui.py`:

```python
def test_every_binding_is_in_a_key_table_and_question_mark_opens_it(cli):
    from treeview.keys import KeysScreen, missing_keys
    groups = [g for _, gs in tui.KEYS.values() for g in gs]
    assert missing_keys(tui.PhyloApp.BINDINGS + tui.SortTable.BINDINGS, groups) == []
    assert set(tui.KEYS) == {"overview", "overview_results", "hgs", "results"}

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test(size=(150, 40)) as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, KeysScreen)
            text = app.screen.query_one("#keys").render().plain
            assert "results of the group" in text
            await pilot.press("q")                                   # closes the list only
            await pilot.pause()
            assert not isinstance(app.screen, KeysScreen) and app.is_running
    _run(go())


def test_results_key_table_lists_t():
    _, groups = tui.KEYS["results"]
    assert any(k == "t" for _, rows in groups for k, _ in rows)
```

Edit `test_strip_with_help_and_no_logo_is_in_every_view`: replace the asserts after `assert len(set(helps.values())) == 3` (from `from rich.text import Text` through `assert "possvm_prev" in helps["results"]`) with:

```python
            from rich.text import Text
            plain = {v: Text.from_markup(h).plain for v, h in helps.items()}
            assert all("? keys" in p and "\n" not in p for p in plain.values())
            assert "█ done" in plain["overview"]                     # the glyph legend stays
            assert plain["hgs"].startswith("HG view") and plain["results"].startswith("Results")
```

Keep the line `assert "enter: open" not in app.query_one("#ovfoot").render().plain`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt && $PY -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider -k "key_table or strip_with_help"`
Expected: FAIL — `AttributeError: module 'phylocli.tui' has no attribute 'KEYS'`.

- [ ] **Step 3: Implement**

`phylocli/tui.py`, module level (after the `FILTERS`/`STATE_STYLE` definitions it references; place it just before `class PhyloApp`):

```python
# The `?` key screens (Grygoriy, 12/10/2026): one table per view; the help strip is one line.
KEYS = {
    "overview": ("Overview · Jobs", [
        ("Move", [("↑ ↓ ← →", "move · ↑ on the first row: the header (←/→ column, enter/s sort)"),
                  ("tab shift+tab", "Results tab")]),
        ("Open", [("enter", "open the group at that stage (HG view)"),
                  ("o", "results of the group")]),
        ("Group & sort", [("c", "group by category"), ("f", "group by family"),
                          ("s", "sort by the column"), ("h", "only actionable at the column")]),
        ("Other", [("R", "refresh"), ("?", "this list"), ("q", "quit")]),
        ("Notes", [("", "search/cluster count families, the other stages HGs"),
                   ("", "default view: failed+ready")])]),
    "overview_results": ("Overview · Results tab", [
        ("Move", [("↑ ↓ ← →", "move · ↑ on the first row: the header (←/→ column, enter/s sort)"),
                  ("tab shift+tab", "Jobs tab")]),
        ("Open", [("enter o", "open the group's Results"),
                  ("t", "trees open from a group's Results (o, then t)")]),
        ("Source", [("p", "possvm ↔ possvm_prev")]),
        ("Group & sort", [("c", "group by category"), ("f", "group by family"),
                          ("s", "sort by the column"), ("h", "hide rows with 0 in the column")]),
        ("Other", [("R", "re-read"), ("?", "this list"), ("q", "quit")]),
        ("Notes", [("⚠", "sup 0 = OGs with support 0 (GeneRax bug case)")])]),
    "hgs": ("HG view", [
        ("Move", [("tab shift+tab", "next / previous pane"), ("↑ ↓", "move"),
                  ("enter", "on stages: pick the stage")]),
        ("Select & act", [("space", "select the HG"), ("a", "select all"),
                          ("r", "resubmit the selected"), ("l", "log of the HG")]),
        ("Filter", [("f", "cycle the filter (" + ", ".join(FILTERS) + ")")]),
        ("Other", [("o", "results of the HG's group"), ("esc", "back to the overview"),
                   ("R", "refresh"), ("?", "this list"), ("q", "quit")]),
        ("Notes", [("", "default filter: failed+ready; the states are "
                    + " · ".join(STATE_STYLE))])]),
    "results": ("Results", [
        ("Move", [("tab shift+tab", "next / previous pane"), ("↑ ↓", "move"),
                  ("s", "sort (↑ on the first row: the header)")]),
        ("Look", [("/", "filter this pane"), ("p", "possvm ↔ possvm_prev"),
                  ("t", "gene tree: HG → whole tree · OG → its MRCA, members marked · "
                        "member → its tip")]),
        ("Other", [("esc", "clear filters, then back"), ("R", "refresh"), ("?", "this list"),
                   ("q", "quit")]),
        ("Notes", [("⚠", "support 0 = GeneRax bug case; check possvm_prev")])]),
}
```

`missing_keys` splits key cells on spaces; an empty key cell (`""`) adds no token, which is fine for the Notes rows. If a binding of `PhyloApp.BINDINGS` is still reported missing (e.g. `space`, `a`, `escape`), add it to the table of the view where it acts, with the description from the old help text; do not remove bindings.

`keys_text` computes `w = max(len(k) ...)` per group; a Notes group whose keys are all `""` gets `w = 0`, which is fine.

`PhyloApp.BINDINGS`: add `Binding("question_mark", "keys", "keys"),` before the `q` binding.

Add to `PhyloApp`:

```python
    def _keys_view(self) -> str:
        if self.view == "overview":
            return "overview_results" if self.tab == "results" else "overview"
        return self.view

    def action_keys(self) -> None:
        from treeview.keys import KeysScreen     # vendored (core puts phylocli/vendor on sys.path)
        title, groups = KEYS[self._keys_view()]
        self.push_screen(KeysScreen(f"phylocli keys · {title}", groups))
```

Replace the body of `_help_for(self, view)` with one line per view (the overview keeps its glyph legend):

```python
    def _help_for(self, view: str) -> str:
        key = "overview_results" if view == "overview" and self.tab == "results" else view
        title = KEYS.get(key, KEYS["overview"])[0]
        if key == "overview":
            glyphs = " ".join(f"[{fg}]{ch}[/] {name}" for (ch, fg), name in
                              zip(self.OV_GLYPHS, ("done", "running", "ready/failed", "blocked")))
            return f"[b]{title}[/]  {glyphs}  · ? keys"
        return f"[b]{title}[/]  · ? keys"
```

- [ ] **Step 4: Run the whole phylocli suite**

Run: `cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt && $PY -m pytest phylocli/tests -q -p no:cacheprovider`
Expected: all pass (393 + 2 = 395). If another test asserted old help text (search `grep -n "_help_text\|help" phylocli/tests/test_tui.py`), change it to assert the key-table text instead and list it in the report.

- [ ] **Step 5: Commit**

```bash
cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt
git add phylocli/tui.py phylocli/tests/test_tui.py
git commit -m "? key screen per view; the help strip is one line

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the plan (controller, not a task)

- Deploy to v3 with the usual per-file procedure once `/users` accepts writes (v3 copies equal the base commit; tar backup into `v3/phylocli/backup-pre-treeview-<date>.tar.gz`; `cp f v3/f.new-tmp && mv`; `cmp`). Files: `phylocli/core.py`, `phylocli/model.py`, `phylocli/tui.py`, `phylocli/vendor/**`, plus the pending `nextflow.config`, `submit_nf.sh`, `TODOs.md` (commits 475b44b, 0b65ca1).
- Smoke test on the cluster in `phylo` (headless pilot via ssh): open Results for `tfs`, `t` on T-box HG1 in both sources.
