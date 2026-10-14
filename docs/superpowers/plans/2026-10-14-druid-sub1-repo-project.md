# druid sub-project 1 — repo, project dir, write boundary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split phylocli out of phylohpc into a standalone `druid` repo whose code runs against a project directory (`druid init` / `adopt`), never writes outside it, and ships `doctor` + `environment.yml`.

**Architecture:** `git filter-repo` carries the history of `phylocli/`, `docs/superpowers/` and the 6 phylohpc helpers into a new repo, renamed to a `druid/` package. The single `ROOT` is split into `paths.DRUID_HOME` (the install, read-only) and `paths.project_root()` (discovered from `--project`, `$DRUID_PROJECT`, or the nearest `druid.yaml` above the cwd). Every file write goes through `druid/paths.py`, which refuses paths outside the project; an AST lint test enforces that.

**Tech Stack:** Python 3.9, typer, textual >= 8.2 < 9, rich, ete3 3.1.3, pyyaml, pytest; bash stage scripts; SLURM; git-filter-repo (local: `/home/grygoriyzolotarov/mambaforge/bin/git-filter-repo`).

**Spec:** `/home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt/docs/superpowers/specs/2026-10-14-druid-standalone-design.md` (sub-project 1). After Task 1 the same file is at `docs/superpowers/specs/2026-10-14-druid-standalone-design.md` inside the druid repo.

## Global Constraints

