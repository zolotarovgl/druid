#!/usr/bin/env python3
"""phylo: progress report and per-stage SLURM job arrays for the step2 pipeline."""
from __future__ import annotations

import collections
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
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

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Report step2 progress and submit per-stage SLURM job arrays.")

TOOLS = {"align": ["mafft", "clipkit"], "tree": ["iqtree2"], "generax": ["generax", "mpirun"],
         "gxsup": ["iqtree2"], "possvm": [], "possvm_prev": []}
MAX_ARRAY = 1000  # SLURM MaxArraySize default 1001 -> indices 0..1000
SHOW = 20

SBATCH = """#!/usr/bin/env bash
#SBATCH --job-name=phylo-{stage}
#SBATCH --partition={partition}
#SBATCH --qos={qos}
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={mem_mb}M
#SBATCH --time={time_min}
#SBATCH --array=0-{n_minus_1}%{max_running}
#SBATCH --output={run_dir}/logs/{stage}_%A_%a.out
#SBATCH --error={run_dir}/logs/{stage}_%A_%a.err
{signal_line}
set -uo pipefail
HG=$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" "{ids_file}")
echo "phylo {stage} ${{HG}} (array ${{SLURM_ARRAY_JOB_ID}}_${{SLURM_ARRAY_TASK_ID}})"
export PHYLOCLI_CONFIG="{run_dir}/config.yaml"
python3 "{root}/phylocli/phylo.py" _run {stage} "$HG" --run-dir "{run_dir}" &
PID=$!
trap 'kill -USR2 $PID 2>/dev/null' USR2
trap 'kill -TERM $PID 2>/dev/null' TERM
wait $PID; RC=$?
while kill -0 $PID 2>/dev/null; do wait $PID; RC=$?; done
exit $RC
"""


def _cfg() -> core.Config:
    p = os.environ.get("PHYLOCLI_CONFIG")
    return core.load_config(Path(p)) if p else core.load_config()


def _fail(msg: str, code: int = 2):
    typer.echo(msg, err=True)
    raise typer.Exit(code)


def _check_stage(stage: str) -> str:
    if stage not in core.STAGES:
        raise typer.BadParameter(f"stage must be one of {', '.join(core.STAGES)}")
    return stage


def _show(ids: list[str]) -> str:
    s = " ".join(ids[:SHOW])
    return s + (f" ... and {len(ids) - SHOW} more" if len(ids) > SHOW else "")


FAM_HELP = "restrict to a category (tfs) or a family (tfs.T-box), matched on whole id parts"


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
        ok = core.ready_set(cfg, stage, out)
        out = [hg for hg in out if hg in ok]
    return out


BAR_WIDTH = 30


# Bar segments (done, ready, blocked) as (char, colour). `status` shows progress;
# `missing` blanks the done part so only the outstanding work is drawn.
BAR_STYLES = {
    "status":  (("█", "green"), ("▓", "yellow"), ("░", "bright_black")),
    "missing": ((" ", None),    ("█", "green"),  ("░", "bright_black")),
}


def _bar(done: int, ready: int, blocked: int, mode: str = "status") -> str:
    """Fixed-width bar split into done / ready to run / blocked (no inputs)."""
    total = done + ready + blocked
    if total == 0:
        return ""
    n_done = round(BAR_WIDTH * done / total)
    n_ready = min(round(BAR_WIDTH * ready / total), BAR_WIDTH - n_done)
    n_blocked = BAR_WIDTH - n_done - n_ready
    return "".join(typer.style(ch * n, fg=fg) for (ch, fg), n
                   in zip(BAR_STYLES[mode], (n_done, n_ready, n_blocked)))


def _summary(cfg: core.Config, ids: Path | None, mode: str = "status",
             fam: str | None = None) -> tuple[set[str], dict]:
    exp = _selected(cfg, ids, fam)
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)
    legend = [typer.style(f"{ch} {name}", fg=fg) for (ch, fg), name
              in zip(BAR_STYLES[mode], ("done", "ready", "blocked")) if ch.strip()]
    typer.echo(f"{'stage':<12} {'done':>6} {'ready':>6} {'blocked':>8} {'total':>6}  "
               + " ".join(legend))
    for st in core.STAGES:
        if not core.applicable(cfg, st):
            typer.echo(f"{st:<12} {'n/a':>6}")
            continue
        todo = exp - done[st]
        n_ready = len(core.ready_set(cfg, st, todo))
        n_done = len(done[st])
        n_blocked = len(todo) - n_ready
        typer.echo(f"{st:<12} {n_done:>6} {n_ready:>6} {n_blocked:>8} {len(exp):>6}  "
                   + _bar(n_done, n_ready, n_blocked, mode))
    return exp, done


def _squeue(fmt: str) -> list[str] | None:
    if shutil.which("squeue") is None:
        return None
    r = subprocess.run(["squeue", "--me", "-h", "-o", fmt], capture_output=True, text=True)
    if r.returncode != 0:
        _fail(f"squeue failed: {r.stderr.strip()}", 1)
    return r.stdout.splitlines()


