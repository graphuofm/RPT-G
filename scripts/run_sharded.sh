#!/bin/bash
# Run the prototype on a query file split into N shards in parallel, then merge the CSVs.
# usage: run_sharded.sh GRAPH_DIR QUERY_FILE OUT_CSV NSHARDS [extra rptg args...]
# The binary is taken from $RPTG_BIN (default: prototype/bin/rptg, i.e. the current build).
# Historical runs used the versioned binaries listed in prototype/VERSIONS.md, e.g.
#   RPTG_BIN=prototype/bin/rptg_v5b scripts/run_sharded.sh data/bin/dblp queries/dblp_robust100.txt ...
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BIN=${RPTG_BIN:-$ROOT/prototype/bin/rptg}
[[ $BIN == /* ]] || BIN=$ROOT/$BIN
GRAPH=$1; Q=$2; OUT=$3; N=$4; shift 4
DIR=$(dirname "$OUT")/shards_$(basename "$OUT" .csv); mkdir -p "$DIR"
grep -v "^#" "$Q" | grep -v "^$" > "$DIR/all.txt"; split -n l/$N -d "$DIR/all.txt" "$DIR/q_"
for f in "$DIR"/q_[0-9]*; do
  [[ $f == *.csv || $f == *.log ]] && continue
  "$BIN" --graph "$GRAPH" --queries "$f" --out "$f.csv" "$@" > "$f.log" 2>&1 &
done
wait
head -1 "$(ls "$DIR"/q_*.csv | head -1)" > "$OUT"
for f in "$DIR"/q_[0-9]*.csv; do tail -n +2 "$f" >> "$OUT"; done
echo "merged $(($(wc -l < "$OUT") - 1)) rows -> $OUT"
