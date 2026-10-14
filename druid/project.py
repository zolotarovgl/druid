"""druid init / druid adopt: make a project dir, or open a phylohpc project in place."""
from __future__ import annotations

from pathlib import Path

import yaml

from druid import paths

ShippedData = ("species_tree.binary.newick", "species_tree.newick", "species_info.tsv",
               "Mmus_gene_names.csv")
TEMPLATE = paths.DRUID_HOME / "druid" / "templates" / "druid.yaml"
DATA = paths.DRUID_HOME / "druid" / "data"


class ProjectError(RuntimeError):
    pass


def init(dest: Path, today: str) -> list:
    dest = Path(dest).expanduser().resolve()
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ProjectError(f"{dest} is not empty; druid init needs a new or empty directory")
    paths.mkdir(dest / "data", parents=True, exist_ok=True, root=dest)
    out = [paths.write_text(dest / "druid.yaml", TEMPLATE.read_text().format(today=today), root=dest)]
    out += [paths.copy2(DATA / f, dest / "data" / f, root=dest) for f in ShippedData]
    out.append(paths.write_text(dest / "data" / "families.csv", "", root=dest))
    return out


def adopt(dest: Path, today: str) -> Path:
    dest = Path(dest).expanduser().resolve()
    old = dest / "phylocli" / "config.yaml"
    if (dest / paths.CONFIG_NAME).exists():
        raise ProjectError(f"{dest / paths.CONFIG_NAME} already exists; nothing written")
    if not old.is_file():
        raise ProjectError(f"{old} not found: not a phylohpc project with phylocli/config.yaml")
    raw = yaml.safe_load(old.read_text()) or {}
    raw.setdefault("runs_dir", "phylocli/runs")
    raw.setdefault("nextflow_dir", ".")
    raw["prepare"] = "locked"
    head = (f"# druid project adopted from phylocli/config.yaml on {today} (druid adopt).\n"
            "# prepare: locked -- data/input.fasta is curated; druid never rebuilds it\n"
            "# (Phylogenies_v3/PROVENANCE.md: rebuilding from xgraubove breaks 11 species' ids).\n")
    return paths.write_text(dest / paths.CONFIG_NAME, head + yaml.safe_dump(raw, sort_keys=False),
                            root=dest)
