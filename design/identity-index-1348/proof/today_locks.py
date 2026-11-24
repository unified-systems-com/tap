"""Today's code: the importer's real `_take_identity_locks` with real `identity_lock_key` / `edge_lock_key`.

Builds N node keys and N edge keys the way the importer does (one per ref node, one per ref edge),
takes them inside one transaction, and reports the advisory locks this backend holds (pg_locks).
No table is touched: `_take_identity_locks` only runs `pg_advisory_xact_lock`.

Usage: python today_locks.py N   (run inside the web image, DJANGO_SETTINGS_MODULE=tap.settings)
"""

import os
import sys
import time
import uuid

import django

django.setup()

from django.db import connection, transaction  # noqa: E402

from tap_grid.edge_identity import edge_lock_key  # noqa: E402
from tap_grid.grift.importer import _take_identity_locks  # noqa: E402
from tap_grid.natural_key import identity_lock_key  # noqa: E402

n = int(sys.argv[1])
node_ids = [uuid.uuid7() for _ in range(n)]
node_keys = [identity_lock_key("qualys_detection", {"qid": i, "host_id": f"h{i % 997}"}) for i in range(n)]
edge_keys = [edge_lock_key("affects", node_ids[i], node_ids[(i + 1) % n], {}) for i in range(n)]

with connection.cursor() as c:
    c.execute("show max_locks_per_transaction")
    mlpt = c.fetchone()[0]
    c.execute("show max_connections")
    mc = c.fetchone()[0]
print(f"server: max_locks_per_transaction={mlpt} max_connections={mc} db={connection.settings_dict['NAME']}")
started = time.perf_counter()
try:
    with transaction.atomic():
        _take_identity_locks(node_keys)
        t_nodes = time.perf_counter() - started
        _take_identity_locks(edge_keys)
        t_all = time.perf_counter() - started
        with connection.cursor() as c:
            c.execute("select count(*) from pg_locks where pid = pg_backend_pid() and locktype = 'advisory'")
            held = c.fetchone()[0]
            c.execute("select count(*) from pg_locks where pid = pg_backend_pid()")
            total = c.fetchone()[0]
        print(f"keys={2 * n} advisory_locks_held={held} all_locks_held={total} "
              f"node_phase_s={t_nodes:.2f} total_s={t_all:.2f}")
except Exception as exc:  # the lock-table failure surfaces here
    print(f"keys={2 * n} FAILED after {time.perf_counter() - started:.2f}s: {type(exc).__name__}: {str(exc).splitlines()[0]}"
          f" | {str(exc).splitlines()[1] if len(str(exc).splitlines()) > 1 else ''}")
