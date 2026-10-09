#!/usr/bin/env python3
"""phylo: progress report and per-stage SLURM job arrays for the step2 pipeline."""
from __future__ import annotations

import collections
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import typer  # noqa: E402

from phylocli import core, history, runner  # noqa: E402
from phylocli.common import (FAILED_STATES, RUNNING_STATES, expand_indices as _expand_indices,  # noqa: E402,F401
                             fmt_mem as _fmt_mem, fmt_time as _fmt_time, ids_path as _ids_path,
                             runs_dir as _runs_dir)
from phylocli.runner import run_one  # noqa: E402,F401  (module-level name: tests patch it)
from phylocli import model  # noqa: E402


def _guard(fn):
    """Call a model function; a ModelError becomes the CLI's usual message + exit code."""
    def wrapped(*a, **k):
        try:
            return fn(*a, **k)
        except model.ModelError as e:
            _fail(str(e), e.code)
    return wrapped


app = typer.Typer(add_completion=False, no_args_is_help=True,
                  context_settings={"help_option_names": ["-h", "--help"]},
                  help="Report step2 progress and submit per-stage SLURM job arrays.")

TOOLS, MAX_ARRAY, SBATCH, SHOW = model.TOOLS, model.MAX_ARRAY, model.SBATCH, model.SHOW
_chunks = model.chunks
_new_run_dir = model.new_run_dir
_show = model.show


def _cfg() -> core.Config:
    p = os.environ.get("PHYLOCLI_CONFIG")
    return core.load_config(Path(p)) if p else core.load_config()


def _fail(msg: str, code: int = 2):
    typer.echo(msg, err=True)
    raise typer.Exit(code)


_live = _guard(model.live)
live_hgs = _guard(model.live_hgs)
_task_states = _guard(model.task_states)
_submissions = model.submissions
_category = model.category


def _check_stage(stage: str) -> str:
    if stage not in core.STAGES:
        raise typer.BadParameter(f"stage must be one of {', '.join(core.STAGES)}")
    return stage


FAM_HELP = "restrict to a category (tfs) or a family (tfs.T-box), matched on whole id parts"

# written when `phylo tui` exits: mouse reporting off (1000/1002/1003/1006), leave the
# alternate screen, show the cursor, clear the screen and home the cursor
TERM_RESET = "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1049l\x1b[?25h\x1b[2J\x1b[H"


def _selected(cfg: core.Config, ids: Path | None, fam: str | None = None) -> set[str]:
    exp = core.expected(cfg)
    if ids is not None:
        exp &= set(core.read_ids(ids))
    if fam:
        exp = core.filter_fam(exp, fam)
        if not exp:
            _fail(f"no HGs match --fam {fam}", 1)
    return exp


def _missing(cfg: core.Config, stage: str, ids: Path | None, ready: bool = False,
             fam: str | None = None) -> list[str]:
    exp = _selected(cfg, ids, fam)
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)
    out = sorted(exp - done[stage])
    if ready:
        live = _live(core.expected(cfg)) or {}
        busy = live.get(stage, set())
        ok = core.ready_set(cfg, stage, [hg for hg in out if hg not in busy])
        out = [hg for hg in out if hg in ok]
    return out


BAR_WIDTH = 30


# Bar segments (done, running, ready, blocked) as (char, colour). `status` shows progress;
# `missing` blanks the done part so only the outstanding work is drawn.
BAR_STYLES = {
    "status":  (("█", "green"), ("▒", "cyan"), ("▓", "yellow"), ("░", "bright_black")),
    "missing": ((" ", None),    ("▒", "cyan"), ("█", "green"),  ("░", "bright_black")),
}
BAR_NAMES = ("done", "running", "ready", "blocked")


def _bar(done: int, running: int, ready: int, blocked: int, mode: str = "status") -> str:
    """Fixed-width bar split into done / running (in SLURM now) / ready to run / blocked;
    largest-remainder rounding so the segments always add up to BAR_WIDTH."""
    n = model.bar_segments((done, running, ready, blocked), BAR_WIDTH)
    if not n:
        return ""
    return "".join(typer.style(ch * k, fg=fg) for (ch, fg), k in zip(BAR_STYLES[mode], n))