- Repo: `/home/grygoriyzolotarov/Documents/projects/phylogenies/druid` (local dev). Cluster run clone: `~/projects/druid` on `login1.hpc.crg.es` (Task 9). **No GitHub remote is created in this plan** (Task 11 asks Grygoriy first).
- phylohpc (`/home/grygoriyzolotarov/Documents/projects/phylogenies/phylohpc`, worktree `phylocli-wt`) is **never modified** by this plan except for committing this plan/spec on branch `phylocli` before Task 1.
- **druid writes only inside the project directory.** Read-only: the proteome dir (`/users/asebe/xgraubove/genomes/data`), `pfam_db`, `hmm_dir`, `DRUID_HOME`, other projects. Never `hmmpress`. Never `/tmp` (`tempfile` is forbidden in `druid/*.py`).
- Code edits with Edit/Write. Where a task renames many tokens it uses the checked script given in the task (asserts a match count per file; never a bare `sed`).
- Python 3.9 compatible (`Path.is_relative_to` is fine; no `glob(root_dir=)`, no `match`).
- SLURM job names keep the prefix `phylo-` (`druid/model.py` matches squeue names on it; old v3 jobs must still be recognised).
- Run-dir config copies keep the file name `config.yaml` inside each run dir (old v3 run dirs use it).
- Env vars: `DRUID_PROJECT` (project dir), `DRUID_CONFIG` (config file override; set by array jobs to the run dir's `config.yaml`), `DRUID_HISTORY` (replaces `PHYLOCLI_HISTORY`). `PHYLOCLI_CONFIG` / `PHYLOCLI_RUNS` disappear.
- `druid.yaml` top-level keys: `outdir`, `runs_dir` (default `runs`), `nextflow_dir` (default `.`), `partition`, `qos`, `prepare` (`auto` | `locked`), `proteomes_dir`, `proteome_glob`, `species`, `params`. The spec's "`families: data/families.csv`" is realised as the existing `params.genefam_info` (one key for one file).
- Test interpreter (local): `PY=/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-phylogenies/3dad6ea4-c859-4fe6-b319-93a358944ac8/scratchpad/py39/bin/python` (textual 8.2.8). Full suite: `cd /home/grygoriyzolotarov/Documents/projects/phylogenies/druid && $PY -m pytest tests -q -p no:cacheprovider`. If that interpreter is gone, use the cluster `phylo` env in `~/projects/druid` after Task 9.
- CPU: tests are single-process; anything heavier: check `top -bn1 | head -12` first, never more than 24 cores.
- Dates in docs/comments: dd/mm/yyyy. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A run-dir config copy resolving its relative paths against the run dir** instead of the project → jobs read `runs/<run>/data/input.fasta`. Expected: relative paths always resolve against `DRUID_PROJECT`. Pinned in Task 3 (`test_run_dir_config_resolves_against_project`).
2. **A symlink inside the project pointing out** (e.g. `data/input.fasta -> /users/asebe/xgraubove/...`) being written through. Expected: content writes follow symlinks and are refused; removing the link itself is allowed. Pinned in Task 2 (`test_writable_*symlink*`).
3. **`druid` started from outside any project** (e.g. `druid status` in `$HOME`). Expected: one-line error naming `--project`, `$DRUID_PROJECT`, `druid init`; exit 2; no traceback. Pinned in Task 3 (`test_cli_outside_project_says_how`).
4. **Python byte-code written into `DRUID_HOME`** by stage helpers (`drop_small_hgs.py` imports `report_status`). Expected: no `__pycache__` appears under `druid/helpers` from a stage run. Pinned in Task 4 (`PYTHONDONTWRITEBYTECODE=1`) and Task 9.
5. **`adopt` on a dir that already has a `druid.yaml`, or no `phylocli/config.yaml`.** Expected: refuse, write nothing. Pinned in Task 7.

---

### Task 1: Split the repo and rename to the druid layout (tests green, behaviour unchanged)

**Files:**
- Create: repo `/home/grygoriyzolotarov/Documents/projects/phylogenies/druid`
- Move (filter-repo): `phylocli/` → `druid/`, `phylocli/tests/` → `tests/`, `workflow/{og_origin,report_status,possvm_postprocess,reroot_to_generax,remove_gaponly,drop_small_hgs}.py` → `druid/helpers/`, `docs/superpowers/` kept
- Move (git mv): `druid/phylo.py` → `druid/cli.py`, `druid/phylo` → `bin/druid`, `druid/README.md` → `README.md`
- Modify: `druid/core.py:13-15,49`, `druid/common.py:17`, `druid/runner.py:15,22`, `druid/model.py:404`, `druid/tui.py:30`, `druid/cli.py:456`, `druid/stages/*.sh`, `bin/druid`, `tests/conftest.py:7-9`, `tests/test_vendor.py:9`, `tests/test_step1.py` (stage_project, config paths, step1.nf test), every `phylocli` import
- Create: `submodules/phylogeny` (git submodule), `druid/helpers/VENDORED`

**Interfaces:**
- Produces: package `druid` (modules `core common model runner history tui cli`), `druid.runner.DRUID_HOME: Path` (= repo root), stage env var `DRUID_HOME`; stage scripts call `${DRUID_HOME}/submodules/phylogeny/main.py` and `${DRUID_HOME}/druid/helpers/<x>.py`. `druid/config.yaml` is still the default config in this task (Task 3 replaces it).

- [ ] **Step 1: Commit this plan in phylocli-wt first** (so it travels with the history)

```bash
cd /home/grygoriyzolotarov/Documents/projects/phylogenies/phylocli-wt
git add docs/superpowers/plans/2026-10-14-druid-sub1-repo-project.md
git commit -m "plan: druid sub-project 1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git status --porcelain --untracked-files=no   # must be empty
```

- [ ] **Step 2: Fresh clone of branch `phylocli` and filter it**

```bash
cd /home/grygoriyzolotarov/Documents/projects/phylogenies
test ! -e druid
git clone --no-local --branch phylocli --single-branch phylohpc druid
cd druid
git filter-repo \
  --path phylocli/ --path docs/superpowers/ \
  --path workflow/og_origin.py --path workflow/report_status.py \
  --path workflow/possvm_postprocess.py --path workflow/reroot_to_generax.py \
  --path workflow/remove_gaponly.py --path workflow/drop_small_hgs.py \
  --path-rename phylocli/tests/:tests/ \
  --path-rename phylocli/:druid/ \
  --path-rename workflow/:druid/helpers/
git branch -m phylocli main
git remote -v            # expected: empty (filter-repo drops origin)
git ls-files | grep -c . ; git ls-files | grep -vE '^(druid/|tests/|docs/superpowers/)'   # expected: nothing from the second command
git log --oneline | wc -l   # report this number
```

- [ ] **Step 3: git mv the entry points and README**

```bash
git mv druid/phylo.py druid/cli.py
mkdir -p bin && git mv druid/phylo bin/druid
git mv druid/README.md README.md
```

Then Write `bin/druid`:

```bash
#!/usr/bin/env bash
# druid entry point. No byte-code is written into the install (write boundary, spec 14/10/2026).
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$(dirname "$(readlink -f "$0")")/../druid/cli.py" "$@"
```

- [ ] **Step 4: Rename the package in imports with a checked script**

Save as `/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-2022-Mlei/0a22b1f8-b83b-4910-996d-6e5ecad4a2e0/scratchpad/rename_pkg.py` and run it from the repo root with `$PY`:

```python
"""phylocli -> druid in import statements only; fails loudly per file."""
import re, sys
from pathlib import Path

PAT = [(re.compile(r"^(\s*)from phylocli(\.| import)", re.M), r"\1from druid\2"),
       (re.compile(r"^(\s*)import phylocli\b", re.M), r"\1import druid"),
       (re.compile(r"([\"'])phylocli\.(core|common|model|runner|history|tui|phylo)\b"), r"\1druid.\2")]
files = sorted(Path("druid").glob("*.py")) + sorted(Path("tests").glob("*.py"))
total = 0
for f in files:
    s = f.read_text()
    n_file = 0
    for rx, rep in PAT:
        s, n = rx.subn(rep, s)
        n_file += n
    if n_file:
        f.write_text(s)
    print(f"{f}: {n_file}")
    total += n_file
if total == 0:
    sys.exit("no import was renamed: wrong cwd?")
left = [f"{f}:{i+1}: {l}" for f in files for i, l in enumerate(f.read_text().splitlines())
        if re.search(r"\bphylocli\b", l)]
print("\n".join(left))
```

Review every remaining `phylocli` line it prints; change code references with Edit, leave historical comments/docstrings.

- [ ] **Step 5: Path edits (Edit tool, each must match)**

`druid/core.py`:
```python
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "druid" / "helpers"))
sys.path.insert(0, str(ROOT / "druid" / "vendor"))   # vendored treeview (vendor/update_treeview.sh)
```
and `def load_config(path: Path = ROOT / "druid/config.yaml") -> Config:`.

`druid/common.py`: `return Path(os.environ.get("PHYLOCLI_RUNS") or ROOT / "runs")`.

`druid/runner.py`:
```python
DRUID_HOME = ROOT                      # the install: stages, helpers, submodules/phylogeny
STAGES_DIR = DRUID_HOME / "druid/stages"
```
and in `stage_env`: `env.update(ID=hg, CPUS=str(cpus), PROJECT_DIR=str(ROOT), DRUID_HOME=str(DRUID_HOME), OUTDIR=str(cfg.outdir), PYTHONNOUSERSITE="1")`.

`druid/model.py` SBATCH: `python3 "{root}/druid/cli.py" _run {stage} "$HG" --run-dir "{run_dir}" &`.

`druid/tui.py:30` and `druid/cli.py` (the `submit` raw read): `core.ROOT / "druid/config.yaml"`.

Stage scripts — Edit each occurrence (12 total: `phylogeny/main.py` ×7 in align, cluster, generax, possvm, possvm_prev, search, tree; helpers ×5):
- `${PROJECT_DIR}/phylogeny/main.py` → `${DRUID_HOME}/submodules/phylogeny/main.py`
- `${PROJECT_DIR}/workflow/` → `${DRUID_HOME}/druid/helpers/`
Verify: `grep -n 'PROJECT_DIR}/\(phylogeny\|workflow\)' druid/stages/*.sh` → nothing; `grep -c 'DRUID_HOME}' druid/stages/*.sh` sums to 12. Update the header comments of `search.sh`/`cluster.sh` (`Env: ... PROJECT_DIR` → `DRUID_HOME, PROJECT_DIR`).

- [ ] **Step 6: Submodule and helpers record**

```bash
git submodule add https://github.com/zolotarovgl/phylogeny submodules/phylogeny
git -C submodules/phylogeny checkout 2c61675fe329bfb0e1654a69559efaff30f54d4f
git submodule update --init --recursive
git -C submodules/phylogeny/submodules/possvm-orthology rev-parse HEAD   # expected e86caf2cfbe4de30281563c7b64de694a386db02
```
Write `druid/helpers/VENDORED`:
```
source: phylohpc (github.com/zolotarovgl/phylohpc), branch phylocli, workflow/
commit: <output of: git -C /home/grygoriyzolotarov/Documents/projects/phylogenies/phylohpc rev-parse phylocli>
date: 14/10/2026
files: og_origin.py report_status.py possvm_postprocess.py reroot_to_generax.py remove_gaponly.py drop_small_hgs.py
history: carried by git filter-repo; edit them here from now on
```

- [ ] **Step 7: Tests to the new layout**

`tests/conftest.py`:
```python
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "druid" / "helpers"))
from druid import core  # noqa: E402
```
and `base = yaml.safe_load((ROOT / "druid/config.yaml").read_text())`.
`tests/test_vendor.py`: `VENDOR = core.ROOT / "druid/vendor"`.
`tests/test_step1.py`: config path `core.ROOT / "druid/config.yaml"` (lines ~84, ~98); in `stage_project` build the fake install instead of the fake project:
```python
    home = tmp_path / "home"
    (home / "submodules" / "phylogeny").mkdir(parents=True)
    (home / "submodules" / "phylogeny" / "main.py").write_text(FAKE_MAIN)
    (home / "druid").mkdir()
    (home / "druid" / "helpers").symlink_to(core.ROOT / "druid" / "helpers")
    ...
    monkeypatch.setattr(runner, "DRUID_HOME", home)        # stage_env: DRUID_HOME
    return home
```
(keep the PATH stubs as they are). Delete the test asserting `step1.nf` content (lines ~855-858; `step1.nf` is phylohpc's). `tests/test_runner.py:54`: also assert `env["DRUID_HOME"] == str(runner.DRUID_HOME)`.

- [ ] **Step 8: Run the suite**

Run: `$PY -m pytest tests -q -p no:cacheprovider`
Expected: all pass; count = 402 minus the deleted `step1.nf` test(s). Report the exact number.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "druid: split from phylohpc (phylocli/ + 6 workflow helpers), package druid/, submodule phylogeny

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `druid/paths.py` — project discovery and the write gate

**Files:**
- Create: `druid/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Produces (exact):
  - `DRUID_HOME: Path`; `CONFIG_NAME = "druid.yaml"`
  - `class NoProject(RuntimeError)`, `class OutsideProject(RuntimeError)`
  - `use(project: Path | str | None) -> None`; `project_root() -> Path`; `config_file() -> Path`; `runs_dir() -> Path`; `tmp_dir() -> Path`
  - `writable(p, root: Path | None = None, entry: bool = False) -> Path`
  - ops: `write_text(p, text) -> Path`, `mkdir(p, parents=True, exist_ok=False) -> Path`, `copy2(src, dst) -> Path`, `copytree(src, dst) -> Path`, `replace(src, dst) -> Path`, `rmtree(p) -> None`, `unlink(p) -> None`, `symlink(link, target) -> Path`, `mkstemp(prefix: str, suffix: str) -> Path`

- [ ] **Step 1: Write the failing tests** (`tests/test_paths.py`)

```python
"""druid/paths.py: project discovery and the write gate (spec 14/10/2026, Write boundary)."""
import os
from pathlib import Path

import pytest

from druid import paths


@pytest.fixture
def proj(tmp_path, monkeypatch):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "druid.yaml").write_text("outdir: results\nruns_dir: runs\npartition: x\nqos: y\nparams: {}\n")
    monkeypatch.delenv("DRUID_PROJECT", raising=False)
    monkeypatch.delenv("DRUID_CONFIG", raising=False)
    paths.use(None)
    yield p.resolve()
    paths.use(None)


def test_discovery_order_explicit_env_walkup(proj, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    (other / "druid.yaml").write_text("outdir: r\n")
    (proj / "a" / "b").mkdir(parents=True)
    monkeypatch.chdir(proj / "a" / "b")
    assert paths.project_root() == proj                       # walk up
    monkeypatch.setenv("DRUID_PROJECT", str(other))
    assert paths.project_root() == other.resolve()            # env beats walk-up
    paths.use(proj)
    assert paths.project_root() == proj                       # explicit beats env


def test_no_project_names_the_three_ways(tmp_path, monkeypatch):
    monkeypatch.delenv("DRUID_PROJECT", raising=False)
    paths.use(None)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(paths.NoProject) as e:
        paths.project_root()
    msg = str(e.value)
    assert "--project" in msg and "DRUID_PROJECT" in msg and "druid init" in msg


def test_env_or_explicit_without_druid_yaml_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("DRUID_PROJECT", str(tmp_path))
    with pytest.raises(paths.NoProject):
        paths.project_root()
    monkeypatch.delenv("DRUID_PROJECT")
    paths.use(tmp_path)
    with pytest.raises(paths.NoProject):
        paths.project_root()
    paths.use(None)


def test_config_file_and_runs_dir(proj, monkeypatch, tmp_path):
    paths.use(proj)
    assert paths.config_file() == proj / "druid.yaml"
    assert paths.runs_dir() == proj / "runs"
    run_cfg = proj / "runs" / "r1" / "config.yaml"
    run_cfg.parent.mkdir(parents=True)
    run_cfg.write_text("outdir: results\nruns_dir: phylocli/runs\n")
    monkeypatch.setenv("DRUID_CONFIG", str(run_cfg))
    assert paths.config_file() == run_cfg
    assert paths.runs_dir() == proj / "phylocli" / "runs"     # still relative to the project


def test_runs_dir_defaults_to_runs(proj):
    (proj / "druid.yaml").write_text("outdir: results\n")
    paths.use(proj)
    assert paths.runs_dir() == proj / "runs"


def test_writable_inside_and_outside(proj, tmp_path):
    paths.use(proj)
    assert paths.writable(proj / "results" / "x.txt") == proj / "results" / "x.txt"
    for bad in (tmp_path / "elsewhere.txt", proj / ".." / "escape.txt", Path("/tmp/x")):
        with pytest.raises(paths.OutsideProject):
            paths.writable(bad)


def test_writable_relative_is_against_cwd(proj, tmp_path, monkeypatch):
    paths.use(proj)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(paths.OutsideProject):
        paths.writable("x.txt")
    monkeypatch.chdir(proj)
    assert paths.writable("x.txt") == proj / "x.txt"


def test_writable_content_through_outward_symlink_is_refused(proj, tmp_path):
    paths.use(proj)
    outside = tmp_path / "xgraubove"
    outside.mkdir()
    (outside / "Mlei_long.pep.fasta").write_text(">a\nM\n")
    (proj / "data").mkdir()
    (proj / "data" / "link.fasta").symlink_to(outside / "Mlei_long.pep.fasta")
    (proj / "dirlink").symlink_to(outside)
    with pytest.raises(paths.OutsideProject):
        paths.write_text(proj / "data" / "link.fasta", "x")
    with pytest.raises(paths.OutsideProject):
        paths.write_text(proj / "dirlink" / "new.txt", "x")
    assert (outside / "Mlei_long.pep.fasta").read_text() == ">a\nM\n"


def test_unlinking_an_outward_symlink_is_allowed_and_keeps_the_target(proj, tmp_path):
    paths.use(proj)
    target = tmp_path / "t.txt"
    target.write_text("keep")
    link = proj / "l.txt"
    link.symlink_to(target)
    paths.unlink(link)
    assert not link.is_symlink() and target.read_text() == "keep"


def test_rmtree_of_a_workdir_with_outward_links_keeps_targets(proj, tmp_path):
    paths.use(proj)
    target = tmp_path / "t.txt"
    target.write_text("keep")
    work = proj / "runs" / "work" / "HG1"
    paths.mkdir(work, parents=True)
    paths.symlink(work / "t.txt", target)
    paths.rmtree(work)
    assert not work.exists() and target.read_text() == "keep"


def test_ops_inside(proj, tmp_path):
    paths.use(proj)
    src = tmp_path / "src.txt"
    src.write_text("s")
    d = paths.mkdir(proj / "a" / "b", parents=True)
    assert d.is_dir()
    paths.write_text(d / "f.txt", "hello")
    paths.copy2(src, d / "g.txt")
    paths.replace(d / "g.txt", d / "h.txt")
    assert (d / "h.txt").read_text() == "s" and not (d / "g.txt").exists()
    sd = tmp_path / "sd"
    sd.mkdir()
    (sd / "x").write_text("x")
    paths.copytree(sd, d / "sd")
    assert (d / "sd" / "x").read_text() == "x"
    with pytest.raises(paths.OutsideProject):
        paths.copy2(d / "h.txt", tmp_path / "out.txt")
    with pytest.raises(paths.OutsideProject):
        paths.replace(d / "h.txt", tmp_path / "out.txt")


def test_tmp_dir_and_mkstemp_are_in_the_project(proj):
    paths.use(proj)
    assert paths.tmp_dir() == proj / ".druid" / "tmp" and paths.tmp_dir().is_dir()
    f = paths.mkstemp(prefix="nxflog-", suffix=".log")
    assert f.parent == proj / ".druid" / "tmp" and f.name.startswith("nxflog-") and f.exists()


def test_druid_home_is_the_install():
    assert (paths.DRUID_HOME / "druid" / "paths.py").is_file()
```

- [ ] **Step 2: Run to see them fail**

Run: `$PY -m pytest tests/test_paths.py -q -p no:cacheprovider`
Expected: FAIL, `ImportError: cannot import name 'paths'`.

- [ ] **Step 3: Implement `druid/paths.py`**

```python
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


def writable(p: PathLike, root: Optional[Path] = None, entry: bool = False) -> Path:
    """`p` as an absolute path if writing it stays inside the project, else OutsideProject.
    entry=True checks the directory entry itself (its parent resolved), not a symlink's target."""
    root = Path(root).resolve() if root is not None else project_root()
    q = _abs(p)
    r = (q.parent.resolve() / q.name) if entry else q.resolve()
    if r != root and root not in r.parents:
        raise OutsideProject(f"refusing to write {p}: outside the project {root}")
    return q


def tmp_dir() -> Path:
    d = project_root() / ".druid" / "tmp"
    d.mkdir(parents=True, exist_ok=True)       # inside the project by construction
    return d


def write_text(p: PathLike, text: str) -> Path:
    q = writable(p)
    q.write_text(text)
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
    shutil.rmtree(writable(p, entry=True))     # never follows symlinks inside the tree


def unlink(p: PathLike) -> None:
    writable(p, entry=True).unlink()


def symlink(link: PathLike, target: PathLike) -> Path:
    q = writable(link, entry=True)
    q.symlink_to(target)
    return q


def mkstemp(prefix: str, suffix: str) -> Path:
    fd, name = _tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=str(tmp_dir()))
    os.close(fd)
    return Path(name)
```

- [ ] **Step 4: Run** — `$PY -m pytest tests/test_paths.py -q -p no:cacheprovider` → PASS; then the full suite → PASS.

- [ ] **Step 5: Commit** — `git add druid/paths.py tests/test_paths.py && git commit -m "paths: project discovery and the write gate"` (+ co-author line).

---

### Task 3: Project-rooted config, CLI `--project`, env-var rename

**Files:**
- Modify: `druid/core.py` (`ROOT`, `_abs`, `Config.nextflow_dir`, `load_config`), `druid/common.py` (`ROOT`, `runs_dir`), `druid/history.py:83-84` (`history_dir`), `druid/tui.py:28-31` (`load_raw`), `druid/cli.py` (`ROOT` uses, `_cfg`, `submit` raw read, `_print_dry_run` shown path, new callback), `druid/model.py:863,939` (fallbacks)
- Move: `druid/config.yaml` → `druid/templates/druid.yaml` (`git mv`; Task 7 edits its content)
- Modify tests: `tests/conftest.py`, `tests/test_cli.py`, `tests/test_model.py`, `tests/test_step1.py`, `tests/test_tui.py`, `tests/test_history.py`, `tests/test_core.py`

**Interfaces:**
- Consumes: `paths.project_root()`, `paths.config_file()`, `paths.runs_dir()`, `paths.use()`, `paths.NoProject` (Task 2).
- Produces: `core.load_config(path: Path | None = None) -> Config` (None = `paths.config_file()`); relative config paths resolve against `paths.project_root()`; `common.runs_dir() -> Path` = `paths.runs_dir()`; `history.history_dir()` reads `DRUID_HISTORY`; CLI option `--project/-P` on the app callback. `core.ROOT`, `common.ROOT` are removed (any remaining use is a bug). The `results_tree` fixture writes `<root>/druid.yaml` and sets `DRUID_PROJECT=<root>`; it still returns `(cfg, root)`.

- [ ] **Step 1: Failing tests** — add to `tests/test_core.py`:

```python
def test_relative_config_paths_resolve_against_the_project(tmp_path, monkeypatch):
    from druid import paths
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "druid.yaml").write_text(
        "outdir: results\npartition: a\nqos: b\nparams:\n  infasta: data/input.fasta\n  hmm_dir: null\n")
    monkeypatch.setenv("DRUID_PROJECT", str(proj))
    monkeypatch.chdir(tmp_path)                         # cwd is NOT the project
    cfg = core.load_config()
    assert cfg.outdir == proj.resolve() / "results"
    assert cfg.params["infasta"] == str(proj.resolve() / "data/input.fasta")
    assert cfg.params["hmm_dir"] is None
    assert cfg.nextflow_dir == proj.resolve()


