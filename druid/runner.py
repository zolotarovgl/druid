"""Run one stage for one HG in a scratch work dir and publish outputs on success."""
from __future__ import annotations

import glob
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from druid import paths
from druid.core import (Config, publish_dir, publish_patterns,
                           stage_inputs)

DRUID_HOME = paths.DRUID_HOME                      # the install: stages, helpers, submodules/phylogeny
STAGES_DIR = DRUID_HOME / "druid/stages"
TMP_SUFFIX = ".tmp-phylo"
NO_OUTPUT_RC = 65


def stage_env(cfg: Config, stage: str, hg: str, cpus: int) -> dict[str, str]:
    env = dict(os.environ)
    env.update(ID=hg, CPUS=str(cpus), PROJECT_DIR=str(paths.project_root()),
               DRUID_HOME=str(DRUID_HOME), OUTDIR=str(cfg.outdir),
               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    for k, v in cfg.params.items():
        if isinstance(v, bool):
            env[str(k)] = "true" if v else "false"
        else:
            env[str(k)] = "" if v is None else str(v)       # hmm_dir: null -> "" (not "None")
    return env


def _expand(work: Path, patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for pat in patterns:
        # glob(root_dir=) needs Python >= 3.10; the cluster phylo env is older.
        for m in sorted(glob.glob(os.path.join(glob.escape(str(work)), pat))):
            p = work / os.path.basename(m)
            if p not in out:
                out.append(p)
    return out


def _copy_atomic(src: Path, dest: Path) -> Path:
    final = dest / src.name
    tmp = dest / (src.name + TMP_SUFFIX)
    if tmp.is_dir() and not tmp.is_symlink():
        shutil.rmtree(tmp)
    elif tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    if src.is_dir():
        shutil.copytree(src, tmp)  # symlinks=False: copies link targets
        if final.is_dir() and not final.is_symlink():
            shutil.rmtree(final)
    else:
        shutil.copy2(src, tmp)  # follows symlinks
    os.replace(tmp, final)
    return final


def publish(work: Path, dest: Path, first: list[str], marker: str) -> list[Path]:
    work, dest = Path(work), Path(dest)
    markers = _expand(work, [marker])
    if not markers:
        raise FileNotFoundError(f"marker {marker!r} not produced in {work}")
    dest.mkdir(parents=True, exist_ok=True)
    firsts = [p for p in _expand(work, first) if p not in markers]
    return [_copy_atomic(p, dest) for p in firsts + markers]


def run_one(cfg: Config, stage: str, hg: str, work_root: Path) -> int:
    from druid import core
    work = Path(work_root) / hg
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    inputs = stage_inputs(cfg, stage, hg)
    for p in inputs:
        (work / p.name).symlink_to(p)
    table = core.load_resources_tsv(Path(cfg.params.get("resources_tsv", "")))
    cpus = core.resources(cfg, stage, hg, table).cpus
    state = {"proc": None, "pending": []}

    def forward(signum, _frame):
        proc = state["proc"]
        if proc is None:  # signal arrived before Popen returned: deliver it afterwards
            state["pending"].append(signum)
            return
        try:
            proc.send_signal(signum)
        except ProcessLookupError:
            pass

    old = {s: signal.signal(s, forward) for s in (signal.SIGUSR2, signal.SIGTERM)}
    try:
        proc = subprocess.Popen(["bash", str(STAGES_DIR / f"{stage}.sh"), *[p.name for p in inputs]],
                                cwd=work, env=stage_env(cfg, stage, hg, cpus))
        state["proc"] = proc
        for s in state["pending"]:
            forward(s, None)
        rc = proc.wait()
    finally:
        for s, h in old.items():
            signal.signal(s, h)
    if rc == 0:
        tree = inputs[0].name if stage in ("possvm", "possvm_prev") else None
        first, marker = publish_patterns(stage, hg, tree)
        try:
            publish(work, publish_dir(cfg, stage), first, marker)
        except FileNotFoundError:
            print(f"phylocli: {stage} for {hg} exited 0 but produced no output matching "
                  f"{marker!r}; nothing published, work dir kept: {work}", file=sys.stderr)
            return NO_OUTPUT_RC
        shutil.rmtree(work)
    return rc