# Neo4j 5.26 — cross-system reference only

RPT-G is not integrated into Neo4j (its Cypher runtime has no planner hook comparable to the semi-mask
or predicate-transfer optimizers; a procedure-based plugin is a possible later item). The server is
used only to put the Q-GEN workload numbers next to a third engine (plan §8.11).

Install: `ext/neo4j` = neo4j-community-5.26.0, OpenJDK 21 from the conda env `neo4j`.
`neo4j.conf` in this directory is the appended configuration: Bolt on 127.0.0.1:7697, HTTP 7484, auth
off, 8 GB heap, 8 GB page cache, `db.transaction.timeout=10s`, default database `dblp`.

```
export JAVA_HOME=~/miniconda3/envs/neo4j PATH=~/miniconda3/envs/neo4j/bin:$PATH
~/miniconda3/bin/python scripts/neo4j_export_csv.py data/bin/dblp data/neo4j_csv/dblp
cd ext/neo4j
bin/neo4j-admin database import full --nodes=V=$PWD/../../data/neo4j_csv/dblp/V.csv \
    --relationships=E=$PWD/../../data/neo4j_csv/dblp/E.csv --overwrite-destination dblp
bin/neo4j start
# then, through the driver: CREATE RANGE INDEX v_pu IF NOT EXISTS FOR (v:V) ON (v.pu)  (same for pd, label)
```

Run (`neo4j` Python driver in the same conda env):

```
~/miniconda3/envs/neo4j/bin/python scripts/run_neo4j.py --database dblp --queries queries/test_small.txt \
    --reps 2 --warm 1 --timeout 10 --out results/neo4j_test.csv
scripts/run_neo4j_sharded.sh dblp results/shards_neo4j_dblp results/neo4j_dblp_qgen.csv --reps 2 --warm 1 --timeout 10
```

The runner emits one `MATCH` clause per pattern edge (Neo4j's relationship-uniqueness rule is per
clause), so counts are homomorphism counts like everywhere else; all 8 smoke-test counts match. It
records the client wall time and the server-side time from the result summary, reconnects with backoff
when the server stalls after huge results, and `--resume` skips queries already in the output file.
Community edition executes a query single-threaded; expect many 10 s timeouts on Q-GEN.
