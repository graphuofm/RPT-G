# RPT-G in Kùzu 0.11.3

Source tree: `ext/kuzu` (tag `v0.11.3`, branch `rptg`, patch applied but uncommitted).
`rptg_stage_g.patch` is the current integration (24 files, ~2,600 lines: stage E plus the counting
shortcut); stages a–e are kept as history and are superseded, and `rptg_stage_f.patch` is the LadybugDB-only
neighbour-mask stage (see `docs/kuzu_integration.md` for what each stage added and its numbers).

## What the patch adds

- `src/optimizer/rptg_transfer_optimizer.{cpp,h}` — replaces Kùzu's `HashJoinSIPOptimizer` when
  `rptg_mode > 0`: serializes the plan into SCAN / EXTEND / JOIN steps, decides one transfer per join
  edge (push direction along the host join order), prunes transfers with no consumer, pre-screens with
  zone-map (min/max) selectivity estimates.
- `src/processor/operator/rptg_transfer_sink.{cpp,h}` — `RPTGTransferSink` (materializes B_y ← B_y ∩
  N(B_x) into a semi mask) and `RPTGController` (run-time budget: exact cost from degree sums vs estimated
  benefit, transfers chained in plan order; skipped transfers cost nothing).
- `src/include/common/rptg_budget_model.h` — the shared work/survival/benefit model
  (`planWork`, `survival`, `simulate`, `decide`, `prescreen`).
- `src/storage/rptg_degree_cache.{cpp,h}` — per-vertex out/in degree arrays read once from the CSR
  headers (exact Σdeg(B_x)).
- Modified: `mask.h` / `roaring_mask.h` / `semi_masker.{h,cpp}` / `map_semi_masker.cpp` (masks are
  intersected, marked `exact`, enabled on first write), `node_group.cpp` (`applySemiMaskRowFilter`: the
  scan honours an exact mask per row instead of per 2,048-row vector), `plan_mapper.cpp`, `logical_plan.h`,
  `settings.h` / `db_config.cpp` / `client_config.h` (settings below), `optimizer.cpp`.

Settings (`CALL name=value;`):

| setting | default | meaning |
|---------|---------|---------|
| `rptg_mode` | 0 | 0 = stock Kùzu; 1 = RPT-G transfers, all executed; 2 = transfers subject to the budget |
| `rptg_beta` | 1.0 | run a transfer iff exact cost ≤ β × estimated benefit (mode 2) |
| `rptg_pipeline_cost` | 10000 | fixed cost charged per extra pipeline (rows-equivalent) |
| `rptg_prescreen_slack` | 1.0 | slack factor of the plan-time pre-screen |
| `rptg_transfer_unit_cost` | 0.5 | measured cost per adjacency entry relative to a scanned row |

`RPTG_DEBUG=1` in the environment prints every decision (estimated vs exact sizes, cost, benefit).

`ext/kuzu_dev` is the same tree plus `CALL exact_semi_mask=true` (`SemiMask::exactByDefault`), which
makes Kùzu's own semi-mask row-exact too — the fair host baseline "KSX".

## Counting shortcut (stage G, 2026-10-14)

