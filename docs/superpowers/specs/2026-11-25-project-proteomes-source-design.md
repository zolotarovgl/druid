# Project `proteomes/` as an implicit source — design

Approved by Grygoriy, 25/11/2026 (short design, chat).

## Intent

Grygoriy's 2026_planaria test project (`/users/asebe/gzolotarov/projects/2026_planaria/Phylogenies`,
already initialised, `sources: []`) keeps its custom proteomes as `proteomes/<code>.pep` symlinks
inside the project. Today they need a Setup › Sources entry typed by hand. Goal: druid finds
`<project>/proteomes/` by itself; where Xavi's folder (the default source) has the same code, Xavi's
proteome is used (Grygoriy: "If there is a species that is already in Xavi's, it's proteome will
be used"; matching "by the code", not by Latin name).

## Design

- **Implicit source.** When `<project root>/proteomes/` is a directory, `setup_state.sources()`
  adds a source named `project` (after the default source, before the explicit `sources:`
  entries): `proteomes_dir = <root>/proteomes`, glob `{sp}.pep`. Nothing is written to
  `druid.yaml`; an already initialised project gets it with no migration.
- **Its taxonomy.** Rows from `proteomes/taxonomy.tsv` when that file exists, else none; any code
  without a row there falls back to the default source's table (the project's
  `data/genome_sources.tsv`). Same format as every taxonomy table (no header; col 1 code, col 2
  Latin name, col 6 lineage). Used everywhere a source's table is read (candidates and prepare's
  `species_info.tsv`).
- **Default source wins, by code.** A `project` file whose code is also a default-source
  candidate is not offered as a candidate. Setup › Sources lists it, e.g.
  `Smed: default source used (proteomes/Smed.pep not offered)`.
- **Ignored files.** Any entry in `proteomes/` that is not `<code>.pep` and not `taxonomy.tsv`
  is listed in Setup › Sources as ignored, never dropped silently.
- **Rowless.** A `project` file with no row in either table is reported exactly as an explicit
  custom source's is today (`no taxonomy row for project: <file>`, a prepare blocker).
- **Explicit sources unchanged.** `sources:` entries behave as now. The name `project` is
  reserved: Setup refuses it as a new source name even when `proteomes/` is absent. An explicit
  entry named `project` in `druid.yaml` (hand-written) wins and the implicit one is not added.
- **Same directory twice.** If an explicit source's `proteomes_dir` resolves to the same directory
  as `<root>/proteomes`, the implicit source is not added (no duplicate candidates).
- A species ticked from `project` is stored as `{sp: X, source: project}` like any custom source.

## Approaches

- Implicit read-time source (chosen): works for projects already initialised, stays in sync if
  `proteomes/` appears later, no config write.
- `druid init` writes a `sources:` entry when `proteomes/` exists: visible and editable, but misses
  the already-initialised 2026_planaria and any `proteomes/` created after init. Rejected.

## Non-goals

- Matching species across codes (`Djap` vs Xavi's `Dugjap`, both *Dugesia japonica*): by code only
  (Grygoriy, 25/11/2026). Several proteomes per species stays deferred.
- Other file names in `proteomes/` (`.fa`, `.fasta`): not picked up; listed as ignored.

## Left to the builder

Function names and where the shadowed/ignored lists are computed; test layout; the docs wording in
`docs/reference.md`.

## Build rulings (Claude, 25/11/2026; review findings and calls made while building)

- Built on main (no worktree), as the 24/11 plan was; Grygoriy pushes.
- The implicit source is also dropped when the *default* source's `proteomes_dir` is `proteomes/`
  (same files would be offered twice).
- An unreadable entry in `proteomes/` (e.g. a symlink into a directory that lost its permissions)
  is skipped and listed as `proteomes/<name>: unreadable (<Error>)`; Setup still opens. Explicit and
  default sources keep raising as before (a silent skip there would hide a broken folder).
- A species ticked from `project` that the default source later also offers stays listed in Species
  (so it can be unticked), is noted `<sp>: ticked from project, but the default source has it
  (untick it, tick the default one)`, and blocks prepare with `<sp>: ticked from project, but the
  default source has it`.
- Taxonomy line in Setup › Sources: `taxonomy <proteomes/taxonomy.tsv>[ (not found)] (fallback:
  <default table>)` (the plan's "(missing rows: …)" read wrongly).
- A `.pep` in `proteomes/` with no taxonomy row blocks prepare even when only default species are
  ticked (rowless, as for explicit sources). Remove the file or give it a row.
- A ticked `project` species whose `proteomes/` vanished: blocker `<sp>: source project: proteomes/
  not found`.
- Not changed: the prepare test's reliance on `_clade` → `Other`; the reference.md paragraph's
  position in the druid.yaml section.
