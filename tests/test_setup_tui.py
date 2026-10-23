"""druid/setup_tui.py: the TUI Setup tab (Textual pilot tests; skipped without Textual)."""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses

import pytest
import yaml

pytest.importorskip("textual")

from druid import core, families, paths, project, setup_state, setup_tui, sptree, tui, yamledit  # noqa: E402
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


def test_leaving_setup_with_invalid_config_keeps_raw_and_cfg(cli):
    async def go():
        app = tui.PhyloApp(core.load_config(paths.config_file()), refresh_s=3600)
        async with app.run_test() as pilot:
            raw0, cfg0 = app.raw, app.cfg
            await _setup(app, pilot)
            f = paths.config_file()
            bad = yaml.safe_load(f.read_text())
            bad.pop("outdir")                                         # parses, fails validation
            f.write_text(yaml.safe_dump(bad))
            with pytest.raises(core.ConfigError):
                core.config_from_raw(paths.read_raw())
            await pilot.press("tab")
            await pilot.pause()
            assert not isinstance(app.screen, setup_tui.SetupScreen) and app.tab == "jobs"
            assert app.raw is raw0 and app.cfg is cfg0 and "outdir" in app.raw   # neither half-updated
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
            for bad in ("{sp}{sp.fa}", "{sp}_{x}.fa", "{sp}{", "{sp}{0}", "nosp.fa"):
                # AttributeError, KeyError, ValueError, IndexError, no {sp}
                scr.query_one("#src-glob").value = bad
                scr.query_one("#src-tax").focus()
                await pilot.press("enter")
                await pilot.pause()
                assert paths.config_file().read_bytes() == before, bad
                assert "ERROR: the glob" in _text(scr, "#blockers"), bad
            scr.query_one("#src-glob").value = ""
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


def test_setup_on_locked_project_writes_nothing(cli, monkeypatch, tmp_path):
    f = paths.config_file()
    prot = tmp_path / "locked_prot"                                   # candidates, so ticks are real attempts
    prot.mkdir()
    for sp in ("Aaa", "Bbb"):
        (prot / f"{sp}_long.pep.fasta").write_text(">x\nM\n")
    (tmp_path / "locked_tax.tsv").write_text(TAX)
    raw = yaml.safe_load(f.read_text())
    raw["prepare"] = "locked"
    raw["species"] = ["Aaa"]
    raw["proteomes_dir"] = str(prot)
    raw["proteome_glob"] = "{sp}_long.pep.fasta"      # the fixture loads the template unformatted ({{sp}})
    raw["taxonomy"] = str(tmp_path / "locked_tax.tsv")
    f.write_text("# druid project adopted from phylocli/config.yaml (druid adopt).\n"
                 + yaml.safe_dump(raw, sort_keys=False))
    before = f.read_bytes()
    from pathlib import Path
    Path(core.load_config(f).params["genefam_info"]).write_text("")   # empty: Families would fill it
    files = {p: p.read_bytes() for p in paths.project_root().rglob("*")
             if p.is_file() and ".druid" not in p.parts}
    monkeypatch.setattr(setup_tui, "_run_editor", lambda path: pytest.fail("editor started"))

    async def go():
        app = tui.PhyloApp(core.load_config(f), refresh_s=3600)
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            for name in setup_tui.SetupScreen.SECTIONS:
                await _section(pilot, scr, name)
                await pilot.press("space", "a", "e", "enter", "x", "enter", "P")
                await app.workers.wait_for_complete()
                await pilot.pause()
            assert "ERROR: this project is adopted" in _text(scr, "#blockers")    # P refused
            scr.query_one("#rb-hmm").value = True                     # behind the disabled radios
            await pilot.pause()
            scr._set_hmm_dir(str(tmp_path))
            scr._set_families_source(str(tmp_path / "locked_tax.tsv"))
            scr._set_tree_source(str(tmp_path / "locked_tax.tsv"))
            scr._placed("Aaa", frozenset({"Bbb"}))
            scr._open_edit(0)
            await pilot.pause()
            assert not scr.query_one("#fam-edit").display
            for wid in ("#sw-generax", "#sw-origins"):                # toggle attempts behind the UI
                sw = scr.query_one(wid)
                assert sw.disabled
                sw.value = not sw.value
                await pilot.pause()
            await _section(pilot, scr, "Species")                     # table ticks: space, down, space, a
            scr.query_one("#sp-filter").value = ""
            t = scr.query_one("#sp-table")
            t.focus()
            await pilot.pause()
            assert t.row_count == 2 and scr.focused is t
            scr._msg = ""
            await pilot.press("space", "down", "space", "a")
            await pilot.pause()
            assert "prepare: locked" in _text(scr, "#blockers")      # each attempt refused with the reason
            assert all(str(t.get_row_at(i)[0]) == ("[x]" if i == 0 else "[ ]") for i in range(2))
            assert all(scr.query_one(f"#src-{k}").disabled for k in ("name", "dir", "glob", "tax"))
            assert "prepare: locked" in _text(scr, "#sp-reason")
            await pilot.press("tab")
            await pilot.pause()
            assert not isinstance(app.screen, setup_tui.SetupScreen)
    _run(go())
    assert f.read_bytes() == before
    assert {p: p.read_bytes() for p in paths.project_root().rglob("*")      # families, placements,
            if p.is_file() and ".druid" not in p.parts} == files            # trees: nothing written


