#!/usr/bin/env python
"""Load an LSQB data set (projected-FK CSVs) into a Kuzu database.

Schema = LSQB's Kuzu/LadybugDB schema (queries/lsqb/kuzu/schema.cypher, copied from
ext/lsqb/ladybug/schema.cypher): ID-only node tables; Comment and Post are merged into one node table
Message (their ids are disjoint), the Comment/Post edge files into Message_* rel tables, and
Person_knows_Person is stored in both directions (each undirected knows edge twice), exactly as
LSQB's ladybug/convert.sh + load.py do. Instead of writing concatenated CSVs next to the data (as
convert.sh does) the loader COPYs from lists of files and loads the reversed knows edges through
LOAD FROM, so data/raw stays untouched.

    PY=python          # official kuzu 0.11.3 wheel
    $PY scripts/lsqb_kuzu_load.py 0.1   # -> data/kuzu/lsqb_sf0.1.kz

The database files are also opened by the patched build (ext/kuzu/tools/python_api/build).
"""
import argparse, os, shutil, sys, time
import kuzu

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (rel/node table, source files, reversed?) -- order: all node tables first
NODES = [
    ('Company', ['Company']), ('University', ['University']), ('Continent', ['Continent']),
    ('Country', ['Country']), ('City', ['City']), ('Tag', ['Tag']), ('TagClass', ['TagClass']),
    ('Forum', ['Forum']), ('Message', ['Comment', 'Post']), ('Person', ['Person']),
]
RELS = [
    ('City_isPartOf_Country', ['City_isPartOf_Country']),
    ('Message_hasCreator_Person', ['Comment_hasCreator_Person', 'Post_hasCreator_Person']),
    ('Message_hasTag_Tag', ['Comment_hasTag_Tag', 'Post_hasTag_Tag']),
    ('Message_isLocatedIn_Country', ['Comment_isLocatedIn_Country', 'Post_isLocatedIn_Country']),
    ('Message_replyOf_Message', ['Comment_replyOf_Comment', 'Comment_replyOf_Post']),
    ('Comment_replyOf_Post', ['Comment_replyOf_Post']),
    ('Company_isLocatedIn_Country', ['Company_isLocatedIn_Country']),
    ('Country_isPartOf_Continent', ['Country_isPartOf_Continent']),
    ('Forum_containerOf_Message', ['Forum_containerOf_Post']),   # containers always hold Posts
    ('Forum_hasMember_Person', ['Forum_hasMember_Person']),
    ('Forum_hasModerator_Person', ['Forum_hasModerator_Person']),
    ('Forum_hasTag_Tag', ['Forum_hasTag_Tag']),
    ('Person_hasInterest_Tag', ['Person_hasInterest_Tag']),
    ('Person_isLocatedIn_City', ['Person_isLocatedIn_City']),
    ('Person_knows_Person', ['Person_knows_Person']),              # + reversed copy below
    ('Person_likes_Message', ['Person_likes_Comment', 'Person_likes_Post']),
    ('Person_studyAt_University', ['Person_studyAt_University']),
    ('Person_workAt_Company', ['Person_workAt_Company']),
    ('TagClass_isSubclassOf_TagClass', ['TagClass_isSubclassOf_TagClass']),
    ('Tag_hasType_TagClass', ['Tag_hasType_TagClass']),
    ('University_isLocatedIn_City', ['University_isLocatedIn_City']),
]
OPTS = "(HEADER=true, DELIM='|')"


def rows(path):
    with open(path, 'rb') as f:
        return sum(1 for _ in f) - 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sf', help='scale factor, e.g. 0.1, 0.3, 1, 3 (or "example")')
    ap.add_argument('--data', default=None, help='projected-fk directory (default data/raw/lsqb/social-network-sf{SF}-projected-fk)')
    ap.add_argument('--db', default=None, help='default data/kuzu/lsqb_sf{SF}.kz')
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--buffer-gb', type=float, default=8.0)
    ap.add_argument('--force', action='store_true', help='delete an existing database first')
    a = ap.parse_args()
    data = os.path.abspath(a.data or os.path.join(ROOT, f'data/raw/lsqb/social-network-sf{a.sf}-projected-fk'))
    db_path = a.db or os.path.join(ROOT, f'data/kuzu/lsqb_sf{a.sf}.kz')
    if os.path.exists(db_path):
        if not a.force:
            sys.exit(f'{db_path} exists (use --force)')
        shutil.rmtree(db_path) if os.path.isdir(db_path) else os.remove(db_path)
        if os.path.exists(db_path + '.wal'):
            os.remove(db_path + '.wal')
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    t0 = time.time()
    db = kuzu.Database(db_path, buffer_pool_size=int(a.buffer_gb * (1 << 30)), max_num_threads=a.threads)
    con = kuzu.Connection(db, num_threads=a.threads)
    schema = open(os.path.join(ROOT, 'queries/lsqb/kuzu/schema.cypher')).read()
    for stmt in schema.split(';'):
        if stmt.strip():
            con.execute(stmt)
    bad = []
    for table, files in NODES + RELS:
        paths = [os.path.join(data, f + '.csv') for f in files]
        src = f"'{paths[0]}'" if len(paths) == 1 else '[' + ', '.join(f"'{p}'" for p in paths) + ']'
        t1 = time.time()
        con.execute(f'COPY {table} FROM {src} {OPTS}')
        expected = sum(rows(p) for p in paths)
        if table == 'Person_knows_Person':
            con.execute(f"COPY {table} FROM (LOAD WITH HEADERS (p1 INT64, p2 INT64) FROM '{paths[0]}' {OPTS} RETURN p2, p1)")
            expected *= 2
        if (table, files) in NODES:
            got = con.execute(f'MATCH (n:{table}) RETURN count(*)').get_next()[0]
        else:
            got = con.execute(f'MATCH ()-[e:{table}]->() RETURN count(*)').get_next()[0]
        flag = '' if got == expected else f'  MISMATCH (csv rows {expected:,})'
        if flag:
            bad.append(table)
        print(f'{table:32s} {got:>12,}  {time.time()-t1:6.1f}s{flag}', flush=True)
    print(f'loaded SF {a.sf} in {time.time()-t0:.1f}s -> {db_path}' + (f'; MISMATCHES: {bad}' if bad else ''))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
