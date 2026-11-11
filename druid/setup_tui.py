"""The TUI Setup tab (sub-project 2, 23/10/2026): proteome sources, the species picker, the analyses
switches, the base species tree (v3 curated / chromo / custom) and the placement of ticked species
missing from it, the search type, the families and the stage parameters (params_form: lists for
discrete settings, typed numbers), with the blockers `prepare` would report on the bottom line;
`P` runs prepare, `S` then step 1 (the Jobs tab's run box). Config writes go through
yamledit.update_config, the placements and families files through sptree / families (paths). An
adopted project (prepare: locked) is read-only throughout; a species-locked one (the first job
exists) in the Species and Tree sections and in the Parameters that affect every output (the cpus
and the families stay editable). Imported by druid.tui when the Setup tab opens."""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (ContentSwitcher, DataTable, Footer, Header, Input, Label, ListItem,
                             ListView, RadioButton, RadioSet, Select, Static, Switch)

from ete3 import Tree

from druid import core, families, params_form, paths, prepare, setup_state, sptree, yamledit
from druid.tui import DruidTreeScreen, RunScreen   # vendored TreeScreen + druid's key help; S's box
from treeview import model as tvm                # vendored: core puts druid/vendor on sys.path

SWITCHES = {"sw-generax": "run_generax", "sw-origins": "origins"}   # switch id -> params key
SRC_FIELDS = ("name", "dir", "glob", "tax")                          # #src-<field> inputs, in order
SEARCH = {"rb-file": "file", "rb-hmm": "hmm"}                         # radio id -> search type
# the editable families-file columns (#fe-<col>, in order) and what the pipeline does with each,
# checked 23/10/2026 in submodules/phylogeny/helper/hmmsearch.py and druid/stages/cluster.sh
EDIT_COLS = {"inflation": "inflation (per family; overrides the default params.s2_inflation)",
             "min_seqs": "min_seqs (per family; the stages use params.min_seqs)",
             "threshold": "threshold (GA: hmmsearch --cut_ga; else a --domE e-value)",
             "pref1": "pref1 (category)",
             "pref2": "pref2 (id prefix: the family id is <pref2>.<class_name>; pref1 when empty)"}
TREE_OFF = "placement not needed: GeneRax and origins are off (prepare reads and writes no species tree)"
# radio id -> setup_state.tree_base; the base tree the Tree section shows as
TREE_BASES = {"rb-tree-v3": "v3", "rb-tree-chromo": "chromo", "rb-tree-custom": "custom"}
TREE_LABELS = {"v3": "v3 curated, 59 tips", "chromo": "chromo, 94 tips", "custom": "tree_source"}
LOCKED_ALL = "read-only: adopted project (prepare: locked); druid never changes its druid.yaml here"
RUN_HINT = "S: run step 1 (search → cluster)"    # after a good prepare: the next step
OPTION_KEYS = "↑↓ move · space/enter toggle"     # Analyses switches, Tree / Search radio sets
PA_FIELDS = {f.key: f for f in params_form.FIELDS}   # Parameters: #pa-<key> -> its field
PA_STEP1_GROUP = "Clustering"                        # the step 1 group; every other is step 2
PA_FROZEN = ("read-only: set before the first job; changing it would change every output "
             "(the cpus stay editable)")
PA_NOCFG = "read-only until druid.yaml loads (see the errors below)"
PA_GX_OFF = "GeneRax is off (Analyses): these settings are not used"
PA_HELP = "a list: enter opens it, ↑↓ enter picks · a number or path: type it, enter writes"


def _default_inflation(raw: dict) -> str:
    """params.s2_inflation of a raw druid.yaml mapping ('1.1' when absent)."""
    params = raw.get("params") if isinstance(raw, dict) else None
    return str((params or {}).get("s2_inflation", "1.1")) if isinstance(params, dict) else "1.1"


def _resolve(p: str, root: Path) -> Path:
    q = Path(p).expanduser()
    return q if q.is_absolute() else root / q


def _fam_id(r: families.Row) -> str:
    return next(iter(families.ticked_ids([r])))


def _key(r: families.Row) -> tuple:
    """A row's family: its id and HMMs. The id alone is not unique (the library has neu.Synapsin
    twice, with different HMMs), nor is class_name + hmms (rbp.CSD and tfs.CSD)."""
    return _fam_id(r), r.hmms


def _merge(universe: list, file_rows: list) -> list:
    """[[Row, ticked]]: the universe in its order, each row replaced by its families-file row
    (ticked) — an identical row first, else the same family (id and hmms; settings edited), else
    the one row with that class_name and hmms (its prefix edited; never a guess between two, e.g.
    rbp.CSD / tfs.CSD); file rows matching none are appended, ticked. Empty file: none ticked
    (Grygoriy, 25/10/2026: start with no families selected)."""
    out = [[r, False] for r in universe]

    def match(rows, same, unique=False) -> list:
        left = []
        for f in rows:
            hits = [i for i, (r, t) in enumerate(out) if not t and same(r, f)]
            if hits and (not unique or len(hits) == 1):
                out[hits[0]] = [f, True]
            else:
                left.append(f)
        return left

    rest = match(file_rows, lambda r, f: r.fields() == f.fields())        # identical
    rest = match(rest, lambda r, f: _key(r) == _key(f))                     # settings edited
    rest = match(rest, lambda r, f: (r.class_name, r.hmms) == (f.class_name, f.hmms),
                 unique=True)                                               # prefix edited
    return out + [[f, True] for f in rest]


def _edit_error(v: dict) -> str:
    """Why the edit form's values cannot be saved ("" = fine)."""
    def positive(s):
        try:
            return float(s) > 0
        except ValueError:
            return False
    if not positive(v["inflation"]):
        return f"inflation must be a number > 0, not {v['inflation']!r}"
    if not v["min_seqs"].isdigit() or int(v["min_seqs"]) < 1:
        return f"min_seqs must be a whole number >= 1, not {v['min_seqs']!r}"
    if v["threshold"] != "GA" and not positive(v["threshold"]):
        return f"threshold must be GA or an e-value > 0, not {v['threshold']!r}"
    for c in ("pref1", "pref2"):
        if any(ch.isspace() or ch == "." for ch in v[c]):
            return f"{c} takes no spaces or dots: {v[c]!r}"
    if not v["pref1"] and not v["pref2"]:
        return "pref1 or pref2 must be set (the family id prefix)"
    return ""


def _ticked_note(sps: list, most: int = 5) -> str:
    """"+3 ticked (Mlei, Hcal, Bova)"; the names left out past `most`: "+42 ticked"."""
    note = f"+{len(sps)} ticked"
    return f"{note} ({', '.join(sps)})" if len(sps) <= most else note


def _species_filter(cands: list, text: str, root=None) -> tuple:
    """(shown, not_found) for the Species filter. "@v3", "@chromo" or "@<file>": that species set
    (setup_state.species_set; Grygoriy, 06/11/2026), its codes that are no candidate (or the one
    error) as not_found. Two or more words separated by commas or spaces,
    at least one of them a candidate's prefix (case ignored): the list of prefixes, in the order
    typed, and the words that are no prefix (Grygoriy, 25/10/2026). Otherwise (one word, or a
    phrase such as "Metazoa, Ctenophora" or a Latin name): a substring of any column."""
    prefixes = {c.sp.lower() for c in cands}
    if text.strip().startswith("@"):
        codes, err = setup_state.species_set(text, root if root is not None else paths.project_root())
        if err:
            return [], [err]
        shown = [c for w in dict.fromkeys(w.lower() for w in codes)
                 for c in cands if c.sp.lower() == w]
        return shown, [w for w in codes if w.lower() not in prefixes]
    words = [w for w in re.split(r"[,\s]+", text.strip()) if w]
    if len(words) > 1 and any(w.lower() in prefixes for w in words):
        shown = [c for w in dict.fromkeys(w.lower() for w in words)
                 for c in cands if c.sp.lower() == w]
        return shown, [w for w in words if w.lower() not in prefixes]
    q = text.strip().lower()
    return [c for c in cands if not q or
            any(q in str(v).lower() for v in (c.sp, c.name, c.taxonomy, c.source))], []


def _named_list(cands: list, text: str) -> bool:
    """The filter names species (an @set, or a list of prefixes) rather than searching."""
    text = text.strip()
    if text.startswith("@"):
        return True
    words = [w.lower() for w in re.split(r"[,\s]+", text) if w]
    return len(words) > 1 and bool(set(words) & {c.sp.lower() for c in cands})


def _tick(ticked: bool) -> Text:
    """The tick cell as plain text: a str "[x]" is Rich markup to a DataTable and shows nothing."""
    return Text("[x]" if ticked else "[ ]")