# ---- Tree, Search, Families, prepare (Task 8) ----------------------------------------------------
def _tree(root, newick):
    for f in ("base_tree.binary.newick", "base_tree.newick"):
        (root / "data" / f).write_text(newick)


def _mine(mine):
    return {("sources",): [{"name": "mine", "proteomes_dir": str(mine),
                            "proteome_glob": "{sp}_long.pep.fasta", "taxonomy": "data/tax.tsv"}]}


def _fams(root):
    return [r.fields() for r in families.read(root / "data" / "families.csv")]


def test_tree_section_switches_off_base_usable(proj):
    root, _prot, _mine_ = proj
    _tree(root, "((Aaa:1,Xxx:1):1,Yyy:1)R;")
    yamledit.update_config({("species",): ["Aaa", "Bbb"]})

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Tree")
            t = scr.query_one("#tree-missing")
            assert t.display and t.row_count == 1 and str(t.get_row_at(0)[0]) == "Bbb"
            assert scr.focused is t
            assert "1 ticked species not on the tree: Bbb" in _text(scr, "#blockers")
            assert _text(scr, "#lbl-tree").endswith("!")
            await _section(pilot, scr, "Analyses")
            await pilot.press("space")                                    # GeneRax off
            scr.query_one("#sw-origins").focus()
            await pilot.press("space")                                    # origins off
            await pilot.pause()
            await _section(pilot, scr, "Tree")
            # Ruling K: placement hidden; the base choice and tree_source stay usable
            assert not t.display
            for wid in ("#tree-base", "#tree-source"):
                assert scr.query_one(wid).display and not scr.query_one(wid).disabled
            assert scr.focused is scr.query_one("#tree-base")
            assert setup_tui.TREE_OFF in _text(scr, "#tree-info")
            assert _text(scr, "#lbl-tree").endswith("·")
            assert "not on the tree" not in _text(scr, "#blockers")
            assert _text(scr, "#blockers") == "no blockers: ready for prepare"
            scr.query_one("#rb-tree-chromo").value = True
            await pilot.pause()
            assert _raw()["tree_source"] == setup_state.CHROMO_TREE
            assert _text(scr, "#blockers").endswith("no blockers: ready for prepare")
            scr._placed("Bbb", frozenset({"Aaa"}))                        # placement: refused
            await pilot.pause()
            assert _text(scr, "#blockers").startswith(setup_tui.TREE_OFF)
            assert not (root / "data" / sptree.PLACEMENTS).exists()
    _run(go())


