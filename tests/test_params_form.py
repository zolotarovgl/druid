"""params_form: the Setup parameter fields, presets, parsing and the freeze rule."""
from __future__ import annotations

import pytest

from druid import params_form


def _f(key):
    return next(f for f in params_form.FIELDS if f.key == key)


def test_fields_cover_the_spec_keys():
    assert [f.key for f in params_form.FIELDS] == ["s2_inflation", "max_n", "domain_expand",
        "s1_ncpu", "s2_ncpu", "MAFFT_OPT", "TREE_METHOD", "IQTREE2_MODEL", "min_seqs",
        "min_distinct", "SUBS_MODEL", "MAX_SPR", "NCPU_GENERAX", "REFSPECIES", "REFNAMES"]
    assert {f.key for f in params_form.FIELDS if not f.frozen} == {"s1_ncpu", "s2_ncpu", "NCPU_GENERAX"}
    assert [f.group for f in params_form.FIELDS][0] == "Clustering"
    assert {f.group for f in params_form.FIELDS} == {"Clustering", "Alignment", "Phylogeny",
                                                     "GeneRax", "POSSVM"}


def test_choices_keep_an_unknown_value_as_custom():
    f = _f("MAFFT_OPT")
    assert params_form.choices(f, "--auto --reorder", [])[-1] == ("custom: --auto --reorder", "--auto --reorder")
    assert ("linsi", "--maxiterate 1000 --localpair") in params_form.choices(f, "--maxiterate 1000 --localpair", [])
    assert not any(l.startswith("custom") for l, _ in params_form.choices(f, "--auto", []))


def test_mafft_presets_verbatim():
    assert dict(_f("MAFFT_OPT").presets) == {"linsi": "--maxiterate 1000 --localpair",
        "einsi": "--maxiterate 1000 --genafpair --ep 0", "ginsi": "--maxiterate 1000 --globalpair",
        "auto": "--auto"}


def test_species_choices_are_the_ticked_species():
    f = _f("REFSPECIES")
    assert params_form.choices(f, "Mmus", ["Aaa", "Mmus"]) == [("Aaa", "Aaa"), ("Mmus", "Mmus")]
    assert params_form.choices(f, "Hsap", ["Aaa"])[-1] == ("custom: Hsap", "Hsap")


@pytest.mark.parametrize("key,text,want", [("s2_inflation", "1.4", 1.4), ("max_n", "2000", 2000),
                                           ("domain_expand", "0", 0)])
def test_parse_numbers(key, text, want, tmp_path):
    got = params_form.parse(_f(key), text, tmp_path)
    assert got == want and type(got) is type(want)


@pytest.mark.parametrize("key,text", [("s2_inflation", "0"), ("s2_inflation", "1,5"),
    ("max_n", "abc"), ("max_n", "2.5"), ("min_seqs", "3"), ("s1_ncpu", "-1")])
def test_parse_refuses(key, text, tmp_path):
    with pytest.raises(ValueError):
        params_form.parse(_f(key), text, tmp_path)


def test_parse_path_must_exist(tmp_path):
    (tmp_path / "names.csv").write_text("a\tb\n")
    f = _f("REFNAMES")
    assert params_form.parse(f, "names.csv", tmp_path) == "names.csv"
    with pytest.raises(ValueError):
        params_form.parse(f, "missing.csv", tmp_path)


def test_tilde_path_is_the_file_the_stages_get(tmp_path, monkeypatch):
    """`~` in REFNAMES: parse and the blocker expand it, and so does core (the possvm stage's
    params.REFNAMES), never <root>/~/names.csv (final review 04/11/2026)."""
    from druid import core
    home = tmp_path / "home"
    home.mkdir()
    (home / "names.csv").write_text("a\tb\n")
    monkeypatch.setenv("HOME", str(home))
    root = tmp_path / "proj"
    root.mkdir()
    assert params_form.parse(_f("REFNAMES"), "~/names.csv", root) == "~/names.csv"
    cfg = core.config_from_raw({"outdir": "results", "partition": "p", "qos": "q",
                                "params": {"REFNAMES": "~/names.csv"}}, root)
    assert cfg.params["REFNAMES"] == str(home / "names.csv")


@pytest.mark.parametrize("text", ["inf", "-inf", "nan", "1e999"])
def test_parse_refuses_non_finite(text, tmp_path):
    for key in ("s2_inflation", "max_n"):
        with pytest.raises(ValueError):
            params_form.parse(_f(key), text, tmp_path)


def _align_parser():
    """main.py's argparse parser, built by its own code (the `__main__` block up to parse_args),
    without importing main.py's helpers (the submodule is not edited)."""
    import argparse
    import ast
    from druid import paths
    tree = ast.parse((paths.DRUID_HOME / "submodules/phylogeny/main.py").read_text())
    main = next(n for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.dump(n.test))
    body = []
    for st in main.body:
        if "parse_args" in ast.dump(st):
            break
        body.append(st)
    ns = {"argparse": argparse}
    exec(compile(ast.Module(body=body, type_ignores=[]), "main.py", "exec"), ns)
    return ns["parser"]


@pytest.mark.parametrize("label,opt", _f("MAFFT_OPT").presets)
def test_align_sh_passes_every_mafft_preset(label, opt):
    """druid/stages/align.sh's main.py align line, expanded by bash with MAFFT_OPT=<preset>, parses
    to mafft == the preset (`-m --auto` was refused by argparse: final review 04/11/2026)."""
    import os
    import subprocess
    from druid import paths
    sh = (paths.DRUID_HOME / "druid/stages/align.sh").read_text().splitlines()
    line = next(l for l in sh if "main.py align" in l)
    cmd = line.replace("python ${DRUID_HOME}/submodules/phylogeny/main.py", "printf '%s\\0'")
    assert cmd != line
    out = subprocess.run(["bash", "-c", cmd], check=True, capture_output=True,
                         env={**os.environ, "FASTA": "x.fasta", "ID": "x", "CPUS": "2",
                              "MAFFT_OPT": opt}).stdout.decode()
    args = _align_parser().parse_args(out.split("\0")[:-1])
    assert args.command == "align" and args.mafft == opt