def _summary(cfg: core.Config, ids: Path | None, mode: str = "status",
             fam: str | None = None) -> tuple[set[str], dict]:
    exp = _selected(cfg, ids, fam)
    rows, known, done = _guard(model.stage_rows)(cfg, exp)
    if not known:
        typer.echo("squeue not on PATH: running jobs not detected")
    legend = [typer.style(f"{ch} {name}", fg=fg) for (ch, fg), name
              in zip(BAR_STYLES[mode], BAR_NAMES) if ch.strip()]
    typer.echo(f"{'stage':<12} {'done':>6} {'running':>7} {'ready':>6} {'blocked':>8} {'total':>6}  "
               + " ".join(legend))
    for r in rows:
        if not r.applicable:
            typer.echo(f"{r.stage:<12} {'n/a':>6}")
            continue
        typer.echo(f"{r.stage:<12} {r.done:>6} {r.running:>7} {r.ready:>6} {r.blocked:>8} {r.total:>6}  "
                   + _bar(r.done, r.running, r.ready, r.blocked, mode))
    return exp, done


def _requested(a: history.Attempt) -> str:
    return f"{a.cpus}/{a.mem}/{a.time}"


def _used(a: history.Attempt) -> str:
    return f"{a.peak_rss}/{a.realtime}" if (a.peak_rss, a.realtime) != ("-", "-") else "–"


def _status_cell(a: history.Attempt) -> str:
    why = history.reason(a.status, a.exit)
    c = history.colour(a.status)
    return f"[{c}]{a.status}[/]" + (f" ({why})" if why else "")


def _hg_status(cfg: core.Config, hg: str, show_history: bool):
    """`status HG`: last attempt per stage, or (--history) every attempt, oldest first."""
    from rich.console import Console
    from rich.markup import escape
    from rich.table import Table

    exp = core.expected(cfg)
    if hg not in exp:
        _fail(f"unknown HG id: {hg}", 1)
    # not a terminal (pipe, file): wide enough that table cells and log paths are not wrapped
    con = Console(highlight=False, width=None if sys.stdout.isatty() else 400)
    atts = history.attempts(cfg, hg, warn=lambda m: con.print(f"[yellow]{m}[/]"))
    con.print(f"{hg}  ({core.nseq(cfg, hg)} seqs)")
    t = Table(box=None, header_style="bold")
    if show_history:
        for col in ("stage", "source", "run", "submitted", "att", "status (reason)", "requested",
                    "used", "log"):
            t.add_column(col, no_wrap=True)
        for a in atts:
            t.add_row(a.stage, a.source, a.run, a.submitted, str(a.attempt), _status_cell(a),
                      _requested(a), _used(a), escape(a.log))
        con.print(t)
        return
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)
    live = _live(core.expected(cfg)) or {}
    latest = history.latest_by_stage(atts)
    for col in ("stage", "state", "source", "run", "status (reason)", "requested", "used"):
        t.add_column(col)
    for st in core.STAGES:
        if not core.applicable(cfg, st):
            state = "n/a"
        elif hg in done[st]:
            state = "[green]done[/]"
        elif hg in live.get(st, set()):
            state = "[cyan]running[/]"
        elif hg in core.ready_set(cfg, st, [hg]):
            state = "[yellow]ready[/]"
        else:
            state = "[bright_black]blocked[/]"
        a = latest.get(st)
        if a is None:
            t.add_row(st, state, "–", "–", "–", "–", "–")
        else:
            t.add_row(st, state, a.source, a.run, _status_cell(a), _requested(a), _used(a))
    con.print(t)
    for st in core.STAGES:
        a = latest.get(st)
        if a is not None and a.status != "COMPLETED":
            con.print(f"log ({st}): {escape(a.log)}", soft_wrap=True)


