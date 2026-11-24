# Consensus species tree: build inputs

`tools/build_species_tree.py` merges three species trees into druid's default tree
(spec: `docs/superpowers/specs/2026-11-24-consensus-species-tree-design.md`).

| file | what | origin | md5 |
|---|---|---|---|
| `inputs/latest_20251014.newick` | `latest` Holozoa tree (178 tips), the backbone | species_tree folder `latest.newick` (cluster), as of 24/11/2026 | 205631b2efb8f8e17a3a94cf858fae70 |
| `inputs/v3_origin.newick` | Phylogenies_v3 origin tree (59 tips); its ctenophore subtree replaces latest's | `Phylogenies_v3/data/species_tree.newick`, = previous `druid/data/species_tree.newick` | 95521216cef1137d35a9e95f515033c3 |
| `druid/data/species_tree.chromo94.newick` | 2026_chromo tree (94 tips), shipped, not copied here | `2026_chromo/phylohpc/data/species_tree.newick` | 5a8e45f5fc151b31897b525c3ba74a4c |
| `inputs/planarians.tsv` | `code<TAB>Latin name` of the planarian clade (Dugjap is named in `druid/data/genome_sources.tsv`) | hand-written | |

Rebuild: `python3 tools/build_species_tree.py --out-dir DIR` (writes `species_tree.newick` and
`species_tree.binary.newick`, prints the report). `--check DIR` writes nothing and exits 1 if DIR
differs from a fresh build.
