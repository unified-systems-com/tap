#!/bin/bash
# Dimension-RLS spike on tap-db:latest. N=rows R=rounds. Logs to run.log; always removes container+volume.
cd "$(dirname "$0")"; exec > run.log 2>&1
N=${N:-1000000}; R=${R:-3}; C=spike3-rls-pg
CFGS="V0 L_arr C_gin_arr C_gin_slots C_gpo_arr C_gpo_slots C_none_slots"
trap 'echo "== cleanup"; docker rm -f -v $C >/dev/null 2>&1; docker ps -a --filter name=$C --format "left: {{.Names}}"; echo CLEANED' EXIT
echo "== start $(date) N=$N R=$R load: $(uptime | sed 's/.*load/load/')"
docker run -d --name $C --memory 3g --cpus 2 --shm-size 256m -e POSTGRES_PASSWORD=spike -e POSTGRES_DB=spike ghcr.io/unified-systems-com/tap-db:latest >/dev/null || { echo RUNFAIL; exit 1; }
for i in $(seq 1 60); do docker exec $C pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1 && break; sleep 2; done
docker exec -e PGPASSWORD=spike $C psql -h 127.0.0.1 -U postgres -d spike -Atc "show server_version"
./psql.sh postgres < 01_roles.sql >/dev/null || { echo ROLEFAIL; exit 1; }
./psql.sh spike_owner < 02_schema.sql >/dev/null || { echo SCHEMAFAIL; exit 1; }
echo "== load $(date)"; ./psql.sh spike_owner -v N=$N < 03_load.sql || { echo LOADFAIL; exit 1; }
echo "== correctness: rows visible to spike_search vs ground truth (owner, explicit predicate)"
while IFS='|' read -r sn sj; do
  truth=$(printf "SET tap.scope='%s';\nSELECT count(*) FROM tap_entity WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(current_setting('tap.scope', true)::jsonb) s(v) WHERE dimensions @> s.v);\n" "$sj" | ./psql.sh spike_owner -At | tail -1)
  line="$sn truth=$truth"
  for c in $CFGS; do
    ./mkpol.sh $c | ./psql.sh spike_owner >/dev/null 2>&1 || line="$line $c=APPLYFAIL"
    got=$(printf "SET tap.scope='%s';\nSELECT count(*) FROM spike_finding;\n" "$sj" | ./psql.sh spike_search -At 2>&1 | tail -1)
    [ "$c" = V0 ] && continue
    [ "$got" = "$truth" ] && line="$line $c=ok" || line="$line $c=MISMATCH($got)"
  done
  echo "$line"
done < scopes.txt
echo "== write cost"; ./psql.sh spike_owner < write_cost.sql 2>&1 | grep -E "^===|Time:"
echo "== interleave $(date) load: $(uptime | sed 's/.*load/load/')"
: > timings.tsv; rm -f plans_*.txt
for r in $(seq 1 $R); do
 while IFS='|' read -r sn sj; do
  for c in $CFGS; do
   ./mkpol.sh $c | ./psql.sh spike_owner >/dev/null 2>&1
   while IFS='|' read -r qn qs; do
     out=$(printf "SET statement_timeout='90s';\nSET tap.scope='%s';\nEXPLAIN (ANALYZE, BUFFERS) %s;\n" "$sj" "$qs" | ./psql.sh spike_search 2>&1)
     ms=$(echo "$out" | sed -n 's/.*Execution Time: \([0-9.]*\) ms.*/\1/p'); [ -z "$ms" ] && ms=90000
     load=$(uptime | sed 's/.*load averages*: *\([0-9.]*\).*/\1/')
     printf "%s\t%s\t%s\t%s\t%s\t%s\n" $r $sn $c $qn $ms $load >> timings.tsv
     if [ $r = 1 ] && [ "$qn" = a ] && { [ $sn = S1 ] || [ $sn = S4 ]; }; then { echo "== $c $sn $qn"; echo "$out" | grep -vE "^\s*$|Buffers|Planning|JIT|Functions|Options|Timing"; } >> plans_$c.txt; fi
   done < queries.txt
  done
 done < scopes.txt
done
echo "== summary"; python3 -I summarize.py timings.tsv
echo "== done $(date) load: $(uptime | sed 's/.*load/load/')"; echo RUN_COMPLETE
