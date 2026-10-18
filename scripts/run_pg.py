#!/usr/bin/env python
"""Run an RPT-G query file on PostgreSQL (scripts/pg19_ctl.sh cluster, database from scripts/pg19_load.py).

Every query is translated into the same SQL COUNT(*) self-join as the DuckDB runs (`to_sql` from
scripts/run_duckdb.py: one E copy per pattern edge, one V copy per predicate vertex, homomorphism
semantics). PostgreSQL resolves `real_col < 0.001` to float4 < float8 (float48lt), i.e. the float32
column is compared as a double against the double literal, as in DuckDB.

Configurations (--configs NAME:GUC=val;GUC=val,NAME2:...) each get their own session with the GUCs set
once (SELECT set_config(...)); they are interleaved rep-major per query: warm-up rep(s), then rep 0 of
every config, rep 1 of every config, ... A configuration that fails (statement_timeout, error) is not run
again for that query; the failure is recorded as its next rep (a warm-up failure becomes rep 0), the same
convention as the other host runners (scripts/analyze_host.py).

Time = client wall time around execute + fetchone (includes parse/plan and one unix-socket round trip,
like the DuckDB CLI `.timer`); prepared statements are disabled, so every run is planned afresh.
Output CSV: qid,method,order,rep,status,total_ms,count (status ok|timeout|error; timeouts are written
with total_ms = timeout and count -1). Rows of a query are written once the query is finished, so
--resume simply skips the qids already in the output file.

Sharding: --shard i/n runs every n-th query starting at i; or use
    RUNNER=scripts/run_pg.py scripts/run_kuzu_sharded.sh dblp queries/X.txt results/Y.csv N --configs ...
(that script passes --db/--queries/--out, which this runner accepts).

usage: run_pg.py --db dblp --queries queries/test_small.txt --configs "PGNO:,PG1:max_parallel_workers_per_gather=0"
"""
import argparse, os, sys, time
import psycopg
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_duckdb import parse, to_sql, to_sql_ordered  # noqa: E402  (same SQL text as the DuckDB runs)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_configs(s):
    """'PGNO:,PG1:max_parallel_workers_per_gather=0;enable_hashjoin=off' -> [(name, [(guc, val), ...])]"""
    out = []
    for c in s.split(','):
        name, _, rest = c.partition(':')
        gucs = []
        for kv in filter(None, rest.split(';')):
            k, v = kv.split('=', 1)
            gucs.append((k.strip(), v.strip()))
        out.append((name.strip(), gucs))
    return out


