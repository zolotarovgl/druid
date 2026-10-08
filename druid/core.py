"""Pure logic for phylocli: config, HG sets, stage table, resources, validation."""
from __future__ import annotations

import os
import re
import sys
import dataclasses
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workflow"))
import report_status  # noqa: E402

STAGES = ["align", "tree", "possvm_prev", "generax", "gxsup", "possvm"]
PUBLISH_DIR = {"align": "align", "tree": "gene_trees", "possvm_prev": "possvm_prev",
               "generax": "generax", "gxsup": "generax_support", "possvm": "possvm"}
PATH_PARAMS = ("REFNAMES", "SPECIES_TREE", "resources_tsv")


@dataclass(frozen=True)
class Config:
    outdir: Path
    params: dict
    partition: str
    qos: str
    nextflow_dir: Path = ROOT      # where .nextflow/ (the run history) lives


def _abs(p) -> str:
    p = Path(p)
    return str(p if p.is_absolute() else ROOT / p)


def load_config(path: Path = ROOT / "phylocli/config.yaml") -> Config:
    return config_from_raw(yaml.safe_load(Path(path).read_text()))


def _coerce(key: str, old, value: str):
    if isinstance(old, bool):
        v = value.strip().lower()
        if v in ("true", "yes", "1"):
            return True
        if v in ("false", "no", "0"):
            return False
        raise ValueError(f"{key} expects true/false, got {value!r}")
    if isinstance(old, int):
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"{key} expects an integer, got {value!r}") from None
    if isinstance(old, float):
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"{key} expects a number, got {value!r}") from None
    return value


def apply_sets(raw: dict, sets: list[str]) -> list[str]:
    """Apply KEY=VALUE overrides to raw['params'] in place, converting each value to the type
    of the existing one. Only existing keys are allowed. Returns 'KEY=VALUE (was OLD)' notes."""
    params = raw.setdefault("params", {})
    notes = []
    for s in sets:
        if "=" not in s:
            raise ValueError(f"--set expects KEY=VALUE, got {s!r}")
        key, value = (x.strip() for x in s.split("=", 1))
        if key not in params:
            raise ValueError(f"unknown parameter {key!r}; known: {', '.join(params)}")
        old = params[key]
        params[key] = _coerce(key, old, value)
        notes.append(f"set {key}={params[key]} (was {old})")
    return notes


def config_from_raw(raw: dict) -> Config:
    params = dict(raw.get("params", {}))
    for k in PATH_PARAMS:
        if k in params:
            params[k] = _abs(params[k])
    return Config(outdir=Path(_abs(raw["outdir"])), params=params,
                  partition=raw["partition"], qos=raw["qos"],
                  nextflow_dir=Path(_abs(raw.get("nextflow_dir", "."))))


@dataclass(frozen=True)
class Res:
    cpus: int
    mem_mb: int
    time_min: int
    qos: str
    signal: str | None


