"""Write boundary (spec 2026-10-14): druid writes only inside the project."""
import ast
from pathlib import Path

import pytest

from druid import core, paths

PKG = paths.DRUID_HOME / "druid"
ATTR_WRITES = {"write_text", "write_bytes", "mkdir", "symlink_to", "hardlink_to", "touch",
               "unlink", "rmdir", "rename", "chmod"}
MOD_WRITES = {"shutil": {"copy", "copy2", "copyfile", "copytree", "move", "rmtree"},
              "os": {"replace", "rename", "remove", "unlink", "makedirs", "mkdir", "rmdir", "symlink"},
              "tempfile": {"mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryDirectory",
                           "gettempdir", "TemporaryFile", "SpooledTemporaryFile"}}


def _offences(path: Path) -> list:
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute):
            if isinstance(f.value, ast.Name) and f.value.id == "paths":
                continue                                  # the gate itself
            base = f.value.id if isinstance(f.value, ast.Name) else None
            if base in MOD_WRITES and f.attr in MOD_WRITES[base]:
                out.append(f"{path.name}:{node.lineno} {base}.{f.attr}")
            elif base not in MOD_WRITES and f.attr in ATTR_WRITES:
                out.append(f"{path.name}:{node.lineno} .{f.attr}()")
        elif isinstance(f, ast.Name) and f.id == "open":
            mode = node.args[1] if len(node.args) > 1 else next(
                (k.value for k in node.keywords if k.arg == "mode"), None)
            if mode is not None and not (isinstance(mode, ast.Constant)
                                         and not set(str(mode.value)) & set("wax+")):
                out.append(f"{path.name}:{node.lineno} open(mode={ast.dump(mode)})")
    return out


def test_no_write_outside_paths_module():
    files = [p for p in sorted(PKG.glob("*.py")) if p.name != "paths.py"]
    assert files, PKG
    bad = [o for p in files for o in _offences(p)]
    assert bad == [], "write calls must go through druid.paths:\n" + "\n".join(bad)


def test_lint_catches_a_write(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("import shutil, os\nfrom pathlib import Path\nPath('a').write_text('x')\n"
                 "shutil.copy2('a', 'b')\nos.replace('a', 'b')\nopen('a', 'w')\nopen('a')\n")
    assert len(_offences(f)) == 4


def test_lint_exempts_the_gate(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("from druid import paths\npaths.write_text('a', 'x')\npaths.mkdir('a')\n"
                 "paths.unlink('a')\n")
    assert _offences(f) == []


@pytest.mark.parametrize("key", ["outdir", "runs_dir", "infasta", "genefam_info"])
def test_config_refuses_write_targets_outside_the_project(results_tree, tmp_path, key):
    import yaml
    _cfg, root = results_tree
    raw = yaml.safe_load((root / "druid.yaml").read_text())
    outside = str(tmp_path / "outside" / "x")
    if key in ("outdir", "runs_dir"):
        raw[key] = outside
    else:
        raw["params"][key] = outside
    with pytest.raises(ValueError, match="inside the project"):
        core.config_from_raw(raw)


def test_config_allows_read_only_inputs_outside(results_tree, tmp_path):
    import yaml
    _cfg, root = results_tree
    raw = yaml.safe_load((root / "druid.yaml").read_text())
    raw["params"]["pfam_db"] = "/users/asebe/xgraubove/data/pfam/Pfam-A.hmm"
    raw["params"]["SPECIES_TREE"] = str(tmp_path / "elsewhere.newick")
    core.config_from_raw(raw)                                    # no error