def _jobs_map() -> dict[str, Path]:
    out = {}
    for f in sorted(_runs_dir().glob("*/jobs.tsv")):
        for line in f.read_text().splitlines():
            if "\t" in line:
                jid, ids = line.split("\t", 1)
                out[jid.strip()] = _ids_path(f.parent, ids.strip())
    return out


def live_hgs(stage: str, allow_no_squeue: bool = False) -> set[str]:
    lines = _squeue("%F %j")
    if lines is None:
        if allow_no_squeue:
            return set()
        _fail("squeue not on PATH: cannot check for already queued HGs (only --dry-run may skip this)", 1)
    jobs = _jobs_map()
    live: set[str] = set()
    for line in lines:
        parts = line.split()
        if len(parts) == 2 and parts[1] == f"phylo-{stage}" and parts[0] in jobs:
            f = jobs[parts[0]]
            if f.is_file():
                live |= set(core.read_ids(f))
    return live


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
    latest = history.latest_by_stage(atts)
    for col in ("stage", "state", "source", "run", "status (reason)", "requested", "used"):
        t.add_column(col)
    for st in core.STAGES:
        if not core.applicable(cfg, st):
            state = "n/a"
        elif hg in done[st]:
            state = "[green]done[/]"
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
    lost = [t for t in TOOLS[stage] if shutil.which(t) is None]
    hint = ("       run 'conda activate phylo' and 'module load OpenMPI' before submitting;\n"
            "       see workflow/environment.yaml.")
    py_err = None
    if stage != "gxsup":  # same `python` + PYTHONNOUSERSITE=1 as the stage scripts
        py = shutil.which("python")
        if py is None:
            py_err = "python: not on PATH"
        else:
            r = subprocess.run([py, "-c", "import ete3, Bio, yaml"], capture_output=True, text=True,
                               env={**os.environ, "PYTHONNOUSERSITE": "1"})
            if r.returncode != 0:
                py_err = (f"{py} (PYTHONNOUSERSITE=1) cannot import ete3, Bio, yaml:\n"
                          f"       {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'exit ' + str(r.returncode)}")
    if lost or py_err:
        msg = "ERROR:"
        if lost:
            msg += f" not on PATH: {' '.join(lost)}"
        if py_err:
            msg += f"\n       {py_err}"
        _fail(msg + "\n" + hint, 78)


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


def _chunks(ids: list[str], n: int = MAX_ARRAY) -> list[list[str]]:
    return [ids[i:i + n] for i in range(0, len(ids), n)]


