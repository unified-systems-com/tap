"""Claim-table properties on a toy database (psycopg 3, raw SQL): size per row, DO UPDATE vs DO NOTHING +
FOR UPDATE, re-entrancy, two writers in opposite orders, pruning races, the lazy single-key caller.

python claim_toy.py DSN
"""

from __future__ import annotations

import hashlib
import sys
import threading
import time

import psycopg

DSN = sys.argv[1]
DDL = """
DROP TABLE IF EXISTS tap_identity_claim;
CREATE TABLE tap_identity_claim (
    fingerprint bytea PRIMARY KEY,
    entity_type varchar(255) NOT NULL,
    recipe smallint NOT NULL,
    claimed_at timestamptz NOT NULL DEFAULT now()
);
"""
UPDATE_SQL = (
    "INSERT INTO tap_identity_claim (fingerprint, entity_type, recipe) "
    "SELECT f, 'qualys_detection', 1 FROM unnest(%s::bytea[]) AS u(f) ORDER BY f "
    "ON CONFLICT (fingerprint) DO UPDATE SET claimed_at = now()"
)
NOTHING_SQL = (
    "INSERT INTO tap_identity_claim (fingerprint, entity_type, recipe) "
    "SELECT f, 'qualys_detection', 1 FROM unnest(%s::bytea[]) AS u(f) ORDER BY f ON CONFLICT (fingerprint) DO NOTHING"
)
LOCK_SQL = (
    "SELECT count(*) FROM (SELECT 1 FROM tap_identity_claim WHERE fingerprint = ANY(%s::bytea[]) "
    "ORDER BY fingerprint FOR UPDATE) l"
)


def fp(i: int) -> bytes:
    return hashlib.sha256(f"1\x1equalys_detection\x1f{{\"qid\":{i}}}".encode()).digest()


def keys(lo: int, hi: int) -> list[bytes]:
    return [fp(i) for i in range(lo, hi)]


def claim(cur, fps, mode):
    fps = sorted(set(fps))
    if mode == "update":
        cur.execute(UPDATE_SQL, [fps])
        return len(fps)
    cur.execute(NOTHING_SQL, [fps])
    return cur.execute(LOCK_SQL, [fps]).fetchone()[0]


def reset():
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(DDL)


def own_locks(cur):
    return cur.execute(
        "select count(*), count(*) filter (where locktype='advisory') from pg_locks where pid = pg_backend_pid()"
    ).fetchone()


def stats():
    with psycopg.connect(DSN, autocommit=True) as c:
        time.sleep(1.2)
        return c.execute(
            "select n_tup_ins, n_tup_upd, n_tup_hot_upd, n_dead_tup from pg_stat_user_tables "
            "where relname='tap_identity_claim'"
        ).fetchone()


def size_and_modes():
    for mode in ("update", "nothing"):
        reset()
        for label in ("first ", "resend"):
            with psycopg.connect(DSN) as c, c.cursor() as cur:
                t0 = time.perf_counter()
                got = claim(cur, keys(0, 20000), mode)
                locks = own_locks(cur)
                cur.execute("select pg_stat_force_next_flush()")
                c.commit()
                print(f"[mode={mode}] {label} 20,000 keys: s={time.perf_counter() - t0:.3f} locked={got} "
                      f"lock_entries={locks[0]} advisory={locks[1]}")
        ins, upd, hot, dead = stats()
        print(f"[mode={mode}] after first+resend: ins={ins} upd={upd} hot_upd={hot} dead={dead}")
    reset()
    with psycopg.connect(DSN) as c, c.cursor() as cur:
        for lo in range(0, 1_000_000, 100_000):
            claim(cur, keys(lo, lo + 100_000), "update")
        c.commit()
        cur.execute("vacuum analyze tap_identity_claim") if False else None
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("vacuum tap_identity_claim")
        heap, idx = c.execute(
            "select pg_relation_size('tap_identity_claim'), pg_indexes_size('tap_identity_claim')"
        ).fetchone()
    print(f"[size] 1,000,000 claims: heap={heap / 1e6:.1f} MB pkey={idx / 1e6:.1f} MB "
          f"per_claim={(heap + idx) / 1e6:.0f} bytes")


def reentrant():
    reset()
    with psycopg.connect(DSN) as c, c.cursor() as cur:
        cur.execute("set lock_timeout = '1s'")
        claim(cur, keys(0, 1000), "update")
        t0 = time.perf_counter()
        for i in (5, 500, 999):
            claim(cur, [fp(i)], "update")
        print(f"[re-entrant] re-claiming 3 held keys in the same transaction: s={time.perf_counter() - t0:.4f}, no wait")
        c.commit()


