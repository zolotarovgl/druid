"""Gene-family tables: the shipped library, a project's families file, default rows for custom HMMs.

The families file is tab-separated (despite the .csv name), no header, the columns of COLS
(submodules/phylogeny/helper/hmmsearch.py parse_gene_family_info). Family id = <pref>.<class_name>
with pref = the last non-empty field, exactly core.parse_genefam."""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

from druid import paths

COLS = ("class_name", "hmms", "inflation", "min_seqs", "threshold", "pref1", "pref2")


@dataclass
class Row:
    class_name: str
    hmms: str                   # comma-separated HMM names
    inflation: str = "1.1"
    min_seqs: str = "3"
    threshold: str = "GA"
    pref1: str = ""
    pref2: str = ""

    def fields(self) -> list[str]:
        return [getattr(self, f.name) for f in fields(self)]


def read(path) -> list[Row]:
    """Rows of a families file. Blank lines are skipped, short rows padded with ''; a trailing
    empty 8th field is dropped (core.parse_genefam strips the line the same way)."""
    out: list[Row] = []
    for line in Path(path).read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        cols = [c.strip() for c in line.strip().split("\t")][:len(COLS)]
        cols += [""] * (len(COLS) - len(cols))
        out.append(Row(*cols))
    return out


def library() -> list[Row]:
    return read(paths.DRUID_HOME / "druid" / "data" / "families_library.csv")


def write(path, rows) -> Path:
    return paths.write_text(path, "".join("\t".join(r.fields()) + "\n" for r in rows))


def _pref(r: Row) -> str:
    # core.parse_genefam: the last non-empty field of the row
    for v in reversed(r.fields()):
        if v.strip():
            return v.strip()
    return ""


def ticked_ids(rows) -> set[str]:
    return {f"{_pref(r)}.{r.class_name.strip()}" for r in rows}


def inflation_of(path, family_id: str) -> str:
    """The inflation field of the first row of the families file whose id (<pref>.<class_name>) is
    family_id; '' when absent, blank, or the file is unreadable."""
    try:
        rows = read(path)
    except (OSError, TypeError, ValueError):
        return ""
    for r in rows:
        if f"{_pref(r)}.{r.class_name.strip()}" == family_id:
            return r.inflation.strip()
    return ""


def hmm_rows(hmm_dir, inflation: str = "1.1") -> list[Row]:
    """One default row per *.hmm in hmm_dir (read only): threshold GA when the file has a GA line
    (curated gathering cutoff), else the e-value 1e-5; inflation as given (the params default)."""
    out: list[Row] = []
    for p in sorted(Path(hmm_dir).glob("*.hmm")):
        with open(p, errors="replace") as fh:
            has_ga = any(l.startswith("GA ") for l in fh)
        out.append(Row(p.stem, p.stem, inflation, "3", "GA" if has_ga else "1e-5", "custom", "cus"))
    return out
