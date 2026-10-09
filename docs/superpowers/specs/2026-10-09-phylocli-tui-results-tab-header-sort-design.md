# phylocli TUI: Results tab on the first screen + header sorting — design

Date: 09/10/2026 · Branch: `phylocli` · Status: agreed in chat (Grygoriy), spec awaiting review
Builds on: `2026-10-08-phylocli-tui-design.md` (overview, HG view),
`2026-10-09-phylocli-tui-og-explorer-sort-design.md` (Results window, overview `s`/`h`).

## Part A — Jobs / Results tabs on the first screen

Grygoriy, 09/10/2026: "the results should be indicated in the Entry page so the user can toggle
between the jobs and results with tab."

- The first screen gets two tabs: **Jobs** (today's overview: stage bars per group) and
  **Results** (POSSVM output per group). `tab` / `shift+tab` switch tab while the first screen is
  shown (the overview has a single table, so `tab` is otherwise unused there). The active tab
  name is highlighted in the header line: `[Jobs] │ Results` / `Jobs │ [Results]`.
- **Results tab rows**: `ALL`, then one row per category, or per family with `f` (`c` back) — the
  same grouping and the same `by` state as Jobs (switching tab keeps it).
- **Columns**: group · HGs (expected) · HGs with output (the source has a non-empty
  `*.ortholog_groups.csv`) · OGs · genes · OGs with support 0 (`⚠`). **No focal-species column**
  (Grygoriy, 09/10/2026: "do not add focal species genes for now").
- **Source**: `p` toggles `possvm` ↔ `possvm_prev` (same switch as the Results window; the tab
  title shows it).
- `s` / `h` work on the Results tab as on Jobs: `s` sorts by the highlighted column (numbers
  descending, group by name; again → reverse); `h` hides rows whose highlighted count is 0. `ALL`
  stays pinned.
- `enter` (and `o`) on a row opens the existing Results window for that group (HG list → OGs →
  members → species); `esc` comes back to the Results tab, cursor kept.
- **Data**: one background read of every HG's ortholog-group file for the source
  (`model.group_ogs` over all expected HGs, with the existing progress/cancel hooks; ~10 s for
  ~1,900 files measured 09/10/2026), aggregated per group in memory; cached until `R` or `p`; the
  tab shows `loading k/n…` meanwhile. Opening the Results window for a group then reuses the
  cached per-HG data (no second read). Switching tabs never re-reads.
- The Jobs tab is unchanged.

## Part B — header sorting in every table

Grygoriy, 09/10/2026: "when tables are presented, allow going into header with arrows so the
sorted column is highlighted."

Applies to: the Jobs and Results tabs, pane `2 HGs`, and the Results window's `Results`, `OGs`,
`members` panes. (Not `1 Stages` — its rows are the pipeline order — and not `3 Arrays` — newest
first by design.)

- `↑` on the first row moves the cursor into the **header**; `←` / `→` move between column
  names; the header cell under the header cursor is shown reversed; `↓` returns to the rows
  (cursor on the first row).
- `enter` or `s` in the header sorts the table by that column; again → reverse. Numbers sort
  descending first, text ascending first.
- The sorted column's header always shows `▲` / `▼` after its name, in and out of header mode,
  so it is visible what a table is sorted by. One sorted column per table at a time.
- The sort is per table, kept across refreshes and regrouping, and is pure in memory.
- In the Jobs/Results tabs, header sorting and the existing `s` on a cell are the same sort (the
  cell `s` sorts by the cell's column).
- Pinned rows stay pinned (`ALL` in the first-screen tabs).
- Stage columns of the Jobs tab sort by their failed+ready count (as `s` does today); the `│`
  separator column cannot be selected in header mode (skipped by `←`/`→`).

## Error handling
- Results tab read errors per HG are counted, not fatal: a footer `n HGs unreadable` and the
  per-HG error shown in the Results window, as today.
- Header mode never captures typing: the members `/` filter box still takes all keys.

## Testing
- Results tab: `tab` switches; rows = the same groups as Jobs; counts on a fixture equal the sum of
  the Results window's per-HG numbers; `p` switches source and recomputes; `enter` opens the
  Results window for the row and `esc` returns to the tab; one read only (counting `group_ogs`).
- Header sorting: `↑` from row 0 enters header mode; `←→` move (skipping `│`); `enter`/`s` sorts
  and toggles `▲`/`▼`; `↓` leaves; sort kept across refresh; numeric vs text order; `ALL` pinned;
  no file or SLURM access on these keys.

## Out of scope
Warnings window (TODOs.md 4), focal-species columns, chains.
