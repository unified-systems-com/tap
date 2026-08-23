# Vendored SBOM schemas (req-cicd-sbom-11)

Pinned, committed copies — the conformance gate must never fetch its schemas from the
network at publish time (that would be its own supply-chain hole).

| File | Source | Version |
| --- | --- | --- |
| bom-1.6.schema.json | github.com/CycloneDX/specification @ 1.6.1 | CycloneDX 1.6 |
| spdx.schema.json | github.com/CycloneDX/specification @ 1.6.1 (license-id enum, $ref'd by bom-1.6) | — |
| jsf-0.82.schema.json | github.com/CycloneDX/specification @ 1.6.1 (signature schema, $ref'd by bom-1.6) | JSF 0.82 |
| spdx-2.3.schema.json | github.com/spdx/spdx-spec @ support/2.3 | SPDX 2.3 |

Bump procedure: replace the file(s) from the tagged upstream release, update this table,
and let `tap/tests/test_sbom_generate.py` prove the tooling still validates against them.