def test_tree_base_refused_on_locked_project(cli):
    """Ruling E: prepare: locked: the base choice and tree_source refuse every change, behind the UI
    too; druid.yaml and the project's files stay byte-identical."""
    f = paths.config_file()
    raw = yaml.safe_load(f.read_text())
    raw["prepare"] = "locked"
    f.write_text(yaml.safe_dump(raw, sort_keys=False))
    before = f.read_bytes()
    files = {p: p.read_bytes() for p in paths.project_root().rglob("*")
             if p.is_file() and ".druid" not in p.parts}

    async def go():
        app = tui.PhyloApp(core.load_config(f), refresh_s=3600)
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Tree")
            assert scr.query_one("#tree-base").disabled and scr.query_one("#tree-source").disabled
            assert scr.focused is not scr.query_one("#tree-base")
            for rid in ("#rb-tree-chromo", "#rb-tree-custom"):        # behind the disabled radios
                scr._msg = ""
                scr.query_one(rid).value = True
                await pilot.pause()
                assert scr.query_one("#rb-tree-v3").value and "prepare: locked" in _text(scr, "#blockers")
            for kind in ("chromo", "custom"):
                scr._set_tree_base(kind)
            scr._set_tree_source(setup_state.CHROMO_TREE)
            await pilot.pause()
            assert scr.query_one("#rb-tree-v3").value and not scr._tree_custom
    _run(go())
    assert f.read_bytes() == before
    assert {p: p.read_bytes() for p in paths.project_root().rglob("*")
            if p.is_file() and ".druid" not in p.parts} == files


def test_tree_base_choice(proj):
    """v3 curated (tree_source unset) / chromo (94) / custom; the missing list follows the base."""
    root, prot, _mine_ = proj
    (prot / "Mlei_long.pep.fasta").write_text(">x\nM\n")
    (root / "data" / "tax.tsv").write_text(TAX + "Mlei\tMnemiopsis leidyi\t1\t1\t1\tMetazoa\tsrc\t1\tMT\tNA\n")
    yamledit.update_config({("species",): ["Aaa", "Mlei"]})            # fixture base: Aaa, Bbb, Ccc
    chromo = sptree.tips((root / "data" / "base_tree.chromo94.newick").read_text())
    assert len(chromo) == 94 and "Mlei" in chromo and "Aaa" not in chromo

    def missing(scr):
        t = scr.query_one("#tree-missing")
        return [str(t.get_row_at(i)[0]) for i in range(t.row_count)]

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Tree")
            assert scr.query_one("#rb-tree-v3").value and missing(scr) == ["Mlei"]
            scr.query_one("#rb-tree-chromo").value = True
            await pilot.pause()
            assert _raw()["tree_source"] == setup_state.CHROMO_TREE
            assert missing(scr) == ["Aaa"] and "chromo, 94 tips" in _text(scr, "#tree-info")
            assert "1 ticked species not on the tree: Aaa" in _text(scr, "#blockers")
            scr.query_one("#rb-tree-custom").value = True                 # nothing written yet
            await pilot.pause()
            assert _raw()["tree_source"] == setup_state.CHROMO_TREE
            assert scr.focused is scr.query_one("#tree-source") and scr.query_one("#rb-tree-custom").value
            scr.query_one("#rb-tree-v3").value = True
            await pilot.pause()
            assert not _raw().get("tree_source") and missing(scr) == ["Mlei"]
            assert scr.query_one("#rb-tree-v3").value
    _run(go())
    yamledit.update_config({("species_locked",): True})
    before = paths.config_file().read_bytes()

    async def locked():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Tree")
            assert scr.query_one("#tree-base").disabled
            scr.query_one("#rb-tree-chromo").value = True                 # behind the UI: refused
            await pilot.pause()
            assert scr.query_one("#rb-tree-v3").value and "read-only" in _text(scr, "#blockers")
    _run(locked())
    assert paths.config_file().read_bytes() == before