@app.command()
def status(hg: str = typer.Argument(None, help="HG id: show its last attempt per stage "
                                               "(requested vs used resources, Nextflow + phylocli)"),
           ids: Path = typer.Option(None, "--ids", help="restrict to the HG ids in this file"),
           fam: str = typer.Option(None, "--fam", "-f", help=FAM_HELP),
           history_: bool = typer.Option(False, "--history",
                                         help="with HG: one row per attempt, oldest first")):
    """Per-stage bars of done / ready / blocked HGs, and the overall done count.
    With an HG id: per-stage state and the latest job (requested / used resources)."""
    cfg = _cfg()
    if not (cfg.outdir / "clusters").is_dir():
        _fail(f"no clusters/ in {cfg.outdir}", 1)
    if hg is not None:
        if ids is not None or fam:
            _fail("status HG cannot be combined with --ids / --fam", 2)
        _hg_status(cfg, hg, history_)
        return
    if history_:
        _fail("--history needs an HG id", 2)
    exp, done = _summary(cfg, ids, mode="status", fam=fam)
    final = "possvm" if done["generax"] else "possvm_prev"
    n = len(done[final])
    typer.echo(f"\n{n}/{len(exp)} HGs done ({100 * n / max(len(exp), 1):.1f} %; done = {final})")


@app.command()
def missing(stage: str = typer.Argument(None, help="stage; omit for a per-stage summary"),
            ids: Path = typer.Option(None, "--ids"),
            fam: str = typer.Option(None, "--fam", "-f", help=FAM_HELP),
            all_: bool = typer.Option(False, "--all",
                                      help="also list HGs whose inputs for STAGE do not exist yet"),
            per_fam: bool = typer.Option(False, "--per-fam",
                                         help="print 'family missing/total' per family instead of ids")):
    """Without STAGE: per-stage counts of done / ready / blocked HGs with a bar.
    With STAGE: print HG ids not done for STAGE whose inputs exist (--all: every HG not done)."""
    if stage is None:
        _summary(_cfg(), ids, mode="missing", fam=fam)
        return
    _check_stage(stage)
    cfg = _cfg()
    todo = _missing(cfg, stage, ids, ready=not all_, fam=fam)
    if not per_fam:
        for hg in todo:
            typer.echo(hg)
        return
    family = lambda hg: hg.rsplit(".", 1)[0]  # noqa: E731  tfs.T-box.HG1 -> tfs.T-box
    total = collections.Counter(family(h) for h in _selected(cfg, ids, fam))
    n_todo = collections.Counter(family(h) for h in todo)
    w = max([len(f) for f in n_todo] + [len("family")])
    # ready = not done for STAGE and inputs present; missing (--all) = not done for STAGE
    typer.echo(f"{'family':<{w}}  {'missing' if all_ else 'ready'}/total")
    for f in sorted(n_todo, key=lambda f: (-n_todo[f], -total[f], f)):
        typer.echo(f"{f:<{w}}  {n_todo[f]}/{total[f]}")


def _preflight(stage: str):
    msg = model.preflight(stage)
    if msg:
        _fail(msg, 78)