class PlaceScreen(DruidTreeScreen):
    """The species tree as built now (base tree, ticked species, earlier placements) in the
    vendored treeview; p dismisses with the tip names under the cursor node, which the new species
    becomes the sister of (a tip or an internal node); esc leaves without a placement."""
    BINDINGS = [Binding("p", "place", "place here")]

    def on_mount(self) -> None:
        """Tips on consecutive rows, each internal node on its own row between its children's
        (TreeView gap 0, not the compact -1 the gene trees open in; Grygoriy, 23/10/2026)."""
        self.tree.gap = 0
        self.tree.rebuild()

    def action_place(self) -> None:
        m, i = self.model, self.tree.cursor
        self.dismiss(frozenset(m.name[j] for j in range(i, i + m.size[i]) if m.is_tip(j)))


class PickScreen(DruidTreeScreen):
    """t in Species / Tree (Grygoriy, 11/11/2026): the base tree with the placements grafted and a
    tick column ([x] / [ ] / — no proteome); x ticks the tips with a proteome under the cursor
    (a tip, or a whole clade), or unticks them when all are ticked. Each x writes druid.yaml
    through `toggle(names) -> message`; `ticked()` is the ticked species after it."""
    BINDINGS = [Binding("x", "tick", "tick tip / clade")]

    def __init__(self, model, toggle, ticked, **kwargs):
        super().__init__(model, **kwargs)
        self._toggle, self._ticked = toggle, ticked
        if self.n_grouped:                       # the tick column is no grouping: all open
            model.expand_all()
            self.n_grouped = 0

    def on_mount(self) -> None:
        self.tree.gap = 0
        self.tree.show_meta = True
        self.tree.rebuild()

    def action_tick(self) -> None:
        m, i = self.model, self.tree.cursor
        names = [m.name[j] for j in range(i, i + m.size[i])
                 if m.is_tip(j) and m.meta_value(j, "tick") != "—"]
        if not names:
            self._status("no species with a proteome here")
            return
        note = self._toggle(names)
        ticked = self._ticked()
        for j, row in m.meta.items():
            if row[0] != "—":
                row[0] = "[x]" if m.name[j] in ticked else "[ ]"
        self.tree.rebuild()
        self._status(note)


