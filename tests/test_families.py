import os
import stat

from druid import core, families, paths


def test_library_356_rows_parse_like_core():
    rows = families.library()
    assert len(rows) == 356
    ids, _ = core.parse_genefam(paths.DRUID_HOME / "druid" / "data" / "families_library.csv")
    assert families.ticked_ids(rows) == set(ids)


def test_write_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "project_root", lambda: tmp_path)
    rows = families.library()
    out = families.write(tmp_path / "fam.csv", rows)
    assert families.read(out) == rows
    lib = paths.DRUID_HOME / "druid" / "data" / "families_library.csv"
    assert core.parse_genefam(out) == core.parse_genefam(lib)


def test_hmm_rows_defaults_ga_and_evalue(tmp_path):
    (tmp_path / "a.hmm").write_text("NAME a\nGA    25.0 25.0;\n")
    (tmp_path / "b.hmm").write_text("NAME b\n")
    (tmp_path / "c.txt").write_text("x")
    a, b = families.hmm_rows(tmp_path)
    assert a == families.Row("a", "a", "1.1", "3", "GA", "custom", "cus")
    assert (b.class_name, b.hmms, b.threshold) == ("b", "b", "1e-5")
    assert families.ticked_ids([a, b]) == {"cus.a", "cus.b"}


def test_hmm_dir_untouched(tmp_path):
    d = tmp_path / "hmms"
    d.mkdir()
    (d / "a.hmm").write_text("GA 1 1;\n")
    before = os.stat(d).st_mtime_ns, os.stat(d / "a.hmm").st_mtime_ns
    d.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        families.hmm_rows(d)
    finally:
        d.chmod(stat.S_IRWXU)
    assert (os.stat(d).st_mtime_ns, os.stat(d / "a.hmm").st_mtime_ns) == before
    assert sorted(os.listdir(d)) == ["a.hmm"]


def test_hmm_rows_take_the_default_inflation(tmp_path):
    (tmp_path / "X.hmm").write_text("HMMER3\nGA 10 10;\n")
    assert families.hmm_rows(tmp_path, "1.4")[0].inflation == "1.4"
    assert families.hmm_rows(tmp_path)[0].inflation == "1.1"
