"""`druid run` (sub-project 3): plan, write and queue step 1 in one go -- search arrays, each with
a cluster array over the same ids file whose task i waits on search task i (aftercorr), plus
cluster-only arrays for families already searched. Done, no-hits and queued families are skipped
(counted); a family that fails any check other than the linked cluster's "input missing" is
dropped from both arrays with a note. The CLI and the TUI only call these functions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from druid import core, model, paths, setup_state

ADOPTED = ("ERROR: druid run is not available on an adopted project (prepare: locked); "
           "use druid submit")


@dataclass
class RunPlan:
    search: "model.Plan | None"
    linked: "model.Plan | None"       # cluster pieces mirroring search's: same ids lists, same order
    only: "model.Plan | None"
    notes: list
    counts: dict                       # search, cluster_only, no_hits, done, queued, dropped


@dataclass
class RunWritten:
    search: "model.Written | None"
    linked: "model.Written | None"
    only: "model.Written | None"


def refusal(raw: dict, cfg: core.Config) -> str:
    """"" when `druid run` may go ahead, else its one ERROR: line (exit 2)."""
    try:
        model.require_prefix(raw, cfg)
    except model.ModelError as e:
        return str(e)
    if raw.get("prepare") == "locked":
        return ADOPTED
    infasta = cfg.params.get("infasta")
    if not infasta or not Path(infasta).is_file():
        return f"ERROR: run prepare first (no {infasta or 'params.infasta'})"
    # once the species are locked (a run exists) the stages read input.fasta, not the proteomes
    if not setup_state.species_locked(raw, cfg):
        b = setup_state.blockers(raw, cfg, paths.project_root())
        if b:
            return f"ERROR: Setup has blockers: {'; '.join(b)}"
    return ""


def counts_line(counts: dict) -> str:
    s = (f"search+cluster {counts['search']} · cluster only {counts['cluster_only']} · "
         f"no hits {counts['no_hits']} · done {counts['done']} · queued {counts['queued']}")
    return s + (f" · dropped {counts['dropped']}" if counts.get("dropped") else "")


def _queued(fams: set, dry_run: bool) -> "tuple[set, set]":
    """(queued for search, queued for cluster) among `fams`; one squeue call."""
    lv = model.live(fams)
    if lv is None:
        if not dry_run:
            model.live_hgs("search")               # raises the "squeue not on PATH" error
        lv = {}
    return lv.get("search", set()) & fams, lv.get("cluster", set()) & fams


def plan_run(cfg: core.Config, raw: dict, fam: "str | None" = None, dry_run: bool = False,
             override: "dict | None" = None) -> RunPlan:
    """The run's three plans (None when empty), its notes and its counts. `raw` is the config the
    plan is for (write() snapshots it); `fam` narrows the families like --fam."""
    try:
        fams = core.filter_fam(core.family_ids(cfg), fam)
    except core.FamilyError as e:
        raise model.ModelError(str(e), 1) from None
    st = core.family_done(cfg, fams)
    qs, qc = _queued(fams, dry_run)
    need = fams - st["search"] - qs - qc
    only = st["hits"] - st["cluster"] - qc
    queued = ((fams - st["search"]) & (qs | qc)) | ((st["hits"] - st["cluster"]) & qc)
    try:
        e_s = core.validate(cfg, "search", sorted(need), qs)
        e_c = core.validate(cfg, "cluster", sorted(need), qc)
        e_o = core.validate(cfg, "cluster", sorted(only), qc)
    except core.FamilyError as e:
        raise model.ModelError(str(e), 1) from None
    bad = ({f for v in e_s.values() for f in v}
           | {f for k, v in e_c.items() if k != "input_missing" for f in v})
    bad_only = {f for v in e_o.values() for f in v}
    dropped = sorted(bad | bad_only)
    notes = [f"dropped ({len(dropped)}): {model.show(dropped)}"] if dropped else []
    need, only = sorted(need - bad), sorted(only - bad_only)

    flags = [f"{k}={v}" for k, v in (override or {}).items() if v is not None]

    def plan(stage, ids):                  # as `druid submit <stage>` plans them; None when empty
        if not ids:
            return None
        p = model.plan(cfg, stage, model.select(cfg, stage, ids, dry_run=dry_run), override,
                       over_flags=flags)
        return p if p.groups or p.errors else None

    search, only_p, linked = plan("search", need), plan("cluster", only), None
    if search is not None and not search.errors:
        pieces = []
        for _res, ids in search.groups:
            g = core.group(cfg, "cluster", ids, override)
            if len(g) != 1:
                raise model.ModelError(f"linked cluster array over {len(ids)} families needs "
                                       f"{len(g)} resource groups; it must be one", 1)
            pieces.append((next(iter(g)), ids))
        over = f"; overridden by {' '.join(flags)}" if flags else ""
        linked = model.Plan("cluster", pieces, [
            f"resources: step1 defaults for {sum(len(i) for _r, i in pieces)} families{over}",
            "each cluster array waits on its search array task by task "
            "(--dependency=aftercorr, --kill-on-invalid-dep=yes)"], {})
    counts = {"search": sum(len(i) for _r, i in search.groups) if search else 0,
              "cluster_only": sum(len(i) for _r, i in only_p.groups) if only_p else 0,
              "no_hits": len(st["no_hits"]), "done": len(st["cluster"] & st["hits"]),
              "queued": len(queued), "dropped": len(dropped)}
    return RunPlan(search, linked, only_p, notes, counts)


def write(cfg: core.Config, raw: dict, rp: RunPlan, dry_run: bool, max_running: int = 50,
          partition: "str | None" = None, qos: "str | None" = None) -> RunWritten:
    """One run dir per non-empty plan (search snapshots genefam.csv); the linked cluster run dir's
    ids files are the search run dir's, byte for byte."""
    def one(p):
        return (model.write_run(cfg, raw, p, dry_run, max_running, partition, qos)
                if p is not None and p.groups else None)
    return RunWritten(one(rp.search), one(rp.linked), one(rp.only))


