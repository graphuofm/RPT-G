#!/usr/bin/env python
"""Run the 9 LSQB queries on Kuzu (Python API) and/or DuckDB (CLI) and validate the counts.

For every (engine, SF, query): 1 warm-up + N timed repetitions in one process (Kuzu: one worker
process per SF with a query timeout; DuckDB: one CLI process per query with `.timer on`, killed when a
single execution exceeds the timeout). Counts are compared with LSQB's expected results
(queries/lsqb/expected-output.csv).

Output CSV: engine,sf,query,rep,status,total_ms,count -- one row per timed repetition (rep 0..N-1)
plus one row with rep=median per (engine, sf, query). status: ok | wrong (count differs from LSQB's
expected count) | timeout | error | crash. A timeout counts as the timeout in the median.

    PY=~/miniconda3/bin/python
    $PY scripts/run_lsqb.py --engines kuzu,duckdb --sfs 0.1,0.3,1,3 --out results/lsqb_baseline.csv
    # patched Kuzu build with RPT-G settings, labelled separately:
    PYTHONPATH=ext/kuzu/tools/python_api/build ~/miniconda3/envs/rptg-build/bin/python scripts/run_lsqb.py \
        --engines kuzu --label KR2 --kuzu-calls 'enable_semi_mask=false;rptg_mode=2;rptg_beta=1.0' --out ...
"""
import argparse, os, queue, re, statistics, subprocess, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMER_RE = re.compile(r'Run Time \(s\): real ([0-9.]+)')


def expected_counts():
    exp = {}
    for line in open(os.path.join(ROOT, 'queries/lsqb/expected-output.csv')):
        f = line.rstrip('\n').split('\t')
        if len(f) >= 6 and f[0] == 'expected':
            exp[(f[2], int(f[3]))] = int(f[5])
    return exp


def kuzu_worker(a):
    """Runs inside a subprocess: prints `query,rep,status,ms,count` lines (rep -1 = warm-up)."""
    import kuzu
    db = kuzu.Database(os.path.join(ROOT, f'data/kuzu/lsqb_sf{a.sf}.kz'), read_only=True,
                       buffer_pool_size=int(a.kuzu_buffer_gb * (1 << 30)))
    con = kuzu.Connection(db, num_threads=a.threads)
    con.set_query_timeout(int(a.timeout * 1000))
    for kv in filter(None, (a.kuzu_calls or '').split(';')):
        con.execute(f'CALL {kv.strip()}')
    for q in a.qs:
        text = open(os.path.join(ROOT, f'queries/lsqb/kuzu/q{q}.cypher')).read()
        for r in range(-a.warm, a.reps):
            t = time.perf_counter()
            try:
                cnt, status = con.execute(text).get_next()[0], 'ok'
            except RuntimeError as e:
                cnt = -1
                status = 'timeout' if ('nterrupt' in str(e) or 'imeout' in str(e)) else 'error'
                if status == 'error':
                    print(f'kuzu sf{a.sf} q{q}: {str(e)[:300]}', file=sys.stderr)
            ms = (time.perf_counter() - t) * 1000
            print(f'{q},{r},{status},{ms:.3f},{cnt}', flush=True)
            if status != 'ok':
                break


def run_kuzu(a, sf, qs):
    cmd = [sys.executable, os.path.abspath(__file__), '--worker', '--sf', sf, '--queries', ','.join(map(str, qs)),
           '--threads', str(a.threads), '--timeout', str(a.timeout), '--reps', str(a.reps), '--warm', str(a.warm),
           '--kuzu-buffer-gb', str(a.kuzu_buffer_gb)] + (['--kuzu-calls', a.kuzu_calls] if a.kuzu_calls else [])
    p = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(p.stderr)
    res = {}
    for line in p.stdout.splitlines():
        q, r, status, ms, cnt = line.split(',')
        res.setdefault(int(q), []).append((int(r), status, float(ms), int(cnt)))
    for q in qs:                     # the worker died while running q: mark it and continue after it
        if q not in res:
            res[q] = [(0, 'crash', -1.0, -1)]
            rest = [x for x in qs if x > q and x not in res]
            if p.returncode != 0 and rest:
                print(f'kuzu sf{sf}: worker crashed (rc={p.returncode}) on q{q}; restarting', file=sys.stderr)
                res.update(run_kuzu(a, sf, rest))
            break
    return res