def _new_run_dir(stage: str, dry_run: bool = False) -> Path:
    # A dry run writes its scripts under the system temp dir, so runs/ only holds real
    # submissions (queue and the already-queued check read runs/*/jobs.tsv).
    root = Path(tempfile.gettempdir()) / "phylocli-dryrun" if dry_run else _runs_dir()
    base = root / f"{datetime.now():%Y%m%d-%H%M%S}_{stage}"
    d, k = base, 1
    while True:
        try:
            d.mkdir(parents=True)
            break
        except FileExistsError:
            k += 1
            d = base.with_name(f"{base.name}-{k}")
    (d / "logs").mkdir()
    return d


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
    # Ids that are not expected HGs (typos like a trailing ".") are always an error, before the
    # default mode would otherwise skip them silently as "without inputs".
    unknown = sorted(set(selected) - core.expected(cfg))
    if unknown:
        typer.echo(f"unknown ({len(unknown)}): {_show(unknown)}", err=True)
        typer.echo("nothing submitted", err=True)
        raise typer.Exit(2)
    queued = live_hgs(stage, allow_no_squeue=dry_run)
    notes: list[str] = list(set_notes)   # printed plainly on submit, inside the panel on a dry run
    if not all_:
        unready = [hg for hg in selected if not core.inputs_ready(cfg, stage, hg)]
        busy = [hg for hg in selected if hg in queued and hg not in unready]
        if unready:
            notes.append(f"skipped {len(unready)} HGs without inputs")
        if busy:
            notes.append(f"skipped {len(busy)} HGs already queued")
        drop = set(unready) | set(busy)
        selected = [hg for hg in selected if hg not in drop]
    if not selected:
        for note in notes:
            typer.echo(note)
        typer.echo("nothing to submit")
        raise typer.Exit(0)
    _preflight(stage)
    errs = core.validate(cfg, stage, selected, queued)
    bad = {k: v for k, v in errs.items() if v}
    if bad:
        for k, v in bad.items():
            typer.echo(f"{k} ({len(v)}): {_show(v)}", err=True)
        typer.echo("nothing submitted", err=True)
        raise typer.Exit(2)
    n_rows = core.resources_rows(cfg, selected)
    over = [f"{k}={v}" for k, v in (("--mem", mem), ("--time", time), ("--cpus", cpus)) if v]
    notes.append(f"resources.tsv: row found for {n_rows} of {len(selected)} HGs"
                 + (" (others: step2 defaults)" if n_rows < len(selected) else "")
                 + (f"; overridden by {' '.join(over)}" if over else ""))
    groups = core.group(cfg, stage, selected, override)
    run_dir = _new_run_dir(stage, dry_run)
    (run_dir / "config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    plan = []
    pieces = [(res, c) for res, g in groups.items() for c in _chunks(g)]
    for k, (res, ids_) in enumerate(pieces):
        ids_file = run_dir / f"ids_{k}.txt"
        ids_file.write_text("\n".join(ids_) + "\n")
        script = run_dir / f"array_{k}.sbatch"
        script.write_text(SBATCH.format(
            stage=stage, partition=partition or cfg.partition, qos=qos or res.qos,
            cpus=res.cpus, mem_mb=res.mem_mb, time_min=res.time_min,
            n_minus_1=len(ids_) - 1, max_running=max_running, run_dir=run_dir,
            signal_line=f"#SBATCH --signal={res.signal}" if res.signal else "",
            ids_file=ids_file, root=ROOT))
        plan.append((res, ids_, ids_file, script))
    if dry_run:
        _print_dry_run(stage, run_dir, plan, qos, notes)
        return
    for note in notes:
        typer.echo(note)
    typer.echo(f"run dir: {run_dir}")
    submitted = []
    for i, (res, ids_, ids_file, script) in enumerate(plan):
        r = subprocess.run(["sbatch", "--parsable", str(script)], capture_output=True, text=True)
        jid = r.stdout.strip().split(";")[0]
        if r.returncode != 0 or not jid:
            typer.echo(f"sbatch failed for {script}: {r.stderr.strip()}", err=True)
            typer.echo(f"submitted job ids: {' '.join(submitted) or 'none'}", err=True)
            typer.echo("not submitted: " + " ".join(str(p[3]) for p in plan[i:]), err=True)
            raise typer.Exit(1)
        with open(run_dir / "jobs.tsv", "a") as fh:
            fh.write(f"{jid}\t{ids_file}\n")
        submitted.append(jid)
        typer.echo(f"submitted {jid}: {len(ids_)} HGs ({res.cpus} cpus, {res.mem_mb}M, {res.time_min} min)")


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


def _category(state: str) -> str:
    if state == "COMPLETED":
        return "done"
    if state in FAILED_STATES:
        return "failed"
    if state in RUNNING_STATES:
        return "running"
    return "pending"


def _task_states(job_ids: list[str]) -> dict[str, dict[int, str]] | None:
    """{array job id: {task index: SLURM state}} from sacct; None if sacct is unavailable."""
    if not job_ids or shutil.which("sacct") is None:
        return None if job_ids else {}
    r = subprocess.run(["sacct", "-n", "-P", "-X", "-j", ",".join(job_ids), "-o", "JobID,State"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        _fail(f"sacct failed: {r.stderr.strip()}", 1)
    out: dict[str, dict[int, str]] = {}
    for line in r.stdout.splitlines():
        if "|" not in line:
            continue
        jid, state = line.split("|", 1)
        state = state.split()[0] if state.split() else "UNKNOWN"   # "CANCELLED by 1000"
        master, _, idx = jid.partition("_")
        idxs = _expand_indices(idx.strip("[]")) if idx else []
        for i in idxs:
            out.setdefault(master, {})[i] = state
    return out


def _submissions(stage: str | None, last: int) -> list[tuple[Path, str, str, Path]]:
    """(run dir, stage, job id, ids file) for the newest `last` real submissions."""
    rows = []
    for f in sorted(_runs_dir().glob("*/jobs.tsv"), key=lambda p: p.parent.name, reverse=True):
        st = f.parent.name.split("_", 2)[-1]
        if stage and st != stage:
            continue
        for line in f.read_text().splitlines():
            if "\t" in line:
                jid, ids = line.split("\t", 1)
                rows.append((f.parent, st, jid.strip(), _ids_path(f.parent, ids.strip())))
    runs = list(dict.fromkeys(r[0] for r in rows))[:last]
    return [r for r in rows if r[0] in runs]


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
    for run, st, jid, ids_file in subs:
        n = len(core.read_ids(ids_file)) if ids_file.is_file() else 0
        c = collections.Counter(_category(s) for s in states.get(jid, {}).values())
        c["pending"] += max(n - sum(c.values()), 0)        # tasks sacct has not reported yet
        cells = ([f"[{colour}]{c[col]}[/]" if c[col] else "[dim]0[/]" for col, colour in JOB_COLS]
                 if known else ["?"] * len(JOB_COLS))
        t.add_row(run.name.split("_")[0], st, jid, str(n), *cells, _job_bar(c) if known else "")
    con.print(t)




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
