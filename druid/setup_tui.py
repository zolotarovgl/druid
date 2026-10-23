"""The TUI Setup tab (sub-project 2, 23/10/2026): proteome sources, the species picker, the analyses
switches and druid.yaml, with the blockers `prepare` would report on the bottom line. Every write goes
through yamledit.update_config; an adopted project (prepare: locked) is read-only throughout, a
species-locked one only in the Species section. Imported by druid.tui when the Setup tab opens."""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (ContentSwitcher, DataTable, Footer, Header, Input, Label, ListItem,
                             ListView, Static, Switch)

from druid import core, paths, setup_state, yamledit

SWITCHES = {"sw-generax": "run_generax", "sw-origins": "origins"}   # switch id -> params key
SRC_FIELDS = ("name", "dir", "glob", "tax")                          # #src-<field> inputs, in order
PLACEHOLDERS = {
    "Tree": "Not available yet: placing ticked species that are missing from the species tree.",
    "Search": "Not available yet: the family file, custom HMMs or query sequences to search with.",
    "Families": "Not available yet: ticking the families to run from the shipped library."}
LOCKED_ALL = "read-only: adopted project (prepare: locked); druid never changes its druid.yaml here"


def _run_editor(path: Path) -> int:
    """$EDITOR (fallback nano) on `path`, in the foreground; its exit code. Tests replace it."""
    return subprocess.call(shlex.split(os.environ.get("EDITOR") or "nano") + [str(path)])


def _resolve(p: str, root: Path) -> Path:
    q = Path(p).expanduser()
    return q if q.is_absolute() else root / q


