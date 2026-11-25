# `druid report` (step-2 HTML report) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** druid writes the step-2 interactive HTML report (`report_step2.html`) for a project, as one SLURM job, from the vendored phylohpc script.

**Architecture:** The script is vendored byte-for-byte under `druid/vendor/report_step2/` (refresh script + `VENDORED` stamp, as treeview). A new module `druid/report.py` builds the argument list and the sbatch text and submits it; `druid report` (cli) and one Results-tab key (tui) call it.

**Tech Stack:** Python 3, Typer CLI, Textual TUI, SLURM `sbatch`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-25-step2-report-design.md`

## Global Constraints

- Vendored file: `druid/vendor/report_step2/report_step2.py`, byte-identical to phylohpc `workflow/report_step2.py` at the stamped commit (today md5 `f3d58a2c…`, commit `f0fc039`); never edited by hand.
- `VENDORED` lines: `source: <repo>`, `commit: <full sha>`, `date: dd/mm/yyyy`.
- Job: name `<job_prefix>-report`; project partition/qos; `--cpus-per-task=1`; default `--mem=4096M`, `--time=30` (minutes); `--mem` / `--time` overrides use druid's existing parsers (`16G`, `90m`, `1d`).
- Output `<outdir>/report_step2.html`; with `-f PREFIX`: `<outdir>/report_step2.<PREFIX>.html`.
- Args: `--results_dir <outdir> --possvm_dir <outdir>/possvm --possvm_prev_dir <outdir>/possvm_prev --search_dir <outdir>/search --cluster_dir <outdir>/clusters --align_dir <outdir>/align --family_info <genefam_info or filtered copy> --species_tree <params.SPECIES_TREE> --species_info <project>/data/species_info.tsv`, plus `--refnames <REFNAMES> --refsps <REFSPECIES>` when set, `--species_images <params.report_images>` when set, `--output …`. All paths absolute.
- Refusals (no write, exit 2): `job_prefix` unset; no file in `<outdir>/possvm` nor `<outdir>/possvm_prev`; `-f` matches no family.
- Writes only inside the project: `runs/<ts>_report/` (dry run: the dry-run dir) and `<outdir>`.
- Full suite before each commit: `python -m pytest -q 2>&1 | tail -1` → 0 failed.

## Review Focus

1. Paths with spaces in the project dir: every argument in the sbatch is shell-quoted. → Task 2 `test_report_script_quotes_paths`.
2. `-f tfs` filter: the family table copy keeps the header and only matching rows, matched on whole id parts like other commands (`tfs` matches `tfs.T-box`, not `tfsx.A`). → Task 2 `test_report_family_filter`.
3. A project with GeneRax off (only `possvm_prev/`): not refused. → Task 2 `test_report_prev_only_ok`.
4. REFNAMES / REFSPECIES / report_images unset: their flags are absent, not empty strings. → Task 2 `test_report_optional_flags_absent`.
5. TUI key pressed twice quickly: one dialog/one submission per confirmed press; no submission without confirmation. → Task 3 `test_results_report_key_confirms`.

---

### Task 1: vendor the script

**Files:**
- Create: `druid/vendor/report_step2/report_step2.py` (copy), `druid/vendor/report_step2/VENDORED`, `druid/vendor/update_report.sh`
- Test: `tests/test_vendor.py`

**Interfaces:**
- Produces: `paths.DRUID_HOME / "druid/vendor/report_step2/report_step2.py"` (Task 2 runs it by path).

- [ ] **Step 1: Write the failing tests** in `tests/test_vendor.py`:
  - `test_vendored_report_matches_stamp`: the file exists; `VENDORED` has `source:`, `commit:` (40 hex) and `date:` lines; `python3 report_step2.py --help` exits 0 and mentions `--possvm_prev_dir`.
  - `test_update_report_script_copies_and_refuses_dirty`: same shape as `test_update_script_copies_without_tests_and_refuses_dirty` — a temp git repo with `workflow/report_step2.py`, `REPORT_REMOTE_REPO=<path>`, `VENDOR_DEST=<tmp>`; after the run `<dest>/report_step2/report_step2.py` equals the committed bytes and `VENDORED` names the HEAD sha; an uncommitted change → exit 1, "uncommitted" on stderr, nothing copied.
- [ ] **Step 2:** `python -m pytest -q tests/test_vendor.py -k report` → FAIL.
- [ ] **Step 3: Implement `druid/vendor/update_report.sh`** modelled on `update_treeview.sh` (same `_git` helper, dirty check, `git archive` of HEAD): it extracts only `workflow/report_step2.py` into `$VENDOR_DEST/report_step2/report_step2.py` and writes `VENDORED`. `REPORT_REMOTE_REPO` default: `$HOME/Documents/projects/phylogenies/phylohpc` (no cluster clone exists; measured 25/11/2026). Then run it once for real against that local clone (clean, HEAD `30b3944`) to create the vendored copy; confirm `md5sum` of the copy starts `f3d58a2c`.
- [ ] **Step 4:** tests pass; full suite 0 failed.
- [ ] **Step 5: Commit** `vendor: phylohpc report_step2.py (+ update_report.sh)`.

### Task 2: `druid/report.py` + `druid report`

**Files:**
- Create: `druid/report.py`
- Modify: `druid/cli.py` (new `report` command), `docs/reference.md` (command list + one paragraph)
- Test: `tests/test_report.py` (use the `cli` fixture from `tests/test_cli.py`: fake `sbatch` on PATH writing `calls.txt`, echoing `12345`; and its results fixture for a project with `possvm`/`possvm_prev` files)

**Interfaces:**
- Consumes: Task 1's vendored path.
- Produces:
  - `class ReportError(Exception)` (message shown as `ERROR: …`, exit 2)
  - `report_args(cfg, raw, fam: str | None, fam_file: Path | None) -> list[str]` — the script's argv after `python3 <script>`, absolute paths
  - `write(cfg, raw, fam: str | None = None, dry_run: bool = False, mem: str | None = None, time: str | None = None) -> Path` — makes the run dir via `model.new_run_dir("report", dry_run)`, writes `report.sbatch` (and `genefam.<fam>.csv` when `fam`), returns the sbatch path; raises `ReportError` on the refusals
  - `submit(script: Path) -> str` — `sbatch --parsable <script>` via `model._slurm`, returns the job id (raises `ReportError` on a non-zero exit, with sbatch's stderr)
  - `output_path(cfg, fam: str | None = None) -> Path`

- [ ] **Step 1: Write the failing tests** (`tests/test_report.py`):
  - `test_report_args_whole_project`: `report_args` == the Global Constraints list in that order, `--output <outdir>/report_step2.html`.
  - `test_report_optional_flags_absent`: REFNAMES/REFSPECIES/report_images unset → none of `--refnames --refsps --species_images` in argv; set → each present once with its value.
  - `test_report_family_filter`: `-f tfs` writes `genefam.tfs.csv` in the run dir with the source header and only rows whose family id matches `tfs` on whole id parts; argv `--family_info` points at it and `--output` ends `report_step2.tfs.html`; `-f nomatch` → `ReportError`, run dir not left behind.
  - `test_report_refusals`: no `job_prefix` → `ReportError`; no files in `possvm/` and `possvm_prev/` → `ReportError` mentioning both dirs.
  - `test_report_prev_only_ok`: only `possvm_prev/` populated → `write` succeeds.
  - `test_report_script_quotes_paths`: project dir containing a space → the sbatch's `python3` line is valid shell (`bash -n` exits 0) and `shlex.split` of it recovers each path intact.
  - `test_report_sbatch_header`: `#SBATCH --job-name=<prefix>-report`, `--cpus-per-task=1`, `--mem=4096M`, `--time=30`, partition/qos from config, `--output`/`--error` under the run dir; `mem="16G", time="2h"` → `--mem=16384M`, `--time=120`.
  - `test_cli_report_dry_run_and_submit`: `druid report -n` prints the script path and never calls sbatch (`calls.txt` absent); `druid report` calls sbatch once with `--parsable`, prints the job id `12345` and the output path.
