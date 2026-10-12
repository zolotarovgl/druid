"""python -m treeview TREE [--colours FILE] [--sep _] [--view clado|outline] [--meta FILE]"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

TERM_RESET = "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1049l\x1b[?25h\x1b[3J"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="treeview", description="Interactive newick viewer.")
    ap.add_argument("tree", help="newick file")
    ap.add_argument("--colours", help="code<TAB>colour, or species_info.tsv (colour by group)")
    ap.add_argument("--sep", default="_", help="species code = tip name up to the first SEP")
    ap.add_argument("--view", choices=("clado", "outline"), default="clado")
    ap.add_argument("--meta", help="tip metadata: TSV (CSV if *.csv) with a header row, "
                                   "first column = tip name")
    a = ap.parse_args(argv)
    from treeview import model
    try:
        tree = model.load(Path(a.tree))
    except Exception as e:
        print(f"treeview: cannot read {a.tree}: {e}", file=sys.stderr)
        return 1
    colours = {}
    if a.colours:
        try:
            colours = model.load_colours(a.colours)
        except OSError as e:
            print(f"treeview: {a.colours}: {e} (default colours)", file=sys.stderr)
    meta, cols = None, None
    if a.meta:
        try:
            cols, meta = model.load_meta(a.meta)
        except (OSError, ValueError, csv.Error) as e:
            print(f"treeview: {a.meta}: {e} (no metadata)", file=sys.stderr)
    from treeview.app import TreeApp
    app = TreeApp(model.TreeModel(tree, sep=a.sep, colours=colours, meta=meta, meta_cols=cols),
                  view=a.view, title=Path(a.tree).name, path=Path(a.tree))
    try:
        app.run(mouse=False)
    finally:
        sys.stdout.write(TERM_RESET)
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
