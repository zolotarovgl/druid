"""Data layer of phylocli: everything the CLI (phylo.py) and the TUI (tui.py) show or submit,
computed without printing. Errors are raised as ModelError(msg, code); phylo.py turns them
into the same message + exit code it always printed."""
from __future__ import annotations

import collections
import dataclasses
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from phylocli import core, history
from phylocli.common import FAILED_STATES, RUNNING_STATES, ROOT, expand_indices, ids_path, runs_dir

SLURM_TIMEOUT = 60  # seconds; a stuck slurmctld must not hang the CLI or freeze the TUI


class ModelError(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def _slurm(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=SLURM_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ModelError(f"{cmd[0]} timed out after {SLURM_TIMEOUT} s", 1) from None


def squeue(fmt: str, array_tasks: bool = False) -> list[str] | None:
    if shutil.which("squeue") is None:
        return None
    r = _slurm(["squeue", "--me", "-h"] + (["-r"] if array_tasks else []) + ["-o", fmt])
    if r.returncode != 0:
        raise ModelError(f"squeue failed: {r.stderr.strip()}", 1)
    return r.stdout.splitlines()


def jobs_map() -> dict[str, Path]:
    out = {}
    for f in sorted(runs_dir().glob("*/jobs.tsv")):
        for line in f.read_text().splitlines():
            if "\t" in line:
                jid, ids = line.split("\t", 1)
                out[jid.strip()] = ids_path(f.parent, ids.strip())
    return out


def nf_job(name: str) -> tuple[str, str] | None:
    """(process, tag) from a Nextflow SLURM job name like nf-PHY_(tfs.T-box.HG1). Process
    names contain underscores (PVM_PREV, GR_watcher), so match the known names, longest first."""
    body = name[len("nf-"):]
    for proc in sorted(history.PROC_STAGE, key=len, reverse=True):
        if body.startswith(proc + "_"):
            return proc, body[len(proc) + 1:].strip("()")
    return None


def live(expected: set) -> dict[str, set[str]] | None:
    """stage -> ids pending or running in SLURM right now: tasks of phylocli arrays (`squeue -r`
    lists each array task; task i = line i+1 of its ids file) and Nextflow jobs (named
    nf-<PROCESS>_(<tag>)). None when squeue is not on PATH."""
    lines = squeue("%i|%.300j", array_tasks=True)
    if lines is None:
        return None
    jobs = jobs_map()
    cache: dict[Path, list[str]] = {}
    out: dict[str, set[str]] = collections.defaultdict(set)
    for line in lines:
        if "|" not in line:
            continue
        jid, name = (x.strip() for x in line.split("|", 1))
        if name.startswith("phylo-"):
            master, _, idx = jid.partition("_")
            f = jobs.get(master)
            if f is None or not f.is_file():
                continue
            ids = cache.setdefault(f, core.read_ids(f))
            idxs = ([int(idx)] if idx.isdigit()
                    else expand_indices(idx.strip("[]")) if idx else range(len(ids)))
            out[name[len("phylo-"):]].update(ids[i] for i in idxs if i < len(ids))
        elif name.startswith("nf-"):
            nf = nf_job(name)
            if nf:
                hg = history._resolve_tag(nf[1], expected)
                if hg:
                    out[history.PROC_STAGE[nf[0]]].add(hg)
    return dict(out)


def live_hgs(stage: str, allow_no_squeue: bool = False, expected: set | None = None) -> set[str]:
    lv = live(expected if expected is not None else set())
    if lv is None:
        if allow_no_squeue:
            return set()
        raise ModelError("squeue not on PATH: cannot check for already queued HGs "
                         "(only --dry-run may skip this)", 1)
    return lv.get(stage, set())


def category(state: str) -> str:
    if state == "COMPLETED":
        return "done"
    if state in FAILED_STATES:
        return "failed"
    if state in RUNNING_STATES:
        return "running"
    return "pending"


def task_states(job_ids: list[str]) -> dict[str, dict[int, str]] | None:
    """{array job id: {task index: SLURM state}} from sacct; None if sacct is unavailable."""
    if not job_ids or shutil.which("sacct") is None:
        return None if job_ids else {}
    r = _slurm(["sacct", "-n", "-P", "-X", "-j", ",".join(job_ids), "-o", "JobID,State"])
    if r.returncode != 0:
        raise ModelError(f"sacct failed: {r.stderr.strip()}", 1)
    out: dict[str, dict[int, str]] = {}
    for line in r.stdout.splitlines():
        if "|" not in line:
            continue
        jid, state = line.split("|", 1)
        state = state.split()[0] if state.split() else "UNKNOWN"   # "CANCELLED by 1000"
        master, _, idx = jid.partition("_")
        idxs = expand_indices(idx.strip("[]")) if idx else []
        for i in idxs:
            out.setdefault(master, {})[i] = state
    return out


def submissions(stage: str | None, last: int) -> list[tuple[Path, str, str, Path]]:
    """(run dir, stage, job id, ids file) for the newest `last` real submissions."""
    rows = []
    for f in sorted(runs_dir().glob("*/jobs.tsv"), key=lambda p: p.parent.name, reverse=True):
        st = f.parent.name.split("_", 2)[-1]
        if stage and st != stage:
            continue
        for line in f.read_text().splitlines():
            if "\t" in line:
                jid, ids = line.split("\t", 1)
                rows.append((f.parent, st, jid.strip(), ids_path(f.parent, ids.strip())))
    runs = list(dict.fromkeys(r[0] for r in rows))[:last]
    return [r for r in rows if r[0] in runs]


@dataclass
class StageRow:
    stage: str
    applicable: bool
    done: int = 0
    running: int = 0
    ready: int = 0
    blocked: int = 0
    total: int = 0


def stage_rows(cfg: core.Config, exp: set[str]):
    """(rows, live_known, done-by-stage) — exactly the counts `phylo status` draws."""
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)
    lv = live(core.expected(cfg))
    known = lv is not None
    lv = lv or {}
    rows = []
    for st in core.STAGES:
        if not core.applicable(cfg, st):
            rows.append(StageRow(st, False))
            continue
        todo = exp - done[st]
        running = todo & lv.get(st, set())
        n_ready = len(core.ready_set(cfg, st, todo - running))
        rows.append(StageRow(st, True, len(done[st]), len(running), n_ready,
                             len(todo) - len(running) - n_ready, len(exp)))
    return rows, known, done


@dataclass
class HGRow:
    hg: str
    state: str
    last: "history.Attempt | None" = None


def _latest_for(atts: list, stage: str) -> dict[str, "history.Attempt"]:
    out: dict = {}
    for a in sorted(atts, key=lambda a: (a.submitted, a.attempt, a.run)):
        if a.stage == stage:
            out[a.hg] = a
    return out


def hg_rows(cfg: core.Config, stage: str, exp: set[str] | None = None,
            atts: list | None = None) -> list[HGRow]:
    """One row per expected HG for `stage`. failed = inputs present, not done, not queued,
    and the latest attempt at this stage ended in a FAILED_STATES state."""
    exp = core.expected(cfg) if exp is None else exp
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)[stage]
    busy = (live(core.expected(cfg)) or {}).get(stage, set())
    todo = exp - done
    ready = core.ready_set(cfg, stage, todo - busy)
    latest = _latest_for(history.attempts(cfg) if atts is None else atts, stage)
    rows = []
    for hg in sorted(exp):
        a = latest.get(hg)
        if hg in done:
            state = "done"
        elif hg in busy:
            state = "running"
        elif hg in ready:
            state = "failed" if a is not None and a.status in FAILED_STATES else "ready"
        else:
            state = "blocked"
        rows.append(HGRow(hg, state, a))
    return rows


