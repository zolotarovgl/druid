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
                st = history.PROC_STAGE[nf[0]]
                # step1 tags are the family id itself; step2 tags may carry a prefix (pre_<id>)
                hg = nf[1] if st in core.FAMILY_STAGES else history._resolve_tag(nf[1], expected)
                if hg:
                    out[st].add(hg)
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
        if "." in jid:                 # a job step (12345_0.batch): -X hides them, never a task
            continue
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
    no_hits: int = 0


def family_states(cfg: core.Config, fams, lv: dict) -> dict:
    """search / cluster -> family id -> 0 done / 1 running / 2 ready / 3 blocked, from output
    files and squeue only (no history), like stage_states() for HGs. The one family-state code
    path: the CLI summary rows (stage_rows) and the TUI overview cells (group_rows) count it."""
    fams = set(fams)
    if not fams:
        return {}
    fd = core.family_done(cfg, fams)
    out: dict[str, dict[str, int]] = {}
    for st in core.FAMILY_STAGES:
        d = fd[st]
        todo = fams - d
        running = todo & lv.get(st, set())
        ready = core.ready_set(cfg, st, todo - running)
        out[st] = {f: (0 if f in d else 1 if f in running else 2 if f in ready else 3)
                   for f in fams}
    return out


def stage_rows(cfg: core.Config, exp: set[str], fams: set | None = None):
    """(rows, live_known, done-by-stage) — exactly the counts `phylo status` draws. `fams` (family
    ids) puts the search / cluster rows first, counted in families from family_states (cluster
    also reports the no-hits families); None or empty: HG stages only. done-by-stage is the HG
    stages' dict."""
    done = core.report_status.done_by_stage(str(cfg.outdir), exp)
    lv = live(core.expected(cfg))
    known = lv is not None
    lv = lv or {}
    rows = []
    if fams:
        fs = family_states(cfg, fams, lv)
        no_hits = len(core.family_done(cfg, fams)["no_hits"])
        for st in core.FAMILY_STAGES:
            c = [0, 0, 0, 0]
            for v in fs[st].values():
                c[v] += 1
            rows.append(StageRow(st, True, c[0], c[1], c[2], c[3], len(fams),
                                 no_hits if st == "cluster" else 0))
    for st in core.HG_STAGES:
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


def _state_rows(ids, done, busy, ready, latest) -> list[HGRow]:
    rows = []
    for hg in sorted(ids):
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


def hg_rows(cfg: core.Config, stage: str, exp: set[str] | None = None,
            atts: list | None = None, done_map: dict | None = None,
            live_map: dict | None = None, fams: set | None = None) -> list[HGRow]:
    """One row per expected HG for `stage`. failed = inputs present, not done, not queued,
    and the latest attempt at this stage ended in a FAILED_STATES state.
    `done_map` / `live_map` (stage -> ids) let a caller that builds several stages compute
    them once; when omitted they are computed here (squeue is called).
    search / cluster: one row per family (`hg` = family id); `exp` and `done_map` are not used,
    and `atts` should be history.family_attempts() (the default). `fams`: the family ids from
    a caller that already has them (otherwise read here; an unreadable genefam file gives none)."""
    if stage in core.FAMILY_STAGES:
        if fams is None:
            try:
                fams = core.family_ids(cfg, strict=False)
            except (OSError, ValueError):
                fams = set()
        done = core.family_done(cfg, fams)[stage]
        busy = (live_map if live_map is not None else (live(set()) or {})).get(stage, set())
        todo = fams - done - busy
        # search is ready whenever the family has a row, and todo is a subset of fams
        ready = todo if stage == "search" else core.ready_set(cfg, stage, todo)
        latest = _latest_for(history.family_attempts(cfg, fams=fams) if atts is None else atts,
                           stage)
        return _state_rows(fams, done, busy, ready, latest)
    exp = core.expected(cfg) if exp is None else exp
    done = (done_map if done_map is not None
            else core.report_status.done_by_stage(str(cfg.outdir), exp))[stage]
    busy = (live_map if live_map is not None
            else (live(core.expected(cfg)) or {})).get(stage, set())
    todo = exp - done
    ready = core.ready_set(cfg, stage, todo - busy)
    latest = _latest_for(history.attempts(cfg) if atts is None else atts, stage)
    return _state_rows(exp, done, busy, ready, latest)


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
    for st in core.HG_STAGES:
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


