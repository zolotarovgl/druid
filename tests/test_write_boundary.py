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


IO_LIKE = {"io", "gzip", "bz2", "lzma", "codecs"}      # open(file, mode): the mode is argument 2
MODE_CHARS = set("rwxabtU+")


def _bindings(tree) -> list:
    """Every place the name `paths` is bound: ('gate', node) for `from druid import paths`
    (no asname), ('other', node) for anything else."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if (a.asname or a.name) == "paths":
                    gate = n.module == "druid" and n.level == 0 and a.name == "paths" and a.asname is None
                    out.append(("gate" if gate else "other", n))
        elif isinstance(n, ast.Import):
            for a in n.names:
                if (a.asname or a.name.split(".")[0]) == "paths":
                    out.append(("other", n))
        elif isinstance(n, ast.Name) and n.id == "paths" and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.append(("other", n))
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == "paths":
            out.append(("other", n))
        elif isinstance(n, ast.arg) and n.arg == "paths":
            out.append(("other", n))
    return out


def _writes_mode(mode) -> bool:
    """True if an open() mode argument may write: not a constant, or a constant with w, a, x or +."""
    return not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                and not set(mode.value) & set("wax+"))


def _kw(node, name):
    return next((k.value for k in node.keywords if k.arg == name), None)


def _offences(path: Path) -> list:
    tree = ast.parse(path.read_text())
    binds = _bindings(tree)
    gate = bool(binds) and all(k == "gate" for k, _ in binds)   # `paths` is only ever the gate
    out = []
    for k, n in binds:
        if k == "other" and isinstance(n, (ast.Import, ast.ImportFrom)):
            out.append(f"{path.name}:{n.lineno} import rebinding 'paths'")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in MOD_WRITES and a.asname:
                    out.append(f"{path.name}:{node.lineno} import {a.name} as {a.asname}")
        elif isinstance(node, ast.ImportFrom) and node.module in MOD_WRITES and node.level == 0:
            for a in node.names:
                if a.name == "*" or a.name in MOD_WRITES[node.module]:
                    out.append(f"{path.name}:{node.lineno} from {node.module} import {a.name}")
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute):
            base = f.value.id if isinstance(f.value, ast.Name) else None
            if gate and base == "paths":
                continue                                  # the gate itself
            if base in MOD_WRITES and f.attr in MOD_WRITES[base]:
                out.append(f"{path.name}:{node.lineno} {base}.{f.attr}")
            elif base not in MOD_WRITES and f.attr in ATTR_WRITES:
                out.append(f"{path.name}:{node.lineno} .{f.attr}()")
            elif base == "os" and f.attr == "open":
                flags = node.args[1] if len(node.args) > 1 else _kw(node, "flags")
                if not (isinstance(flags, ast.Attribute) and flags.attr == "O_RDONLY"):
                    out.append(f"{path.name}:{node.lineno} os.open")
            elif f.attr == "open":
                pos = 1 if base in IO_LIKE else 0
                mode = node.args[pos] if len(node.args) > pos else _kw(node, "mode")
                strict = (base in IO_LIKE or _kw(node, "mode") is not None
                          or (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                              and set(mode.value) <= MODE_CHARS))    # Path.open("w"), not webbrowser.open(url)
                if mode is not None and strict and _writes_mode(mode):
                    out.append(f"{path.name}:{node.lineno} .open(mode={ast.dump(mode)})")
        elif isinstance(f, ast.Name) and f.id == "open":
            mode = node.args[1] if len(node.args) > 1 else _kw(node, "mode")
            if mode is not None and _writes_mode(mode):
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


@pytest.mark.parametrize("src", [
    "import shutil as paths\npaths.write_text('a', 'x')\n",                    # not the gate
    "import foo as paths\npaths.write_text('a', 'x')\n",
    "from druid import paths\nimport shutil as paths\npaths.mkdir('a')\n",
    "from druid import paths as p\np.x()\nimport shutil as paths\npaths.mkdir('a')\n",
    "from druid import paths\npaths = object()\npaths.mkdir('a')\n",           # rebound
    "from druid import paths\ndef f(paths):\n    paths.mkdir('a')\n",
    "from other import paths\npaths.write_text('a', 'x')\n",
    "import shutil as sh\nsh.copy2('a', 'b')\n",                                # aliased module
    "import os as o\no.replace('a', 'b')\n",
    "import tempfile as t\nt.mkdtemp()\n",
    "from shutil import copy2\ncopy2('a', 'b')\n",                              # bare names
    "from shutil import rmtree as rm\nrm('a')\n",
    "from os import replace\nreplace('a', 'b')\n",
    "from tempfile import mkstemp\nmkstemp()\n",
    "from os import *\n",
    "from pathlib import Path\nPath('a').open('w')\n",                          # .open writes
    "from pathlib import Path\nPath('a').open(mode='a')\n",
    "from pathlib import Path\nPath('a').open('r+')\n",
    "from pathlib import Path\nm = 'r'\nPath('a').open(mode=m)\n",
    "import io\nio.open('a', 'w')\n",
    "import io\nio.open('a', mode='x')\n",
    "import io\nio.open('a', m)\n",
    "import gzip\ngzip.open('a', 'wt')\n",
    "import os\nos.open('a', os.O_WRONLY)\n",
    "import os\nos.open('a', os.O_RDWR | os.O_CREAT)\n",
])
def test_lint_catches_evasions(tmp_path, src):
    f = tmp_path / "x.py"
    f.write_text(src)
    assert _offences(f), src


@pytest.mark.parametrize("src", [
    "from druid import paths\npaths.write_text('a', 'x')\npaths.copy2('a', 'b')\n",
    "from pathlib import Path\nPath('a').open()\nPath('a').open('r')\nPath('a').open('rb')\n",
    "import io, gzip\nio.open('a')\nio.open('a', 'r')\ngzip.open('a', 'rt')\n",
    "import os, shutil\nos.open('a', os.O_RDONLY)\nos.path.join('a', 'b')\nshutil.which('x')\n",
    "from os import path, environ\nfrom shutil import which\n",
    "import webbrowser\nwebbrowser.open('http://x')\n",
])
def test_lint_allows_reads(tmp_path, src):
    f = tmp_path / "x.py"
    f.write_text(src)
    assert _offences(f) == [], src


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


def test_config_refuses_runs_dir_equal_to_the_project(results_tree):
    import yaml
    _cfg, root = results_tree
    raw = yaml.safe_load((root / "druid.yaml").read_text())
    for val in (".", str(root), "sub/.."):
        raw["runs_dir"] = val
        with pytest.raises(ValueError, match="runs_dir must be a subdirectory of the project"):
            core.config_from_raw(raw)


def test_config_refuses_an_outdir_symlinked_out_of_the_project(results_tree, tmp_path):
    import yaml
    _cfg, root = results_tree
    outside = tmp_path / "outside_results"
    outside.mkdir()
    (root / "linked").symlink_to(outside)
    raw = yaml.safe_load((root / "druid.yaml").read_text())
    raw["outdir"] = str(root / "linked")
    with pytest.raises(ValueError, match="outdir must be inside the project"):
        core.config_from_raw(raw)