@dataclass
class HGDetail:
    hg: str
    nseq: int
    states: dict
    latest: dict


def hg_detail(cfg: core.Config, hg: str, atts: list | None = None) -> HGDetail:
    exp = core.expected(cfg)
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)
    lv = live(exp) or {}
    states = {}
    for st in core.STAGES:
        if not core.applicable(cfg, st):
            states[st] = "n/a"
        elif hg in done[st]:
            states[st] = "done"
        elif hg in lv.get(st, set()):
            states[st] = "running"
        elif hg in core.ready_set(cfg, st, [hg]):
            states[st] = "ready"
        else:
            states[st] = "blocked"
    atts = history.attempts(cfg, hg) if atts is None else [a for a in atts if a.hg == hg]
    return HGDetail(hg, core.nseq(cfg, hg), states, history.latest_by_stage(atts))


@dataclass
class ArrayRow:
    run: Path
    stage: str
    job: str
    n: int
    counts: collections.Counter


def array_rows(stage: str | None = None, last: int = 10):
    """(rows, sacct_known): the table `phylo jobs` prints."""
    subs = submissions(stage, last)
    states = task_states(sorted({jid for _r, _s, jid, _f in subs}))
    known = states is not None
    states = states or {}
    rows = []
    for run, st, jid, ids_file in subs:
        n = len(core.read_ids(ids_file)) if ids_file.is_file() else 0
        c = collections.Counter(category(s) for s in states.get(jid, {}).values())
        c["pending"] += max(n - sum(c.values()), 0)        # tasks sacct has not reported yet
        rows.append(ArrayRow(run, st, jid, n, c))
    return rows, known