def run_duckdb(a, sf, q):
    db = os.path.join(ROOT, f'data/duckdb/lsqb_sf{sf}.duckdb')
    text = open(os.path.join(ROOT, f'queries/lsqb/sql/q{q}.sql')).read().strip().rstrip(';') + ';\n'
    script = f'SET threads={a.threads};\n.timer on\n.mode csv\n.headers off\n' + text * (a.warm + a.reps) + '.quit\n'
    p = subprocess.Popen([a.duckdb_bin, '-readonly', db], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(l) for l in p.stdout] + [lines.put(None)], daemon=True).start()
    p.stdin.write(script); p.stdin.close()
    out, cnt, t_last, runs, status = [], -1, time.perf_counter(), 0, 'ok'
    while runs < a.warm + a.reps:
        try:
            line = lines.get(timeout=max(0.0, a.timeout - (time.perf_counter() - t_last)) + 1.0)
        except queue.Empty:
            p.kill(); status = 'timeout'; break
        if line is None:
            status = 'error'; break
        m = TIMER_RE.search(line)
        if m:
            ms = float(m.group(1)) * 1000
            runs += 1; t_last = time.perf_counter()
            if ms > a.timeout * 1000:
                status = 'timeout'; p.kill(); break
            out.append((runs - 1 - a.warm, 'ok', ms, cnt))
        elif re.fullmatch(r'\s*\d+\s*', line):
            cnt = int(line)
        elif 'Error' in line:
            print(f'duckdb sf{sf} q{q}: {line.strip()[:300]}', file=sys.stderr)
    p.wait()
    if status != 'ok':
        out.append((max(runs - a.warm, 0), status, a.timeout * 1000 if status == 'timeout' else -1.0, -1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engines', default='kuzu,duckdb')
    ap.add_argument('--sfs', default='0.1,0.3,1,3')
    ap.add_argument('--queries', default='1,2,3,4,5,6,7,8,9')
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--timeout', type=float, default=60.0, help='seconds per execution')
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--warm', type=int, default=1)
    ap.add_argument('--out', default=os.path.join(ROOT, 'results/lsqb_baseline.csv'))
    ap.add_argument('--append', action='store_true')
    ap.add_argument('--label', default=None, help='engine name written to the CSV (default: the engine)')
    ap.add_argument('--duckdb-bin', default=os.path.join(ROOT, 'ext/duckdb130/duckdb'))
    ap.add_argument('--kuzu-buffer-gb', type=float, default=12.0)
    ap.add_argument('--kuzu-calls', default=None, help='";"-separated Kuzu settings, e.g. "enable_semi_mask=false;rptg_mode=2"')
    ap.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--sf', default=None, help=argparse.SUPPRESS)
    a = ap.parse_args()
    a.qs = [int(x) for x in a.queries.split(',')]
    if a.worker:
        return kuzu_worker(a)

    exp = expected_counts()
    new = not (a.append and os.path.exists(a.out))
    out = open(a.out, 'a' if not new else 'w')
    if new:
        out.write('engine,sf,query,rep,status,total_ms,count\n')
    summary = []
    for engine in a.engines.split(','):
        label = a.label or engine
        for sf in a.sfs.split(','):
            res = run_kuzu(a, sf, a.qs) if engine == 'kuzu' else {q: run_duckdb(a, sf, q) for q in a.qs}
            for q in a.qs:
                rows = [x for x in res[q] if x[0] >= 0 or x[1] != 'ok']      # drop the ok warm-up
                times = []
                for r, status, ms, cnt in rows:
                    if status == 'ok' and cnt != exp.get((sf, q), cnt):
                        status = 'wrong'
                    out.write(f'{label},{sf},{q},{max(r, 0)},{status},{ms:.3f},{cnt}\n')
                    times.append(ms if status in ('ok', 'wrong') else a.timeout * 1000)
                statuses = {x[1] for x in rows}
                cnts = {x[3] for x in rows if x[1] == 'ok'}
                cnt = cnts.pop() if len(cnts) == 1 else -1
                st = 'ok' if statuses == {'ok'} else sorted(statuses - {'ok'})[0]
                if st == 'ok' and cnt != exp.get((sf, q), cnt):
                    st = 'wrong'
                med = statistics.median(times + [a.timeout * 1000] * (a.reps - len(times))) if times else -1
                out.write(f'{label},{sf},{q},median,{st},{med:.3f},{cnt}\n')
                out.flush()
                summary.append((label, sf, q, st, med, cnt, exp.get((sf, q))))
                print(f'{label:8s} sf{sf:4s} q{q}  {st:7s} {med:10.1f} ms  count={cnt} expected={exp.get((sf, q))}', flush=True)
    out.close()


if __name__ == '__main__':
    main()
