"""A bad or incomplete druid.yaml is one `ERROR:` line and exit 2, never a traceback."""
import pytest
import yaml

from druid import core, paths
from tests.test_cli import cli  # noqa: F401  (fixture)


def _raw(root):
    return yaml.safe_load((root / "druid.yaml").read_text())


def _put(root, raw):
    (root / "druid.yaml").write_text(yaml.safe_dump(raw))


def _clean(r, *needles):
    assert r.exit_code == 2, (r.exit_code, r.output)
    assert "ERROR:" in r.output and "Traceback" not in r.output, r.output
    for n in needles:
        assert n in r.output, r.output


def test_config_error_is_a_value_error_exported_by_core():
    assert core.ConfigError is paths.ConfigError and issubclass(core.ConfigError, ValueError)


@pytest.mark.parametrize("cmd", [["status"], ["tui"], ["jobs"], ["submit", "align", "tfs.C_x.HG1", "-n"]])
def test_malformed_yaml(cli, results_tree, cmd):
    _cfg, root = results_tree
    (root / "druid.yaml").write_text("a: [unclosed\n")
    _clean(cli(cmd), "druid.yaml")


@pytest.mark.parametrize("cmd", [["status"], ["tui"], ["jobs"], ["submit", "align", "tfs.C_x.HG1", "-n"]])
@pytest.mark.parametrize("text", ["", "# only a comment\n", "- a\n- list\n"])
def test_empty_or_non_mapping_yaml(cli, results_tree, cmd, text):
    _cfg, root = results_tree
    (root / "druid.yaml").write_text(text)
    _clean(cli(cmd), "druid.yaml")


@pytest.mark.parametrize("key", ["outdir", "partition", "qos", "params"])
@pytest.mark.parametrize("cmd", [["status"], ["submit", "align", "tfs.C_x.HG1", "-n"]])
def test_missing_required_key(cli, results_tree, cmd, key):
    _cfg, root = results_tree
    raw = _raw(root)
    del raw[key]
    _put(root, raw)
    _clean(cli(cmd), key)


def test_params_must_be_a_mapping(cli, results_tree):
    _cfg, root = results_tree
    raw = _raw(root)
    raw["params"] = ["a"]
    _put(root, raw)
    _clean(cli(["status"]), "params")


def test_druid_config_pointing_nowhere(cli, results_tree, tmp_path, monkeypatch):
    monkeypatch.setenv("DRUID_CONFIG", str(tmp_path / "nonexist.yaml"))
    for cmd in (["status"], ["jobs"], ["submit", "align", "tfs.C_x.HG1", "-n"], ["tui"]):
        _clean(cli(cmd), "nonexist.yaml")


def test_config_from_raw_rejects_a_non_mapping():
    with pytest.raises(core.ConfigError):
        core.config_from_raw(["x"])


def test_main_wrapper_catches_config_error(results_tree, monkeypatch, capsys):
    """`python cli.py ...` (what array jobs run) prints ERROR: and exits 2 on a bad config."""
    import runpy
    import sys
    _cfg, root = results_tree
    (root / "druid.yaml").write_text("a: [unclosed\n")
    monkeypatch.setattr(sys, "argv", ["druid", "status"])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(str(paths.DRUID_HOME / "druid" / "cli.py"), run_name="__main__")
    assert e.value.code == 2 and "ERROR:" in capsys.readouterr().err