def parse_duration_min(s: str) -> int | None:
    """Minutes from fmt_time / Nextflow trace strings: 30m, 4h, 1h30m, 1d, 2d 3h."""
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*(d|h|m)(?![a-z])", str(s), re.I)
    if not parts:
        return None
    mult = {"d": 1440, "h": 60, "m": 1}
    return int(round(sum(float(v) * mult[u.lower()] for v, u in parts)))


def _is_oom(att) -> bool:
    return att.status == "OUT_OF_MEMORY" or att.exit == "137"


def _is_timeout(att) -> bool:
    return att.status == "TIMEOUT" or att.exit == "140"


def bump_reason(att) -> str:
    if att is None:
        return ""
    if _is_oom(att):
        return "OOM"
    if _is_timeout(att):
        return "time"
    return history.reason(att.status, att.exit)


def bump(att, res: core.Res) -> core.Res:
    """Resources for a resubmit: start from max(last request, current default); OOM doubles
    memory, a time limit doubles time, anything else resubmits unchanged."""
    if att is None:
        return res
    try:
        mem = core.parse_mem_mb(att.mem)
    except ValueError:
        mem = res.mem_mb
    t = parse_duration_min(att.time) or res.time_min
    base = dataclasses.replace(res, mem_mb=max(mem, res.mem_mb), time_min=max(t, res.time_min))
    if _is_oom(att):
        return dataclasses.replace(base, mem_mb=base.mem_mb * 2)
    if _is_timeout(att):
        return dataclasses.replace(base, time_min=base.time_min * 2)
    return base


TOOLS = {"align": ["mafft", "clipkit"], "tree": ["iqtree2"], "generax": ["generax", "mpirun"],
         "gxsup": ["iqtree2"], "possvm": [], "possvm_prev": []}
MAX_ARRAY = 1000  # SLURM MaxArraySize default 1001 -> indices 0..1000
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


def chunks(ids: list[str], n: int = MAX_ARRAY) -> list[list[str]]:
    return [ids[i:i + n] for i in range(0, len(ids), n)]


def new_run_dir(stage: str, dry_run: bool = False) -> Path:
    # A dry run writes its scripts under the system temp dir, so runs/ only holds real
    # submissions (queue and the already-queued check read runs/*/jobs.tsv).
    root = Path(tempfile.gettempdir()) / "phylocli-dryrun" if dry_run else runs_dir()
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


def preflight(stage: str) -> str | None:
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
    if not (lost or py_err):
        return None
    msg = "ERROR:"
    if lost:
        msg += f" not on PATH: {' '.join(lost)}"
    if py_err:
        msg += f"\n       {py_err}"
    return msg + "\n" + hint


SHOW = 20


def show(ids: list[str]) -> str:
    s = " ".join(ids[:SHOW])
    return s + (f" ... and {len(ids) - SHOW} more" if len(ids) > SHOW else "")


