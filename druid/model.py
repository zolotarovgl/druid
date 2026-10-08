"""Data layer of phylocli: everything the CLI (phylo.py) and the TUI (tui.py) show or submit,
computed without printing. Errors are raised as ModelError(msg, code); phylo.py turns them
into the same message + exit code it always printed."""
from __future__ import annotations

import collections
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from phylocli import core, history
from phylocli.common import FAILED_STATES, RUNNING_STATES, expand_indices, ids_path, runs_dir

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
