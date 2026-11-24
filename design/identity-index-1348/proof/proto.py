"""Issue 1348 prototype: advisory-lock identity (today's shape) vs partial unique index + ON CONFLICT,
vs mutex rows. Raw SQL over psycopg 3 against a throwaway database (schema.sql).

python proto.py DSN [N]
Prints one line per measurement; every number in the spec draft comes from this output.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg

DSN = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
HERE = Path(__file__).parent


def connect() -> psycopg.Connection:
    return psycopg.connect(DSN, autocommit=False)


def reset() -> None:
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute((HERE / "schema.sql").read_text())


def own_locks(cur) -> tuple[int, int]:
    cur.execute(
        "select count(*), count(*) filter (where locktype = 'advisory') from pg_locks where pid = pg_backend_pid()"
    )
    return cur.fetchone()


def node_rows(lo: int, hi: int, tag: str = "p") -> list[tuple]:
    return [(uuid.uuid7(), i, f"h{i % 997}", f"{tag}{i}") for i in range(lo, hi)]


def node_key(qid: int, host: str) -> str:
    # The shape of identity_lock_key: type, unit separator, canonical JSON of the declared values.
    return "det\x1f" + json.dumps({"host_id": host, "qid": qid}, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------- today's shape
def batch_today(conn, rows) -> dict:
    """Every key's advisory lock up front, sorted (_take_identity_locks), then per key the search and, on a
    miss, the spine + typed insert. Round trips per key as today; the ORM adds more on top."""
    t0 = time.perf_counter()
    batch = uuid.uuid7()
    with conn.cursor() as cur:
        for key in sorted({node_key(q, h) for _, q, h, _ in rows}):
            cur.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])
        created = found = 0
        for eid, q, h, p in rows:
            cur.execute("select entity_id from det where qid = %s and host_id = %s and spine_deleted_at is null", [q, h])
            hit = cur.fetchone()
            if hit:
                cur.execute("update det set payload = %s where entity_id = %s", [p, hit[0]])
                cur.execute("update ent set last_observed_batch = %s where id = %s", [batch, hit[0]])
                found += 1
            else:
                cur.execute(
                    "insert into ent (id, entity_type, natural_key, last_observed_batch) values (%s, 'det', %s, %s)",
                    [eid, f"{q}|{h}", batch],
                )
                cur.execute("insert into det (entity_id, qid, host_id, payload) values (%s, %s, %s, %s)", [eid, q, h, p])
                created += 1
        locks, advisory = own_locks(cur)
    conn.commit()
    return {"created": created, "found": found, "locks": locks, "advisory": advisory, "s": time.perf_counter() - t0}


# --------------------------------------------------------------------------- option A: index + ON CONFLICT
def batch_index(conn, rows, *, sort: bool = True, hold: threading.Barrier | None = None) -> dict:
    """COPY into a staging table, one INSERT ... SELECT ... ON CONFLICT over the partial unique index, in key
    order. A new key inserts its typed row (the spine row follows; the FK is deferred); a found key is
    row-locked by DO UPDATE and its spine row's observation pointer is updated."""
    t0 = time.perf_counter()
    batch = uuid.uuid7()
    order = "ORDER BY qid, host_id" if sort else ""
    with conn.cursor() as cur:
        cur.execute(
            "create temp table stage (id uuid, qid int, host_id text, payload text) on commit drop;"
            "create temp table claimed (entity_id uuid, inserted bool) on commit drop;"
        )
        with cur.copy("copy stage from stdin") as cp:
            for r in rows:
                cp.write_row(r)
        if hold is not None:
            hold.wait()
        cur.execute(
            f"""
            with up as (
                insert into det (entity_id, qid, host_id, payload)
                select id, qid, host_id, payload from stage {order}
                on conflict (qid, host_id) where spine_deleted_at is null
                do update set payload = excluded.payload
                returning entity_id, (xmax = 0) as inserted
            )
            insert into claimed select * from up
            """
        )
        cur.execute(
            "insert into ent (id, entity_type, natural_key, last_observed_batch) "
            "select c.entity_id, 'det', s.qid::text || '|' || s.host_id, %s "
            "from claimed c join stage s on s.id = c.entity_id where c.inserted",
            [batch],
        )
        cur.execute(
            "update ent set last_observed_batch = %s from claimed c where ent.id = c.entity_id and not c.inserted",
            [batch],
        )
        cur.execute("select count(*) filter (where inserted), count(*) filter (where not inserted) from claimed")
        created, found = cur.fetchone()
        locks, advisory = own_locks(cur)
    conn.commit()
    return {"created": created, "found": found, "locks": locks, "advisory": advisory, "s": time.perf_counter() - t0}