def test_run_dir_config_resolves_against_project(tmp_path, monkeypatch):
    proj = tmp_path / "p"
    run = proj / "runs" / "20261014-120000_align"
    run.mkdir(parents=True)
    body = "outdir: results\npartition: a\nqos: b\nparams:\n  infasta: data/input.fasta\n"
    (proj / "druid.yaml").write_text(body)
    (run / "config.yaml").write_text(body)
    monkeypatch.setenv("DRUID_PROJECT", str(proj))
    monkeypatch.setenv("DRUID_CONFIG", str(run / "config.yaml"))
    cfg = core.load_config()
    assert cfg.params["infasta"] == str(proj.resolve() / "data/input.fasta")   # not run/data/...
```

Add to `tests/test_cli.py`:

```python
def test_cli_outside_project_says_how(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from druid import cli, paths
    monkeypatch.delenv("DRUID_PROJECT", raising=False)
    monkeypatch.delenv("DRUID_CONFIG", raising=False)
    paths.use(None)
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli.app, ["status"])
    assert r.exit_code == 2
    assert "--project" in r.output and "druid init" in r.output
    assert "Traceback" not in r.output


def test_project_option_selects_the_project(results_tree, tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from druid import cli, paths
    _cfg, root = results_tree
    monkeypatch.delenv("DRUID_PROJECT", raising=False)
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli.app, ["--project", str(root), "missing"])
    assert r.exit_code == 0, r.output
    assert paths.project_root() == root.resolve()
    paths.use(None)
```

- [ ] **Step 2: Run** — `$PY -m pytest tests/test_core.py tests/test_cli.py -q -p no:cacheprovider` → the new tests FAIL.

- [ ] **Step 3: Implement**

`druid/core.py` top:
```python
from druid import paths

sys.path.insert(0, str(paths.DRUID_HOME / "druid" / "helpers"))
sys.path.insert(0, str(paths.DRUID_HOME / "druid" / "vendor"))   # vendored treeview (vendor/update_treeview.sh)
import report_status  # noqa: E402
```
(delete `ROOT = ...`). Then:
```python
@dataclass(frozen=True)
class Config:
    outdir: Path
    params: dict
    partition: str
    qos: str
    nextflow_dir: Path = Path(".")   # set by config_from_raw (project root unless configured)


