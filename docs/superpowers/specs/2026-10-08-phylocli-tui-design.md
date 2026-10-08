# phylocli TUI — design

Date: 08/10/2026 · Branch: `phylocli` · Status: approved in chat (Grygoriy), spec awaiting review

## Goal

One full-screen terminal view on the cluster login node to **monitor step2 progress and repair
failures without typing commands**: pick a stage, list its failed/ready HGs, select some,
resubmit them with bumped resources after a dry run and an explicit confirmation.

Success = the TUI's numbers are identical to `phylo status` / `phylo jobs`, and nothing is ever
submitted without a confirmed dry run.

## Constraints

- **CLI unchanged**: output text and exit codes of `status`, `missing`, `submit`, `jobs` stay
  byte-identical; the existing 118 tests pin them and must pass unmodified.
- **Python 3.9-safe** (cluster `phylo` env; tests run on mambaforge python3 and a 3.9 venv).
- **Textual is optional**: imported only by `phylo tui`; every other command works without it.
- Runs over SSH on `login1` inside the `phylo` env (Textual installed there 08/10/2026).

## Architecture

```
phylo.py (typer CLI) ──┐
                       ├──> model.py (data only, no printing) ──> core.py / history.py / common.py
tui.py (Textual app) ──┘
```

### `phylocli/model.py` (new) — pure data layer

| function | returns |
|---|---|
| `stage_rows(cfg, exp=None)` | per stage: `done, running, ready, blocked, total` (`n/a` when not applicable) — the numbers `_summary` prints today |
| `hg_rows(cfg, stage)` | one row per expected HG: `hg, state, nseq, last` where `state ∈ {done, running, ready, failed, blocked}`; **failed** = ready AND latest attempt for this stage is in `FAILED_STATES` |
| `array_rows(stage=None, last=10)` | latest submissions: job id, stage, n tasks, per-state counts (from `sacct`), run dir |
| `hg_detail(cfg, hg)` | nseq, per-stage state, latest attempt per stage (requested / used / reason / log path) |
| `bump(attempt, res)` | `Res` for a resubmit: OOM → mem ×2, TIMEOUT → time ×2, anything else → unchanged |
| `plan_submit(stage, hgs, overrides, ...)` | a `Plan` (arrays: resources + ids, notes, skipped HGs, validation errors); writes nothing |
| `run_submit(plan, dry_run)` | writes run dir + sbatch scripts; submits unless `dry_run`; returns submitted job ids and any failure |

`live` (squeue), `sacct` and history reads stay where they are; `model.py` calls them and
returns `None`-marked fields when a tool is missing, instead of printing.

### `phylo.py` — commands become printers over `model.py`

`status`, `missing`, `jobs`, `submit` call `model.*` and format the result exactly as today.
The refactor is behaviour-preserving; the 118 tests are the guard.

### `core.group()` — per-HG overrides

Gains an optional `per_hg: dict[str, dict]` (mem_mb / time_min / cpus per HG), applied on top of
the existing `override`; HGs whose resulting `Res` differ land in different arrays (as today's
grouping already does by `Res`).

### `phylocli/tui.py` (new) — Textual app, `phylo tui`

`phylo tui` imports `phylocli.tui` lazily; without Textual it exits 1 with
`textual not installed: pip install textual`.

## Screens and interaction

### Overview — the first screen (amended 09/10/2026, Grygoriy: "I don't want to see the logs at first, I want to see the overview of stages, maybe binned by family")

`phylo tui` opens on an **overview**, not on the HG panels:

```
phylocli · Phylogenies_v3 · 10:42                      [c]ategory / [f]amily · q
              align      tree       possvm_prev generax    gxsup      possvm
ALL   1822    ██████████ █████████▓ █████████░  █████████▒ ████████░░ ████████░░  1757 done
adh    912    ██████████ ██████████ ██████████  █████████▒ █████████░ █████████░
tfs    489    ██████████ █████████▓ █████████░  ██████████ ████████░░ ████████░░
█ done ▒ running ▓ ready/failed ░ blocked      enter: open the HGs of a row
```

- One row per **category** (first id part: `tfs`, `adh`, …) by default; `f` switches to one row per
  **family** (`tfs.T-box`, …), `c` back. Rows sorted by HG count, descending; an `ALL` row first.
- One column per applicable stage: a fixed-width bar of done / running / ready / blocked
  (same glyphs and largest-remainder rounding as `phylo status`; `n/a` for a non-applicable
  stage). A footer line shows the exact counts of the highlighted row per stage.