- [ ] **Step 2:** `python -m pytest -q tests/test_report.py` → FAIL.
- [ ] **Step 3: Implement.** Family matching: reuse the helper the other `--fam` options use (find it from `FAM_HELP`'s users in `cli.py`); do not write a new matcher. Mem/time parsing: reuse druid's existing parsers used by `druid run --mem/--time`. `params.report_images` (not in `core.PATH_PARAMS`): a relative value is resolved against the project root. Validate every refusal before creating the run dir. The sbatch text: shebang, `#SBATCH` header (above), `set -euo pipefail`, `export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1`, then the `python3` line with every token `shlex.quote`d. `docs/reference.md`: add `druid report [-f PREFIX] [-n] [--mem] [--time]` to the command list and one paragraph (what it writes, where, defaults, the refusals, species images via `params.report_images`).
- [ ] **Step 4:** tests pass; full suite 0 failed.
- [ ] **Step 5: Commit** `druid report: step-2 HTML report as one SLURM job`.

### Task 3: Results-tab key and header

**Files:**
- Modify: `druid/tui.py` (Results tab binding + header text), `docs/reference.md` (Results keys line)
- Test: `tests/test_tui.py` (or the file holding Results-tab tests; follow its app/pilot helpers)

**Interfaces:**
- Consumes: `report.write`, `report.submit`, `report.output_path`, `report.ReportError` (Task 2).

- [ ] **Step 1: Write the failing tests:**
  - `test_results_header_shows_report_age`: no report → header contains `report: none`; after touching `<outdir>/report_step2.html` and refreshing (`R`) → contains `report: ` + the path relative to the project and an age (e.g. `0m ago`).
  - `test_results_report_key_confirms`: on Results, the report key opens a confirm prompt naming the output path; `n`/`esc` → no sbatch call; `y` → exactly one sbatch call and the status line shows the job id `12345`; a `ReportError` (e.g. no `job_prefix`) shows `ERROR: …` and calls nothing.
- [ ] **Step 2:** run them → FAIL.
- [ ] **Step 3: Implement.** Key: `W` (free on Results today: check `Binding(` list in `tui.py` around line 600; pick another free capital and say which in the report if `W` is taken), label `report`. Reuse the TUI's existing confirm-dialog pattern (the one `x` uses on Jobs). Header text: `report: <relpath> (<age> ago)` or `report: none`, age via the existing age/duration formatter if the TUI has one.
- [ ] **Step 4:** tests pass; full suite 0 failed.
- [ ] **Step 5: Commit** `tui: Results W submits druid report; header shows report age`.
