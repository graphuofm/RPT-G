#!/usr/bin/env python
"""Load a binary RPT-G graph directory into a Kuzu database (node table V, rel table E).

V(id INT64 PK, pu FLOAT, pd FLOAT, label INT32); E(FROM V TO V). Edges are loaded exactly as stored
in the CSR (undirected graphs already contain both directions), so a directed pattern edge a>b in
the RPT-G query format corresponds to (a)-[:E]->(b).
"""
import os, sys, time
import numpy as np, pandas as pd, kuzu

src_dir, db_path = sys.argv[1], sys.argv[2]
n = int(open(os.path.join(src_dir, 'meta.txt')).read().split()[0])
out_off = np.fromfile(os.path.join(src_dir, 'out_off.bin'), dtype=np.uint64)
src = np.repeat(np.arange(n, dtype=np.int64), np.diff(out_off).astype(np.int64))
dst = np.fromfile(os.path.join(src_dir, 'out_nbr.bin'), dtype=np.uint32).astype(np.int64)
vdf = pd.DataFrame({'id': np.arange(n, dtype=np.int64),
                    'pu': np.fromfile(os.path.join(src_dir, 'pu.bin'), dtype=np.float32),
                    'pd': np.fromfile(os.path.join(src_dir, 'pd.bin'), dtype=np.float32),
                    'label': np.fromfile(os.path.join(src_dir, 'label.bin'), dtype=np.int32)})
tmp = db_path + '.csvtmp'; os.makedirs(tmp, exist_ok=True)
vdf.to_parquet(os.path.join(tmp, 'V.parquet'), index=False)
pd.DataFrame({'from': src, 'to': dst}).to_parquet(os.path.join(tmp, 'E.parquet'), index=False)

t0 = time.time()
db = kuzu.Database(db_path); con = kuzu.Connection(db)
con.execute('CREATE NODE TABLE V(id INT64, pu FLOAT, pd FLOAT, label INT32, PRIMARY KEY(id))')
con.execute('CREATE REL TABLE E(FROM V TO V)')
con.execute(f"COPY V FROM '{tmp}/V.parquet'")
con.execute(f"COPY E FROM '{tmp}/E.parquet'")
r = con.execute('MATCH (a:V)-[:E]->(b:V) RETURN count(*)').get_next()[0]
print(f'loaded n={n:,} m={r:,} in {time.time()-t0:.1f}s -> {db_path}')
