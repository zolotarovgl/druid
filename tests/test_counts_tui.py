"""druid/counts_tui.py: the Counts heatmap screen (Textual pilot tests)."""
from __future__ import annotations

import asyncio
import types

import pytest

pytest.importorskip("textual")

from textual.app import App  # noqa: E402
from textual.widgets import DataTable  # noqa: E402

from druid import counts_tui, model  # noqa: E402
from druid.counts import Col  # noqa: E402
from tests.test_model import POSSVM_HG1, POSSVM_HG11, PREV_HG1, SP4, og_csv  # noqa: E402
from treeview import model as tvm  # noqa: E402
from treeview.keys import KeysScreen, missing_keys  # noqa: E402

FAMS = [Col("tfs.A", "tfs.A", {"Mlei": 3, "Hsap": 2}), Col("tfs.B", "tfs.B", {"Nvec": 1}),
        Col("slc.X", "slc.X", {"Bova": 2})]
HGS = [Col("tfs.A.HG1", "tfs.A.HG1", {"Mlei": 2, "Hsap": 1, "Nvec": 1}),
       Col("tfs.A.HG11", "tfs.A.HG11", {"Bova": 1, "Mlei": 1})]


def _cfg(tmp_path):
    for d in ("possvm", "possvm_prev"):
        (tmp_path / d).mkdir(exist_ok=True)
    (tmp_path / "possvm/tfs.A.HG1.generax.support.tree.ortholog_groups.csv").write_text(og_csv(POSSVM_HG1))
    (tmp_path / "possvm_prev/tfs.A.HG1.treefile.ortholog_groups.csv").write_text(og_csv(PREV_HG1))
    (tmp_path / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv").write_text(
        og_csv(POSSVM_HG11))                     # no possvm_prev csv for HG11
    return types.SimpleNamespace(outdir=tmp_path)


class _Host(App):
    def __init__(self, scr):
        super().__init__()
        self.scr = scr

    def on_mount(self) -> None:
        self.push_screen(self.scr)


def _screen(tmp_path, level="class", scope=None, fams=FAMS, hgs=HGS, calls=None, **kw):
    cfg = _cfg(tmp_path)
    calls = [] if calls is None else calls

    def og_source(hg, source):
        calls.append(("og_source", hg, source))
        return model.HGOgs(hg, model.read_ogs(cfg, hg, source) or [])
    kw.setdefault("og_source", og_source)
    m = tvm.TreeModel(tvm.load(SP4), sep="_")
    return counts_tui.CountsScreen(cfg, m, fams, hgs, level, scope, **kw)


def _run(scr, body):
    async def go():
        app = _Host(scr)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await body(app, pilot)
    asyncio.run(go())


def _table(scr):
    return scr.query_one("#counts", DataTable)


def _to_row(scr, label):
    t = _table(scr)
    t.move_cursor(row=[t.get_row_at(i)[1] for i in range(t.row_count)].index(label))


def test_counts_drill_and_back(tmp_path):
    calls = []
    scr = _screen(tmp_path, calls=calls)

    async def body(app, pilot):
        assert scr.level == "class" and [c.id for c in scr.cols] == ["tfs", "slc"]
        await pilot.press("enter")
        await pilot.pause()
        assert (scr.level, scr.scope) == ("family", "tfs")
        assert [c.id for c in scr.cols] == ["tfs.A", "tfs.B"]
        await pilot.press("enter")
        await pilot.pause()
        assert (scr.level, scr.scope) == ("hg", "tfs.A")
        assert [c.id for c in scr.cols] == ["tfs.A.HG1", "tfs.A.HG11"]
        await pilot.press("enter")
        await pilot.pause()
        assert (scr.level, scr.scope) == ("og", "tfs.A.HG1")
        assert ("og_source", "tfs.A.HG1", "possvm") in calls
        assert [c.label for c in scr.cols] == ["HG1.0:T/Tbx19", "HG1.1:like:Eomes/Tbr1"]
        assert _table(scr).border_title == "Counts · tfs › tfs.A › HG1"
        await pilot.press("enter")
        assert scr.status == "bottom level · t opens the tree"
        for want in ("hg", "family", "class"):
            await pilot.press("escape")
            await pilot.pause()
            assert scr.level == want
        assert app.screen is scr
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is not scr
    _run(scr, body)


def test_counts_opened_at_family_closes_at_family(tmp_path):
    scr = _screen(tmp_path, level="family", scope="tfs")

    async def body(app, pilot):
        assert [c.id for c in scr.cols] == ["tfs.A", "tfs.B"]
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is not scr
    _run(scr, body)


