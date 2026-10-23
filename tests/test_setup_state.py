"""setup_state: sources, candidates, selection, species lock, blockers; the sbatch_all lock hook."""
from __future__ import annotations

import pytest
import yaml

from druid import core, model, paths, project, setup_state as ss
from druid import yamledit
from tests.conftest import GENEFAM
from tests.test_cli import cli  # noqa: F401  (fixture)

TAX = "".join(f"{p}\t{p} sp\t1\t1\t1\tMetazoa, X\tsrc\t1\tMT\tNA\n" for p in ("Aaa", "Bbb", "Ccc"))


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "p"
    project.init(root, "23/10/2026")
    paths.use(root)
    prot = tmp_path / "prot"
    prot.mkdir()
    for sp in ("Aaa", "Bbb", "Zzz"):                   # Zzz has no taxonomy row
        (prot / f"{sp}_long.pep.fasta").write_text(">x\nM\n")
    (root / "data" / "tax.tsv").write_text(TAX + "short\trow\n")
    (root / "data" / "families.csv").write_text(GENEFAM)
    for f in ("base_tree.binary.newick", "base_tree.newick"):   # species tree for the tree blockers
        (root / "data" / f).write_text("((Aaa:1,Bbb:1):1,Nope:1)R;")
    yamledit.update_config({("proteomes_dir",): str(prot), ("taxonomy",): "data/tax.tsv",
                            ("species",): ["Aaa"]})
    return root, prot


def _raw():
    raw = paths.read_raw()
    return raw, core.config_from_raw(raw)


def _custom(tmp_path, files=("Ccc_long.pep.fasta", "Qqq_long.pep.fasta")):
    d = tmp_path / "mine"
    d.mkdir()
    for f in files:
        (d / f).write_text(">x\nM\n")
    return d


def test_sources_default_and_custom(proj, tmp_path):
    root, prot = proj
    d = _custom(tmp_path)
    yamledit.update_config({("sources",): [{"name": "mine", "proteomes_dir": str(d),
                                            "proteome_glob": "{sp}.faa", "taxonomy": "data/t2.tsv"}]})
    raw, _ = _raw()
    a, b = ss.sources(raw, root)
    assert (a.name, a.proteomes_dir, a.glob, a.taxonomy) == ("default", prot, "{sp}_long.pep.fasta",
                                                             root / "data" / "tax.tsv")
    assert (b.name, b.proteomes_dir, b.glob, b.taxonomy) == ("mine", d, "{sp}.faa", root / "data" / "t2.tsv")
    raw.pop("taxonomy")
    assert ss.sources(raw, root)[0].taxonomy == ss.SHIPPED_TAXONOMY
    assert ss.SHIPPED_TAXONOMY.is_file()


def test_candidates_hide_rowless_default_list_rowless_custom(proj, tmp_path):
    root, prot = proj
    d = _custom(tmp_path)
    yamledit.update_config({("sources",): [{"name": "mine", "proteomes_dir": str(d),
                                            "proteome_glob": "{sp}_long.pep.fasta",
                                            "taxonomy": "data/tax.tsv"}]})
    raw, _ = _raw()
    cands, rowless = ss.candidates(ss.sources(raw, root))
    assert [(c.sp, c.source) for c in cands] == [("Aaa", "default"), ("Bbb", "default"), ("Ccc", "mine")]
    assert cands[0].name == "Aaa sp" and cands[0].taxonomy == "Metazoa, X" and cands[0].path == prot / "Aaa_long.pep.fasta"
    assert rowless == ["mine: Qqq_long.pep.fasta"]            # Zzz (default) is dropped silently
    assert ss.read_taxonomy(root / "data" / "tax.tsv").keys() == {"Aaa", "Bbb", "Ccc"}   # short row skipped


