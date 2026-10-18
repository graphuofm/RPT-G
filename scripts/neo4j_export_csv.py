#!/usr/bin/env python
"""Write a binary RPT-G graph directory as CSVs for `neo4j-admin database import`."""
import os, sys
import numpy as np, pandas as pd
d, out = sys.argv[1], sys.argv[2]; os.makedirs(out, exist_ok=True)
n = int(open(os.path.join(d, 'meta.txt')).read().split()[0])
out_off = np.fromfile(os.path.join(d, 'out_off.bin'), dtype=np.uint64)
src = np.repeat(np.arange(n, dtype=np.int64), np.diff(out_off).astype(np.int64))
dst = np.fromfile(os.path.join(d, 'out_nbr.bin'), dtype=np.uint32).astype(np.int64)
pd.DataFrame({'id:ID': np.arange(n), 'pu:float': np.fromfile(os.path.join(d, 'pu.bin'), dtype=np.float32),
              'pd:float': np.fromfile(os.path.join(d, 'pd.bin'), dtype=np.float32),
              'label:int': np.fromfile(os.path.join(d, 'label.bin'), dtype=np.int32)}).to_csv(os.path.join(out, 'V.csv'), index=False)
pd.DataFrame({':START_ID': src, ':END_ID': dst}).to_csv(os.path.join(out, 'E.csv'), index=False)
print('wrote', out, n, len(src))