class SetupScreen(Screen):
    """Left: the sections, each with a mark (✓ fine, ! needs attention, a number = how many);
    right: the highlighted section; bottom: the last error and the blockers."""
    SECTIONS = ("Project", "Source", "Species", "Analyses", "Tree", "Search", "Families", "Parameters")
    DEFAULT_CSS = """
    SetupScreen #setup-tabbar { height: 1; }
    SetupScreen #setup-body { height: 1fr; }
    SetupScreen #sections { width: 18; border: round $primary; }
    SetupScreen #sections:focus { border: round orange; }
    SetupScreen #content { width: 1fr; border: round $primary; }
    SetupScreen #content:focus-within { border: round orange; }
    SetupScreen #content > * { height: 1fr; }
    SetupScreen #sp-table { height: 1fr; }
    SetupScreen #sp-table:focus { border: round orange; }
    SetupScreen #tree-missing { height: 1fr; }
    SetupScreen #tree-missing:focus { border: round orange; }
    SetupScreen #fam-table { height: 1fr; }
    SetupScreen #fam-table:focus { border: round orange; }
    SetupScreen #fam-edit { height: auto; display: none; }
    SetupScreen #fam-edit-help { display: none; }
    SetupScreen #fam-edit Input { width: 1fr; }
    SetupScreen #se-type { height: auto; }
    SetupScreen #tree-base { height: auto; }
    SetupScreen .row { height: auto; }
    SetupScreen .row Label { padding: 1 1; }
    SetupScreen .row:focus-within { background: $boost; }
    SetupScreen .row:focus-within Label { text-style: bold; }
    SetupScreen Switch:focus { border: tall orange; }
    SetupScreen RadioSet:focus { border: tall orange; }
    SetupScreen .note { color: $text-muted; height: auto; }
    SetupScreen .pa-group { text-style: bold; height: auto; padding: 1 0 0 0; }
    SetupScreen #pa-cols { height: auto; }
    SetupScreen .pa-col { width: 1fr; height: auto; padding: 0 1; }
    SetupScreen #pa-step1 { border-right: solid $primary; }
    SetupScreen .pa-step { text-style: bold underline; height: auto; }
    SetupScreen #sec-parameters .row Label { width: 22; }
    SetupScreen #sec-parameters Select { width: 1fr; }
    SetupScreen #sec-parameters Input { width: 1fr; }
    SetupScreen #blockers { height: auto; max-height: 8; color: $warning; }
    SetupScreen #warnings { height: auto; max-height: 8; display: none; border: round $primary; }
    SetupScreen #warnings:focus { border: round orange; }
    SetupScreen #warn-text { color: $text-muted; }
    """
    BINDINGS = [
        # tab moves between the panes and controls, never out of Setup: esc on the list leaves
        # (Grygoriy, 23/10/2026); the app's own tab would switch the first-screen tabs
        Binding("tab", "focus_move(1)", "next pane"),
        Binding("shift+tab", "focus_move(-1)", "previous pane", show=False),
        Binding("escape", "back", "back"),
        Binding("space", "toggle", "tick"),
        Binding("a", "tick_all", "tick shown"),
        Binding("A", "untick_all", "untick shown"),
        Binding("e", "edit_family", "edit row"),     # Families; enter ticks (Grygoriy, 23/10/2026)
        Binding("t", "tree_pick", "species tree"),   # Species / Tree (Grygoriy, 11/11/2026)
        Binding("u", "toggle_unplaced", "unplaced"),
        Binding("P", "prepare", "prepare"),
        Binding("S", "run_step1", "run step 1"),
        Binding("w", "toggle_warnings", "warnings"),
        # Analyses: ↑↓ between the switches (the radio sets move by themselves; Grygoriy 23/10/2026)
        Binding("up", "switch_move(-1)", "previous", show=False),
        Binding("down", "switch_move(1)", "next", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.current = self.SECTIONS[0]
        self._msg = ""                           # the last action's error / note, top of #blockers
        self._cmd = ""                           # a `:` command being typed, above it
        self._show_warn = False                  # w: the warnings list (off: only their count)
        self._raw: dict = {}
        self._cfg = None                         # core.Config, None when druid.yaml does not load
        self._errors: list = []                  # ERROR: ... lines (config, sources, blockers)
        self._srcs: list = []
        self._cands: list = []
        self._rowless: list = []
        self._sel: list = []                     # [(sp, source)], the species: order
        self._shown: list = []                   # candidates passing the filter, as in #sp-table
        self._show_unplaced = False              # u: species not on the base tree (11/11/2026)
        self._placed = None                      # base tree tips + placed species; None: unknown
        self._sp_unknown: list = []              # filter words that are no prefix (a list typed)
        self._blockers: list = []
        self._warnings: list = []                # core.family_warnings: shown, never blocking
        self._ro_all = False                     # prepare: locked
        self._sp_reason = ""                     # why Species / Tree are read-only ("" = editable)
        self._tree_on = True                     # GeneRax or origins on: a species tree is needed
        self._tree_file = None                   # the base binary tree (setup_state.base_tree_files)
        self._tree_err = ""                      # why the tree cannot be read ("" = fine)
        self._built = ""                         # the binary tree as built now (newick)
        self._missing: list = []                 # ticked species not on it
        self._placements: list = []              # sptree.Placement, data/placements.tsv
        self._tree_custom = False                # "custom" chosen, its tree_source not yet entered
        self._search = None                      # "file" | "hmm"; hmm_dir set in druid.yaml wins
        self._hmm_dir = None                     # params.hmm_dir resolved, None when unset
        self._fam_target = None                  # params.genefam_info (data/families.csv)
        self._fam: list = []                     # [[families.Row, ticked]] in table order
        self._fam_extra: list = []               # file-only rows seen this session (kept unticked)
        self._fam_extra_src = None               # the families source they were seen under
        self._fam_nfile = 0                      # rows in the families file
        self._fam_shown: list = []               # indices into _fam passing the filter
        self._fam_edit = None                    # the _fam index in the edit form
        self._pa_opts: dict = {}                 # Parameters: key -> the options its Select shows
        self._pa_frozen = False                  # Parameters: frozen fields read-only (first job)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="setup-tabbar")
        with Horizontal(id="setup-body"):
            yield ListView(*[ListItem(Label(s, id=f"lbl-{s.lower()}"), id=f"item-{s.lower()}")
                             for s in self.SECTIONS], id="sections")
            with ContentSwitcher(id="content", initial="sec-project"):
                with Vertical(id="sec-project"):
                    yield Static("", id="pj-reason", classes="note", markup=False)
                    yield Static("job_prefix: your SLURM job names are <job_prefix>-<stage> "
                                 "(letters, digits, _; 1-20 characters, first a letter)",
                                 classes="note", markup=False)
                    yield Input(placeholder="job_prefix: your SLURM job names are <job_prefix>-<stage>",
                                id="job-prefix")
                with Vertical(id="sec-source"):
                    yield Static("", id="src-list", markup=False)
                    yield Static("add a custom source (enter: next field · enter on the last: add)",
                                 classes="note")
                    yield Input(placeholder="name", id="src-name")
                    yield Input(placeholder="proteome directory (read-only)", id="src-dir")
                    yield Input(placeholder=f"glob (default {setup_state.DEFAULT_GLOB})",
                                id="src-glob")
                    yield Input(placeholder="taxonomy table (default: the shipped one)", id="src-tax")
                with Vertical(id="sec-species"):
                    yield Static("", id="sp-reason", classes="note", markup=False)
                    yield Input(placeholder="filter (any column, or prefixes: Mlei, Hsap Nvec) · "
                                            "enter: tick all shown",
                                id="sp-filter")
                    yield Static("sets: @v3 (59) · @chromo (94) · @<file> (one code per line) · "
                                 "t: pick on the tree · u: species not on the tree",
                                 classes="note", markup=False)
                    yield DataTable(id="sp-table", cursor_type="row")
                    yield Static("", id="sp-count", markup=False)
                with Vertical(id="sec-analyses"):
                    yield Static("", id="an-reason", classes="note", markup=False)
                    yield Static(OPTION_KEYS, classes="note", markup=False)
                    with Horizontal(classes="row"):
                        yield Switch(id="sw-generax")
                        yield Label("GeneRax gene-tree reconciliation (params.run_generax)")
                    with Horizontal(classes="row"):
                        yield Switch(id="sw-origins")
                        yield Label("orthogroup origins on ORIGIN_TREE (params.origins)")
                    yield Static("Both off: no species tree is needed.", classes="note")
                with Vertical(id="sec-tree"):
                    yield Static("", id="tree-info", classes="note", markup=False)
                    yield Static(OPTION_KEYS, classes="note", markup=False)
                    with RadioSet(id="tree-base"):
                        yield RadioButton("v3 curated (59)", id="rb-tree-v3", value=True)
                        yield RadioButton("chromo (94)", id="rb-tree-chromo")
                        yield RadioButton("custom", id="rb-tree-custom")
                    yield Static("custom: one species tree of your own, used for both trees "
                                 "(tree_source; empty: the v3 curated tree)",
                                 id="tree-source-note", classes="note")
                    yield Input(placeholder="tree_source (newick)", id="tree-source")
                    yield DataTable(id="tree-missing", cursor_type="row")
                with Vertical(id="sec-search"):
                    yield Static("", id="se-reason", classes="note", markup=False)
                    yield Static(OPTION_KEYS, classes="note", markup=False)
                    with RadioSet(id="se-type"):
                        yield RadioButton("gene family file (Pfam HMM names)", id="rb-file",
                                          value=True)
                        yield RadioButton("custom HMMs (one family per <name>.hmm in params.hmm_dir)",
                                          id="rb-hmm")
                        yield RadioButton("custom query sequences: not available yet", id="rb-query",
                                          disabled=True)
                    yield Static("your own families file (tab-separated, the library's columns; "
                                 "empty: the shipped library)", classes="note")
                    yield Input(placeholder="families_source", id="se-famfile")
                    yield Static("custom HMM directory (read-only; enter: set params.hmm_dir)",
                                 classes="note")
                    yield Input(placeholder="params.hmm_dir", id="se-hmmdir")
                with Vertical(id="sec-families"):
                    yield Static("", id="fam-reason", classes="note", markup=False)
                    yield Input(placeholder="filter (any column · enter: the list)", id="fam-filter")
                    yield DataTable(id="fam-table", cursor_type="row")
                    yield Static("\n".join(EDIT_COLS.values()) + "\nenter: next field · enter on "
                                 "the last: save (the row is ticked) · esc: cancel",
                                 id="fam-edit-help", classes="note", markup=False)
                    with Horizontal(id="fam-edit"):
                        for col in EDIT_COLS:
                            inp = Input(id=f"fe-{col}")
                            inp.border_title = col
                            yield inp
                    yield Static("", id="fam-count", markup=False)
                # one scrolling form, a heading per stage group (spec 2026-11-04); the scroll
                # itself takes no focus: tab goes field to field
                with VerticalScroll(id="sec-parameters", can_focus=False):
                    yield Static("", id="pa-path", classes="note", markup=False)
                    yield Static("", id="pa-reason", classes="note", markup=False)
                    # step 1 (search + cluster) left, step 2 (align -> possvm) right, a vertical
                    # line between them (Grygoriy, 05/11/2026)
                    with Horizontal(id="pa-cols"):
                        for step, col_id in (("Step 1", "pa-step1"), ("Step 2", "pa-step2")):
                            with Vertical(id=col_id, classes="pa-col"):
                                yield Static(step, classes="pa-step", markup=False)
                                group = None
                                for f in params_form.FIELDS:
                                    if (f.group == PA_STEP1_GROUP) != (step == "Step 1"):
                                        continue
                                    if f.group != group:
                                        group = f.group
                                        yield Static(group, classes="pa-group", markup=False)
                                        if group == "GeneRax":
                                            yield Static("", id="pa-gx-note", classes="note",
                                                         markup=False)
                                    with Horizontal(classes="row"):
                                        yield Label(f.label)
                                        if f.kind in ("preset", "species"):
                                            # options come from the file in _fill_params
                                            yield Select([("", "")], allow_blank=False,
                                                         id=f"pa-{f.key}")
                                        else:
                                            yield Input(placeholder=f.key, id=f"pa-{f.key}")
        yield Static("", id="blockers", markup=False)
        with VerticalScroll(id="warnings"):          # w; height-limited, scrolls
            yield Static("", id="warn-text", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#sp-table", DataTable).add_columns("", "prefix", "name", "taxonomy", "source")
        self.query_one("#tree-missing", DataTable).add_columns("missing from the tree", "source")
        self.query_one("#fam-table", DataTable).add_columns("", "family", "hmms", *EDIT_COLS)
        self.query_one("#content").border_title = self.current
        txt = Text()
        txt.append("Jobs │ Results │ ")
        txt.append("[Setup]", style="reverse bold")
        txt.append("   tab: next pane · enter: open a section · esc q: back (on the list: to Jobs) · "
                   "w: warnings · :q! quit", style="dim")
        self.query_one("#setup-tabbar", Static).update(txt)
        self._reload()
        self._refresh()
        self.query_one("#sections", ListView).focus()

    # ---- state ------------------------------------------------------------------------------
    def _try(self, label: str, fn, default):
        """fn(), or `default` plus an ERROR line: a bad glob, path or table in druid.yaml or a
        custom source must never crash the screen (setup_state raises KeyError, ValueError, ...)."""
        try:
            return fn()
        except Exception as e:                   # anything: the screen shows it and stays up
            self._errors.append(f"ERROR: {label}: {type(e).__name__}: {e}")
            return default

    def _reload(self) -> None:
        """Re-read druid.yaml and everything derived from it."""
        self._errors = []
        root = paths.project_root()
        try:
            raw = paths.read_raw()
        except core.ConfigError as e:
            raw, self._cfg = {}, None
            self._errors.append(f"ERROR: {e}")
        else:
            self._cfg = self._try("druid.yaml", lambda: core.config_from_raw(raw), None)
            if not isinstance(raw, dict):
                raw = {}
        self._raw = raw
        self._srcs = self._try("sources", lambda: setup_state.sources(raw, root), [])
        self._cands, self._rowless = self._try(
            "proteome sources", lambda: setup_state.candidates(self._srcs), ([], []))
        self._sel = self._try("species", lambda: setup_state.selected(raw), [])
        self._ro_all = raw.get("prepare") == "locked"
        if self._ro_all:
            self._sp_reason = LOCKED_ALL
        elif self._cfg is None:
            self._sp_reason = "read-only until druid.yaml loads (see the errors below)"
        elif self._try("species lock", lambda: setup_state.species_locked(raw, self._cfg), True):
            self._sp_reason = ("read-only: the species are locked once the pipeline has run "
                               "(species_locked, a run in runs_dir, or results in outdir)")
        else:
            self._sp_reason = ""
        self._blockers = [] if self._cfg is None else self._try(
            "blockers", lambda: setup_state.blockers(raw, self._cfg, root), [])
        # duplicate ids, a class_name under two prefixes (rbp.CSD + tfs.CSD): allowed, not wanted
        # (Grygoriy, 23/10/2026): a warning line, never a blocker
        self._warnings = [] if self._cfg is None else self._try(
            "families file", lambda: core.family_warnings(self._cfg), [])
        params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
        self._reload_tree(raw, params, root)
        self._reload_families(raw, params, root)
        self._pa_frozen = self._cfg is not None and self._try(   # Parameters: the first job exists
            "parameters freeze", lambda: params_form.frozen(raw, self._cfg), True)

    def _reload_tree(self, raw: dict, params: dict, root: Path) -> None:
        """The base binary tree, the placements, the tree built from them and who is missing; a
        bad tree is the Tree section's own note (setup_state.blockers lists it as a blocker). Both
        switches off: only the base's path, nothing is read (Ruling K)."""
        self._tree_on = setup_state.trees_needed(params)
        self._tree_err, self._built, self._missing, self._placements = "", "", [], []
        try:
            self._tree_file = setup_state.base_tree_files(raw, root)[0]
        except Exception as e:                   # tree_source: ~nouser/... (expanduser), ...
            self._tree_file, self._tree_err = None, f"tree_source unusable: {type(e).__name__}: {e}"
            self._placed = None
            return
        try:                                     # Species hides the rest (Grygoriy, 11/11/2026)
            pl = sptree.read_placements(root / "data" / sptree.PLACEMENTS)
            self._placed = sptree.tips(self._tree_file.read_text()) | {x.sp for x in pl}
        except Exception:                        # unreadable tree: hide nothing
            self._placed = None
        if not self._tree_on:
            return
        species = list(dict.fromkeys(sp for sp, _src in self._sel))
        try:
            self._placements = sptree.read_placements(root / "data" / sptree.PLACEMENTS)
            base = self._tree_file.read_text().strip()
            self._built = sptree.build_trees(base, base, species, self._placements)[0]
            self._missing = sptree.missing(base, species, self._placements)
        except Exception as e:                   # unreadable / unparsable newick, a bad path, ...
            self._tree_err = f"species tree unreadable ({self._tree_file}): {type(e).__name__}: {e}"

    def _reload_families(self, raw: dict, params: dict, root: Path) -> None:
        """The families table: the library (or families_source) plus the hmm_dir rows, merged with
        the project's families file (its rows are the ticked set; none: nothing ticked)."""
        hd = params.get("hmm_dir")
        self._hmm_dir = _resolve(str(hd), root) if hd else None
        if self._hmm_dir is not None:
            self._search = "hmm"
            if not self._hmm_dir.is_dir():
                self._errors.append(f"ERROR: params.hmm_dir is not a directory: {self._hmm_dir}")
        elif self._search is None:
            self._search = "file"
        elif self._search == "hmm":
            self._errors.append("custom HMMs chosen: set params.hmm_dir in Search")
        self._fam_target = None
        if self._cfg is not None and self._cfg.params.get("genefam_info"):
            self._fam_target = Path(self._cfg.params["genefam_info"])
        universe = self._try("families", lambda: self._fam_universe(raw, root), [])
        file_rows = []
        if self._fam_target is not None and self._fam_target.is_file():
            file_rows = self._try(f"families file {self._fam_target}",
                                  lambda: families.read(self._fam_target), [])
        self._fam_nfile = len(file_rows)
        fam = _merge(universe, file_rows)
        # rows only the families file had stay listed (unticked) once unticked, for this Setup
        # session and this families source, so they can be ticked again (Grygoriy, 02/11/2026)
        src = (raw.get("families_source"), str(self._hmm_dir))
        if src != self._fam_extra_src:
            self._fam_extra, self._fam_extra_src = [], src
        for r, _t in fam[len(universe):]:
            if all(r.fields() != x.fields() for x in self._fam_extra):
                self._fam_extra.append(r)
        listed = {tuple(r.fields()) for r, _t in fam}
        self._fam = fam + [[r, False] for r in self._fam_extra if tuple(r.fields()) not in listed]

    def _fam_universe(self, raw: dict, root: Path) -> list:
        src = raw.get("families_source")
        rows = families.read(_resolve(str(src), root)) if src else families.library()
        if self._hmm_dir is not None and self._hmm_dir.is_dir():
            rows = rows + families.hmm_rows(self._hmm_dir, _default_inflation(raw))
        return rows

    def _write(self, changes: dict, done: str = "", fam_rows=None) -> None:
        """update_config(changes), then (fam_rows given) the families file; the error (nothing
        more written) on the bottom line; then re-read."""
        try:
            if changes:
                yamledit.update_config(changes)
            if fam_rows is not None:
                if self._fam_target is None:
                    raise core.ConfigError("no params.genefam_info to write the families to")
                families.write(self._fam_target, fam_rows)
        except (core.ConfigError, OSError, paths.OutsideProject) as e:
            self._msg = f"ERROR: {e}"
        else:
            self._msg = done
        self._reload()
        self._refresh()

    # ---- drawing ----------------------------------------------------------------------------
    def _marks(self) -> dict:
        nsrc_bad = any(e.startswith(("ERROR: sources", "ERROR: proteome")) for e in self._errors)
        nfam = sum(1 for _r, t in self._fam if t)
        hmm_bad = self._search == "hmm" and (self._hmm_dir is None or not self._hmm_dir.is_dir())
        return {"Project": "✓" if self._cfg is not None and (
                    self._cfg.job_prefix or self._ro_all) else "!",
                "Source": "!" if nsrc_bad or self._rowless else str(len(self._srcs)),
                "Species": str(len(self._sel)) if self._sel else "!",
                "Analyses": "✓",
                "Tree": "·" if not self._tree_on else "!" if self._tree_err or self._missing else "✓",
                "Search": "!" if hmm_bad else "✓",
                "Families": str(nfam) if nfam and self._fam_nfile else "!",
                "Parameters": "!" if self._cfg is None else "✓"}

    def _refresh(self) -> None:
        for name, mark in self._marks().items():
            self.query_one(f"#lbl-{name.lower()}", Label).update(f"{name:<9} {mark}")
        self._fill_project()
        self._fill_source()
        self._fill_species()
        self._fill_analyses()
        self._fill_tree()
        self._fill_search()
        self._fill_families()
        self._fill_params()
        self._fill_blockers()

    def show_command(self, text: str) -> None:
        """The `:` command being typed (PhyloApp._show_cmd), first on the bottom line; "" = none."""
        self._cmd = text
        self._fill_blockers()

    def _fill_blockers(self) -> None:
        """The bottom line: the command, the last note, the ERROR lines and the blockers, always;
        the warnings (never blocking) only as a count unless w shows them in their own scrolled
        box (Grygoriy, 23/10/2026: they took most of the screen)."""
        lines = [x for x in (self._cmd, self._msg) if x] + self._errors
        if self._blockers:
            lines.append("blockers: " + " · ".join(self._blockers))
        elif self._cfg is not None:
            lines.append("no blockers: ready for prepare")
        n = len(self._warnings)
        if n:                                    # last: the blockers line stays in view
            lines.append(f"{n} warning{'s' if n != 1 else ''} "
                         f"(w: {'hide' if self._show_warn else 'show'})")
        self.query_one("#blockers", Static).update("\n".join(lines))
        self.query_one("#warn-text", Static).update("\n".join(self._warnings))
        self.query_one("#warnings").display = self._show_warn and bool(n)

    def action_toggle_warnings(self) -> None:
        self._show_warn = not self._show_warn
        self._fill_blockers()

    def action_switch_move(self, d: int) -> None:
        """↑↓ in Analyses: the focus to the previous / next switch (the focused one is lit)."""
        sws = [s for s in self.query(Switch) if not s.disabled]
        if self.focused in sws:
            sws[min(max(sws.index(self.focused) + d, 0), len(sws) - 1)].focus()

    def _fill_project(self) -> None:
        inp = self.query_one("#job-prefix", Input)
        inp.disabled = self._ro_all
        self.query_one("#pj-reason", Static).update(LOCKED_ALL if self._ro_all else "")
        if not inp.has_focus:
            inp.value = str(self._raw.get("job_prefix") or "")

    def _set_job_prefix(self, value: str) -> None:
        if self._ro_all:
            self._refuse(LOCKED_ALL)
            return
        why = core.job_prefix_error(value)
        if why:
            self._refuse(f"ERROR: {why}")           # never written
            return
        self._write({("job_prefix",): value}, done=f"job_prefix = {value}")

    def _fill_source(self) -> None:
        n = {}
        for c in self._cands:
            n[c.source] = n.get(c.source, 0) + 1
        lines = [LOCKED_ALL, ""] if self._ro_all else []
        for s in self._srcs:
            where = "" if s.proteomes_dir.is_dir() else "  (directory not found)"
            lines.append(f"{s.name}: {s.proteomes_dir} · {s.glob}{where}")
            lines.append(f"    taxonomy {s.taxonomy} · {n.get(s.name, 0)} proteomes with a row")
        self.query_one("#src-list", Static).update("\n".join(lines))
        for k in SRC_FIELDS:
            self.query_one(f"#src-{k}", Input).disabled = self._ro_all

    def _fill_species(self) -> None:
        q = self.query_one("#sp-filter", Input).value.strip()
        self._shown, self._sp_unknown = _species_filter(self._cands, q)
        ticked = set(self._sel)
        # not on the base tree nor placed (Grygoriy, 11/11/2026): hidden unless u, ticked, or
        # named in a list (@set, prefixes); shown ones are dim
        placed = self._placed if self._placed is not None else {c.sp for c in self._cands}
        hidden = 0
        if not self._show_unplaced and not _named_list(self._cands, q):
            keep = [c for c in self._shown if c.sp in placed or (c.sp, c.source) in ticked]
            hidden, self._shown = len(self._shown) - len(keep), keep
        t = self.query_one("#sp-table", DataTable)
        row = t.cursor_row
        t.clear()
        dim = 0
        for c in self._shown:
            style = "" if c.sp in placed else "dim"
            dim += bool(style)
            tick = _tick((c.sp, c.source) in ticked)
            tick.style = style
            t.add_row(tick, *(Text(str(v), style=style) for v in (c.sp, c.name, c.taxonomy, c.source)))
        if self._shown:
            t.move_cursor(row=min(max(row, 0), len(self._shown) - 1))
        count = f"{len(self._sel)} ticked / {len(self._cands)}"
        if q:
            count += f" · {len(self._shown)} shown"
        if hidden:
            count += f" · {hidden} hidden: not on the tree (u: show)"
        if dim:
            count += f" · {dim} dim: not on the tree"
        if self._sp_unknown:
            count += " · not found: " + ", ".join(self._sp_unknown)
        self.query_one("#sp-count", Static).update(count)
        self.query_one("#sp-reason", Static).update(self._sp_reason)

    def _fill_analyses(self) -> None:
        params = self._raw.get("params")
        params = params if isinstance(params, dict) else {}
        values = {"sw-generax": bool(params.get("run_generax")),        # = setup_state.blockers
                  "sw-origins": bool(params.get("origins", True))}
        for wid, v in values.items():
            sw = self.query_one(f"#{wid}", Switch)
            with sw.prevent(Switch.Changed):     # showing a value is not a toggle
                sw.value = v
            sw.disabled = self._ro_all
        self.query_one("#an-reason", Static).update(LOCKED_ALL if self._ro_all else "")

    def _tree_base(self) -> str:
        """The base shown as chosen: "custom" while one is being entered, else from tree_source."""
        if self._tree_custom:
            return "custom"
        try:
            return setup_state.tree_base(self._raw, paths.project_root())
        except Exception:                        # tree_source: ~nouser/... (expanduser), ...
            return "custom"

    def _fill_tree(self) -> None:
        """The base choice and tree_source (always: Ruling K), the missing species (a switch on)."""
        base = self._tree_base()
        ro = bool(self._sp_reason)
        for rid, kind in TREE_BASES.items():     # the Changed this posts matches _tree_base: a no-op
            rb = self.query_one(f"#{rid}", RadioButton)
            if kind == base and not rb.value:
                rb.value = True
        self.query_one("#tree-base", RadioSet).disabled = ro
        ts = self._raw.get("tree_source")
        inp = self.query_one("#tree-source", Input)
        inp.disabled = ro
        if not inp.has_focus:
            inp.value = str(ts or "")
        t = self.query_one("#tree-missing", DataTable)
        t.display = self._tree_on
        t.disabled = ro
        lines = [self._sp_reason] if self._sp_reason else []
        lines.append(f"species tree: {self._tree_file} ({TREE_LABELS[base]})")
        if not self._tree_on:
            t.clear()
            lines.append(TREE_OFF)
            if self._tree_err:
                lines.append(f"ERROR: {self._tree_err}")
            self.query_one("#tree-info", Static).update("\n".join(lines))
            return
        src = dict(self._sel)
        row = t.cursor_row
        t.clear()
        for sp in self._missing:
            t.add_row(sp, src.get(sp, ""))
        if self._missing:
            t.move_cursor(row=min(max(row, 0), len(self._missing) - 1))
        if self._tree_err:
            lines.append(f"ERROR: {self._tree_err}")
        elif self._missing:
            lines.append(f"{len(self._missing)} ticked species missing · enter on one: the tree, "
                         "then p on the node it becomes the sister of")
        else:
            lines.append("every ticked species is on the tree")
        if self._placements:
            lines.append("placed: " + " · ".join(f"{x.sp} (sister of {len(x.tipset)} tips)"
                                                for x in self._placements))
        self.query_one("#tree-info", Static).update("\n".join(lines))

    def _fam_reason(self) -> str:
        """Why Search and Families are read-only ("" = editable; the species lock does not count)."""
        if self._ro_all:
            return LOCKED_ALL
        if self._cfg is None:
            return "read-only until druid.yaml loads (see the errors below)"
        return ""

    def _fill_search(self) -> None:
        reason = self._fam_reason()
        rs = self.query_one("#se-type", RadioSet)
        for rid, kind in SEARCH.items():     # the Changed this posts matches _search: a no-op
            rb = self.query_one(f"#{rid}", RadioButton)
            if kind == self._search and not rb.value:
                rb.value = True
        rs.disabled = bool(reason)
        for wid, value in (("#se-famfile", self._raw.get("families_source")),
                           ("#se-hmmdir", (self._raw.get("params") or {}).get("hmm_dir")
                            if isinstance(self._raw.get("params"), dict) else None)):
            inp = self.query_one(wid, Input)
            inp.disabled = bool(reason)
            if not inp.has_focus:
                inp.value = str(value or "")
        self.query_one("#se-hmmdir").display = self._search == "hmm"
        self.query_one("#se-reason", Static).update(reason)

    def _fill_families(self) -> None:
        q = self.query_one("#fam-filter", Input).value.strip().lower()
        self._fam_shown = [i for i, (r, _t) in enumerate(self._fam) if not q or
                           any(q in v.lower() for v in [_fam_id(r)] + r.fields())]
        t = self.query_one("#fam-table", DataTable)
        row = t.cursor_row
        t.clear()
        for i in self._fam_shown:
            r, ticked = self._fam[i]
            t.add_row(_tick(ticked), _fam_id(r), r.hmms,
                      *(getattr(r, c) for c in EDIT_COLS))
        if self._fam_shown:
            t.move_cursor(row=min(max(row, 0), len(self._fam_shown) - 1))
        n = sum(1 for _r, ticked in self._fam if ticked)
        count = f"{n} ticked / {len(self._fam)} → {self._fam_target or 'params.genefam_info'}"
        if q:
            count += f" · {len(self._fam_shown)} shown"
        if not self._fam_nfile:
            count += " · none ticked yet"
        self.query_one("#fam-count", Static).update(count)
        reason = self._fam_reason()
        self.query_one("#fam-reason", Static).update(
            reason or "space enter: tick / untick · a: tick all shown · e: edit the row's settings")

    # ---- Parameters -------------------------------------------------------------------------
    def _params(self) -> dict:
        p = self._raw.get("params")
        return p if isinstance(p, dict) else {}

    def _pa_reason(self, f: "params_form.Field") -> str:
        """Why field `f` is read-only now ("" = editable)."""
        if self._ro_all:
            return LOCKED_ALL
        if self._cfg is None:
            return PA_NOCFG
        if f.frozen and self._pa_frozen:
            return PA_FROZEN
        if f.group == "GeneRax" and not self._params().get("run_generax"):
            return PA_GX_OFF
        return ""

    def _fill_params(self) -> None:
        """Each field shows the file's value; showing it is never a write (Select.Changed is
        prevented here, and on_select_changed ignores what the user did not pick)."""
        params = self._params()
        species = list(dict.fromkeys(sp for sp, _src in self._sel))
        for f in params_form.FIELDS:
            w = self.query_one(f"#pa-{f.key}")
            cur = params.get(f.key)
            if isinstance(w, Select):
                opts = params_form.choices(f, cur, species) or [("(no species ticked)", "")]
                with w.prevent(Select.Changed):
                    if opts != self._pa_opts.get(f.key):  # unchanged: keep the open list as is
                        w.set_options(opts)
                        self._pa_opts[f.key] = opts
                    w.value = cur if cur not in (None, "") else opts[0][1]
            elif not w.has_focus:                # a value being typed is left alone
                w.value = "" if cur is None else str(cur)
            w.disabled = bool(self._pa_reason(f))
        self.query_one("#pa-path", Static).update(f"druid.yaml: {paths.config_file()}")
        note = (LOCKED_ALL if self._ro_all else PA_NOCFG if self._cfg is None
                else PA_FROZEN if self._pa_frozen else PA_HELP)
        self.query_one("#pa-reason", Static).update(note)
        gx_off = not self._ro_all and self._cfg is not None and not params.get("run_generax")
        self.query_one("#pa-gx-note", Static).update(PA_GX_OFF if gx_off else "")

    def on_select_changed(self, event: Select.Changed) -> None:
        """A list pick in Parameters. Only one the user made, while the list has the focus, is
        written: the Select's own mount-time value and anything set behind the UI are put back
        to the file's value."""
        wid = event.select.id or ""
        if not wid.startswith("pa-"):
            return
        f = PA_FIELDS[wid[len("pa-"):]]
        if event.value == self._params().get(f.key):
            return
        if not event.select.has_focus_within or event.value == "":
            self._fill_params()
            return
        self._set_param(f.key, str(event.value))

    def _set_param(self, key: str, text: str) -> None:
        """Write params.<key> from `text` (a picked value or what was typed), parsed by
        params_form (numbers as int / float); refused with the reason (nothing written, the field
        back to the file's value) when read-only or invalid."""
        f = PA_FIELDS[key]
        self._reload()                           # the file decides, not what was last shown
        why = self._pa_reason(f)
        if not why:
            try:
                value = params_form.parse(f, text, paths.project_root())
            except ValueError as e:
                why = f"ERROR: {e}"
        if why:
            w = self.query_one(f"#pa-{key}")
            if isinstance(w, Input):
                cur = self._params().get(key)
                w.value = "" if cur is None else str(cur)
            self._msg = why
            self._refresh()
            return
        self._write({("params", key): value}, done=f"params.{key} = {value}")

    # ---- navigation -------------------------------------------------------------------------
    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None or event.list_view.id != "sections":
            return
        name = event.item.id[len("item-"):]
        self.current = next(s for s in self.SECTIONS if s.lower() == name)
        self.query_one("#content", ContentSwitcher).current = f"sec-{name}"
        self.query_one("#content").border_title = self.current
        self.refresh_bindings()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """enter on a section: into its first control (none for a locked form)."""
        if event.list_view.id != "sections":
            return
        target = {"Project": "#job-prefix", "Source": "#src-name", "Species": "#sp-filter", "Analyses": "#sw-generax",
                  "Tree": "#tree-missing" if self._tree_on and self._missing else "#tree-base",
                  "Search": "#se-type", "Families": "#fam-filter"}.get(self.current)
        if self.current == "Parameters":         # the first editable field (frozen: the cpus)
            target = next((f"#pa-{f.key}" for f in params_form.FIELDS
                           if not self.query_one(f"#pa-{f.key}").disabled), None)
        if target:
            w = self.query_one(target)
            if not w.disabled and w.display:
                w.focus()

    def check_action(self, action: str, parameters: tuple) -> "bool | None":
        if action == "toggle":
            return self.current in ("Species", "Families")
        if action in ("tick_all", "untick_all"):
            return self.current in ("Species", "Families")
        if action == "edit_family":
            return self.current == "Families"
        if action == "tree_pick":
            return self.current in ("Species", "Tree")
        if action == "toggle_unplaced":
            return self.current == "Species"
        if action == "switch_move":              # else ↑↓ go on to the focused widget's parents
            return isinstance(self.focused, Switch)
        return True

    def action_focus_move(self, d: int) -> None:
        """tab / shift+tab: the next / previous focusable widget in screen order (the list, the
        shown section's controls, the warnings box when shown); disabled ones are skipped."""
        if d > 0:
            self.focus_next()
        else:
            self.focus_previous()

    def action_back(self) -> None:
        """esc: out of the family edit form to the table; from a section back to the list; on the
        list, back to Jobs."""
        sections = self.query_one("#sections", ListView)
        if self._fam_edit is not None:
            self._close_edit()
        elif sections.has_focus:
            self.dismiss("jobs")
        else:
            sections.focus()

    # ---- Source -----------------------------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        wid = event.input.id or ""
        if wid == "job-prefix":
            self._set_job_prefix(event.value.strip())
        elif wid == "sp-filter":
            self._tick_filtered()
        elif wid == "fam-filter":
            self.query_one("#fam-table").focus()
        elif wid == "tree-source":
            self._set_tree_source(event.value.strip())
        elif wid == "se-famfile":
            self._set_families_source(event.value.strip())
        elif wid == "se-hmmdir":
            self._set_hmm_dir(event.value.strip())
        elif wid.startswith("pa-"):
            self._set_param(wid[len("pa-"):], event.value)
        elif wid.startswith("fe-"):
            cols = list(EDIT_COLS)
            i = cols.index(wid[len("fe-"):])
            if i + 1 < len(cols):
                self.query_one(f"#fe-{cols[i + 1]}").focus()
            else:
                self._save_edit()
        elif wid.startswith("src-"):
            i = SRC_FIELDS.index(wid[len("src-"):])
            if i + 1 < len(SRC_FIELDS):
                self.query_one(f"#src-{SRC_FIELDS[i + 1]}").focus()
            else:
                self._add_source()

    def _source_error(self, v: dict, root: Path) -> str:
        names = {s.name for s in self._srcs} | {setup_state.DEFAULT}
        names |= {str(e.get("name")) for e in self._raw.get("sources") or [] if isinstance(e, dict)}
        if not v["name"]:
            return "a source needs a name"
        if v["name"] in names:
            return f"a source named {v['name']!r} already exists"
        if not v["dir"]:
            return "a source needs a proteome directory"
        if not _resolve(v["dir"], root).is_dir():
            return f"not a directory: {_resolve(v['dir'], root)}"
        glob = v["glob"] or setup_state.DEFAULT_GLOB
        try:
            ok = "{sp}" in glob and bool(glob.format(sp="x"))
        except Exception:                        # KeyError, AttributeError ({sp.fa}), ...: refused
            ok = False
        if not ok:
            return f"the glob {glob!r} needs {{sp}} (the species prefix) and no other {{...}}"
        if v["tax"] and not _resolve(v["tax"], root).is_file():
            return f"no such taxonomy table: {_resolve(v['tax'], root)}"
        return ""

    def _add_source(self) -> None:
        if self._ro_all:
            self._msg = LOCKED_ALL
            self._fill_blockers()
            return
        v = {k: self.query_one(f"#src-{k}", Input).value.strip() for k in SRC_FIELDS}
        err = self._source_error(v, paths.project_root())
        if err:
            self._msg = f"ERROR: {err}"
            self._fill_blockers()
            return
        entry = {"name": v["name"], "proteomes_dir": v["dir"],
                 "proteome_glob": v["glob"] or setup_state.DEFAULT_GLOB}
        if v["tax"]:
            entry["taxonomy"] = v["tax"]
        old = self._raw.get("sources")
        self._write({("sources",): (list(old) if isinstance(old, list) else []) + [entry]},
                    done=f"added source {v['name']}")
        if not self._msg.startswith("ERROR"):
            for k in SRC_FIELDS:
                self.query_one(f"#src-{k}", Input).value = ""
            self.query_one("#src-name").focus()

    # ---- Species ----------------------------------------------------------------------------
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "sp-filter":
            self._fill_species()
        elif event.input.id == "fam-filter":
            self._fill_families()

    def _species_editable(self) -> bool:
        """Re-read druid.yaml (a tick starts from the file, not from what was last shown); False,
        with the reason on the bottom line, when the species are read-only."""
        self._reload()
        if self._sp_reason:
            self._msg = self._sp_reason
            self._fill_blockers()
            return False
        return True

    def action_toggle(self) -> None:
        if self.current == "Families":
            self._toggle_family()
            return
        t = self.query_one("#sp-table", DataTable)
        if not t.has_focus or not self._shown or not self._species_editable():
            return
        c = self._shown[t.cursor_row]
        sel = list(self._sel)
        if (c.sp, c.source) in sel:
            sel.remove((c.sp, c.source))
        else:
            sel.append((c.sp, c.source))
        self._write({("species",): setup_state.species_value(sel)})

    def action_tick_all(self) -> None:
        if self.current == "Families":
            self._tick_shown_families()
            return
        if not self._shown or not self._species_editable():
            return
        sel = list(self._sel)
        sel += [(c.sp, c.source) for c in self._shown if (c.sp, c.source) not in sel]
        self._write({("species",): setup_state.species_value(sel)})

    def action_untick_all(self) -> None:
        """A: untick every row shown by the filter, one write (Grygoriy, 02/11/2026)."""
        if self.current == "Families":
            self._untick_shown_families()
            return
        if not self._shown or not self._species_editable():
            return
        shown = {(c.sp, c.source) for c in self._shown}
        sel = [s for s in self._sel if s not in shown]
        n = len(self._sel) - len(sel)
        if not n:
            self._msg = f"-0 unticked: none of the {len(shown)} shown is ticked"
            self._fill_blockers()
            return
        self._write({("species",): setup_state.species_value(sel)}, done=f"-{n} unticked")

    def action_toggle_unplaced(self) -> None:
        """u: show / hide the species not on the base tree nor placed (Grygoriy, 11/11/2026)."""
        self._show_unplaced = not self._show_unplaced
        self._msg = ("showing species not on the tree (dim)" if self._show_unplaced
                     else "hiding species not on the tree")
        self._fill_species()
        self._fill_blockers()

    def action_tree_pick(self) -> None:
        """t: the base tree, placements grafted, with a tick column; x ticks there (PickScreen)."""
        self._reload()
        if self._tree_file is None or self._placed is None:
            self._refuse(f"ERROR: {self._tree_err or 'species tree unreadable'}")
            return
        try:
            pl = sptree.read_placements(paths.project_root() / "data" / sptree.PLACEMENTS)
            newick = sptree.full_tree(self._tree_file.read_text().strip(), pl)
            tree = Tree(newick, format=1)
        except Exception as e:                   # unparsable newick, a bad placements file, ...
            self._refuse(f"ERROR: species tree unreadable ({self._tree_file}): {e}")
            return
        first = {}
        for c in self._cands:
            first.setdefault(c.sp, c)
        ticked = {sp for sp, _src in self._sel}
        meta = {n.name: (["[x]" if n.name in ticked else "[ ]", first[n.name].name]
                         if n.name in first else ["—", "no proteome"])
                for n in tree.iter_leaves()}
        m = tvm.TreeModel(tree, sep="_", meta=meta, meta_cols=["tick", "name"])
        ro = f" · {self._sp_reason}" if self._sp_reason else ""
        self.app.push_screen(PickScreen(
            m, self._pick_toggle, lambda: {sp for sp, _src in self._sel},
            title=f"species tree ({self._tree_file.name}): x ticks the tip / clade · esc: back{ro}",
            write_guard=paths.writable), callback=lambda _r: self._refresh())

    def _pick_toggle(self, names: list) -> str:
        """x in PickScreen: tick `names` (each species' first source), or untick them all when
        every one is ticked already; the message for its status line."""
        if not self._species_editable():
            return self._sp_reason
        sel = list(self._sel)
        have = {sp for sp, _src in sel}
        if all(n in have for n in names):
            drop = set(names)
            new = [s for s in sel if s[0] not in drop]
            done = f"-{len(sel) - len(new)} unticked"
        else:
            first = {}
            for c in self._cands:
                first.setdefault(c.sp, c)
            add = [(n, first[n].source) for n in names if n not in have and n in first]
            new = sel + add
            done = _ticked_note([sp for sp, _src in add])
        self._write({("species",): setup_state.species_value(new)}, done=done)
        return self._msg or done

    def _tick_filtered(self) -> None:
        """enter in the filter (Grygoriy, 23/10/2026): tick every species shown (adds only), one
        write, then clear the filter for the next query; focus stays in it, and the full list
        scrolls to the first species just ticked so its [x] is in view (25/10/2026)."""
        f = self.query_one("#sp-filter", Input)
        if not self._species_editable():
            return
        if not f.value.strip():                  # never every candidate by accident
            self._refuse("type a filter first (a: tick all shown)")
            return
        self._fill_species()                     # the filter over the candidates just re-read
        if not self._shown:
            self._refuse(f"no species match {f.value.strip()!r}")
            return
        sel = list(self._sel)
        new = [(c.sp, c.source) for c in self._shown if (c.sp, c.source) not in sel]
        unknown = " · not found: " + ", ".join(self._sp_unknown) if self._sp_unknown else ""
        if new:
            self._write({("species",): setup_state.species_value(sel + new)},
                        done=_ticked_note([sp for sp, _src in new]) + unknown)
        else:
            self._msg = f"+0 ticked: all {len(self._shown)} shown already ticked" + unknown
        if not self._msg.startswith("ERROR"):
            f.value = ""
            self._fill_species()
            first = new[0] if new else None      # the full list again: show the new ticks
            rows = [i for i, c in enumerate(self._shown) if (c.sp, c.source) == first]
            if rows:
                self.query_one("#sp-table", DataTable).move_cursor(row=rows[0])
        self._fill_blockers()

    # ---- Analyses ---------------------------------------------------------------------------
    def on_switch_changed(self, event: Switch.Changed) -> None:
        key = SWITCHES.get(event.switch.id or "")
        if key is None:
            return
        if self._ro_all:                         # a locked project: put the switch back
            with event.switch.prevent(Switch.Changed):
                event.switch.value = not event.value
            self._msg = LOCKED_ALL
            self._fill_blockers()
            return
        # species locked: prepare refuses, so a switch changed now leaves the trees as they are
        locked = self._cfg is not None and self._try(
            "species lock", lambda: setup_state.species_locked(self._raw, self._cfg), False)
        self._write({("params", key): bool(event.value)},
                    done=f"params.{key} = {bool(event.value)}: trees not rebuilt: species are locked"
                    if locked else "")

    # ---- Tree -------------------------------------------------------------------------------
    def _refuse(self, why: str) -> bool:
        """`why` on the bottom line; False, for `return self._refuse(...)` in a guard."""
        self._msg = why
        self._fill_blockers()
        return False

    def _tree_editable(self, place: bool = True) -> bool:
        """Re-read; False with the reason when the Tree section is read-only or, for a placement
        (place), not needed. The base tree can be chosen with both switches off (Ruling K)."""
        self._reload()
        if self._sp_reason:
            return self._refuse(self._sp_reason)
        if place and not self._tree_on:
            return self._refuse(TREE_OFF)
        return True

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "tree-missing":
            self._open_place(event.cursor_row)
        elif event.data_table.id in ("sp-table", "fam-table"):
            self.action_toggle()                 # enter ticks like space

    def action_edit_family(self) -> None:
        """e on a Families row: its settings form."""
        t = self.query_one("#fam-table", DataTable)
        if t.has_focus:
            self._open_edit(t.cursor_row)

    def _open_place(self, row: int) -> None:
        """enter on a missing species: PlaceScreen on the tree as built now (earlier placements
        shown); p there places it, esc cancels."""
        sp = self._missing[row] if 0 <= row < len(self._missing) else None
        if sp is None or not self._tree_editable():
            return
        if sp not in self._missing:              # placed or unticked meanwhile
            self._refresh()
            return
        if self._tree_err:
            self._refuse(f"ERROR: {self._tree_err}")
            return
        if not self._built:
            self._refuse(f"ERROR: no ticked species is on the tree yet: nothing to place {sp} "
                         "next to (tick one that is, or set tree_source)")
            return
        m = tvm.TreeModel(Tree(self._built, format=1), sep="_")
        self.app.push_screen(PlaceScreen(m, title=f"place {sp}: p on its sister node · esc: cancel",
                                         write_guard=paths.writable),
                             callback=lambda tips, sp=sp: self._placed(sp, tips))

    def _placed(self, sp: str, tips) -> None:
        if tips is None or not self._tree_editable():
            return
        pl = [x for x in self._placements if x.sp != sp] + [sptree.Placement(sp, frozenset(tips))]
        try:
            sptree.write_placements(paths.project_root() / "data" / sptree.PLACEMENTS, pl)
        except (OSError, paths.OutsideProject) as e:
            self._msg = f"ERROR: {e}"
        else:
            names = sorted(tips)
            self._msg = (f"placed {sp} as the sister of "
                         + (", ".join(names) if len(names) <= 4 else f"a clade of {len(names)} tips")
                         + f" (data/{sptree.PLACEMENTS})")
        self._reload()
        self._refresh()

    def _set_tree_source(self, value: str) -> None:
        if not self._tree_editable(place=False):
            return
        if value == str(self._raw.get("tree_source") or ""):
            self._tree_custom = False
            self._refresh()
            return
        if value and not _resolve(value, paths.project_root()).is_file():
            self._refuse(f"ERROR: no such tree file: {_resolve(value, paths.project_root())}")
            return
        self._tree_custom = False
        self._write({("tree_source",): value or None},
                    done=f"tree_source = {value}" if value else "tree_source cleared: the v3 curated tree")

    def _set_tree_base(self, kind: str) -> None:
        """A base chosen in the radio set: v3 unsets tree_source, chromo sets it to CHROMO_TREE
        (one tree for both), custom waits for a tree_source to be entered. Placements whose sister
        tips are not on the new base are skipped with a note (sptree.build_trees)."""
        if kind == self._tree_base():            # showing the current value: not a choice
            return
        if not self._tree_editable(place=False):
            self._fill_tree()                    # put the radio back
            return
        if kind == "custom":
            self._tree_custom = True
            self._msg = "custom tree: enter its newick path in tree_source"
            self._refresh()
            self.query_one("#tree-source").focus()
            return
        self._tree_custom = False
        if kind == "v3":
            if self._raw.get("tree_source"):
                self._write({("tree_source",): None}, done="species tree: v3 curated (59 tips)")
            else:                                # custom was chosen, nothing entered
                self._msg = ""
                self._refresh()
            return
        chromo = paths.project_root() / setup_state.CHROMO_TREE
        if not chromo.is_file():                 # a project made before 23/10/2026
            self._refuse(f"ERROR: no such tree file: {chromo} (copy it from "
                         f"{paths.DRUID_HOME / 'druid' / 'data' / 'species_tree.chromo94.newick'})")
            self._fill_tree()
            return
        self._write({("tree_source",): setup_state.CHROMO_TREE},
                    done=f"species tree: chromo (94 tips, {setup_state.CHROMO_TREE})")

    # ---- Search -----------------------------------------------------------------------------
    def _fam_editable(self) -> bool:
        """Re-read; False with the reason when Search / Families are read-only."""
        self._reload()
        reason = self._fam_reason()
        return self._refuse(reason) if reason else True

    def _hmm_rows(self, d):
        """families.hmm_rows(d), or None with the error on the bottom line (an unreadable .hmm
        must not crash the app)."""
        try:
            return families.hmm_rows(d, _default_inflation(self._raw))
        except Exception as e:                   # PermissionError, a directory named x.hmm, ...
            self._refuse(f"ERROR: cannot read the HMMs in {d}: {type(e).__name__}: {e}")
            return None

    def _hmm_keys(self, d):
        """The _key of each hmm_dir row: by its cus.<name> id, so a CSD.hmm never matches the
        library's rbp.CSD / tfs.CSD (a custom row whose prefix was edited is no longer matched).
        None (error shown) when the directory cannot be read."""
        if d is None or not d.is_dir():
            return set()
        rows = self._hmm_rows(d)
        return None if rows is None else {_key(r) for r in rows}

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "tree-base":
            kind = TREE_BASES.get(event.pressed.id or "")
            if kind is not None:
                self._set_tree_base(kind)
            return
        kind = SEARCH.get(event.pressed.id or "")
        if kind is None or kind == self._search:  # showing the current value: not a choice
            return
        if not self._fam_editable():
            self._fill_search()                  # put the radio back
            return
        old_dir = self._hmm_dir
        keys = self._hmm_keys(old_dir) if kind == "file" else set()
        if keys is None:                         # its families cannot be told apart: refused
            self._fill_search()                  # put the radio back
            return
        self._search = kind
        if kind == "hmm":
            self._msg = "custom HMMs: enter the directory of the <name>.hmm files"
            self._reload()
            self._refresh()
            self.query_one("#se-hmmdir").focus()
        elif old_dir is None:
            self._msg = ""
            self._reload()
            self._refresh()
        else:                                    # back to the family file: drop the HMM families
            self._write({("params", "hmm_dir"): None},
                        done="search: gene family file (params.hmm_dir cleared, its families dropped)",
                        fam_rows=[r for r, t in self._fam if t and _key(r) not in keys])

    def _set_hmm_dir(self, value: str) -> None:
        if not self._fam_editable():
            return
        if not value:
            self._refuse("ERROR: enter the directory of the <name>.hmm files")
            return
        d = _resolve(value, paths.project_root())
        if not d.is_dir():
            self._refuse(f"ERROR: not a directory: {d}")
            return
        new = self._hmm_rows(d)
        if new is None:
            return
        if not new:
            self._refuse(f"ERROR: no *.hmm files in {d}")
            return
        same = self._hmm_dir is not None and self._hmm_dir.resolve() == d.resolve()
        old = set() if same else self._hmm_keys(self._hmm_dir)   # same dir: edits kept
        if old is None:
            return
        rows = [r for r, t in self._fam if t and _key(r) not in old]
        have = {_key(r) for r in rows}
        added = [r for r in new if _key(r) not in have]
        self._write({("params", "hmm_dir"): value},
                    done=f"params.hmm_dir = {value}: {len(added)} custom families added (ticked; "
                         "e on one in Families edits its settings)",
                    fam_rows=rows + added)

    def _set_families_source(self, value: str) -> None:
        """Your own families file (empty: the library) as the table's rows, none of them ticked
        (the hmm_dir rows stay ticked: the user added them)."""
        if not self._fam_editable():
            return
        if value == str(self._raw.get("families_source") or ""):
            self._refresh()
            return
        if value:
            p = _resolve(value, paths.project_root())
            if not p.is_file():
                self._refuse(f"ERROR: no such families file: {p}")
                return
            if self._fam_target is not None and p.resolve() == self._fam_target.resolve():
                self._refuse("ERROR: that is the project's families file (params.genefam_info); "
                             "give the file it was copied from")
                return
            try:
                rows = families.read(p)
            except OSError as e:
                self._refuse(f"ERROR: {e}")
                return
            if not rows:
                self._refuse(f"ERROR: no rows in {p}")
                return
        else:
            rows = families.library()
        if self._hmm_dir is not None and self._hmm_dir.is_dir():
            hmm = self._hmm_rows(self._hmm_dir)
            if hmm is None:
                return
        else:
            hmm = []
        self._write({("families_source",): value or None},
                    done=f"families from {value or 'the shipped library'}: {len(rows) + len(hmm)} "
                         f"rows, {len(hmm)} ticked · space / a ticks",
                    fam_rows=hmm)

    # ---- Families ---------------------------------------------------------------------------
    def _tick_shown_families(self) -> None:
        """a: tick every family shown by the filter (adds only), one write, in table order."""
        if not self._fam_shown or not self._fam_editable():
            return
        shown = set(self._fam_shown)
        new = sum(1 for i in shown if i < len(self._fam) and not self._fam[i][1])
        if not new:
            self._msg = f"+0 ticked: all {len(shown)} shown already ticked"
            self._fill_blockers()
            return
        self._write({}, done=f"+{new} families ticked",
                    fam_rows=[r for i, (r, x) in enumerate(self._fam) if x or i in shown])

    def _untick_shown_families(self) -> None:
        """A: untick every family shown by the filter, one write."""
        if not self._fam_shown or not self._fam_editable():
            return
        shown = set(self._fam_shown)
        n = sum(1 for i in shown if i < len(self._fam) and self._fam[i][1])
        if not n:
            self._msg = f"-0 unticked: none of the {len(shown)} shown is ticked"
            self._fill_blockers()
            return
        self._write({}, done=f"-{n} families unticked",
                    fam_rows=[r for i, (r, x) in enumerate(self._fam) if x and i not in shown])

    def _toggle_family(self) -> None:
        t = self.query_one("#fam-table", DataTable)
        if not t.has_focus or not self._fam_shown:
            return
        i = self._fam_shown[t.cursor_row]
        if not self._fam_editable() or i >= len(self._fam):
            return
        r, ticked = self._fam[i]
        self._fam[i] = [r, not ticked]
        self._write({}, fam_rows=[r for r, x in self._fam if x])

    def _open_edit(self, row: int) -> None:
        if not 0 <= row < len(self._fam_shown) or not self._fam_editable():
            return
        self._fam_edit = self._fam_shown[row]
        r = self._fam[self._fam_edit][0]
        for col in EDIT_COLS:
            self.query_one(f"#fe-{col}", Input).value = getattr(r, col)
        self.query_one("#fam-edit").display = True
        self.query_one("#fam-edit-help").display = True
        self.query_one("#fe-inflation").focus()
        self._msg = f"editing {_fam_id(r)}"
        self._fill_blockers()

    def _close_edit(self) -> None:
        self._fam_edit = None
        self.query_one("#fam-edit").display = False
        self.query_one("#fam-edit-help").display = False
        self.query_one("#fam-table").focus()

    def _save_edit(self) -> None:
        i = self._fam_edit
        if i is None:
            return
        vals = {c: self.query_one(f"#fe-{c}", Input).value.strip() for c in EDIT_COLS}
        err = _edit_error(vals)
        if err:
            self._refuse(f"ERROR: {err}")
            return
        if not self._fam_editable() or i >= len(self._fam):
            self._close_edit()
            return
        row = dataclasses.replace(self._fam[i][0], **vals)
        self._fam[i] = [row, True]
        self._close_edit()
        self._write({}, done=f"{_fam_id(row)}: saved", fam_rows=[r for r, t in self._fam if t])

    # ---- prepare ----------------------------------------------------------------------------
    def action_prepare(self) -> None:
        """P: prepare.run in a worker (it refuses a locked project or any blocker itself); the
        files written, the tree notes or the ERROR on the bottom line."""
        self._reload()
        if self._cfg is None:
            self._msg = "ERROR: prepare: druid.yaml does not load (see the errors below)"
        elif self._raw.get("prepare") != "locked" and \
                self._try("species lock", lambda: setup_state.species_locked(self._raw, self._cfg), False):
            # after the first run there is nothing to rebuild: ticked families are already saved
            self._msg = "prepare: species locked, inputs kept; families are already saved. " + RUN_HINT
        else:
            self._msg = "prepare: running…"
            self._run_prepare(self._raw, self._cfg, paths.project_root())
        self._refresh()

    @work(thread=True, exclusive=True, group="prepare")
    def _run_prepare(self, raw: dict, cfg, root: Path) -> None:
        notes: list = []
        steps: list = []

        def progress(m: str) -> None:            # each step on the bottom line as it starts
            steps.append(m)
            self.app.call_from_thread(self._prepare_step, list(steps))
        try:
            written = prepare.run(raw, cfg, root, notes, progress=progress)
        except prepare.PrepareError as e:
            msg = f"ERROR: {e}"
        except Exception as e:                   # anything: reported, the screen stays up
            msg = f"ERROR: prepare: {type(e).__name__}: {e}"
        else:
            def rel(p):
                try:
                    return str(Path(p).relative_to(root))
                except ValueError:
                    return str(p)
            msg = "\n".join(["prepare wrote " + ", ".join(rel(p) for p in written)] + notes
                            + [RUN_HINT])
        self.app.call_from_thread(self._prepared, msg)

    def _prepare_step(self, steps: list, most: int = 6) -> None:
        """prepare running: the steps so far (the last `most`), the current one last."""
        done = [f"  ✓ {m}" for m in steps[-most:-1]]
        self._msg = "\n".join([f"prepare: step {len(steps)}"] + done + [f"  … {steps[-1]}"])
        self._fill_blockers()

    def _prepared(self, msg: str) -> None:
        self._msg = msg
        self._reload()
        self._refresh()

    # ---- run step 1 -------------------------------------------------------------------------
    def action_run_step1(self) -> None:
        """S: the Jobs tab's run box (step1run refuses a missing job_prefix, an adopted project, no
        prepare yet); druid.yaml is read again first, and again when the box closes (a submit
        locks the species)."""
        if any(w.group == "prepare" and w.is_running for w in self.app.workers):
            self._msg = "run: prepare is still running; wait for it to finish"
            self._fill_blockers()
            return
        self._reload()
        if self._cfg is None:
            self._msg = "ERROR: run: druid.yaml does not load (see the errors below)"
            self._refresh()
            return
        self.app.push_screen(RunScreen(self._cfg, self._raw),
                             lambda _jids: (self._reload(), self._refresh()))