def test_place_as_sister_writes_placements(proj):
    root, _prot, mine = proj
    _tree(root, "((Aaa:1,Bbb:1):1,Xxx:1)R;")
    yamledit.update_config({**_mine(mine), ("species",): ["Aaa", "Bbb", {"sp": "Ccc", "source": "mine"}]})
    pl_file = root / "data" / sptree.PLACEMENTS

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Tree")
            assert str(scr.query_one("#tree-missing").get_row_at(0)[0]) == "Ccc"
            await pilot.press("enter")
            await pilot.pause()
            place = app.screen
            assert isinstance(place, setup_tui.PlaceScreen)
            assert {place.model.name[i] for i in range(len(place.model)) if place.model.is_tip(i)} \
                == {"Aaa", "Bbb"}                                         # the built tree, pruned
            await pilot.press("escape")                                   # cancel: nothing written
            await pilot.pause()
            assert app.screen is scr and not pl_file.exists()
            await pilot.press("enter")
            await pilot.pause()
            place = app.screen
            place.tree.goto(place.model.tip("Aaa"))
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            assert app.screen is scr
            assert pl_file.read_text() == "Ccc\tAaa\n"
            assert scr.query_one("#tree-missing").row_count == 0
            assert "placed Ccc as the sister of Aaa" in _text(scr, "#blockers")
            assert "not on the tree" not in _text(scr, "#blockers")
            assert _text(scr, "#lbl-tree").endswith("✓")
            built = sptree.build_trees("((Aaa:1,Bbb:1):1,Xxx:1)R;", "((Aaa:1,Bbb:1):1,Xxx:1)R;",
                                       ["Aaa", "Bbb", "Ccc"], sptree.read_placements(pl_file))[0]
            assert sptree.tips(built) == {"Aaa", "Bbb", "Ccc"}
    _run(go())


def test_place_on_internal_node_and_tree_source(proj, tmp_path):
    root, _prot, mine = proj
    _tree(root, "((Aaa:1,Xxx:1):1,Yyy:1)R;")
    own = tmp_path / "own.newick"
    own.write_text("((Aaa:1,Bbb:1)ab:1,Yyy:1)R;")
    yamledit.update_config({**_mine(mine), ("species",): ["Aaa", "Bbb", {"sp": "Ccc", "source": "mine"}]})

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Tree")
            assert scr.query_one("#tree-missing").row_count == 2          # Bbb, Ccc
            scr.query_one("#tree-source").focus()
            scr.query_one("#tree-source").value = str(tmp_path / "nope.newick")
            await pilot.press("enter")
            await pilot.pause()
            assert "tree_source" not in _raw() and "ERROR: no such tree file" in _text(scr, "#blockers")
            scr.query_one("#tree-source").value = str(own)
            await pilot.press("enter")
            await pilot.pause()
            assert _raw()["tree_source"] == str(own)
            t = scr.query_one("#tree-missing")
            assert t.row_count == 1 and str(t.get_row_at(0)[0]) == "Ccc"
            t.focus()
            await pilot.press("enter")
            await pilot.pause()
            place = app.screen
            place.tree.goto(place.model.mrca([place.model.tip("Aaa"), place.model.tip("Bbb")]))
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            assert (root / "data" / sptree.PLACEMENTS).read_text() == "Ccc\tAaa,Bbb\n"
            assert scr.query_one("#tree-missing").row_count == 0
    _run(go())
    assert own.read_text() == "((Aaa:1,Bbb:1)ab:1,Yyy:1)R;"                # the user's tree is read only


def test_search_custom_hmm_rows_appear_with_defaults(proj, tmp_path):
    root, _prot, _mine_ = proj
    hd = tmp_path / "hmms"
    hd.mkdir()
    (hd / "Foo.hmm").write_text("HMMER3/f\nNAME  Foo\nGA    20.0 20.0;\n//\n")
    (hd / "Bar.hmm").write_text("HMMER3/f\nNAME  Bar\n//\n")
    hd.chmod(0o555)
    mtimes = {p.name: p.stat().st_mtime_ns for p in hd.iterdir()}
    n0 = len(_fams(root))

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Search")
            assert scr.focused is scr.query_one("#se-type")
            assert scr.query_one("#rb-file").value and not scr.query_one("#se-hmmdir").display
            before = paths.config_file().read_bytes()
            scr.query_one("#rb-hmm").value = True
            await pilot.pause()
            assert scr.query_one("#se-hmmdir").display and scr.focused is scr.query_one("#se-hmmdir")
            assert "set params.hmm_dir" in _text(scr, "#blockers")
            assert _text(scr, "#lbl-search").endswith("!")
            scr.query_one("#se-hmmdir").value = str(tmp_path / "nope")
            await pilot.press("enter")
            await pilot.pause()
            assert paths.config_file().read_bytes() == before
            assert "ERROR: not a directory" in _text(scr, "#blockers")
            scr.query_one("#se-hmmdir").value = str(hd)
            await pilot.press("enter")
            await pilot.pause()
            assert _raw()["params"]["hmm_dir"] == str(hd)
            rows = _fams(root)
            assert len(rows) == n0 + 2
            assert rows[-2:] == [["Bar", "Bar", "1.1", "3", "1e-5", "custom", "cus"],
                                 ["Foo", "Foo", "1.1", "3", "GA", "custom", "cus"]]
            assert _text(scr, "#lbl-search").endswith("✓")
            await _section(pilot, scr, "Families")
            scr.query_one("#fam-filter").value = "custom"
            await pilot.pause()
            t = scr.query_one("#fam-table")
            assert t.row_count == 2
            assert [str(c) for c in t.get_row_at(0)] == ["[x]", "cus.Bar", "Bar", "1.1", "3", "1e-5",
                                                       "custom", "cus"]
            scr.query_one("#rb-file").value = True                        # back: hmm_dir and rows go
            await pilot.pause()
            assert _raw()["params"]["hmm_dir"] is None and len(_fams(root)) == n0
            assert "hmm_dir: null        # optional dir" in paths.config_file().read_text()
    _run(go())
    hd.chmod(0o755)
    assert {p.name: p.stat().st_mtime_ns for p in hd.iterdir()} == mtimes


