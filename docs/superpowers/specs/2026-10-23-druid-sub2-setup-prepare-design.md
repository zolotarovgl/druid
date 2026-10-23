# druid sub-project 2 — setup tab + `prepare` (design)

Grygoriy, 23/10/2026. Parent spec: `docs/superpowers/specs/2026-10-14-druid-standalone-design.md`
(sub-project 2 row). Sub-project 1 (repo, `init`/`adopt`/`doctor`, write boundary) is done at `71132b7`.

## Intent

After `druid init <dir>`, a user sets a project up entirely from the TUI: picks where the proteomes
come from, ticks the species, decides whether GeneRax / origin analysis will run (and only then
deals with a species tree), picks the search type and the families, and runs `prepare`, which
builds the project's inputs. What actually changes between projects is **the species sampling and
the family sampling** (Grygoriy); the run parameters almost never change, so they get no form.

Launching the pipeline is sub-project 3 (`druid run`). After this sub-project, a project is
prepared and runnable stage by stage with the existing commands.

## Goals

1. A **Setup tab** in the TUI, next to Overview / Results (Grygoriy chose layout B, 23/10/2026):
   a left column of sections, the active section on the right, and a status line naming what
   still blocks `prepare`.
2. **Two proteome sources**: Xavi's database (default) and custom proteomes.
3. **Species**: one tickable list — prefix, Latin name, taxonomy string — with a filter.
4. **Optional analyses**: two switches, GeneRax and origins. A species tree is needed only if one is on.
5. **Tree placement** of ticked species missing from the tree, in the embedded treeview.
6. **Search type** choice: gene family file, custom HMMs, custom query sequences (the last shown, not built).
7. **Families**: the library, all ticked, untick to drop.
8. **`druid prepare`** (CLI and a TUI key): builds `data/input.fasta`, the project trees and
   `species_info.tsv`, then locks the species.

## Non-goals (this sub-project)

