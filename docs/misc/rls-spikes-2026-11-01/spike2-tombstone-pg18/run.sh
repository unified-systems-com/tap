#!/bin/bash
# End-to-end rerun on tap-db:latest. Log to run.log. Always removes the container+volume on exit.
cd "$(dirname "$0")"; exec > run.log 2>&1
N=spike2-rls-pg
trap 'echo "== cleanup"; docker rm -f -v $N >/dev/null 2>&1; docker ps -a --filter name=$N --format "left: {{.Names}}"; echo CLEANED' EXIT
echo "== start $(date) load: $(uptime | sed 's/.*load/load/')"
docker run -d --name $N --memory 3g --cpus 2 --shm-size 256m -e POSTGRES_PASSWORD=spike -e POSTGRES_DB=spike ghcr.io/unified-systems-com/tap-db:latest >/dev/null || { echo "RUNFAIL"; exit 1; }
for i in $(seq 1 60); do docker exec $N pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1 && break; sleep 2; done
echo "== server_version"; PGPASSWORD=spike docker exec -e PGPASSWORD=spike $N psql -h 127.0.0.1 -U postgres -d spike -Atc "show server_version; select version();"
./psql.sh postgres < 01_roles.sql || { echo ROLEFAIL; exit 1; }
echo "== schema"; ./psql.sh spike_owner < 02_schema.sql || exit 1
echo "== load $(date) load: $(uptime | sed 's/.*load/load/')"; ./psql.sh spike_owner < 03_load.sql || { echo LOADFAIL; exit 1; }
echo "== v2 prep"; ./psql.sh spike_owner < v_2_prep.sql || exit 1
echo "== write cost (owner)"; ./psql.sh spike_owner < write_cost.sql
echo "== interleave $(date) load: $(uptime | sed 's/.*load/load/')"
R=${R:-5} VARS="V0 V1 V2 V3c" ./interleave.sh
echo "== summary"; python3 -I summarize.py interleave.tsv
echo "== V2 without partial indexes (shape a, d): does the partial index matter?"
./psql.sh spike_owner < v_2.sql >/dev/null
for q in "SELECT count(*) FROM spike_finding WHERE status='open'" "SELECT from_entity_id FROM tap_edge WHERE edge_type='X'"; do
  echo "-- with partial idx: $q"; echo "EXPLAIN (ANALYZE) $q;" | ./psql.sh spike_search | grep -E "Scan|Execution Time"
done
./psql.sh spike_owner -c "DROP INDEX spike_finding_live_idx; DROP INDEX tap_edge_live_type_idx;" >/dev/null
for q in "SELECT count(*) FROM spike_finding WHERE status='open'" "SELECT from_entity_id FROM tap_edge WHERE edge_type='X'"; do
  echo "-- without partial idx: $q"; echo "EXPLAIN (ANALYZE) $q;" | ./psql.sh spike_search | grep -E "Scan|Execution Time"
done
echo "== PG plan for V1 shape a (semi-join or SubPlan?)"
./psql.sh spike_owner < v_1.sql >/dev/null
echo "EXPLAIN SELECT count(*) FROM spike_finding WHERE status='open';" | ./psql.sh spike_search
echo "== done $(date) load: $(uptime | sed 's/.*load/load/')"
echo RUN_COMPLETE
