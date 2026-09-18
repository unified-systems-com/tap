"""The cascade confirmation corpus — known-answer cascade scenarios with a reference oracle.

A committed set of small, eyeballable graphs, each with one delete operation and the
hand-authored outcome it must produce: which nodes and edges retire, which do not, what
the records say, or which refusal comes back with nothing written. The corpus runs in the
lanes and confirms the contained cascade (``req-grid-service-delete-cascade``) still does
exactly what it did — no more, no less — the way the openCypher TCK and Neo4j's own
corpora hold a query engine steady over time. The shape deliberately mirrors Gridkin
(``tap-plugin-gryphon-playground``, ``spec-gridkin-v0.md``): scenarios are data, the
expected answer is authored by a human, and an independent model (``model_oracle``) must
agree with every hand answer at load time, so a wrong expectation is loud, not quietly
copied from the code under test. Issue# 578 - tap.
"""
