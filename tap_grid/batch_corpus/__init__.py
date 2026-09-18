"""The batch playground — known-answer GRIFT import scenarios with a reference oracle.

A committed set of small, eyeballable import scenarios, each naming a starting grid, one or
more GRIFT documents imported in order, and the exact outcome they must produce: which rows
exist afterwards (by name, with liveness and version), which batches committed, skipped or
failed, which events were recorded on which batch, and the exact issue codes and paths of a
refusal — with nothing else written. The shape is the cascade confirmation corpus's
(``tap_grid/cascade_corpus``, Issue# 578 - tap): scenarios are data, the expected answer is
authored by a human, and an independent model (``model_oracle``) must agree with every hand
answer at load time, so a wrong expectation is loud, not quietly copied from the importer.
Issue# 603 - tap, ruled after the intra-batch duplicate gap (Issue# 602 - tap) was found by a
question rather than a test.
"""