def test_counts_c_s_z_e(tmp_path):
    scr = _screen(tmp_path, level="family", scope="tfs")

    async def body(app, pilot):
        assert scr.mode == "z"
        await pilot.press("c")
        assert scr.mode == "abs" and scr.status == "colour: absolute"
        await pilot.press("c")
        assert scr.mode == "z" and scr.status == "colour: z-score"
        _to_row(scr, "Nvec")
        await pilot.press("s")
        assert scr.sort_row == scr._ax.labels.index("Nvec")
        assert [c.id for c in scr.cols] == ["tfs.B", "tfs.A"]
        await pilot.press("s")
        assert scr.sort_row is None and [c.id for c in scr.cols] == ["tfs.A", "tfs.B"]
        n = _table(scr).row_count
        _to_row(scr, "Mlei")
        await pilot.press("z")
        assert _table(scr).row_count == n - 1
        await pilot.press("e")
        assert _table(scr).row_count == n
        await pilot.press("z")
        _to_row(scr, "Nvec")
        await pilot.press("s")
        assert scr.sort_row is not None
        assert [c.id for c in scr.cols] == ["tfs.B", "tfs.A"]
        _table(scr).move_cursor(column=counts_tui.FIXED + 1)
        await pilot.press("enter")
        await pilot.pause()
        assert (scr.level, scr.scope) == ("hg", "tfs.A") and scr.sort_row is None
        assert _table(scr).row_count == n - 1                      # collapse kept
    _run(scr, body)


def test_counts_no_data_level(tmp_path):
    scr = _screen(tmp_path, level="family", scope="tfs")

    async def body(app, pilot):
        await pilot.press("right", "enter")                        # tfs.B: no HG cols
        await pilot.pause()
        assert (scr.level, scr.scope) == ("hg", "tfs.B")
        t = _table(scr)
        assert t.row_count == 1 and str(t.get_row_at(0)[0]) == "no data"
        await pilot.press("escape")
        await pilot.pause()
        assert scr.level == "family" and app.screen is scr
    _run(scr, body)


def test_counts_og_error(tmp_path):
    scr = _screen(tmp_path, level="og", scope="tfs.A.HG1",
                  og_source=lambda hg, s: model.HGOgs(hg, [], error="bad csv"))

    async def body(app, pilot):
        t = _table(scr)
        assert t.row_count == 1 and str(t.get_row_at(0)[0]) == "no data"
        assert "bad csv" in scr.status
    _run(scr, body)


def test_counts_t_calls_open_tree(tmp_path):
    got = []
    scr = _screen(tmp_path, level="hg", scope="tfs.A", open_tree=lambda *a: got.append(a))

    async def body(app, pilot):
        _to_row(scr, "Mlei")
        await pilot.press("t")
        assert got == [("tfs.A.HG1", "possvm", None, {"Mlei"})]
        await pilot.press("enter")
        await pilot.pause()
        _to_row(scr, "Mlei")
        await pilot.press("t")
        assert got[-1][0] == "tfs.A.HG1" and got[-1][2].id == "tfs.A.HG1.0"
    _run(scr, body)
    scr2 = _screen(tmp_path, open_tree=lambda *a: got.append(a))

    async def body2(app, pilot):
        await pilot.press("t")
        assert scr2.status == "t: HG or OG level only"
    _run(scr2, body2)
    scr3 = _screen(tmp_path, level="hg", scope="tfs.A")

    async def body3(app, pilot):
        for k in ("t", "slash", "R"):
            await pilot.press(k)
            assert scr3.status == "not available here"
    _run(scr3, body3)


def test_counts_p_and_custom(tmp_path):
    calls = []
    cfg = _cfg(tmp_path)
    ogs = model.read_ogs(cfg, "tfs.A.HG1", "possvm")
    scr = _screen(tmp_path, level="og", scope="tfs.A.HG1", calls=calls,
                  og_search=lambda q: [("tfs.A.HG1", o, "possvm") for o in ogs])

    async def body(app, pilot):
        await pilot.press("p")
        assert scr.source == "possvm_prev"
        assert calls[-1] == ("og_source", "tfs.A.HG1", "possvm_prev")
        assert [c.label for c in scr.cols] == ["HG1.0:like:Tbx2/Tbx3"]
        await pilot.press("p")
        assert scr.source == "possvm"
        await pilot.press("slash", *"T/Tbx", "enter")
        await pilot.pause()
        assert scr.level == "custom" and len(scr.cols) == 2 and len(scr.custom) == 2
        await pilot.press("x")
        assert len(scr.cols) == 1 and len(scr.custom) == 1
        await pilot.press("escape")
        await pilot.pause()
        assert scr.level == "og"
    _run(scr, body)
    scr2 = _screen(tmp_path)

    async def body2(app, pilot):
        await pilot.press("p")
        assert scr2.status == "p: OG level only"
    _run(scr2, body2)