def two_writers(mode, rounds=5, n=20000):
    reset()
    outcomes = []
    for r in range(rounds):
        base = r * 3 * n
        shared = keys(base, base + n // 2)
        a = shared + keys(base + n, base + n + n // 2)
        b = list(reversed(shared)) + keys(base + 2 * n, base + 2 * n + n // 2)
        bar = threading.Barrier(2)

        def run(fps, tag, sort=True):
            try:
                with psycopg.connect(DSN) as c, c.cursor() as cur:
                    bar.wait()
                    if sort:
                        claim(cur, fps, mode)
                    else:  # unsorted control: claim one at a time in the given order
                        for f in fps[:2000]:
                            claim(cur, [f], mode)
                    time.sleep(0.05)
                    c.commit()
                outcomes.append("ok")
            except psycopg.errors.DeadlockDetected:
                outcomes.append("deadlock")

        ts = [threading.Thread(target=run, args=(a, "A")), threading.Thread(target=run, args=(b, "B"))]
        [t.start() for t in ts]
        [t.join() for t in ts]
    print(f"[two writers mode={mode} sorted] rounds={rounds}: ok={outcomes.count('ok')} deadlock={outcomes.count('deadlock')}")


def two_writers_unsorted(mode, rounds=5):
    """Control: each claims shared keys one at a time, in opposite orders (no sort)."""
    reset()
    dl = ok = 0
    for r in range(rounds):
        shared = keys(r * 100, r * 100 + 50)
        bar = threading.Barrier(2)
        res = []

        def run(order):
            try:
                with psycopg.connect(DSN) as c, c.cursor() as cur:
                    claim(cur, [order[0]], mode)
                    bar.wait()
                    for f in order[1:]:
                        claim(cur, [f], mode)
                    c.commit()
                res.append("ok")
            except psycopg.errors.DeadlockDetected:
                res.append("deadlock")

        ts = [threading.Thread(target=run, args=(shared,)), threading.Thread(target=run, args=(list(reversed(shared)),))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        dl += res.count("deadlock")
        ok += res.count("ok")
    print(f"[two writers mode={mode} one-at-a-time, opposite orders] rounds={rounds}: ok={ok} deadlock={dl}")


def lazy_caller(kind):
    """A lazy single-key caller (b then a) against a sorted batch ([a, b]), forced interleaving.
    kind = advisory (today) or claim."""
    reset()
    a, b = sorted([fp(1), fp(2)])
    res = {}
    lazy_has_b = threading.Event()

    def take(cur, f):
        if kind == "advisory":
            cur.execute("select pg_advisory_xact_lock(hashtextextended(encode(%s, 'hex'), 0))", [f])
        else:
            claim(cur, [f], "update")

    def lazy():
        try:
            with psycopg.connect(DSN) as c, c.cursor() as cur:
                take(cur, b)
                lazy_has_b.set()
                time.sleep(0.5)  # the batch takes a and queues on b
                take(cur, a)
                c.commit()
            res["lazy"] = "ok"
        except psycopg.errors.DeadlockDetected:
            res["lazy"] = "deadlock"

    def batch():
        lazy_has_b.wait()
        try:
            with psycopg.connect(DSN) as c, c.cursor() as cur:
                for f in (a, b):
                    take(cur, f)
                c.commit()
            res["batch"] = "ok"
        except psycopg.errors.DeadlockDetected:
            res["batch"] = "deadlock"

    ts = [threading.Thread(target=lazy), threading.Thread(target=batch)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    print(f"[lazy caller vs sorted batch, {kind}] {res}")


def prune_races():
    reset()
    with psycopg.connect(DSN) as c, c.cursor() as cur:
        claim(cur, keys(0, 1000), "update")
        c.commit()
    prune = (
        "DELETE FROM tap_identity_claim WHERE fingerprint IN (SELECT fingerprint FROM tap_identity_claim "
        "ORDER BY fingerprint FOR UPDATE SKIP LOCKED LIMIT 10000)"
    )
    # 1. a held claim is never pruned
    with psycopg.connect(DSN) as holder, holder.cursor() as hc:
        claim(hc, keys(0, 100), "update")
        with psycopg.connect(DSN, autocommit=True) as p:
            n = p.execute(prune).rowcount
            left = p.execute("select count(*) from tap_identity_claim").fetchone()[0]
        holder.commit()
    print(f"[prune] while 100 claims are held: pruned={n}, left={left} (the held ones)")
    # 2. an uncommitted prune and a claimant of the same key (DO UPDATE): the claimant waits, then holds a row
    with psycopg.connect(DSN) as p, p.cursor() as pc:
        pc.execute(prune)
        res = {}

        def claimant():
            with psycopg.connect(DSN) as c, c.cursor() as cur:
                t0 = time.perf_counter()
                claim(cur, keys(0, 10), "update")
                res["waited_s"] = round(time.perf_counter() - t0, 2)
                res["held"] = cur.execute(
                    "select count(*) from tap_identity_claim where fingerprint = any(%s)", [keys(0, 10)]
                ).fetchone()[0]
                c.commit()

        t = threading.Thread(target=claimant)
        t.start()
        time.sleep(0.5)
        p.commit()
        t.join()
    print(f"[prune] claimant (DO UPDATE) racing an uncommitted prune: {res}")
    # 3. DO NOTHING then FOR UPDATE, with a prune committed between the two statements
    with psycopg.connect(DSN) as c, c.cursor() as cur:
        claim(cur, keys(100, 110), "update")
        c.commit()
    with psycopg.connect(DSN) as c, c.cursor() as cur:
        cur.execute(NOTHING_SQL, [keys(100, 110)])
        with psycopg.connect(DSN, autocommit=True) as p:
            p.execute("delete from tap_identity_claim where fingerprint = any(%s)", [keys(100, 110)])
        got = cur.execute(LOCK_SQL, [keys(100, 110)]).fetchone()[0]
        c.commit()
    print(f"[prune] DO NOTHING + FOR UPDATE with a prune between them: locked {got} of 10 (must re-claim)")


if __name__ == "__main__":
    size_and_modes()
    reentrant()
    for m in ("update", "nothing"):
        two_writers(m)
        two_writers_unsorted(m)
    lazy_caller("advisory")
    lazy_caller("claim")
    prune_races()