def _abs(p) -> str:
    p = Path(p)
    return str(p if p.is_absolute() else paths.project_root() / p)


def load_config(path: Path | None = None) -> Config:
    return config_from_raw(yaml.safe_load(Path(path or paths.config_file()).read_text()))
```
`druid/common.py`: delete `ROOT`; `def runs_dir() -> Path: return paths.runs_dir()` (import `from druid import paths`).
`druid/history.py`:
```python
def history_dir() -> Path:
    p = os.environ.get("DRUID_HISTORY")
    return Path(p) if p else runs_dir().parent / "history"
```
`druid/tui.py`:
```python
def load_raw() -> dict:
    """The raw druid.yaml (same path logic as `druid submit`); written into each run dir."""
    return yaml.safe_load(paths.config_file().read_text())
```
`druid/model.py`: `species_info_path` → `... else paths.project_root() / p`; `origin_tree_path` → `... else paths.project_root() / "data/species_tree.newick"`. In `write_run` the SBATCH `root=` argument stays `paths.DRUID_HOME` for now (Task 4 changes the template).
`druid/cli.py`:
```python
ROOT = Path(__file__).resolve().parents[1]          # the install, for sys.path only
...
from druid import core, history, model, paths, runner  # noqa: E402


@app.callback()
def main(project: Path = typer.Option(None, "--project", "-P",
                                      help="project directory (else $DRUID_PROJECT, else the "
                                           "nearest druid.yaml above the cwd)")):
    paths.use(project)


def _cfg() -> core.Config:
    try:
        return core.load_config()
    except paths.NoProject as e:
        _fail(f"ERROR: {e}", 2)
```
`submit`: `raw = yaml.safe_load(paths.config_file().read_text())` wrapped in the same `NoProject` → `_fail`. `_print_dry_run`: `shown = run_dir.relative_to(paths.project_root())`. Wrap `app()` in `if __name__ == "__main__":` so any other `NoProject` reaching the top prints `ERROR: ...` and exits 2:
```python
if __name__ == "__main__":
    try:
        app()
    except paths.NoProject as e:
        typer.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
```
and give `typer.Typer(...)` `pretty_exceptions_enable=False`. For `CliRunner` tests the callback/commands must raise via `_fail`: every command that resolves the project calls `_cfg()` (or the guarded raw read) before anything else.

`git mv druid/config.yaml druid/templates/druid.yaml`.

Tests — apply these rules everywhere (Edit):
- `os.environ["PHYLOCLI_CONFIG"]` → `str(paths.config_file())`; `monkeypatch.setenv("PHYLOCLI_CONFIG", X)` → write the config to `<project>/druid.yaml` and `monkeypatch.setenv("DRUID_PROJECT", <project>)`.
- `PHYLOCLI_RUNS` → `runs_dir:` key in the fixture's `druid.yaml`, a path **inside** the fixture project (e.g. `runs`); tests that pointed runs elsewhere use `<root>/runs`.
- `PHYLOCLI_HISTORY` → `DRUID_HISTORY`.
- `core.ROOT / "druid/config.yaml"` → `paths.DRUID_HOME / "druid/templates/druid.yaml"`; `core.ROOT / "data/..."` expectations (test_model ~462/468, test_step1 ~92/93) → `paths.project_root() / "data/..."`.
- `tests/conftest.py` `results_tree`: write `cfg_file = root / "druid.yaml"`, add `base["runs_dir"] = "runs"`, `monkeypatch.setenv("DRUID_PROJECT", str(root))` (add `monkeypatch` to the fixture args), keep returning `core.load_config(cfg_file), root`. Add an autouse fixture that calls `paths.use(None)` before and after each test and deletes `DRUID_PROJECT`/`DRUID_CONFIG` before.

- [ ] **Step 4: Run** the full suite → PASS (count = Task 1 count + 4). `grep -rn "ROOT" druid/*.py` → only `cli.py`'s sys.path line.

- [ ] **Step 5: Commit** — `git commit -am "project-rooted config: --project, DRUID_PROJECT, druid.yaml"` (+ co-author; `git add druid/templates`).

---

### Task 4: Install-rooted stages and jobs; temp files inside the project

**Files:**
- Modify: `druid/runner.py` (`DRUID_HOME`, `stage_env`), `druid/model.py:389-411` (SBATCH), `druid/model.py:419-432` (`new_run_dir`), `druid/model.py:~580` (format args), `druid/history.py:118-131` (`_call_nextflow`)
- Test: `tests/test_runner.py`, `tests/test_cli.py`, `tests/test_history.py`

**Interfaces:**
- Consumes: `paths.DRUID_HOME`, `paths.project_root()`, `paths.tmp_dir()`, `paths.mkstemp()`, `paths.unlink()`.
- Produces: `runner.DRUID_HOME = paths.DRUID_HOME`; stage env `PROJECT_DIR=<project>`, `DRUID_HOME=<install>`, `PYTHONDONTWRITEBYTECODE=1`; SBATCH exports `DRUID_PROJECT` and `DRUID_CONFIG` and runs `{druid_home}/druid/cli.py _run`; dry runs under `<project>/.druid/tmp/dryrun/`.

- [ ] **Step 1: Failing tests**

`tests/test_runner.py` (replace the assertion at ~54):
```python
    assert env["PROJECT_DIR"] == str(paths.project_root())
    assert env["DRUID_HOME"] == str(runner.DRUID_HOME) == str(paths.DRUID_HOME)
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
```
`tests/test_cli.py` (replace the two `PHYLOCLI_CONFIG` sbatch assertions at ~443 and ~473):
```python
    text = (run / "array_0.sbatch").read_text()
    assert f'export DRUID_CONFIG="{run}/config.yaml"' in text
    assert f'export DRUID_PROJECT="{paths.project_root()}"' in text
    assert f'python3 "{paths.DRUID_HOME}/druid/cli.py" _run' in text
    assert "#SBATCH --job-name=phylo-" in text
```
plus a new test:
```python
def test_dry_run_scripts_go_under_the_project(results_tree):
    from druid import model, paths
    d = model.new_run_dir("align", dry_run=True)
    assert d.parent == paths.project_root() / ".druid" / "tmp" / "dryrun"
```
`tests/test_history.py`:
```python
def test_nextflow_log_temp_is_inside_the_project(results_tree, monkeypatch):
    from druid import history, paths
    seen = {}

    def fake_run(cmd, **kw):
        seen["log"] = cmd[cmd.index("-log") + 1]
        class R: returncode, stdout, stderr = 0, "", ""
        return R()
    monkeypatch.setattr(history.subprocess, "run", fake_run)
    history._call_nextflow(paths.project_root(), "run_x")
    assert Path(seen["log"]).parent == paths.project_root() / ".druid" / "tmp"
    assert not Path(seen["log"]).exists()                    # removed afterwards
```

- [ ] **Step 2: Run** those three files → the new assertions FAIL.

- [ ] **Step 3: Implement**

`druid/runner.py`:
```python
from druid import paths
from druid.core import Config, publish_dir, publish_patterns, stage_inputs

DRUID_HOME = paths.DRUID_HOME          # the install: stages, helpers, submodules/phylogeny
STAGES_DIR = DRUID_HOME / "druid/stages"
...
    env.update(ID=hg, CPUS=str(cpus), PROJECT_DIR=str(paths.project_root()),
               DRUID_HOME=str(DRUID_HOME), OUTDIR=str(cfg.outdir),
               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
```
`druid/model.py` SBATCH body lines (keep everything else):
```
export DRUID_PROJECT="{project}"
export DRUID_CONFIG="{run_dir}/config.yaml"
export PYTHONDONTWRITEBYTECODE=1
python3 "{druid_home}/druid/cli.py" _run {stage} "$HG" --run-dir "{run_dir}" &
```
and the `.format(...)` call passes `project=paths.project_root(), druid_home=paths.DRUID_HOME` instead of `root=ROOT`.
`new_run_dir`:
```python
    # A dry run writes its scripts under the project's .druid/tmp, so runs/ only holds real
    # submissions (queue and the already-queued check read runs/*/jobs.tsv).
    root = paths.tmp_dir() / "dryrun" if dry_run else runs_dir()
```
(remove `import tempfile`).
`druid/history.py` `_call_nextflow`:
```python
    tmp = paths.mkstemp(prefix="druid-nxflog-", suffix=".log")
    try:
        r = subprocess.run(["nextflow", "-log", str(tmp), "log", run, "-f", NF_FIELDS], ...)
    ...
    finally:
        try:
            paths.unlink(tmp)
        except OSError:
            pass
