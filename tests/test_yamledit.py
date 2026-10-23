"""yamledit: set druid.yaml keys without losing comments (sub-project 2)."""
from pathlib import Path

import pytest
import yaml

from druid import core, paths, project, yamledit


@pytest.fixture
def proj(tmp_path):
    dest = tmp_path / "proj"
    project.init(dest, today="23/10/2026")
    paths.use(dest)
    return dest


def _comments(text):
    return [l for l in text.splitlines() if l.lstrip().startswith("#")]


def test_set_top_list_keeps_comments(proj):
    text = (proj / "druid.yaml").read_text()
    new = yamledit.set_key(text, ("species",), ["Mlei", "Hsap"])
    assert yaml.safe_load(new)["species"] == ["Mlei", "Hsap"]
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            assert line in new.splitlines()
    # a second, longer-to-shorter rewrite replaces the whole block, leaving no stale items
    again = yamledit.set_key(new, ("species",), ["Nvec"])
    assert yaml.safe_load(again)["species"] == ["Nvec"]
    assert _comments(again) == _comments(text)


def test_set_nested_scalar_keeps_inline_comment(proj):
    text = (proj / "druid.yaml").read_text()
    new = yamledit.set_key(text, ("params", "min_seqs"), 7)
    assert yaml.safe_load(new)["params"]["min_seqs"] == 7
    line = [l for l in new.splitlines() if l.strip().startswith("min_seqs:")][0]
    assert line.startswith("  min_seqs: 7") and "# skip HGs with fewer seqs" in line
    new = yamledit.set_key(text, ("params", "run_generax"), False)
    assert yaml.safe_load(new)["params"]["run_generax"] is False
    assert _comments(new) == _comments(text)


def test_append_missing_top_and_nested(proj):
    text = (proj / "druid.yaml").read_text()
    new = yamledit.set_key(text, ("species_locked",), True)
    assert new.endswith("species_locked: true\n")
    assert yaml.safe_load(new)["species_locked"] is True
    cut = "".join(l for l in text.splitlines(True) if not l.strip().startswith("origins:"))
    assert "origins" not in yaml.safe_load(cut)["params"]
    new = yamledit.set_key(cut, ("params", "origins"), False)
    got = yaml.safe_load(new)
    assert got["params"]["origins"] is False
    assert got["params"]["s2_inflation"] == 1.1          # still inside params
    assert new.splitlines()[-1].strip() == "origins: false"


def test_other_keys_unchanged(proj):
    text = (proj / "druid.yaml").read_text()
    before = yaml.safe_load(text)
    new = yaml.safe_load(yamledit.set_key(yamledit.set_key(text, ("species",), ["A", "B"]),
                                          ("params", "max_n"), 5))
    before["species"] = ["A", "B"]
    before["params"]["max_n"] = 5
    assert new == before


def test_update_config_writes_and_validates(proj):
    out = yamledit.update_config({("species",): ["Mlei"], ("params", "gxsup"): False})
    assert out == proj / "druid.yaml"
    raw = paths.read_raw()
    assert raw["species"] == ["Mlei"] and raw["params"]["gxsup"] is False


def test_update_config_refuses_invalid(proj):
    f = proj / "druid.yaml"
    before = f.read_bytes()
    with pytest.raises(core.ConfigError):
        yamledit.update_config({("outdir",): "/elsewhere/results"})
    assert f.read_bytes() == before
