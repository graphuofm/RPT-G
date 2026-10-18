#!/usr/bin/env python
"""Run one (query, forced order) pair of the robustness workload in DuckDB, alternating RPT-G off/on, and
print the per-run times and the RPT-G debug line (diagnosis helper).
usage: duckdb_pair.py QID ORDER [--runs 5] [--queries queries/dblp_robust100b.txt]"""
import argparse, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(__file__))
from run_duckdb import parse, to_sql, to_sql_ordered  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('qid', type=int)
ap.add_argument('order', type=int)
ap.add_argument('--runs', type=int, default=5)
ap.add_argument('--queries', default='queries/dblp_robust100b.txt')
ap.add_argument('--orders', default='results/kuzu_dblp_robust.orders.csv')
ap.add_argument('--bin', default='ext/duckdb_rptg/build/release/duckdb')
ap.add_argument('--db', default='data/bin/dblp/dblp_130.db')
ap.add_argument('--force', action='store_true', help='mode 1 forces every useful transfer (scripts/duckdb_force_wrap.sh)')
a = ap.parse_args()
line = next(l.strip() for l in open(a.queries) if l.startswith(f'id={a.qid} '))
qid, k, edges, preds = parse(line)
if a.order >= 0:
    ostr = next(l.strip().split(',', 2)[2] for l in open(a.orders) if l.startswith(f'{a.qid},{a.order},'))
    sql, pre = to_sql_ordered(k, edges, preds, ostr), "SET disabled_optimizers='join_order';\n"
else:
    sql, pre = to_sql(k, edges, preds), ''
script = f'SET threads=8;\n{pre}.timer on\n' + (sql + ';\n') * (a.runs + 1)
for mode in ['0', '1', '0', '1']:
    env = dict(os.environ, RPTG_MODE=mode, RPTG_DEBUG='1')
    binary = 'scripts/duckdb_force_wrap.sh' if a.force and mode == '1' else a.bin
    if a.force and mode == '1':
        env['RPTG_BETA'] = '1e6'
    p = subprocess.run([binary, '-readonly', a.db], input=script, capture_output=True, text=True, env=env)
    txt = p.stdout + p.stderr
    t = [float(x) * 1000 for x in re.findall(r'Run Time \(s\): real ([0-9.]+)', txt)][1:]
    dbg = [l for l in txt.split('\n') if l.startswith('[rptg] k=') or l.startswith('[rptg] edges')]
    print(f'mode {mode}: ' + ' '.join(f'{x:.0f}' for x in t) + f'   median {sorted(t)[len(t) // 2]:.0f} ms')
    if mode == '1' and dbg:
        print('   ', dbg[-1][:400])