def parse_mem_mb(s: str) -> int:
    m = re.fullmatch(r"\s*([\d.]+)\s*\.?\s*([KMGT]?)B?\s*", str(s), re.I)
    if not m:
        raise ValueError(f"bad memory value: {s!r}")
    mult = {"": 1, "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}[m.group(2).upper()]
    return int(round(float(m.group(1)) * mult))


def parse_time_min(s: str) -> int:
    m = re.fullmatch(r"\s*([\d.]+)\s*\.?\s*(min|m|h|d)\s*", str(s), re.I)
    if not m:
        raise ValueError(f"bad time value: {s!r}")
    mult = {"min": 1, "m": 1, "h": 60, "d": 1440}[m.group(2).lower()]
    return int(round(float(m.group(1)) * mult))


def load_resources_tsv(path: Path) -> dict[str, dict[str, str]]:
    path = Path(path)
    if not path.is_file():
        return {}
    lines = [l.rstrip("\n") for l in path.read_text().splitlines() if l.strip()]
    if not lines:
        return {}
    header = lines[0].split("\t")
    out = {}
    for l in lines[1:]:
        cells = l.split("\t")
        row = {h: c.strip() for h, c in zip(header[1:], cells[1:])}
        out[cells[0].strip()] = row
    return out


def expected(cfg: Config) -> set[str]:
    return report_status.expected_hgs(str(cfg.outdir), min_seqs=int(cfg.params.get("min_seqs", 2)),
                                      min_distinct=int(cfg.params.get("min_distinct", 1)))


def read_ids(path) -> list[str]:
    seen, out = set(), []
    for l in Path(path).read_text().splitlines():
        l = l.strip()
        if l and l not in seen:
            seen.add(l)
            out.append(l)
    return out


def nseq(cfg: Config, hg: str) -> int:
    p = cfg.outdir / "clusters" / f"{hg}.fasta"
    if not p.is_file():
        return 0
    with open(p, errors="replace") as fh:
        return sum(1 for line in fh if line.startswith(">"))


def _val(table: dict, hg: str, *cols: str) -> str | None:
    row = table.get(hg, {})
    for c in cols:
        v = row.get(c, "")
        if v and v.upper() not in ("NA", "-"):
            return v
    return None


def resources(cfg: Config, stage: str, hg: str, table: dict, n_seqs: "int | None" = None) -> Res:
    """`n_seqs` (sequences in the HG's FASTA) lets a caller that already knows it skip the file read."""
    qos = cfg.qos
    signal = None
    cpus = 1
    if stage == "align":
        cpus = 4
        v = _val(table, hg, "aln_mem")
        mem = max(parse_mem_mb(v), 4096) if v else 4096
        time = 240  # step2.nf ALN has no time directive: slurm profile default (4 h); aln_time unused
    elif stage == "tree":
        cpus, signal = 4, "B:USR2@180"
        v = _val(table, hg, "phy_mem")
        mem = parse_mem_mb(v) if v else 300
        v = _val(table, hg, "phy_time")
        time = parse_time_min(v) if v else 30
        if (nseq(cfg, hg) if n_seqs is None else n_seqs) > 500:
            qos = "long"
    elif stage in ("possvm_prev", "possvm"):
        v = _val(table, hg, "pvm_mem")
        mem = parse_mem_mb(v) if v else 500
        v = _val(table, hg, "pvm_time")
        time = parse_time_min(v) if v else 5
    elif stage == "generax":
        cpus, signal = int(cfg.params["NCPU_GENERAX"]), "B:USR2@300"
        v = _val(table, hg, "gr_mem", "gr_watcher_mem")
        mem = parse_mem_mb(v) if v else 500
        v = _val(table, hg, "gr_time", "gr_watcher_time")
        time = min(parse_time_min(v), 1440) if v else 30
    elif stage == "gxsup":
        cpus, mem, time = 2, 2048, 30
    else:
        raise ValueError(f"unknown stage {stage!r}")
    return Res(cpus, mem, time, qos, signal)


def applicable(cfg: Config, stage: str) -> bool:
    if stage in ("possvm_prev", "generax", "gxsup") and not cfg.params.get("run_generax"):
        return False
    if stage == "gxsup" and not cfg.params.get("gxsup"):
        return False
    return True


def publish_dir(cfg: Config, stage: str) -> Path:
    return cfg.outdir / PUBLISH_DIR[stage]


def _possvm_tree(cfg: Config, hg: str) -> Path:
    if cfg.params.get("run_generax"):
        if cfg.params.get("gxsup"):
            return cfg.outdir / "generax_support" / f"{hg}.generax.support.tree"
        return cfg.outdir / "generax" / f"{hg}.generax.tree"
    return cfg.outdir / "gene_trees" / f"{hg}.treefile"


def stage_inputs(cfg: Config, stage: str, hg: str) -> list[Path]:
    o = cfg.outdir
    if stage == "align":
        return [o / "clusters" / f"{hg}.fasta"]
    if stage == "tree":
        return [o / "align" / f"{hg}.aln.fasta"]
    if stage == "possvm_prev":
        return [o / "gene_trees" / f"{hg}.treefile", Path(cfg.params["REFNAMES"])]
    if stage == "generax":
        return [o / "align" / f"{hg}.aln.fasta", o / "gene_trees" / f"{hg}.treefile",
                Path(cfg.params["SPECIES_TREE"])]
    if stage == "gxsup":
        return [o / "generax" / f"{hg}.generax.tree", o / "align" / f"{hg}.aln.fasta",
                o / "gene_trees" / f"{hg}.log"]
    if stage == "possvm":
        return [_possvm_tree(cfg, hg), Path(cfg.params["REFNAMES"])]
    raise ValueError(f"unknown stage {stage!r}")


def publish_patterns(stage: str, hg: str, treefile: str | None = None) -> tuple[list[str], str]:
    """(patterns copied first, marker copied last), relative to the work dir.

    For possvm stages pass `treefile` (the input tree's file name) to get exact
    names; without it the tree name is a `*` wildcard (which still needs the
    literal `<hg>.` prefix, so HG1 never matches HG11 files).
    """
    if stage == "align":
        return [], f"{hg}.aln.fasta"
    if stage == "tree":
        return [f"{hg}.log", f"{hg}.aln.fasta", f"{hg}.ckp.gz"], f"{hg}.treefile"
    if stage in ("possvm_prev", "possvm"):
        # POSSVM names outputs after the tree file, which itself starts with `<hg>.`
        t = treefile if treefile is not None else f"{hg}.*"
        first = [f"{t}.ortholog_groups.newick", f"{t}.pairs_orthologs.csv"]
        if treefile is not None:
            first.insert(0, treefile)
        return first, f"{t}.ortholog_groups.csv"
    if stage == "generax":
        return ([f"{hg}.generax.log", f"{hg}.progress.tree", f"{hg}.aln.fasta",
                 f"{hg}.reconciliations"], f"{hg}.generax.tree")
    if stage == "gxsup":
        return [f"{hg}.gxsup.iqtree"], f"{hg}.generax.support.tree"
    raise ValueError(f"unknown stage {stage!r}")


def inputs_ready(cfg: Config, stage: str, hg: str) -> bool:
    """True if every input file the stage reads for this HG exists."""
    return all(p.exists() for p in stage_inputs(cfg, stage, hg))


def filter_fam(hgs, fam: str | None) -> set[str]:
    """Keep HG ids whose leading dot-separated parts equal `fam`'s parts: "tfs" keeps every
    tfs.* HG, "tfs.T-box" keeps tfs.T-box.HG1, tfs.T-box.HG2, ... but not tfs.T-box2.HG1."""
    if not fam:
        return set(hgs)
    parts = fam.strip(".").split(".")
    return {h for h in hgs if h.split(".")[:len(parts)] == parts}


def ready_set(cfg: Config, stage: str, hgs) -> set[str]:
    """HGs whose stage inputs all exist, like inputs_ready() but with one directory listing
    per input directory instead of one stat per file (fast on network mounts)."""
    listings: dict[Path, set[str]] = {}

    def present(p: Path) -> bool:
        d = p.parent
        if d not in listings:
            try:
                listings[d] = set(os.listdir(d))
            except OSError:
                listings[d] = set()
        return p.name in listings[d]

    return {hg for hg in hgs if all(present(p) for p in stage_inputs(cfg, stage, hg))}


def validate(cfg: Config, stage: str, hgs: list[str], queued: set[str]) -> dict[str, list[str]]:
    errs = {k: [] for k in ("not_applicable", "unknown", "output_exists", "input_missing", "queued")}
    exp = expected(cfg)
    known = []
    for hg in hgs:
        (known if hg in exp else errs["unknown"]).append(hg)
    if not applicable(cfg, stage):
        errs["not_applicable"] = list(known)
    else:
        done = report_status.done_by_stage(str(cfg.outdir), exp)[stage]
        for hg in known:
            if hg in done:
                errs["output_exists"].append(hg)
            if not inputs_ready(cfg, stage, hg):
                errs["input_missing"].append(hg)
            if hg in queued:
                errs["queued"].append(hg)
    return {k: sorted(v) for k, v in errs.items()}


def group(cfg: Config, stage: str, hgs: list[str],
          override: dict | None = None, per_hg: dict | None = None) -> dict[Res, list[str]]:
    """Group HGs by resources. `override` (keys cpus / mem_mb / time_min) replaces the
    per-HG value from resources.tsv or the step2 default for every HG; `per_hg`
    ({hg: {mem_mb: .., time_min: .., cpus: ..}}) then applies to single HGs."""
    table = load_resources_tsv(Path(cfg.params["resources_tsv"]))
    over = {k: v for k, v in (override or {}).items() if v is not None}
    out: dict[Res, list[str]] = {}
    for hg in sorted(hgs):
        res = resources(cfg, stage, hg, table)
        if over:
            res = dataclasses.replace(res, **over)
        mine = {k: v for k, v in (per_hg or {}).get(hg, {}).items() if v is not None}
        if mine:
            res = dataclasses.replace(res, **mine)
        out.setdefault(res, []).append(hg)
    return out


def resources_rows(cfg: Config, hgs) -> int:
    """How many of these HGs have a row in resources.tsv."""
    table = load_resources_tsv(Path(cfg.params["resources_tsv"]))
    return sum(1 for hg in hgs if hg in table)
