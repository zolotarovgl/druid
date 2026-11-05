"""Setup › Parameters: the fields, their presets, typed-value parsing and the freeze rule. Pure
logic; the Setup screen renders it. Spec: docs/superpowers/specs/2026-11-04-setup-parameters-design.md."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from druid import setup_state


@dataclass(frozen=True)
class Field:
    key: str
    group: str
    label: str
    kind: str                     # "number" | "preset" | "species" | "path"
    presets: tuple = ()           # (label, value) pairs
    num: str = ""                 # "int" | "float"
    minimum: float = 0
    frozen: bool = True           # read-only once the first job exists


def _preset(key, group, label, presets):
    return Field(key, group, label, "preset", presets=tuple(presets))


FIELDS = (
    Field("s2_inflation", "Clustering", "MCL inflation (default)", "number", num="float"),
    Field("max_n", "Clustering", "maximum HG size (seq)", "number", num="int", minimum=1),
    Field("domain_expand", "Clustering", "domain expand (aa)", "number", num="int", minimum=0),
    Field("s1_ncpu", "Clustering", "search cpus", "number", num="int", minimum=1, frozen=False),
    Field("s2_ncpu", "Clustering", "cluster cpus", "number", num="int", minimum=1, frozen=False),
    _preset("MAFFT_OPT", "Alignment", "MAFFT", (
        ("linsi", "--maxiterate 1000 --localpair"),
        ("einsi", "--maxiterate 1000 --genafpair --ep 0"),
        ("ginsi", "--maxiterate 1000 --globalpair"),
        ("auto", "--auto"))),
    _preset("TREE_METHOD", "Phylogeny", "method", [(v, v) for v in ("fasttree", "iqtree2", "iqtree3")]),
    _preset("IQTREE2_MODEL", "Phylogeny", "IQ-TREE model",
            [(v, v) for v in ("TEST", "MFP", "LG+G4", "WAG+G4")]),
    Field("min_seqs", "Phylogeny", "min seqs", "number", num="int", minimum=4),
    Field("min_distinct", "Phylogeny", "min distinct", "number", num="int", minimum=1),
    _preset("SUBS_MODEL", "GeneRax", "model if no IQ-TREE fit",[(v, v) for v in ("LG", "LG+G", "WAG", "JTT")]),
    Field("MAX_SPR", "GeneRax", "max SPR radius", "number", num="int", minimum=1),
    Field("NCPU_GENERAX", "GeneRax", "cpus", "number", num="int", minimum=1, frozen=False),
    Field("REFSPECIES", "POSSVM", "reference species", "species"),
    Field("REFNAMES", "POSSVM", "reference gene names", "path"),
)


def choices(field: Field, current, species: list) -> list:
    """(label, value) entries to pick from; a set value outside them is kept as "custom: <value>"
    so opening Setup never changes it."""
    out = [(s, s) for s in species] if field.kind == "species" else list(field.presets)
    if current not in (None, "") and current not in [v for _l, v in out]:
        out.append((f"custom: {current}", current))
    return out


def parse(field: Field, text: str, root: Path):
    """The typed text as the value to write; ValueError (one line, names the label) when refused."""
    text = (text or "").strip()
    if field.kind == "number":
        conv = int if field.num == "int" else float
        try:
            v = conv(text)
        except ValueError:
            raise ValueError(f"{field.label}: {text!r} is not {'an integer' if conv is int else 'a number'}") from None
        if not math.isfinite(v):                 # float("inf"), float("nan")
            raise ValueError(f"{field.label}: {text!r} is not a finite number")
        if field.key == "s2_inflation":
            if not v > 0:
                raise ValueError(f"{field.label}: must be > 0")
        elif v < field.minimum:
            raise ValueError(f"{field.label}: must be >= {int(field.minimum)}")
        return v
    if field.kind == "path":
        p = Path(text).expanduser()
        if not text or not (p if p.is_absolute() else Path(root) / p).is_file():
            raise ValueError(f"{field.label}: file not found: {text}")
        return text
    if not text:
        raise ValueError(f"{field.label}: empty")
    return text


def frozen(raw: dict, cfg) -> bool:
    return setup_state.species_locked(raw, cfg)
