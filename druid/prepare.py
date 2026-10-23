"""Prepare (sub-project 2): build the project's data/input.fasta from the ticked proteomes (the
`<prefix>_` is added to headers only in the copy), the two species trees (only with GeneRax or
origins on) and data/species_info.tsv.
Every input is checked before anything is written; each output is written to a temp file under the
project and moved into place, so an interrupted run keeps the old files."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from druid import core, model, paths, setup_state as ss

SHIPPED_INFO = paths.DRUID_HOME / "druid" / "data" / "species_info.tsv"
OTHER = "Other"


class PrepareError(RuntimeError):
    pass


def _shipped_clades() -> Dict[str, tuple]:
    """prefix -> (Latin name, clade) of the shipped species_info.tsv."""
    out = {}
    for line in SHIPPED_INFO.read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if len(f) >= 3 and f[0].strip():
            out[f[0].strip()] = (f[1].strip(), f[2].strip())
    return out


def _clade(sp: str, taxonomy: str, shipped: Dict[str, tuple]) -> str:
    if sp in shipped and shipped[sp][1]:
        return shipped[sp][1]
    known = {c for _l, c in shipped.values() if c}
    for part in taxonomy.split(", "):
        if part.strip() in known:
            return part.strip()
    return OTHER


def _species_info_text(sel, srcs) -> str:
    shipped = _shipped_clades()
    tax = {s.name: ss.read_taxonomy(s.taxonomy) for s in srcs.values()}
    rows = []
    for sp, src in sel:
        latin, taxonomy = tax.get(src, {}).get(sp, ("", ""))
        rows.append(f"{sp}\t{latin or shipped.get(sp, ('', ''))[0] or sp}\t{_clade(sp, taxonomy, shipped)}\n")
    return "".join(rows)


def _prefixed(src_file: Path, sp: str) -> str:
    """src_file's text with \\r stripped, blank lines dropped, a newline at the end and headers
    prefixed `<sp>_` unless they already are."""
    prefix = sp + "_"
    out = []
    with open(src_file, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.replace("\r", "").rstrip("\n")
            if not line.strip():
                continue
            if line.startswith(">"):
                if not line[1:].startswith(prefix):
                    line = ">" + prefix + line[1:]
            out.append(line + "\n")
    return "".join(out)


def run(raw: dict, cfg: core.Config, root: Path, notes: Optional[list] = None) -> List[Path]:
    """Write input.fasta, the species trees (pruned to the ticked species; placements added; none
    with GeneRax and origins off) and species_info.tsv.
    Returns the paths written; the tree build's notes are appended to `notes` if given."""
    if raw.get("prepare") == "locked":
        raise PrepareError("this project is adopted (prepare: locked): its inputs are not rebuilt")
    if ss.species_locked(raw, cfg):
        raise PrepareError("the species list is locked (a run or results exist)")
    bl = ss.blockers(raw, cfg, root)
    if bl:
        raise PrepareError("cannot prepare:\n  " + "\n  ".join(bl))
    sel = ss.selected(raw)
    srcs = {s.name: s for s in ss.sources(raw, root)}
    files = [ss.proteome_file(srcs[src], sp) for sp, src in sel]
    for f in files:                                        # readable before anything is written
        try:
            with open(f, "rb") as fh:
                fh.read(1)
        except OSError as e:
            raise PrepareError(f"cannot read {f}: {e}")
    # GeneRax and origins off (Ruling K): no base tree is read and no tree written; the species
    # universe is then the ticked species (model.species_universe), not SPECIES_TREE
    trees = None
    if ss.trees_needed(raw.get("params") or {}):
        from druid import sptree
        bin_f, org_f = ss.base_tree_files(raw, root)
        try:
            trees = sptree.build_trees(bin_f.read_text(encoding="utf-8").strip(),
                                       org_f.read_text(encoding="utf-8").strip(),
                                       list(dict.fromkeys(sp for sp, _ in sel)),
                                       sptree.read_placements(Path(root) / "data" / sptree.PLACEMENTS))
        except Exception as e:
            raise PrepareError(f"species tree: {e}")
    info = _species_info_text(sel, srcs)

    written, tmps = [], []
    try:
        fa = paths.mkstemp("input_", ".fasta")
        tmps.append(fa)
        for (sp, _src), f in zip(sel, files):
            try:
                paths.append_text(fa, _prefixed(f, sp), encoding="utf-8")
            except OSError as e:
                raise PrepareError(f"cannot read {f}: {e}")
        jobs = [(fa, Path(cfg.params["infasta"]))]
        if trees is not None:
            binary, origin, tree_notes = trees
            if notes is not None:
                notes.extend(tree_notes)
            for text, dst in ((binary, cfg.params["SPECIES_TREE"]),
                              (origin, cfg.params["ORIGIN_TREE"])):
                t = paths.mkstemp("tree_", ".newick")
                tmps.append(t)
                paths.write_text(t, text + "\n", encoding="utf-8")
                jobs.append((t, Path(dst)))
        t = paths.mkstemp("species_info_", ".tsv")
        tmps.append(t)
        paths.write_text(t, info, encoding="utf-8")
        jobs.append((t, model.species_info_path(cfg)))
        mode = paths.default_file_mode()
        for tmp, dst in jobs:
            paths.mkdir(dst.parent, exist_ok=True)
            paths.chmod(tmp, mode)                     # mkstemp's 0600 -> what open() would give
            paths.replace(tmp, dst)
            written.append(dst)
    finally:
        for t in tmps:
            if t.exists():
                paths.unlink(t)
    return written
