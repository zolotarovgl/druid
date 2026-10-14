"""Helpers shared by phylo.py and history.py (kept here to avoid a circular import)."""
from __future__ import annotations

from pathlib import Path

from druid import paths

# SLURM job states.
FAILED_STATES = {"FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "CANCELLED", "PREEMPTED",
                 "BOOT_FAIL", "DEADLINE"}
RUNNING_STATES = {"RUNNING", "COMPLETING", "CONFIGURING", "STAGE_OUT", "SUSPENDED"}


def runs_dir() -> Path:
    return paths.runs_dir()


def ids_path(run: Path, recorded: str) -> Path:
    """The ids file named in jobs.tsv, or the same file name inside the run dir when the
    recorded absolute path is not visible here (e.g. the run dir seen through a mount)."""
    p = Path(recorded)
    return p if p.is_file() else run / p.name


def fmt_mem(mb: int) -> str:
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb} MB"


def fmt_time(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}m" if h and m else (f"{h}h" if h else f"{m}m")


def expand_indices(spec: str) -> list[int]:
    """'0-3,7%50' -> [0, 1, 2, 3, 7] (SLURM array index spec, throttle dropped)."""
    out = []
    for part in spec.split("%")[0].split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out
