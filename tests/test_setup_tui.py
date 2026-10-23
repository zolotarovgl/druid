"""druid/setup_tui.py: the TUI Setup tab (Textual pilot tests; skipped without Textual)."""
from __future__ import annotations

import asyncio
import contextlib

import pytest
import yaml

pytest.importorskip("textual")

from druid import core, paths, project, setup_state, setup_tui, tui, yamledit  # noqa: E402
from tests.conftest import GENEFAM  # noqa: E402
from tests.test_cli import cli  # noqa: E402,F401  (fixture)

TAX = "".join(f"{p}\t{p} sp\t1\t1\t1\tMetazoa, X{p}\tsrc\t1\tMT\tNA\n" for p in ("Aaa", "Bbb", "Ccc"))


@pytest.fixture
def proj(tmp_path):
    """A fresh `druid init` project: default source Aaa, Bbb (+ Zzz, no taxonomy row), nothing ticked;
    a custom proteome dir `mine` (Ccc) not yet a source."""
    root = tmp_path / "p"
    project.init(root, "23/10/2026")
    paths.use(root)
    prot = tmp_path / "prot"
    prot.mkdir()
    for sp in ("Aaa", "Bbb", "Zzz"):
        (prot / f"{sp}_long.pep.fasta").write_text(">x\nM\n")
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "Ccc_long.pep.fasta").write_text(">x\nM\n")
    (root / "data" / "tax.tsv").write_text(TAX)
    (root / "data" / "families.csv").write_text(GENEFAM)
    for f in ("base_tree.binary.newick", "base_tree.newick"):
        (root / "data" / f).write_text("((Aaa:1,Bbb:1):1,Ccc:1)R;")
    yamledit.update_config({("proteomes_dir",): str(prot), ("taxonomy",): "data/tax.tsv"})
    return root, prot, mine


def _app():
    return tui.PhyloApp(core.load_config(paths.config_file()), refresh_s=3600)


def _run(coro):
    return asyncio.run(coro)


def _raw():
    return paths.read_raw()


async def _setup(app, pilot):
    """The open SetupScreen (opening it with tab tab when the app did not start there)."""
    await pilot.pause()
    if not isinstance(app.screen, setup_tui.SetupScreen):
        await pilot.press("tab", "tab")
        await pilot.pause()
    assert isinstance(app.screen, setup_tui.SetupScreen)
    return app.screen


async def _section(pilot, scr, name):
    """Highlight `name` in the left list, then enter it."""
    scr.query_one("#sections").focus()
    scr.query_one("#sections").index = setup_tui.SetupScreen.SECTIONS.index(name)
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


def _text(scr, wid):
    return str(scr.query_one(wid).render())


def test_tab_cycles_to_setup_and_back(cli):
    async def go():
        app = tui.PhyloApp(core.load_config(paths.config_file()), refresh_s=3600)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert not isinstance(app.screen, setup_tui.SetupScreen)     # results exist: locked
            assert app._tab_text == "[Jobs] │ Results │ Setup"
            await pilot.press("tab")
            await pilot.pause()
            assert app.tab == "results" and app._tab_text == "Jobs │ [Results] │ Setup"
            await pilot.press("tab")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, setup_tui.SetupScreen) and app.tab == "setup"
            assert scr.query_one("#sections").has_focus
            yamledit.update_config({("params", "min_seqs"): 7})      # an edit made while in Setup
            await pilot.press("tab")
            await pilot.pause()
            assert not isinstance(app.screen, setup_tui.SetupScreen) and app.tab == "jobs"
            assert app.raw["params"]["min_seqs"] == 7 and app.cfg.params["min_seqs"] == 7
            assert app.focused is app.query_one("#overview")
            await pilot.press("shift+tab")                            # backwards: Jobs -> Setup
            await pilot.pause()
            assert isinstance(app.screen, setup_tui.SetupScreen)
            await pilot.press("escape")                               # esc on the list: back to Jobs
            await pilot.pause()
            assert not isinstance(app.screen, setup_tui.SetupScreen) and app.tab == "jobs"
    _run(go())


