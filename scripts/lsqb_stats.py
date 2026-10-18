#!/usr/bin/env python
"""Statistics of the LSQB data sets and of the attributes available for predicates (markdown to stdout).

    PY=python
    $PY scripts/lsqb_stats.py counts  --sfs 0.1,0.3,1,3        # vertex/edge counts and sizes per SF
    $PY scripts/lsqb_stats.py degrees --sfs 0.1,1,3            # out/in-degree max and mean per edge type
    $PY scripts/lsqb_stats.py attrs   --bi data/raw/snb_bi/bi-sf1-composite-merged-fk --lsqb-sf 1

LSQB's CSVs carry ids only. `attrs` therefore profiles the attributes of the LDBC SNB BI data set of
the same scale factor (same generator; files from datasets.ldbcouncil.org/bi-pre-audit/) and reports
how many LSQB ids of each type are found in it (i.e. can receive a real attribute by an id join).
The BI directory may hold the raw Parquet layout (graphs/parquet/raw/composite-merged-fk, all
entities incl. deleted ones; SF 0.1 tarball) or the CSV layout (graphs/csv/bi/composite-merged-fk,
initial_snapshot + inserts are unioned).
"""
import argparse, glob, os
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'data/raw/lsqb')

VERTICES = ['Person', 'Forum', 'Post', 'Comment', 'Tag', 'TagClass', 'Country', 'City', 'Continent',
            'Company', 'University']


def pdir(sf):
    return os.path.join(RAW, f'social-network-sf{sf}-projected-fk')


def nrows(path):
    with open(path, 'rb') as f:
        return sum(1 for _ in f) - 1


def fmt(x):
    return f'{x:,}' if isinstance(x, int) else f'{x:,.2f}'


def edge_files(sf):
    out = []
    for p in sorted(glob.glob(os.path.join(pdir(sf), '*_*_*.csv'))):
        name = os.path.basename(p)[:-4]
        src, rel, dst = name.split('_', 2)
        out.append((name, src, rel, dst, p))
    return out


def counts(a):
    sfs = a.sfs.split(',')
    print('| SF | .tar.zst merged-fk / projected-fk | extracted merged-fk / projected-fk |')
    print('|----|---:|---:|')
    for sf in sfs:
        z = [os.path.getsize(os.path.join(RAW, f'social-network-sf{sf}-{f}.tar.zst')) / 1e6 for f in ('merged-fk', 'projected-fk')]
        d = [sum(os.path.getsize(p) for p in glob.glob(os.path.join(RAW, f'social-network-sf{sf}-{f}', '*.csv'))) / 1e6
             for f in ('merged-fk', 'projected-fk')]
        print(f'| {sf} | {z[0]:.1f} MB / {z[1]:.1f} MB | {d[0]:.0f} MB / {d[1]:.0f} MB |')
    print()
    print('| vertex type | ' + ' | '.join(f'SF {sf}' for sf in sfs) + ' |')
    print('|---|' + '---:|' * len(sfs))
    tot = {sf: 0 for sf in sfs}
    for v in VERTICES:
        row = []
        for sf in sfs:
            n = nrows(os.path.join(pdir(sf), f'{v}.csv')); tot[sf] += n; row.append(fmt(n))
        print(f'| {v} | ' + ' | '.join(row) + ' |')
    print('| **total** | ' + ' | '.join(f'**{fmt(tot[sf])}**' for sf in sfs) + ' |')
    print()
    print('| edge type (projected-fk file) | ' + ' | '.join(f'SF {sf}' for sf in sfs) + ' |')
    print('|---|' + '---:|' * len(sfs))
    tot = {sf: 0 for sf in sfs}
    for name, *_ in edge_files(sfs[0]):
        row = []
        for sf in sfs:
            n = nrows(os.path.join(pdir(sf), f'{name}.csv')); tot[sf] += n; row.append(fmt(n))
        print(f'| {name} | ' + ' | '.join(row) + ' |')
    print('| **total** (knows counted once) | ' + ' | '.join(f'**{fmt(tot[sf])}**' for sf in sfs) + ' |')


