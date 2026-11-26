import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from druid import core, paths, report
from tests.conftest import _w
from tests.test_cli import calls_txt, cli  # noqa: F401  (fixture)

_REAL_ETE3_ERROR = getattr(report, "_ete3_error", None)


@pytest.fixture(autouse=True)
def _ete3_ok(monkeypatch):
    """The host python3 need not have ete3: the check is exercised on a fake python3 below."""
    monkeypatch.setattr(report, "_ete3_error", lambda: None, raising=False)


def _cfg(results_tree, **params):
    cfg, root = results_tree
    _w(root / "data/species_info.tsv", "Hsap\tHomo sapiens\tChordata\n")
    raw = paths.read_raw()
    raw["params"].pop("REFNAMES", None)
    raw["params"].pop("REFSPECIES", None)
    raw["params"].pop("report_images", None)
    raw["params"].update(params)
    return core.config_from_raw(raw), raw, root


def _lines(script):
    return script.read_text().splitlines()


def _line(script):
    """The report command (not the `python3 -c 'import ete3'` check before it)."""
    return next(l for l in _lines(script) if l.startswith("python3 ") and "report_step2.py" in l)


def _arg(script, flag):
    toks = shlex.split(_line(script))
    return toks[toks.index(flag) + 1]


def test_report_args_whole_project(results_tree):
    cfg, raw, root = _cfg(results_tree, REFNAMES="refnames.csv", REFSPECIES="Mmus")
    out = cfg.outdir
    assert report.report_args(cfg, raw, None, None) == [
        "--results_dir", str(out), "--possvm_dir", f"{out}/possvm", "--possvm_prev_dir", f"{out}/possvm_prev",
        "--search_dir", f"{out}/search", "--cluster_dir", f"{out}/clusters", "--align_dir", f"{out}/align",
        "--family_info", cfg.params["genefam_info"], "--species_tree", cfg.params["SPECIES_TREE"],
        "--species_info", f"{root}/data/species_info.tsv",
        "--refnames", f"{root}/refnames.csv", "--refsps", "Mmus",
        "--output", f"{out}/report_step2.html.part"]


def test_report_optional_flags_absent(results_tree):
    cfg, raw, root = _cfg(results_tree)
    a = report.report_args(cfg, raw, None, None)
    assert not {"--refnames", "--refsps", "--species_images"} & set(a)
    cfg, raw, root = _cfg(results_tree, REFNAMES="refnames.csv", REFSPECIES="Mmus", report_images="img")
    a = report.report_args(cfg, raw, None, None)
    for flag, val in (("--refnames", f"{root}/refnames.csv"), ("--refsps", "Mmus"),
                      ("--species_images", f"{root}/img")):
        assert a.count(flag) == 1 and a[a.index(flag) + 1] == val


def test_report_family_filter(results_tree):
    cfg, raw, root = _cfg(results_tree)
    gf = Path(cfg.params["genefam_info"])
    gf.write_text("#header\n" + gf.read_text() + "X\tPF_X\t1.1\t3\tGA\tTF\ttfsx\n")
    s = report.write(cfg, raw, fam="tfs")
    fam_file = s.parent / "genefam.tfs.csv"
    lines = fam_file.read_text().splitlines()
    assert lines[0] == "#header"
    assert [l.split("\t")[0] for l in lines[1:] if l] == ["A", "B", "C_x"]
    a = report.report_args(cfg, raw, "tfs", fam_file)
    assert a[a.index("--family_info") + 1] == str(fam_file)
    assert a[a.index("--output") + 1].endswith("report_step2.tfs.html.part")
    assert "report_step2.tfs.html" in _line(s)
    before = sorted(p.name for p in (root / "runs").iterdir())
    with pytest.raises(report.ReportError):
        report.write(cfg, raw, fam="nomatch")
    assert sorted(p.name for p in (root / "runs").iterdir()) == before


