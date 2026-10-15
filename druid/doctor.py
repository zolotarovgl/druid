"""druid doctor: is everything druid needs here? Reads only; never fixes anything."""
from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from druid import paths

# Tools the stage scripts and submodules/phylogeny call (grep of druid/stages/*.sh and
# submodules/phylogeny/{main.py,helper/*.py}, 14/10/2026), plus SLURM. Optional and not listed:
# nextflow (only the history view), fasttree / iqtree3 / mmseqs / blast (non-default methods).
TOOLS = ("hmmsearch", "hmmfetch", "bedtools", "samtools", "mafft", "clipkit", "iqtree2",
         "diamond", "mcl", "generax", "mpirun", "sbatch", "squeue", "sacct")
# (import name, distribution name, lowest version, first unsupported version)
PACKAGES = (("textual", "textual", "8.2", "9"), ("ete3", "ete3", "3.1.3", None),
            ("rich", "rich", "14", "16"), ("typer", "typer", None, None),
            ("yaml", "PyYAML", None, None), ("Bio", "biopython", None, None))
PFAM_INDEX = (".h3m", ".h3i", ".h3f", ".h3p")


@dataclass(frozen=True)
class Check:
    ok: bool
    name: str
    detail: str


def _version(tool: str) -> str:
    for flag in ("--version", "-version", "-h"):
        try:
            r = subprocess.run([tool, flag], capture_output=True, text=True, errors="replace",
                               timeout=10, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode != 0:                       # "No such option --version" is not a version
            continue
        lines = [ln.strip() for ln in (r.stdout + r.stderr).splitlines() if ln.strip()]
        line = next((ln for ln in lines if re.search(r"\d+\.\d+", ln)), lines[0] if lines else "")
        if line:
            return line[:70]
    return "version unknown"


def _vtuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split(".")[:3] if x.isdigit())


def _tools() -> list:
    out = []
    for t in TOOLS:
        p = shutil.which(t)
        out.append(Check(bool(p), t, _version(t) if p else "not on PATH"))
    return out


def _packages() -> list:
    from importlib import metadata
    out = []
    for mod, dist, lo, hi in PACKAGES:
        try:
            importlib.import_module(mod)
        except ImportError:
            out.append(Check(False, f"python:{mod}", "not importable"))
            continue
        try:
            v = metadata.version(dist)
        except metadata.PackageNotFoundError:
            v = "?"
        ok = v == "?" or ((lo is None or _vtuple(v) >= _vtuple(lo))
                          and (hi is None or _vtuple(v) < _vtuple(hi)))
        rng = f" (needs >= {lo}{', < ' + hi if hi else ''})" if lo else ""
        out.append(Check(ok, f"python:{mod}", f"{v}{rng}"))
    return out


def _install() -> list:
    main = paths.DRUID_HOME / "submodules" / "phylogeny" / "main.py"
    possvm = paths.DRUID_HOME / "submodules" / "phylogeny" / "submodules" / "possvm-orthology"
    ok = main.is_file() and possvm.is_dir() and any(possvm.iterdir())
    return [Check(ok, "submodules", str(main) if ok else
                  "missing: run git submodule update --init --recursive in " + str(paths.DRUID_HOME))]


def _project() -> list:
    from druid import core
    try:
        root = paths.project_root()
    except paths.NoProject as e:
        return [Check(True, "project", f"SKIP {e}")]
    out = [Check(True, "project", str(root))]
    try:
        raw = paths.read_raw()
        cfg = core.config_from_raw(raw)
    except core.ConfigError as e:             # unreadable, malformed, incomplete, or a target outside
        return out + [Check(False, "config", f"{paths.config_file()}: {e}")]
    out.append(Check(True, "config", str(paths.config_file())))
    pf = Path(cfg.params.get("pfam_db") or "")
    missing = [e for e in PFAM_INDEX if not Path(str(pf) + e).is_file()]
    if not pf.is_file() or not os.access(pf, os.R_OK):
        out.append(Check(False, "pfam_db", f"not readable: {pf}"))
    elif missing:
        out.append(Check(False, "pfam_db", f"{pf}: no {' '.join(missing)}; its owner must run "
                                           f"hmmpress (druid never writes there)"))
    else:
        out.append(Check(True, "pfam_db", str(pf)))
    prot = Path(raw.get("proteomes_dir") or "").expanduser()
    if not prot.is_absolute():                      # relative to the project, like the other paths
        prot = paths.project_root() / prot
    sps = list(raw.get("species") or [])
    if not (prot.is_dir() and os.access(prot, os.R_OK | os.X_OK)):
        out.append(Check(False, "proteomes", f"not readable: {prot}"))
    else:
        glob = raw.get("proteome_glob") or "{sp}_long.pep.fasta"
        try:
            lost = [s for s in sps if not list(prot.glob(glob.format(sp=s)))]
        except (KeyError, IndexError, ValueError, NotImplementedError) as e:
            out.append(Check(False, "proteomes",
                             f"proteome_glob {glob!r} unusable ({type(e).__name__}: {e}); "
                             f"it is a relative pattern with {{sp}} as the only placeholder"))
        else:
            out.append(Check(not lost, "proteomes",
                             f"{len(sps) - len(lost)}/{len(sps)} species have a file in {prot}"
                             + (f"; missing: {', '.join(lost)}" if lost else "")))
    tree = Path(cfg.params.get("SPECIES_TREE") or "")
    try:
        from ete3 import Tree
        n = len(Tree(tree.read_text(), format=1))
        out.append(Check(True, "species_tree", f"{tree} ({n} tips)"))
    except Exception as e:
        out.append(Check(False, "species_tree", f"{tree}: {e}"))
    return out


def checks() -> list:
    return _tools() + _packages() + _install() + _project()
