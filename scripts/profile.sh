#!/bin/bash
# Fast development loop (2026-10-06): the stratified profiling set (queries/profile_G.txt, ~300 queries), one measured
# repetition per method, per-phase operation counts and time, printed as entries / ms / ns per entry per phase, next
# to the speedup summary. Runs in a few minutes; the 1k runs are for final numbers only.
# usage: scripts/profile.sh BIN dblp|lj [extra flags]      e.g. scripts/profile.sh prototype/bin/rptg_v24 lj --beta 0.25
BIN=$1; G=$2; shift 2
cd $RPTG_ROOT
OUT=${OUT_DIR:-/tmp/rptg_profile} $BIN)${OUT_TAG:+_$OUT_TAG}.csv
$BIN --graph data/bin/$G --queries queries/profile_$G.txt --out $OUT --methods M0,M6,M8 --reps 1 --warm 1 --timeout 10 \
  --col-index 1 --min-work 20000 --word-cost 0.3 --extrapolate 1 --cascade 1 --count-far 8 --warm-each 1 "$@" > /dev/null 2>&1
python - "$OUT" <<'PY'
import pandas as pd, numpy as np, sys
gm=lambda s: float(np.exp(np.log(s).mean()))
d=pd.read_csv(sys.argv[1]); ok=d[d.status=='ok']
fail=d.groupby(['qid','method']).status.apply(lambda s:(s!='ok').any()).unstack()
m=ok.groupby(['qid','method'])[['total_ms','init_ms','transfer_ms','join_ms','transfer_work','join_work','join_out','count']].mean()
c=ok.groupby(['qid','method'])['count'].first().unstack()
t=m.total_ms.unstack().where(~fail,10000.); tt=t[t.M0<10000].dropna()
print(f"{sys.argv[1].split('/')[-1]}: {len(tt)} queries; count mismatches", {x:int(((c[x]!=c['M0'])&c[x].notna()).sum()) for x in c.columns if x!='M0'})
for x in [x for x in ['M6','M8'] if x in tt]:
    sp=tt.M0/tt[x]; print(f"  {x}: geo {gm(sp):.2f} <0.9 {100*(sp<0.9).mean():.1f}% <0.5 {100*(sp<0.5).mean():.1f}% total {tt.M0.sum()/1e3:.1f}->{tt[x].sum()/1e3:.1f}s")
q=[x for x in fail.index if not fail.loc[x].any()]
print(f"  phases over {len(q)} queries (entries | ms | ns/entry):")
for meth in [x for x in ['M0','M6','M8'] if x in t]:
    x=m.xs(meth,level=1).loc[q]
    tw,tm=x.transfer_work.sum(),x.transfer_ms.sum(); jw,jm=x.join_work.sum(),x.join_ms.sum(); jo=x.join_out.sum()
    print(f"    {meth}: init {x.init_ms.sum():7.0f} ms | transfer {tw:10.3g} {tm:8.0f} ms {1e6*tm/max(tw,1):6.1f} ns | join scanned {jw:10.3g} counted {jo:10.3g} {jm:8.0f} ms {1e6*jm/max(jw,1):6.1f} ns/scanned")
PY