def test_selected_roundtrip_plain_and_mapping():
    raw = {"species": ["Mlei", {"sp": "Abcd", "source": "mine"}]}
    sel = ss.selected(raw)
    assert sel == [("Mlei", "default"), ("Abcd", "mine")]
    assert ss.species_value(sel) == raw["species"]
    assert ss.selected({}) == []


def test_species_locked_flag_runs_outdir(proj):
    root, _ = proj
    raw, cfg = _raw()
    assert not ss.species_locked(raw, cfg)
    assert ss.species_locked({**raw, "species_locked": True}, cfg)
    (root / "runs" / "x").mkdir(parents=True)
    assert not ss.species_locked(raw, cfg)                    # a run dir without jobs.tsv is not a submit
    (root / "runs" / "x" / "jobs.tsv").write_text("1\tf\n")
    assert ss.species_locked(raw, cfg)
    (root / "runs" / "x" / "jobs.tsv").unlink()
    cfg.outdir.mkdir(parents=True, exist_ok=True)
    assert not ss.species_locked(raw, cfg)                    # empty outdir
    (cfg.outdir / "f").write_text("x")
    assert ss.species_locked(raw, cfg)


def test_lock_species_writes_flag_once(proj):
    raw, cfg = _raw()
    assert ss.lock_species(raw, cfg) is True
    text = paths.config_file().read_text()
    assert paths.read_raw()["species_locked"] is True
    raw, cfg = _raw()
    assert ss.lock_species(raw, cfg) is False
    assert paths.config_file().read_text() == text


def test_lock_species_never_writes_adopted(proj):
    yamledit.update_config({("prepare",): "locked"})
    before = paths.config_file().read_bytes()
    raw, cfg = _raw()
    assert ss.lock_species(raw, cfg) is False
    assert paths.config_file().read_bytes() == before


def test_lock_species_never_writes_inferred(proj):
    root, _ = proj
    (root / "runs" / "x").mkdir(parents=True)
    (root / "runs" / "x" / "jobs.tsv").write_text("1\tf\n")
    before = paths.config_file().read_bytes()
    raw, cfg = _raw()
    assert ss.lock_species(raw, cfg) is False
    assert paths.config_file().read_bytes() == before


def test_blockers_messages(proj, tmp_path):
    root, prot = proj
    raw, cfg = _raw()
    assert ss.blockers(raw, cfg, root) == []

    def with_(**kw):
        return ss.blockers({**raw, **kw}, cfg, root)

    assert with_(species=[]) == ["no species ticked"]
    two = _custom(tmp_path, ("Aaa_long.pep.fasta",))
    assert with_(species=["Aaa", {"sp": "Aaa", "source": "mine"}], sources=[
        {"name": "mine", "proteomes_dir": str(two), "proteome_glob": "{sp}_long.pep.fasta",
        "taxonomy": "data/tax.tsv"}]) == \
        ["Aaa is ticked from two sources: default, mine"]
    assert with_(species=["Aaa", "Nope"]) == [f"Nope: no proteome file in {prot} ({{sp}}_long.pep.fasta)"]
    d = tmp_path / "mine2"
    d.mkdir()
    (d / "Qqq_long.pep.fasta").write_text(">x\n")
    assert with_(sources=[{"name": "mine", "proteomes_dir": str(d), "taxonomy": "data/tax.tsv"}]) == \
        ["no taxonomy row for mine: Qqq_long.pep.fasta"]
    (root / "data" / "families.csv").write_text("")
    assert ss.blockers(raw, cfg, root) == ["no families in params.genefam_info"]