def test_unreadable_hmm_is_an_error_line_not_a_crash(proj, tmp_path):
    hd = tmp_path / "hmms"
    hd.mkdir()
    (hd / "Foo.hmm").write_text("HMMER3/f\nNAME  Foo\n//\n")
    (hd / "Foo.hmm").chmod(0o000)

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Search")
            before = paths.config_file().read_bytes()
            scr.query_one("#rb-hmm").value = True
            await pilot.pause()
            scr.query_one("#se-hmmdir").value = str(hd)
            await pilot.press("enter")
            await pilot.pause()
            assert paths.config_file().read_bytes() == before
            assert f"ERROR: cannot read the HMMs in {hd}: PermissionError" in _text(scr, "#blockers")
            (hd / "Foo.hmm").chmod(0o644)                              # readable: set it,
            scr._set_hmm_dir(str(hd))
            await pilot.pause()
            assert _raw()["params"]["hmm_dir"] == str(hd)
            (hd / "Foo.hmm").chmod(0o000)                              # then unreadable again:
            scr.query_one("#rb-file").value = True                     # switching back is refused
            await pilot.pause()
            assert _raw()["params"]["hmm_dir"] == str(hd)
            assert f"ERROR: cannot read the HMMs in {hd}" in _text(scr, "#blockers")
            assert app.is_running
    try:
        _run(go())
    finally:
        (hd / "Foo.hmm").chmod(0o644)


def test_switch_on_species_locked_project_notes_stale_trees(proj):
    yamledit.update_config({("species",): ["Aaa"], ("species_locked",): True})

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Analyses")
            await pilot.press("space")                                 # GeneRax off
            await pilot.pause()
            assert _raw()["params"]["run_generax"] is False
            assert "trees not rebuilt: species are locked" in _text(scr, "#blockers")
    _run(go())


def test_bad_hmm_dir_in_config_is_a_blocker_line(proj, tmp_path):
    yamledit.update_config({("params", "hmm_dir"): str(tmp_path / "gone")})

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            assert "params.hmm_dir is not a directory" in _text(scr, "#blockers")
            assert scr.query_one("#rb-hmm").value and _text(scr, "#lbl-search").endswith("!")
    _run(go())


def test_query_sequences_disabled(proj):
    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Search")
            rb = scr.query_one("#rb-query")
            assert rb.disabled and "not available yet" in str(rb.label)
            before = paths.config_file().read_bytes()
            await pilot.press("down", "down", "enter", "space")
            await pilot.pause()
            assert not rb.value and scr._search == "file"
            assert paths.config_file().read_bytes() == before
    _run(go())