# search: main.py hmmsearch -> helper/hmmsearch.py runs hmmfetch, hmmsearch, bedtools and
# `samtools faidx` (line 136, check=True: the .fai feeds bedtools slop -g);
# cluster: main.py cluster -> helper/functions.py cluster runs diamond, mcl; cluster.sh: samtools.
TOOLS = {"search": ["hmmsearch", "hmmfetch", "bedtools", "samtools"], "cluster": ["samtools", "diamond", "mcl"],
         "align": ["mafft", "clipkit"], "tree": ["iqtree2"], "generax": ["generax", "mpirun"],
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


def _missing_files(stage: str, cfg: "core.Config | None") -> list[str]:
    """search reads these by their configured paths (pfam_db is passed as a path, not staged)."""
    if cfg is None or stage != "search":
        return []
    out = [f"{k}={cfg.params.get(k)}" for k in ("genefam_info", "infasta", "pfam_db")
           if not cfg.params.get(k) or not Path(cfg.params[k]).is_file()]
    h = cfg.params.get("hmm_dir")
    if h and not Path(h).is_dir():
        out.append(f"hmm_dir={h}")
    return out


def preflight(stage: str, cfg: "core.Config | None" = None) -> str | None:
    lost = [t for t in TOOLS[stage] if shutil.which(t) is None]
    files = _missing_files(stage, cfg)
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
        return f"ERROR: not found: {' '.join(files)}" if files else None
    msg = "ERROR:"
    if lost:
        msg += f" not on PATH: {' '.join(lost)}"
    if py_err:
        msg += f"\n       {py_err}"
    if files:
        msg += f"\n       not found: {' '.join(files)}"
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
    family = stage in core.FAMILY_STAGES
    if family:
        try:
            exp = core.family_ids(cfg)
        except core.FamilyError as e:
            raise ModelError(str(e), 1) from None
    else:
        exp = core.expected(cfg)
    unknown = sorted(set(hgs) - exp)
    if unknown:
        raise ModelError(f"unknown ({len(unknown)}): {show(unknown)}\nnothing submitted", 2)
    queued = live_hgs(stage, allow_no_squeue=dry_run, expected=exp)
    notes: list[str] = []
    selected = list(hgs)
    if not all_:
        if family:                         # one listing for all families, not one per id
            ok = core.ready_set(cfg, stage, selected)
            unready = [hg for hg in selected if hg not in ok]
        else:
            unready = [hg for hg in selected if not core.inputs_ready(cfg, stage, hg)]
        busy = [hg for hg in selected if hg in queued and hg not in unready]
        unit = core.unit(stage)
        if unready:
            notes.append(f"skipped {len(unready)} {unit} without inputs")
        if busy:
            notes.append(f"skipped {len(busy)} {unit} already queued")
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
    try:
        errs = core.validate(cfg, stage, sel.selected, sel.queued)
    except core.FamilyError as e:
        raise ModelError(str(e), 1) from None
    bad = {k: v for k, v in errs.items() if v}
    notes = list(sel.notes)
    if bad:
        return Plan(stage, [], notes, bad)
    over_flags = list(over_flags)
    over = f"; overridden by {' '.join(over_flags)}" if over_flags else ""
    if stage in core.FAMILY_STAGES:                  # family ids never have resources.tsv rows
        notes.append(f"resources: step1 defaults for {len(sel.selected)} families{over}")
    else:
        n_rows = core.resources_rows(cfg, sel.selected)
        notes.append(f"resources.tsv: row found for {n_rows} of {len(sel.selected)} HGs"
                     + (" (others: step2 defaults)" if n_rows < len(sel.selected) else "") + over)
    groups = core.group(cfg, stage, sel.selected, override, per_hg)
    pieces = [(res, c) for res, g in groups.items() for c in chunks(g)]
    return Plan(stage, pieces, notes, {})


@dataclass
class Written:
    run_dir: Path
    arrays: list


def write_run(cfg: core.Config, raw: dict, p: Plan, dry_run: bool, max_running: int = 50,
              partition: str | None = None, qos: str | None = None) -> Written:
    import copy
    import yaml
    run_dir = new_run_dir(p.stage, dry_run)
    if p.stage == "search":
        # main.py hmmsearch reads the family's row at run time: the jobs read a copy taken now
        # (the file the ids were validated against), and the run keeps it as the record.
        raw = copy.deepcopy(raw)
        snap = run_dir / "genefam.csv"
        shutil.copy2(cfg.params["genefam_info"], snap)
        raw.setdefault("params", {})["genefam_info"] = str(snap)
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


def sbatch_all(w: Written, submitted: list[str] | None = None) -> tuple[list[str], str | None]:
    """`submitted`, if given, is filled in place as arrays are queued, so a caller that sees an
    exception mid-way still knows which job ids exist."""
    submitted = [] if submitted is None else submitted
    for i, (res, ids_, ids_file, script) in enumerate(w.arrays):
        try:
            r = _slurm(["sbatch", "--parsable", str(script)])
            jid, rc, why = r.stdout.strip().split(";")[0], r.returncode, r.stderr.strip()
        except ModelError as e:                      # timed out
            jid, rc, why = "", 1, (f"{e} for {script}: the array may have been queued"
                                   " — check 'squeue --me' before resubmitting")
            timed_out = True
        else:
            timed_out = False
        if rc != 0 or not jid:
            head = why if timed_out else f"sbatch failed for {script}: {why}"
            return submitted, (f"{head}\n"
                               f"submitted job ids: {' '.join(submitted) or 'none'}\n"
                               + ("not submitted (or unknown): " if timed_out else "not submitted: ")
                               + " ".join(str(a[3]) for a in w.arrays[i:]))
        submitted.append(jid)                        # before the write: the array IS queued
        with open(w.run_dir / "jobs.tsv", "a") as fh:
            fh.write(f"{jid}\t{ids_file}\n")
    return submitted, None


def bar_segments(counts, width: int) -> list[int]:
    """Largest-remainder split of `width` cells over `counts`; [] when all are 0."""
    total = sum(counts)
    if total == 0:
        return []
    exact = [width * c / total for c in counts]
    n = [int(x) for x in exact]
    for i in sorted(range(len(n)), key=lambda i: exact[i] - n[i], reverse=True)[:width - sum(n)]:
        n[i] += 1
    return n


def group_key(hg: str, by: str) -> str:
    """category = first id part (tfs); family = id without the HG part (tfs.T-box)."""
    return hg.split(".", 1)[0] if by == "category" else hg.rsplit(".", 1)[0]


def fam_group_key(fam: str, by: str) -> str:
    """Group of a FAMILY id (search / cluster rows): category = first id part (slc); family = the
    family id itself (slc.SLC25) -- an HG's family group (group_key(hg, "family")) is the same."""
    return fam.split(".", 1)[0] if by == "category" else fam


@dataclass
class GroupRow:
    group: str
    total: int
    per_stage: dict
    n_fams: int = 0


def stage_states(cfg: core.Config, exp: set[str], done: dict, lv: dict) -> dict:
    """stage -> hg -> 0 done / 1 running / 2 ready / 3 blocked, for applicable stages only.
    The expensive part (ready_set lists directories); computed once per refresh."""
    state: dict[str, dict[str, int]] = {}
    for st in core.HG_STAGES:
        if not core.applicable(cfg, st):
            continue
        d = done.get(st, set())
        todo = exp - d
        running = todo & lv.get(st, set())
        ready = core.ready_set(cfg, st, todo - running)
        state[st] = {hg: (0 if hg in d else 1 if hg in running else 2 if hg in ready else 3)
                     for hg in exp}
    return state


def group_rows(cfg: core.Config, exp: set[str], by: str = "category",
               done: dict | None = None, lv: dict | None = None, states: dict | None = None,
               fams: set | None = None, fstates: dict | None = None):
    """(rows, squeue_known): per-group done/running/ready/blocked per stage, from output files
    and squeue only (no attempt history). rows[0] is ALL and equals stage_rows().
    `states` (from stage_states) makes this pure in-memory counting.
    `fams` (family ids) fills the search / cluster cells, counted in FAMILIES: ALL = all
    families, a category row = that category's families, a family row = that one family; a group
    with families but no HG yet (a new genefam row) gets a row too. `fstates` (from
    family_states) keeps that in-memory as well. GroupRow.total stays the HG count, .n_fams the
    families. Without `fams` the search / cluster cells are None (as for a non-applicable stage)."""
    known = True
    fams = set(fams or ())
    if states is None or (fams and fstates is None):
        if lv is None:
            lv = live(exp)
            known = lv is not None
            lv = lv or {}
        if states is None:
            done = core.report_status.done_by_stage(str(cfg.outdir), exp) if done is None else done
            states = stage_states(cfg, exp, done, lv)
        if fams and fstates is None:
            fstates = family_states(cfg, fams, lv)
    fstates = fstates or {}
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for hg in exp:
        groups[group_key(hg, by)].append(hg)
    fgroups: dict[str, list[str]] = collections.defaultdict(list)
    for f in fams:
        fgroups[fam_group_key(f, by)].append(f)

    def row(name: str, hgs, fs) -> GroupRow:
        per = {}
        for st in core.STAGES:
            src, ids = (fstates, fs) if st in core.FAMILY_STAGES else (states, hgs)
            if st not in src:
                per[st] = None
                continue
            c = [0, 0, 0, 0]
            for i in ids:
                c[src[st][i]] += 1
            per[st] = tuple(c)
        return GroupRow(name, len(hgs), per, len(fs))

    names = sorted(set(groups) | set(fgroups), key=lambda g: (-len(groups.get(g, ())), g))
    rows = [row("ALL", exp, fams)] + [row(g, groups.get(g, []), fgroups.get(g, [])) for g in names]
    return rows, known


# ---- POSSVM ortholog groups (TUI Results window) ---------------------------------------------
OG_SUFFIX = ".ortholog_groups.csv"
OG_HEADER = ["gene", "orthogroup", "orthogroup_support", "reference_ortholog", "reference_support"]


@dataclass
class Member:
    gene: str
    species: str               # species_of(gene)
    ref: str                   # this row's reference_ortholog (as written, NA included)
    ref_support: str           # this row's reference_support (as written)


@dataclass
class OG:
    id: str                    # <hg>.<n>, e.g. tfs.T-box.HG1.0
    name: str                  # after the first ':', e.g. like:Tbx2/Tbx3
    genes: list                # [Member], file order
    support: "float | None"    # orthogroup_support; None for NA / empty
    ref: str                   # reference_ortholog of the OG's first row
    ref_support: str


@dataclass
class HGOgs:
    hg: str
    ogs: list                  # [OG]; [] when error is set
    error: str = ""


@dataclass
class PhylumRow:
    phylum: str
    covered: int               # species of this phylum with >= 1 member
    total: int                 # species of this phylum in the universe
    n_genes: int
    species: list              # [(code, n)] with n > 0, n desc


def species_of(gene: str) -> str:
    """Species code = the gene id up to the first '_' (Mlei_v05_G1 -> Mlei)."""
    return gene.split("_", 1)[0]


def read_ogs(cfg: core.Config, hg: str, source: str, names: set[str] | None = None):
    """The ortholog groups of one HG, largest first, from
    <outdir>/<source>/<hg>.<tree name>.ortholog_groups.csv.  None when there is no non-empty
    such file (report_status counts an empty one as not done).  `names` = the directory's
    non-empty file names, so that group_ogs lists the directory once for many HGs."""
    d = cfg.outdir / source
    if names is None:
        names = core.report_status.nonempty_files(str(d))
    files = sorted(n for n in names if n.startswith(hg + ".") and n.endswith(OG_SUFFIX))
    if not files:
        return None
    if len(files) > 1:
        raise ModelError(f"{hg}: {len(files)} ortholog_groups.csv files in {d}: {', '.join(files)}")
    path = d / files[0]
    by: dict[str, OG] = {}
    with open(path, errors="replace") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.rstrip("\r\n")
            if ln == 1:
                if line.split("\t") != OG_HEADER:
                    raise ModelError(f"{path}:1: not a POSSVM ortholog_groups.csv header: {line[:80]!r}")
                continue
            if not line.strip():
                continue
            f = line.split("\t")
            og_id, sep, name = f[1].partition(":") if len(f) == 5 else ("", "", "")
            n = og_id[len(hg) + 1:] if og_id.startswith(hg + ".") else ""
            if len(f) != 5 or not sep or not n.isdigit():
                raise ModelError(f"{path}:{ln}: cannot parse row {line[:120]!r}")
            try:
                sup = None if f[2] in ("", "NA") else float(f[2])
            except ValueError:
                raise ModelError(f"{path}:{ln}: bad orthogroup_support {f[2]!r}") from None
            og = by.get(og_id)
            if og is None:
                og = by[og_id] = OG(og_id, name, [], sup, f[3], f[4])
            og.genes.append(Member(f[0], species_of(f[0]), f[3], f[4]))
    return sorted(by.values(), key=lambda o: (-len(o.genes), int(o.id.rsplit(".", 1)[1])))


def hg_sort_key(hg: str) -> tuple:
    """Family, then the HG number as a number (HG2 before HG10)."""
    fam, _, last = hg.rpartition(".")
    m = re.fullmatch(r"HG(\d+)", last)
    return (fam, int(m.group(1)) if m else -1, last)


def group_ogs(cfg: core.Config, hgs, source: str, progress=None,
              cancelled=None) -> tuple[list[HGOgs], int]:
    """(one HGOgs per HG with output, sorted by HG id; number of HGs without output).
    Lists <outdir>/<source>/ once (NFS); an unreadable file becomes that HG's error.
    Optional `progress(k, n)` is called before each HG; `cancelled()` true stops early
    (the partial result is returned; the caller discards it)."""
    names = core.report_status.nonempty_files(str(cfg.outdir / source))
    rows: list[HGOgs] = []
    missing = 0
    todo = sorted(hgs, key=hg_sort_key)
    for k, hg in enumerate(todo):
        if cancelled is not None and cancelled():
            break
        if progress is not None:
            progress(k, len(todo))
        try:
            ogs = read_ogs(cfg, hg, source, names)
        except ModelError as e:
            rows.append(HGOgs(hg, [], str(e)))
            continue
        if ogs is None:
            missing += 1
        else:
            rows.append(HGOgs(hg, ogs))
    return rows, missing


def default_source(cfg: core.Config) -> str:
    """possvm/ (post-GeneRax) when it exists, else possvm_prev/ (raw IQ-TREE)."""
    return "possvm" if (cfg.outdir / "possvm").is_dir() else "possvm_prev"


_NEWICK_TIP = re.compile(r"[(,]\s*([^\s():,;\[\]]+)")    # a name right after '(' or ',' = a tip


def species_universe(cfg: core.Config) -> list[str]:
    """Tip names of params.SPECIES_TREE in newick order (names after ')' are clades: skipped).
    Only the names are read: no tree parsing, no ete3."""
    text = Path(cfg.params["SPECIES_TREE"]).read_text()
    return list(dict.fromkeys(_NEWICK_TIP.findall(text)))


def species_info_path(cfg: core.Config) -> Path:
    """params.species_info if set (relative = to the repo root), else species_info.tsv next to
    the species tree (data/species_info.tsv)."""
    p = cfg.params.get("species_info")
    if p:
        return Path(p) if Path(p).is_absolute() else core.ROOT / p
    return Path(cfg.params.get("SPECIES_TREE", "")).parent / "species_info.tsv"


def phyla(cfg: core.Config) -> dict[str, str]:
    """species code -> phylum from species_info.tsv (code, Latin name, phylum; tab-separated).
    A row without a phylum (2 columns, or an empty 3rd) gives "unknown"."""
    out: dict[str, str] = {}
    with open(species_info_path(cfg), errors="replace") as fh:
        for line in fh:
            f = line.rstrip("\r\n").split("\t")
            code = f[0].strip()
            if not code or code.startswith("#"):
                continue
            out[code] = (f[2].strip() if len(f) > 2 else "") or "unknown"
    return out


def og_species_stats(og: OG, universe, phyla: dict) -> list[PhylumRow]:
    """Per phylum of the universe: species covered / total and member genes; phyla with
    members first (n_genes desc, then name), then the absent ones (by name)."""
    counts = collections.Counter(m.species for m in og.genes)
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for sp in universe:
        groups[phyla.get(sp) or "unknown"].append(sp)
    rows = []
    for ph, sps in groups.items():
        present = sorted(((sp, counts[sp]) for sp in sps if counts[sp]), key=lambda x: (-x[1], x[0]))
        rows.append(PhylumRow(ph, len(present), len(sps), sum(n for _, n in present), present))
    return (sorted((r for r in rows if r.covered), key=lambda r: (-r.n_genes, r.phylum))
            + sorted((r for r in rows if not r.covered), key=lambda r: r.phylum))


def og_outside(og: OG, universe) -> list[tuple[str, int]]:
    """Member species that are not tips of the species tree, with their gene counts."""
    u = set(universe)
    c = collections.Counter(m.species for m in og.genes if m.species not in u)
    return sorted(c.items(), key=lambda x: (-x[1], x[0]))
