"""phylocli/tui.py (Textual pilot tests; skipped when Textual is not installed)."""
import asyncio
import os
import re
import time

import pytest

pytest.importorskip("textual")

from phylocli import core, tui  # noqa: E402
from phylocli.tests.test_cli import _state, cli  # noqa: E402,F401

SACCT_OOM = ("12345_0|COMPLETED|10M|00:01:00|0:0\\n"
             "12345_1|OUT_OF_MEMORY|4100M|00:03:00|0:125\\n")


def _cfg():
    return core.load_config(os.environ["PHYLOCLI_CONFIG"])


def _run(coro):
    return asyncio.run(coro)


def test_tui_loads_and_filters_failed(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600, start="hgs")
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert app.stage == "align" and app.filter == "actionable"
            await pilot.press("f")
            assert app.filter == "failed"
            assert [r.hg for r in app.visible()] == ["tfs.C_x.HG1"]
            await pilot.press("f")
            assert app.filter == "ready" and [r.hg for r in app.visible()] == ["tfs.A.HG11"]
    _run(go())


def test_tui_select_all_and_quit(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600, start="hgs")
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("f", "a")                     # actionable -> failed
            assert app.selected == {"tfs.C_x.HG1"}
            await pilot.press("q")
    _run(go())


def test_tui_command_without_textual(cli, monkeypatch):
    import sys

    import phylocli
    # None in sys.modules makes `from textual import ...` raise ModuleNotFoundError(name="textual");
    # phylocli.tui must be forgotten both as a module and as the package attribute.
    monkeypatch.setitem(sys.modules, "textual", None)
    monkeypatch.delitem(sys.modules, "phylocli.tui", raising=False)
    monkeypatch.delattr(phylocli, "tui", raising=False)
    r = cli(["tui"])
    assert r.exit_code == 1 and "pip install textual" in r.output


async def _settle(app, pilot):
    """Wait for the dialog's worker thread and the UI messages it posted."""
    await app.workers.wait_for_complete()
    await pilot.pause()


def _calls():
    p = _state["bin"] / "calls.txt"
    return p.read_text().splitlines() if p.exists() else []


def _failed_app(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)
    app = tui.PhyloApp(_cfg(), refresh_s=3600, start="hgs")
    app.filter = "failed"          # these tests exercise the failed-only view (default is actionable)
    return app


def test_resource_groups_bump_oom(cli, monkeypatch):
    _failed_app(cli, monkeypatch)
    from phylocli import model
    rows = [r for r in model.hg_rows(_cfg(), "align") if r.state == "failed"]
    groups = tui.resource_groups(_cfg(), "align", rows)
    assert [(g[0], g[1].mem_mb, g[2]) for g in groups] == [("OOM", 8192, ["tfs.C_x.HG1"])]