def test_own_families_file(proj, tmp_path):
    root, _prot, _mine_ = proj
    own = tmp_path / "own.csv"
    own.write_text("X1\tPF_X\t1.1\t3\tGA\tTF\ttfs\nX2\tPF_Y\t1.1\t3\tGA\tTF\ttfs\n")

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Search")
            scr.query_one("#se-famfile").focus()
            scr.query_one("#se-famfile").value = "data/families.csv"     # the target itself: refused
            await pilot.press("enter")
            await pilot.pause()
            assert "families_source" not in _raw() and "ERROR:" in _text(scr, "#blockers")
            scr.query_one("#se-famfile").value = str(own)
            await pilot.press("enter")
            await pilot.pause()
            assert _raw()["families_source"] == str(own)
            assert _fams(root) == [r.fields() for r in families.read(own)]
            assert scr.query_one("#fam-table").row_count == 2
    _run(go())


def test_families_all_ticked_untick_writes_csv(proj):
    root, _prot, _mine_ = proj
    f = root / "data" / "families.csv"
    f.write_text("")
    lib = [r.fields() for r in families.library()]

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            assert "no families in params.genefam_info" in _text(scr, "#blockers")
            assert _text(scr, "#lbl-families").endswith("!")
            await _section(pilot, scr, "Families")                        # first open: all written
            assert _fams(root) == lib and len(lib) == 356
            t = scr.query_one("#fam-table")
            assert t.row_count == 356 and all(str(t.get_row_at(i)[0]) == "[x]" for i in range(356))
            assert "no families" not in _text(scr, "#blockers")
            assert _text(scr, "#lbl-families").endswith("356")
            assert scr.focused is scr.query_one("#fam-filter")
            await pilot.press("enter")                                    # to the table
            assert scr.focused is t
            await pilot.press("space")                                    # untick row 0
            await pilot.pause()
            assert _fams(root) == lib[1:] and str(t.get_row_at(0)[0]) == "[ ]"
            assert "355 ticked / 356" in _text(scr, "#fam-count")
            scr.query_one("#fam-filter").value = "slc"
            await pilot.pause()
            assert 0 < t.row_count < 356 and "shown" in _text(scr, "#fam-count")
            scr.query_one("#fam-filter").value = ""
            await pilot.pause()
            t.focus()
            t.move_cursor(row=0)
            await pilot.press("space")                                    # tick again: library order
            await pilot.pause()
            assert _fams(root) == lib
    _run(go())


def test_family_row_edit_persists(proj):
    root, _prot, _mine_ = proj

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Families")
            await pilot.press(*"PF_A", "enter")
            t = scr.query_one("#fam-table")
            assert t.row_count == 1 and scr.focused is t
            await pilot.press("enter")                                    # the edit form
            await pilot.pause()
            assert scr.query_one("#fam-edit").display and scr.focused is scr.query_one("#fe-inflation")
            assert scr.query_one("#fe-threshold").value == "GA"
            before = _fams(root)
            scr.query_one("#fe-inflation").value = "x"
            for _ in range(5):
                await pilot.press("enter")
            await pilot.pause()
            assert _fams(root) == before and "ERROR: inflation" in _text(scr, "#blockers")
            await pilot.press("escape")                                   # cancel
            await pilot.pause()
            assert not scr.query_one("#fam-edit").display and scr.focused is t
            await pilot.press("enter")
            await pilot.pause()
            for col, v in (("inflation", "1.5"), ("min_seqs", "4"), ("threshold", "1e-10"),
                           ("pref1", "TF"), ("pref2", "tfx")):
                scr.query_one(f"#fe-{col}").value = v
            scr.query_one("#fe-pref2").focus()
            await pilot.press("enter")
            await pilot.pause()
            assert not scr.query_one("#fam-edit").display
            assert ["A", "PF_A", "1.5", "4", "1e-10", "TF", "tfx"] in _fams(root)
            assert "tfx.A: saved" in _text(scr, "#blockers")
        app2 = _app()                                                     # reopened: the edit wins
        async with app2.run_test() as pilot:
            scr = await _setup(app2, pilot)
            await _section(pilot, scr, "Families")
            await pilot.press(*"PF_A")
            await pilot.pause()
            t = scr.query_one("#fam-table")
            assert t.row_count == 1
            assert [str(c) for c in t.get_row_at(0)] == ["[x]", "tfx.A", "PF_A", "1.5", "4", "1e-10",
                                                       "TF", "tfx"]
    _run(go())