def submit(rw: RunWritten) -> "tuple[list[tuple[str, str, int, str | None, core.Res]], str | None]":
    """Queue search array k, then its cluster array k (after search k), ..., then the cluster-only
    arrays; stop at the first failure. ([(stage, job id, n tasks, search job id it waits on or
    None, the array's core.Res)], error or None)."""
    order = []                                   # (stage, one-array Written, linked pair index)
    s_arr = rw.search.arrays if rw.search else []
    l_arr = rw.linked.arrays if rw.linked else []
    if len(s_arr) != len(l_arr):
        raise model.ModelError(f"{len(s_arr)} search arrays but {len(l_arr)} linked cluster "
                               "arrays: nothing submitted", 1)
    for k in range(len(s_arr)):
        order.append(("search", model.Written(rw.search.run_dir, [s_arr[k]]), None))
        order.append(("cluster", model.Written(rw.linked.run_dir, [l_arr[k]]), k))
    for a in (rw.only.arrays if rw.only else []):
        order.append(("cluster", model.Written(rw.only.run_dir, [a]), None))
    done: list = []
    jids: list = []                              # shared: errors list every id, one lock attempt
    search_of: dict = {}                         # linked pair k -> its search job id
    for j, (stage, w, pair) in enumerate(order):
        after = search_of.get(pair) if pair is not None else None
        n0 = len(jids)
        _ids, err = model.sbatch_all(w, jids, [after] if after else None)
        if err:
            rest = [str(a[3]) for _st, w2, _p in order[j + 1:] for a in w2.arrays]
            msg = err + ("" if not rest else " " + " ".join(rest))
            if after:
                msg += (f"\nsearch array {after} is queued without its cluster array: "
                        "the next druid run clusters them")
            return done, msg
        jid = jids[n0]
        if stage == "search":
            search_of[len(search_of)] = jid
        done.append((stage, jid, len(w.arrays[0][1]), after, w.arrays[0][0]))
    return done, None
