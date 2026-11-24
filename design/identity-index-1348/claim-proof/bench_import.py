"""End-to-end grift_import through the real importer: N ref panels (keyed on slug) and E ref edges
(PG_LINKS__grid_fixtures, plain identity) between seeded grid_fixtures nodes, in ONE batch.
Runs the first import (all new), then a resend (all found). A sampler connection records the peak
number of advisory locks and of all locks held in this database while each import runs.

python bench_import.py N E LABEL
"""

from __future__ import annotations

import sys
import threading
import time
import uuid

import django

django.setup()

import psycopg  # noqa: E402
from django.conf import settings  # noqa: E402

from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor  # noqa: E402
from tap_grid.edge_identity import _edge_identity_registry, register_edge_identity  # noqa: E402
from tap_grid.grift import grift_import  # noqa: E402

N, E, LABEL = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
PLAIN = "PG_LINKS__grid_fixtures"
WEB = {"tap.graph": "web"}
RUN = uuid.uuid4().hex[:6]

if _edge_identity_registry.get_optional(PLAIN) is None:
    register_edge_identity(PLAIN, {"discriminators": []})


def doc(nodes, edges):
    bid = str(uuid.uuid4())
    return {
        "metadata": {"grift_version": "0"},
        "_reserved": {},
        "batches": [
            {
                "batch_entity": {"entity_id": bid, "entity_type": "batch", "name": "bench", "dimensions": {}},
                "batch_node": {"name": "bench", "description": "", "description_json": None, "source": "bench", "metadata": {}},
                "nodes": nodes,
                "edges": edges,
            }
        ],
    }


def dsn():
    db = settings.DATABASES["default"]
    return f"postgresql://{db['USER']}:{db['PASSWORD']}@{db['HOST']}:{db['PORT'] or 5432}/{db['NAME']}"


def timed(label, document):
    peak = {"advisory": 0, "all": 0}
    stop = threading.Event()

    def sample():
        with psycopg.connect(dsn(), autocommit=True) as c:
            while not stop.is_set():
                a, t = c.execute(
                    "select count(*) filter (where l.locktype = 'advisory'), count(*) from pg_locks l "
                    "join pg_stat_activity s on s.pid = l.pid where s.datname = current_database() "
                    "and l.pid <> pg_backend_pid()"
                ).fetchone()
                peak["advisory"], peak["all"] = max(peak["advisory"], a), max(peak["all"], t)
                time.sleep(0.05)

    th = threading.Thread(target=sample)
    th.start()
    t0 = time.perf_counter()
    try:
        result = grift_import(document)
        ok = result.success
        err = "" if ok else "; ".join(f"{i.code}: {i.message[:120]}" for i in result.errors[:2])
    except Exception as exc:  # the lock-table failure surfaces as an exception or an execution issue
        ok, err = False, f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
    s = time.perf_counter() - t0
    stop.set()
    th.join()
    print(f"[{LABEL}] {label}: ok={ok} s={s:.1f} peak_advisory={peak['advisory']} peak_locks={peak['all']} {err}",
          flush=True)
    return ok


from tap.pytest_harness import _seed_test_dimensions  # noqa: E402
from tap_grid.live_dimensions import vocabulary  # noqa: E402

if 'tap.playground' not in vocabulary().by_name:
    _seed_test_dimensions()

with acting_as(get_builtin_actor(COLLECTOR)):
    m = 0
    while m * (m - 1) < E:
        m += 1
    seeds = [
        {"entity": {"entity_id": str(uuid.uuid4()), "entity_type": "grid_fixtures__node", "name": f"s{i}", "dimensions": {}},
         "node": {"name": f"s{i}", "description": ""}}
        for i in range(max(m, 2))
    ]
    _r = grift_import(doc(seeds, []))
    assert _r.success, [(i.code, i.message[:300]) for i in _r.errors[:3]]
    ids = [s["entity"]["entity_id"] for s in seeds]
    pairs = [(a, b) for a in ids for b in ids if a != b][:E]

    def build():
        nodes = [
            {"entity": {"ref": f"p{i}", "entity_type": "panel", "name": f"p{i}", "dimensions": WEB},
             "node": {"name": f"p{i}", "slug": f"bench-{RUN}-{i}", "description": "", "view": "tap_web/panel_error.html"}}
            for i in range(N)
        ]
        edges = [
            {"entity": {"ref": f"e{j}", "entity_type": "edge", "dimensions": {}},
             "edge": {"from_entity_id": a, "to_entity_id": b, "edge_type": PLAIN, "properties": {}}}
            for j, (a, b) in enumerate(pairs)
        ]
        return doc(nodes, edges)

    print(f"[{LABEL}] N={N} panels, E={len(pairs)} edges, keys={N + len(pairs)}", flush=True)
    if timed("first ", build()):
        timed("resend", build())
