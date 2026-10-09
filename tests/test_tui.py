"""phylocli/tui.py (Textual pilot tests; skipped when Textual is not installed)."""
import asyncio
import collections
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
            await pilot.press("f", "f", "f", "f", "down", "space", "a", "f", "f")
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
            assert "loading history" in app._status
            assert "loading history" in str(app.query_one("#status").render())
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "loading history" not in app._status
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
            assert any("unreadable genefam" in str(n.message) for n in app._notifications)
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
            assert _cells(app, "#ogs", 0) == ["HG1.0", "3", "2", "78.4", "T/Tbx19"]   # no ref columns
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
            assert (_cells(app, "#ogs", 0)[0], _cells(app, "#ogs", 0)[4]) == ("HG11.0", "Tbx20")
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
            await _press(pilot, "tab", "tab")                      # `/` filters the focused pane
            await _press(pilot, "slash")
            assert inp.display and app.focused is inp
            await _press(pilot, "h", "s", "a", "p")             # `p` is text here, not a switch
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


def _tcol(app, table, c=0):
    t = app.query_one(table)
    return [str(t.get_cell_at((i, c))) for i in range(t.row_count)]


def test_slash_filters_results_pane_and_repoints(cli, monkeypatch):
    write_results(_cfg())

    def boom(*a, **k):
        raise AssertionError("file read on a filter keystroke")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            for name in ("read_ogs", "group_ogs", "species_universe", "phyla"):
                monkeypatch.setattr(tui.model, name, boom)
            inp = app.query_one("#memfilter")
            assert app.focused is app.query_one("#res")
            await _press(pilot, "slash")
            assert inp.display and app.focused is inp and "filter Results" in inp.placeholder
            await _press(pilot, "q", "p", "R", "h", "o", "s")            # all text, no app keys
            assert app.view == "results" and inp.value == "qpRhos" and app.res_source == "possvm"
            await _press(pilot, "ctrl+u")
            assert inp.value == ""
            await _press(pilot, "1", "1")
            assert _tcol(app, "#res") == ["tfs.A.HG11"]
            assert app.query_one("#ogs").border_title.startswith("OGs · tfs.A.HG11")
            assert _tcol(app, "#ogs") == ["HG11.0"] and _member_genes(app) == ["Bova_x1", "Mlei_v05_G9"]
            assert app.query_one("#res").border_title == "Results · tfs · /11"
            await _press(pilot, "enter")
            assert app.focused is app.query_one("#res") and app.view == "results"
            await _press(pilot, "tab", "tab")                            # pane moves keep it
            assert app.query_one("#res").border_title == "Results · tfs · /11"
            assert _tcol(app, "#res") == ["tfs.A.HG11"]
            await _press(pilot, "shift+tab", "shift+tab", "slash")
            assert inp.value == "11"
            await _press(pilot, "escape")                                # esc in the box clears
            assert _tcol(app, "#res") == ["tfs.A.HG1", "tfs.A.HG11"]
            assert app.query_one("#res").border_title == "Results · tfs"
            assert app.focused is app.query_one("#res") and app.view == "results"
            await _press(pilot, "slash", "T", "X", "Z")                  # no match: no crash
            assert _tcol(app, "#res") == [] and _tcol(app, "#ogs") == [] and _member_genes(app) == []
            assert "no match" in app._res_foot
    _run(go())


