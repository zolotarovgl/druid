"""The vendored treeview (spec 2026-10-12, P1)."""
import os
import re
import subprocess
from pathlib import Path

from phylocli import core

VENDOR = core.ROOT / "phylocli/vendor"
SCRIPT = VENDOR / "update_treeview.sh"


def test_vendored_treeview_is_imported_from_vendor():
    import treeview.keys  # noqa: F401
    import treeview.widget  # noqa: F401
    import treeview
    assert Path(treeview.__file__).resolve().is_relative_to(VENDOR.resolve())
    v = (VENDOR / "treeview/VENDORED").read_text()
    assert re.search(r"^commit: [0-9a-f]{40}$", v, re.M)
    assert not (VENDOR / "treeview/tests").exists()


def _src_repo(tmp_path):
    src = tmp_path / "src"
    (src / "treeview/tests").mkdir(parents=True)
    (src / "treeview/__init__.py").write_text("")
    (src / "treeview/model.py").write_text("X = 1\n")
    (src / "treeview/tests/test_x.py").write_text("")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=src, check=True, env=env)
    return src


def test_update_script_copies_without_tests_and_refuses_dirty(tmp_path):
    src = _src_repo(tmp_path)
    dest = tmp_path / "vendor"
    env = dict(os.environ, TREEVIEW_REMOTE_REPO=str(src), VENDOR_DEST=str(dest))
    (src / "treeview/stray.py").write_text("untracked\n")                 # not in the commit
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (dest / "treeview/model.py").read_text() == "X = 1\n"
    assert not (dest / "treeview/tests").exists()
    assert not (dest / "treeview/stray.py").exists()                      # bytes come from the commit
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True,
                          text=True).stdout.strip()
    vendored = (dest / "treeview/VENDORED").read_text()
    assert f"commit: {head}" in vendored
    (src / "treeview/model.py").write_text("X = 2\n")                     # uncommitted change
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "uncommitted" in r.stderr
    assert (dest / "treeview/model.py").read_text() == "X = 1\n"         # nothing copied
    assert (dest / "treeview/VENDORED").read_text() == vendored          # stamp untouched
