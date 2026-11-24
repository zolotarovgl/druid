# Consensus species tree (replaces the shipped v3 tree) — design

Approved by Grygoriy, 24/11/2026 (short design, chat).

## Intent

druid ships a 59-tip tree copied from Phylogenies_v3. Species off the base tree are hidden in Setup
and must be placed one by one, so a project with species beyond those 59 (e.g. the 2026_planaria
test with custom proteomes) starts with placement work. Grygoriy keeps a 178-tip hand-curated tree
(`/users/asebe/gzolotarov/species_tree/trees/latest.newick`, 14/10/2025, no citation, manual edit
log in that folder's README). Goal: one consensus tree, shipped as druid's default and also filed
in `species_tree/` (plotted) so it can be examined and used across projects.

"v3" is not kept as a name (Grygoriy: "it's meaningless").

## Goals

- Build a consensus pair (origin tree with polytomies + binary tree for GeneRax) from:
  - `latest.newick` (178 tips; md5 `205631b2efb8f8e17a3a94cf858fae70`) — the backbone;
  - druid's shipped v3 pair (59 tips; md5 origin `95521216cef1137d35a9e95f515033c3`, binary
    `4ae364378f9b95f162e880b76d1afd4c`);
  - druid's shipped `species_tree.chromo94.newick` (94 tips; md5 `5a8e45f5fc151b31897b525c3ba74a4c`);
  - Grygoriy's planarian clade `((((Smed,Spol),Djap),Gtig),Pnig)` (24/11/2026).
- Rebuildable: a script in the repo with its inputs frozen in the repo (md5 checked).
- Replace druid's shipped v3 pair with it; existing projects are unaffected (they keep the trees
  `init` copied; the adopted Phylogenies_v3 keeps its own).
- File it in `/users/asebe/gzolotarov/species_tree/` the way the other trees are, with a plot.

## Non-goals

- Several proteomes / several codes for one species (Grygoriy: "address … later on"). Known cases
  are reported by the build, not resolved: `Djap`/`Dugjap` (*Dugesia japonica*), `Bflo`/`Bflz`
  (*Branchiostoma floridae*), `HoiH11`/`HoiH04` (*Hoilungia* sp.), and four codes with no row in
  Xavi's taxonomy table (`Avas`, `Braflo`, `Clad`, `Halduj`).
- The chromo94 base and `@chromo` are unchanged.
- No branch lengths with meaning.

## Measured before design (24/11/2026)

On shared tips, `latest` vs v3 origin: 53 shared; v3-only `Aphvas Corcan Halcae Haloct Hydrsy
Turdoh`; the only conflicting clades are inside Ctenophora. `latest` vs chromo94: 74 shared, 20
chromo-only, 0 conflicts. Union with the planarians: 205 tips. `latest` has 5 polytomous nodes.

## Ctenophores

v3's ctenophore topology replaces `latest`'s. Source: Whelan et al. 2017, *Nat Ecol Evol*
1:1737–1746, doi:10.1038/s41559-017-0331-3, Fig. 3 — *Dryodora* sister to *Beroe* (99/1), Beroida
sister to Lobata + Cestida, Cydippida a grade (vault note
`2022_Mlei/Mlei/Whelan2017_ctenophore_phylogeny.md`). `latest` puts *Dryodora* inside the
cydippids, contradicted by that figure. *Lampea* (`Lampan`) is not in Whelan Fig. 3 and stays in
v3's cydippid polytomy (unresolved). Both trees carry the same 16 ctenophore tips.

## Build rules

1. Backbone `latest`; its ctenophore subtree (MRCA of `Eupdun`, `Mlei`) replaced by v3's origin
   ctenophore subtree.
2. Graft the tips missing from the backbone — v3-only, then chromo-only — each beside its sister
   in its source tree: the sister node's tips restricted to tips already placed; an exact clade →
   new sister (`sptree.add_sister` semantics); otherwise one more child of the smallest node
   containing them (`sptree.carry_to_origin` semantics). A tip whose sister set is still empty
   waits for the next pass; no progress in a pass is an error.
3. `(Smed,Dugjap)` → `((((Smed,Spol),(Djap,Dugjap)),Gtig),Pnig)`, keeping the old node's name
   (`Tricladida`). `Dugjap` beside `Djap` is Claude's call (same species, see Non-goals).
4. Internal names: v3's name where the node's tips restricted to v3's tips equal a v3 clade,
   else `latest`'s, else chromo94's, else unnamed. A name used twice gets `.2`, `.3` (v3 already
   has `Scleractinia.2`). Claude's call.
5. All branch lengths 1. Binary tree = the origin tree with every polytomy resolved
   deterministically, new branches length 0 (the v3 binary convention). Claude's call.
6. The build prints: tip count, polytomies resolved, every name renamed, and the codes sharing a
   Latin name (from `druid/data/genome_sources.tsv` + the planarian names) or with no row.

## Checks (tests)

- 205 unique tips; the binary tree is binary; both trees have the same tips.
- Pruned to v3's 59 tips, the origin tree has v3's origin topology (RF 0).
- Pruned to `latest`'s tips, the origin tree equals `latest` except inside Ctenophora and
  Tricladida.
- Pruned to chromo94's tips, no clade conflicts with chromo94 outside the ctenophores (chromo94
  shares `latest`'s ctenophore topology; measured 24/11/2026, v3 vs chromo94 conflict only there).
  The shipped chromo94 base itself stays as it is (Non-goals).
- Rebuilding from the frozen inputs reproduces the shipped files byte for byte.

## druid changes

- `druid/data/species_tree.newick` and `species_tree.binary.newick` = the consensus pair;
  `SOURCE` rewritten for them (inputs, md5s, date, the Whelan source).
- Species set `@v3` → `@all` (every tip of the project's base tree); `@chromo` unchanged.
- Setup › Tree: the base is labelled `default` (`default, 205 tips`); `tree_base()` returns
  `"default"`. Nothing is stored in `druid.yaml` for it, so existing projects need no migration.
- Tests asserting 59 / `@v3` updated; `docs/reference.md` updated.

## species_tree folder (cluster)

- `trees/holozoa_241126_prefixes.newick` (origin) and `trees/holozoa_241126_prefixes.binary.newick`.
- `figs/holozoa_241126_prefixes.pdf` from the folder's own `plot.R` (`Rscript plot.R in out`).
- `latest.newick` backed up as `latest.newick_backup_241126`, then overwritten with the origin
  tree (Claude's call).
- A `## 24.11.26` entry in its README: what was merged, the ctenophore source, the open duplicates.

## Left to the builder

Script location and CLI, frozen-input file names, test layout.
