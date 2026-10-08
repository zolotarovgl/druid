"""Per-HG job history: Nextflow run database (read-only) + phylocli's own SLURM submissions.

Nextflow side: `.nextflow/history` is parsed directly, then `nextflow log <run> -f ...` is called
once per step2 run with `-log <temp file>` (so no .nextflow.log is written into the project);
a finished run never changes, so its parsed attempts are cached under the history dir.
phylocli side: runs/*/{jobs.tsv,ids_k.txt,array_k.sbatch} give the request, one `sacct` call
gives state and used resources.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from phylocli import core
from phylocli.common import (FAILED_STATES, expand_indices, fmt_mem, fmt_time, ids_path,
                             runs_dir)

PROC_STAGE = {"ALN": "align", "PHY": "tree", "PVM_PREV": "possvm_prev",
              "GR_watcher": "generax", "GXSUP": "gxsup", "PVM": "possvm"}
NF_FIELDS = "process,tag,status,exit,attempt,cpus,memory,time,peak_rss,realtime,workdir,submit"
NF_VER = "25.04.2"
NF_WARNING = "nextflow not on PATH: Nextflow history skipped"
SACCT_TIMEOUT = 60       # seconds; the TUI calls this every refresh, a stuck slurmdbd must not hang it
NEXTFLOW_TIMEOUT = 120   # seconds for one `nextflow log`


@dataclass(frozen=True)
class Attempt:
    hg: str
    stage: str
    source: str            # "nextflow" | "phylocli"
    run: str               # run name / run dir name
    submitted: str         # sortable "YYYY-mm-dd HH:MM:SS"
    attempt: int           # Nextflow attempt; 1 for phylocli
    status: str            # COMPLETED / FAILED / OUT_OF_MEMORY / ...
    exit: str              # exit code or "-"
    cpus: str              # requested
    mem: str
    time: str
    peak_rss: str          # used, human-readable or "-"
    realtime: str
    log: str


# ---- reasons / colours ------------------------------------------------------------------

EXIT_REASON = {"137": "killed: out of memory?", "140": "time limit (SIGUSR2 warning)",
               "143": "terminated", "10": "GeneRax parse error",
               "65": "stage produced no output"}
STATE_REASON = {"OUT_OF_MEMORY": "out of memory", "TIMEOUT": "time limit", "CANCELLED": "cancelled"}


def reason(status: str, exit_: str) -> str:
    if status in STATE_REASON:
        return STATE_REASON[status]
    if exit_ in ("", "-"):
        return "ok" if status == "COMPLETED" else ""
    if exit_ == "0":
        if status == "COMPLETED":
            return "ok"
        return status.lower().replace("_", " ") if status in FAILED_STATES else "exit 0"
    return EXIT_REASON.get(exit_, f"exit {exit_}")


def colour(status: str) -> str:
    if status == "COMPLETED":
        return "green"
    if status in FAILED_STATES or status in ("FAILED", "ABORTED"):
        return "red"
    return "yellow"


# ---- Nextflow ------------------------------------------------------------------------------

def history_dir() -> Path:
    p = os.environ.get("PHYLOCLI_HISTORY")
    return Path(p) if p else runs_dir().parent / "history"


def nf_runs(nextflow_dir: Path) -> list[tuple[str, str, bool]]:
    """(run name, start 'YYYY-mm-dd HH:MM:SS', final) for every step2.nf run; final = safe to
    cache (finished, or not the newest run)."""
    f = Path(nextflow_dir) / ".nextflow" / "history"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(errors="replace").splitlines():
        c = line.split("\t")
        if len(c) >= 7 and "step2.nf" in c[6]:
            out.append((c[2], c[0].strip(), c[3].strip() != "-"))
    # Nextflow holds a lock per launch dir, so only the newest run can still be running: an
    # older run still marked "-" is a crashed/killed session and will never change.
    return [(r, s, fin or i < len(out) - 1) for i, (r, s, fin) in enumerate(out)]


def _parse_nf(text: str, started: str) -> list[tuple]:
    """Rows (tag, stage, status, exit, attempt, cpus, mem, time, peak, realtime, workdir,
    submitted) from `nextflow log` output; CACHED rows, other processes and noise are dropped."""
    rows = []
    for line in text.splitlines():
        c = line.rstrip("\n").split("\t")
        if len(c) != 12 or c[0] not in PROC_STAGE or c[2] == "CACHED":
            continue
        sub = c[11].strip()
        sub = sub[:19] if re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", sub) else started
        rows.append((c[1], PROC_STAGE[c[0]], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9],
                     c[10], sub))
    return rows


def _call_nextflow(nextflow_dir: Path, run: str) -> str:
    fd, tmp = tempfile.mkstemp(prefix="phylocli-nxflog-", suffix=".log")
    os.close(fd)
    try:
        r = subprocess.run(["nextflow", "-log", tmp, "log", run, "-f", NF_FIELDS],
                           cwd=str(nextflow_dir), capture_output=True, text=True,
                           env={**os.environ, "NXF_VER": os.environ.get("NXF_VER", NF_VER)},
                           timeout=NEXTFLOW_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"nextflow log timed out after {NEXTFLOW_TIMEOUT} s") from None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if r.returncode != 0:
        raise RuntimeError((r.stderr.strip().splitlines() or [f"exit {r.returncode}"])[-1])
    return r.stdout


def _write_cache(path: Path, rows: list[tuple]):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join("\t".join(r) + "\n" for r in rows))
    os.replace(tmp, path)


def _nf_rows(cfg: core.Config, warn) -> list[tuple[str, tuple]]:
    out = []
    hdir = history_dir()
    warned = False
    for run, started, finished in nf_runs(cfg.nextflow_dir):
        cache = hdir / f"nf_{run}.tsv"
        if finished and cache.is_file():
            rows = [tuple(l.split("\t")) for l in cache.read_text().splitlines()]
            rows = [r for r in rows if len(r) == 12]
        else:
            if shutil.which("nextflow") is None:
                if not warned:
                    warn(NF_WARNING)
                    warned = True
                continue
            try:
                rows = _parse_nf(_call_nextflow(cfg.nextflow_dir, run), started)
            except (RuntimeError, OSError) as e:
                warn(f"nextflow log {run} failed ({e}): run skipped")
                continue
            if finished:
                _write_cache(cache, rows)
        out.extend((run, r) for r in rows)
    return out


def _resolve_tag(tag: str, expected: set) -> str | None:
    if tag in expected:
        return tag
    if "_" in tag:
        rest = tag.split("_", 1)[1]
        if rest in expected:
            return rest
    return None


def _nextflow_attempts(cfg: core.Config, hg: str | None, expected: set, warn) -> list[Attempt]:
    out = []
    for run, r in _nf_rows(cfg, warn):
        tag, stage, status, exit_, att, cpus, mem, time, peak, rt, wd, sub = r
        h = _resolve_tag(tag, expected)
        if h is None or (hg and h != hg):
            continue
        try:
            n = int(att)
        except ValueError:
            n = 1
        out.append(Attempt(h, stage, "nextflow", run, sub, n, status, exit_, cpus, mem, time,
                           peak, rt, f"{wd}/.command.err"))
    return out


# ---- phylocli submissions ---------------------------------------------------------------

RUN_RE = re.compile(r"^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)_(.+?)(?:-\d+)?$")


def _elapsed_s(s: str) -> int | None:
    m = re.fullmatch(r"(?:(\d+)-)?(\d+):(\d\d):(\d\d)(?:\.\d+)?", s.strip())
    if not m:
        return None
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + sec


def fmt_elapsed(s: str) -> str:
    sec = _elapsed_s(s)
    if sec is None:
        return "-"
    parts = [(sec // 86400, "d"), (sec % 86400 // 3600, "h"), (sec % 3600 // 60, "m"), (sec % 60, "s")]
    txt = " ".join(f"{v}{u}" for v, u in parts if v)
    return txt or "0s"


def _rss(s: str) -> str:
    m = re.fullmatch(r"([\d.]+)([KMGT]?)", s.strip())
    if not m or not m.group(1):
        return "-"
    mb = float(m.group(1)) * {"K": 1 / 1024, "": 1 / 1024 / 1024, "M": 1, "G": 1024,
                              "T": 1024 * 1024}[m.group(2)]
    return fmt_mem(int(mb))


def _exit(s: str) -> str:
    left, _, right = s.partition(":")
    if left not in ("", "0"):
        return left
    return right if right not in ("", "0") else ("0" if left == "0" else "-")


def _sacct(job_ids: list[str]) -> dict | None:
    """{(job id, task index): {state, elapsed, exit, rss}}; None if sacct is unavailable."""
    if not job_ids:
        return {}
    if shutil.which("sacct") is None:
        return None
    try:
        r = subprocess.run(["sacct", "-n", "-P", "-j", ",".join(job_ids), "-o",
                            "JobID,State,MaxRSS,Elapsed,ExitCode"], capture_output=True, text=True,
                           timeout=SACCT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    out: dict = {}
    for line in r.stdout.splitlines():
        c = line.split("|")
        if len(c) < 5:
            continue
        jid, state, rss, el, ex = c[:5]
        state = state.split()[0] if state.split() else "UNKNOWN"
        base, _, step = jid.partition(".")
        master, _, idx = base.partition("_")
        if not idx:
            continue
        if idx.startswith("["):                                  # pending array: one row, many tasks
            for i in expand_indices(idx.strip("[]")):
                out.setdefault((master, i), {"state": state, "elapsed": "", "exit": "", "rss": ""})
            continue
        if not idx.isdigit():
            continue
        rec = out.setdefault((master, int(idx)), {"state": "UNKNOWN", "elapsed": "", "exit": "",
                                                  "rss": ""})
        if step == "batch":
            rec["rss"] = rss
        elif not step:
            rec.update(state=state, elapsed=el, exit=ex)
    return out


def _sbatch_request(path: Path) -> tuple[str, str, str]:
    try:
        text = path.read_text()
    except OSError:
        return "-", "-", "-"
    cpus = re.search(r"--cpus-per-task=(\d+)", text)
    mem = re.search(r"--mem=(\d+)M", text)
    time = re.search(r"--time=(\d+)\s*$", text, re.M)
    return (cpus.group(1) if cpus else "-",
            fmt_mem(int(mem.group(1))) if mem else "-",
            fmt_time(int(time.group(1))) if time else "-")


def _phylocli_attempts(hg: str | None) -> list[Attempt]:
    subs = []     # (run dir, stage, submitted, job id, ids list, array k)
    for f in sorted(runs_dir().glob("*/jobs.tsv")):
        m = RUN_RE.match(f.parent.name)
        if not m or m.group(7) not in core.STAGES:
            continue
        sub = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}:{m.group(6)}"
        for line in f.read_text().splitlines():
            if "\t" not in line:
                continue
            jid, ids = line.split("\t", 1)
            idf = ids_path(f.parent, ids.strip())
            try:
                hgs = [l.strip() for l in idf.read_text().splitlines()]
            except OSError:
                continue
            if hg and hg not in hgs:
                continue
            k = re.fullmatch(r"ids_(\d+)\.txt", idf.name)
            subs.append((f.parent, m.group(7), sub, jid.strip(), hgs, k.group(1) if k else None))
    states = _sacct(sorted({s[3] for s in subs}))
    out = []
    for run, stage, sub, jid, hgs, k in subs:
        cpus, mem, time = (_sbatch_request(run / f"array_{k}.sbatch") if k is not None
                           else ("-", "-", "-"))
        for i, h in enumerate(hgs):
            if hg and h != hg:
                continue
            if states is None:
                status, exit_, rss, el = "unknown", "-", "-", "-"
            else:
                rec = states.get((jid, i))
                if rec is None:
                    status, exit_, rss, el = "PENDING", "-", "-", "-"
                else:
                    status = rec["state"]
                    exit_ = _exit(rec["exit"]) if rec["exit"] else "-"
                    rss = _rss(rec["rss"]) if rec["rss"] else "-"
                    el = fmt_elapsed(rec["elapsed"]) if rec["elapsed"] else "-"
            out.append(Attempt(h, stage, "phylocli", run.name, sub, 1, status, exit_, cpus, mem,
                               time, rss, el, str(run / "logs" / f"{stage}_{jid}_{i}.err")))
    return out


# ---- public --------------------------------------------------------------------------------

def attempts(cfg: core.Config, hg: str | None = None, warn=None) -> list[Attempt]:
    """Every recorded attempt (Nextflow + phylocli), for one HG if given, oldest first."""
    warn = warn or (lambda _msg: None)
    out = _nextflow_attempts(cfg, hg, core.expected(cfg), warn) + _phylocli_attempts(hg)
    return sorted(out, key=lambda a: (a.submitted, a.attempt, a.run))


def latest_by_stage(atts: list[Attempt]) -> dict[str, Attempt]:
    out: dict[str, Attempt] = {}
    for a in sorted(atts, key=lambda a: (a.submitted, a.attempt, a.run)):
        out[a.stage] = a
    return out