@dataclass
class Selection:
    selected: list
    notes: list
    queued: set


def select(cfg: core.Config, stage: str, hgs: list[str], all_: bool = False,
           dry_run: bool = False) -> Selection:
    """The submit command's selection rules: unknown ids are an error; by default HGs
    without inputs or already queued are skipped with a note."""
    exp = core.expected(cfg)
    unknown = sorted(set(hgs) - exp)
    if unknown:
        raise ModelError(f"unknown ({len(unknown)}): {show(unknown)}\nnothing submitted", 2)
    queued = live_hgs(stage, allow_no_squeue=dry_run, expected=exp)
    notes: list[str] = []
    selected = list(hgs)
    if not all_:
        unready = [hg for hg in selected if not core.inputs_ready(cfg, stage, hg)]
        busy = [hg for hg in selected if hg in queued and hg not in unready]
        if unready:
            notes.append(f"skipped {len(unready)} HGs without inputs")
        if busy:
            notes.append(f"skipped {len(busy)} HGs already queued")
        drop = set(unready) | set(busy)
        selected = [hg for hg in selected if hg not in drop]
    return Selection(selected, notes, queued)


@dataclass
class Plan:
    stage: str
    groups: list
    notes: list
    errors: dict


def plan(cfg: core.Config, stage: str, sel: Selection, override: dict | None = None,
         per_hg: dict | None = None, over_flags=()) -> Plan:
    errs = core.validate(cfg, stage, sel.selected, sel.queued)
    bad = {k: v for k, v in errs.items() if v}
    notes = list(sel.notes)
    if bad:
        return Plan(stage, [], notes, bad)
    n_rows = core.resources_rows(cfg, sel.selected)
    over_flags = list(over_flags)
    notes.append(f"resources.tsv: row found for {n_rows} of {len(sel.selected)} HGs"
                 + (" (others: step2 defaults)" if n_rows < len(sel.selected) else "")
                 + (f"; overridden by {' '.join(over_flags)}" if over_flags else ""))
    groups = core.group(cfg, stage, sel.selected, override, per_hg)
    pieces = [(res, c) for res, g in groups.items() for c in chunks(g)]
    return Plan(stage, pieces, notes, {})


@dataclass
class Written:
    run_dir: Path
    arrays: list


def write_run(cfg: core.Config, raw: dict, p: Plan, dry_run: bool, max_running: int = 50,
              partition: str | None = None, qos: str | None = None) -> Written:
    import yaml
    run_dir = new_run_dir(p.stage, dry_run)
    (run_dir / "config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    arrays = []
    for k, (res, ids_) in enumerate(p.groups):
        ids_file = run_dir / f"ids_{k}.txt"
        ids_file.write_text("\n".join(ids_) + "\n")
        script = run_dir / f"array_{k}.sbatch"
        script.write_text(SBATCH.format(
            stage=p.stage, partition=partition or cfg.partition, qos=qos or res.qos,
            cpus=res.cpus, mem_mb=res.mem_mb, time_min=res.time_min,
            n_minus_1=len(ids_) - 1, max_running=max_running, run_dir=run_dir,
            signal_line=f"#SBATCH --signal={res.signal}" if res.signal else "",
            ids_file=ids_file, root=ROOT))
        arrays.append((res, ids_, ids_file, script))
    return Written(run_dir, arrays)


def sbatch_all(w: Written) -> tuple[list[str], str | None]:
    submitted: list[str] = []
    for i, (res, ids_, ids_file, script) in enumerate(w.arrays):
        r = subprocess.run(["sbatch", "--parsable", str(script)], capture_output=True, text=True)
        jid = r.stdout.strip().split(";")[0]
        if r.returncode != 0 or not jid:
            return submitted, (f"sbatch failed for {script}: {r.stderr.strip()}\n"
                               f"submitted job ids: {' '.join(submitted) or 'none'}\n"
                               "not submitted: " + " ".join(str(a[3]) for a in w.arrays[i:]))
        with open(w.run_dir / "jobs.tsv", "a") as fh:
            fh.write(f"{jid}\t{ids_file}\n")
        submitted.append(jid)
    return submitted, None
