# phylocli: step1 (`search`, `cluster`) as family-level stages

Date: 04/10/2026 · Status: design approved in chat (option B), awaiting spec review
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
- Duplicate family ids in the genefam file are an error listing them (currently `slc.SLC44`).
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
- Tool preflight: search -> `hmmsearch` (+ python imports); cluster -> `samtools` (+ python
  imports, whatever `main.py cluster` needs, e.g. mcl/diamond — read helper/functions.py).

## Testing
Unit tests on fixtures (family parsing incl. trailing tab + duplicates; done/ready/no-hits;
publish order; submit/missing/status for family ids), both Python 3.9 venv and system python.
Real check (local, ≤ 4 threads, measure `top` first): run `search` then `cluster` for ONE small
new SLC family into a scratch OUTDIR via `runner.run_one`, compare HG count with nothing (new);
and re-run search+cluster for one EXISTING small family into scratch and diff the HG membership
against v3's `results/clusters/<id>_cluster.tsv`. `nextflow run step1.nf -preview` after the switch.

## Out of scope
Fixing the duplicate SLC44 row or the trailing tabs in the genefam file (reported, not edited).
