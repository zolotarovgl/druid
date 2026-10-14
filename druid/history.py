"""Per-HG job history: Nextflow run database (read-only) + phylocli's own SLURM submissions.

Nextflow side: `.nextflow/history` is parsed directly, then `nextflow log <run> -f ...` is called
once per step2 run with `-log <temp file>` (so no .nextflow.log is written into the project);
a finished run never changes, so its parsed attempts are cached under the history dir.
phylocli side: runs/*/{jobs.tsv,ids_k.txt,array_k.sbatch} give the request, one `sacct` call
gives state and used resources.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from druid import core, paths
from druid.common import (FAILED_STATES, expand_indices, fmt_mem, fmt_time, ids_path,
                             runs_dir)

PROC_STAGE = {"SEARCH": "search", "CLUSTER": "cluster",                       # step1.nf
              "ALN": "align", "PHY": "tree", "PVM_PREV": "possvm_prev",       # step2.nf
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
    p = os.environ.get("DRUID_HISTORY")
    return Path(p) if p else runs_dir().parent / "history"


def nf_runs(nextflow_dir: Path, script: str = "step2.nf") -> list[tuple[str, str, bool]]:
    """(run name, start 'YYYY-mm-dd HH:MM:SS', final) for every run of `script` (step2.nf: the HG
    stages; step1.nf: search / cluster); final = safe to cache (finished, or not the newest run)."""
    f = Path(nextflow_dir) / ".nextflow" / "history"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(errors="replace").splitlines():
        c = line.split("\t")
        if len(c) >= 7 and script in c[6]:
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
    tmp = paths.mkstemp(prefix="druid-nxflog-", suffix=".log")
    try:
        r = subprocess.run(["nextflow", "-log", str(tmp), "log", run, "-f", NF_FIELDS],
                           cwd=str(nextflow_dir), capture_output=True, text=True,
                           env={**os.environ, "NXF_VER": os.environ.get("NXF_VER", NF_VER)},
                           timeout=NEXTFLOW_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"nextflow log timed out after {NEXTFLOW_TIMEOUT} s") from None
    finally:
        try:
            paths.unlink(tmp)
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


def _nf_rows(cfg: core.Config, warn, script: str = "step2.nf") -> list[tuple[str, tuple]]:
    out = []
    hdir = history_dir()
    warned = False
    for run, started, finished in nf_runs(cfg.nextflow_dir, script):
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


def _nextflow_attempts(cfg: core.Config, hg: str | None, expected: set, warn,
                       script: str = "step2.nf") -> list[Attempt]:
    out = []
    for run, r in _nf_rows(cfg, warn, script):
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


ARRAY_CACHE = "phylocli_arrays.json"
_REC_KEYS = ("state", "elapsed", "exit", "rss")


def _terminal(state: str) -> bool:
    return state == "COMPLETED" or state in FAILED_STATES


def _load_array_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_array_cache(path: Path, data: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")   # per process: concurrent writers
        tmp.write_text(json.dumps(data))
        os.replace(tmp, path)
    except OSError:
        pass        # the cache is an optimisation; never fail a refresh over it


def _phylocli_attempts(hg: str | None, stages=None) -> list[Attempt]:
    """Attempts of phylocli's own submissions. Arrays whose every task is terminal in sacct are
    cached (history dir, phylocli_arrays.json, keyed run dir|job id) and never queried again."""
    stages = core.HG_STAGES if stages is None else stages
    cache_path = history_dir() / ARRAY_CACHE
    cache = _load_array_cache(cache_path)
    subs = []     # (run dir, stage, submitted, job id, ids list, array k, key, ids stamp, line, entry)
    live = set()
    for f in sorted(runs_dir().glob("*/jobs.tsv")):
        live.add(f.parent.name)
        m = RUN_RE.match(f.parent.name)
        if not m or m.group(7) not in stages:
            continue
        sub = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}:{m.group(6)}"
        for line in f.read_text().splitlines():
            if "\t" not in line:
                continue
            jid, ids = line.split("\t", 1)
            idf = ids_path(f.parent, ids.strip())
            try:
                st = idf.stat()
            except OSError:
                continue
            stamp = [str(idf), st.st_mtime_ns, st.st_size]
            key = f"{f.parent.name}|{jid.strip()}"
            entry = cache.get(key)
            if isinstance(entry, dict) and entry.get("line") == line.strip() \
                    and entry.get("ids") == stamp:
                hgs = entry["hgs"]
            else:
                entry = None
                try:
                    hgs = [l.strip() for l in idf.read_text().splitlines()]
                except OSError:
                    continue
            if hg and hg not in hgs:
                continue
            k = re.fullmatch(r"ids_(\d+)\.txt", idf.name)
            subs.append((f.parent, m.group(7), sub, jid.strip(), hgs, k.group(1) if k else None,
                         key, stamp, line.strip(), entry))
    states = _sacct(sorted({s[3] for s in subs if s[9] is None}))
    fresh = {}
    out = []
    for run, stage, sub, jid, hgs, k, key, stamp, line, entry in subs:
        if entry is not None:
            cpus, mem, time = entry["req"]
            recs = [dict(zip(_REC_KEYS, t)) for t in entry["tasks"]]
        else:
            cpus, mem, time = (_sbatch_request(run / f"array_{k}.sbatch") if k is not None
                               else ("-", "-", "-"))
            recs = [states.get((jid, i)) if states is not None else None
                    for i in range(len(hgs))]
            if states is not None and recs and all(r is not None and _terminal(r["state"])
                                                   for r in recs):
                fresh[key] = {"line": line, "ids": stamp, "hgs": hgs, "req": [cpus, mem, time],
                              "tasks": [[r[x] for x in _REC_KEYS] for r in recs]}
        for i, h in enumerate(hgs):
            if hg and h != hg:
                continue
            if entry is None and states is None:
                status, exit_, rss, el = "unknown", "-", "-", "-"
            else:
                rec = recs[i]
                if rec is None:
                    status, exit_, rss, el = "PENDING", "-", "-", "-"
                else:
                    status = rec["state"]
                    exit_ = _exit(rec["exit"]) if rec["exit"] else "-"
                    rss = _rss(rec["rss"]) if rec["rss"] else "-"
                    el = fmt_elapsed(rec["elapsed"]) if rec["elapsed"] else "-"
            out.append(Attempt(h, stage, "phylocli", run.name, sub, 1, status, exit_, cpus, mem,
                               time, rss, el, str(run / "logs" / f"{stage}_{jid}_{i}.err")))
    merged = {k: v for k, v in cache.items() if k.split("|", 1)[0] in live}
    merged.update(fresh)
    if fresh or merged.keys() != cache.keys():
        _write_array_cache(cache_path, merged)
    return out


# ---- public --------------------------------------------------------------------------------

def attempts(cfg: core.Config, hg: str | None = None, warn=None) -> list[Attempt]:
    """Every recorded attempt (Nextflow + phylocli), for one HG if given, oldest first."""
    warn = warn or (lambda _msg: None)
    out = _nextflow_attempts(cfg, hg, core.expected(cfg), warn) + _phylocli_attempts(hg)
    return sorted(out, key=lambda a: (a.submitted, a.attempt, a.run))


def family_attempts(cfg: core.Config, fam: str | None = None, warn=None,
                    fams: set | None = None) -> list[Attempt]:
    """Every recorded search / cluster attempt, for one family if given, oldest first: step1.nf
    runs (processes SEARCH / CLUSTER, tag = <pref>.<family>) + phylocli runs of those stages.
    Kept apart from attempts() so `status HG` never starts nextflow for step1 runs.
    `fams`: family ids from a caller that already has them (else read; unreadable file: none)."""
    warn = warn or (lambda _msg: None)
    if fams is None:
        try:
            fams = core.family_ids(cfg, strict=False)
        except (OSError, ValueError):
            fams = set()
    out = (_nextflow_attempts(cfg, fam, fams, warn, script="step1.nf")
           + _phylocli_attempts(fam, core.FAMILY_STAGES))
    return sorted(out, key=lambda a: (a.submitted, a.attempt, a.run))


def latest_by_stage(atts: list[Attempt]) -> dict[str, Attempt]:
    out: dict[str, Attempt] = {}
    for a in sorted(atts, key=lambda a: (a.submitted, a.attempt, a.run)):
        out[a.stage] = a
    return out
