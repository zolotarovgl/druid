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
           "question_mark": "?", "left_square_bracket": "[", "right_square_bracket": "]"}


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
