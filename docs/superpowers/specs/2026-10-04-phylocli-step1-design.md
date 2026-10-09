# phylocli: step1 (`search`, `cluster`) as family-level stages

Date: 04/10/2026 · Status: design approved in chat (option B), awaiting spec review ·
amended 08/10/2026 (small clusters not written; model.py data layer; TUI; resource pre-training as future)
Builds on: `2026-09-30-phylocli-design.md` (step2 stages) and the later additions
(`--ready` default / `--all`, `--fam`, `--per-fam`, `jobs`, `status HG` history, `--set`).

## Goal
New gene families are added to `data/gene_families_searchinfo.csv` (e.g. 18 SLC families,
04/10/2026). phylocli must run step1 for them — hmmsearch then clustering into HGs — with the
same commands, safety rules and status views as the step2 stages, without Nextflow.

## Units and ids
- Family id = `<pref>.<family>` where `family` = column 1 and `pref` = LAST column of the genefam
  row (exactly what `step1.nf` uses: `cols[0]`, `cols[-1]`), e.g. `slc.SLC25`. Blank lines skipped;
  trailing tabs tolerated (the file has rows with an 8th empty field: take the last NON-EMPTY field).
- Duplicate family ids in the genefam file are a **warning** naming them, never an error (amended
  09/10/2026, Grygoriy; currently `slc.SLC44` and `neu.Synapsin`): the `status`/`missing`
  summaries, the TUI banner and every family command (`missing search|cluster`,
  `submit search|cluster`, `status FAMILY`) print it and proceed. Each id counts once; the LAST row
  is the one used, as in `main.py hmmsearch` (keys rows by name, last row wins) and step1.nf.
- A family NAME listed under two prefixes (currently `CSD`: `rbp`, `tfs`) is a **warning** too
  (amended 09/10/2026, Grygoriy): `main.py hmmsearch` keys rows by name, so `rbp.CSD`'s hits are
  written as `tfs.CSD.*` and `rbp.CSD` is published empty ("no hits"), as step1.nf does.
  `search` keeps that result and prints a `WARNING` saying so; the summaries, the TUI banner and
  `submit search` print `warning: family name CSD is listed under 2 prefixes (rbp, tfs); hmmsearch
  keys rows by name, so rbp.CSD's hits are written as tfs.CSD.* and rbp.CSD looks like "no hits"`.
- HG ids (`<pref>.<family>.HGn`) remain the unit of the six step2 stages.

## Stages
| stage | unit | done when | ready when | inputs | publish to | marker (last) |
|---|---|---|---|---|---|---|
| search | family | `search/<id>.domains.fasta` exists | always (family row exists) | genefam file, infasta, pfam_db, hmm_dir | `results/search/` | `<id>.domains.fasta` (after `.domains.csv`, `.domains_ummerged.csv`, `.genes.list`) |
| cluster | family | `clusters/<id>_cluster.tsv` exists, OR the domains fasta exists and is empty ("no hits") | domains fasta exists and is non-empty | `search/<id>.domains.fasta` | `results/clusters/` | `<id>_cluster.tsv` (after all `<id>.HG*.fasta`) |

Stage scripts `phylocli/stages/search.sh` and `cluster.sh` = the `SEARCH` / `CLUSTER` script
bodies of v3 `step1.nf` moved verbatim (only Nextflow interpolations -> env vars / positional args,
as for step2). `step1.nf` is switched to call them; its family-skip logic and outputs are unchanged
(step1 decides completeness from published outputs, not the resume cache, so this costs no rerun).
Backup `step1.nf.bak-20261004` first.

Note: `search` reads the genefam row for its family from the genefam file given to hmmsearch
(`-g`), so the job must stage the CURRENT file; record it in the run's config copy.

**Small clusters are not written** (amended 08/10/2026, Grygoriy). `cluster.sh` writes
`<id>.HG<n>.fasta` only for HGs with ≥ `min_seqs` sequences AND ≥ `min_distinct` distinct
sequences (the same params and the same counting rules as `workflow/report_status.py`
`count_seqs` / `count_distinct`, so step1 and step2 can never disagree). `<id>_cluster.tsv` stays
COMPLETE — every HG and member, as MCL produced it — because it is the membership record
(`hg_meta.tsv` and reports read it); HG numbering is unchanged, so skipped HGs leave gaps.
The script prints `skipped <k> HGs below min_seqs/min_distinct` per family. Because the scripts
are shared, `step1.nf` CLUSTER gets the same behaviour; it reads `params.min_seqs` /
`params.min_distinct` (already in `nextflow.config`). Existing `results/clusters/` is not touched;
the 1,579 small HGs already moved to `results/_removed_small_hgs/` stay there.