def test_families_editable_after_lock(proj):
    root, _prot, _mine_ = proj
    _tree(root, "((Aaa:1,Xxx:1):1,Yyy:1)R;")
    yamledit.update_config({("species",): ["Aaa", "Bbb"], ("species_locked",): True})
    before = paths.config_file().read_bytes()

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Tree")                            # read-only: nothing focused
            t = scr.query_one("#tree-missing")
            assert t.row_count == 1 and t.disabled and scr.query_one("#tree-source").disabled
            assert "read-only" in _text(scr, "#tree-info")
            scr._open_place(0)                                            # behind the UI: refused
            await pilot.pause()
            assert not isinstance(app.screen, setup_tui.PlaceScreen)
            assert not (root / "data" / sptree.PLACEMENTS).exists()
            await _section(pilot, scr, "Families")
            assert _text(scr, "#fam-reason").startswith("space")
            await pilot.press(*"PF_A", "enter", "space")
            await pilot.pause()
            assert len(_fams(root)) == 4 and "PF_A" not in {r[1] for r in _fams(root)}   # GENEFAM: 5
    _run(go())
    assert paths.config_file().read_bytes() == before


def test_prepare_key_runs_and_reports(proj):
    root, _prot, _mine_ = proj

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await pilot.press("P")                                        # nothing ticked
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert _text(scr, "#blockers").startswith("ERROR: cannot prepare")
            assert not (root / "data" / "input.fasta").exists()
            yamledit.update_config({("species",): ["Aaa", "Bbb"]})
            await pilot.press("P")
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = _text(scr, "#blockers")
            assert text.startswith("prepare wrote data/input.fasta, data/species_tree.binary.newick")
            assert (root / "data" / "input.fasta").read_text() == ">Aaa_x\nM\n>Bbb_x\nM\n"
            assert sptree.tips((root / "data" / "species_tree.binary.newick").read_text()) == {"Aaa", "Bbb"}
    _run(go())


def _ids_ticks(scr, ids):
    t = scr.query_one("#fam-table")
    rows = [[str(c) for c in t.get_row_at(i)] for i in range(t.row_count)]
    return [(r[1], r[0], r[3]) for r in rows if r[1] in ids]           # (id, tick, inflation)


def test_merge_shared_class_name_on_the_library():
    lib = families.library()
    ids = [setup_tui._fam_id(r) for r in lib]
    assert ids.count("rbp.CSD") == 1 and ids.count("tfs.CSD") == 1    # same class_name and hmms
    edited = [dataclasses.replace(r, inflation="1.5") if setup_tui._fam_id(r) == "tfs.CSD" else r
              for r in lib if setup_tui._fam_id(r) != "rbp.CSD"]
    out = setup_tui._merge(lib, edited)
    assert len(out) == len(lib)                                        # nothing appended
    got = {setup_tui._fam_id(r): (t, r.inflation) for r, t in out if r.class_name == "CSD"}
    assert got == {"rbp.CSD": (False, "1.1"), "tfs.CSD": (True, "1.5")}
    # both Synapsin rows share the id neu.Synapsin: each edit stays on its own row (by hmms)
    syn = [dataclasses.replace(r, min_seqs="9") if r.hmms == "Synapsin" else r for r in lib]
    out = setup_tui._merge(lib, syn)
    assert sorted((r.hmms, r.min_seqs) for r, t in out if r.class_name == "Synapsin" and t) == \
        [("Synapsin", "9"), ("Synapsin,Synapsin_C", "3")]
    # a prefix edit with two candidates (rbp.CSD and tfs.CSD both unticked): no guess, appended
    pre = [dataclasses.replace(r, pref2="tfx") if setup_tui._fam_id(r) == "tfs.CSD" else r
           for r in lib if setup_tui._fam_id(r) != "rbp.CSD"]
    out = setup_tui._merge(lib, pre)
    got = sorted((setup_tui._fam_id(r), t) for r, t in out if r.class_name == "CSD")
    assert got == [("rbp.CSD", False), ("tfs.CSD", False), ("tfx.CSD", True)]