def test_counts_keys_table_complete(tmp_path):
    assert missing_keys(counts_tui.CountsScreen.BINDINGS, counts_tui.COUNTS_KEYS) == []
    scr = _screen(tmp_path)

    async def body(app, pilot):
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, KeysScreen)
    _run(scr, body)


def test_counts_off_tree_row_and_sigma(tmp_path):
    fams = [Col("tfs.A", "tfs.A", {"Mlei": 3, "Zzz": 2}), Col("tfs.B", "tfs.B", {"Hsap": 1})]
    scr = _screen(tmp_path, level="family", scope="tfs", fams=fams)

    async def body(app, pilot):
        t = _table(scr)
        labels = [t.get_row_at(i)[1] for i in range(t.row_count)]
        assert labels[-2:] == ["(not on tree)", "Σ"]
        sigma = t.get_row_at(t.row_count - 1)
        assert [str(x) for x in sigma[2:4]] == [str(c.total) for c in scr.cols] == ["5", "1"]
        _to_row(scr, "(not on tree)")
        await pilot.pause()
        assert "Zzz 2" in scr.status
    _run(scr, body)


def test_counts_R_rereads(tmp_path):
    new = [Col("tfs.C", "tfs.C", {"Hsap": 9})]
    scr = _screen(tmp_path, level="family", scope="tfs", reload=lambda: (new, [], 2), unreadable=1)

    async def body(app, pilot):
        assert scr.status == "1 files unreadable"
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert [c.id for c in scr.cols] == ["tfs.C"]
        assert scr.status == "counts re-read · 2 files unreadable"
    _run(scr, body)


def test_counts_p_at_custom_keeps_and_restores(tmp_path):
    cfg = _cfg(tmp_path)
    hits = ([("tfs.A.HG1", o, "possvm") for o in model.read_ogs(cfg, "tfs.A.HG1", "possvm")]
            + [("tfs.A.HG11", o, "possvm") for o in model.read_ogs(cfg, "tfs.A.HG11", "possvm")])
    scr = _screen(tmp_path, og_search=lambda q: hits)

    async def body(app, pilot):
        await pilot.press("slash", *"Tbx", "enter")
        await pilot.pause()
        orig = list(scr.custom)
        assert scr.level == "custom" and len(orig) == 3
        await pilot.press("p")
        assert scr.source == "possvm_prev"
        # HG1.0 -> prev HG1.0 (shares Mlei_v05_G1); HG1.1 shares no gene; HG11 has no prev csv
        assert [og.id for _, og, _ in scr.custom] == ["tfs.A.HG1.0"]
        assert scr.custom[0][1].name == "like:Tbx2/Tbx3" and scr.custom[0][2] == "possvm_prev"
        assert scr.status == "possvm_prev: 2 of 3 OGs have no counterpart"
        await pilot.press("p")
        assert scr.source == "possvm" and scr.custom == orig
        assert scr.status == "source: possvm" and len(scr.cols) == 3
    _run(scr, body)


def test_counts_breadcrumb_from_visited_levels(tmp_path):
    fams = [Col("tfs.A.b", "tfs.A.b", {"Mlei": 1})]
    hgs = [Col("tfs.A.b.HG1", "tfs.A.b.HG1", {"Mlei": 1})]
    empty = dict(og_source=lambda hg, s: model.HGOgs(hg, []))
    scr = _screen(tmp_path, fams=fams, hgs=hgs, **empty)

    async def body(app, pilot):
        assert _table(scr).border_title == "Counts"
        for want in ("Counts · tfs", "Counts · tfs › tfs.A.b", "Counts · tfs › tfs.A.b › HG1"):
            await pilot.press("enter")
            await pilot.pause()
            assert _table(scr).border_title == want
        await pilot.press("escape")
        await pilot.pause()
        assert _table(scr).border_title == "Counts · tfs › tfs.A.b"
    _run(scr, body)
    scr2 = _screen(tmp_path, level="og", scope="tfs.A.b.HG1", fams=fams, hgs=hgs, **empty)

    async def body2(app, pilot):
        assert _table(scr2).border_title == "Counts · tfs › tfs.A.b › HG1"
    _run(scr2, body2)