def test_slash_filters_ogs_pane_by_id_and_name(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            await _press(pilot, "tab", "slash")                          # focus: OGs
            inp = app.query_one("#memfilter")
            assert app.focused is inp and "filter OGs" in inp.placeholder
            await _press(pilot, "e", "O", "M", "E", "S")                 # name, case-insensitive
            assert _tcol(app, "#ogs") == ["HG1.1"]
            assert _member_genes(app) == ["Hsap_ENSP2", "Nvec_v1_g3"]    # re-pointed at HG1.1
            assert app.query_one("#members").border_title.startswith("members · HG1.1")
            assert app.query_one("#ogs").border_title.endswith(" · /eOMES")
            await _press(pilot, "ctrl+u", "h", "g", "1", "full_stop", "0")    # id
            assert _tcol(app, "#ogs") == ["HG1.0"]
            await _press(pilot, "ctrl+u", "q", "q", "q")
            assert _tcol(app, "#ogs") == [] and _member_genes(app) == []
            assert "no match" in app._res_foot
            await _press(pilot, "escape")
            assert _tcol(app, "#ogs") == ["HG1.0", "HG1.1"]
    _run(go())


def test_pane_filters_are_independent(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            await _press(pilot, "slash", "1", "1", "enter")              # Results /11
            await _press(pilot, "tab", "tab", "slash", "b", "o", "v", "enter")   # members /bov
            assert _member_genes(app) == ["Bova_x1"]
            assert app.query_one("#members").border_title.endswith("/bov")
            assert app.query_one("#res").border_title == "Results · tfs · /11"
            assert _tcol(app, "#res") == ["tfs.A.HG11"]
            await _press(pilot, "slash")
            assert app.query_one("#memfilter").value == "bov"            # box shows this pane's
            await _press(pilot, "escape")
            assert _member_genes(app) == ["Bova_x1", "Mlei_v05_G9"]
            assert _tcol(app, "#res") == ["tfs.A.HG11"]                   # Results filter untouched
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
            assert (_cells(app, "#ogs", 0)[0], _cells(app, "#ogs", 0)[4]) == ("HG1.0", "like:Tbx2/Tbx3")
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
            assert (_cells(app, "#ogs", 0)[0], _cells(app, "#ogs", 0)[4]) == ("HG1.0", "T/Tbx19")
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
            assert cells[3] == "0.0 ⚠" and cells[4] == name[:24] + "…" and len(cells) == 5
            t = app.query_one("#ogs")
            head = sum(c.get_render_width(t) for c in list(t.columns.values())[:4])
            assert head <= t.size.width                  # OG, genes, spp, support visible
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
            assert app.query_one("#overview").border_title == "Overview · sort: group ▲"
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


# ---- final-review fix wave -------------------------------------------------------------------
def test_long_ref_support_is_truncated_in_ogs_and_members(cli):
    write_results(_cfg())
    long = "98.2/" * 120                                    # 600 characters, as in sig.GPCRglut
    p = _cfg().outdir / "possvm/tfs.A.HG1.generax.support.tree.ortholog_groups.csv"
    p.write_text(OG_HEAD + f"Mlei_v05_G1\ttfs.A.HG1.0:T/Tbx19\t78.4\t{'R' * 60}\t{long}\n")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            og = _cells(app, "#ogs", 0)
            assert len(og) == 5                          # OGs carry no reference columns
            mem = _cells(app, "#members", 0)
            assert len(mem[2]) <= 25 and len(mem[3]) <= 13, (len(mem[2]), len(mem[3]))
    _run(go())


def test_R_in_results_reloads_results_keeping_source_and_cursor(cli, monkeypatch):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            app.query_one("#res").move_cursor(row=1)
            await pilot.pause()
            gen = app._res_gen
            await pilot.press("R")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._res_gen > gen and app.view == "results"
            assert app.res_source == "possvm" and app.res_group == "tfs"
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG11"
    _run(go())


def test_h_fallback_cursor_is_previous_row_not_zero(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            row = _shown(app).index("tfs.A")
            assert row >= 1
            _to_col(app, "tree", row=row)
            await _key(pilot, "h")                       # tfs.A has nothing to do at tree
            assert "tfs.A" not in _shown(app)
            assert app.query_one("#overview").cursor_row == min(row, len(_shown(app)) - 1)
    _run(go())


def test_o_on_hg_without_output_notifies_and_goes_to_first_hg(cli, monkeypatch):
    write_results(_cfg())
    notes = []

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        monkeypatch.setattr(app, "notify", lambda msg, **kw: notes.append(msg))
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.open_group("tfs", "align")
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            vis = [r.hg for r in app.visible()]
            assert "tfs.C_x.HG1" in vis
            app.query_one("#hgs").move_cursor(row=vis.index("tfs.C_x.HG1"))
            await pilot.pause()
            await pilot.press("o")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results"
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG1"
            assert "tfs.C_x.HG1: no output in possvm" in notes
    _run(go())


def test_footer_prev_hint_only_for_possvm(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert "check possvm_prev" in app._res_foot
            await pilot.press("p")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_source == "possvm_prev"
            assert "check possvm_prev" not in app._res_foot
    _run(go())


@pytest.mark.parametrize("pane", ["#stages", "#arrays"])
def test_selection_keys_only_act_in_hgs_pane(cli, monkeypatch, pane):
    app = _failed_app(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.query_one(pane).focus()
            await pilot.pause()
            await pilot.press("space", "a", "r")
            await pilot.pause()
            assert not app.selected
            assert not isinstance(app.screen, tui.ResubmitScreen)
            msgs = [str(n.message) for n in app._notifications]
            assert msgs.count("tab to 2 HGs to select") == 3
            app.query_one("#hgs").focus()
            await pilot.pause()
            await pilot.press("a", "r")
            await pilot.pause()
            assert app.selected and isinstance(app.screen, tui.ResubmitScreen)
    _run(go())


def test_selection_keys_stay_in_footer(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.query_one("#stages").focus()
            await pilot.pause()
            for a in ("toggle", "select_all", "resubmit"):
                assert app.check_action(a, ()) is True
    _run(go())


def test_esc_outside_box_clears_all_filters_then_leaves(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            await _press(pilot, "tab", "tab", "slash", "b", "o", "v", "enter")   # members /bov only
            await _press(pilot, "shift+tab")                            # focus on OGs (no filter)
            assert getattr(app.focused, "id", None) == "ogs"
            await _press(pilot, "escape")                               # 1st esc: clears members'
            assert app.view == "results" and all(not q for q in app._flt.values())
            assert len(_member_genes(app)) > 1                         # members unfiltered again
            await _press(pilot, "escape")                               # 2nd esc: leaves
            assert app.view != "results"
    _run(go())


def test_logo_is_9_lines_of_10_cells():
    from rich.text import Text
    from phylocli import logo
    lines = logo.render_logo()
    assert len(lines) == 9
    assert {Text.from_markup(l).cell_len for l in lines} == {10}
    assert "white" not in "".join(lines)                          # ⬜ is transparent
    assert logo.COLOURS["⬛"] == "#6e6e6e"
    assert len(logo.render_logo(logo.PIXELS_FULL)) == 18


def test_strip_with_logo_and_help_is_in_every_view(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test(size=(150, 40)) as pilot:
            app.load_now()
            await pilot.pause()
            helps = {}
            for view in ("overview", "hgs", "results"):
                if view == "hgs":
                    app.open_group("tfs")
                elif view == "results":
                    app.action_open_results()
                await pilot.pause()
                assert app.view == view
                strip = app.query_one("#strip")
                assert strip.display and strip.size.height == 9
                assert app.query_one("#logo").display and app.query_one("#logo").size.width == 10
                assert not app.query("#banner")
                helps[view] = app._help_text
            assert len(set(helps.values())) == 3
            from rich.text import Text
            assert "o: results" in helps["overview"]
            assert "█ done" in Text.from_markup(helps["overview"]).plain
            assert "resubmit" in helps["hgs"]
            assert "possvm_prev" in helps["results"]
            assert "enter: open" not in app.query_one("#ovfoot").render().plain
    _run(go())


def test_warning_is_notified_once_per_session(cli, monkeypatch):
    def boom(*a, **k):
        raise OSError("unreadable genefam")
    monkeypatch.setattr(core, "family_ids", boom)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            n = lambda: sum("unreadable genefam" in str(x.message) for x in app._notifications)
            assert n() == 1
            app.load_now()                                       # next refresh: same message
            await pilot.pause()
            assert n() == 1
    _run(go())


# ---- header sorting ---------------------------------------------------------------------------
def _heads(app, wid):
    """Header labels of a table as shown (the overview's are two-row: 'step2 ·\\nalign')."""
    return [c.label.plain for c in app.query_one(wid).ordered_columns]


def _hcur(app, wid):
    """Index of the reversed header label (the header cursor), None outside header mode."""
    hits = [i for i, c in enumerate(app.query_one(wid).ordered_columns) if "reverse" in str(c.label.style)]
    return hits[0] if hits else None


def test_sort_rows_and_arrow():
    keys = {"n": (lambda r: r[1], True), "name": (lambda r: r[0], False)}
    rows = [("b", 1), ("a", 3), ("c", 1)]
    assert tui.sort_rows(rows, ("n", False), keys) == [("a", 3), ("b", 1), ("c", 1)]   # ties keep order
    assert tui.sort_rows(rows, ("n", True), keys) == [("b", 1), ("c", 1), ("a", 3)]
    assert tui.sort_rows(rows, ("name", False), keys) == [("a", 3), ("b", 1), ("c", 1)]
    assert tui.sort_rows(rows, None, keys) == rows and tui.sort_rows(rows, ("x", False), keys) == rows
    assert (tui.sort_arrow(True, False), tui.sort_arrow(True, True)) == ("▼", "▲")
    assert (tui.sort_arrow(False, False), tui.sort_arrow(False, True)) == ("▲", "▼")


def test_up_on_first_row_enters_overview_header_and_down_leaves(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            ov = app.query_one("#overview")
            _to_col(app, "tree", row=1)
            await _key(pilot, "up")
            assert not ov.header and ov.cursor_row == 0
            await _key(pilot, "up")                                  # row 0: into the header
            assert ov.header and _hcur(app, "#overview") == tui.ov_column("tree")
            await _key(pilot, "right")
            assert _hcur(app, "#overview") == tui.ov_column("tree") + 1
            await _key(pilot, "down")                                # back to the first row
            assert not ov.header and _hcur(app, "#overview") is None
            assert ov.cursor_row == 0 and ov.cursor_column == tui.ov_column("tree") + 1
    _run(go())


def test_header_enter_and_s_sort_with_arrow_and_same_state_as_cell_s(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            ov = app.query_one("#overview")
            _to_col(app, "tree")
            await _key(pilot, "up", "enter")                         # header: sort, never open
            assert app.view == "overview" and ov.header
            assert app.ov_sort == ("tree", False) and _pair(app) == ["tfs.C_x", "tfs.A"]
            assert _heads(app, "#overview")[tui.ov_column("tree")] == "HGs\ntree ▼"
            await _key(pilot, "s")                                   # s in the header: reverse
            assert app.ov_sort == ("tree", True) and _pair(app) == ["tfs.A", "tfs.C_x"]
            assert _heads(app, "#overview")[tui.ov_column("tree")] == "HGs\ntree ▲"
            await _key(pilot, "down", "s")                           # s on a cell: the same sort
            assert app.ov_sort == ("tree", False) and ov.cursor_row == 0
            assert app.query_one("#overview").border_title == "Overview · sort: tree ▼"
            _to_col(app, "group")
            await _key(pilot, "up", "enter")                         # text: ascending first
            assert app.ov_sort == ("group", False) and _heads(app, "#overview")[0] == "\ngroup ▲"
            assert _heads(app, "#overview")[tui.ov_column("tree")] == "HGs\ntree"   # one arrow
            assert _shown(app)[0] == "ALL"                           # ALL stays pinned
    _run(go())


def test_header_skips_separator_and_sort_survives_refresh(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            ov = app.query_one("#overview")
            sep = tui.ov_column("align") - 1
            ov.move_cursor(row=0, column=sep - 1)
            await pilot.pause()
            await _key(pilot, "up", "right")                         # cluster -> align, not │
            assert _hcur(app, "#overview") == tui.ov_column("align")
            await _key(pilot, "left")
            assert _hcur(app, "#overview") == sep - 1
            ov.move_cursor(row=0, column=sep)
            await _key(pilot, "down")
            ov.move_cursor(row=0, column=sep)
            await pilot.pause()
            await _key(pilot, "up")                                  # from │: next column right
            assert _hcur(app, "#overview") == tui.ov_column("align")
            await _key(pilot, "enter")
            app.load_now()
            await pilot.pause()
            assert app.ov_sort == ("align", False)
            assert _heads(app, "#overview")[tui.ov_column("align")].endswith("align ▼")
            assert _hcur(app, "#overview") == tui.ov_column("align")   # still in header mode
            await _key(pilot, "c")                                   # regroup: sort kept
            assert app.ov_sort == ("align", False) and _shown(app)[0] == "ALL"
    _run(go())


def test_header_keys_touch_no_files_or_slurm(cli, monkeypatch):
    _sorted_fixture()

    def boom(*a, **k):
        raise AssertionError("file or SLURM access on a header key")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            await app.workers.wait_for_complete()
            monkeypatch.setattr(core, "ready_set", boom)
            monkeypatch.setattr(core.report_status, "done_by_stage", boom)
            monkeypatch.setattr(core.report_status, "nonempty_files", boom)
            monkeypatch.setattr(tui.model, "_slurm", boom)
            _to_col(app, "tree")
            await _key(pilot, "up", "left", "right", "enter", "s", "down")
            assert app.ov_sort == ("tree", True)
    _run(go())


def test_hgs_pane_header_sort_skips_mark_and_survives_refresh_and_unit(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    app.filter = "actionable"                    # tfs.A.HG11 ready (3 seqs), tfs.C_x.HG1 failed (600)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            t = app.query_one("#hgs")
            t.focus()
            t.move_cursor(row=0)
            await pilot.pause()
            await _key(pilot, "up")
            assert t.header and _hcur(app, "#hgs") == 1             # HG: the mark is skipped
            await _key(pilot, "left")
            assert _hcur(app, "#hgs") == 1
            await _key(pilot, "right", "enter")                      # seqs: numbers descending
            assert [r.hg for r in app.visible()] == ["tfs.C_x.HG1", "tfs.A.HG11"]
            assert _heads(app, "#hgs")[2] == "seqs ▼"
            await _key(pilot, "enter")
            assert [r.hg for r in app.visible()] == ["tfs.A.HG11", "tfs.C_x.HG1"]
            assert _heads(app, "#hgs")[2] == "seqs ▲"
            await _key(pilot, "down", "space")                       # rows again: row 0 selected
            assert not t.header and app.selected == {"tfs.A.HG11"}
            app.load_now()
            await pilot.pause()
            assert [r.hg for r in app.visible()] == ["tfs.A.HG11", "tfs.C_x.HG1"]
            app.open_group("ALL", "search")                          # family unit: same column
            await pilot.pause()
            assert _heads(app, "#hgs")[1:3] == ["family", "HGs ▲"]
    _run(go())


def test_results_panes_header_sort_independently(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            await _key(pilot, "up", "right", "enter", "enter")      # Results: OGs ascending
            assert _tcol(app, "#res") == ["tfs.A.HG11", "tfs.A.HG1"]
            assert _heads(app, "#res") == ["HG", "OGs ▲", "genes", "⚠"]
            await _key(pilot, "down")
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG11"
            await _key(pilot, "up")                                  # cursor back on HG1 ...
            app.query_one("#res").move_cursor(row=1)
            await pilot.pause()
            assert app.query_one("#ogs").border_title.startswith("OGs · tfs.A.HG1 ")
            await _key(pilot, "tab", "up", "right", "right", "right", "enter")   # OGs: support
            assert _tcol(app, "#ogs") == ["HG1.0", "HG1.1"]
            assert _heads(app, "#ogs")[3] == "support ▼"
            await _key(pilot, "enter")                               # reversed: cursor stays on OG
            assert _tcol(app, "#ogs") == ["HG1.1", "HG1.0"]
            assert app._key_at_cursor(app.query_one("#ogs")) == "tfs.A.HG1.0"
            assert app.query_one("#members").border_title == "members · HG1.0 T/Tbx19"
            await _key(pilot, "down")                                # first row: HG1.1
            assert app.query_one("#members").border_title == "members · HG1.1 like:Eomes/Tbr1"
            await _key(pilot, "tab", "up", "right", "enter")        # members: sp, text ascending
            assert _member_genes(app) == ["Hsap_ENSP2", "Nvec_v1_g3"]
            await _key(pilot, "enter")
            assert _member_genes(app) == ["Nvec_v1_g3", "Hsap_ENSP2"]
            assert _heads(app, "#res")[1] == "OGs ▲"                 # each pane its own sort
            assert app.query_one("#res").sort_state == ("ogs", True)
            assert app.query_one("#ogs").sort_state == ("support", True)
            assert app.query_one("#members").sort_state == ("sp", True)
            await pilot.press("p")                                   # new source: sorts kept
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_source == "possvm_prev" and _heads(app, "#res")[1] == "OGs ▲"
    _run(go())


def test_header_mode_never_captures_filter_typing(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            await _key(pilot, "tab", "tab", "up")                    # members header mode
            m = app.query_one("#members")
            assert m.header
            await _key(pilot, "slash", "s", "q", "R", "p")           # all text for the box
            inp = app.query_one("#memfilter")
            assert inp.value == "sqRp" and app.focused is inp
            assert m.sort_state is None and not m.header and app.view == "results"
            assert app.res_source == "possvm"
    _run(go())


def test_header_sort_on_empty_results_pane(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "cal")                   # a group with no HGs
            assert app.query_one("#res").row_count == 0
            await _key(pilot, "up", "enter", "down")
            assert app.query_one("#res").sort_state == ("hg", False) and app.view == "results"
    _run(go())


# ---- Results cursor fixes (Part C review) -----------------------------------------------------
def test_filters_keep_the_og_cursor_when_it_still_matches(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            ogs = app.query_one("#ogs")
            await _key(pilot, "tab", "down")                         # OGs: HG1.1
            assert app._key_at_cursor(ogs) == "tfs.A.HG1.1"
            await _key(pilot, "slash", "h", "g", "enter")           # both OGs match: kept
            assert _tcol(app, "#ogs") == ["HG1.0", "HG1.1"]
            assert app._key_at_cursor(ogs) == "tfs.A.HG1.1"
            await _key(pilot, "shift+tab", "slash", "h", "g", "1")  # refine Results /hg1 ...
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG1"
            assert app._key_at_cursor(ogs) == "tfs.A.HG1.1"          # ... same HG: OG kept
            await _key(pilot, "1")                                   # /hg11: another HG -> row 0
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG11"
            assert app._key_at_cursor(ogs) == "tfs.A.HG11.0"
    _run(go())


def test_results_filter_during_load_keeps_cursor(cli, monkeypatch):
    import threading
    write_results(_cfg())
    gate = threading.Event()
    gate.set()
    real = tui.model.read_ogs

    def gated(*a, **k):
        gate.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(tui.model, "read_ogs", gated)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            app.query_one("#res").move_cursor(row=1)                 # tfs.A.HG11
            await pilot.pause()
            gate.clear()
            await _key(pilot, "R")                                   # reload, held at the gate
            assert app.query_one("#resv").has_class("loading") and app.res_rows == []
            await _key(pilot, "slash", "h", "g", "1", "enter")      # filter while loading
            assert _tcol(app, "#res") == ["tfs.A.HG1", "tfs.A.HG11"]     # greyed rows stay
            assert app.query_one("#res").border_title == "Results · tfs · /hg1"
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert _tcol(app, "#res") == ["tfs.A.HG1", "tfs.A.HG11"]
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG11"
    _run(go())


# ---- review fixes of the header sorting (Tasks 1-2) -------------------------------------------
def _rendered_header(app, wid, rows=1):
    """The header as Textual DRAWS it (render_line), not the column labels."""
    t = app.query_one(wid)
    return "\n".join(t.render_line(y).text for y in range(rows))


def _widths(app, wid):
    t = app.query_one(wid)
    return [c.get_render_width(t) for c in t.ordered_columns]


def test_rendered_header_shows_the_arrow_and_widths_do_not_move(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test(size=(240, 50)) as pilot:
            await _open_results(app, pilot, "tfs")
            before = _widths(app, "#res")
            assert "OGs ▲" not in _rendered_header(app, "#res")
            await _key(pilot, "up", "right", "enter")                # OGs: numbers, descending
            assert "OGs ▼" in _rendered_header(app, "#res")
            await _key(pilot, "enter")
            assert "OGs ▲" in _rendered_header(app, "#res")
            assert _widths(app, "#res") == before                    # the arrow was pre-sized
            await _key(pilot, "right", "enter")                      # genes: the arrow moves
            out = _rendered_header(app, "#res")
            assert "genes ▼" in out and "OGs ▲" not in out
    _run(go())


def test_sorting_hgs_keeps_the_cursor_on_the_same_hg(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    app.filter = "actionable"                    # tfs.A.HG11 (3 seqs), tfs.C_x.HG1 (600)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            t = app.query_one("#hgs")
            t.focus()
            t.move_cursor(row=0)
            await pilot.pause()
            first = app._cursor_hg()
            await _key(pilot, "up", "right", "enter")                # seqs descending: C_x first
            assert [r.hg for r in app.visible()][0] != first
            assert app._cursor_hg() == first and t.cursor_row == 1
    _run(go())


def test_sorting_res_keeps_the_og_cursor(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            ogs = app.query_one("#ogs")
            await _key(pilot, "tab", "down")                         # OGs: HG1.1
            assert app._key_at_cursor(ogs) == "tfs.A.HG1.1"
            await _key(pilot, "shift+tab", "up", "right", "enter", "enter")   # Results: OGs asc
            assert _tcol(app, "#res") == ["tfs.A.HG11", "tfs.A.HG1"]
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG1"
            assert app._key_at_cursor(ogs) == "tfs.A.HG1.1"
    _run(go())


def test_row_keys_do_nothing_in_header_mode(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    app.filter = "actionable"

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            t = app.query_one("#hgs")
            t.focus()
            t.move_cursor(row=0)
            await pilot.pause()
            await _key(pilot, "up")
            assert t.header
            n = len(app.screen_stack)
            await _key(pilot, "space", "a", "r", "l", "o")
            assert app.selected == set() and t.header and len(app.screen_stack) == n
            assert app.view == "hgs"
            await _key(pilot, "down", "space")                       # rows again: works
            assert not t.header and len(app.selected) == 1
    _run(go())


def test_o_does_nothing_in_the_overview_header(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            ov = app.query_one("#overview")
            ov.move_cursor(row=0, column=2)
            await pilot.pause()
            await _key(pilot, "up")
            assert ov.header
            await _key(pilot, "o")
            assert app.view == "overview"
    _run(go())


def test_nan_sorts_last_and_never_breaks_sorted():
    nan = float("nan")
    assert tui._lead_float("nan") == -float("inf") and tui._lead_float("nan/3") == -float("inf")
    assert tui._lead_float("98.2/97.0") == 98.2
    O = collections.namedtuple("O", "support")
    key = tui.OG_KEYS["support"][0]
    assert key(O(nan)) == -float("inf") and key(O(None)) == -float("inf")
    rows = [O(1.0), O(nan), O(3.0), O(None), O(2.0)]
    out = tui.sort_rows(rows, ("support", False), tui.OG_KEYS)      # descending first
    assert [o.support for o in out[:3]] == [3.0, 2.0, 1.0]
    M = collections.namedtuple("M", "ref_support")
    mrows = [(0, M("5.0")), (1, M("nan")), (2, M("9.0")), (3, M("-")), (4, M("7.0"))]
    out = tui.sort_rows(mrows, ("sup", False), tui.MEM_KEYS)
    assert [i for i, _ in out[:3]] == [2, 4, 0]


# ---- Results tab (first screen) ---------------------------------------------------------------
def _count_group_ogs(monkeypatch):
    calls = []
    real = tui.model.group_ogs

    def counted(cfg, hgs, source, **k):
        calls.append((len(list(hgs)), source))
        return real(cfg, hgs, source, **k)
    monkeypatch.setattr(tui.model, "group_ogs", counted)
    return calls


async def _results_tab(app, pilot):
    """First screen, after the first refresh -> tab -> wait for the one read."""
    app.load_now()
    await pilot.pause()
    await pilot.press("tab")
    await app.workers.wait_for_complete()
    await pilot.pause()


def _rt(app):
    return [(r.group, r.hgs, r.with_output, r.ogs, r.genes, r.zero) for r in app.rt_shown]


def test_tab_switches_jobs_and_results_tabs(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert app._tab_text == "[Jobs] │ Results" and app.focused is app.query_one("#overview")
            await pilot.press("tab")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.tab == "results" and app._tab_text == "Jobs │ [Results]"
            assert app.focused is app.query_one("#rtab") and not app.query_one("#overview").display
            assert [r.group for r in app.rt_shown] == [r.group for r in app.ov_rows]   # same groups
            assert _rt(app)[:2] == [("ALL", 3, 2, 3, 7, 1), ("tfs", 3, 2, 3, 7, 1)]
            assert _rt(app)[2][1:] == (0, 0, 0, 0, 0)
            assert app.query_one("#rtab").border_title == "Results · possvm"
            assert app.check_action("toggle_source", ()) and app.check_action("sort", ())
            await _key(pilot, "shift+tab")
            assert app.tab == "jobs" and app.focused is app.query_one("#overview")
            assert not app.check_action("toggle_source", ())
            await _key(pilot, "f", "tab")                            # by family: kept across tabs
            assert app.by == "family" and app.tab == "results"
            assert ("tfs.A", 2, 2, 3, 7, 1) in _rt(app) and ("tfs.C_x", 1, 0, 0, 0, 0) in _rt(app)
    _run(go())


def test_results_tab_reads_once_and_window_reuses_it(cli, monkeypatch):
    write_results(_cfg())
    calls = _count_group_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            assert calls == [(3, "possvm")]
            rt = app.query_one("#rtab")
            rt.move_cursor(row=[r.group for r in app.rt_shown].index("tfs"), column=3)
            await pilot.pause()
            await pilot.press("enter")                               # opens the Results window
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and app.res_group == "tfs"
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
            win = [_cells(app, "#res", i) for i in range(app.query_one("#res").row_count)]
            tab = next(r for r in app.rt_rows if r.group == "tfs")
            assert (tab.with_output, tab.hgs) == (len(app.res_rows), len(app.res_rows) + app.res_missing)
            assert (tab.ogs, tab.genes, tab.zero) == tuple(sum(int(c[i]) for c in win) for i in (1, 2, 3))
            assert calls == [(3, "possvm")]                          # no second read
            await _key(pilot, "escape")
            assert app.view == "overview" and app.tab == "results" and app.focused is rt
            assert app._key_at_cursor(rt) == "tfs" and rt.cursor_column == 3
            await _key(pilot, "tab", "o")                            # Jobs tab o: cache reused too
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and calls == [(3, "possvm")]
            await _key(pilot, "escape", "tab")
            assert app.tab == "results" and calls == [(3, "possvm")]   # switching never re-reads
    _run(go())


def test_results_tab_p_switches_source_and_R_rereads(cli, monkeypatch):
    write_results(_cfg())
    calls = _count_group_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            await pilot.press("p")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.rt_source == "possvm_prev" and calls[-1] == (3, "possvm_prev")
            assert _rt(app)[0] == ("ALL", 3, 1, 1, 2, 0)
            assert app.query_one("#rtab").border_title == "Results · possvm_prev"
            await pilot.press("enter")                               # window opens on prev, cached
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_source == "possvm_prev" and len(calls) == 2
            await _key(pilot, "escape")
            await pilot.press("R")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(calls) == 3 and app.rt_source == "possvm_prev"
    _run(go())


def test_results_tab_sort_hide_and_header_keep_all_pinned(cli, monkeypatch):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            rt = app.query_one("#rtab")
            rt.move_cursor(row=1, column=3)                          # OGs
            await pilot.pause()
            await _key(pilot, "h")
            assert [r[0] for r in _rt(app)] == ["ALL", "tfs"]
            assert rt.border_title == "Results · possvm · only ogs > 0"
            await _key(pilot, "h")
            assert len(_rt(app)) == 4
            rt.move_cursor(row=0, column=0)
            await pilot.pause()
            await _key(pilot, "h")                                   # group: not a count
            assert app.rt_hide is None
            await _key(pilot, "s")                                   # s on a cell: group ▲
            assert rt.sort_state == ("group", False) and [r[0] for r in _rt(app)] == ["ALL", "cal", "slc", "tfs"]
            await _key(pilot, "up", "right", "right", "right", "enter")   # header: OGs ▼
            assert app.view == "overview"                            # enter in the header never opens
            assert rt.sort_state == ("ogs", False) and _heads(app, "#rtab")[3] == "OGs ▼"
            assert [r[0] for r in _rt(app)][:2] == ["ALL", "tfs"]
            app.load_now()                                           # refresh: sort kept, no read
            await pilot.pause()
            assert rt.sort_state == ("ogs", False) and [r[0] for r in _rt(app)][:2] == ["ALL", "tfs"]
    _run(go())


def test_results_tab_waits_for_first_refresh_and_shows_progress(cli, monkeypatch):
    write_results(_cfg())
    calls = _count_group_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app._ov_inputs = (set(), {}, set(), {})                  # as before the first refresh
            await pilot.press("tab")
            await pilot.pause()
            assert app.tab == "results" and calls == [] and app._og_cache is None
            app.load_now()                                           # first data: the read starts
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(calls) == 1 and app._og_cache is not None
            app.query_one("#rtab").add_class("loading")
            app._rt_progress(app._rt_gen, 100, 1915)
            assert "loading 100/1915…" in app._rt_foot
            app._rt_progress(app._rt_gen - 1, 150, 1915)              # stale generation: ignored
            assert "150/1915" not in app._rt_foot
    _run(go())


def test_results_tab_counts_unreadable_hgs(cli):
    write_results(_cfg())
    (_cfg().outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv").write_text(
        OG_HEAD + "broken\n")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            assert _rt(app)[0] == ("ALL", 3, 2, 2, 5, 1)
            assert "1 HG unreadable" in app._rt_foot
    _run(go())


def test_results_tab_keys_touch_no_files_or_slurm(cli, monkeypatch):
    write_results(_cfg())

    def boom(*a, **k):
        raise AssertionError("file or SLURM access on a Results tab key")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            monkeypatch.setattr(core, "ready_set", boom)
            monkeypatch.setattr(core.report_status, "done_by_stage", boom)
            monkeypatch.setattr(core.report_status, "nonempty_files", boom)
            monkeypatch.setattr(tui.model, "read_ogs", boom)
            monkeypatch.setattr(tui.model, "_slurm", boom)
            app.query_one("#rtab").move_cursor(row=0, column=3)
            await _key(pilot, "s", "h", "h", "up", "right", "enter", "down", "f", "c",
                       "shift+tab", "tab")
            assert app.tab == "results" and app.query_one("#rtab").sort_state == ("genes", False)
    _run(go())


def test_R_during_a_tab_read_drops_it_and_next_visit_rereads(cli, monkeypatch):
    import threading
    write_results(_cfg())
    gate, started = threading.Event(), threading.Event()
    real = tui.model.group_ogs
    calls = []

    def gated(cfg, hgs, source, **k):
        calls.append(source)
        if len(calls) == 1:                      # the first read waits for the gate
            started.set()
            gate.wait(10)
        return real(cfg, hgs, source, **k)
    monkeypatch.setattr(tui.model, "group_ogs", gated)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("tab")             # Results tab: the read starts and blocks
            for _ in range(100):
                if started.is_set():
                    break
                await pilot.pause(0.05)
            assert started.is_set() and app._rt_loading()
            await pilot.press("shift+tab")
            await pilot.press("R")               # on Jobs, mid-read
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._og_cache is None and not app._rt_loading()   # stale read dropped
            await pilot.press("tab")             # next visit reads afresh
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(calls) == 2 and app._og_cache is not None
    _run(go())


def test_stale_apply_rtab_is_dropped(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            before = app._og_cache
            app._apply_rtab(dict(gen=app._rt_gen - 1, source="possvm_prev", rows=[], hgs=[], note=""))
            assert app._og_cache is before and app.rt_source == "possvm"
    _run(go())


def test_results_tab_footer_counts_the_groups_own_unreadable_hgs(cli):
    write_results(_cfg())
    (_cfg().outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv").write_text(
        OG_HEAD + "broken\n")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            rt = app.query_one("#rtab")
            rt.move_cursor(row=[r.group for r in app.rt_shown].index("cal"), column=0)
            await pilot.pause()
            assert "cal:" in app._rt_foot and "unreadable" not in app._rt_foot
    _run(go())


def test_switching_tab_leaves_header_mode(cli):
    """(on_blur also leaves header mode on this path; _switch_tab does it explicitly.)"""
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            ov, rt = app.query_one("#overview"), app.query_one("#rtab")
            await _key(pilot, "up")
            assert rt.header
            await _key(pilot, "shift+tab")                           # Jobs tab: its table in row mode
            assert app.tab == "jobs" and not rt.header and not ov.header and rt.show_cursor
            await _key(pilot, "up")
            assert ov.header
            await _key(pilot, "tab")
            assert app.tab == "results" and not ov.header and not rt.header and ov.show_cursor
            assert _hcur(app, "#overview") is None and _hcur(app, "#rtab") is None
    _run(go())


def test_set_cols_sizes_a_sorted_column_like_a_resort(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test(size=(240, 50)) as pilot:
            await _open_results(app, pilot, "tfs")
            t = app.query_one("#res")
            t.on_sort = None                                         # no row refill: labels only
            t.sort_state = None
            t.set_cols(tui.RES_COLS)
            t.sort_by(1)                                            # plain re-sort: OGs ▼, pre-sized
            await pilot.pause()
            assert t.sort_state == ("ogs", False)
            after_sort = _widths(app, "#res")
            t.set_cols(tui.RES_COLS)                                 # refill with the sort kept
            await pilot.pause()
            assert _widths(app, "#res") == after_sort
    _run(go())


# ---- species coverage colours (D) and overview numbers (E) ------------------------------------
def test_coverage_style_thirds():
    assert [tui.coverage_style(k, 3) for k in range(4)] == ["red", "yellow", "green", "green"]
    assert tui.coverage_style(0, 0) == "red" and tui.coverage_style(1, 4) == "red"
    assert tui.coverage_style(1, 2) == "yellow" and tui.coverage_style(5, 5) == "green"


def test_species_text_colours_counts_only_and_never_parses_markup():
    text = "\n".join(["Ctenophora  1/2 spp  2 genes", "  Mlei 2 · [b]x 1",
                      "Chordata    0/3 spp  0 genes", "absent: unknown, [red]"])
    t = tui.species_text(text)
    assert t.plain == text                                   # numbers and names unchanged
    assert [(t.plain[s.start:s.end], str(s.style)) for s in t.spans] == [
        ("1/2 spp", "yellow"), ("0/3 spp", "red"), ("absent: unknown, [red]", "dim")]


def test_species_pane_is_coloured_by_coverage(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert app._species_text.splitlines()[0] == "Ctenophora  1/2 spp  2 genes"
            t = tui.species_text(app._species_text)
            assert [str(s.style) for s in t.spans] == ["yellow", "green", "dim"]
    _run(go())


def test_ov_cell_numbers_left_of_six_cell_bar():
    from rich.text import Text as RText
    g = tui.PhyloApp.OV_GLYPHS
    assert tui.PhyloApp.OV_BAR == 6
    cell = tui.ov_cell((1800, 0, 0, 214), 9, 6, g)
    assert RText.from_markup(cell).plain == "1800/2014 █████░"
    assert RText.from_markup(tui.ov_cell((1, 0, 1, 0), 9, 6, g)).plain == "      1/2 ███▓▓▓"
    assert RText.from_markup(tui.ov_cell((0, 0, 0, 0), 3, 6, g)).plain == "0/0 "


def test_overview_cells_show_done_over_total(cli):
    from rich.text import Text as RText

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            c = app.ov_rows[0].per_stage["align"]
            cell = _cells(app, "#overview", 0)[tui.ov_column("align")]
            assert RText.from_markup(cell).plain.startswith(f"{c[0]}/{sum(c)} ")
            assert len(RText.from_markup(cell).plain.split(" ")[-1]) == 6
            col = [RText.from_markup(_cells(app, "#overview", i)[tui.ov_column("align")]).plain
                   for i in range(len(app.ov_shown))]
            assert len({len(x.rsplit(" ", 1)[0]) for x in col if x != "n/a"}) == 1   # right-aligned
    _run(go())


def test_stage_sort_and_hide_use_failed_ready_not_the_done_total_text(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            _to_col(app, "tree")
            await _key(pilot, "s")
            assert _pair(app) == ["tfs.C_x", "tfs.A"]               # by failed+ready, as before
            cell = _cells(app, "#overview", 1)[tui.ov_column("tree")]
            assert "/" in cell                                      # the new done/total text
            await _key(pilot, "h")
            assert all(tui._todo_at(r, "tree") != (0, 0) and tui._todo_at(r, "tree") != (-1, -1)
                       for r in app.ov_shown if r.group != "ALL")
    _run(go())


# ---- spinner (F) ------------------------------------------------------------------------------
def _gated_read_ogs(monkeypatch, start_open=False):
    import threading
    gate = threading.Event()
    if start_open:
        gate.set()
    real = tui.model.read_ogs

    def gated(*a, **k):
        gate.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(tui.model, "read_ogs", gated)
    return gate


def test_spinner_turns_while_results_window_loads_and_stops_on_apply(cli, monkeypatch):
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            spin = app.query_one("#status")
            assert not spin.running and str(spin.render()) == ""        # idle: empty
            await _key(pilot, "o")
            assert spin.running and spin.text == "loading…" == app._status
            f0 = spin.frame
            await pilot.pause(0.4)                                     # ~8 frames/s
            assert spin.frame != f0
            assert str(spin.render()) == f"{tui.SPIN_FRAMES[spin.frame]} loading…"
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not spin.running and str(spin.render()) == "" and app._status == ""
    _run(go())


def test_spinner_stops_on_esc_during_results_load(cli, monkeypatch):
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _key(pilot, "o")                                     # ALL
            spin = app.query_one("#status")
            assert spin.running
            await _key(pilot, "escape")                                # cancel
            assert app.view == "overview" and not spin.running
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not spin.running and str(spin.render()) == ""
    _run(go())


def test_spinner_on_results_tab_and_for_history(cli, monkeypatch):
    import threading
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _key(pilot, "tab")
            spin = app.query_one("#status")
            assert spin.running and spin.text == "loading…"
            await _key(pilot, "tab")                                   # Jobs tab: not its wait
            assert not spin.running
            await _key(pilot, "tab")
            assert spin.running
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not spin.running and app._og_cache is not None
            real = tui.history.attempts
            hold = threading.Event()
            monkeypatch.setattr(tui.history, "attempts",
                                lambda *a, **k: hold.wait(10) and real(*a, **k))
            app.by_stage = {}                                          # no HG-view history yet
            app.open_group("tfs")
            await pilot.pause()
            assert spin.running and spin.text == "loading history…"
            hold.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.by_stage and not spin.running
    _run(go())


def test_spinner_stops_on_R_from_jobs_tab_and_restarts_on_results_tab(cli, monkeypatch):
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _key(pilot, "tab")
            spin = app.query_one("#status")
            assert spin.running
            await _key(pilot, "R")                                     # R on the Results tab: re-read
            assert spin.running and app._status == "loading…"
            await _key(pilot, "shift+tab")                             # Jobs tab
            assert not spin.running
            await _key(pilot, "R")                                     # R drops the read: nothing to wait for
            assert not spin.running and not app.query_one("#rtab").has_class("loading")
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not spin.running and app._og_cache is None          # the dropped read cached nothing
    _run(go())


def test_spinner_runs_and_stops_on_p_source_switch(cli, monkeypatch):
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch, start_open=True)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            spin = app.query_one("#status")
            assert not spin.running
            gate.clear()
            await _key(pilot, "p")
            assert spin.running and spin.text == "loading…"
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not spin.running and app.res_source == "possvm_prev"
            await _key(pilot, "escape")
            await _key(pilot, "tab")
            await app.workers.wait_for_complete()
            await pilot.pause()
            gate.clear()
            await _key(pilot, "p")                                     # p on the Results tab
            assert spin.running and app.query_one("#rtab").has_class("loading")
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not spin.running
    _run(go())


def test_spinner_ignores_a_stale_generation(cli, monkeypatch):
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _key(pilot, "tab")
            spin = app.query_one("#status")
            assert spin.running
            app._apply_rtab(dict(gen=app._rt_gen - 1, source="possvm", rows=[], hgs=[], note=""))
            assert spin.running and app._og_cache is None             # stale: dropped, still waiting
            app._rt_gen += 1                                           # the live read becomes stale
            app.query_one("#rtab").remove_class("loading")
            app._apply_rtab(dict(gen=app._rt_gen - 1, source="possvm", rows=[], hgs=[], note=""))
            assert not spin.running                                    # nothing is waited for any more
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not spin.running
    _run(go())


def test_spinner_stops_when_a_read_is_cancelled_by_leaving_the_window(cli, monkeypatch):
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _key(pilot, "o")
            spin = app.query_one("#status")
            assert spin.running
            app.workers.cancel_group(app, "results")                  # the worker is cancelled ...
            gate.set()
            await pilot.pause(0.5)                                     # (a cancelled worker applies nothing)
            assert app.res_rows == []
            await _key(pilot, "escape")                                # ... and the user leaves
            assert not spin.running and str(spin.render()) == ""
    _run(go())


# ---- final-review fixes ----------------------------------------------------------------------
def _flip_possvm_done():
    """tfs.C_x.HG1 had no POSSVM output; give it one (its possvm stage is now done)."""
    from phylocli.tests.test_model import POSSVM_HG1, og_csv
    (_cfg().outdir / "possvm/tfs.C_x.HG1.generax.support.tree.ortholog_groups.csv").write_text(
        og_csv(POSSVM_HG1))


def test_refresh_after_possvm_finishes_rereads_results_tab_keeping_old_rows(cli, monkeypatch):
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch, start_open=True)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            assert _rt(app)[1] == ("tfs", 3, 2, 3, 7, 1)
            _flip_possvm_done()
            gate.clear()
            app.load_now()
            await pilot.pause()
            await pilot.pause(0.3)
            assert app.query_one("#rtab").has_class("loading")      # background re-read started
            assert _rt(app)[1] == ("tfs", 3, 2, 3, 7, 1)            # ... old rows kept meanwhile
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert _rt(app)[1][2] == 3 and not app.query_one("#rtab").has_class("loading")
    _run(go())


def test_refresh_after_possvm_finishes_then_o_reads_the_new_hg(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            assert app._og_cache is not None
            await _key(pilot, "shift+tab")                          # Jobs tab
            _flip_possvm_done()
            app.load_now()
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await _key(pilot, "o")                                  # ALL
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_missing == 0 and "tfs.C_x.HG1" in [r.hg for r in app.res_rows]
    _run(go())


def test_R_before_the_first_snapshot_reads_nothing_and_the_snapshot_then_reads(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            app._ov_inputs = (set(), {}, set(), {})                 # no snapshot yet
            app.tab = "results"
            app._og_cache = None
            app.action_refresh()                                    # (its own snapshot lands later)
            assert app._og_cache is None and not app.query_one("#rtab").has_class("loading")
            app.load_now()                                          # the snapshot lands
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._og_cache is not None and len(app._og_cache["hgs"]) == 3
    _run(go())


def test_repeated_R_during_a_load_leaves_one_spinner_timer(cli, monkeypatch):
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _key(pilot, "tab")
            spin = app.query_one("#status")
            for _ in range(4):
                await _key(pilot, "R")
            assert spin.running and len(spin._timers) == 1
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not spin.running and len(spin._timers) == 0
    _run(go())


def test_sort_state_does_not_shadow_datatable_sort(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            t = app.query_one("#overview")
            assert t.sort_state is None
            assert t.sort.__func__ is tui.DataTable.sort            # the method is intact
    _run(go())


def test_header_mode_refreshes_the_footer_bindings(cli, monkeypatch):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            calls = []
            real = app.refresh_bindings
            monkeypatch.setattr(app, "refresh_bindings", lambda *a, **k: (calls.append(1), real(*a, **k)))
            await _key(pilot, "up")
            assert app.query_one("#overview").header and len(calls) >= 1
            n = len(calls)
            await _key(pilot, "down")
            assert not app.query_one("#overview").header and len(calls) > n
    _run(go())