class SetupScreen(Screen):
    """Left: the sections, each with a mark (✓ fine, ! needs attention, a number = how many);
    right: the highlighted section; bottom: the last error and the blockers."""
    SECTIONS = ("Source", "Species", "Analyses", "Tree", "Search", "Families", "Config")
    DEFAULT_CSS = """
    SetupScreen #setup-tabbar { height: 1; }
    SetupScreen #setup-body { height: 1fr; }
    SetupScreen #sections { width: 18; border: round $primary; }
    SetupScreen #sections:focus { border: round orange; }
    SetupScreen #content { width: 1fr; border: round $primary; }
    SetupScreen #content > * { height: 1fr; }
    SetupScreen #sp-table { height: 1fr; }
    SetupScreen #sp-table:focus { border: round orange; }
    SetupScreen .row { height: auto; }
    SetupScreen .row Label { padding: 1 1; }
    SetupScreen .note { color: $text-muted; }
    SetupScreen #blockers { height: auto; max-height: 8; color: $warning; }
    """
    BINDINGS = [
        Binding("tab", "leave('jobs')", "Jobs", priority=True),
        Binding("shift+tab", "leave('results')", "Results", show=False, priority=True),
        Binding("escape", "back", "back"),
        Binding("space", "toggle", "tick"),
        Binding("a", "tick_all", "tick shown"),
        Binding("e", "edit_config", "edit druid.yaml"),
    ]

    def __init__(self):
        super().__init__()
        self.current = self.SECTIONS[0]
        self._msg = ""                           # the last action's error / note, top of #blockers
        self._raw: dict = {}
        self._cfg = None                         # core.Config, None when druid.yaml does not load
        self._errors: list = []                  # ERROR: ... lines (config, sources, blockers)
        self._srcs: list = []
        self._cands: list = []
        self._rowless: list = []
        self._sel: list = []                     # [(sp, source)], the species: order
        self._shown: list = []                   # candidates passing the filter, as in #sp-table
        self._blockers: list = []
        self._ro_all = False                     # prepare: locked
        self._sp_reason = ""                     # why Species is read-only ("" = editable)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="setup-tabbar")
        with Horizontal(id="setup-body"):
            yield ListView(*[ListItem(Label(s, id=f"lbl-{s.lower()}"), id=f"item-{s.lower()}")
                             for s in self.SECTIONS], id="sections")
            with ContentSwitcher(id="content", initial="sec-source"):
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
                    yield Input(placeholder="filter (any column · enter: the list)", id="sp-filter")
                    yield DataTable(id="sp-table", cursor_type="row")
                    yield Static("", id="sp-count", markup=False)
                with Vertical(id="sec-analyses"):
                    yield Static("", id="an-reason", classes="note", markup=False)
                    with Horizontal(classes="row"):
                        yield Switch(id="sw-generax")
                        yield Label("GeneRax gene-tree reconciliation (params.run_generax)")
                    with Horizontal(classes="row"):
                        yield Switch(id="sw-origins")
                        yield Label("orthogroup origins on ORIGIN_TREE (params.origins)")
                    yield Static("Both off: no species tree is needed.", classes="note")
                for name, text in PLACEHOLDERS.items():
                    yield Static(text, id=f"sec-{name.lower()}", classes="note")
                with VerticalScroll(id="sec-config"):
                    yield Static("", id="cfg-help", classes="note", markup=False)
                    yield Static("", id="cfg-text", markup=False)
        yield Static("", id="blockers", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#sp-table", DataTable).add_columns("", "prefix", "name", "taxonomy", "source")
        self.query_one("#content").border_title = self.current
        txt = Text()
        txt.append("Jobs │ Results │ ")
        txt.append("[Setup]", style="reverse bold")
        txt.append("   tab: back to Jobs · enter: open a section · esc: back", style="dim")
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

    def _write(self, changes: dict, done: str = "") -> None:
        """update_config(changes); its error (nothing written) on the bottom line; then re-read."""
        try:
            yamledit.update_config(changes)
        except (core.ConfigError, OSError) as e:
            self._msg = f"ERROR: {e}"
        else:
            self._msg = done
        self._reload()
        self._refresh()

    # ---- drawing ----------------------------------------------------------------------------
    def _marks(self) -> dict:
        nsrc_bad = any(e.startswith(("ERROR: sources", "ERROR: proteome")) for e in self._errors)
        return {"Source": "!" if nsrc_bad or self._rowless else str(len(self._srcs)),
                "Species": str(len(self._sel)) if self._sel else "!",
                "Analyses": "✓", "Tree": "·", "Search": "·", "Families": "·",
                "Config": "!" if self._cfg is None else "✓"}

    def _refresh(self) -> None:
        for name, mark in self._marks().items():
            self.query_one(f"#lbl-{name.lower()}", Label).update(f"{name:<9} {mark}")
        self._fill_source()
        self._fill_species()
        self._fill_analyses()
        self._fill_config()
        self._fill_blockers()

    def _fill_blockers(self) -> None:
        lines = ([self._msg] if self._msg else []) + self._errors
        if self._blockers:
            lines.append("blockers: " + " · ".join(self._blockers))
        elif self._cfg is not None:
            lines.append("no blockers: ready for prepare")
        self.query_one("#blockers", Static).update("\n".join(lines))

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
        q = self.query_one("#sp-filter", Input).value.strip().lower()
        self._shown = [c for c in self._cands if not q or
                       any(q in str(v).lower() for v in (c.sp, c.name, c.taxonomy, c.source))]
        t = self.query_one("#sp-table", DataTable)
        row = t.cursor_row
        t.clear()
        ticked = set(self._sel)
        for c in self._shown:
            t.add_row("[x]" if (c.sp, c.source) in ticked else "[ ]", c.sp, c.name, c.taxonomy,
                      c.source)
        if self._shown:
            t.move_cursor(row=min(max(row, 0), len(self._shown) - 1))
        count = f"{len(self._sel)} ticked / {len(self._cands)}"
        if q:
            count += f" · {len(self._shown)} shown"
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

    def _fill_config(self) -> None:
        f = paths.config_file()
        try:
            text = f.read_text()
        except OSError as e:
            text = f"cannot read {f}: {e}"
        help_ = LOCKED_ALL if self._ro_all else \
            "e: edit in $EDITOR (fallback nano); druid.yaml is checked again on return"
        self.query_one("#cfg-help", Static).update(f"{f}\n{help_}\n")
        self.query_one("#cfg-text", Static).update(text)

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
        """enter on a section: into its first control (none for a placeholder or a locked form)."""
        target = {"Source": "#src-name", "Species": "#sp-filter", "Analyses": "#sw-generax",
                  "Config": "#sec-config"}.get(self.current)
        if target:
            w = self.query_one(target)
            if not w.disabled:
                w.focus()

    def check_action(self, action: str, parameters: tuple) -> "bool | None":
        if action in ("toggle", "tick_all"):
            return self.current == "Species"
        if action == "edit_config":
            return self.current == "Config"
        return True

    def action_leave(self, to: str) -> None:
        self.dismiss(to)

    def action_back(self) -> None:
        """esc: from a section back to the list; on the list, back to Jobs."""
        sections = self.query_one("#sections", ListView)
        if sections.has_focus:
            self.dismiss("jobs")
        else:
            sections.focus()

    # ---- Source -----------------------------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        wid = event.input.id or ""
        if wid == "sp-filter":
            self.query_one("#sp-table").focus()
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
        if not self._shown or not self._species_editable():
            return
        sel = list(self._sel)
        sel += [(c.sp, c.source) for c in self._shown if (c.sp, c.source) not in sel]
        self._write({("species",): setup_state.species_value(sel)})

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
        self._write({("params", key): bool(event.value)})

    # ---- Config -----------------------------------------------------------------------------
    def action_edit_config(self) -> None:
        if self._ro_all:
            self._msg = LOCKED_ALL
            self._fill_blockers()
            return
        f = paths.config_file()
        try:
            with self.app.suspend():
                rc = _run_editor(f)
        except SuspendNotSupported:
            self._msg = "ERROR: this terminal cannot suspend the TUI; edit druid.yaml outside it"
        except OSError as e:
            self._msg = f"ERROR: cannot start the editor: {e}"
        else:
            self._msg = f"the editor exited with {rc}" if rc else ""
        self._reload()
        self._refresh()