```
(remove `import tempfile`).

- [ ] **Step 4: Run** the full suite → PASS.
- [ ] **Step 5: Commit** — `"jobs and stages: DRUID_HOME + DRUID_PROJECT; temp files under .druid/tmp"`.

---

### Task 5: Route every write through the gate; config boundary checks; lint test

**Files:**
- Modify: `druid/runner.py` (`_copy_atomic`, `publish`, `run_one`), `druid/model.py` (`new_run_dir`, `write_run`), `druid/history.py` (`_write_cache`, the json cache writer at ~305-310), `druid/core.py` (`config_from_raw`)
- Test: `tests/test_write_boundary.py` (new), `tests/test_step1.py` (`_spy_replace`)

**Interfaces:**
- Consumes: all `paths` ops (Task 2).
- Produces: `core.config_from_raw` raises `ValueError("<key> must be inside the project <root>: <path>")` when `outdir`, the runs dir, `params.infasta` or `params.genefam_info` resolve outside the project (others — `REFNAMES`, `SPECIES_TREE`, `ORIGIN_TREE`, `pfam_db`, `hmm_dir`, `resources_tsv` — are read-only and may be anywhere).

- [ ] **Step 1: Failing tests** — `tests/test_write_boundary.py`:

```python
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
```

- [ ] **Step 2: Run** → `test_no_write_outside_paths_module` FAILS listing the current sites (runner ×11, model ×6, history ×6); the config tests FAIL.

- [ ] **Step 3: Implement**

`druid/runner.py`:
```python
def _copy_atomic(src: Path, dest: Path) -> Path:
    final = dest / src.name
    tmp = dest / (src.name + TMP_SUFFIX)
    if tmp.is_dir() and not tmp.is_symlink():
        paths.rmtree(tmp)
    elif tmp.exists() or tmp.is_symlink():
        paths.unlink(tmp)
    if src.is_dir():
        paths.copytree(src, tmp)  # symlinks=False: copies link targets
        if final.is_dir() and not final.is_symlink():
            paths.rmtree(final)
    else:
        paths.copy2(src, tmp)  # follows symlinks
    paths.replace(tmp, final)
    return final
```
`publish`: `paths.mkdir(dest, parents=True, exist_ok=True)`. `run_one`: `paths.rmtree(work)`, `paths.mkdir(work, parents=True)`, `paths.symlink(work / p.name, p)` for each input, and `paths.rmtree(work)` after publishing.
`druid/model.py`: `new_run_dir` → `paths.mkdir(d, parents=True)` (keep the `FileExistsError` loop) and `paths.mkdir(d / "logs")`; `write_run` → `paths.copy2(...)`, `paths.write_text(run_dir / "config.yaml", ...)`, `paths.write_text(ids_file, ...)`, `paths.write_text(script, ...)`.
`druid/history.py`: `_write_cache` → `paths.mkdir(path.parent, parents=True, exist_ok=True)`, `paths.write_text(tmp, ...)`, `paths.replace(tmp, path)`; same three for the json cache at ~305-310.
`druid/core.py` `config_from_raw`, after building the Config:
```python
    root = paths.project_root()
    runs = Path(_abs(raw.get("runs_dir") or "runs"))
    for key, p in (("outdir", cfg.outdir), ("runs_dir", runs),
                   ("infasta", params.get("infasta")), ("genefam_info", params.get("genefam_info"))):
        if p and not _inside(Path(p), root):
            raise ValueError(f"{key} must be inside the project {root}: {p}")
    return cfg
```
with
```python
def _inside(p: Path, root: Path) -> bool:
    r = p.resolve()
    return r == root or root in r.parents