def _print_dry_run(stage: str, run_dir: Path, plan: list, qos: str | None, notes: list[str]):
    """Dry-run report with rich (the library typer uses for its own help/errors)."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    con = Console(highlight=False)
    n = sum(len(ids_) for _res, ids_, _f, _s in plan)
    try:
        shown = run_dir.relative_to(ROOT)
    except ValueError:
        shown = run_dir
    body = [f"[bold]run dir[/]  {shown}", f"[bold]HGs[/]      {n} in {len(plan)} array(s)"]
    body += [f"[dim]{note}[/]" for note in notes]
    con.print(Panel.fit("\n".join(body), title=f"dry run · {stage}", title_align="left",
                        border_style="cyan"))
    t = Table(box=None, header_style="bold")
    for col in ("array", "HGs", "cpus", "memory", "time", "qos", "signal"):
        t.add_column(col, justify="right" if col in ("HGs", "cpus", "memory") else "left")
    for k, (res, ids_, _f, _s) in enumerate(plan):
        t.add_row(str(k), str(len(ids_)), str(res.cpus), _fmt_mem(res.mem_mb),
                  _fmt_time(res.time_min), qos or res.qos, res.signal or "–")
    con.print(t)
    few = 5
    for k, (_res, ids_, _f, _s) in enumerate(plan):
        con.print(f"[dim]array {k}: {', '.join(ids_[:few])}"
                  + (f", … (+{len(ids_) - few} more)" if len(ids_) > few else "") + "[/]",
                  soft_wrap=True)
    con.print(f"[yellow]nothing submitted (dry run)[/] · scripts in {shown}/array_*.sbatch",
              soft_wrap=True)


@app.command()
def submit(stage: str = typer.Argument(...),
           hgs: list[str] = typer.Argument(None, help="HG ids"),
           missing_: bool = typer.Option(False, "--missing", help="HGs not done for STAGE (only those whose inputs exist, unless --all)"),
           ids: Path = typer.Option(None, "--ids", help="HG ids file"),
           fam: str = typer.Option(None, "--fam", "-f", help=FAM_HELP),
           all_: bool = typer.Option(False, "--all",
                                     help="strict: refuse the whole submission if any HG lacks inputs "
                                          "or is already queued (default: skip those HGs)"),
           dry_run: bool = typer.Option(False, "--dry-run", "-n",
                                        help="show the arrays and write the scripts, do not submit"),
           max_running: int = typer.Option(50, "--max-running"),
           partition: str = typer.Option(None, "--partition"),
           qos: str = typer.Option(None, "--qos"),
           mem: str = typer.Option(None, "--mem", help="override memory for every HG, e.g. 16G, 800M"),
           time: str = typer.Option(None, "--time", help="override time limit for every HG, e.g. 24h, 90m, 1d"),
           cpus: int = typer.Option(None, "--cpus", min=1, help="override cpus for every HG"),
           sets: list[str] = typer.Option(None, "--set",
                                          help="override a config.yaml param for this submission, "
                                               "e.g. --set MAX_SPR=2 (repeatable)")):
    """Submit one SLURM array per resource group for STAGE."""
    import yaml

    _check_stage(stage)
    # The submission's config = config.yaml + --set overrides. It is written into the run dir
    # and the jobs read that copy, so the run keeps a record and config.yaml is never changed.
    raw = yaml.safe_load(Path(os.environ.get("PHYLOCLI_CONFIG")
                              or core.ROOT / "phylocli/config.yaml").read_text())
    try:
        override = {"mem_mb": core.parse_mem_mb(mem) if mem else None,
                    "time_min": core.parse_time_min(time) if time else None,
                    "cpus": cpus}
        set_notes = core.apply_sets(raw, sets or [])
    except ValueError as e:
        _fail(f"ERROR: {e}", 2)
    cfg = core.config_from_raw(raw)
    if not core.applicable(cfg, stage):
        _fail(f"not_applicable: stage {stage} does not run with run_generax="
              f"{cfg.params.get('run_generax')}, gxsup={cfg.params.get('gxsup')}; nothing submitted", 2)
    hgs = hgs or []
    if (missing_ + (ids is not None) + bool(hgs)) != 1:
        raise typer.BadParameter("give exactly one of --missing, --ids FILE, or HG ids")
    if missing_:
        selected = _missing(cfg, stage, None)
    elif ids is not None:
        selected = core.read_ids(ids)
    else:
        selected = list(dict.fromkeys(hgs))
    if fam:
        keep = core.filter_fam(selected, fam)
        selected = [hg for hg in selected if hg in keep]
        if not selected:
            _fail(f"no HGs match --fam {fam}", 1)
    try:
        sel = model.select(cfg, stage, selected, all_=all_, dry_run=dry_run)
    except model.ModelError as e:
        if e.code == 2:                     # unknown ids: same two stderr lines as before
            for line in str(e).splitlines():
                typer.echo(line, err=True)
            raise typer.Exit(2)
        _fail(str(e), e.code)
    sel.notes[:0] = set_notes               # printed plainly on submit, inside the panel on a dry run
    if not sel.selected:
        for note in sel.notes:
            typer.echo(note)
        typer.echo("nothing to submit")
        raise typer.Exit(0)
    _preflight(stage)
    over = [f"{k}={v}" for k, v in (("--mem", mem), ("--time", time), ("--cpus", cpus)) if v]
    p = model.plan(cfg, stage, sel, override, over_flags=over)
    if p.errors:
        for k, v in p.errors.items():
            typer.echo(f"{k} ({len(v)}): {_show(v)}", err=True)
        typer.echo("nothing submitted", err=True)
        raise typer.Exit(2)
    w = model.write_run(cfg, raw, p, dry_run, max_running, partition, qos)
    if dry_run:
        _print_dry_run(stage, w.run_dir, w.arrays, qos, p.notes)
        return
    for note in p.notes:
        typer.echo(note)
    typer.echo(f"run dir: {w.run_dir}")
    jids, err = model.sbatch_all(w)
    for jid, (res, ids_, _f, _s) in zip(jids, w.arrays):
        typer.echo(f"submitted {jid}: {len(ids_)} HGs ({res.cpus} cpus, {res.mem_mb}M, {res.time_min} min)")
    if err:
        for line in err.splitlines():
            typer.echo(line, err=True)
        raise typer.Exit(1)


# SLURM job states (common.py) -> the four columns of `jobs`.
JOB_COLS = (("pending", "yellow"), ("running", "cyan"), ("done", "green"), ("failed", "red"))
STATE_COLOUR = dict(JOB_COLS)
# jobs bar: segment order and glyphs (distinct glyphs keep it readable without colour)
JOB_BAR = (("done", "█"), ("failed", "×"), ("running", "▓"), ("pending", "░"))
JOB_BAR_WIDTH = 20


def _job_bar(c: collections.Counter) -> str:
    """Fixed-width rich-markup bar of task states; largest-remainder rounding so the
    segments always add up to JOB_BAR_WIDTH."""
    total = sum(c[k] for k, _ in JOB_BAR)
    if total == 0:
        return ""
    exact = [JOB_BAR_WIDTH * c[k] / total for k, _ in JOB_BAR]
    n = [int(x) for x in exact]
    for i in sorted(range(len(n)), key=lambda i: exact[i] - n[i], reverse=True)[:JOB_BAR_WIDTH - sum(n)]:
        n[i] += 1
    return "".join(f"[{STATE_COLOUR[k]}]{ch * m}[/]" for (k, ch), m in zip(JOB_BAR, n) if m)


@app.command()
def jobs(job_id: str = typer.Argument(None, help="array job id: list its tasks with their HG ids"),
         stage: str = typer.Option(None, "--stage", help="only submissions of this stage"),
         last: int = typer.Option(10, "--last", min=1, help="newest N submissions"),
         failed: bool = typer.Option(False, "--failed",
                                     help="list failed HGs with their state and .err log"),
         running: bool = typer.Option(False, "--running", help="with JOB_ID: only running tasks")):
    """Submitted arrays with pending / running / done / failed task counts (via sacct).
    With JOB_ID: one row per array task — task index, HG id, state, log."""
    from rich.console import Console
    from rich.table import Table

    if job_id is not None:
        _job_tasks(job_id, failed, running)
        return
    subs = _submissions(stage, last)
    if not subs:
        typer.echo("no submissions in " + str(_runs_dir()))
        return
    states = _task_states(sorted({jid for _r, _s, jid, _f in subs}))
    con = Console(highlight=False)
    known = states is not None
    if not known:
        con.print("[yellow]sacct not on PATH: task states unknown[/]")
        states = {}
    if failed:
        for run, st, jid, ids_file in subs:
            hgs = core.read_ids(ids_file) if ids_file.is_file() else []
            for i, state in sorted(states.get(jid, {}).items()):
                if _category(state) == "failed" and i < len(hgs):
                    log = run / "logs" / f"{st}_{jid}_{i}.err"
                    con.print(f"{hgs[i]}\t[red]{state}[/]\t{log}", soft_wrap=True)
        return
    t = Table(box=None, header_style="bold")
    for col in ("run", "stage", "job", "HGs"):
        t.add_column(col, justify="right" if col == "HGs" else "left")
    for col, colour in JOB_COLS:
        t.add_column(f"[{colour}]{col}[/]", justify="right")
    t.add_column("progress", no_wrap=True)
    rows, _known = _guard(model.array_rows)(stage, last)
    for r in rows:
        cells = ([f"[{colour}]{r.counts[col]}[/]" if r.counts[col] else "[dim]0[/]"
                  for col, colour in JOB_COLS] if known else ["?"] * len(JOB_COLS))
        t.add_row(r.run.name.split("_")[0], r.stage, r.job, str(r.n), *cells,
                  _job_bar(r.counts) if known else "")
    con.print(t)


@app.command()
def tui(refresh: int = typer.Option(30, "--refresh", min=5, help="seconds between refreshes")):
    """Interactive view: stages, HGs, arrays; select failed HGs and resubmit them."""
    try:
        from phylocli import tui as tui_mod
    except ModuleNotFoundError as e:
        if (e.name or "").startswith("textual"):
            _fail("textual not installed: pip install textual", 1)
        raise
    try:
        tui_mod.PhyloApp(_cfg(), refresh_s=refresh, raw=tui_mod.load_raw()).run(mouse=False)
    finally:
        # Leave a clean terminal however the app ended (q, Ctrl-C, crash): mouse reporting
        # off, main screen, cursor shown, then clear (else e.g. "35;98;12M" leaks into the shell).
        sys.stdout.write(TERM_RESET)
        sys.stdout.flush()


def _job_tasks(job_id: str, failed: bool, running: bool):
    """One row per task of one array job: SLURM shows a single name for the whole array, so
    the HG of task i is read from line i+1 of the ids file the array was submitted with."""
    from rich.console import Console
    from rich.table import Table

    sub = next((s for s in _submissions(None, 10 ** 6) if s[2] == job_id), None)
    if sub is None:
        _fail(f"job {job_id} is not a phylocli submission in {_runs_dir()}", 1)
    run, st, jid, ids_file = sub
    hgs = core.read_ids(ids_file) if ids_file.is_file() else []
    states = _task_states([jid])
    con = Console(highlight=False)
    if states is None:
        con.print("[yellow]sacct not on PATH: task states unknown[/]")
    t = Table(box=None, header_style="bold")
    for col in ("task", "HG", "state", "log"):
        t.add_column(col)
    for i, hg in enumerate(hgs):
        state = (states or {}).get(jid, {}).get(i, "PENDING" if states is not None else "?")
        cat = _category(state) if states is not None else None
        if (failed and cat != "failed") or (running and cat != "running"):
            continue
        shown = f"[{STATE_COLOUR[cat]}]{state}[/]" if cat else state
        t.add_row(str(i), hg, shown, f"{st}_{jid}_{i}.err")
    con.print(f"[bold]{jid}[/] · {st} · {len(hgs)} HGs · logs in {run / 'logs'}", soft_wrap=True)
    con.print(t)


@app.command("queue", hidden=True)
def queue(stage: str = typer.Option(None, "--stage"), last: int = typer.Option(10, "--last"),
          failed: bool = typer.Option(False, "--failed")):
    """Old name of `jobs`."""
    jobs(job_id=None, stage=stage, last=last, failed=failed, running=False)


@app.command("_run", hidden=True)
def _run(stage: str, hg: str, run_dir: Path = typer.Option(..., "--run-dir")):
    """Run one stage for one HG (used inside the array task)."""
    raise typer.Exit(run_one(_cfg(), stage, hg, Path(run_dir) / "work"))


if __name__ == "__main__":
    app()