# --------------------------------------------------------------------------- option B: mutex rows
def batch_lockrows(conn, rows) -> dict:
    """Advisory locks replaced by row locks on a mutex table (insert-or-lock in digest order), then the
    search and insert done set-wise. Identity semantics unchanged: no unique index on the data."""
    t0 = time.perf_counter()
    batch = uuid.uuid7()
    with conn.cursor() as cur:
        cur.execute("create temp table stage (id uuid, qid int, host_id text, payload text, digest bytea) on commit drop")
        with cur.copy("copy stage from stdin") as cp:
            for e, q, h, p in rows:
                cp.write_row((e, q, h, p, hashlib.sha256(node_key(q, h).encode()).digest()))
        cur.execute(
            "insert into idlock select digest from stage order by digest "
            "on conflict (digest) do update set digest = excluded.digest"
        )
        cur.execute(
            "update stage s set id = d.entity_id from det d "
            "where d.qid = s.qid and d.host_id = s.host_id and d.spine_deleted_at is null"
        )
        cur.execute(
            "insert into ent (id, entity_type, natural_key, last_observed_batch) "
            "select s.id, 'det', s.qid::text || '|' || s.host_id, %s from stage s "
            "where not exists (select 1 from ent e where e.id = s.id)",
            [batch],
        )
        created = cur.rowcount
        cur.execute(
            "insert into det (entity_id, qid, host_id, payload) select id, qid, host_id, payload from stage "
            "on conflict (entity_id) do update set payload = excluded.payload"
        )
        locks, advisory = own_locks(cur)
    conn.commit()
    return {"created": created, "found": len(rows) - created, "locks": locks, "advisory": advisory,
            "s": time.perf_counter() - t0}