class Session:
    def __init__(self, a, name, gucs):
        self.a, self.name, self.gucs = a, name, gucs
        self.conn = None
        self.connect()

    def connect(self):
        a = self.a
        for attempt in range(6):
            try:
                self.conn = psycopg.connect(host=a.host, port=a.port, dbname=a.db, autocommit=True,
                                            prepare_threshold=None, application_name=f'run_pg:{self.name}')
                break
            except psycopg.OperationalError as e:
                print(f'connect {self.name} failed ({e}); retry in {5 * 2 ** attempt}s', file=sys.stderr)
                time.sleep(5 * 2 ** attempt)
        else:
            sys.exit('cannot connect to the server')
        self.conn.execute('SELECT set_config(%s, %s, false)', ('statement_timeout', f'{int(a.timeout * 1000)}ms'))
        for k, v in self.gucs:
            self.conn.execute('SELECT set_config(%s, %s, false)', (k, v))

    def run(self, sql_text):
        """-> (status, ms, count)"""
        t0 = time.perf_counter()
        try:
            cnt = self.conn.execute(sql_text).fetchone()[0]
            return 'ok', (time.perf_counter() - t0) * 1000, cnt
        except psycopg.errors.QueryCanceled:
            return 'timeout', self.a.timeout * 1000, -1
        except psycopg.OperationalError as e:   # connection lost (server crash / restart): reconnect
            print(f'{self.name}: connection error {e}; reconnecting', file=sys.stderr)
            try:
                self.conn.close()
            except Exception:  # noqa
                pass
            self.connect()
            return 'error', (time.perf_counter() - t0) * 1000, -1
        except psycopg.Error as e:
            print(f'{self.name}: error {type(e).__name__}: {str(e)[:300]}', file=sys.stderr)
            return 'error', (time.perf_counter() - t0) * 1000, -1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True)
    ap.add_argument('--queries', required=True)
    ap.add_argument('--out', default='-')
    ap.add_argument('--host', default=os.path.join(ROOT, 'data/pg19/cluster'), help='socket directory or host')
    ap.add_argument('--port', type=int, default=5439)
    ap.add_argument('--configs', default='PGNO:', help='NAME:GUC=val;GUC=val,NAME2:... (interleaved rep-major)')
    ap.add_argument('--timeout', type=float, default=10.0, help='statement_timeout in seconds')
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--warm', type=int, default=1)
    ap.add_argument('--resume', action='store_true', help='append to --out, skipping qids already recorded')
    ap.add_argument('--shard', default=None, help='i/n: run queries i, i+n, i+2n, ... of the file')
    ap.add_argument('--print-sql', action='store_true')
    ap.add_argument('--explain', action='store_true', help='print EXPLAIN (SUMMARY) per query and config, run nothing')
    ap.add_argument('--orders', default=None, help='CSV qid,order,orderstring (e.g. results/kuzu_dblp_robust.orders.csv): run '
                    'every query under each of its forced join orders (explicit JOINs; use join_collapse_limit=1 in the configs)')
    a = ap.parse_args()

    configs = parse_configs(a.configs)
    lines = [l.strip() for l in open(a.queries) if l.strip() and not l.startswith('#')]
    if a.shard:
        i, n = map(int, a.shard.split('/'))
        lines = lines[i::n]
    sessions = [Session(a, name, gucs) for name, gucs in configs]

    if a.explain:
        for line in lines:
            qid, k, edges, preds = parse(line)
            q = to_sql(k, edges, preds)
            print(f'-- q{qid}: {line}\n{q};')
            for s in sessions:
                plan = s.conn.execute('EXPLAIN (SUMMARY) ' + q).fetchall()
                print(f'-- {s.name}\n' + '\n'.join(r[0] for r in plan) + '\n')
        return

    done = set()
    if a.out != '-' and a.resume and os.path.exists(a.out):
        with open(a.out) as f:
            next(f, None)
            done = {int(l.split(',', 1)[0]) for l in f if l.strip()}
        out = open(a.out, 'a')
        print(f'resume: {len(done)} queries already in {a.out}', file=sys.stderr)
    else:
        out = sys.stdout if a.out == '-' else open(a.out, 'w')
        out.write('qid,method,order,rep,status,total_ms,count\n')
        out.flush()

    orders = None
    if a.orders:
        orders = {}
        for l in open(a.orders):
            q_, o_, ostr = l.strip().split(',', 2)
            orders.setdefault(int(q_), []).append((int(o_), ostr))
    t_start = time.time()
    todo = [l for l in lines if parse(l)[0] not in done and (orders is None or parse(l)[0] in orders)]
    for li, line in enumerate(todo):
        qid, k, edges, preds = parse(line)
        variants = [(0, to_sql(k, edges, preds))] if orders is None else \
            [(oi, to_sql_ordered(k, edges, preds, ostr)) for oi, ostr in orders[qid]]
        rows = []
        for oi, q in variants:
            if a.print_sql:
                print(qid, oi, q, file=sys.stderr)
            failed = set()
            for r in range(-a.warm, a.reps):
                for s in sessions:
                    if s.name in failed:
                        continue
                    status, ms, cnt = s.run(q)
                    if status != 'ok':
                        failed.add(s.name)
                        rows.append(f'{qid},{s.name},{oi},{max(r, 0)},{status},{ms:.4f},{cnt}')
                    elif r >= 0:
                        rows.append(f'{qid},{s.name},{oi},{r},{status},{ms:.4f},{cnt}')
        out.write('\n'.join(rows) + '\n')
        out.flush()
        if (li + 1) % 10 == 0 or li + 1 == len(todo):
            print(f'{li + 1}/{len(todo)} queries, {time.time() - t_start:.0f}s', file=sys.stderr, flush=True)
    if out is not sys.stdout:
        out.close()


if __name__ == '__main__':
    main()
