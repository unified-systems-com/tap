#!/bin/bash
# Interleaved: for round in 1..R: for variant in V0 V1 V2 (+V3 list): apply variant DDL as owner, then each query once as spike_search
# (EXPLAIN ANALYZE), logging uptime load avg beside every timing. Output: interleave.tsv  (round variant query ms load1)
cd "$(dirname "$0")"; R=${R:-5}; VARS=${VARS:-"V0 V1 V2"}
: > interleave.tsv
for r in $(seq 1 $R); do
 for v in $VARS; do
  case $v in V0) f=v_off.sql;; V1) f=v_1.sql;; V2) f=v_2.sql;; V3a) f=v_3a.sql;; V3c) f=v_3c.sql;; esac
  ./psql.sh spike_owner < $f >/dev/null 2>&1
  grep -v '^--' queries.sql | while IFS='|' read -r n q; do
    out=$(echo "EXPLAIN (ANALYZE, BUFFERS) $q;" | ./psql.sh spike_search)
    ms=$(echo "$out" | sed -n 's/.*Execution Time: \([0-9.]*\) ms.*/\1/p')
    load=$(uptime | sed 's/.*load averages*: *\([0-9.]*\).*/\1/')
    printf "%s\t%s\t%s\t%s\t%s\n" $r $v $n $ms $load >> interleave.tsv
    [ $r = 1 ] && { echo "== $n ($v/spike_search) load=$load"; echo "$out"; } >> interleave_plans_$v.txt
  done
 done
done
