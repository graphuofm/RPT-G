#!/bin/bash
# usage: run_kuzu_sharded.sh DB QUERY_FILE OUT_CSV NSHARDS [extra run_kuzu.py args...]
# RUNNER=scripts/run_ladybug.py (with PYTHONPATH on the LadybugDB module) shards a LadybugDB run the same way.
set -e
DB=$1; Q=$2; OUT=$3; N=$4; shift 4
DIR=$(dirname "$OUT")/shards_$(basename "$OUT" .csv); mkdir -p "$DIR"
grep -v "^#" "$Q" | grep -v "^$" > "$DIR/all.txt"; split -n l/$N -d "$DIR/all.txt" "$DIR/q_"
for f in "$DIR"/q_[0-9]*; do
  [[ $f == *.csv || $f == *.log ]] && continue
  ${KUZU_PY:-python} ${RUNNER:-$RPTG_ROOT/scripts/run_kuzu.py} --db "$DB" --queries "$f" --out "$f.csv" "$@" > "$f.log" 2>&1 &
done
wait
head -1 "$(ls "$DIR"/q_*.csv | head -1)" > "$OUT"
for f in "$DIR"/q_[0-9]*.csv; do tail -n +2 "$f" >> "$OUT"; done
echo "merged $(($(wc -l < "$OUT") - 1)) rows -> $OUT"