# --------------------------------------------------------------------------- edges
def edge_digest(edge_type: str, src: uuid.UUID, dst: uuid.UUID, values: dict) -> bytes:
    key = f"edge:{edge_type}\x1f" + json.dumps(
        {"from": str(src), "to": str(dst), **{f"properties.{k}": v for k, v in values.items()}},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(key.encode()).digest()


def batch_edges(conn, edges) -> dict:
    t0 = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(
            "create temp table estage (id uuid, edge_type text, from_id uuid, to_id uuid, properties jsonb, digest bytea)"
            " on commit drop; create temp table eclaimed (entity_id uuid, inserted bool) on commit drop;"
        )
        with cur.copy("copy estage from stdin") as cp:
            for e in edges:
                cp.write_row(e)
        cur.execute(
            """
            with up as (
                insert into edge (entity_id, edge_type, from_id, to_id, properties, identity_digest)
                select id, edge_type, from_id, to_id, properties, digest from estage order by digest
                on conflict (identity_digest) where spine_deleted_at is null and identity_digest is not null
                do update set properties = excluded.properties
                returning entity_id, (xmax = 0) as inserted
            )
            insert into eclaimed select * from up
            """
        )
        cur.execute(
            "insert into ent (id, entity_type) select entity_id, 'edge' from eclaimed where inserted"
        )
        cur.execute("select count(*) filter (where inserted), count(*) filter (where not inserted) from eclaimed")
        created, found = cur.fetchone()
        locks, advisory = own_locks(cur)
    conn.commit()
    return {"created": created, "found": found, "locks": locks, "advisory": advisory, "s": time.perf_counter() - t0}


def fmt(d: dict) -> str:
    return " ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k, v in d.items())


def scalar(sql: str, args=None):
    with psycopg.connect(DSN, autocommit=True) as c:
        return c.execute(sql, args).fetchone()[0]


def live_duplicates() -> int:
    return scalar(
        "select count(*) from (select qid, host_id from det where spine_deleted_at is null "
        "group by 1, 2 having count(*) > 1) d"
    )


def orphans() -> int:
    return scalar("select count(*) from det d where not exists (select 1 from ent e where e.id = d.entity_id)")


# --------------------------------------------------------------------------- scenarios
def single_writer() -> None:
    for name, fn in (("today", batch_today), ("index", batch_index), ("lockrows", batch_lockrows)):
        reset()
        with connect() as c:
            for label, rows in (("first ", node_rows(0, N)), ("resend", node_rows(0, N, "q"))):
                t0 = time.perf_counter()
                try:
                    print(f"[{name}] {label} N={N}:", fmt(fn(c, rows)))
                except psycopg.Error as exc:
                    c.rollback()
                    print(f"[{name}] {label} N={N}: FAILED after {time.perf_counter() - t0:.2f}s "
                          f"{type(exc).__name__}: {str(exc).splitlines()[0]}")
        print(f"[{name}] rows={scalar('select count(*) from det')} live_dups={live_duplicates()} orphans={orphans()}")


def hot_stats() -> None:
    reset()
    with connect() as c:
        batch_index(c, node_rows(0, N))
        batch_index(c, node_rows(0, N, "q"))
        c.execute("select pg_stat_force_next_flush()")
        c.commit()
    time.sleep(1.5)
    with psycopg.connect(DSN, autocommit=True) as c:
        r = c.execute(
            "select n_tup_ins, n_tup_upd, n_tup_hot_upd, n_dead_tup from pg_stat_user_tables where relname = 'det'"
        ).fetchone()
    print(f"[index] det after create+resend: ins={r[0]} upd={r[1]} hot_upd={r[2]} dead={r[3]}")


def edges() -> None:
    reset()
    with connect() as c:
        batch_index(c, node_rows(0, N))
        ids = [r[0] for r in c.execute("select entity_id from det order by qid").fetchall()]
        c.commit()
        es = [(uuid.uuid7(), "affects", ids[i], ids[(i + 1) % len(ids)], json.dumps({}),
               edge_digest("affects", ids[i], ids[(i + 1) % len(ids)], {})) for i in range(len(ids))]
        print(f"[edges index] first  E={len(es)}:", fmt(batch_edges(c, es)))
        es2 = [(uuid.uuid7(), *e[1:]) for e in reversed(es)]
        print(f"[edges index] resend E={len(es2)} (reversed):", fmt(batch_edges(c, es2)))
    print(f"[edges index] edges={scalar('select count(*) from edge')}")


def functional() -> None:
    """Small checks: retirement then return; JSON-path arbiter; per-type expression arbiter; the
    in-statement duplicate error; the arbiter needs the predicate restated."""
    reset()
    with psycopg.connect(DSN, autocommit=True) as c:
        with connect() as w:
            first = batch_index(w, [(uuid.uuid7(), 1, "h1", "a")])
        old = c.execute("select entity_id from det where qid = 1").fetchone()[0]
        c.execute("update ent set deleted_at = now() where id = %s", [old])
        c.execute("update det set spine_deleted_at = now() where entity_id = %s", [old])
        with connect() as w:
            again = batch_index(w, [(uuid.uuid7(), 1, "h1", "b")])
        rows = c.execute("select count(*), count(*) filter (where spine_deleted_at is null) from det where qid = 1").fetchone()
        print(f"[retire] first created={first['created']}; after retirement the key returns: created={again['created']} "
              f"found={again['found']}; rows={rows[0]} live={rows[1]}")

        for loc in ('{"route": 123}', '{"route": 123}', '{"route": "123"}'):
            eid = uuid.uuid7()
            c.execute("begin")
            r = c.execute(
                "insert into route (entity_id, location) values (%s, %s) "
                "on conflict ((location -> 'route')) where spine_deleted_at is null do update set location = excluded.location "
                "returning entity_id = %s", [eid, loc, eid],
            ).fetchone()[0]
            c.execute("insert into ent (id, entity_type) values (%s, 'route') on conflict do nothing", [eid])
            c.execute("commit")
            print(f"[json-path] location={loc} inserted_new={r}")

        a, b = uuid.uuid7(), uuid.uuid7()
        c.execute("insert into ent (id, entity_type) values (%s, 'n'), (%s, 'n')", [a, b])
        for scope in ("x", "x", "y"):
            eid = uuid.uuid7()
            c.execute("begin")
            r = c.execute(
                "insert into edge (entity_id, edge_type, from_id, to_id, properties) values (%s, 'scoped', %s, %s, %s) "
                "on conflict (from_id, to_id, (properties -> 'scope')) where edge_type = 'scoped' and spine_deleted_at is null "
                "do update set properties = excluded.properties returning entity_id = %s",
                [eid, a, b, json.dumps({"scope": scope}), eid],
            ).fetchone()[0]
            c.execute("insert into ent (id, entity_type) values (%s, 'edge') on conflict do nothing", [eid])
            c.execute("commit")
            print(f"[per-type expr] scope={scope} inserted_new={r}")

        for label, sql in (
            ("same key twice in one statement",
             "insert into det (entity_id, qid, host_id) values (gen_random_uuid(), 9, 'h'), (gen_random_uuid(), 9, 'h') "
             "on conflict (qid, host_id) where spine_deleted_at is null do update set payload = excluded.payload"),
            ("arbiter without the predicate",
             "insert into det (entity_id, qid, host_id) values (gen_random_uuid(), 9, 'h') "
             "on conflict (qid, host_id) do nothing"),
        ):
            try:
                c.execute("begin")
                c.execute(sql)
                c.execute("rollback")
                print(f"[error] {label}: accepted")
            except psycopg.Error as exc:
                c.execute("rollback")
                print(f"[error] {label}: {type(exc).__name__}: {str(exc).splitlines()[0]}")


def two_writers(rounds: int, *, sort: bool) -> None:
    """Two concurrent batches, N keys each, half shared, in opposite input orders, released together after
    staging. A third connection samples the whole server's lock table while they run."""
    reset()
    outcomes: list[str] = []
    peak = [0]
    stop = threading.Event()

    def sampler():
        with psycopg.connect(DSN, autocommit=True) as s:
            while not stop.is_set():
                peak[0] = max(peak[0], s.execute("select count(*) from pg_locks").fetchone()[0])
                time.sleep(0.01)

    t_total = 0.0
    for rnd in range(rounds):
        base = rnd * 2 * N
        shared = node_rows(base, base + N // 2)
        a = shared + node_rows(base + N, base + N + N // 2)
        b = list(reversed(shared)) + node_rows(base + 2 * N, base + 2 * N + N // 2)
        b = [(uuid.uuid7(), q, h, p) for _, q, h, p in b]
        bar = threading.Barrier(2)

        def run(rows, tag):
            try:
                with connect() as c:
                    r = batch_index(c, rows, sort=sort, hold=bar)
                outcomes.append(f"{tag}:ok(created={r['created']},found={r['found']},locks={r['locks']})")
            except psycopg.errors.DeadlockDetected:
                outcomes.append(f"{tag}:deadlock")

        smp = threading.Thread(target=sampler)
        smp.start()
        t0 = time.perf_counter()
        ts = [threading.Thread(target=run, args=(a, "A")), threading.Thread(target=run, args=(b, "B"))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        t_total += time.perf_counter() - t0
        stop.set()
        smp.join()
        stop.clear()
    dl = sum("deadlock" in o for o in outcomes)
    print(f"[two writers sort={sort}] rounds={rounds} outcomes: ok={len(outcomes) - dl} deadlock={dl} "
          f"live_dups={live_duplicates()} orphans={orphans()} peak_server_locks={peak[0]} mean_round_s={t_total / rounds:.2f}")
    print("   sample:", "; ".join(outcomes[:4]))


if __name__ == "__main__":
    which = sys.argv[3] if len(sys.argv) > 3 else "all"
    if which in ("all", "single"):
        single_writer()
    if which in ("all", "hot"):
        hot_stats()
    if which in ("all", "edges"):
        edges()
    if which in ("all", "functional"):
        functional()
    if which in ("all", "concurrent"):
        two_writers(5, sort=True)
        two_writers(5, sort=False)
