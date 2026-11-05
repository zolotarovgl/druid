# druid

Gene-family phylogenies on the CRG cluster (search → cluster → align → tree → GeneRax → POSSVM),
one SLURM job array per stage. Full reference: [docs/reference.md](docs/reference.md).

## Test run (CRG cluster, lab members)

```bash
git clone --recurse-submodules https://github.com/zolotarovgl/druid
conda activate /no_backup/asebe/gzolotarov/druid-env-test/env
module load OpenMPI
./druid/bin/druid doctor                                   # checks tools and the environment
./druid/bin/druid init /no_backup/<lab>/$USER/druid_test   # new project; opens Setup
```

In Setup (`tab` moves, `enter` selects, `esc` back):

1. **Project**: type a `job_prefix` (e.g. `test`), `enter`.
2. **Species**: type `Mlei Hsap Nvec`, `enter`.
3. **Analyses**: switch GeneRax and origins off.
4. **Families**: tick one or two small families (`space`).
5. `P` prepares, then `S` → `enter` (dry run) → `y` submits step 1.

Follow progress with `./druid/bin/druid --project /no_backup/<lab>/$USER/druid_test tui`.
