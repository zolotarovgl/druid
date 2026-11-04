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
