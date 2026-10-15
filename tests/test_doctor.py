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


def test_tools_match_what_the_stages_call():
    # grep of druid/stages/*.sh + submodules/phylogeny/{main.py,helper/*.py}, 14/10/2026
    for t in ("hmmsearch", "hmmfetch", "bedtools", "samtools", "diamond", "mcl", "mafft",
              "clipkit", "iqtree2", "generax", "mpirun", "sbatch", "squeue", "sacct"):
        assert t in doctor.TOOLS, t
    assert "hmmpress" not in doctor.TOOLS


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


def test_species_tree_tips_counted(results_tree):
    c = _names(doctor.checks())["species_tree"]
    assert c.ok and "2 tips" in c.detail


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


def test_write_target_outside_project_is_a_fail_line_not_a_crash(results_tree, tmp_path):
    import yaml
    cfg, root = results_tree
    raw = yaml.safe_load((root / "druid.yaml").read_text())
    raw["outdir"] = str(tmp_path / "elsewhere")
    (root / "druid.yaml").write_text(yaml.safe_dump(raw))
    c = _names(doctor.checks())["config"]
    assert not c.ok and "inside the project" in c.detail
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert r.exit_code == 1 and "FAIL config" in r.output


def test_malformed_druid_yaml_is_a_fail_line(results_tree):
    cfg, root = results_tree
    (root / "druid.yaml").write_text("a: [unclosed\n")
    c = _names(doctor.checks())["config"]
    assert not c.ok


def test_cli_exit_code(results_tree, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda t: None)
    r = CliRunner().invoke(cli.app, ["doctor"])
    assert r.exit_code == 1 and "FAIL" in r.output


def test_tool_output_that_is_not_utf8_does_not_crash(tmp_path, monkeypatch):
    fake = tmp_path / "bin" / "fakeoddtool"
    fake.parent.mkdir()
    fake.write_bytes(b"#!/bin/sh\nprintf 'v1 \\253\\n'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake.parent) + ":" + __import__("os").environ["PATH"])
    assert doctor._version("fakeoddtool").startswith("v1")


def test_a_flag_the_tool_rejects_is_not_reported_as_its_version(tmp_path, monkeypatch):
    fake = tmp_path / "bin" / "hmmlike"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\n"
                    "if [ \"$1\" = -h ]; then printf '# hmmlike :: search\\n# HMMER 3.4 (Aug 2023)\\n'; exit 0; fi\n"
                    "echo 'Failed to parse command line: No such option' >&2; exit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake.parent) + ":" + __import__("os").environ["PATH"])
    assert doctor._version("hmmlike") == "# HMMER 3.4 (Aug 2023)"


def test_version_probe_gets_no_stdin(monkeypatch):
    seen = {}

    class R:
        returncode, stdout, stderr = 0, "tool 1.2\n", ""

    def fake_run(cmd, **kw):
        seen.update(kw)
        return R()
    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    assert doctor._version("whatever") == "tool 1.2"
    assert seen.get("stdin") is doctor.subprocess.DEVNULL
    assert seen.get("cwd") == "/"                      # a tool that scribbles on -h scribbles nowhere useful


def test_mpirun_missing_says_who_needs_it(monkeypatch):
    real = doctor.shutil.which
    monkeypatch.setattr(doctor.shutil, "which", lambda t: None if t == "mpirun" else real(t))
    c = _names(doctor.checks())["mpirun"]
    assert not c.ok                                                # still a FAIL
    assert c.detail == ("not on PATH \u2014 needed by the generax stage only (module load OpenMPI, "
                        "or a conda env whose openmpi provides mpirun)")


def test_relative_proteomes_dir_is_resolved_against_the_project(results_tree, tmp_path, monkeypatch):
    import yaml
    cfg, root = results_tree
    (root / "prot").mkdir()
    (root / "prot" / "Mlei_long.pep.fasta").write_text(">Mlei_1\nM\n")
    raw = yaml.safe_load((root / "druid.yaml").read_text())
    raw.update(proteomes_dir="prot", proteome_glob="{sp}_long.pep.fasta", species=["Mlei"])
    (root / "druid.yaml").write_text(yaml.safe_dump(raw))
    monkeypatch.chdir(tmp_path)                       # not the project dir
    c = _names(doctor.checks())["proteomes"]
    assert c.ok and "1/1" in c.detail


def test_bad_proteome_glob_is_a_fail_line_not_a_crash(results_tree, tmp_path):
    import yaml
    cfg, root = results_tree
    prot = tmp_path / "prot"
    prot.mkdir()
    for glob in ("{typo}_long.pep.fasta", "{}_long.pep.fasta", "{sp", "/abs/{sp}.fasta"):
        raw = yaml.safe_load((root / "druid.yaml").read_text())
        raw.update(proteomes_dir=str(prot), proteome_glob=glob, species=["Mlei"])
        (root / "druid.yaml").write_text(yaml.safe_dump(raw))
        c = _names(doctor.checks())["proteomes"]
        assert not c.ok and "proteome_glob" in c.detail, glob


def test_explicit_project_without_druid_yaml_is_a_fail_not_a_skip(tmp_path, monkeypatch):
    from druid import paths
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("DRUID_PROJECT", str(empty))
    c = _names(doctor.checks())["project"]
    assert not c.ok and "druid.yaml" in c.detail and "SKIP" not in c.detail
    paths.use(empty)                                   # --project
    monkeypatch.delenv("DRUID_PROJECT")
    c = _names(doctor.checks())["project"]
    assert not c.ok and "SKIP" not in c.detail
    r = CliRunner().invoke(cli.app, ["--project", str(empty), "doctor"])
    assert r.exit_code == 1 and "FAIL project" in r.output


def test_walk_up_finding_nothing_stays_a_skip(tmp_path, monkeypatch):
    from druid import paths
    monkeypatch.delenv("DRUID_PROJECT", raising=False)
    paths.use(None)
    monkeypatch.chdir(tmp_path)
    c = _names(doctor.checks())["project"]
    assert c.ok and c.detail.startswith("SKIP")
