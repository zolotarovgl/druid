import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from druid import core, paths, report
from tests.conftest import _w
from tests.test_cli import calls_txt, cli  # noqa: F401  (fixture)


def _cfg(results_tree, **params):
    cfg, root = results_tree
    raw = paths.read_raw()
    raw["params"].pop("REFNAMES", None)
    raw["params"].pop("REFSPECIES", None)
    raw["params"].pop("report_images", None)
    raw["params"].update(params)
    return core.config_from_raw(raw), raw, root


def _line(script):
    return next(l for l in script.read_text().splitlines() if l.startswith("python3 "))


def test_report_args_whole_project(results_tree):
    cfg, raw, root = _cfg(results_tree, REFNAMES="refnames.csv", REFSPECIES="Mmus")
    out = cfg.outdir
    assert report.report_args(cfg, raw, None, None) == [
        "--results_dir", str(out), "--possvm_dir", f"{out}/possvm", "--possvm_prev_dir", f"{out}/possvm_prev",
        "--search_dir", f"{out}/search", "--cluster_dir", f"{out}/clusters", "--align_dir", f"{out}/align",
        "--family_info", cfg.params["genefam_info"], "--species_tree", cfg.params["SPECIES_TREE"],
        "--species_info", f"{root}/data/species_info.tsv",
        "--refnames", f"{root}/refnames.csv", "--refsps", "Mmus",
        "--output", f"{out}/report_step2.html"]


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
    assert a[a.index("--output") + 1].endswith("report_step2.tfs.html")
    assert "report_step2.tfs.html" in _line(s)
    before = sorted(p.name for p in (root / "runs").iterdir())
    with pytest.raises(report.ReportError):
        report.write(cfg, raw, fam="nomatch")
    assert sorted(p.name for p in (root / "runs").iterdir()) == before


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


def test_report_prev_only_ok(results_tree):
    cfg, raw, root = _cfg(results_tree)
    for f in (cfg.outdir / "possvm").iterdir():
        f.unlink()
    assert report.write(cfg, raw).is_file()


def test_report_script_quotes_paths(results_tree, tmp_path, monkeypatch):
    cfg0, root0 = results_tree
    root = tmp_path / "my proj"
    shutil.copytree(root0, root)
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
    assert toks[toks.index("--output") + 1] == str(root / "res ults/report_step2.html")


def test_report_sbatch_header(results_tree):
    cfg, raw, root = _cfg(results_tree)
    t = report.write(cfg, raw).read_text()
    run = (root / "runs").iterdir().__next__()
    for l in ("#SBATCH --job-name=t-report", "#SBATCH --cpus-per-task=1", "#SBATCH --mem=4096M",
              "#SBATCH --time=30", f"#SBATCH --partition={cfg.partition}", f"#SBATCH --qos={cfg.qos}",
              "set -euo pipefail", "export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1"):
        assert l in t.splitlines()
    assert f"#SBATCH --output={run}/logs/report_%j.out" in t
    assert f"#SBATCH --error={run}/logs/report_%j.err" in t
    t = report.write(cfg, raw, mem="16G", time="2h").read_text()
    assert "--mem=16384M" in t and "--time=120" in t


def test_cli_report_dry_run_and_submit(cli):
    r = cli(["report", "-n"])
    assert r.exit_code == 0 and "report.sbatch" in r.output
    assert not calls_txt().exists()
    r = cli(["report"])
    assert r.exit_code == 0 and "12345" in r.output and "report_step2.html" in r.output
    assert calls_txt().read_text().count("--parsable") == 1
    assert cli(["report", "-f", "nomatch"]).exit_code == 2
