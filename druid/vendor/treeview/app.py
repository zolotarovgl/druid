"""The standalone viewer: TreeApp's base screen is a TreeScreen (so esc never pops to nothing)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import App
from textual.binding import Binding

from treeview.model import TreeModel
from treeview.widget import TreeScreen


class TreeApp(App):
    TITLE = "treeview"
    BINDINGS = [Binding("q", "quit", "quit")]

    def __init__(self, model: TreeModel, view: str = "clado", title: str = "",
                 path: Optional[Path] = None):
        super().__init__()
        self.model, self.view, self.tree_title, self.path = model, view, title, path

    def get_default_screen(self) -> TreeScreen:
        return TreeScreen(self.model, view=self.view, title=self.tree_title, path=self.path)
