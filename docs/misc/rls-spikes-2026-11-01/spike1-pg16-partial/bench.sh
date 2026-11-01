#!/bin/bash
# usage: bench.sh ROLE LABEL  -> 1 EXPLAIN ANALYZE BUFFERS dump (explain_LABEL_ROLE.txt) + 7 timed runs each, median ms of Execution Time
role=$1; label=$2; cd "$(dirname "$0")"
: > explain_${label}_${role}.txt
grep -v '^--' queries.sql | while IFS='|' read -r n q; do
  ts=""
  for i in 1 2 3 4 5 6 7; do
    out=$(echo "EXPLAIN (ANALYZE, BUFFERS) $q;" | ./psql.sh $role)
    t=$(echo "$out" | sed -n 's/.*Execution Time: \([0-9.]*\) ms.*/\1/p'); ts="$ts $t"
  done
  echo "== $n ($label/$role)" >> explain_${label}_${role}.txt; echo "$out" >> explain_${label}_${role}.txt
  med=$(echo $ts | tr ' ' '\n' | sort -n | sed -n 4p)
  echo "$label $role $n median_ms=$med runs=[$ts ]"
done