def degrees(a):
    con = duckdb.connect(); con.execute(f'SET threads={a.threads}')
    sfs = a.sfs.split(',')
    stats = {}
    for sf in sfs:
        vcount = {v: nrows(os.path.join(pdir(sf), f'{v}.csv')) for v in VERTICES}
        for name, src, rel, dst, p in edge_files(sf):
            rd = f"read_csv('{p}', delim='|', header=false, skip=1, columns={{'s': 'BIGINT', 'd': 'BIGINT'}})"
            if name == 'Person_knows_Person':         # undirected: degree over both directions
                rd = f'(SELECT s, d FROM {rd} UNION ALL SELECT d, s FROM {rd})'
            m = con.execute(f'SELECT count(*) FROM {rd}').fetchone()[0]
            so = con.execute(f'SELECT count(*), max(c), quantile_disc(c, 0.99) FROM (SELECT count(*) c FROM {rd} GROUP BY s)').fetchone()
            si = con.execute(f'SELECT count(*), max(c), quantile_disc(c, 0.99) FROM (SELECT count(*) c FROM {rd} GROUP BY d)').fetchone()
            stats[(sf, name)] = (m, vcount[src], so, vcount[dst], si)
    print('Degrees per edge type (out = per source vertex, in = per target vertex; mean over *all* vertices '
          'of the type, incl. degree 0; p99 over vertices with degree >= 1; `knows` counted in both directions).')
    for sf in sfs:
        print(f'\n**SF {sf}**\n')
        print('| edge type | edges | out: mean / p99 / max | src with deg>=1 | in: mean / p99 / max | dst with deg>=1 |')
        print('|---|---:|---:|---:|---:|---:|')
        for name, *_ in edge_files(sf):
            m, ns, so, nd, si = stats[(sf, name)]
            print(f'| {name} | {m:,} | {m/ns:.2f} / {so[2]:,} / {so[1]:,} | {so[0]/ns:.0%} | '
                  f'{m/nd:.2f} / {si[2]:,} / {si[1]:,} | {si[0]/nd:.0%} |')


