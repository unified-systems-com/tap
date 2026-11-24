"""The index path at 200,000 keys on the default-64 server: lock count stays flat."""
import sys
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
sys.path.insert(0, "/proof")
import proto
proto.reset()
with proto.connect() as c:
    print(f"[index] first  N={proto.N}:", proto.fmt(proto.batch_index(c, proto.node_rows(0, proto.N))))
    print(f"[index] resend N={proto.N}:", proto.fmt(proto.batch_index(c, proto.node_rows(0, proto.N, "q"))))
print("live_dups", proto.live_duplicates())