def test_report_family_views(results_tree):
    """-f <class>.<family>: the per-HG dirs the script filters by class are passed as symlink
    views in the run dir holding only that family's files; results/ is not touched."""
    cfg, raw, root = _cfg(results_tree)
    out = cfg.outdir
    _w(out / "search/tfs.A.genes.list", "a\n")
    _w(out / "search/tfs.B.genes.list", "b\n")
    listing = lambda: sorted(str(p.relative_to(out)) for p in out.rglob("*"))  # noqa: E731
    before = listing()
    s = report.write(cfg, raw, fam="tfs.A")
    v = s.parent / "view"
    want = {"possvm": ["tfs.A.HG11.generax.support.tree.ortholog_groups.csv"],
            "possvm_prev": ["tfs.A.HG1.treefile.ortholog_groups.csv"],
            "search": ["tfs.A.genes.list"],
            "clusters": ["tfs.A.HG1.fasta", "tfs.A.HG11.fasta"]}
    flags = {"possvm": "--possvm_dir", "possvm_prev": "--possvm_prev_dir", "search": "--search_dir",
             "clusters": "--cluster_dir"}
    for name, files in want.items():
        assert sorted(os.listdir(v / name)) == files
        for f in files:
            assert (v / name / f).is_symlink() and os.readlink(v / name / f) == str(out / name / f)
        assert _arg(s, flags[name]) == str(v / name)
    assert _arg(s, "--results_dir") == str(out) and _arg(s, "--align_dir") == str(out / "align")
    assert _arg(s, "--family_info") == str(s.parent / "genefam.tfs.A.csv")
    assert listing() == before
    for fam in (None, "tfs"):                       # whole project and a class: no views
        s = report.write(cfg, raw, fam=fam)
        assert not (s.parent / "view").exists()
        for name, flag in flags.items():
            assert _arg(s, flag) == str(out / name)


def test_report_refusals(results_tree):
    cfg, raw, root = _cfg(results_tree)
    raw2 = dict(raw, job_prefix=None)
    with pytest.raises(report.ReportError):
        report.write(core.config_from_raw(raw2), raw2)
    for d in ("possvm", "possvm_prev"):
        for f in (cfg.outdir / d).iterdir():
            f.unlink()
    with pytest.raises(report.ReportError) as e:
        report.write(cfg, raw)
    assert "possvm_prev" in str(e.value) and f"{cfg.outdir}/possvm " in str(e.value)
    assert not (root / "runs").exists()


def test_report_check_writes_nothing(results_tree):
    cfg, raw, root = _cfg(results_tree)
    report.check(cfg, raw)
    report.check(cfg, raw, fam="tfs.A", mem="8G", time="1h")
    assert not (root / "runs").exists() and not (root / ".druid/tmp/dryrun").exists()
    with pytest.raises(report.ReportError):
        report.check(cfg, raw, mem="lots")


def test_report_refuses_missing_inputs(results_tree):
    cfg, raw, root = _cfg(results_tree)
    sp = root / "data/species_info.tsv"
    sp.unlink()
    with pytest.raises(report.ReportError) as e:
        report.write(cfg, raw)
    assert str(sp) in str(e.value)
    for k in ("SPECIES_TREE", "genefam_info"):
        cfg, raw, root = _cfg(results_tree, **{k: str(root / "gone.file")})
        with pytest.raises(report.ReportError) as e:
            report.write(cfg, raw)
        assert f"params.{k}" in str(e.value) and str(root / "gone.file") in str(e.value)
    assert not (root / "runs").exists()


def test_report_fam_without_genefam_says_unset(results_tree):
    cfg, raw, root = _cfg(results_tree, genefam_info=None)
    with pytest.raises(report.ReportError) as e:
        report.write(cfg, raw, fam="tfs")
    assert "params.genefam_info is not set" in str(e.value) and "None" not in str(e.value)


def test_report_refuses_without_ete3(results_tree, tmp_path, monkeypatch):
    """The job's python3 runs with PYTHONNOUSERSITE=1; without ete3 the script writes a report with
    no trees and exits 0, so druid refuses before writing anything."""
    monkeypatch.setattr(report, "_ete3_error", _REAL_ETE3_ERROR)
    cfg, raw, root = _cfg(results_tree)
    b = tmp_path / "bin"
    b.mkdir()
    py = b / "python3"
    # a user-site ete3 would import: the check must hide it the way the sbatch does
    py.write_text('#!/bin/sh\n[ "$PYTHONNOUSERSITE" = 1 ] || exit 0\n'
                  "echo \"ModuleNotFoundError: No module named 'ete3'\" >&2\nexit 1\n")
    py.chmod(0o755)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(report.ReportError) as e:
        report.check(cfg, raw)
    m = str(e.value)
    assert "cannot import ete3" in m and "No module named 'ete3'" in m and "conda activate phylo" in m
    with pytest.raises(report.ReportError):
        report.write(cfg, raw)
    assert not (root / "runs").exists()
    py.write_text('#!/bin/sh\n[ "$PYTHONNOUSERSITE" = 1 ] || exit 1\nexit 0\n')
    report.check(cfg, raw)


