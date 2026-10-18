#!/usr/bin/env bash
# Load an LSQB data set into a PostgreSQL database (LSQB's own PostgreSQL implementation, run with a
# local psql instead of LSQB's Docker container).
#
#   scripts/lsqb_pg_load.sh [options] SF
#     -h HOST      host or socket directory   (default: $PGHOST, else $RPTG_ROOT/data/pg19/cluster)
#     -p PORT      port                        (default: $PGPORT, else 5439)
#     -d DBNAME    database                    (default: lsqb_sf${SF} with the dot removed, e.g. lsqb_sf01)
#     -U USER      role                        (default: $PGUSER, else the OS user)
#     -v VARIANT   sql (default): merged-FK tables + UNION ALL views, LSQB sql/*.sql, queries in
#                  queries/lsqb/sql/;  pgq: projected-FK tables + CREATE PROPERTY GRAPH lsqb (SQL/PGQ,
#                  PostgreSQL >= 19), queries in queries/lsqb/pgq/
#     -i           also create indexes (not part of LSQB: PK on vertex ids, btree on every FK/edge column)
#     -r           replace: drop and recreate DBNAME if it exists (otherwise an existing DB is an error)
#   env: PSQL (default ext/pg19/install/bin/psql if present, else psql), DATA (CSV directory)
#
# Schema/load/view SQL: queries/lsqb/{sql,pgq}/{schema,snb-load,views}.sql, copied verbatim from
# ext/lsqb (sql/ and postgres/pgq/). The server-side COPY statements of sql/snb-load.sql are run as
# client-side \copy so that no superuser rights or server file access are needed. Afterwards:
# VACUUM ANALYZE and a row-count check against the CSVs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST=${PGHOST:-$ROOT/data/pg19/cluster}; PORT=${PGPORT:-5439}; USERNAME=${PGUSER:-$(id -un)}
DBNAME=""; VARIANT=sql; INDEXES=0; REPLACE=0
while getopts "h:p:d:U:v:ir" o; do
  case $o in
    h) HOST=$OPTARG ;; p) PORT=$OPTARG ;; d) DBNAME=$OPTARG ;; U) USERNAME=$OPTARG ;;
    v) VARIANT=$OPTARG ;; i) INDEXES=1 ;; r) REPLACE=1 ;;
    *) sed -n '2,20p' "$0"; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
SF=${1:?usage: lsqb_pg_load.sh [-h host] [-p port] [-d db] [-U user] [-v sql|pgq] [-i] [-r] SF}
DBNAME=${DBNAME:-lsqb_sf${SF//./}}
if [ -z "${PSQL:-}" ]; then
  if [ -x "$ROOT/ext/pg19/install/bin/psql" ]; then PSQL=$ROOT/ext/pg19/install/bin/psql; else PSQL=psql; fi
fi
case $VARIANT in
  sql) FMT=merged-fk ;;
  pgq) FMT=projected-fk ;;
  *) echo "unknown variant $VARIANT" >&2; exit 2 ;;
esac
DATA=$(cd "${DATA:-$ROOT/data/raw/lsqb/social-network-sf${SF}-${FMT}}" && pwd)
SQL=$ROOT/queries/lsqb/$VARIANT
PSQLC=("$PSQL" -X -q -v ON_ERROR_STOP=1 -h "$HOST" -p "$PORT" -U "$USERNAME")

exists=$("${PSQLC[@]}" -d postgres -tA -c "SELECT 1 FROM pg_database WHERE datname = '$DBNAME'")
if [ "$exists" = 1 ]; then
  if [ $REPLACE = 1 ]; then
    "${PSQLC[@]}" -d postgres -c "DROP DATABASE \"$DBNAME\" WITH (FORCE)"
  else
    echo "database $DBNAME exists (use -r to replace it)" >&2; exit 1
  fi
fi
"${PSQLC[@]}" -d postgres -c "CREATE DATABASE \"$DBNAME\""

start=$(date +%s.%N)
echo "loading SF $SF ($VARIANT, $DATA) into $DBNAME at $HOST:$PORT"
{
  cat "$SQL/schema.sql"
  # PATHVAR -> data dir; server-side COPY -> client-side \copy (one statement per line in both variants)
  sed -e "s|PATHVAR|${DATA}|g" -e 's|^COPY |\\copy |' "$SQL/snb-load.sql"
  cat "$SQL/views.sql"
} | "${PSQLC[@]}" -d "$DBNAME"

