# RPT-G in LadybugDB (maintained Kùzu fork)

Source tree: `ext/ladybug` (v0.21.0-dev, upstream head `6953959`, branch `rptg`).
`rptg_stage_e.patch` is the Kùzu stage-E patch ported to the fork (25 files, ~1,750 lines). Differences
from the Kùzu version are mechanical: namespace `lbug`, `LBUG_API`, `storage::StorageManager::Get(*context)`,
`transaction::Transaction::Get(*context)`, `context->getDatabase()->getMemoryManager()`,
`getMergedColumnChunkStats()` without a transaction, `InMemChunkedCSRHeader` in the degree cache,
setting bodies in `src/main/settings.cpp`. LadybugDB's own semi masks are already row-exact (it made
the same fix as our `applySemiMaskRowFilter` upstream), so no `exact_semi_mask` switch is needed here.

## Build

```
conda activate rptg-build
cd ext/ladybug && git submodule update --init tools/python_api
git apply ../../hosts/ladybug/rptg_stage_e.patch
OPENSSL_ROOT_DIR=~/miniconda3/envs/rptg-build nice -n 19 make python NUM_THREADS=10   # module `ladybug` (_lbug.so)
```

## Load and run

`scripts/ladybug_load.py` and `scripts/run_ladybug.py` are the Kùzu scripts with `import ladybug as kuzu`;
same arguments and config strings as in `hosts/kuzu/README.md`.

```
export PYTHONPATH=ext/ladybug/tools/python_api/build
~/miniconda3/envs/rptg-build/bin/python scripts/ladybug_load.py data/bin/dblp data/ladybug/dblp.lb
~/miniconda3/envs/rptg-build/bin/python scripts/run_ladybug.py --db data/ladybug/dblp.lb \
    --queries queries/qgen_dblp_300.txt --out results/ladybug_dblp300.csv \
    --configs KNO:0:0,KSM:1:0,KR2:0:2:1.0 --reps 3 --warm 1 --threads 8 --timeout 10
```

All 8 smoke-test counts match. LadybugDB's planner chooses worse plans than Kùzu 0.11.3 on some
queries (test q8: 5.5 s vs 140 ms), so compare configurations within a host, never across the two.