`rptg_count` (default true, with `rptg_mode >= 1`): a bare `MATCH ... RETURN count(*)` over a tree pattern is
answered by the shared core's counting pass (`third_party/rptg -> prototype/src`, `rptg_c.cpp` compiled into
`kuzu_optimizer`). `rptgTryCount` in `rptg_transfer_optimizer.cpp` recognizes the shape (projections above one
`COUNT_STAR` aggregate without keys), loads the adjacency index of the rel table once per process through a side
connection (`MATCH (a)-[]->(b) RETURN offset(id(a)), offset(id(b))`), decides from the zone-map estimates
(`rptg_count_decide`: count when the counting cost is at most `rptg_count_host` (8) times the enumeration
estimate, or below `rptg_count_floor` (2e6) entries), materializes the predicate sets through side queries
(`MATCH (v:V) WHERE <filter chain> RETURN offset(id(v))`, with the bound filter rendered back to Cypher:
comparisons, AND/OR/NOT, properties, literals, casts dropped), counts (`rptg_count`), and replaces the plan by a
projection of the constant over a dummy scan. Primary-key lookups, multi-table patterns, cyclic patterns, and
filters the renderer does not cover are left to the transfer path. The settings are per connection, so a runner
that interleaves configurations on one connection must set `rptg_count` in every configuration. Run:
`scripts/kuzu_count_300.sh` (KNO / KR2 with `rptg_count=false` / KRC with `rptg_count=true`, 300-query DBLP
sample, 1 warm-up + 3 reps, 8 threads, 10 s, 2 shards) -> `results/kuzu_count_dblp300.csv`; the adjacency index
(672 ms) is loaded once per process, inside the first query's warm-up run. Result (2026-10-14): 282 queries
evaluated, geo 4.65 (transfers alone 2.04), 87.7 -> 6.4 s (268 -> 9 s with the 18 baseline failures at 10 s, all of
which finish), < 0.8x 3.5% against a noise floor of 7.1%, counts identical to KNO on every query
(`docs/kuzu_integration.md`, stage G).

## Build

```
conda activate rptg-build            # GCC 13, cmake, ninja
cd ext/kuzu && git checkout v0.11.3 && git apply ../../hosts/kuzu/rptg_stage_g.patch
ln -s ../../../prototype/src third_party/rptg   # the shared core, compiled into kuzu_optimizer
make python NUM_THREADS=28           # -> tools/python_api/build (module `kuzu`)
```

## Load and run

```
PY=~/miniconda3/envs/rptg-build/bin/python
export PYTHONPATH=ext/kuzu/tools/python_api/build
$PY scripts/kuzu_load.py data/bin/dblp data/kuzu/dblp.kz        # V(id, pu, pd, label), E(FROM V TO V)
$PY scripts/run_kuzu.py --db data/kuzu/dblp.kz --queries queries/test_small.txt \
    --configs KNO:0:0,KSM:1:0,KR2:0:2:1.0 --reps 3 --warm 1 --threads 8 --timeout 10 --buffer-gb 8
KUZU_PY=$PY scripts/run_kuzu_sharded.sh data/kuzu/dblp.kz queries/qgen_dblp.txt results/kuzu_dblp_3way_e.csv 2 \
    --configs KNO:0:0,KSM:1:0,KR2:0:2:1.0 --reps 3 --warm 1 --threads 8 --timeout 10
```

A config is `NAME:semi_mask:rptg_mode[:beta[:exact_semi_mask]]`; `exact_semi_mask=1` needs the
`kuzu_dev` build (`KSX:1:0:1.0:1`). Configs are interleaved rep-major. `run_kuzu.py` runs as a
supervisor that restarts its worker (`--worker-start`) after a crash or a buffer-manager error and
resumes from the `.progress` file. Keep `--buffer-gb` explicit: Kùzu's default buffer pool is 80% of
RAM per process.

## Results to report (Q-GEN, 8 threads, median of 3 interleaved reps, against no mask in the same run)

| graph | config | speedup < 0.8× | < 0.5× | geomean speedup | total time | file |
|-------|--------|---------------:|-------:|----------------:|-----------:|------|
| DBLP (4,693 evaluated) | Kùzu semi-mask (KSM) | 17.3% | 5.1% | 1.07 | 1,210 s | `kuzu_dblp_3way_e.csv` |
| | RPT-G (KR2, β = 1) | 4.6% | 0.0% | 1.92 | 688 s | (no mask: 1,072 s) |
| DBLP (4,668, separate run) | Kùzu semi-mask, row-exact masks (KSX) | 15.7% | 4.8% | 1.24 | 1,318 s | `kuzu_dblp_ksx.csv` (no mask: 1,207 s) |
| LiveJournal (3,746) | Kùzu semi-mask (KSM) | 29.5% | 15.1% | 0.86 | 4,415 s | `kuzu_lj_3way_e.csv` |
| | RPT-G (KR2, β = 1) | 4.5% | 0.4% | 2.19 | 1,902 s | (no mask: 3,693 s) |

Analyse with `scripts/analyze_host.py results/<file>.csv --meta queries/qgen_<graph>.txt.meta.csv`.