def attrs(a):
    con = duckdb.connect(); con.execute(f'SET threads={a.threads}')
    raw = os.path.join(a.bi, 'graphs/parquet/raw/composite-merged-fk')
    csvd = os.path.join(a.bi, 'graphs/csv/bi/composite-merged-fk')

    def src(t, static):
        d = 'static' if static else 'dynamic'
        if os.path.isdir(raw):
            return f"read_parquet('{raw}/{d}/{t}/*.parquet')"
        if static:
            return f"read_csv('{csvd}/initial_snapshot/static/{t}/*.csv*', delim='|', header=true)"
        return (f"(SELECT * FROM read_csv('{csvd}/initial_snapshot/dynamic/{t}/*.csv*', delim='|', header=true) "
                f"UNION ALL BY NAME SELECT * EXCLUDE (batch_id) FROM read_csv('{csvd}/inserts/dynamic/{t}/*/*.csv*', "
                f"delim='|', header=true, hive_partitioning=true))")

    types = [('Person', False, None), ('Forum', False, None), ('Post', False, None), ('Comment', False, None),
             ('Tag', True, None), ('TagClass', True, None), ('Place', True, None), ('Organisation', True, None),
             ('Person_knows_Person', False, None), ('Person_hasInterest_Tag', False, None),
             ('Person_studyAt_University', False, None), ('Person_workAt_Company', False, None),
             ('Forum_hasMember_Person', False, None), ('Person_likes_Post', False, None),
             ('Person_likes_Comment', False, None), ('Post_hasTag_Tag', False, None), ('Comment_hasTag_Tag', False, None)]
    skip_cols = {'deletionDate', 'explicitlyDeleted', 'url'}
    print(f'Source: `{os.path.relpath(a.bi, ROOT)}` ({"raw Parquet" if os.path.isdir(raw) else "CSV initial_snapshot + inserts"})\n')
    print('| type | attribute | type | rows | distinct | nulls | min | max | most frequent (share) |')
    print('|---|---|---|---:|---:|---:|---|---|---|')
    for t, static, _ in types:
        con.execute(f'CREATE OR REPLACE TEMP TABLE cur AS SELECT * FROM {src(t, static)}')
        rel = 'cur'
        cols = con.execute(f'DESCRIBE SELECT * FROM {rel}').fetchall()
        n = con.execute(f'SELECT count(*) FROM {rel}').fetchone()[0]
        for c, ty, *_ in cols:
            if c in skip_cols or c.endswith('Id') or c == 'id':
                continue
            if c == 'content':
                nn = con.execute(f'SELECT count(*) - count(content) FROM {rel}').fetchone()[0]
                print(f'| {t} | content | varchar | {n:,} | (text) | {nn:,} | | | |')
                continue
            q = f'SELECT count(DISTINCT "{c}"), count(*) - count("{c}"), min("{c}")::VARCHAR, max("{c}")::VARCHAR FROM {rel}'
            nd, nn, mn, mx = con.execute(q).fetchone()
            top = ''
            if nd <= 5000 or ty == 'VARCHAR':
                tops = con.execute(f'SELECT "{c}"::VARCHAR, count(*) FROM {rel} GROUP BY 1 ORDER BY 2 DESC LIMIT 3').fetchall()
                top = ', '.join(f'{str(v)[:24]} ({k / n:.1%})' for v, k in tops)
            s = lambda v: str(v)[:25].replace('|', '/')
            print(f'| {t} | {c} | {ty.split(" ")[0].lower()} | {n:,} | {nd:,} | {nn:,} | {s(mn)} | {s(mx)} | {top} |')
    if a.lsqb_sf:
        L = os.path.join(RAW, f'social-network-sf{a.lsqb_sf}-merged-fk')
        print(f'\nCoverage: LSQB SF {a.lsqb_sf} ids found in the BI data set (by id / by id pair)\n')
        print('| LSQB table | LSQB rows | BI rows | LSQB rows matched |')
        print('|---|---:|---:|---:|')
        chk = [('Person', 'Person', 'id', 'id'), ('Forum', 'Forum', 'id', 'id'), ('Post', 'Post', 'id', 'id'),
               ('Comment', 'Comment', 'id', 'id'), ('Tag', 'Tag', 'id', 'id'), ('TagClass', 'TagClass', 'id', 'id'),
               ('City', 'Place', 'id', 'id'), ('Country', 'Place', 'id', 'id'),
               ('Company', 'Organisation', 'id', 'id'), ('University', 'Organisation', 'id', 'id'),
               ('Person_knows_Person', 'Person_knows_Person', 'person1id, person2id', 'Person1Id, Person2Id'),
               ('Person_hasInterest_Tag', 'Person_hasInterest_Tag', 'id, hasinterest_tag', 'PersonId, TagId'),
               ('Forum_hasMember_Person', 'Forum_hasMember_Person', 'id, hasmember_person', 'ForumId, PersonId')]
        for lt, bt, lk, bk in chk:
            static = bt in ('Tag', 'TagClass', 'Place', 'Organisation')
            l = f"read_csv('{L}/{lt}.csv', delim='|', header=true)"
            nl = con.execute(f'SELECT count(*) FROM {l}').fetchone()[0]
            nb = con.execute(f'SELECT count(*) FROM {src(bt, static)}').fetchone()[0]
            m = con.execute(f'SELECT count(*) FROM {l} WHERE ({lk}) IN (SELECT ({bk}) FROM {src(bt, static)})').fetchone()[0]
            print(f'| {lt} | {nl:,} | {nb:,} | {m:,} ({m / nl:.1%}) |')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('what', choices=['counts', 'degrees', 'attrs'])
    ap.add_argument('--sfs', default='0.1,0.3,1,3')
    ap.add_argument('--bi', default=os.path.join(ROOT, 'data/raw/snb_bi/bi-sf1-composite-merged-fk'))
    ap.add_argument('--lsqb-sf', default=None)
    ap.add_argument('--threads', type=int, default=4)
    a = ap.parse_args()
    {'counts': counts, 'degrees': degrees, 'attrs': attrs}[a.what](a)


if __name__ == '__main__':
    main()
