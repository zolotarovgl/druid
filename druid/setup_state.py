"""Setup state (sub-project 2): proteome sources, species candidates, the ticked selection, the
species lock and the blockers the Setup screen and `prepare` show. Pure reads of the config and the
proteome directories; the only write is the lock flag, through yamledit."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from druid import core, paths, yamledit

DEFAULT = "default"
DEFAULT_GLOB = "{sp}_long.pep.fasta"
SHIPPED_TAXONOMY = paths.DRUID_HOME / "druid" / "data" / "genome_sources.tsv"


@dataclass(frozen=True)
class Source:
    name: str
    proteomes_dir: Path
    glob: str
    taxonomy: Path


@dataclass(frozen=True)
class Candidate:
    sp: str
    name: str
    taxonomy: str
    source: str
    path: Path


def _resolve(p, root: Path) -> Path:
    p = Path(str(p)).expanduser()
    return p if p.is_absolute() else Path(root) / p


def sources(raw: dict, root: Path) -> list:
    """The default source (proteomes_dir / proteome_glob / taxonomy) first, then raw["sources"]."""
    tax = raw.get("taxonomy")
    out = [Source(DEFAULT, _resolve(raw.get("proteomes_dir") or ".", root),
                  raw.get("proteome_glob") or DEFAULT_GLOB,
                  _resolve(tax, root) if tax else SHIPPED_TAXONOMY)]
    for e in raw.get("sources") or []:
        if not isinstance(e, dict):
            continue
        out.append(Source(str(e.get("name") or ""), _resolve(e.get("proteomes_dir") or ".", root),
                          e.get("proteome_glob") or DEFAULT_GLOB,
                          _resolve(e["taxonomy"], root) if e.get("taxonomy") else SHIPPED_TAXONOMY))
    return out


def read_taxonomy(path) -> dict:
    """prefix -> (Latin name, taxonomy string) from a genome_sources.tsv (no header; col 1 prefix,
    col 2 Latin name, col 6 taxonomy). Rows with fewer than 6 columns are skipped."""
    out = {}
    try:
        text = Path(path).read_text()
    except OSError:
        return out
    for line in text.splitlines():
        f = line.rstrip("\n").split("\t")
        if len(f) >= 6 and f[0].strip():
            out[f[0].strip()] = (f[1].strip(), f[5].strip())
    return out


def _prefix_regex(glob: str):
    """A glob like "{sp}_long.pep.fasta" as a regex whose group 1 is the {sp} part."""
    parts = glob.split("{sp}")
    def esc(s):
        return "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in s)
    return re.compile("([^/]+?)".join(esc(p) for p in parts))


def candidates(srcs) -> tuple:
    """(candidates, rowless): every file matching a source's glob whose {sp} prefix has a taxonomy
    row; rowless = "<source>: <file>" for custom-source files without one (the default source's are
    dropped silently: its directory holds far more genomes than the table covers)."""
    cands, rowless = [], []
    for s in srcs:
        if "{sp}" not in s.glob or not s.proteomes_dir.is_dir():
            continue
        rx = _prefix_regex(s.glob)
        tax = read_taxonomy(s.taxonomy)
        for f in sorted(s.proteomes_dir.iterdir()):
            m = rx.fullmatch(f.name)
            if not m or not f.is_file():
                continue
            sp = m.group(1)
            if sp in tax:
                cands.append(Candidate(sp, tax[sp][0], tax[sp][1], s.name, f))
            elif s.name != DEFAULT:
                rowless.append(f"{s.name}: {f.name}")
    return cands, rowless


def selected(raw: dict) -> list:
    """`species:` as (sp, source) pairs: "Mlei" -> ("Mlei", "default"); {sp: X, source: Y} -> ("X", "Y")."""
    out = []
    for e in raw.get("species") or []:
        if isinstance(e, dict):
            out.append((str(e.get("sp")), str(e.get("source") or DEFAULT)))
        else:
            out.append((str(e), DEFAULT))
    return out


def species_value(sel) -> list:
    """Inverse of selected(): default-source species as plain strings."""
    return [sp if src == DEFAULT else {"sp": sp, "source": src} for sp, src in sel]


def species_locked(raw: dict, cfg: core.Config) -> bool:
    """The species list is frozen: the flag is set, or a run / results exist (inferred)."""
    if raw.get("species_locked"):
        return True
    runs = Path(raw.get("runs_dir") or "runs")
    runs = runs if runs.is_absolute() else paths.project_root() / runs
    if runs.is_dir() and any(runs.glob("*/jobs.tsv")):
        return True
    return cfg.outdir.is_dir() and any(cfg.outdir.iterdir())


def lock_species(raw: dict, cfg: core.Config) -> bool:
    """Set species_locked at the first real submit. True if it wrote the flag; never writes an
    adopted (prepare: locked) project or one already locked by inference."""
    if raw.get("prepare") == "locked" or species_locked(raw, cfg):
        return False
    yamledit.update_config({("species_locked",): True})
    return True


def proteome_file(src: Source, sp: str):
    return next(iter(sorted(src.proteomes_dir.glob(src.glob.format(sp=sp)))), None)


def base_tree_files(raw: dict, root: Path):
    """(binary, origin) newick paths: raw["tree_source"] (one user tree for both) if set, else the
    project's data/base_tree.binary.newick and data/base_tree.newick."""
    ts = raw.get("tree_source")
    if ts:
        p = _resolve(ts, root)
        return p, p
    return Path(root) / "data" / "base_tree.binary.newick", Path(root) / "data" / "base_tree.newick"


