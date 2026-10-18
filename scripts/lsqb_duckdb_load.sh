#!/usr/bin/env bash
# Load an LSQB data set (merged-FK CSVs) into a DuckDB database with the DuckDB 1.3.0 CLI.
#
# Uses LSQB's own relational schema and loader (queries/lsqb/sql/{schema,snb-load,views}.sql, copied
# from ext/lsqb/sql/): one table per vertex type with its many-to-one edges as FK columns (merged FK),
# one table per many-to-many edge type, Person_knows_Person loaded in both directions, and UNION ALL
# views for Message, Comment_replyOf_Message, Message_hasCreator_Person, Message_hasTag_Tag,
# Message_isLocatedIn_Country and Person_likes_Message. Row counts are checked against the CSVs.
#
#   scripts/lsqb_duckdb_load.sh SF [DB]          # default DB = data/duckdb/lsqb_sf${SF}.duckdb
#   DUCKDB=ext/duckdb130/duckdb THREADS=8 DATA=data/raw/lsqb/social-network-sf${SF}-merged-fk
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SF=${1:?usage: lsqb_duckdb_load.sh SF [DB]}
DB=${2:-$ROOT/data/duckdb/lsqb_sf${SF}.duckdb}
DUCKDB=${DUCKDB:-$ROOT/ext/duckdb130/duckdb}
THREADS=${THREADS:-8}
DATA=$(cd "${DATA:-$ROOT/data/raw/lsqb/social-network-sf${SF}-merged-fk}" && pwd)
SQL=$ROOT/queries/lsqb/sql

mkdir -p "$(dirname "$DB")"
rm -f "$DB" "$DB.wal"
start=$(date +%s.%N)
{
  echo "SET threads=${THREADS};"
  cat "$SQL/schema.sql"
  sed "s|PATHVAR|${DATA}|g" "$SQL/snb-load.sql"
  cat "$SQL/views.sql"
  echo "CHECKPOINT;"
} | "$DUCKDB" "$DB" >/dev/null
end=$(date +%s.%N)

# row-count check: every table against its CSV (Person_knows_Person holds both directions)
fail=0
for t in Company University Continent Country City Forum Comment Post Person Tag TagClass \
         Comment_hasTag_Tag Post_hasTag_Tag Forum_hasMember_Person Forum_hasTag_Tag Person_hasInterest_Tag \
         Person_likes_Comment Person_likes_Post Person_studyAt_University Person_workAt_Company Person_knows_Person; do
  csv=$(( $(wc -l < "$DATA/$t.csv") - 1 ))
  [ "$t" = Person_knows_Person ] && csv=$(( csv * 2 ))
  got=$("$DUCKDB" -readonly -noheader -list "$DB" -c "SELECT count(*) FROM $t;")
  flag=""; if [ "$got" != "$csv" ]; then flag="  MISMATCH (csv rows $csv)"; fail=1; fi
  printf '%-28s %12s%s\n' "$t" "$got" "$flag"
done
printf 'loaded SF %s in %.1fs -> %s (%s)\n' "$SF" "$(echo "$end - $start" | bc)" "$DB" "$(du -h "$DB" | cut -f1)"
exit $fail
