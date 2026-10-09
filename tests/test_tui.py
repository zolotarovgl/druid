"""phylocli/tui.py (Textual pilot tests; skipped when Textual is not installed)."""
import asyncio
import os
import re
import time

import pytest

pytest.importorskip("textual")

from phylocli import core, tui  # noqa: E402
from phylocli.tests.test_cli import _state, cli  # noqa: E402,F401
from phylocli.tests.test_model import OG_HEAD, write_results  # noqa: E402

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
            # a successful submit closes the dialog (and the app refreshes), so the same
            # dialog can no longer be re-run: enter / y now reach the HG list, not a submit
            assert not isinstance(app.screen, tui.ResubmitScreen)
            await pilot.press("enter", "y")
            await _settle(app, pilot)
            assert len(_calls()) == n0 + 1 and scr.submitted == ["12345"]
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
            # the submit finished: the dialog closed on success (not because of the escape)
            # and the job id is in the notification
            assert not isinstance(app.screen, tui.ResubmitScreen)
            assert scr.submitted == ["12345"]
            assert any("12345" in str(n.message) for n in app._notifications)
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
            msgs = [str(n.message) for n in app._notifications]
            assert any("12345" in m and "resources.tsv: row found" in m for m in msgs), msgs
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
            n_arrays = len(scr.submitted)
            return n_arrays
    n_arrays = asyncio.run(go())
    assert len(_calls()) == n0 + n_arrays
    # the typed 2G (not a y-overwritten value) reached the submitted script
    scripts = [p.read_text() for p in _state["runs"].glob("*_align*/array_*.sbatch")]
    assert any("--mem=2048M" in s for s in scripts)


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