- Proteomes with no taxonomy row (159–183 of 620 in Xavi's dir, 23/10/2026) — hidden, not handled.
- BLASTology-style custom query search — the option is visible and disabled ("not available yet").
- A config form. Run parameters stay hand-edited in `druid.yaml`.
- `druid run` / stage chaining (sub-project 3). Counts heatmap (sub-project 4).
- Changing the species of a project after its first launch.

## Anti-goals (a failure even if it works)

- **Any write outside the project directory** — above all into Xavi's proteome dir or the
  source file of a custom proteome. Parent spec "Write boundary" applies unchanged: every write
  goes through `druid.paths`.
- Silently producing an `input.fasta` whose headers do not start with `<prefix>_` — every later
  stage takes a gene's species from that prefix.
- Silently mixing results across a species change.
- Rebuilding `input.fasta` on an adopted project (`prepare: locked`, v3).

## Constraints

- Python 3.9, Textual >= 8.2, < 9 (the CRG `phylo` env); no new dependencies.
- The treeview is the vendored one (`druid/vendor/treeview`, embedded with `write_guard=paths.writable`).
- Every new write site passes the AST lint in `tests/test_write_boundary.py`.
- Shipped data lives in `druid/data/` and is copied into the project by `init`, so a project stays
  frozen when druid updates.

## Decisions (Grygoriy, 23/10/2026, unless marked "my call")

### Source section

- **Xavi's database (default).** Proteomes: `/users/asebe/xgraubove/genomes/data`,
  `proteome_glob: "{sp}_long.pep.fasta"` (620 files on 23/10/2026). Names and taxonomy: **druid's
  own copy** of Xavi's `/users/asebe/xgraubove/genomes/genome_sources_2025-10-13.tsv`, shipped in
  `druid/data/` (Grygoriy: "we will hold our local copy of the table"; "use xavi's table as a
  starting example"). That file has no header; columns used: 1 prefix, 2 Latin name, 6 taxonomy
  string (comma-separated, e.g. `Metazoa, Ctenophora, Tentaculata, Lobata`). 476 rows, 437 of which
  have a proteome in the dir.
- **Custom proteomes.** The user supplies a proteome directory (+ glob), a taxonomy table in the
  same column layout, and — only if GeneRax or origins is on — a species tree. Every file found
  must have a table row; a file without one is listed as a blocker (not hidden), since the user
  chose this directory.
- **One project may mix both** (Grygoriy, 23/10/2026: e.g. Xavi's set plus one or two of the
  user's own proteomes). The source is therefore **per species**: the project lists any number of
  sources (Xavi's is one entry, on by default; each custom one is a dir + glob + taxonomy table),
  and each ticked species records which source it came from. A prefix offered by two sources is
  a blocker until the user picks one.
- All sources are read-only. The sources and each species' source are recorded in `druid.yaml`.

### Species section

- One list of every proteome that has a taxonomy row, across all sources: tick box, prefix,
  Latin name, taxonomy string, source. A filter box matches any column. Count line: `N ticked / M`.
- Proteomes with no row are not shown (Xavi route).
- The ticked list is written to `druid.yaml` `species:` (the key already exists, empty after `init`).
- **Locked after the first launch** (Grygoriy: "the species are fixed once the pipeline is
  launched"). Once locked, the section is read-only and says why.
- *My call — what "launched" means before sub-project 3 exists:* the lock is a stored flag
  (`species_locked: true` in `druid.yaml`), set by the first `druid submit` of any stage (and later
  by `druid run`). A project with existing attempts in `runs_dir` or a non-empty `outdir` is also
  treated as locked, so adopted v3 and pre-existing projects are covered without the flag.

### Analyses switches

- **GeneRax** (`params.run_generax`, already in the template) and **origins** (orthogroup origin
  from `ORIGIN_TREE`; today computed by the TUI Results tab, `model.og_origins`). Both optional.
- If both are off, the Tree section is skipped and no tree is required for `prepare`.
- *My call:* origins gets a new key `params.origins: true|false`; when false the Results tab does
  not load `ORIGIN_TREE` and shows no origin column.

### Tree section (only when a switch is on)

- Starts from the shipped curated tree (Xavi route; 59 tips, the v3 species) or the user's tree
  (custom route), pruned to the ticked species.
- Lists the ticked species **missing from the tree**. The user picks one, then selects a node in
  the embedded treeview: **the new species becomes the sister of the selected node**, whether that
  node is a tip or an internal node (Grygoriy). The tree therefore stays binary (GeneRax needs it).
- *My call:* the user clicks the **binary** `SPECIES_TREE`. The same placement is carried to
  `ORIGIN_TREE` (polytomies kept) by tip set: the selected node stands for the set of tips under
  it; if `ORIGIN_TREE` has a clade with exactly that set, the new species becomes its sister;
  otherwise (the set sits inside a polytomy) the species is added as one more child of the
  smallest `ORIGIN_TREE` node containing the set. Both trees are written only into the project's `data/`.
- *My call — custom route trees:* the user supplies one tree, used for both. If GeneRax is on and
  that tree has polytomies, it is a blocker (druid does not resolve them).
- Blocker while any ticked species is still missing.

### Search section

- Three choices: **gene family file** (the library or the user's own CSV, Pfam names),
  **custom HMMs** (`params.hmm_dir`), **custom query sequences** (BLASTology-like) — shown,
  disabled, "not available yet".
- **Custom HMMs** (Grygoriy, 23/10/2026): one family per `.hmm` file, its CSV row filled with
  **default settings** (CSV columns 3–7, defaults = the library's most common values, e.g.
  `1.1 3 GA`; the builder confirms each column's meaning from `search.sh` / `main.py hmmsearch`
  before labelling it in the UI), and the user **reviews and edits those
  settings interactively** in the Families section before `prepare`. The edited rows go to
  `data/families.csv` like any other family.

### Families section

- The shipped library `druid/data/families_library.csv` (356 rows), **all ticked**; the user
  unticks what to drop (Grygoriy: "I usually copy the whole family file and then filter it").
  Filter box as in Species. The ticked rows are written to the project's `data/families.csv`
  (`params.genefam_info`), which stays hand-editable.
- Families can be added after launch; only the new ones run (existing behaviour of the stages).

### Config section

- *My call:* no form. Shows `druid.yaml`; a key opens it in `$EDITOR` (fallback `nano`) and
  re-validates with `config_from_raw` on return, showing any `ERROR:` in the status line.

### `druid prepare`

- CLI `druid prepare` and a TUI key on the Setup tab; the TUI runs the same code.
- Refuses when `prepare: locked`, when the species are locked, or when any blocker remains.
- Writes, all inside the project via `druid.paths`:
  - `data/input.fasta`: the ticked proteomes concatenated in `species:` order. For a proteome
    whose headers do not start with `<prefix>_`, prepare **adds the prefix to that species'
    headers in `input.fasta` only — the source file is never touched** (Grygoriy). Headers that
    already carry it are left as they are (Xavi's do: `>Mlei_v05_G000001.t0`).
  - `data/species_tree.binary.newick`, `data/species_tree.newick` (when a switch is on).
  - `data/species_info.tsv` for the ticked species. *My call — column 3 (the clade the Results
    tab colours by):* the shipped `species_info.tsv` row when the species has one (all 59 shipped
    tips do); otherwise the first element of the taxonomy string that is already a column-3 value
    in the shipped file (e.g. `Chordata`, `Ctenophora`, `Porifera`); otherwise `Other`.
- Writes atomically (temp file in `.druid/tmp`, then replace), so an interrupted prepare leaves
  the previous files.
- Re-running prepare before launch rebuilds everything from scratch.
- **Species lock:** set at the first launch (sub-project 3 sets it; this sub-project provides the
  lock state and refuses changes once set).

## Left to the builder

- Widget choices inside each section, key bindings (consistent with the existing TUI), how the
  blocker line is computed and refreshed.
- How the sources, per-species source and the lock are recorded in `druid.yaml` (new keys
  allowed; old projects and adopted v3 must still load). *My call:* the TUI rewrites only the
  top-level keys it owns (`sources`, `species`, `species_locked`, the two switches) with a small
  text-level writer, so the template's comments survive; no `yaml.safe_dump` of the whole file
  and no new dependency.
- Tests: per section and for prepare, including a proteome dir made read-only and a custom
  proteome without prefixes (source file byte-identical afterwards).