## Config (`phylocli/config.yaml`, values from v3 `nextflow.config` + the 24/09/2026 step1 run)
`genefam_info: data/gene_families_searchinfo.csv`, `infasta: data/input.fasta`,
`pfam_db: /users/asebe/xgraubove/data/pfam/Pfam-A.hmm`, `hmm_dir: null`, `domain_expand: 30`,
`s1_ncpu: 4`, `s2_ncpu: 4`, `max_n: 2000`, `s2_inflation: 1.1` (all under `params:`, so `--set`
works for them).

## Resources (step1 attempt 1)
search: cpus `s1_ncpu`, 500 MB, 5 min. cluster: cpus `s2_ncpu`, 300 MB, 10 min. No resources.tsv
rows (family ids). `--mem/--time/--cpus` overrides apply as for HG stages.

## CLI behaviour
- `STAGES` order: `search, cluster, align, tree, possvm_prev, generax, gxsup, possvm`.
- `missing` (no stage): bars for search/cluster counted in families, then a blank line, then the
  HG stages. cluster row adds a "no hits" count.
- `missing search|cluster [-f PREFIX] [--all]`: family ids. `--per-fam` is an error for these
  stages (each row is already a family).
- `submit search|cluster` with `--missing`, `--ids`, explicit family ids, `-f`, `-n`, `--set`,
  `--mem/--time/--cpus`, `--all` — same rules: output exists -> error; unknown id -> error;
  without `--all`, not-ready and already-queued are skipped with a note.
- `status <family id>`: rows for search and cluster with latest attempt (Nextflow processes
  `SEARCH`/`CLUSTER`, tag `<pref>.<family>`, + phylocli runs), like `status <HG>`.
- `jobs`: unchanged (works on run dirs; family ids in ids files).
- **Data layer** (amended 08/10/2026): since the TUI work, counts and rows live in
  `phylocli/model.py`. `stage_rows` gains the two family stages, counted in families (`total` =
  number of families), plus the cluster "no hits" count; `hg_rows(cfg, stage)` returns family
  rows for `search`/`cluster` (same `HGRow` shape, `hg` = family id) so the CLI and the TUI
  share one code path. `select`/`plan` accept family ids for these stages.
- **Overview separates step1 from step2** (amended 09/10/2026): search/cluster columns sit under a
  `step1 · families` header, the HG stages under `step2 · HGs`, with a `│` separator between them.
- **TUI** (amended 08/10/2026): `search` and `cluster` appear first in the stages panel; the
  list panel shows families for them (filters, select, resubmit, log work unchanged); the detail
  panel shows the family's two stages and its HG count.
- Tool preflight: search -> `hmmsearch` (+ python imports); cluster -> `samtools` (+ python
  imports, whatever `main.py cluster` needs, e.g. mcl/diamond — read helper/functions.py).

## Testing
Unit tests on fixtures (family parsing incl. trailing tab + duplicates; done/ready/no-hits;
publish order; submit/missing/status for family ids), both Python 3.9 venv and system python.
Real check (local, ≤ 4 threads, measure `top` first): run `search` then `cluster` for ONE small
new SLC family into a scratch OUTDIR via `runner.run_one`, compare HG count with nothing (new);
and re-run search+cluster for one EXISTING small family into scratch and diff the HG membership
against v3's `results/clusters/<id>_cluster.tsv`. `nextflow run step1.nf -preview` after the switch.

Also test: `cluster.sh` on a fixture with HGs of 1, 4 and 5 seqs and one 5-seq HG of identical
sequences → only the passing HG's FASTA is written, `_cluster.tsv` lists all four, and
`expected_hgs` / `missing align` agree with the files on disk.

## Out of scope
Fixing the duplicate SLC44 row or the trailing tabs in the genefam file (reported, not edited).

## Future (separate design, after step1)
**Resource pre-training** as an optional first step (Grygoriy, 08/10/2026): subsample existing HGs
across the size range, run each stage on them with the current pipeline setup, fit per-stage
scaling of memory/time on HG size, and use the fit so step2 submissions request informed
resources. Builds on `workflow/train.R` (quantile regression on Nextflow traces) and
`workflow/predict_resources.py`; must also learn from phylocli runs.