def test_report_prev_only_ok(results_tree):
    cfg, raw, root = _cfg(results_tree)
    for f in (cfg.outdir / "possvm").iterdir():
        f.unlink()
    assert report.write(cfg, raw).is_file()


def test_report_script_quotes_paths(results_tree, tmp_path, monkeypatch):
    cfg0, root0 = results_tree
    root = tmp_path / "my proj"
    shutil.copytree(root0, root)
    _w(root / "data/species_info.tsv", "Hsap\tHomo sapiens\tChordata\n")
    raw = yaml.safe_load((root / "druid.yaml").read_text().replace(str(root0), str(root)))
    raw["outdir"] = str(root / "res ults")
    raw["params"]["report_images"] = "im ages"
    (root / "druid.yaml").write_text(yaml.safe_dump(raw))
    _w(root / "res ults/possvm_prev/x.csv", "x\n")
    monkeypatch.setenv("DRUID_PROJECT", str(root))
    raw = paths.read_raw()
    cfg = core.config_from_raw(raw)
    s = report.write(cfg, raw)
    assert subprocess.run(["bash", "-n", str(s)]).returncode == 0
    toks = shlex.split(_line(s))
    assert toks[2:4] == ["--results_dir", str(root / "res ults")]
    assert toks[toks.index("--species_images") + 1] == str(root / "im ages")
    assert toks[toks.index("--output") + 1] == str(root / "res ults/report_step2.html.part")
    mv = next(l for l in _lines(s) if l.startswith("mv "))
    assert shlex.split(mv)[-2:] == [str(root / "res ults/report_step2.html.part"),
                                    str(root / "res ults/report_step2.html")]


def test_report_sbatch_header(results_tree):
    cfg, raw, root = _cfg(results_tree)
    s = report.write(cfg, raw)
    t = s.read_text()
    run = s.parent
    for l in ("#SBATCH --job-name=t-report", "#SBATCH --cpus-per-task=1", "#SBATCH --mem=4096M",
              "#SBATCH --time=30", f"#SBATCH --partition={cfg.partition}", f"#SBATCH --qos={cfg.qos}",
              f"#SBATCH --chdir={run}",
              "set -euo pipefail", "export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1"):
        assert l in t.splitlines()
    assert f"#SBATCH --output={run}/logs/report_%j.out" in t
    assert f"#SBATCH --error={run}/logs/report_%j.err" in t
    lines = _lines(s)
    out = cfg.outdir / "report_step2.html"
    i_ete3 = lines.index("python3 -c 'import ete3'")
    i_cmd = lines.index(_line(s))
    i_mv = next(i for i, l in enumerate(lines) if l.startswith("mv "))
    assert i_ete3 < i_cmd < i_mv
    assert shlex.split(lines[i_mv]) == ["mv", "-f", "--", f"{out}.part", str(out)]
    assert _arg(s, "--output") == f"{out}.part"
    t = report.write(cfg, raw, mem="16G", time="2h").read_text()
    assert "--mem=16384M" in t and "--time=120" in t


# Just enough of ete3.Tree (format=1) for report_step2.py: the tests do not depend on the host
# python having ete3, and PYTHONNOUSERSITE=1 (exported by the sbatch) hides a user-site copy.
ETE3_STUB = '''
import os


class Tree:
    def __init__(self, newick=None, format=0):
        self.children, self.name, self.dist, self.support = [], "", 0.0, 1.0
        if newick is not None:
            s = open(newick).read() if os.path.exists(newick) else newick
            _parse(s.strip().rstrip(";"), 0, self)

    def is_leaf(self):
        return not self.children

    def get_leaves(self):
        return [self] if self.is_leaf() else [l for c in self.children for l in c.get_leaves()]

    def traverse(self, strategy="levelorder"):
        q = [self]
        while q:
            n = q.pop(0)
            yield n
            q += n.children


def _parse(s, i, node):
    if i < len(s) and s[i] == "(":
        while True:
            child = Tree()
            node.children.append(child)
            i = _parse(s, i + 1, child)
            if s[i] != ",":
                break
        i += 1
    j = i
    while j < len(s) and s[j] not in ",()":
        j += 1
    name, _, dist = s[i:j].partition(":")
    node.name, node.dist = name.strip(), float(dist) if dist else 0.0
    return j
'''