def _tree_blockers(raw: dict, root: Path, species: list, generax: bool) -> list:
    from druid import sptree
    binary_f, _origin_f = base_tree_files(raw, root)
    try:
        base = binary_f.read_text().strip()
        pl = sptree.read_placements(Path(root) / "data" / sptree.PLACEMENTS)
        miss = sptree.missing(base, species, pl)
        built = sptree.build_trees(base, base, species, pl)[0]
    except Exception as e:                      # unreadable / unparsable newick
        return [f"species tree unreadable ({binary_f}): {e}"]
    out = []
    if miss:
        out.append(f"{len(miss)} ticked species not on the tree: {', '.join(miss)}")
    if generax and raw.get("tree_source") and sptree.has_polytomy(built):
        out.append("tree_source has polytomies; GeneRax needs a binary tree")
    return out


def blockers(raw: dict, cfg: core.Config, root: Path) -> list:
    """Why prepare cannot run, human-readable, in this order."""
    out = []
    sel = selected(raw)
    if not sel:
        out.append("no species ticked")
    by_sp = {}
    for sp, src in sel:
        by_sp.setdefault(sp, []).append(src)
    for sp, srcs_ in by_sp.items():
        if len(set(srcs_)) > 1:
            out.append(f"{sp} is ticked from two sources: {', '.join(sorted(set(srcs_)))}")
    srcs = {s.name: s for s in sources(raw, root)}
    for sp, src in sel:
        s = srcs.get(src)
        if s is None:
            out.append(f"{sp}: unknown source {src!r}")
        elif proteome_file(s, sp) is None:
            out.append(f"{sp}: no proteome file in {s.proteomes_dir} ({s.glob})")
    _cands, rowless = candidates(list(srcs.values()))
    for r in rowless:
        out.append(f"no taxonomy row for {r}")
    # species tree / placement check (GeneRax or origins on)
    params = raw.get("params") or {}
    gx = bool(params.get("run_generax"))
    if sel and (gx or params.get("origins", True)):
        out.extend(_tree_blockers(raw, root, list(dict.fromkeys(sp for sp, _ in sel)), gx))
    if not core.family_ids(cfg, strict=False):
        out.append("no families in params.genefam_info")
    return out