- **ready includes failed** at this level ("▓ ready/failed"): the overview reads only output
  files + `squeue`, never the attempt history, so it cannot tell them apart — that keeps a refresh
  to the cost of `phylo status` (~2 s on v3).
- The `ALL` row's numbers equal `phylo status` exactly (one code path: `model`).
- Refresh in the background every 30 s and on `R`; the cursor row is kept across refreshes.
- **Cell cursor** (amended 09/10/2026, Grygoriy: "select the stage, then move to the second
  window and select which jobs I want to resubmit"): `↑↓` picks the group, `←→` picks the stage
  column. `enter` on a stage cell opens the HG view **for that group at that stage**: the stage
  is preselected in the stages panel, the filter is `failed`, and the cursor is already in the HG
  list, so the next keys are `space`… / `a`, then `r`. `enter` on the group or HG-count column
  opens the group at the current stage.
- Keys: `↑↓←→` move · `enter` open · `c`/`f` grouping · `R` refresh · `q` quit.

### HG view — opened from an overview row with `enter`

The four panels below, **restricted to the HGs of that row** (all HGs for `ALL`). The attempt
history (`history.attempts`, the slow part: ~3.5 s on v3) is loaded only here, in the background,
and cached for the session; until it arrives the HG list is empty and the banner says
"loading history…" (amended 09/10/2026: an empty list rather than states without the
failed/ready split — a half-informed list invites resubmitting HGs whose last attempt is unknown).
The stages panel shows the opened group's counts (the overview row), not the global ones. `esc` returns to the overview (cursor kept).
Everything else — filters, selection, resubmit, log — is unchanged.

Four panels:

- **Stages** (top left): stage, done, running, ready, blocked, total, coloured bar.
- **HGs** (top right): HGs of the highlighted stage; `f` cycles the filter
  failed → ready → running → blocked → done. Columns: HG, nseq, last reason, requested/used.
- **Arrays** (bottom left): latest 10 submissions with a progress bar.
- **Detail** (bottom right): the highlighted HG's nseq, per-stage state, last attempt, log path.

Keys: `↑↓` move · `tab` panel · `space` select HG · `a` select all in the list ·
`r` resubmit selection · `l` show the last 200 lines of the last attempt's .err/.out in a pop-up (no `less`: suspending the app needs Textual ≥ 0.48, unverified on the cluster) ·
`R` refresh now · `q` quit.

### Resubmit flow (`r`)

1. Dialog: one row per resource group of the selection, pre-filled with `bump()`
   (e.g. `12 HGs · OOM · 2048M → 4096M · 30m`); **mem and time are editable** per row.
2. `enter` → dry run via `plan_submit` + `run_submit(dry_run=True)`: arrays, HG counts, skipped
   (already queued / without inputs), validation errors.
3. `y` → `run_submit(dry_run=False)`; dialog shows submitted job ids. `esc` at any step →
   nothing submitted.

### Refresh

Background worker every 30 s (and on `R`); the UI never blocks on `squeue`/`sacct`.
Header shows the last refresh time. Each refresh computes the expected HG set **once** and passes
it to every consumer (measured 09/10/2026 on v3: `core.expected` 1.2 s, called 3–4× per refresh;
whole HG-view refresh 7–10 s).

## Error handling

- No `squeue`/`sacct`: yellow banner "running/failed states unavailable"; counts shown without
  them (same as `status` today).
- Submit validation errors (unknown ids, missing inputs): shown verbatim in the dialog, nothing
  submitted.
- `sbatch` failing part-way: dialog lists submitted and not-submitted arrays (same information
  `submit` prints today).
- Textual missing: `phylo tui` exits 1 with the install hint; other commands unaffected.

## Testing

- Existing 118 tests unchanged, all passing (CLI output/exit codes).
- `test_model.py`: `stage_rows` equals what `status` prints for the fixture; `hg_rows` states incl.
  failed; `bump()` for OOM / TIMEOUT / FAILED; `core.group` per-HG overrides split arrays.
- `test_tui.py` (skipped without Textual): Textual `App.run_test()` pilot — load, filter to
  failed, select, `r`, edit mem, dry run, `y` → fake `sbatch` receives the bumped resources;
  `esc` submits nothing.
- Both Pythons: mambaforge python3 and the 3.9 venv.

## Out of scope

Stage chaining (`--after`), editing config params from the TUI, Nextflow launch from the TUI.