def test_counts_focus_col_not_a_column_falls_back_to_first(tmp_path):
    scr = _screen(tmp_path, level="og", scope="tfs.A.HG1", focus_col="tfs.A.HG1.99")

    async def body(app, pilot):
        assert _table(scr).cursor_coordinate.column == counts_tui.FIXED
        assert [c.id for c in scr.cols] and scr.status
    _run(scr, body)


def test_counts_source_keyword(tmp_path):
    calls = []
    scr = _screen(tmp_path, level="og", scope="tfs.A.HG1", calls=calls, source="possvm_prev")

    async def body(app, pilot):
        assert scr.source == "possvm_prev" and ("og_source", "tfs.A.HG1", "possvm_prev") in calls
        assert [c.id for c in scr.cols] == ["tfs.A.HG1.0"]
    _run(scr, body)
    with pytest.raises(ValueError):
        _screen(tmp_path, level="og", scope="tfs.A.HG1", source="cluster")


def test_counts_species_name_once_per_row(tmp_path):
    scr = _screen(tmp_path)

    async def body(app, pilot):
        t = _table(scr)
        for i in range(len(scr._ax.labels)):
            clado, lab = (str(x) for x in t.get_row_at(i)[:2])
            assert (clado + " " + lab).count(lab) == 1
    _run(scr, body)


def test_counts_search_needs_3_characters(tmp_path):
    asked = []
    scr = _screen(tmp_path, og_search=lambda q: asked.append(q) or [])

    async def body(app, pilot):
        await pilot.press("slash", *"HG", "enter")
        await pilot.pause()
        assert scr.status == "type at least 3 characters" and asked == []
        assert scr.level == "class"
    _run(scr, body)


def test_counts_search_adds_at_most_200(tmp_path):
    many = [("tfs.A.HG1", model.OG(f"tfs.A.HG1.{k}", "x",
                                   [model.Member("Mlei_v05_G1", "Mlei", "NA", "NA")], None,
                                   "NA", "NA"), "possvm") for k in range(250)]
    scr = _screen(tmp_path, og_search=lambda q: many)

    async def body(app, pilot):
        await pilot.press("slash", *"HG1", "enter")
        await pilot.pause()
        assert len(scr.custom) == 200 and len(scr.cols) == 200
        assert scr.status == "200 of 250 hits shown"
    _run(scr, body)


def test_counts_custom_entries_keep_their_source(tmp_path):
    cfg = _cfg(tmp_path)
    cur = model.read_ogs(cfg, "tfs.A.HG1", "possvm")
    prev = model.read_ogs(cfg, "tfs.A.HG1", "possvm_prev")
    trees = []
    scr = _screen(tmp_path, og_search=lambda q: [("tfs.A.HG1", cur[0], "possvm"),
                                                 ("tfs.A.HG1", prev[0], "possvm_prev")],
                  open_tree=lambda hg, src, og, sp: trees.append((hg, src, og.id)))

    async def body(app, pilot):
        await pilot.press("slash", *"Tbx", "enter")
        await pilot.pause()
        assert scr.source == "possvm" and len(scr.cols) == 2
        assert _table(scr).border_title == "Counts · Custom (2) · mixed"
        assert {c.id for c in scr.cols} == {"tfs.A.HG1.0@possvm", "tfs.A.HG1.0@possvm_prev"}
        for j, c in enumerate(scr.cols):
            _table(scr).move_cursor(row=0, column=counts_tui.FIXED + j)
            await pilot.pause()
            await pilot.press("t")
            assert trees[-1] == ("tfs.A.HG1", c.id.split("@")[1], "tfs.A.HG1.0")
        await pilot.press("p")                    # each entry to the other of ITS source
        got = sorted((og.id, og.name, src) for _, og, src in scr.custom)
        assert got == [("tfs.A.HG1.0", "T/Tbx19", "possvm"),
                       ("tfs.A.HG1.0", "like:Tbx2/Tbx3", "possvm_prev")]
        await pilot.press("p")
        assert [(og.name, src) for _, og, src in scr.custom] == [
            ("T/Tbx19", "possvm"), ("like:Tbx2/Tbx3", "possvm_prev")]
    _run(scr, body)