def test_successful_submit_closes_dialog_and_refreshes(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    loads = {"n": 0}
    real = tui.PhyloApp.load_bg

    async def go():
        async with app.run_test() as pilot:
            scr = await _open_dialog(app, pilot)
            monkeypatch.setattr(app, "load_bg", lambda: (loads.__setitem__("n", loads["n"] + 1), real(app)))
            await pilot.press("enter")
            await _settle(app, pilot)
            await pilot.press("y")
            await _settle(app, pilot)
            assert not isinstance(app.screen, tui.ResubmitScreen)
            assert loads["n"] >= 1                      # the app refreshed after the submit
            assert app.selected == set()
            assert any("12345" in str(n.message) for n in app._notifications)
    _run(go())


def test_partial_sbatch_failure_keeps_dialog_open(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    from phylocli import model

    def half(w, submitted=None):
        submitted = submitted if submitted is not None else []
        submitted.append("12345")
        return submitted, "sbatch failed for array_1.sbatch: boom"
    monkeypatch.setattr(model, "sbatch_all", half)

    async def go():
        async with app.run_test() as pilot:
            scr = await _open_dialog(app, pilot)
            await pilot.press("enter")
            await _settle(app, pilot)
            await pilot.press("y")
            await _settle(app, pilot)
            assert isinstance(app.screen, tui.ResubmitScreen)
            assert "boom" in scr._shown and scr.submitted == ["12345"]
    _run(go())


# ---- Results window ---------------------------------------------------------------------------
def _ov_row(app, group):
    return [r.group for r in app.ov_rows].index(group)


async def _press(pilot, *keys):
    for k in keys:
        await pilot.press(k)
        await pilot.pause()


async def _open_results(app, pilot, group, family=False):
    """Overview -> cursor on `group` -> o -> wait for the Results load."""
    app.load_now()
    await pilot.pause()
    if family:
        await _press(pilot, "f")
    app.query_one("#overview").move_cursor(row=_ov_row(app, group), column=2)
    await pilot.pause()
    await pilot.press("o")
    await app.workers.wait_for_complete()
    await pilot.pause()


def _cells(app, table, row):
    t = app.query_one(table)
    return [str(t.get_cell_at((row, c))) for c in range(len(t.columns))]


def _member_genes(app):
    t = app.query_one("#members")
    return [str(t.get_cell_at((i, 0))) for i in range(t.row_count)]


def test_o_on_overview_opens_results_for_that_group(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert app.view == "results" and app.focused is app.query_one("#res")
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]   # C_x: no output
            assert app.res_missing == 1 and "1 HG without output" in app._res_foot
            assert app.query_one("#res").border_title == "Results · tfs"
            assert _cells(app, "#res", 0) == ["tfs.A.HG1", "2", "5", "1"]
            assert app.query_one("#ogs").border_title == "OGs · tfs.A.HG1 · possvm"
            assert _cells(app, "#ogs", 0) == ["HG1.0", "3", "2", "78.4", "98.2/98.2", "T/Tbx19",
                                              "T/Tbx19"]
            assert _cells(app, "#ogs", 1)[3] == "0.0 ⚠"
            assert app.query_one("#members").border_title == "members · HG1.0 T/Tbx19"
            assert _cells(app, "#members", 2) == ["Hsap_ENSP1", "Hsap", "T/Tbx19", "98.2/98.2"]
            assert app.query_one("#species_box").border_title == "species · HG1.0"
            assert app._species_text.splitlines() == [
                "Ctenophora  1/2 spp  2 genes", "  Mlei 2",
                "Chordata    1/1 spp  1 gene", "  Hsap 1",
                "absent: unknown"]
            assert "2 OGs · possvm · ⚠ = support 0 (GeneRax bug case; check possvm_prev)" \
                in app._res_foot
    _run(go())


def test_o_on_hg_highlights_it_and_esc_returns_to_hg_view(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.open_group("tfs", "align")
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            vis = [r.hg for r in app.visible()]
            assert "tfs.A.HG11" in vis
            app.query_one("#hgs").move_cursor(row=vis.index("tfs.A.HG11"))
            await pilot.pause()
            await pilot.press("o")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and app.res_group == "tfs"
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG11"
            assert app.query_one("#ogs").border_title == "OGs · tfs.A.HG11 · possvm"
            assert (_cells(app, "#ogs", 0)[0], _cells(app, "#ogs", 0)[6]) == ("HG11.0", "Tbx20")
            await _press(pilot, "escape")
            assert app.view == "hgs" and app._cursor_hg() == "tfs.A.HG11"
            assert app.focused is app.query_one("#hgs")
    _run(go())


def test_o_on_family_row_opens_results_for_its_hgs(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.open_group("ALL", "search")                        # rows are families here
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            vis = [r.hg for r in app.visible()]
            assert "tfs.A" in vis                                  # no search output: ready
            app.query_one("#hgs").move_cursor(row=vis.index("tfs.A"))
            await pilot.pause()
            await pilot.press("o")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and app.res_group == "tfs.A"
            assert app.res_hgs == ["tfs.A.HG1", "tfs.A.HG11"]
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
            assert app.query_one("#res").border_title == "Results · tfs.A"
            await _press(pilot, "escape")
            assert app.view == "hgs" and app.stage == "search" and app._cursor_hg() == "tfs.A"
    _run(go())


def test_results_cursor_moves_update_panes_without_file_reads(cli, monkeypatch):
    write_results(_cfg())

    def boom(*a, **k):
        raise AssertionError("file read on a key press")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            for name in ("read_ogs", "group_ogs", "species_universe", "phyla"):
                monkeypatch.setattr(tui.model, name, boom)
            monkeypatch.setattr(core.report_status, "nonempty_files", boom)
            await _press(pilot, "down")                            # Results: tfs.A.HG11
            assert app.query_one("#ogs").border_title == "OGs · tfs.A.HG11 · possvm"
            assert _member_genes(app) == ["Bova_x1", "Mlei_v05_G9"]
            assert app._species_text.splitlines()[:2] == ["Ctenophora  2/2 spp  2 genes",
                                                          "  Bova 1 · Mlei 1"]
            await _press(pilot, "up", "tab")                       # back to HG1, into OGs
            assert app.focused is app.query_one("#ogs")
            await _press(pilot, "down")                            # OG HG1.1: Hsap + Nvec
            assert app.query_one("#members").border_title == "members · HG1.1 like:Eomes/Tbr1"
            assert _member_genes(app) == ["Hsap_ENSP2", "Nvec_v1_g3"]
            assert app._species_text.splitlines() == [
                "Chordata  1/1 spp  1 gene", "  Hsap 1",
                "unknown   1/1 spp  1 gene", "  Nvec 1",
                "absent: Ctenophora"]
    _run(go())


def test_slash_filters_members_and_esc_clears(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert len(_member_genes(app)) == 3
            inp = app.query_one("#memfilter")
            assert not inp.display
            await _press(pilot, "slash")
            assert inp.display and app.focused is inp
            await _press(pilot, "h", "s", "a", "p")               # `p` is text here, not a switch
            assert app.res_source == "possvm" and inp.value == "hsap"
            assert _member_genes(app) == ["Hsap_ENSP1"]
            await _press(pilot, "escape")                          # clears; stays in Results
            assert app.view == "results" and not inp.display and inp.value == ""
            assert len(_member_genes(app)) == 3 and app.focused is app.query_one("#members")
            await _press(pilot, "slash", "M", "L", "E", "I", "enter")   # case-insensitive; enter keeps
            assert app.focused is app.query_one("#members")
            assert _member_genes(app) == ["Mlei_v05_G1", "Mlei_v05_G2"]
            await _press(pilot, "escape", "escape")
            assert app.view == "overview"
    _run(go())


def test_p_switches_source_and_recomputes_results(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
            await pilot.press("p")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_source == "possvm_prev"
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1"] and app.res_missing == 2
            assert app.query_one("#ogs").border_title == "OGs · tfs.A.HG1 · possvm_prev"
            assert (_cells(app, "#ogs", 0)[0], _cells(app, "#ogs", 0)[6]) == ("HG1.0", "like:Tbx2/Tbx3")
            assert app._species_text.splitlines() == [
                "Ctenophora  1/2 spp  1 gene", "  Mlei 1",
                "absent: Chordata, unknown",
                "not in species tree: Zzz 1"]
            await pilot.press("p")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_source == "possvm" and len(app.res_rows) == 2
    _run(go())


def test_esc_from_results_returns_to_overview_cursor_kept(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _press(pilot, "f")
            ov = app.query_one("#overview")
            ov.move_cursor(row=_ov_row(app, "tfs.C_x"), column=3)
            await pilot.pause()
            await pilot.press("o")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and app.res_group == "tfs.C_x"
            await _press(pilot, "escape")
            assert app.view == "overview" and app.focused is ov
            assert (ov.cursor_row, ov.cursor_column) == (_ov_row(app, "tfs.C_x"), 3)
    _run(go())


def test_results_without_output_says_so_and_p_still_works(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs.C_x", family=True)
            assert app.res_rows == []
            assert "no ortholog groups yet (possvm not done)" in app._res_foot
            assert app._species_text == "no ortholog groups yet (possvm not done)"
            await pilot.press("p")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_source == "possvm_prev"
            assert "no ortholog groups yet (possvm_prev not done)" in app._res_foot
    _run(go())


def test_results_read_in_worker_shows_loading(cli, monkeypatch):
    import threading
    write_results(_cfg())
    gate = threading.Event()
    on_main = []
    real = tui.model.read_ogs

    def slow(*a, **k):
        on_main.append(threading.current_thread() is threading.main_thread())
        gate.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(tui.model, "read_ogs", slow)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("o")                                 # cursor on ALL
            await pilot.pause()
            assert app.view == "results" and app.res_group == "ALL"
            assert app.query_one("#resv").has_class("loading")
            assert "loading…" in app._res_foot and app.res_rows == []
            app.load_bg()                                          # a periodic refresh meanwhile
            await pilot.pause()
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not app.query_one("#resv").has_class("loading")
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
    _run(go())
    assert on_main and not any(on_main)


def test_results_bad_row_is_shown_not_a_crash(cli):
    write_results(_cfg())
    p = _cfg().outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv"
    p.write_text(OG_HEAD + "broken row\n")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
            assert _cells(app, "#res", 1) == ["tfs.A.HG11", "–", "–", "!"]
            await _press(pilot, "down")
            assert f"{p}:2:" in app._species_text and f"{p}:2:" in app._res_foot
            assert app.query_one("#ogs").row_count == 0 and _member_genes(app) == []
    _run(go())


def test_results_without_species_files_still_lists_ogs(cli):
    from pathlib import Path
    write_results(_cfg())
    tree = Path(_cfg().params["SPECIES_TREE"])
    info = tui.model.species_info_path(_cfg())
    tree.unlink()
    info.unlink()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert (_cells(app, "#ogs", 0)[0], _cells(app, "#ogs", 0)[6]) == ("HG1.0", "T/Tbx19")
            assert len(_member_genes(app)) == 3
            lines = app._species_text.splitlines()
            assert lines[0].startswith(f"species tree {tree}: ")
            assert f"{info}: " in lines[0] and "phyla shown as unknown" in lines[0]
            assert lines[-1] == "not in species tree: Mlei 2, Hsap 1"
    _run(go())


def test_results_tab_cycles_four_panes_with_orange_border(cli):
    from textual.color import Color
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            panes = ("#res", "#ogs", "#members", "#species_box")
            for pane in panes:
                assert app.focused is app.query_one(pane)
                for other in panes:
                    colour = app.query_one(other).styles.border.top[1]
                    assert (colour == Color.parse("orange")) == (other == pane), (pane, other)
                await _press(pilot, "tab")
            assert app.focused is app.query_one("#res")             # wraps around
            await _press(pilot, "shift+tab")
            assert app.focused is app.query_one("#species_box")
    _run(go())


def test_footer_keys_in_results(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert app.check_action("open_results", ())
            assert not app.check_action("toggle_source", ()) and not app.check_action("member_filter", ())
            await _open_results(app, pilot, "tfs")
            for a in ("toggle_source", "member_filter", "back"):
                assert app.check_action(a, ()), a
            for a in ("open_results", "resubmit", "toggle", "select_all", "log", "by_category",
                      "cycle_filter"):
                assert not app.check_action(a, ()), a
    _run(go())


def test_late_result_of_previous_group_is_dropped(cli, monkeypatch):
    import threading
    write_results(_cfg())
    gate = threading.Event()
    real = tui.model.group_ogs

    def slow(cfg, hgs, source, **kw):
        if list(hgs) == ["tfs.C_x.HG1"]:                         # the first open: family tfs.C_x
            gate.wait(10)
        return real(cfg, hgs, source, **kw)
    monkeypatch.setattr(tui.model, "group_ogs", slow)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _press(pilot, "f")
            ov = app.query_one("#overview")
            ov.move_cursor(row=_ov_row(app, "tfs.C_x"))
            await pilot.pause()
            await _press(pilot, "o", "escape")                     # first load blocked in the worker
            ov.move_cursor(row=_ov_row(app, "tfs.A"))
            await pilot.pause()
            await _press(pilot, "o")
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_group == "tfs.A"
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
    _run(go())


# ---- Results window: fix round 2 --------------------------------------------------------------
def test_esc_cancels_results_worker(cli, monkeypatch):
    import threading
    write_results(_cfg())
    gate = threading.Event()
    reads = []
    real = tui.model.read_ogs

    def counting(*a, **k):
        reads.append(a[1])
        if len(reads) == 1:
            gate.wait(10)                                      # blocked after the first file
        return real(*a, **k)
    monkeypatch.setattr(tui.model, "read_ogs", counting)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("o")                             # ALL: 3 HGs
            await pilot.pause()
            await _press(pilot, "escape")
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "overview"
    _run(go())
    assert 1 <= len(reads) <= 2


# ---- Results window: fix round 1 --------------------------------------------------------------
def test_long_og_name_truncated_and_support_visible(cli):
    write_results(_cfg())
    name = "like:" + "/".join(f"Gene{i}" for i in range(20))             # > 90 chars
    assert len(name) > 90
    p = _cfg().outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv"
    p.write_text(OG_HEAD + f"Bova_x1\ttfs.A.HG11.0:{name}\t0.0\t{name}\t90.0\n")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test(size=(150, 40)) as pilot:
            await _open_results(app, pilot, "tfs")
            await _press(pilot, "down")
            cells = _cells(app, "#ogs", 0)
            assert cells[3] == "0.0 ⚠" and cells[6] == name[:24] + "…" and cells[5] == name[:24] + "…"
            t = app.query_one("#ogs")
            head = sum(c.get_render_width(t) for c in list(t.columns.values())[:5])
            assert head <= t.size.width                  # OG, genes, spp, support, ref sup visible
            assert app.query_one("#members").border_title == f"members · HG11.0 {name}"
    _run(go())


def test_species_lines_wrap_long_species_list():
    row = tui.model.PhylumRow("Ctenophora", 30, 30, 30, [(f"Sp{i:02d}", 1) for i in range(30)])
    lines = tui.species_lines([row], [], width=40)
    assert lines[0].startswith("Ctenophora  30/30 spp  30 genes")
    body = lines[1:]
    assert len(body) > 2 and all(l.startswith("  ") and len(l) <= 40 for l in body)
    assert " · ".join(x.strip() for x in body).count("Sp") == 30


def test_results_subtitle_and_escape_label(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert app.sub_title == "Results · tfs · possvm"
            app.load_bg()                                      # a refresh must not overwrite it
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.sub_title == "Results · tfs · possvm"
            await pilot.press("p")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.sub_title == "Results · tfs · possvm_prev"
            assert next(b for b in app.BINDINGS if b.key == "escape").description == "back"
            await _press(pilot, "escape")
            await app.workers.wait_for_complete()
            assert not app.sub_title.startswith("Results")
    _run(go())


def test_esc_from_results_reloads_hg_view(cli, monkeypatch):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            calls = []
            monkeypatch.setattr(app, "load_bg", lambda: calls.append(1))
            await _press(pilot, "escape")
            assert calls == [1]
    _run(go())


def test_results_load_posts_progress_and_stops_when_cancelled(cli):
    write_results(_cfg())
    cfg = _cfg()
    hgs = [f"tfs.A.HG{i}" for i in range(1, 121)]
    seen = []
    rows, missing = tui.model.group_ogs(cfg, hgs, "possvm", progress=lambda k, n: seen.append((k, n)))
    assert seen[0] == (0, 120) and seen[-1] == (119, 120) and len(seen) == 120
    assert len(rows) == 2 and missing == 118
    stop = []
    rows2, _ = tui.model.group_ogs(cfg, hgs, "possvm", progress=lambda k, n: stop.append(k),
                                   cancelled=lambda: len(stop) >= 3)
    assert stop == [0, 1, 2]

    async def go():
        app = tui.PhyloApp(cfg, refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app._res_gen = 5
            app.query_one("#resv").add_class("loading")
            app._res_progress(5, 100, 1915)
            assert "loading 100/1915…" in app._res_foot
            app._res_progress(4, 150, 1915)                    # stale generation: ignored
            assert "150/1915" not in app._res_foot
    _run(go())


# ---- overview sort / hide ---------------------------------------------------------------------
def _sorted_fixture():
    """tfs.C_x.HG1 gets its alignment: at `tree` tfs.C_x has 1 ready, tfs.A 0 (1 done,
    1 blocked); at `align` tfs.A has 1 ready, tfs.C_x is all done."""
    (_cfg().outdir / "align/tfs.C_x.HG1.aln.fasta").write_text(">s\nAA\n")


def _shown(app):
    return [r.group for r in app.ov_shown]


def _pair(app):
    """Order of the two fixture families among the shown rows (robust to extra groups)."""
    return [g for g in _shown(app) if g in ("tfs.A", "tfs.C_x")]


def _col(app, name):
    """Overview column of `name`: group 0, HGs 1, a stage through step1's ov_column."""
    return {"group": 0, "HGs": 1}.get(name) if name in ("group", "HGs") else tui.ov_column(name)


def _to_col(app, name, row=0):
    app.query_one("#overview").move_cursor(row=row, column=_col(app, name))


async def _family_overview(app, pilot):
    app.load_now()
    await pilot.pause()
    await pilot.press("f")
    await pilot.pause()


async def _key(pilot, *keys):
    for k in keys:
        await pilot.press(k)
        await pilot.pause()


def test_ov_order_ties_on_running_then_name_na_last():
    G = tui.model.GroupRow
    rows = [G("ALL", 9, {"tree": (0, 3, 3, 0)}),
            G("b", 3, {"tree": (0, 2, 1, 0)}), G("a", 3, {"tree": (0, 0, 1, 2)}),
            G("c", 2, {"tree": None}), G("d", 1, {"tree": (0, 2, 1, 0)})]

    def order(sort, hide=None):
        return [r.group for r in tui.ov_order(rows, sort, hide)]
    assert order(("tree", False)) == ["ALL", "b", "d", "a", "c"]
    assert order(("tree", True)) == ["ALL", "c", "a", "b", "d"]
    assert order(("HGs", False)) == ["ALL", "a", "b", "c", "d"]
    assert order(("HGs", True)) == ["ALL", "d", "c", "a", "b"]
    assert order(("group", True)) == ["ALL", "d", "c", "b", "a"]
    assert order(None, "tree") == ["ALL", "b", "a", "d"]
    assert order(None) == ["ALL", "b", "a", "c", "d"]


def test_s_sorts_by_stage_then_reverses(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            assert _pair(app) == ["tfs.A", "tfs.C_x"]
            _to_col(app, "tree")
            await _key(pilot, "s")
            assert _shown(app)[0] == "ALL" and _pair(app) == ["tfs.C_x", "tfs.A"]
            assert app.query_one("#overview").border_title == "Overview · sort: tree ▼"
            await _key(pilot, "s")
            assert _shown(app)[0] == "ALL" and _pair(app) == ["tfs.A", "tfs.C_x"]
            assert app.query_one("#overview").border_title == "Overview · sort: tree ▲"
    _run(go())


def test_s_on_group_and_hgs_columns(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            _to_col(app, "HGs")
            await _key(pilot, "s")
            assert _pair(app) == ["tfs.A", "tfs.C_x"]               # 2 HGs before 1
            await _key(pilot, "s")
            assert _pair(app) == ["tfs.C_x", "tfs.A"]
            _to_col(app, "group")
            await _key(pilot, "s")                                  # new column: fresh, by name
            assert _pair(app) == ["tfs.A", "tfs.C_x"]
            assert app.query_one("#overview").border_title == "Overview · sort: group ▼"
            await _key(pilot, "s")
            assert _pair(app) == ["tfs.C_x", "tfs.A"] and _shown(app)[0] == "ALL"
    _run(go())


def test_h_hides_rows_with_nothing_to_do_and_keeps_all(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            _to_col(app, "tree")
            await _key(pilot, "h")
            assert _shown(app)[0] == "ALL" and _pair(app) == ["tfs.C_x"]
            assert app.query_one("#overview").border_title == "Overview · only actionable at tree"
            assert "tfs.A" in [r.group for r in app.ov_rows]        # ov_rows untouched
            _to_col(app, "align")
            await _key(pilot, "h")                                  # another stage: switch
            assert _pair(app) == ["tfs.A"]
            await _key(pilot, "h")                                  # same stage: show all
            assert _pair(app) == ["tfs.A", "tfs.C_x"]
            assert app.query_one("#overview").border_title == "Overview"
            _to_col(app, "HGs")
            await _key(pilot, "h")                                  # not a stage column
            assert app.ov_hide is None and _pair(app) == ["tfs.A", "tfs.C_x"]
    _run(go())


def test_sort_and_hide_survive_refresh_and_regroup(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            _to_col(app, "tree")
            await _key(pilot, "s", "h")
            assert _pair(app) == ["tfs.C_x"]
            app.load_now()
            await pilot.pause()
            assert _pair(app) == ["tfs.C_x"]
            assert (app.ov_sort, app.ov_hide) == (("tree", False), "tree")
            await _key(pilot, "c")
            assert app.by == "category" and _shown(app)[0] == "ALL" and "tfs" in _shown(app)
            await _key(pilot, "f")
            assert _pair(app) == ["tfs.C_x"]
            assert app.query_one("#overview").border_title == \
                "Overview · sort: tree ▼ · only actionable at tree"
    _run(go())


def test_s_and_h_touch_no_files_or_slurm(cli, monkeypatch):
    _sorted_fixture()

    def boom(*a, **k):
        raise AssertionError("file or SLURM access on s/h")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            await app.workers.wait_for_complete()
            monkeypatch.setattr(core, "ready_set", boom)
            monkeypatch.setattr(core.report_status, "done_by_stage", boom)
            monkeypatch.setattr(tui.model, "_slurm", boom)
            assert app.check_action("sort", ()) and app.check_action("hide", ())
            _to_col(app, "tree")
            await _key(pilot, "s", "h")
            assert _pair(app) == ["tfs.C_x"]
            app.open_group("ALL")
            await pilot.pause()
            assert not app.check_action("sort", ()) and not app.check_action("hide", ())
    _run(go())


def test_enter_on_sorted_overview_opens_row_under_cursor(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            _to_col(app, "tree")
            await _key(pilot, "s")
            ov = app.query_one("#overview")
            row = _shown(app).index("tfs.C_x")
            _to_col(app, "tree", row=row)
            await pilot.pause()
            await _key(pilot, "enter")
            assert app.view == "hgs" and app.group == "tfs.C_x" and app.stage == "tree"
            await _key(pilot, "escape")
            assert app.view == "overview" and _shown(app)[ov.cursor_row] == "tfs.C_x"
            _to_col(app, "tree", row=_shown(app).index("tfs.A"))   # hide the row under the cursor
            await _key(pilot, "h")
            assert "tfs.A" not in _shown(app)
            assert app._key_at_cursor(ov) in _shown(app)
    _run(go())


def test_s_h_on_family_stage_count_families_and_skip_separator(cli):
    """search counts FAMILIES: tfs.A's family is searched (done), tfs.C_x's is not (ready)."""
    (_cfg().outdir / "search").mkdir(exist_ok=True)
    (_cfg().outdir / "search/tfs.A.domains.fasta").write_text(">x\nAA\n")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            rows = {r.group: r for r in app.ov_rows}
            assert rows["tfs.A"].per_stage["search"] == (1, 0, 0, 0)
            assert rows["tfs.C_x"].per_stage["search"] == (0, 0, 1, 0)
            _to_col(app, "search")
            await _key(pilot, "s")
            assert _pair(app) == ["tfs.C_x", "tfs.A"]
            assert app.query_one("#overview").border_title == "Overview · sort: search ▼"
            await _key(pilot, "h")
            assert _shown(app)[0] == "ALL" and _pair(app) == ["tfs.C_x"]
            sep = tui.ov_column("align") - 1                        # the │ column
            assert tui.stage_at_column(sep) is None
            app.query_one("#overview").move_cursor(row=0, column=sep)
            await pilot.pause()
            await _key(pilot, "s", "h")                             # no-ops on the separator
            assert (app.ov_sort, app.ov_hide) == (("search", False), "search")
            assert _pair(app) == ["tfs.C_x"]
    _run(go())