def test_blockers_glob_without_sp_or_unusable(proj, tmp_path):
    root, prot = proj
    raw, cfg = _raw()
    # no {sp}: every species would get the same (first) file -> one line for the source, no per-species ones
    out = ss.blockers({**raw, "species": ["Aaa", "Bbb"], "proteome_glob": "*_long.pep.fasta"}, cfg, root)
    assert out == ["source default: proteome_glob '*_long.pep.fasta' has no {sp}: "
                   "every species would get the same file"]
    for bad, err in (("{sp.x}", "AttributeError"), ("{sp}{x}", "KeyError"), ("{0}{sp}", "IndexError"),
                     ("{sp", "ValueError"), ("/abs/{sp}", "NotImplementedError")):
        out = ss.blockers({**raw, "proteome_glob": bad}, cfg, root)        # never raises
        assert len(out) == 1 and out[0].startswith(f"source default: proteome_glob {bad!r} unusable ({err}"), out
    d = _custom(tmp_path, ("Bbb.faa",))
    out = ss.blockers({**raw, "species": ["Aaa", {"sp": "Bbb", "source": "mine"}], "sources": [
        {"name": "mine", "proteomes_dir": str(d), "proteome_glob": "*.faa", "taxonomy": "data/tax.tsv"}]},
        cfg, root)
    assert out == ["source mine: proteome_glob '*.faa' has no {sp}: every species would get the same file"]


def test_blockers_prefix_with_underscore(proj):
    root, prot = proj
    (prot / "Aa_b_long.pep.fasta").write_text(">x\nM\n")
    raw, cfg = _raw()
    out = ss.blockers({**raw, "species": ["Aaa", "Aa_b"]}, cfg, root)
    assert "Aa_b: a species prefix cannot contain '_' (gene ids are split at the first '_')" in out


def test_blockers_trees_off_read_no_tree(proj, monkeypatch):
    """Ruling K: GeneRax and origins off: no tree line, and no base tree is read."""
    root, _prot = proj
    for f in ("base_tree.binary.newick", "base_tree.newick"):
        (root / "data" / f).unlink()
    raw, cfg = _raw()
    off = {**raw, "species": ["Aaa", "Bbb"],
           "params": {**raw.get("params", {}), "run_generax": False, "origins": False}}
    from druid import sptree
    monkeypatch.setattr(sptree, "build_trees", lambda *a: pytest.fail("a base tree was read"))
    assert ss.blockers(off, cfg, root) == []
    on = {**off, "params": {**off["params"], "origins": True}}
    assert ss.blockers(on, cfg, root)[0].startswith("species tree unreadable")


def _locked_when_called(monkeypatch):
    seen = []

    def fake(cmd):
        seen.append(yaml.safe_load(paths.config_file().read_text()).get("species_locked"))
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, "777\n", "")
    monkeypatch.setattr(model, "_slurm", fake)
    return seen


def _two_arrays():
    ids = paths.project_root() / "ids.txt"
    ids.write_text("a\n")
    sc = paths.project_root() / "a.sbatch"
    sc.write_text("#!/bin/sh\n")
    rd = paths.project_root() / "runs" / "r1"
    rd.mkdir(parents=True)
    return model.Written(rd, [(None, ["a"], ids, sc), (None, ["a"], ids, sc)])


def test_sbatch_all_locks_after_first_success(proj, monkeypatch):
    seen = _locked_when_called(monkeypatch)
    assert model.sbatch_all(_two_arrays()) == (["777", "777"], None)
    assert seen == [None, True]                     # set after the 1st array is queued, before the 2nd
    assert paths.read_raw()["species_locked"] is True


def test_sbatch_all_failed_first_sbatch_does_not_lock(proj, monkeypatch):
    import subprocess
    monkeypatch.setattr(model, "_slurm", lambda cmd: subprocess.CompletedProcess(cmd, 1, "", "denied"))
    submitted, err = model.sbatch_all(_two_arrays())
    assert submitted == [] and "sbatch failed" in err
    assert "species_locked" not in paths.read_raw()


def test_dry_run_does_not_lock(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(ss, "lock_species", lambda raw, cfg: calls.append(1))
    r = cli(["submit", "align", "tfs.A.HG11", "--dry-run"])
    assert r.exit_code == 0 and "nothing submitted (dry run)" in r.output and calls == []
    assert cli(["submit", "align", "tfs.A.HG11"]).exit_code == 0 and calls == [1]
