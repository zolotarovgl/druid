"""Where druid is installed, which project it works on, and the write gate.

druid writes only inside the project directory (spec 2026-10-14, "Write boundary"): every write
in druid goes through the functions below, which refuse a path outside the project. Content
writes follow symlinks (a link pointing out is refused); removing an entry (unlink, rmtree,
creating a symlink) checks the entry itself, so a work dir's links to read-only inputs can be
removed without touching their targets.
"""
from __future__ import annotations

import os
import shutil
import tempfile as _tempfile
from pathlib import Path
from typing import Optional, Union

import yaml

DRUID_HOME = Path(__file__).resolve().parents[1]
CONFIG_NAME = "druid.yaml"
HOW = ("pass --project DIR, set DRUID_PROJECT, or run inside a directory that has a druid.yaml "
       "(druid init DIR makes one)")

PathLike = Union[str, Path]
_explicit: Optional[Path] = None


class NoProject(RuntimeError):
    pass


class OutsideProject(RuntimeError):
    pass


def use(project: Optional[PathLike]) -> None:
    """Set the project explicitly (the CLI's --project); None clears it."""
    global _explicit
    _explicit = Path(project).expanduser().resolve() if project is not None else None


def _checked(p: Path, how: str) -> Path:
    if not (p / CONFIG_NAME).is_file():
        raise NoProject(f"{p} ({how}) has no {CONFIG_NAME}; {HOW}")
    return p


def project_root() -> Path:
    if _explicit is not None:
        return _checked(_explicit, "--project")
    env = os.environ.get("DRUID_PROJECT")
    if env:
        return _checked(Path(env).expanduser().resolve(), "DRUID_PROJECT")
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / CONFIG_NAME).is_file():
            return d
    raise NoProject(f"no druid project here; {HOW}")


def config_file() -> Path:
    env = os.environ.get("DRUID_CONFIG")
    return Path(env) if env else project_root() / CONFIG_NAME


def runs_dir() -> Path:
    raw = yaml.safe_load(config_file().read_text()) or {}
    p = Path(raw.get("runs_dir") or "runs")
    return p if p.is_absolute() else project_root() / p


def _abs(p: PathLike) -> Path:
    q = Path(p).expanduser()
    return q if q.is_absolute() else Path.cwd() / q


def _entry_path(q: Path) -> Path:
    """The directory entry `q` names, its parent resolved. A trailing '.' or '..' names no entry
    of its own (`proj/..` is the parent of the project), so the whole path is resolved instead."""
    if q.name in ("", ".", ".."):
        return q.resolve()
    return q.parent.resolve() / q.name


def writable(p: PathLike, root: Optional[Path] = None, entry: bool = False) -> Path:
    """`p` as an absolute path if writing it stays inside the project, else OutsideProject.
    entry=True checks the directory entry itself (its parent resolved), not a symlink's target."""
    root = Path(root).resolve() if root is not None else project_root()
    q = _abs(p)
    r = _entry_path(q) if entry else q.resolve()
    if r != root and root not in r.parents:
        raise OutsideProject(f"refusing to write {p}: outside the project {root}")
    return q


def _removable(p: PathLike) -> Path:
    """writable(entry=True), and never the project root itself."""
    q = writable(p, entry=True)
    root = project_root()
    if _entry_path(q) == root:
        raise OutsideProject(f"refusing to remove the project root {root}")
    return q


def tmp_dir() -> Path:
    d = project_root() / ".druid" / "tmp"
    writable(d)                                # content mode: a .druid link pointing out is refused
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_text(p: PathLike, text: str) -> Path:
    q = writable(p)
    q.write_text(text)
    return q


def append_text(p: PathLike, text: str) -> Path:
    q = writable(p)
    with open(q, "a") as fh:
        fh.write(text)
    return q


def mkdir(p: PathLike, parents: bool = True, exist_ok: bool = False) -> Path:
    q = writable(p)
    q.mkdir(parents=parents, exist_ok=exist_ok)
    return q


def copy2(src: PathLike, dst: PathLike) -> Path:
    q = writable(dst)
    shutil.copy2(src, q)                       # follows symlinks in src: copies the content
    return q


def copytree(src: PathLike, dst: PathLike) -> Path:
    q = writable(dst)
    shutil.copytree(src, q)                    # symlinks=False: copies link targets
    return q


def replace(src: PathLike, dst: PathLike) -> Path:
    writable(src, entry=True)
    q = writable(dst, entry=True)
    os.replace(src, q)
    return q


def rmtree(p: PathLike) -> None:
    shutil.rmtree(_removable(p))               # never follows symlinks inside the tree


def unlink(p: PathLike) -> None:
    _removable(p).unlink()


def symlink(link: PathLike, target: PathLike) -> Path:
    q = writable(link, entry=True)
    q.symlink_to(target)
    return q


def mkstemp(prefix: str, suffix: str) -> Path:
    fd, name = _tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=str(tmp_dir()))
    os.close(fd)
    return Path(name)
