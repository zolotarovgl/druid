"""`druid report`: the step-2 interactive HTML report, written by one SLURM job.

The job runs the vendored druid/vendor/report_step2/report_step2.py over <outdir>; it writes only
the output HTML in <outdir>. druid itself writes only runs/<ts>_report/ (or the dry-run dir)."""
from __future__ import annotations

import shlex
from pathlib import Path

from druid import core, model, paths

SCRIPT = paths.DRUID_HOME / "druid" / "vendor" / "report_step2" / "report_step2.py"
DEFAULT_MEM_MB = 4096
DEFAULT_TIME_MIN = 30

SBATCH = """#!/usr/bin/env bash
#SBATCH --job-name={job_name}
#SBATCH --partition={partition}
#SBATCH --qos={qos}
#SBATCH --cpus-per-task=1
#SBATCH --mem={mem_mb}M
#SBATCH --time={time_min}
#SBATCH --output={out}
#SBATCH --error={err}
set -euo pipefail
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
{command}
"""


class ReportError(Exception):
    pass


def output_path(cfg: core.Config, fam: str | None = None) -> Path:
    return cfg.outdir / (f"report_step2.{fam.strip('.')}.html" if fam else "report_step2.html")


def _has_files(d: Path) -> bool:
    return d.is_dir() and any(p.is_file() for p in d.iterdir())


def _filtered_family_rows(cfg: core.Config, fam: str) -> str:
    """The genefam file's text with only the rows of `fam` (core.filter_fam's whole-id-part match);
    lines that are not 7-column data rows (a header, comments) are kept."""
    src = cfg.params.get("genefam_info")
    if not src or not Path(src).is_file():
        raise ReportError(f"genefam file not found: {src}")
    keep, n = [], 0
    for line in Path(src).read_text(errors="replace").splitlines(keepends=True):
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


def report_args(cfg: core.Config, raw: dict, fam: str | None, fam_file: Path | None) -> list[str]:
    out, p = cfg.outdir, cfg.params
    family_info = fam_file if fam_file is not None else p.get("genefam_info")
    a = ["--results_dir", out, "--possvm_dir", out / "possvm", "--possvm_prev_dir", out / "possvm_prev",
         "--search_dir", out / "search", "--cluster_dir", out / "clusters",
         "--align_dir", out / "align", "--family_info", family_info,
         "--species_tree", p.get("SPECIES_TREE"),
         "--species_info", paths.project_root() / "data" / "species_info.tsv"]
    if p.get("REFNAMES"):
        a += ["--refnames", p["REFNAMES"]]
    if p.get("REFSPECIES"):
        a += ["--refsps", p["REFSPECIES"]]
    img = p.get("report_images")
    if img:
        a += ["--species_images", core._abs(img)]
    a += ["--output", output_path(cfg, fam)]
    return [str(x) for x in a]


def write(cfg: core.Config, raw: dict, fam: str | None = None, dry_run: bool = False,
          mem: str | None = None, time: str | None = None) -> Path:
    """Write runs/<ts>_report/report.sbatch (dry run: under .druid/tmp/dryrun); return its path."""
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
    rows = _filtered_family_rows(cfg, fam) if fam else None
    for k in ("SPECIES_TREE", "genefam_info"):
        if not cfg.params.get(k):
            raise ReportError(f"params.{k} is not set in druid.yaml")
    d = model.new_run_dir("report", dry_run)
    fam_file = None
    if rows is not None:
        fam_file = d / f"genefam.{fam.strip('.')}.csv"
        paths.write_text(fam_file, rows)
    cmd = " ".join(shlex.quote(x) for x in ["python3", str(SCRIPT)] + report_args(cfg, raw, fam, fam_file))
    script = d / "report.sbatch"
    paths.write_text(script, SBATCH.format(
        job_name=f"{cfg.job_prefix}-report", partition=cfg.partition, qos=cfg.qos,
        mem_mb=mem_mb, time_min=time_min, out=d / "logs" / "report_%j.out",
        err=d / "logs" / "report_%j.err", command=cmd))
    return script


def submit(script: Path) -> str:
    try:
        r = model._slurm(["sbatch", "--parsable", str(script)])
    except (model.ModelError, OSError) as e:
        raise ReportError(str(e)) from None
    if r.returncode != 0:
        raise ReportError(f"sbatch failed: {r.stderr.strip()}")
    return r.stdout.strip().split(";")[0]
