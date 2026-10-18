#!/usr/bin/env python
"""Load a binary graph directory (data/bin/<graph>) into a PostgreSQL database.

Schema (identical to the DuckDB runs, scripts/export_parquet.py):
    V(id INT PRIMARY KEY, pu REAL, pd REAL, label INT)       one row per vertex, ordered by id
    E(src INT, dst INT)                                       one row per out-adjacency entry, ordered by (src, dst)
    btree indexes E(src, dst) and E(dst, src)                 the adjacency index in both directions
followed by VACUUM (ANALYZE) so that index-only scans see an all-visible map and the planner has statistics.

Rows are sent with COPY ... (FORMAT binary) built by numpy in chunks, inside the transaction that creates
the tables, so with wal_level = minimal (scripts/pg19_ctl.sh) the bulk load writes no WAL.

usage: pg19_load.py GRAPH_DIR DBNAME [--drop] [--host SOCKET_DIR] [--port 5439] [--chunk ROWS]
    e.g. pg19_load.py data/bin/dblp dblp          pg19_load.py data/bin/lj lj
"""
import argparse, os, sys, time
import numpy as np
import psycopg
from psycopg import sql

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER = b'PGCOPY\n\xff\r\n\x00' + (0).to_bytes(4, 'big') + (0).to_bytes(4, 'big')
TRAILER = (-1).to_bytes(2, 'big', signed=True)


def copy_binary(cur, table, cols, arrays, chunk):
    """COPY table(cols) FROM STDIN binary; arrays: list of (numpy array, '>i4' | '>f4'), all 4-byte fields."""
    n = len(arrays[0][0])
    fields = [('nf', '>i2')]
    for i, (_, t) in enumerate(arrays):
        fields += [(f'l{i}', '>i4'), (f'f{i}', t)]
    dt = np.dtype(fields)
    stmt = sql.SQL('COPY {} ({}) FROM STDIN (FORMAT binary)').format(
        sql.Identifier(table), sql.SQL(', ').join(map(sql.Identifier, cols)))
    with cur.copy(stmt) as cp:
        cp.write(HEADER)
        for lo in range(0, n, chunk):
            hi = min(n, lo + chunk)
            buf = np.empty(hi - lo, dtype=dt)
            buf['nf'] = len(arrays)
            for i, (a, _) in enumerate(arrays):
                buf[f'l{i}'] = 4
                buf[f'f{i}'] = a[lo:hi]
            cp.write(buf.tobytes())
        cp.write(TRAILER)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('graph')
    ap.add_argument('db')
    ap.add_argument('--host', default=os.path.join(ROOT, 'data/pg19/cluster'))
    ap.add_argument('--port', type=int, default=5439)
    ap.add_argument('--drop', action='store_true', help='drop the database first if it exists')
    ap.add_argument('--chunk', type=int, default=1 << 22)
    a = ap.parse_args()

    d = a.graph
    n, m, _ = open(os.path.join(d, 'meta.txt')).read().split()
    n, m = int(n), int(m)
    out_off = np.fromfile(os.path.join(d, 'out_off.bin'), dtype=np.uint64)
    assert len(out_off) == n + 1 and int(out_off[-1]) == m, 'out_off.bin does not match meta.txt'
    src = np.repeat(np.arange(n, dtype=np.int32), np.diff(out_off).astype(np.int64))
    dst = np.fromfile(os.path.join(d, 'out_nbr.bin'), dtype=np.uint32).astype(np.int32)
    assert len(dst) == m
    del out_off
    ids = np.arange(n, dtype=np.int32)
    pu = np.fromfile(os.path.join(d, 'pu.bin'), dtype=np.float32)
    pdv = np.fromfile(os.path.join(d, 'pd.bin'), dtype=np.float32)
    label = np.fromfile(os.path.join(d, 'label.bin'), dtype=np.int32)
    assert len(pu) == len(pdv) == len(label) == n

    conn = dict(host=a.host, port=a.port)
    with psycopg.connect(dbname='postgres', autocommit=True, **conn) as c:
        exists = c.execute('SELECT 1 FROM pg_database WHERE datname = %s', (a.db,)).fetchone()
        if exists and not a.drop:
            sys.exit(f'database {a.db} exists (use --drop to replace it)')
        if exists:
            c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(a.db)))
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(a.db)))

    t0 = time.time()
    with psycopg.connect(dbname=a.db, **conn) as c:
        with c.cursor() as cur:   # one transaction: CREATE TABLE + COPY (WAL-skipped under wal_level=minimal)
            cur.execute('CREATE TABLE V (id INT NOT NULL, pu REAL, pd REAL, label INT)')
            cur.execute('CREATE TABLE E (src INT NOT NULL, dst INT NOT NULL)')
            copy_binary(cur, 'v', ['id', 'pu', 'pd', 'label'],
                        [(ids, '>i4'), (pu, '>f4'), (pdv, '>f4'), (label, '>i4')], a.chunk)
            copy_binary(cur, 'e', ['src', 'dst'], [(src, '>i4'), (dst, '>i4')], a.chunk)
        c.commit()
        print(f'copied n={n:,} m={m:,} in {time.time() - t0:.1f}s', file=sys.stderr)
        c.autocommit = True
        t1 = time.time()
        c.execute("SET maintenance_work_mem = '2GB'")
        c.execute('ALTER TABLE V ADD PRIMARY KEY (id)')
        c.execute('CREATE INDEX e_src_dst ON E (src, dst)')
        c.execute('CREATE INDEX e_dst_src ON E (dst, src)')
        print(f'indexes in {time.time() - t1:.1f}s', file=sys.stderr)
        t1 = time.time()
        c.execute('VACUUM (ANALYZE) V')
        c.execute('VACUUM (ANALYZE) E')
        print(f'vacuum analyze in {time.time() - t1:.1f}s', file=sys.stderr)
        nv = c.execute('SELECT count(*) FROM V').fetchone()[0]
        ne = c.execute('SELECT count(*) FROM E').fetchone()[0]
        assert (nv, ne) == (n, m), f'row counts {nv}, {ne} != {n}, {m}'
        for rel in ('v', 'e', 'v_pkey', 'e_src_dst', 'e_dst_src'):
            size = c.execute('SELECT pg_size_pretty(pg_relation_size(%s::regclass))', (rel,)).fetchone()[0]
            print(f'  {rel:10s} {size}', file=sys.stderr)
    print(f'loaded {d} -> {a.db}: V {n:,} rows, E {m:,} rows, {time.time() - t0:.1f}s total', file=sys.stderr)


if __name__ == '__main__':
    main()