if [ $INDEXES = 1 ]; then
  if [ "$VARIANT" = sql ]; then
    IDX="
    ALTER TABLE Company ADD PRIMARY KEY (CompanyId);   ALTER TABLE University ADD PRIMARY KEY (UniversityId);
    ALTER TABLE Continent ADD PRIMARY KEY (ContinentId); ALTER TABLE Country ADD PRIMARY KEY (CountryId);
    ALTER TABLE City ADD PRIMARY KEY (CityId);         ALTER TABLE Tag ADD PRIMARY KEY (TagId);
    ALTER TABLE TagClass ADD PRIMARY KEY (TagClassId); ALTER TABLE Forum ADD PRIMARY KEY (ForumId);
    ALTER TABLE Comment ADD PRIMARY KEY (CommentId);   ALTER TABLE Post ADD PRIMARY KEY (PostId);
    ALTER TABLE Person ADD PRIMARY KEY (PersonId);
    CREATE INDEX ON City (isPartOf_CountryId);       CREATE INDEX ON Person (isLocatedIn_CityId);
    CREATE INDEX ON Tag (hasType_TagClassId);        CREATE INDEX ON Forum (hasModerator_PersonId);
    CREATE INDEX ON Comment (hasCreator_PersonId);   CREATE INDEX ON Comment (replyOf_PostId);
    CREATE INDEX ON Comment (replyOf_CommentId);     CREATE INDEX ON Post (hasCreator_PersonId);
    CREATE INDEX ON Post (Forum_containerOfId);
    CREATE INDEX ON Comment_hasTag_Tag (CommentId, TagId);  CREATE INDEX ON Comment_hasTag_Tag (TagId);
    CREATE INDEX ON Post_hasTag_Tag (PostId, TagId);        CREATE INDEX ON Post_hasTag_Tag (TagId);
    CREATE INDEX ON Forum_hasMember_Person (ForumId);       CREATE INDEX ON Forum_hasMember_Person (PersonId);
    CREATE INDEX ON Person_hasInterest_Tag (PersonId);      CREATE INDEX ON Person_hasInterest_Tag (TagId);
    CREATE INDEX ON Person_likes_Comment (CommentId);       CREATE INDEX ON Person_likes_Post (PostId);
    CREATE INDEX ON Person_knows_Person (Person1Id, Person2Id); CREATE INDEX ON Person_knows_Person (Person2Id);"
  else
    IDX=$("${PSQLC[@]}" -d "$DBNAME" -tA -c "
      SELECT string_agg(format('CREATE INDEX ON %I (%I);', c.table_name, c.column_name), E'\n')
      FROM information_schema.columns c
      WHERE c.table_schema = 'public' AND c.table_name LIKE '%\_%\_%' AND c.column_name <> 'id'")
  fi
  echo "$IDX" | "${PSQLC[@]}" -d "$DBNAME"
fi
"${PSQLC[@]}" -d "$DBNAME" -c "VACUUM ANALYZE"
end=$(date +%s.%N)

# row-count check against the CSVs (Person_knows_Person holds both directions)
if [ "$VARIANT" = sql ]; then
  TABLES="Company University Continent Country City Forum Comment Post Person Tag TagClass Comment_hasTag_Tag
          Post_hasTag_Tag Forum_hasMember_Person Forum_hasTag_Tag Person_hasInterest_Tag Person_likes_Comment
          Person_likes_Post Person_studyAt_University Person_workAt_Company Person_knows_Person"
else
  TABLES="Company University Continent Country City Forum Comment Post Person Tag TagClass Comment_hasTag_Tag
          Post_hasTag_Tag Forum_hasMember_Person Person_hasInterest_Tag Person_likes_Comment Person_likes_Post
          Person_knows_Person City_isPartOf_Country Tag_hasType_TagClass Post_hasCreator_Person
          Comment_hasCreator_Person Person_isLocatedIn_City Forum_containerOf_Post Comment_replyOf_Post"
fi
fail=0
for t in $TABLES; do
  csv=$(( $(wc -l < "$DATA/$t.csv") - 1 ))
  [ "$t" = Person_knows_Person ] && csv=$(( csv * 2 ))
  got=$("${PSQLC[@]}" -d "$DBNAME" -tA -c "SELECT count(*) FROM $t")
  flag=""; if [ "$got" != "$csv" ]; then flag="  MISMATCH (csv rows $csv)"; fail=1; fi
  printf '%-28s %12s%s\n' "$t" "$got" "$flag"
done
printf 'loaded SF %s (%s%s) in %.1fs -> %s\n' "$SF" "$VARIANT" "$([ $INDEXES = 1 ] && echo ', indexes')" \
  "$(echo "$end - $start" | bc)" "$DBNAME"
exit $fail