def test_fresh_project_opens_on_setup(proj):
    async def go():
        app = _app()
        async with app.run_test() as pilot:
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, setup_tui.SetupScreen) and app.tab == "setup"
            assert [i.id for i in scr.query_one("#sections").children] == \
                [f"item-{s.lower()}" for s in setup_tui.SetupScreen.SECTIONS]
            for s in setup_tui.SetupScreen.SECTIONS:
                assert scr.query_one(f"#sec-{s.lower()}")
            assert _text(scr, "#lbl-species").endswith("!")          # nothing ticked yet
    _run(go())


def test_species_filter_tick_writes_species(proj):
    root, _prot, mine = proj
    yamledit.update_config({("sources",): [{"name": "mine", "proteomes_dir": str(mine),
                                            "proteome_glob": "{sp}_long.pep.fasta",
                                            "taxonomy": "data/tax.tsv"}]})

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Species")
            assert scr.focused is scr.query_one("#sp-filter")
            t = scr.query_one("#sp-table")
            assert t.row_count == 3                                   # Aaa Bbb (default), Ccc (mine)
            assert _text(scr, "#sp-count") == "0 ticked / 3"
            await pilot.press("x", "b", "b", "b")                     # taxonomy column: "Metazoa, XBbb"
            await pilot.pause()
            assert t.row_count == 1 and _text(scr, "#sp-count") == "0 ticked / 3 · 1 shown"
            await pilot.press("enter", "space")
            await pilot.pause()
            assert _raw()["species"] == ["Bbb"]
            assert _text(scr, "#sp-count") == "1 ticked / 3 · 1 shown"
            assert str(t.get_row_at(0)[0]) == "[x]"
            scr.query_one("#sp-filter").value = "mine"                # source column
            await pilot.pause()
            assert t.row_count == 1
            scr.query_one("#sp-filter").value = ""
            await pilot.pause()
            t.focus()
            await pilot.press("a")                                    # tick all shown
            await pilot.pause()
            assert _raw()["species"] == ["Bbb", "Aaa", {"sp": "Ccc", "source": "mine"}]
            t.move_cursor(row=0)                                      # Aaa: untick
            await pilot.press("space")
            await pilot.pause()
            assert setup_state.selected(_raw()) == [("Bbb", "default"), ("Ccc", "mine")]
            assert _text(scr, "#lbl-species").endswith("2")
    _run(go())


def test_species_readonly_when_locked(proj):
    yamledit.update_config({("species",): ["Aaa"], ("species_locked",): True})
    before = paths.config_file().read_bytes()

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)                            # locked: not opened by itself
            await _section(pilot, scr, "Species")
            assert "read-only" in _text(scr, "#sp-reason") and "locked" in _text(scr, "#sp-reason")
            scr.query_one("#sp-table").focus()
            await pilot.press("space", "down", "space", "a")
            await pilot.pause()
            assert paths.config_file().read_bytes() == before
            assert "read-only" in _text(scr, "#blockers")
            await _section(pilot, scr, "Analyses")                    # only the species are locked
            await pilot.press("space")
            await pilot.pause()
            assert _raw()["params"]["run_generax"] is False
    _run(go())


def test_analyses_switches_write_params(proj):
    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Analyses")
            gx, org = scr.query_one("#sw-generax"), scr.query_one("#sw-origins")
            assert gx.value is True and org.value is True and scr.focused is gx
            await pilot.press("space")
            await pilot.pause()
            assert _raw()["params"]["run_generax"] is False
            org.focus()
            await pilot.press("space")
            await pilot.pause()
            assert _raw()["params"]["origins"] is False and _raw()["params"]["run_generax"] is False
            text = paths.config_file().read_text()
            assert "origins: false        # compute orthogroup origins" in text   # comment kept
    _run(go())