def test_untick_and_edit_rows_sharing_a_class_name(proj):
    root, _prot, _mine_ = proj
    (root / "data" / "families.csv").write_text("")

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Families")                        # all 356 written
            t = scr.query_one("#fam-table")
            ids = [str(t.get_row_at(i)[1]) for i in range(t.row_count)]
            t.focus()
            t.move_cursor(row=ids.index("rbp.CSD"))
            await pilot.press("space")                                    # untick rbp.CSD
            await pilot.pause()
            t.move_cursor(row=ids.index("tfs.CSD"))
            await pilot.press("enter")                                    # edit tfs.CSD
            await pilot.pause()
            scr.query_one("#fe-inflation").value = "1.5"
            scr.query_one("#fe-pref2").focus()
            await pilot.press("enter")
            await pilot.pause()
            assert _ids_ticks(scr, {"rbp.CSD", "tfs.CSD"}) == [("rbp.CSD", "[ ]", "1.1"),
                                                              ("tfs.CSD", "[x]", "1.5")]
            fam_ids = [setup_tui._fam_id(r) for r in families.read(root / "data" / "families.csv")]
            assert "rbp.CSD" not in fam_ids and fam_ids.count("tfs.CSD") == 1
            assert len(fam_ids) == 355
            t.move_cursor(row=ids.index("rbp.CSD"))
            await pilot.press("space")                                    # tick it again: no duplicate
            await pilot.pause()
            rows = families.read(root / "data" / "families.csv")
            fam_ids = [setup_tui._fam_id(r) for r in rows]
            assert fam_ids.count("rbp.CSD") == 1 and fam_ids.count("tfs.CSD") == 1
            assert len(rows) == 356
            assert [r.inflation for r in rows if setup_tui._fam_id(r) == "tfs.CSD"] == ["1.5"]
    _run(go())


def test_hmm_named_like_a_library_family_switch_back(proj, tmp_path):
    root, _prot, _mine_ = proj
    lib = [r.fields() for r in families.library()]
    (root / "data" / "families.csv").write_text("".join("\t".join(f) + "\n" for f in lib))
    hd = tmp_path / "hmms"
    hd.mkdir()
    (hd / "CSD.hmm").write_text("HMMER3/f\nNAME  CSD\nGA    20.0 20.0;\n//\n")

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Search")
            scr.query_one("#rb-hmm").value = True
            await pilot.pause()
            scr.query_one("#se-hmmdir").value = str(hd)
            await pilot.press("enter")
            await pilot.pause()
            assert _fams(root) == lib + [["CSD", "CSD", "1.1", "3", "GA", "custom", "cus"]]
            scr.query_one("#rb-file").value = True                        # back: only cus.CSD goes
            await pilot.pause()
            assert _raw()["params"]["hmm_dir"] is None
            assert _fams(root) == lib
    _run(go())


def test_same_class_name_is_a_warning_not_a_blocker(proj):
    root, _prot, _mine_ = proj
    yamledit.update_config({("species",): ["Aaa", "Bbb"]})

    async def go():
        app = _app()
        async with app.run_test() as pilot:
            scr = await _setup(app, pilot)
            await _section(pilot, scr, "Families")                        # GENEFAM: no collision
            assert "warning" not in _text(scr, "#blockers")
            t = scr.query_one("#fam-table")
            t.focus()
            for fid in ("rbp.CSD", "tfs.CSD"):                            # tick both
                ids = [str(t.get_row_at(i)[1]) for i in range(t.row_count)]
                t.move_cursor(row=ids.index(fid))
                await pilot.press("space")
                await pilot.pause()
            fam_ids = [setup_tui._fam_id(r) for r in families.read(root / "data" / "families.csv")]
            assert {"rbp.CSD", "tfs.CSD"} <= set(fam_ids) and len(fam_ids) == 7
            text = _text(scr, "#blockers")
            assert "warning: family name CSD is listed under 2 prefixes (rbp, tfs)" in text
            assert "no blockers: ready for prepare" in text
            assert not any("CSD" in b for b in scr._blockers)
            await pilot.press("P")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert _text(scr, "#blockers").startswith("prepare wrote data/input.fasta")
            assert "warning: family name CSD" in _text(scr, "#blockers")    # still shown after
    _run(go())
