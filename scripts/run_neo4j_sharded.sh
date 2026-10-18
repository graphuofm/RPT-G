#!/bin/bash
# usage: run_neo4j_sharded.sh DATABASE SHARD_DIR OUT_CSV [extra run_neo4j.py args...]
set -e
DB=$1; DIR=$2; OUT=$3; shift 3
for f in "$DIR"/q_[0-9]*; do
  [[ $f == *.csv || $f == *.log ]] && continue
  $HOME/miniconda3/envs/neo4j/bin/python $RPTG_ROOT/scripts/run_neo4j.py --database "$DB" --queries "$f" --out "$f.csv" --resume "$@" > "$f.log" 2>&1 &
done
wait
head -1 "$(ls "$DIR"/q_*.csv | head -1)" > "$OUT"
for f in "$DIR"/q_[0-9]*.csv; do tail -n +2 "$f" >> "$OUT"; done
echo "merged $(($(wc -l < "$OUT") - 1)) rows -> $OUT"