NWK = "((Hsap_g1:1,Mmus_g1:1)0.9:1,Nvec_g1:1);\n"


def _run_sbatch(script, stub_dir):
    """The job as SLURM would run it (bash ignores the #SBATCH lines)."""
    env = {**os.environ, "PYTHONPATH": str(stub_dir)}
    return subprocess.run(["bash", str(script)], cwd=script.parent, env=env, capture_output=True, text=True)


def _tree_ids(html_path):
    return set(re.findall(r'<script type="application/json" id="treedata-([^"]+)">', html_path.read_text()))


def test_report_end_to_end_family_filter(results_tree, tmp_path):
    """Runs the generated job on the fixture (with an ete3 stub): whole project, a class and one
    family each embed exactly their own gene trees."""
    cfg, raw, root = _cfg(results_tree)
    out = cfg.outdir
    for d, stem in (("possvm", "tfs.A.HG11.generax.support.tree"), ("possvm_prev", "tfs.A.HG1.treefile"),
                    ("possvm_prev", "tfs.B.HG2.treefile"), ("possvm_prev", "tfs.C_x.HG1.treefile"),
                    ("possvm_prev", "slc.NEW.HG1.treefile")):
        _w(out / d / f"{stem}.ortholog_groups.newick", NWK)
    _w(out / "clusters/slc.NEW.HG1.fasta", ">Hsap_g1\nAA\n")
    stub = tmp_path / "stub"
    _w(stub / "ete3/__init__.py", ETE3_STUB)
    tfs = {"tfs.A.HG1", "tfs.A.HG11", "tfs.B.HG2", "tfs.C_x.HG1"}
    for fam, ids, html in ((None, tfs | {"slc.NEW.HG1"}, "report_step2.html"),
                           ("tfs", tfs, "report_step2.tfs.html"),
                           ("tfs.A", {"tfs.A.HG1", "tfs.A.HG11"}, "report_step2.tfs.A.html")):
        s = report.write(cfg, raw, fam=fam)
        r = _run_sbatch(s, stub)
        assert r.returncode == 0, r.stderr
        assert _tree_ids(out / html) == ids, fam
        assert not (out / f"{html}.part").exists()
    assert not list(paths.DRUID_HOME.joinpath("druid/vendor/report_step2").glob("__pycache__"))


def test_report_job_without_ete3_fails_and_writes_no_report(results_tree, tmp_path):
    """A compute node whose python3 lacks ete3 fails the job before the script runs (it would
    otherwise write a report with no trees and exit 0); no output, no .part."""
    cfg, raw, root = _cfg(results_tree)
    stub = tmp_path / "stub"
    _w(stub / "ete3/__init__.py", "raise ImportError(\"No module named 'ete3' (stub)\")\n")
    s = report.write(cfg, raw)
    r = _run_sbatch(s, stub)
    assert r.returncode != 0 and "ete3" in r.stderr and "Report written" not in r.stderr
    out = cfg.outdir / "report_step2.html"
    assert not out.exists() and not Path(f"{out}.part").exists()


def test_cli_report_dry_run_and_submit(cli):
    _w(paths.project_root() / "data/species_info.tsv", "Hsap\tHomo sapiens\tChordata\n")
    r = cli(["report", "-n"])
    assert r.exit_code == 0 and "report.sbatch" in r.output
    assert not calls_txt().exists()
    r = cli(["report"])
    assert r.exit_code == 0 and "12345" in r.output and "report_step2.html" in r.output
    assert calls_txt().read_text().count("--parsable") == 1
    assert cli(["report", "-f", "nomatch"]).exit_code == 2
