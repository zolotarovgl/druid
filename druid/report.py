"""`druid report`: the step-2 interactive HTML report, written by one SLURM job.

The job runs the vendored druid/vendor/report_step2/report_step2.py over <outdir>; it writes only
the output HTML in <outdir> (as <output>.part, renamed when the script succeeds). druid itself
writes only runs/<ts>_report/ (or the dry-run dir)."""
from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import NamedTuple

from druid import core, model, paths

SCRIPT = paths.DRUID_HOME / "druid" / "vendor" / "report_step2" / "report_step2.py"
DEFAULT_MEM_MB = 4096
DEFAULT_TIME_MIN = 30
# The per-HG input dirs the script filters by file name with the family table, which keeps a whole
# class (see _family_view); align/ is read per kept tree id (report_step2.py:11374).
VIEW_DIRS = ("possvm", "possvm_prev", "search", "clusters")

SBATCH = """#!/usr/bin/env bash
#SBATCH --job-name={job_name}
#SBATCH --partition={partition}
#SBATCH --qos={qos}
#SBATCH --cpus-per-task=1
#SBATCH --mem={mem_mb}M
#SBATCH --time={time_min}
#SBATCH --output={out}
#SBATCH --error={err}
#SBATCH --chdir={run_dir}
set -euo pipefail
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
python3 -c 'import ete3'
{command}
{rename}
"""


class ReportError(Exception):
    pass


class Checked(NamedTuple):
    mem_mb: int
    time_min: int
    rows: str | None          # the -f filtered genefam text, None without -f


def output_path(cfg: core.Config, fam: str | None = None) -> Path:
    return cfg.outdir / (f"report_step2.{fam.strip('.')}.html" if fam else "report_step2.html")


def _part(out: Path) -> Path:
    """What the script writes; the job renames it to `out` only after the script succeeds."""
    return out.with_name(out.name + ".part")


def _species_info() -> Path:
    return paths.project_root() / "data" / "species_info.tsv"


def _has_files(d: Path) -> bool:
    return d.is_dir() and any(p.is_file() for p in d.iterdir())


def _ete3_error() -> str | None:
    """The job's python3 cannot import ete3: the script then writes a report with no trees and
    exits 0 (report_step2.py:925-928, :796, :1014 catch the ImportError)."""
    return model.python_import_error("python3", "ete3")


def _family_level(fam: str | None) -> bool:
    """`-f tfs.T-box` (class.family) rather than `-f tfs` (a class)."""
    return bool(fam) and len(fam.strip(".").split(".")) >= 2


def _filtered_family_rows(cfg: core.Config, fam: str) -> str:
    """The genefam file's text with only the rows of `fam` (core.filter_fam's whole-id-part match);
    lines that are not 7-column data rows (a header, comments) are kept. check() has made sure
    params.genefam_info is set and exists."""
    keep, n = [], 0
    for line in Path(cfg.params["genefam_info"]).read_text(errors="replace").splitlines(keepends=True):
        cols = line.strip().split("\t")
        if not line.strip() or len(cols) < 7:
            keep.append(line)
            continue
        fid = f"{cols[-1].strip()}.{cols[0].strip()}"
        if core.filter_fam([fid], fam):
            keep.append(line)
            n += 1
    if not n:
        raise ReportError(f"no families match --fam {fam}")
    return "".join(keep)


def _family_view(cfg: core.Config, run_dir: Path, fam: str) -> Path:
    """<run_dir>/view/<dir>: symlinks to only `fam`'s files of <outdir>/<dir>, for each VIEW_DIRS.
    The script cannot narrow below a class itself: load_family_info maps the class to itself
    (report_step2.py:77-84), and a file is kept when its class prefix is in that map (:101-104,
    :11263-11264), so a one-family genefam copy still keeps every <class>.* file."""
    v = run_dir / "view"
    for name in VIEW_DIRS:
        src = cfg.outdir / name
        paths.mkdir(v / name)
        try:
            names = os.listdir(src)
        except FileNotFoundError:            # an absent dir stays an empty one
            continue
        for f in sorted(core.filter_fam(names, fam)):
            paths.symlink(v / name / f, src / f)
    return v