def test_add_custom_source(proj, tmp_path):
    root, _prot, mine = proj

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Source")
            assert scr.focused is scr.query_one("#src-name")
            assert "default" in _text(scr, "#src-list")
            before = paths.config_file().read_bytes()
            await pilot.press(*"mine", "enter")
            assert scr.focused is scr.query_one("#src-dir")
            scr.query_one("#src-dir").value = str(tmp_path / "nope")
            await pilot.press("enter", "enter", "enter")                  # glob, taxonomy left empty
            await pilot.pause()
            assert paths.config_file().read_bytes() == before         # not a directory: nothing written
            assert "ERROR: not a directory" in _text(scr, "#blockers")
            scr.query_one("#src-dir").value = str(mine)
            scr.query_one("#src-tax").value = "data/tax.tsv"
            scr.query_one("#src-tax").focus()
            await pilot.press("enter")
            await pilot.pause()
            assert _raw()["sources"] == [{"name": "mine", "proteomes_dir": str(mine),
                                          "proteome_glob": "{sp}_long.pep.fasta",
                                          "taxonomy": "data/tax.tsv"}]
            assert "mine" in _text(scr, "#src-list") and scr.query_one("#src-name").value == ""
            assert scr.query_one("#sp-table").row_count == 3              # Ccc from mine is a candidate
            scr.query_one("#src-name").value = "mine"                     # duplicate name refused
            scr.query_one("#src-dir").value = str(mine)
            scr.query_one("#src-tax").focus()
            await pilot.press("enter")
            await pilot.pause()
            assert len(_raw()["sources"]) == 1 and "ERROR:" in _text(scr, "#blockers")
    _run(go())


def test_blockers_line_updates(proj, monkeypatch):
    root, _prot, mine = proj

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            assert "no species ticked" in _text(scr, "#blockers")
            await _section(pilot, scr, "Species")
            scr.query_one("#sp-table").focus()
            await pilot.press("space")                                    # Aaa
            await pilot.pause()
            assert "no species ticked" not in _text(scr, "#blockers")
            assert _text(scr, "#blockers") == "no blockers: ready for prepare"
            # a malformed custom source never crashes the screen: its error is a blockers line
            yamledit.update_config({("sources",): [{"name": "bad", "proteomes_dir": str(mine),
                                                    "proteome_glob": "{sp}_{x}.fa"}],
                                    ("species",): ["Aaa", {"sp": "Ccc", "source": "bad"}]})
            scr.query_one("#sp-table").focus()
            await pilot.press("down", "space")                            # Bbb: any change re-reads
            await pilot.pause()
            assert "KeyError" in _text(scr, "#blockers")
            # Config: e runs $EDITOR (suspended app), then re-validates; a broken file is ERROR:
            await _section(pilot, scr, "Config")
            assert "proteomes_dir:" in _text(scr, "#cfg-text")
            seen = []

            def editor(path):
                seen.append(path)
                path.write_text(path.read_text().replace("qos: normal", "qos: [unclosed"))
                return 0
            monkeypatch.setattr(setup_tui, "_run_editor", editor)
            monkeypatch.setattr(app, "suspend", contextlib.nullcontext)
            await pilot.press("e")
            await pilot.pause()
            assert seen == [paths.config_file()]
            assert _text(scr, "#blockers").startswith("ERROR:") and "not valid YAML" in _text(scr, "#blockers")
            assert _text(scr, "#lbl-config").endswith("!")
    _run(go())


def test_setup_on_locked_project_writes_nothing(cli, monkeypatch):
    f = paths.config_file()
    raw = yaml.safe_load(f.read_text())
    raw["prepare"] = "locked"
    raw["species"] = ["Aaa"]
    f.write_text("# druid project adopted from phylocli/config.yaml (druid adopt).\n"
                 + yaml.safe_dump(raw, sort_keys=False))
    before = f.read_bytes()
    monkeypatch.setattr(setup_tui, "_run_editor", lambda path: pytest.fail("editor started"))

    async def go():
        app = tui.PhyloApp(core.load_config(f), refresh_s=3600)
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            for name in setup_tui.SetupScreen.SECTIONS:
                await _section(pilot, scr, name)
                await pilot.press("space", "a", "e", "enter", "x", "enter")
                await pilot.pause()
            for wid in ("#sw-generax", "#sw-origins"):                # toggle attempts behind the UI
                sw = scr.query_one(wid)
                assert sw.disabled
                sw.value = not sw.value
                await pilot.pause()
            assert all(scr.query_one(f"#src-{k}").disabled for k in ("name", "dir", "glob", "tax"))
            assert "prepare: locked" in _text(scr, "#sp-reason")
            await pilot.press("tab")
            await pilot.pause()
            assert not isinstance(app.screen, setup_tui.SetupScreen)
    _run(go())
    assert f.read_bytes() == before