```
`tests/test_step1.py` `_spy_replace`: patch `paths.os.replace` (from `druid import paths`) instead of `runner.os.replace`.

- [ ] **Step 4: Run** the full suite → PASS. The lint test passing is the proof every site moved.
- [ ] **Step 5: Commit** — `"write boundary: every write through druid.paths; config refuses write targets outside"`.

---

### Task 6: treeview `write_guard`, re-vendor, wire it in the TUI

**Files:**
- Modify (treeview repo, edits via the mount `~/ant/gzolotarov/projects/treeview`, git via `ssh -o BatchMode=yes login1.hpc.crg.es "git -C ~/projects/treeview ..."`): `treeview/widget.py` (`TreeScreen.__init__` ~355, `_write` ~480), `treeview/tests/test_app.py`, `README.md`
- Modify (druid): `druid/vendor/treeview/*` (only via `bash druid/vendor/update_treeview.sh`), `druid/tui.py:~1653`
- Test: treeview `test_app.py`; druid `tests/test_tui.py`

**Interfaces:**
- Produces: `TreeScreen(..., write_guard: Optional[Callable[[Path], Path]] = None)`; `w` calls `out = write_guard(out)` before writing; an exception → status `refused: <message>`, nothing written. druid passes `write_guard=paths.writable`.

- [ ] **Step 1: Failing treeview test** (append to `treeview/tests/test_app.py`, after `test_write_newick`; `App`, `asyncio`, `model`, `TreeScreen`, `_status` are already imported/defined there):

```python
def test_write_guard_refuses_and_writes_nothing(tmp_path):
    ok = tmp_path / "ok"
    ok.mkdir()
    src = ok / "in.nwk"
    src.write_text("((A_1:1,B_2:2)80:1,(C_3:1,D_4:1)Grp:2);\n")

    def guard(p):
        if ok.resolve() not in Path(p).resolve().parents:
            raise RuntimeError("outside the project")
        return p

    class Host(App):
        def on_mount(self):
            self.push_screen(TreeScreen(model.TreeModel(model.load(src)), view="outline",
                                        path=src, write_guard=guard))

    async def go():
        app = Host()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            prompt = app.screen.query_one("#prompt")
            await pilot.press("w")
            prompt.value = str(tmp_path / "bad.nwk")
            await pilot.press("enter")
            await pilot.pause()
            assert _status(app) == "refused: outside the project"
            assert not (tmp_path / "bad.nwk").exists()
            await pilot.press("w")                                     # default: ok/in.named.nwk
            await pilot.press("enter")
            await pilot.pause()
            assert (ok / "in.named.nwk").exists()
    asyncio.run(go())
```

- [ ] **Step 2: Run** — on the mount with `$PY -m pytest treeview/tests -q -p no:cacheprovider` from `~/ant/gzolotarov/projects/treeview` → new test FAILS (`unexpected keyword write_guard`).

- [ ] **Step 3: Implement** in `treeview/widget.py`:

`__init__` signature gains `write_guard=None,` (after `highlight=None,`) and body `self.write_guard = write_guard            # embedding caller's check on the output path (druid: inside the project)`.
`_write`, after the "will not overwrite the input" check:
```python
        if self.write_guard is not None:
            try:
                out = Path(self.write_guard(out))
            except Exception as e:
                self._status(f"refused: {e}")
                return
```
README (the `w` paragraph): add "An embedding caller can pass `write_guard` (a function that returns the path or raises); `w` then refuses a path it rejects (`refused: …`) — druid uses it to keep writes inside the project."

- [ ] **Step 4: Run** the treeview suite → all pass (87). Commit in treeview:
```bash
ssh -o BatchMode=yes login1.hpc.crg.es "cd ~/projects/treeview && git add -A treeview README.md && git commit -qm 'TreeScreen write_guard: an embedding caller can refuse output paths' && git rev-parse HEAD"
```

- [ ] **Step 5: Re-vendor and wire** — from the druid repo: `bash druid/vendor/update_treeview.sh` (it writes `druid/vendor/treeview/` next to itself). In `druid/tui.py` at the `TreeScreen(` call:
```python
        self.push_screen(TreeScreen(m, title=title, path=path, focus=focus, highlight=hl,
                                    write_guard=paths.writable))
```
(import `paths` from `druid`). Add to `tests/test_tui.py`, next to the existing tree-opening test (mirror how it opens the tree and grabs the screen):
```python
    assert app.screen.write_guard is paths.writable
```
- [ ] **Step 6: Run** the druid suite → PASS. Commit: `"treeview <short sha> (write_guard); the embedded tree refuses writes outside the project"`.

---

### Task 7: Shipped data, `druid init`, `druid adopt`

**Files:**
- Create: `druid/data/{species_tree.binary.newick,species_tree.newick,species_info.tsv,families_library.csv,Mmus_gene_names.csv,SOURCE}`, `druid/project.py`
- Modify: `druid/templates/druid.yaml`, `druid/cli.py` (commands `init`, `adopt`)
- Test: `tests/test_project.py`

**Interfaces:**
- Consumes: `paths.writable/write_text/copy2/mkdir` with explicit `root=` (no project exists yet).
- Produces: `project.init(dest: Path, today: str) -> list[Path]` (files written); `project.adopt(dest: Path, today: str) -> Path` (the `druid.yaml`); `project.ShippedData = ("species_tree.binary.newick", "species_tree.newick", "species_info.tsv", "Mmus_gene_names.csv")`; CLI `druid init DIR`, `druid adopt DIR`. Both raise `project.ProjectError(msg)`; the CLI prints `ERROR: msg`, exit 2.

- [ ] **Step 1: Copy the shipped data (read-only from v3, via the mount)**

```bash
V3=~/ant/gzolotarov/projects/2022_scRNAseq_Mlei/Phylogenies_v3/data
mkdir -p druid/data
for f in species_tree.binary.newick species_tree.newick species_info.tsv Mmus_gene_names.csv; do cp "$V3/$f" druid/data/$f; done
cp "$V3/gene_families_searchinfo.csv" druid/data/families_library.csv
md5sum druid/data/* ; ( cd "$V3" && md5sum species_tree.binary.newick species_tree.newick species_info.tsv Mmus_gene_names.csv gene_families_searchinfo.csv )
grep -c . druid/data/families_library.csv
```
Expected md5 prefixes (14/10/2026): binary 4ae36437, species_tree.newick 95521216, species_info 22b73c91, Mmus c3706f1a, families 004a9274 (356 non-empty rows). Stop if any differs from the v3 copy. Write `druid/data/SOURCE` with, per file: v3 path, md5, `14/10/2026`, and "families_library.csv = v3 data/gene_families_searchinfo.csv (356 rows; the spec's 304 was the older phylohpc copy)".

- [ ] **Step 2: Template** — Write `druid/templates/druid.yaml`: the current `params:` block of that file unchanged except the path keys below, with these top-level keys first:

```yaml
# druid project (druid init, {today}). Paths are relative to this directory.
# druid writes only inside this directory; proteomes_dir, pfam_db and hmm_dir are read-only.
outdir: results
runs_dir: runs
nextflow_dir: .
partition: genoa64
qos: normal
prepare: auto            # locked: druid never rebuilds data/input.fasta (druid adopt sets it)
proteomes_dir: /users/asebe/xgraubove/genomes/data   # read-only; files start with the species prefix
proteome_glob: "{sp}_long.pep.fasta"
species: []
params:
  ...                    # as in the file now, with:
  SPECIES_TREE: data/species_tree.binary.newick
  ORIGIN_TREE: data/species_tree.newick
  REFNAMES: data/Mmus_gene_names.csv
  resources_tsv: resources.tsv          # absent = stage defaults
  genefam_info: data/families.csv       # the project's families (library: druid/data/families_library.csv)
  infasta: data/input.fasta             # built by prepare (sub-project 2)
  pfam_db: /users/asebe/xgraubove/data/pfam/Pfam-A.hmm
```
(`{today}` is filled by `init`; no other `{}` in the file, `proteome_glob`'s braces are escaped as `{{sp}}` in the template text so `str.format` leaves `{sp}`.)

- [ ] **Step 3: Failing tests** — `tests/test_project.py`:

```python
"""druid init / druid adopt (spec 2026-10-14)."""
import hashlib
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from druid import cli, core, paths, project


def _md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def _tree_state(d: Path) -> dict:
    return {str(p.relative_to(d)): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in d.rglob("*")}


def test_init_makes_a_loadable_frozen_project(tmp_path, monkeypatch):
    dest = tmp_path / "proj"
    written = project.init(dest, today="14/10/2026")
    raw = yaml.safe_load((dest / "druid.yaml").read_text())
    assert raw["proteome_glob"] == "{sp}_long.pep.fasta" and raw["species"] == []
    assert raw["prepare"] == "auto" and raw["runs_dir"] == "runs"
    assert "14/10/2026" in (dest / "druid.yaml").read_text()
    for f in project.ShippedData:
        assert _md5(dest / "data" / f) == _md5(paths.DRUID_HOME / "druid/data" / f)
    assert (dest / "data/families.csv").read_text() == ""
    assert all(p.resolve().is_relative_to(dest.resolve()) for p in written)
    monkeypatch.setenv("DRUID_PROJECT", str(dest))
    cfg = core.load_config()
    assert cfg.outdir == dest.resolve() / "results"
    assert cfg.params["SPECIES_TREE"] == str(dest.resolve() / "data/species_tree.binary.newick")


def test_init_into_an_empty_existing_dir_is_fine(tmp_path):
    (tmp_path / "e").mkdir()
    project.init(tmp_path / "e", today="14/10/2026")
    assert (tmp_path / "e" / "druid.yaml").is_file()


def test_init_refuses_a_non_empty_dir_and_writes_nothing(tmp_path):
    d = tmp_path / "full"
    d.mkdir()
    (d / "x").write_text("x")
    before = _tree_state(d)
    with pytest.raises(project.ProjectError, match="not empty"):
        project.init(d, today="14/10/2026")
    assert _tree_state(d) == before


def _phylohpc(tmp_path) -> Path:
    v3 = tmp_path / "v3"
    (v3 / "phylocli" / "runs" / "20261001-000000_align").mkdir(parents=True)
    (v3 / "data").mkdir()
    (v3 / "data" / "input.fasta").write_text(">a\nM\n")
    (v3 / "phylocli" / "config.yaml").write_text(
        "outdir: results\npartition: genoa64\nqos: normal\nparams:\n"
        "  infasta: data/input.fasta\n  genefam_info: data/gene_families_searchinfo.csv\n"
        "  SPECIES_TREE: data/species_tree.binary.newick\n")
    return v3


def test_adopt_writes_only_druid_yaml_and_keeps_history(tmp_path, monkeypatch):
    v3 = _phylohpc(tmp_path)
    before = _tree_state(v3)
    out = project.adopt(v3, today="14/10/2026")
    after = _tree_state(v3)
    assert out == v3 / "druid.yaml"
    assert set(after) - set(before) == {"druid.yaml"}
    assert {k: v for k, v in after.items() if k != "druid.yaml"} == before
    raw = yaml.safe_load(out.read_text())
    assert raw["prepare"] == "locked" and raw["runs_dir"] == "phylocli/runs"
    assert raw["nextflow_dir"] == "."
    monkeypatch.setenv("DRUID_PROJECT", str(v3))
    assert paths.runs_dir() == v3.resolve() / "phylocli" / "runs"
    cfg = core.load_config()
    assert cfg.params["infasta"] == str(v3.resolve() / "data/input.fasta")


def test_adopt_refuses_existing_druid_yaml_or_missing_config(tmp_path):
    v3 = _phylohpc(tmp_path)
    (v3 / "druid.yaml").write_text("x: 1\n")
    with pytest.raises(project.ProjectError, match="already"):
        project.adopt(v3, today="14/10/2026")
    assert (v3 / "druid.yaml").read_text() == "x: 1\n"
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(project.ProjectError, match="phylocli/config.yaml"):
        project.adopt(bare, today="14/10/2026")
    assert list(bare.iterdir()) == []


def test_cli_init_and_adopt(tmp_path):
    r = CliRunner().invoke(cli.app, ["init", str(tmp_path / "p")])
    assert r.exit_code == 0, r.output
    assert "druid.yaml" in r.output
    r = CliRunner().invoke(cli.app, ["init", str(tmp_path / "p")])
    assert r.exit_code == 2 and "not empty" in r.output
```

- [ ] **Step 4: Run** → FAIL (`cannot import name 'project'`).

- [ ] **Step 5a: Ops with an explicit root** — no project exists while `init` runs, so add a `root` parameter to three ops in `druid/paths.py`, each passing it on to `writable`:

```python
def write_text(p: PathLike, text: str, root: Optional[Path] = None) -> Path:
    q = writable(p, root=root)
    q.write_text(text)
    return q


def mkdir(p: PathLike, parents: bool = True, exist_ok: bool = False,
          root: Optional[Path] = None) -> Path:
    q = writable(p, root=root)
    q.mkdir(parents=parents, exist_ok=exist_ok)
    return q


def copy2(src: PathLike, dst: PathLike, root: Optional[Path] = None) -> Path:
    q = writable(dst, root=root)
    shutil.copy2(src, q)                       # follows symlinks in src: copies the content
    return q
```

and add one test to `tests/test_paths.py`:

```python
def test_ops_with_explicit_root_need_no_project(tmp_path, monkeypatch):
    monkeypatch.delenv("DRUID_PROJECT", raising=False)
    paths.use(None)
    monkeypatch.chdir(tmp_path)
    new = tmp_path / "new"
    paths.mkdir(new / "data", parents=True, root=new)
    paths.write_text(new / "druid.yaml", "x", root=new)
    with pytest.raises(paths.OutsideProject):
        paths.write_text(tmp_path / "out.txt", "x", root=new)
```

- [ ] **Step 5b: Implement `druid/project.py`**

```python
"""druid init / druid adopt: make a project dir, or open a phylohpc project in place."""
from __future__ import annotations

from pathlib import Path

import yaml

from druid import paths

ShippedData = ("species_tree.binary.newick", "species_tree.newick", "species_info.tsv",
               "Mmus_gene_names.csv")
TEMPLATE = paths.DRUID_HOME / "druid" / "templates" / "druid.yaml"
DATA = paths.DRUID_HOME / "druid" / "data"


class ProjectError(RuntimeError):
    pass


def init(dest: Path, today: str) -> list:
    dest = Path(dest).expanduser().resolve()
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ProjectError(f"{dest} is not empty; druid init needs a new or empty directory")
    paths.mkdir(dest / "data", parents=True, exist_ok=True, root=dest)
    out = [paths.write_text(dest / "druid.yaml", TEMPLATE.read_text().format(today=today), root=dest)]
    out += [paths.copy2(DATA / f, dest / "data" / f, root=dest) for f in ShippedData]
    out.append(paths.write_text(dest / "data" / "families.csv", "", root=dest))
    return out


def adopt(dest: Path, today: str) -> Path:
    dest = Path(dest).expanduser().resolve()
    old = dest / "phylocli" / "config.yaml"
    if (dest / paths.CONFIG_NAME).exists():
        raise ProjectError(f"{dest / paths.CONFIG_NAME} already exists; nothing written")
    if not old.is_file():
        raise ProjectError(f"{old} not found: not a phylohpc project with phylocli/config.yaml")
    raw = yaml.safe_load(old.read_text()) or {}
    raw.setdefault("runs_dir", "phylocli/runs")
    raw.setdefault("nextflow_dir", ".")
    raw["prepare"] = "locked"
    head = (f"# druid project adopted from phylocli/config.yaml on {today} (druid adopt).\n"
            "# prepare: locked -- data/input.fasta is curated; druid never rebuilds it\n"
            "# (Phylogenies_v3/PROVENANCE.md: rebuilding from xgraubove breaks 11 species' ids).\n")
    return paths.write_text(dest / paths.CONFIG_NAME, head + yaml.safe_dump(raw, sort_keys=False),
                            root=dest)
```
`druid/cli.py`:
```python
@app.command()
def init(dest: Path = typer.Argument(..., help="new or empty directory")):
    """Make a druid project directory."""
    from datetime import date
    from druid import project
    try:
        written = project.init(dest, today=date.today().strftime("%d/%m/%Y"))
    except project.ProjectError as e:
        _fail(f"ERROR: {e}", 2)
    typer.echo(f"druid project at {Path(dest).resolve()}: {written[0].name}, "
               f"data/ ({len(written) - 1} files)")


@app.command()
def adopt(dest: Path = typer.Argument(..., help="an existing phylohpc project (has phylocli/config.yaml)")):
    """Open an existing phylohpc project in place (writes only DEST/druid.yaml)."""
    from datetime import date
    from druid import project
    try:
        out = project.adopt(dest, today=date.today().strftime("%d/%m/%Y"))
    except project.ProjectError as e:
        _fail(f"ERROR: {e}", 2)
    typer.echo(f"wrote {out} (prepare: locked)")
```

- [ ] **Step 6: Run** full suite → PASS (lint included). **Step 7: Commit** — `"druid init / adopt; shipped data from Phylogenies_v3 data/ (14/10/2026)"`.

---

### Task 8: `druid doctor`, `environment.yml`, README

**Files:**
- Create: `druid/doctor.py`, `environment.yml`
- Modify: `druid/cli.py` (command `doctor`), `README.md`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Produces: `doctor.TOOLS: tuple[str, ...]`; `doctor.checks() -> list[Check]` with `Check(ok: bool, name: str, detail: str)`; CLI `druid doctor` prints `OK   name  detail` / `FAIL name  detail`, exit 1 on any FAIL. Project checks run only when a project is found; otherwise one line `SKIP project  <NoProject message>`.

- [ ] **Step 1: Failing tests** — `tests/test_doctor.py`:

```python
"""druid doctor (spec 2026-10-14)."""
from pathlib import Path

from typer.testing import CliRunner

from druid import cli, doctor


def _names(cs):
    return {c.name: c for c in cs}


def test_missing_tool_fails(results_tree, monkeypatch):
    real = doctor.shutil.which
    monkeypatch.setattr(doctor.shutil, "which", lambda t: None if t == "mafft" else real(t))
    c = _names(doctor.checks())["mafft"]
    assert not c.ok and "not on PATH" in c.detail


def test_pfam_without_index_fails_and_never_hmmpresses(results_tree, monkeypatch):
    calls = []
    real_run = doctor.subprocess.run
    monkeypatch.setattr(doctor.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or real_run(cmd, **kw))
    c = _names(doctor.checks())["pfam_db"]
    assert not c.ok and "hmmpress" in c.detail          # tells the user; does not run it
    assert not any("hmmpress" in str(x) for cmd in calls for x in cmd)


def test_pfam_with_index_ok(results_tree):
    cfg, root = results_tree
    for ext in (".h3m", ".h3i", ".h3f", ".h3p"):
        Path(cfg.params["pfam_db"] + ext).write_text("")
    assert _names(doctor.checks())["pfam_db"].ok


def test_proteomes_dir_and_species_count(results_tree, tmp_path):
    import yaml
    cfg, root = results_tree
    prot = tmp_path / "prot"
    prot.mkdir()
    (prot / "Mlei_long.pep.fasta").write_text(">Mlei_1\nM\n")
    raw = yaml.safe_load((root / "druid.yaml").read_text())
    raw.update(proteomes_dir=str(prot), proteome_glob="{sp}_long.pep.fasta", species=["Mlei", "Hsap"])
    (root / "druid.yaml").write_text(yaml.safe_dump(raw))
    c = _names(doctor.checks())["proteomes"]
    assert not c.ok and "Hsap" in c.detail and "1/2" in c.detail


def test_no_project_is_skipped_not_failed(tmp_path, monkeypatch):
    from druid import paths
    monkeypatch.delenv("DRUID_PROJECT", raising=False)
    paths.use(None)
    monkeypatch.chdir(tmp_path)
    c = _names(doctor.checks())["project"]
    assert c.ok and c.detail.startswith("SKIP")


def test_cli_exit_code(results_tree, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda t: None)
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert r.exit_code == 1 and "FAIL" in r.output
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** `druid/doctor.py`:

```python
"""druid doctor: is everything druid needs here? Reads only; never fixes anything."""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from druid import paths

# Tools the stage scripts and submodules/phylogeny call (grep of druid/stages/*.sh and
# submodules/phylogeny/{main.py,helper/*.py}, 14/10/2026), plus SLURM.
TOOLS = ("hmmsearch", "hmmfetch", "mafft", "iqtree2", "generax", "mpirun", "clipkit", "mcl",
         "diamond", "samtools", "sbatch", "squeue", "sacct")
PACKAGES = (("textual", "8.2", "9"), ("ete3", "3.1.3", None), ("rich", "14", "16"),
            ("typer", None, None), ("yaml", None, None))
PFAM_INDEX = (".h3m", ".h3i", ".h3f", ".h3p")


@dataclass(frozen=True)
class Check:
    ok: bool
    name: str
    detail: str


def _version(tool: str) -> str:
    for flag in ("--version", "-version", "-h"):
        try:
            r = subprocess.run([tool, flag], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            continue
        line = next((l for l in (r.stdout + r.stderr).splitlines() if l.strip()), "")
        if line:
            return line.strip()[:70]
    return "version unknown"


def _vtuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split(".")[:3] if x.isdigit())


def _tools() -> list:
    out = []
    for t in TOOLS:
        p = shutil.which(t)
        out.append(Check(bool(p), t, _version(t) if p else "not on PATH"))
    return out


def _packages() -> list:
    from importlib import metadata
    out = []
    for mod, lo, hi in PACKAGES:
        try:
            importlib.import_module(mod)
        except ImportError:
            out.append(Check(False, f"python:{mod}", "not importable"))
            continue
        dist = {"yaml": "PyYAML"}.get(mod, mod)
        try:
            v = metadata.version(dist)
        except metadata.PackageNotFoundError:
            v = "?"
        ok = v == "?" or ((lo is None or _vtuple(v) >= _vtuple(lo))
                          and (hi is None or _vtuple(v) < _vtuple(hi)))
        rng = f" (needs >= {lo}{', < ' + hi if hi else ''})" if lo else ""
        out.append(Check(ok, f"python:{mod}", f"{v}{rng}"))
    return out


def _install() -> list:
    main = paths.DRUID_HOME / "submodules" / "phylogeny" / "main.py"
    possvm = paths.DRUID_HOME / "submodules" / "phylogeny" / "submodules" / "possvm-orthology"
    ok = main.is_file() and possvm.is_dir() and any(possvm.iterdir())
    return [Check(ok, "submodules", str(main) if ok else
                  "missing: run git submodule update --init --recursive in " + str(paths.DRUID_HOME))]


def _project() -> list:
    import yaml
    from druid import core
    try:
        root = paths.project_root()
    except paths.NoProject as e:
        return [Check(True, "project", f"SKIP {e}")]
    out = [Check(True, "project", str(root))]
    raw = yaml.safe_load(paths.config_file().read_text()) or {}
    cfg = core.config_from_raw(raw)
    pf = Path(cfg.params.get("pfam_db") or "")
    missing = [e for e in PFAM_INDEX if not Path(str(pf) + e).is_file()]
    if not pf.is_file() or not os.access(pf, os.R_OK):
        out.append(Check(False, "pfam_db", f"not readable: {pf}"))
    elif missing:
        out.append(Check(False, "pfam_db", f"{pf}: no {' '.join(missing)}; its owner must run "
                                           f"hmmpress (druid never writes there)"))
    else:
        out.append(Check(True, "pfam_db", str(pf)))
    prot = Path(raw.get("proteomes_dir") or "")
    sps = list(raw.get("species") or [])
    if not (prot.is_dir() and os.access(prot, os.R_OK | os.X_OK)):
        out.append(Check(False, "proteomes", f"not readable: {prot}"))
    else:
        glob = raw.get("proteome_glob") or "{sp}_long.pep.fasta"
        lost = [s for s in sps if not list(prot.glob(glob.format(sp=s)))]
        out.append(Check(not lost, "proteomes",
                         f"{len(sps) - len(lost)}/{len(sps)} species have a file in {prot}"
                         + (f"; missing: {', '.join(lost)}" if lost else "")))
    tree = Path(cfg.params.get("SPECIES_TREE") or "")
    try:
        from ete3 import Tree
        n = len(Tree(tree.read_text(), format=1))
        out.append(Check(True, "species_tree", f"{tree} ({n} tips)"))
    except Exception as e:
        out.append(Check(False, "species_tree", f"{tree}: {e}"))
    return out


def checks() -> list:
    return _tools() + _packages() + _install() + _project()
```
CLI:
```python
@app.command()
def doctor():
    """Check tools, python packages, the submodule and the project's inputs (reads only)."""
    from druid import doctor as d
    cs = d.checks()
    for c in cs:
        typer.echo(f"{'OK  ' if c.ok else 'FAIL'} {c.name:<16} {c.detail}")
    raise typer.Exit(0 if all(c.ok for c in cs) else 1)
```
(`results_tree`'s `Pfam-A.hmm` stub has no index files, which `test_pfam_without_index_fails...` relies on; the fixture's species tree `(a,b);` parses.)

- [ ] **Step 4: Run** full suite → PASS.

- [ ] **Step 5: environment.yml (read-only export)**

```bash
ssh -o BatchMode=yes login1.hpc.crg.es "conda env export -n phylo --no-builds" > /tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-2022-Mlei/0a22b1f8-b83b-4910-996d-6e5ecad4a2e0/scratchpad/phylo.env.yml
```
Write `environment.yml` from it: `name: druid`, drop the `prefix:` line, keep channels and every dependency pinned as exported. Add a top comment: `# exported read-only from the CRG phylo env on 14/10/2026 (conda env export --no-builds)`.

- [ ] **Step 6: README.md** — rewrite the top-level README: what druid is (one paragraph), Contents (modules, `stages/`, `helpers/`, `vendor/`, `data/`, `templates/`, `submodules/phylogeny`, docs), Install (`git clone --recurse-submodules`, `conda env create -f environment.yml` or the CRG `phylo` env, `bin/druid doctor`), Projects (`druid init DIR`, `druid adopt DIR`, project discovery order), **Write boundary** (the rule, read-only list, never hmmpress), Tests (the pytest command). Keep the existing phylocli command/TUI documentation below as the "Commands" section with `phylo` → `druid`.

- [ ] **Step 7: Commit** — `"druid doctor; environment.yml from the phylo env; README"`.

---

### Task 9: Cluster clone and the read-only sandbox run

**Files:**
- Create: `tests/test_sandbox.py`
- Cluster: `~/projects/druid` (new)

**Interfaces:**
- Consumes: `project.init`, `runner.run_one`, `paths`.

- [ ] **Step 1: Write the test** — `tests/test_sandbox.py`:

```python
"""One HG through align in a fresh project with a read-only proteome dir: nothing outside the
project changes (spec 2026-10-14, Write boundary). Needs mafft + clipkit (cluster phylo env)."""
import hashlib
import os
import shutil
import stat
from pathlib import Path

import pytest

from druid import core, paths, project, runner

pytestmark = pytest.mark.skipif(not (shutil.which("mafft") and shutil.which("clipkit")),
                                reason="needs mafft and clipkit (cluster phylo env)")


def _snapshot(d: Path) -> dict:
    out = {}
    for p in sorted(d.rglob("*")):
        if "__pycache__" in p.parts or ".pytest_cache" in p.parts or ".git" in p.parts:
            continue
        if p.is_file() and not p.is_symlink():
            out[str(p)] = (p.stat().st_mtime_ns, hashlib.md5(p.read_bytes()).hexdigest())
    return out


def test_align_writes_only_inside_the_project(tmp_path, monkeypatch):
    prot = tmp_path / "xgraubove"
    prot.mkdir()
    (prot / "Aaa_long.pep.fasta").write_text(">Aaa_1\nMKVLAAGIVG\n>Aaa_2\nMKVLSAGIVG\n")
    for p in (prot / "Aaa_long.pep.fasta", prot):
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    dest = tmp_path / "proj"
    project.init(dest, today="14/10/2026")
    monkeypatch.setenv("DRUID_PROJECT", str(dest))
    paths.use(None)
    hg = "tst.Fam.HG1"
    clusters = dest / "results" / "clusters"
    clusters.mkdir(parents=True)
    (clusters / f"{hg}.fasta").write_text(
        ">Aaa_1\nMKVLAAGIVGLLA\n>Bbb_1\nMKVLSAGIVGLLA\n>Ccc_1\nMKILAAGIVGLMA\n")
    home_before, prot_before = _snapshot(paths.DRUID_HOME), _snapshot(prot)
    outside_before = {p.name for p in tmp_path.iterdir()}
    cfg = core.load_config()
    rc = runner.run_one(cfg, "align", hg, dest / "runs" / "work")
    assert rc == 0
    assert (dest / "results" / "align" / f"{hg}.aln.fasta").is_file()
    assert _snapshot(paths.DRUID_HOME) == home_before
    assert _snapshot(prot) == prot_before
    assert {p.name for p in tmp_path.iterdir()} == outside_before
    assert not list((paths.DRUID_HOME / "druid" / "helpers").glob("__pycache__/*.cpython-*.pyc.*"))
```

(If `stage_inputs(cfg, "align", hg)` needs a different cluster path or file name, read `core.stage_inputs` and use the path it returns for `align`; the assertions stay.)

- [ ] **Step 2: Local run** — `$PY -m pytest tests/test_sandbox.py -q -p no:cacheprovider` → SKIPPED (no mafft locally) is expected; the rest of the suite PASS. Commit: `"sandbox test: align in a fresh project writes nothing outside it"`.

- [ ] **Step 3: Cluster clone** (a new dir in Grygoriy's home on the cluster; touches nothing else):

```bash
ssh -o BatchMode=yes login1.hpc.crg.es "test ! -e ~/projects/druid && git init -q ~/projects/druid && git -C ~/projects/druid config receive.denyCurrentBranch updateInstead"
cd /home/grygoriyzolotarov/Documents/projects/phylogenies/druid
git push login1.hpc.crg.es:projects/druid main
ssh -o BatchMode=yes login1.hpc.crg.es "cd ~/projects/druid && git checkout -q main && git submodule update --init --recursive && git log --oneline -1"
```

- [ ] **Step 4: Cluster run** — check CPU first (`ssh login1 "uptime; top -bn1 | head -12"`), then:
```bash
ssh -o BatchMode=yes login1.hpc.crg.es "source ~/miniconda3/etc/profile.d/conda.sh && conda activate phylo && cd ~/projects/druid && PYTHONDONTWRITEBYTECODE=1 python -m pytest tests -q -p no:cacheprovider"
```
Expected: all pass, `test_sandbox.py` **passed** (not skipped). Then `ssh login1 "cd ~/projects/druid && bin/druid doctor"` outside a project: tools/packages/submodules OK, `project SKIP`. Report both outputs.

---

### Task 10 (controller, not dispatched): v3 acceptance

Runs on the cluster in the `phylo` env. **No Nextflow preview in v3. The only write to v3 is `druid.yaml`, by the deploy procedure.**

- [ ] **Step 1: Make `druid.yaml` in staging, never in v3 directly**
```bash
ssh -o BatchMode=yes login1.hpc.crg.es 'set -e; V3=/users/asebe/gzolotarov/projects/2022_scRNAseq_Mlei/Phylogenies_v3
test ! -e $V3/druid.yaml
S=$(mktemp -d /no_backup/asebe/gzolotarov/deploy.XXXXXX); mkdir -p $S/v3/phylocli
cp -p $V3/phylocli/config.yaml $S/v3/phylocli/
source ~/miniconda3/etc/profile.d/conda.sh && conda activate phylo
~/projects/druid/bin/druid adopt $S/v3 && cat $S/v3/druid.yaml && echo $S'
```
Review the printed `druid.yaml` (params identical to v3 `phylocli/config.yaml`; `runs_dir: phylocli/runs`, `nextflow_dir: .`, `prepare: locked`).

- [ ] **Step 2: Deploy the one file** — `cp -p $S/v3/druid.yaml $V3/druid.yaml.new-tmp && mv $V3/druid.yaml.new-tmp $V3/druid.yaml && cmp $S/v3/druid.yaml $V3/druid.yaml && md5sum $V3/druid.yaml`. (New file: no backup needed; `test ! -e` above proved none existed.)

- [ ] **Step 3: Compare with phylocli** — for `CMD` in: `status`; `status tfs.T-box.HG1`; 4 more HGs and 5 families chosen with `ls $V3/results/clusters | shuf -n 4 --random-source=<(yes)` and `cut -f1 $V3/data/gene_families_searchinfo.csv | head -5`; `missing`:
```bash
cd $V3 && phylocli/phylo $CMD > $S/a.txt 2>&1; ~/projects/druid/bin/druid --project $V3 $CMD > $S/b.txt 2>&1; diff $S/a.txt $S/b.txt && echo SAME
```
Expected: `SAME` for all 12. Any diff: stop and report it.

- [ ] **Step 4:** `~/projects/druid/bin/druid --project $V3 doctor` → all OK (pfam_db index present, proteomes `0/0` since `species` is empty for an adopted project). Open `druid --project $V3 tui` headless (Textual pilot script in the scratchpad) and compare the overview counts with phylocli's TUI; report the numbers.

- [ ] **Step 5:** `ssh login1 "cd $V3 && git status --porcelain | grep -v '^??' | head"` unchanged vs before; `find $V3 -newer $S/v3/druid.yaml -not -path '*/results/*' | head` lists only `druid.yaml` and the `phylocli/history` cache (that cache is phylocli's own and is rewritten by both tools).

### Task 11 (controller): GitHub remote — ask first

Ask Grygoriy: "Create the private GitHub repo `zolotarovgl/druid` and push `main`? y/n". Only on yes: `gh repo create zolotarovgl/druid --private --source /home/grygoriyzolotarov/Documents/projects/phylogenies/druid --push`, and add it as `origin` in the cluster clone.