def report_args(cfg: core.Config, raw: dict, fam: str | None, fam_file: Path | None,
                view: Path | None = None) -> list[str]:
    out, p = cfg.outdir, cfg.params
    src = view if view is not None else out
    family_info = fam_file if fam_file is not None else p.get("genefam_info")
    a = ["--results_dir", out, "--possvm_dir", src / "possvm", "--possvm_prev_dir", src / "possvm_prev",
         "--search_dir", src / "search", "--cluster_dir", src / "clusters",
         "--align_dir", out / "align", "--family_info", family_info,
         "--species_tree", p.get("SPECIES_TREE"),
         "--species_info", _species_info()]
    if p.get("REFNAMES"):
        a += ["--refnames", p["REFNAMES"]]
    if p.get("REFSPECIES"):
        a += ["--refsps", p["REFSPECIES"]]
    img = p.get("report_images")
    if img:
        a += ["--species_images", core._abs(img)]
    a += ["--output", _part(output_path(cfg, fam))]
    return [str(x) for x in a]


def check(cfg: core.Config, raw: dict, fam: str | None = None, mem: str | None = None,
          time: str | None = None) -> Checked:
    """Every refusal of `druid report`, before anything is written (write() calls it too)."""
    if not cfg.job_prefix:
        raise ReportError("job_prefix is not set in druid.yaml")
    if not (_has_files(cfg.outdir / "possvm") or _has_files(cfg.outdir / "possvm_prev")):
        raise ReportError(f"no possvm output to report on: {cfg.outdir / 'possvm'} and "
                          f"{cfg.outdir / 'possvm_prev'} hold no files (run possvm_prev or possvm first)")
    try:
        mem_mb = core.parse_mem_mb(mem) if mem else DEFAULT_MEM_MB
        time_min = core.parse_time_min(time) if time else DEFAULT_TIME_MIN
    except ValueError as e:
        raise ReportError(str(e)) from None
    for k in ("SPECIES_TREE", "genefam_info"):
        if not cfg.params.get(k):
            raise ReportError(f"params.{k} is not set in druid.yaml")
        if not Path(cfg.params[k]).is_file():
            raise ReportError(f"params.{k} not found: {cfg.params[k]}")
    if not _species_info().is_file():
        raise ReportError(f"species info not found: {_species_info()}")
    rows = _filtered_family_rows(cfg, fam) if fam else None
    err = _ete3_error()
    if err:
        raise ReportError(f"{err}\n{model.ENV_HINT}")
    return Checked(mem_mb, time_min, rows)


def write(cfg: core.Config, raw: dict, fam: str | None = None, dry_run: bool = False,
          mem: str | None = None, time: str | None = None) -> Path:
    """Write runs/<ts>_report/report.sbatch (dry run: under .druid/tmp/dryrun); return its path."""
    c = check(cfg, raw, fam, mem, time)
    d = model.new_run_dir("report", dry_run)
    fam_file = None
    if c.rows is not None:
        fam_file = d / f"genefam.{fam.strip('.')}.csv"
        paths.write_text(fam_file, c.rows)
    view = _family_view(cfg, d, fam) if _family_level(fam) else None
    out = output_path(cfg, fam)
    cmd = " ".join(shlex.quote(x) for x in ["python3", str(SCRIPT)] + report_args(cfg, raw, fam, fam_file, view))
    rename = " ".join(shlex.quote(x) for x in ["mv", "-f", "--", str(_part(out)), str(out)])
    script = d / "report.sbatch"
    paths.write_text(script, SBATCH.format(
        job_name=f"{cfg.job_prefix}-report", partition=cfg.partition, qos=cfg.qos,
        mem_mb=c.mem_mb, time_min=c.time_min, out=d / "logs" / "report_%j.out",
        err=d / "logs" / "report_%j.err", run_dir=d, command=cmd, rename=rename))
    return script


def submit(script: Path) -> str:
    try:
        r = model._slurm(["sbatch", "--parsable", str(script)])
    except (model.ModelError, OSError) as e:
        raise ReportError(str(e)) from None
    if r.returncode != 0:
        raise ReportError(f"sbatch failed: {r.stderr.strip()}")
    return r.stdout.strip().split(";")[0]
