#!/usr/bin/env python
"""Drive a DuckDB CLI binary (vanilla or the RPT+ fork) over an RPT-G query file.

Builds a persistent database file from V.parquet / E.parquet once, then for every query spawns one
CLI process that runs the SQL (warm + reps) with `.timer on`, parsing the reported real times.
A process that exceeds the timeout is killed and the query is marked timeout.

With --configs name:bin:db:RPTG_MODE:RPTG_BETA,... several configurations are run interleaved per
query (one process each, warm + reps inside the process), so that drift of the shared machine's load
over the run hits every configuration alike; `method` in the CSV is the configuration name.
"""
import argparse, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from run_duckdb import parse, to_sql, to_sql_ordered  # noqa: E402

TIMER_RE = re.compile(r'Run Time \(s\): real ([0-9.]+)')


def ensure_db(binary, graph, db):
    if os.path.exists(db):
        return
    sql = (f"CREATE TABLE V AS SELECT * FROM '{graph}/V.parquet'; "
           f"CREATE TABLE E AS SELECT * FROM '{graph}/E.parquet';")
    subprocess.run([binary, db, '-c', sql], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bin', default=None)
    ap.add_argument('--graph', required=True)
    ap.add_argument('--db', default=None)
    ap.add_argument('--configs', default=None, help='name:bin:db:RPTG_MODE:RPTG_BETA[:VAR=value...],... (interleaved per query)')
    ap.add_argument('--queries', required=True)
    ap.add_argument('--out', default='-')
    ap.add_argument('--method', default='M1')
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--timeout', type=float, default=10.0)
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--warm', type=int, default=1)
    ap.add_argument('--orders', default=None, help='CSV qid,order,orderstring: run every query under each of its forced '
                    'join orders (explicit JOINs, join-order optimizer disabled)')
    a = ap.parse_args()

    if a.configs:
        configs = []
        for c in a.configs.split(','):
            fields = c.split(':')
            name, binary, db, mode, beta = fields[:5]
            env = dict(os.environ, RPTG_MODE=mode, RPTG_BETA=beta)
            for kv in fields[5:]:            # extra environment variables, e.g. RPTG_COUNT=0
                k, v = kv.split('=', 1)
                env[k] = v
            configs.append((name, binary, db, env))
    else:
        configs = [(a.method, a.bin, a.db, dict(os.environ))]
    for _, binary, db, _ in configs:
        ensure_db(binary, a.graph, db)
    out = sys.stdout if a.out == '-' else open(a.out, 'w')
    out.write('qid,method,order,rep,status,total_ms,count\n')
    lines = [l.strip() for l in open(a.queries) if l.strip() and not l.startswith('#')]
    nruns = a.warm + a.reps
    orders = None
    if a.orders:
        orders = {}
        for l in open(a.orders):
            q_, o_, ostr = l.strip().split(',', 2)
            orders.setdefault(int(q_), []).append((int(o_), ostr))
    runs = []
    for line in lines:
        qid, k, edges, preds = parse(line)
        if orders is None:
            runs.append((qid, 0, to_sql(k, edges, preds), ''))
        else:
            for oi, ostr in orders.get(qid, []):
                runs.append((qid, oi, to_sql_ordered(k, edges, preds, ostr), "SET disabled_optimizers='join_order';\n"))
    for li, (qid, oi, sql, pre) in enumerate(runs):
        script = f'SET threads={a.threads};\n{pre}.timer on\n.mode csv\n.headers off\n' + (sql + ';\n') * nruns
        for method, binary, db, env in configs:
            try:
                p = subprocess.run([binary, "-readonly", db], input=script, capture_output=True, text=True,
                                   timeout=a.timeout * nruns + 5, env=env)
                txt = p.stdout + p.stderr
            except subprocess.TimeoutExpired as e:
                txt = (e.stdout or b'').decode(errors='ignore') if isinstance(e.stdout, bytes) else (e.stdout or '')
            times = [float(x) * 1000 for x in TIMER_RE.findall(txt)]
            counts = [int(x) for x in re.findall(r'^\s*(\d+)\s*$', txt, re.M)]
            cnt = counts[0] if counts else -1
            if ('Error' in txt or 'error' in txt) and not counts:   # an error before any result: mark it, never 'ok' with count -1
                out.write(f'{qid},{method},{oi},0,error,-1,-1\n')
                print(qid, method, 'error:', txt[:300].replace('\n', ' '), file=sys.stderr)
                continue
            measured = times[a.warm:]
            if not measured:
                out.write(f'{qid},{method},{oi},0,timeout,{a.timeout*1000:.1f},-1\n')
            else:
                for r, ms in enumerate(measured):
                    out.write(f'{qid},{method},{oi},{r},ok,{ms:.4f},{cnt}\n')
                if len(measured) < a.reps:   # killed mid-way: the remaining reps count as timeouts
                    out.write(f'{qid},{method},{oi},{len(measured)},timeout,{a.timeout*1000:.1f},{cnt}\n')
        if (li + 1) % 50 == 0:
            print(f'\r{li+1}/{len(runs)}', end='', file=sys.stderr); out.flush()
    print(f'\r{len(runs)}/{len(runs)} done', file=sys.stderr)
    if out is not sys.stdout:
        out.close()


if __name__ == '__main__':
    main()
