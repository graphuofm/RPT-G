#!/usr/bin/env python
"""Export a binary graph directory to V.parquet / E.parquet for loading into any DuckDB CLI build."""
import os, sys
import numpy as np, pandas, duckdb

d = sys.argv[1]
n = int(open(os.path.join(d, 'meta.txt')).read().split()[0])
out_off = np.fromfile(os.path.join(d, 'out_off.bin'), dtype=np.uint64)
src = np.repeat(np.arange(n, dtype=np.int32), np.diff(out_off).astype(np.int64))
dst = np.fromfile(os.path.join(d, 'out_nbr.bin'), dtype=np.uint32).astype(np.int32)
vdf = pandas.DataFrame({'id': np.arange(n, dtype=np.int32),
                        'pu': np.fromfile(os.path.join(d, 'pu.bin'), dtype=np.float32),
                        'pd': np.fromfile(os.path.join(d, 'pd.bin'), dtype=np.float32),
                        'label': np.fromfile(os.path.join(d, 'label.bin'), dtype=np.int32)})
edf = pandas.DataFrame({'src': src, 'dst': dst})
con = duckdb.connect()
con.execute(f"COPY (SELECT * FROM vdf ORDER BY id) TO '{d}/V.parquet' (FORMAT parquet)")
con.execute(f"COPY (SELECT * FROM edf ORDER BY src, dst) TO '{d}/E.parquet' (FORMAT parquet)")
print('exported', d, n, len(src))