def test_resubmit_dry_run_then_confirm(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    n0 = len(_calls())

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a", "r")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, tui.ResubmitScreen)
            scr.query_one("#mem-0").value = "16G"
            await pilot.press("enter")
            await _settle(app, pilot)
            assert "dry run" in scr._shown
            assert re.search(r"· \d+ cpus · ", scr._shown)   # the separator keeps its space
            assert len(_calls()) == n0                      # dry run submits nothing
            await pilot.press("y")
            await _settle(app, pilot)
            assert scr.submitted == ["12345"]
    _run(go())
    script = sorted((_state["runs"]).glob("*_align*/array_0.sbatch"))[-1].read_text()
    assert "--mem=16384M" in script


def test_resubmit_escape_submits_nothing(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    n0 = len(_calls())

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a", "r", "enter", "escape")
            await _settle(app, pilot)
            assert not isinstance(app.screen, tui.ResubmitScreen)
    _run(go())
    assert len(_calls()) == n0


def test_resubmit_bad_value_is_inline_error(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    n0 = len(_calls())

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a", "r")
            await pilot.pause()
            scr = app.screen
            scr.query_one("#mem-0").value = "abc"
            await pilot.press("enter", "y")
            await pilot.pause()
            assert "bad memory value" in scr._shown
            assert scr.submitted == []
    _run(go())
    assert len(_calls()) == n0


def test_resubmit_nothing_selected(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            assert not isinstance(app.screen, tui.ResubmitScreen)
    _run(go())


def test_confirm_skips_hg_queued_after_dry_run(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a", "r", "enter")
            await _settle(app, pilot)
            scr = app.screen
            monkeypatch.setenv("FAKE_SQUEUE", "12345_1|phylo-align\n")   # queued meanwhile
            await pilot.press("y")
            await _settle(app, pilot)
            assert scr.submitted == [] and "already queued" in scr._shown
    _run(go())


def test_log_popup(cli, monkeypatch, tmp_path):
    app = _failed_app(cli, monkeypatch)
    run = sorted(_state["runs"].glob("*_align"))[-1]
    (run / "logs" / "align_12345_1.err").write_text("boom: out of memory\n")

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("l")
            await pilot.pause()
            assert isinstance(app.screen, tui.LogScreen)
            assert "boom: out of memory" in app.screen.text
            await pilot.press("escape")
    _run(go())


def _three_failed(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)
    return tui.PhyloApp(_cfg(), refresh_s=3600, start="hgs")


async def _tree_blocked(app, pilot):
    """Go to stage `tree` through the stages table; its filter `blocked` has 2 HGs."""
    app.load_now()
    await pilot.pause()
    app.query_one("#stages").focus()
    await pilot.press("down")
    await pilot.pause()
    assert app.stage == "tree"
    app.filter = "blocked"
    app._fill_hgs()
    app.query_one("#hgs").focus()
    await pilot.pause()
    vis = [r.hg for r in app.visible()]
    assert len(vis) == 2
    return vis


def test_space_down_space_selects_two_and_cursor_follows(cli, monkeypatch):
    app = _three_failed(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            vis = await _tree_blocked(app, pilot)
            await pilot.press("space", "down", "space")
            await pilot.pause()
            assert app.selected == set(vis)
            assert app._cursor_hg() == vis[1]           # space did not jump back to row 0
    _run(go())


def test_refresh_keeps_stage_selection_and_cursor(cli, monkeypatch):
    app = _three_failed(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            vis = await _tree_blocked(app, pilot)
            await pilot.press("space", "down")
            await pilot.pause()
            assert app.selected == {vis[0]} and app._cursor_hg() == vis[1]
            app.load_now()                              # what a background refresh does
            await pilot.pause()
            app.load_bg()                               # and the real threaded one
            await _settle(app, pilot)
            assert app.stage == "tree"
            assert app.selected == {vis[0]} and app._cursor_hg() == vis[1]
            assert app.query_one("#stages").cursor_row == core.STAGES.index("tree")
    _run(go())


def test_key_presses_run_no_slurm(cli, monkeypatch):
    app = _three_failed(cli, monkeypatch)
    from phylocli import model

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            calls = []
            monkeypatch.setattr(model, "_slurm", lambda cmd: calls.append(cmd) or (_ for _ in ()).throw(
                AssertionError("subprocess on the UI thread")))
            await pilot.press("f", "f", "down", "up", "space", "a")
            app.query_one("#stages").focus()
            await pilot.press("down", "down", "up")
            await pilot.pause()
            assert calls == []
    _run(go())


def test_second_enter_while_busy_is_ignored(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    from phylocli import model

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a", "r")
            await pilot.pause()
            scr = app.screen
            n = []
            orig = scr._build

            def counted(*a, **k):
                n.append(1)
                time.sleep(0.5)                         # keep the worker in flight
                return orig(*a, **k)
            monkeypatch.setattr(scr, "_build", counted)
            await pilot.press("enter", "enter", "enter")
            assert "working" in scr._shown
            await _settle(app, pilot)
            assert len(n) == 1 and "dry run" in scr._shown
    _run(go())


# ---- final-review fix wave -----------------------------------------------------------------

def _slow_build(scr, monkeypatch, secs=0.5):
    orig = scr._build

    def slow(*a, **k):
        time.sleep(secs)
        return orig(*a, **k)
    monkeypatch.setattr(scr, "_build", slow)


async def _open_dialog(app, pilot):
    app.load_now()
    await pilot.pause()
    await pilot.press("a", "r")
    await pilot.pause()
    assert isinstance(app.screen, tui.ResubmitScreen)
    return app.screen


def test_edit_during_dry_run_is_not_submitted(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    n0 = len(_calls())

    async def go():
        async with app.run_test() as pilot:
            scr = await _open_dialog(app, pilot)
            _slow_build(scr, monkeypatch)
            await pilot.press("enter")
            scr.query_one("#mem-0").value = "64G"           # edited while the dry run is in flight
            await _settle(app, pilot)
            await pilot.press("y")
            await _settle(app, pilot)
            assert scr.submitted == [] and "values changed" in scr._shown
            assert len(_calls()) == n0
    _run(go())


def test_no_duplicate_submit_from_same_dialog(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            scr = await _open_dialog(app, pilot)
            await pilot.press("enter")
            await _settle(app, pilot)
            n0 = len(_calls())
            await pilot.press("y")
            await _settle(app, pilot)
            assert scr.submitted == ["12345"] and len(_calls()) == n0 + 1
            await pilot.press("enter", "y")
            await _settle(app, pilot)
            assert len(_calls()) == n0 + 1 and scr.submitted == ["12345"]
            assert "already submitted" in scr._shown and "12345" in scr._shown
    _run(go())


def test_load_error_does_not_kill_app(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    from phylocli import history

    def boom(*a, **k):
        raise OSError("Stale file handle")
    monkeypatch.setattr(history, "attempts", boom)

    async def go():
        async with app.run_test() as pilot:
            await _settle(app, pilot)
            assert app.is_running
            assert any("Stale file handle" in n.message for n in app._notifications)
    _run(go())


def test_write_run_error_shown_in_dialog(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    from phylocli import model

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(model, "write_run", boom)

    async def go():
        async with app.run_test() as pilot:
            scr = await _open_dialog(app, pilot)
            await pilot.press("enter")
            await _settle(app, pilot)
            await pilot.press("y")
            await _settle(app, pilot)
            assert app.is_running and isinstance(app.screen, tui.ResubmitScreen)
            assert "disk full" in scr._shown and not scr._busy
    _run(go())


def test_error_after_sbatch_keeps_submitted_ids(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    from phylocli import model

    def half(w, submitted=None):
        submitted.append("777")
        raise OSError("jobs.tsv not writable")
    monkeypatch.setattr(model, "sbatch_all", half)

    async def go():
        async with app.run_test() as pilot:
            scr = await _open_dialog(app, pilot)
            await pilot.press("enter")
            await _settle(app, pilot)
            await pilot.press("y")
            await _settle(app, pilot)
            assert scr.submitted == ["777"]
            assert "777" in scr._shown and "jobs.tsv not writable" in scr._shown
    _run(go())


def test_escape_during_submit_waits_for_result(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            scr = await _open_dialog(app, pilot)
            await pilot.press("enter")
            await _settle(app, pilot)
            _slow_build(scr, monkeypatch)
            await pilot.press("y", "escape")
            assert isinstance(app.screen, tui.ResubmitScreen)       # not dismissed mid-flight
            await _settle(app, pilot)
            assert isinstance(app.screen, tui.ResubmitScreen)
            assert scr.submitted == ["12345"] and "12345" in scr._shown
    _run(go())


def test_no_fasta_reads_after_load(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            await _settle(app, pilot)
            app.load_now()
            await pilot.pause()
            calls = []
            monkeypatch.setattr(core, "nseq", lambda cfg, hg: calls.append(hg) or 0)
            await pilot.press("f", "f", "f", "f", "down", "up", "space", "a", "f", "f")
            await pilot.press("r")
            await pilot.pause()
            assert isinstance(app.screen, tui.ResubmitScreen)
            assert calls == []
            assert app.nseq["tfs.C_x.HG1"] == 600                    # filled by the load
    _run(go())


def test_resource_groups_with_nseq_reads_no_fasta(cli, monkeypatch):
    _failed_app(cli, monkeypatch)
    from phylocli import model
    rows = [r for r in model.hg_rows(_cfg(), "tree") if r.hg == "tfs.C_x.HG1"]
    calls = []
    monkeypatch.setattr(core, "nseq", lambda cfg, hg: calls.append(hg) or 0)
    groups = tui.resource_groups(_cfg(), "tree", rows, {"tfs.C_x.HG1": 600})
    assert calls == [] and groups[0][1].qos == "long"


def test_superseded_refresh_is_not_applied(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            await _settle(app, pilot)
            real, applied, n = app._collect, [], []

            def collect():
                n.append(1)
                if len(n) == 1:
                    time.sleep(0.6)                                   # the first one is slow
                return real()
            monkeypatch.setattr(app, "_collect", collect)
            orig_apply = app._apply
            monkeypatch.setattr(app, "_apply", lambda snap: applied.append(1) or orig_apply(snap))
            app.load_bg()
            await asyncio.sleep(0.2)
            app.load_bg()                                             # cancels the first
            await asyncio.sleep(1.0)                                  # past the slow one's end
            await pilot.pause()
            assert len(n) == 2 and applied == [1]
    _run(go())


def test_finished_hg_leaves_selection_on_refresh(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a")
            assert app.selected == {"tfs.C_x.HG1"}
            out = core.load_config(os.environ["PHYLOCLI_CONFIG"]).outdir
            (out / "align" / "tfs.C_x.HG1.aln.fasta").write_text(">a\nAA\n")
            app.load_now()
            await pilot.pause()
            assert app.selected == set()
    _run(go())


def test_submit_result_shows_notes_and_uses_given_raw(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    raw = tui.load_raw()
    raw["marker_key"] = "from-the-command"
    app = tui.PhyloApp(_cfg(), refresh_s=3600, raw=raw, start="hgs")

    async def go():
        async with app.run_test() as pilot:
            scr = await _open_dialog(app, pilot)
            await pilot.press("enter")
            await _settle(app, pilot)
            await pilot.press("y")
            await _settle(app, pilot)
            assert "12345" in scr._shown and "resources.tsv: row found" in scr._shown
    _run(go())
    run = sorted((_state["runs"]).glob("*_align*"))[-1]
    assert "marker_key: from-the-command" in (run / "config.yaml").read_text()


def _counting_attempts(monkeypatch):
    from phylocli import history
    calls = {"n": 0}
    real = history.attempts

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(history, "attempts", counted)
    real_f = history.family_attempts

    def counted_f(*a, **k):
        calls["n"] += 1
        return real_f(*a, **k)
    monkeypatch.setattr(history, "family_attempts", counted_f)
    return calls


def test_overview_is_first_and_reads_no_history(cli, monkeypatch):
    calls = _counting_attempts(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert app.view == "overview"
            assert [r.group for r in app.ov_rows] == ["ALL", "tfs", "cal", "slc"]
            exp = core.expected(_cfg())
            srows, _k, _d = tui.model.stage_rows(_cfg(), exp)
            a = next(s for s in srows if s.stage == "align")
            assert app.ov_rows[0].per_stage["align"] == (a.done, a.running, a.ready, a.blocked)
    _run(go())
    assert calls["n"] == 0


def test_overview_family_toggle(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()
            assert app.by == "family" and [r.group for r in app.ov_rows] == ["ALL", "tfs.A", "tfs.C_x", "cal.Trail", "slc.NEW", "tfs.B"]
            await pilot.press("c")
            await pilot.pause()
            assert app.by == "category"
    _run(go())


def test_open_group_restricts_hgs_and_esc_returns(cli, monkeypatch):
    calls = _counting_attempts(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()
            col0 = tui.ov_column("tree")                            # tfs.A x tree (= 3 before step1)
            app.query_one("#overview").move_cursor(row=1, column=col0)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.view == "hgs" and app.group == "tfs.A"
            app.load_now()
            await pilot.pause()
            assert calls["n"] >= 1
            app.filter = "done"
            app._fill_hgs()
            assert {r.hg for r in app.visible()} <= {"tfs.A.HG1", "tfs.A.HG11"}
            app.filter = "ready"
            app._fill_hgs()
            assert "tfs.C_x.HG1" not in {r.hg for r in app.visible()}
            await pilot.press("f")                                   # HG view: f = cycle filter
            assert app.view == "hgs" and app.by == "family"
            await pilot.press("escape")
            await pilot.pause()
            assert app.view == "overview"
            assert app.query_one("#overview").cursor_row == 1
            assert app.query_one("#overview").cursor_column == col0
    _run(go())


def test_enter_on_stage_cell_opens_that_stage_with_failed_filter(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            ov = app.query_one("#overview")
            ov.move_cursor(row=0, column=tui.ov_column("align"))   # ALL x align
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            assert app.view == "hgs" and app.stage == "align" and app.filter == "actionable"
            assert app.focused is app.query_one("#hgs")
            await pilot.press("f")                                         # actionable -> failed
            assert app.filter == "failed"
            assert [r.hg for r in app.visible()] == ["tfs.C_x.HG1"]
            await pilot.press("space", "r")                                # select and resubmit
            await pilot.pause()
            assert isinstance(app.screen, tui.ResubmitScreen)
    _run(go())


def test_refresh_in_hg_view_stays_in_group(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.open_group("tfs")
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            assert app.view == "hgs" and app.group == "tfs"
            assert {r.hg for r in app.visible()} <= {"tfs.A.HG1", "tfs.A.HG11", "tfs.C_x.HG1"}
            app.filter = "ready"
            app._fill_hgs()
            assert all(tui.model.group_key(r.hg, "category") == "tfs" for r in app.visible())
    _run(go())


def test_open_group_before_hg_data_shows_loading(cli, monkeypatch):
    import threading
    from phylocli import history
    gate = threading.Event()
    real = history.attempts

    def slow(*a, **k):
        gate.wait(10)
        return real(*a, **k)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            monkeypatch.setattr(history, "attempts", slow)
            app.by_stage = {}                       # no HG-view snapshot yet
            app.open_group("tfs")
            await pilot.pause()
            assert app.visible() == []
            assert "loading history" in app._banner_text
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "loading history" not in app._banner_text
            assert app.by_stage
    _run(go())


def test_stages_panel_shows_group_counts(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()
            app.open_group("tfs.A")
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            rows = {r.group: r for r in app.ov_rows}
            t = app.query_one("#stages")
            i = tui.TUI_STAGES.index("align")
            cells = [str(t.get_cell_at((i, c))) for c in range(1, 6)]
            c = rows["tfs.A"].per_stage["align"]
            assert cells == [str(c[0]), str(c[1]), str(c[2]), str(c[3]), str(rows["tfs.A"].total)]
            assert rows["tfs.A"].total != rows["ALL"].total
    _run(go())


def test_regroup_is_in_memory(cli, monkeypatch):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()

            def boom(*a, **k):
                raise AssertionError("ready_set called on regroup")
            monkeypatch.setattr(core, "ready_set", boom)
            await pilot.press("f")
            await pilot.pause()
            assert [r.group for r in app.ov_rows] == ["ALL", "tfs.A", "tfs.C_x", "cal.Trail", "slc.NEW", "tfs.B"]
            await pilot.press("c")
            await pilot.pause()
            assert [r.group for r in app.ov_rows] == ["ALL", "tfs", "cal", "slc"]
    _run(go())


def test_footer_keys_follow_view(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert app.check_action("by_category", ()) and not app.check_action("back", ())
            assert not app.check_action("resubmit", ())
            app.open_group("tfs")
            await pilot.pause()
            assert app.check_action("back", ()) and app.check_action("resubmit", ())
            assert not app.check_action("by_category", ())
    _run(go())


def test_open_group_with_failures_opens_on_failed(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.open_group("ALL", "align")
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            assert app.filter == "actionable" and app.visible()
    _run(go())


def test_open_group_without_failures_picks_first_nonempty_filter(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            ov = app.query_one("#overview")
            ov.move_cursor(row=0, column=tui.ov_column("align"))   # ALL x align
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            assert app.view == "hgs" and app.stage == "align"
            assert app.filter == "actionable" and app.visible()
    _run(go())


def test_default_filter_shows_failed_and_ready_then_f_goes_to_failed(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600, start="hgs")
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert tui.FILTERS[0] == "actionable" and app.filter == "actionable"
            assert {r.hg: r.state for r in app.visible()} == {
                "tfs.C_x.HG1": "failed", "tfs.A.HG11": "ready"}
            await pilot.press("f")
            assert app.filter == "failed"
            assert [r.hg for r in app.visible()] == ["tfs.C_x.HG1"]
    _run(go())


def test_f_while_history_loading_keeps_user_filter(cli, monkeypatch):
    import threading
    from phylocli import history
    gate = threading.Event()
    real = history.attempts

    def slow(*a, **k):
        gate.wait(10)
        return real(*a, **k)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            monkeypatch.setattr(history, "attempts", slow)
            app.by_stage = {}
            app.open_group("ALL", "align")
            await pilot.pause()
            assert app._auto_filter and app.filter == "actionable"
            await pilot.press("f")                          # actionable -> failed, by hand
            assert app.filter == "failed" and not app._auto_filter
            await pilot.press("f", "f")                     # failed -> ready -> running
            user = app.filter
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.by_stage and app.filter == user == "running"
    _run(go())


def test_tui_command_runs_without_mouse(cli, monkeypatch):
    seen = {}
    monkeypatch.setattr(tui.PhyloApp, "run", lambda self, **kw: seen.update(kw))
    assert cli(["tui"]).exit_code == 0
    assert seen.get("mouse") is False


@pytest.mark.parametrize("how", ["quit", "ctrl-c", "crash"])
def test_tui_command_resets_terminal_on_exit(cli, monkeypatch, how):
    from phylocli import phylo

    def run(self, **kw):
        if how == "ctrl-c":
            raise KeyboardInterrupt
        if how == "crash":
            raise RuntimeError("boom")
    monkeypatch.setattr(tui.PhyloApp, "run", run)
    r = cli(["tui"])
    assert r.output.endswith(phylo.TERM_RESET)
    assert (r.exit_code == 0) == (how == "quit")


def test_active_pane_border_is_orange(cli):
    from textual.color import Color

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600, start="hgs")
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            for pane in ("#stages", "#hgs", "#arrays"):
                app.query_one(pane).focus()
                await pilot.pause()
                for other in ("#stages", "#hgs", "#arrays"):
                    colour = app.query_one(other).styles.border.top[1]
                    assert (colour == Color.parse("orange")) == (other == pane), (pane, other)
    _run(go())


def test_edit_value_enter_then_y_submits(cli, monkeypatch):
    """Typing a value, enter (dry run), then y must submit: a focused Input used to swallow
    the y as text, replacing the value and voiding the dry run."""
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)
    n0 = len(_calls())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600, start="hgs")
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("a", "r")
            await pilot.pause()
            scr = app.screen
            inp = scr.query_one("#mem-0")
            inp.focus()
            await pilot.pause()
            inp.value = ""
            await pilot.press("2", "G", "enter")
            await _settle(app, pilot)
            assert "dry run" in scr._shown
            await pilot.press("y")
            await _settle(app, pilot)
            assert scr.submitted and set(scr.submitted) == {"12345"}, scr._shown
            assert scr.query_one("#mem-0").value == "2G"
            n_arrays = len(scr.submitted)
            return n_arrays
    n_arrays = asyncio.run(go())
    assert len(_calls()) == n0 + n_arrays


def test_panes_are_named_top_left(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600, start="hgs")
        async with app.run_test() as pilot:
            await pilot.pause()
            for wid, title in tui.PANE_TITLES.items():
                w = app.query_one(wid)
                assert w.border_title == title
                assert w.styles.border_title_align == "left"
    _run(go())


def test_panels_grey_while_history_loads(cli, monkeypatch):
    import threading
    from phylocli import history
    gate = threading.Event()
    real = history.attempts

    def slow(*a, **k):
        gate.wait(10)
        return real(*a, **k)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            monkeypatch.setattr(history, "attempts", slow)
            app.by_stage = {}
            app.open_group("tfs")
            await pilot.pause()
            hv = app.query_one("#hgview")
            assert hv.has_class("loading") and hv.styles.opacity < 1
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not hv.has_class("loading") and hv.styles.opacity == 1
    _run(go())


def test_hg_rows_family_ids_from_caller_and_guarded_fallback(cli, monkeypatch):
    cfg = _cfg()
    fams = core.family_ids(cfg)
    assert fams
    calls = {"n": 0}
    real = core.family_ids

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(core, "family_ids", counted)
    rows = tui.model.hg_rows(cfg, "search", fams=fams)
    assert calls["n"] == 0 and {r.hg for r in rows} == fams      # no second parse of the file

    def boom(*a, **k):
        raise OSError("unreadable genefam")
    monkeypatch.setattr(core, "family_ids", boom)
    assert tui.model.hg_rows(cfg, "search") == []                # fallback is guarded


def test_unreadable_genefam_does_not_fail_hg_view_collect(cli, monkeypatch):
    def boom(*a, **k):
        raise OSError("unreadable genefam")
    monkeypatch.setattr(core, "family_ids", boom)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600, start="hgs")
        async with app.run_test() as pilot:
            app.load_now()                                       # raised before the fix
            await pilot.pause()
            assert app.by_stage["align"]
            assert app.by_stage["search"] == []
            assert "unreadable genefam" in app._banner_text
    _run(go())


def test_hg_view_headers_follow_the_unit(cli):
    def heads(app, wid):
        return [str(c.label) for c in app.query_one(wid).columns.values()]

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.open_group("ALL", "search")
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            assert heads(app, "#hgs")[1:3] == ["family", "HGs"]
            assert "ids" in heads(app, "#arrays")
            app.open_group("ALL", "align")
            await pilot.pause()
            assert heads(app, "#hgs")[1:3] == ["HG", "seqs"]
            assert "ids" in heads(app, "#arrays") and "HGs" not in heads(app, "#arrays")
    _run(go())
