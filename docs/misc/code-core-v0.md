---
spec: pending-code-core-plugin-spec
audience: [developer, llm]
covers:
  - future-code-core-plugin
  - plugins/computing_core/specs/spec-computing-core-v0.md
  - plugins/aws_core/specs/spec-aws-core-collector-v0.md
  - docs/misc/code-core-v0.md
update-triggers:
  - A code_core plugin spec is created
  - Trailmark's data model changes materially
  - TAP gains a durable file-reference or source-artifact storage mechanism
  - TAP starts importing third-party code-analysis output beyond the SamSite demo path
  - Vulnerability-management modeling introduces package or vulnerability nodes
assumes:
  - Reader is preparing a future code_core plugin build-out
  - Reader knows TAP graph mutations go through GRIFT/service-layer paths
  - Reader understands computing_core is runtime/execution substrate, not source-code structure
provides: |
  A decision record and starting design for a future code_core plugin. It captures
  the SamSite-driven v0 slice: Trailmark-aligned code package/file/unit/package
  dependency modeling, metadata-only files, snapshot package semantics, version-null
  dependency gaps, and deferred annotations/source storage.
---

# Code Core v0 Design Seed

Spec: pending future `code_core` plugin spec.

## Purpose

This document is a seed for a future `code_core` plugin build-out. It is not the
plugin spec yet. Its job is to preserve the design decisions made while planning
the SamSite Lambda drill-in path, so a future session can pull this file in and
turn it into a real plugin specification.

The immediate product pressure is the SamSite demo: a user should be able to
drill from an AWS Lambda function into the code-shaped contents of the deployed
function package and see enough structure to understand the program. The durable
platform direction is broader: code graphs, package dependencies, imports, and
future vulnerability-management surfaces.

## Strategic Boundary

`code_core` should be a distinct plugin from `computing_core`.

The conceptual split:

| Plugin | Role |
| --- | --- |
| `computing_core` | Runtime and execution substrate: programs, files, ports, IPs, connections, keys. |
| `code_core` | Source/package/code-structure substrate: packages, files, units, imports, dependencies. |

No v0 plugin dependency on `computing_core` is expected. Future work may connect
the two once TAP has a durable file-reference mechanism or runtime-to-code
correlation use cases, but v0 should model code in abstract space.

AWS/Lambda extraction is also orthogonal. `code_core` should not care whether
source metadata came from Lambda `GetFunction`, a Git checkout, a manual GRIFT
seed, Trailmark output, or a future analysis runner container.

## Prior Art And Alignment

Trailmark is the primary alignment target for v0. It models code as a graph with
code units and code edges rather than forcing one model per language construct.
That maps well to TAP's graph shape.

The v0 TAP model should align with Trailmark concepts where they are strong:

- code graph provenance
- code units with kinds such as function, method, class, module, interface
- code edges such as calls, imports, inherits, implements, contains
- entrypoint metadata

TAP should not blindly copy Trailmark where Rampart needs more durable semantics.
In particular, Trailmark's dependency surface is too light for vulnerability
management. TAP should model software packages as first-class nodes.

Package identity should align with Package URL (purl) where possible. PURL has
the form:

```text
pkg:type/namespace/name@version?qualifiers#subpath
```

Examples:

```text
pkg:pypi/boto3@1.40.0
pkg:npm/%40scope/name@1.2.0
pkg:golang/github.com/gravitational/teleport@v17.0.0
```

When TAP eventually needs internal packages, private repositories, deployment
artifacts, or other non-standard package identifiers, define a TAP-owned package
identifier convention instead of overloading purl badly.

References:

- Trailmark announcement: https://blog.trailofbits.com/2026/04/23/trailmark-turns-code-into-graphs/
- Trailmark package: https://pypi.org/project/trailmark/
- Package URL specification: https://ecma-tc54.github.io/ECMA-427/multipage/purl-specification.html

## v0 Scope

v0 is Python-first and language-neutral by shape. Do not expand into general
multi-language semantics until a second language creates real demand.

In scope:

- source/deployment package snapshots
- metadata-only source files
- code units such as functions, methods, classes, and modules
- declared package dependencies
- observed imports/usages
- entrypoint metadata on code units
- version-specific software package nodes, including unresolved version gaps

Out of scope:

- source text storage
- durable local file storage
- raw AST node modeling
- control-flow graph modeling
- data-flow graph modeling
- Trailmark annotations as first-class TAP objects
- vulnerability nodes and package-to-vulnerability edges
- arbitrary repository-scale analysis execution
- a Trailmark runner container
- runtime trace to code graph joins

## Model Catalog

### `code_package`

A snapshot of one source/deployment bundle.

Examples:

- a Lambda deployment ZIP snapshot
- a Git checkout at one commit
- a Python wheel snapshot
- a future container source snapshot
- a manually seeded SamSite demo package

`code_package` is snapshot-only. It should not represent a logical package
across versions.

Candidate fields:

| Field | Notes |
| --- | --- |
| `name` | Human-readable label. |
| `package_kind` | `lambda_zip`, `git_checkout`, `wheel`, `source_tree`, `synthetic`, etc. Keep vocabulary small at first. |
| `language` | `python` for v0; nullable/blank for mixed or unknown. |
| `source_ref` | Unresolved string reference to where the source/package came from. No dereference mechanism in v0. |
| `snapshot_ref` | Optional source snapshot identifier such as commit SHA, Lambda code hash, or human-authored demo label. |
| `configuration` | Lossless-ish metadata about extraction/import, not raw source text. |

### `code_file`

Metadata for a file in a code package.

v0 does not store source text. This is a hard boundary until TAP has a source
storage/file-reference mechanism.

Candidate fields:

| Field | Notes |
| --- | --- |
| `name` | Display name, often the basename. |
| `file_path` | Path within the package snapshot. |
| `language` | `python` for SamSite `.py` files. |
| `file_type` | Lightweight type such as `source`, `manifest`, `lockfile`, `config`, `unknown`. |
| `source_ref` | Unresolved string reference to the source object/path. |
| `size_bytes` | Optional. |
| `configuration` | Extraction metadata, parser messages, skipped-content notes. |

Identity in v0 can be `code_package` + `file_path`. Add a future note to consider
hash-based or snapshot-stable identity once source storage and change tracking
matter.

### `code_unit`

A Trailmark-aligned code unit: function, method, class, module, interface, enum,
namespace, or similar source-level construct.

Candidate fields:

| Field | Notes |
| --- | --- |
| `name` | Local name. |
| `qualified_name` | Fully qualified name where known. |
| `kind` | Trailmark-aligned unit kind such as `function`, `method`, `class`, `module`. |
| `language` | `python` in v0. |
| `signature` | Optional rendered signature. |
| `parameters` | Optional JSON list. |
| `return_type` | Optional string. |
| `line_start` | 1-based line start. |
| `line_end` | 1-based line end. |
| `docstring` | Optional, but watch size; may be blank in v0. |
| `is_entrypoint` | Boolean. |
| `entrypoint_kind` | `lambda_handler`, `cli`, `http_route`, `test`, `scheduled_job`, etc. |
| `entrypoint_source` | `aws_lambda.handler`, `trailmark`, `manual`, `framework_detector`, etc. |
| `configuration` | Parser/extractor metadata. |

Identity in v0 can be `qualified_name` + `file_path` + `line_start`/`line_end`.
This intentionally accepts churn when code moves. Revisit identity when code
history and refactoring-aware analysis become important.

Entrypoints are properties on `code_unit` in v0. Reconsider node-ifying
entrypoints if they become independently lifecycle-bearing, annotatable, or
heavily queried.

### `software_package`

A version-specific software package node used for dependency and import
modeling.

Each version is its own node because real environments will often carry multiple
versions of the same package across systems.

Candidate fields:

| Field | Notes |
| --- | --- |
| `ecosystem` | `pypi`, `npm`, `golang`, etc. |
| `namespace` | Optional ecosystem-specific namespace. |
| `name` | Package name. |
| `version` | Nullable. Null is the explicit unresolved-version convention. |
| `purl` | PURL string when representable. Versionless purl is allowed for unresolved imports. |
| `declared_version` | Raw declared constraint/range when this node comes from a manifest. |
| `resolved_version` | Concrete resolved version when known. |
| `configuration` | Package manager metadata, source hints, extraction context. |

For exact versions:

```text
ecosystem = pypi
name = boto3
version = 1.40.0
purl = pkg:pypi/boto3@1.40.0
```

For unresolved imports:

```text
ecosystem = pypi
name = boto3
version = null
purl = pkg:pypi/boto3
```

This makes dependency gaps easy to query: `version is null`.

## Edge Catalog

Use TAP-style mechanical edge names rather than Trailmark's bare names. Preserve
Trailmark semantics while translating edge slugs into explicit predicates.

Candidate v0 edges:

| Edge | Direction | Meaning |
| --- | --- | --- |
| `PACKAGES_FILE` | `code_package -> code_file` | A package snapshot includes a file. |
| `DECLARES_CODE_UNIT` | `code_file -> code_unit` | A file declares a code unit. |
| `CALLS_CODE_UNIT` | `code_unit -> code_unit` | One unit calls another unit. |
| `IMPORTS_CODE_UNIT` | `code_unit -> code_unit` | One unit imports another modeled unit, when resolvable. |
| `EXTENDS_CODE_UNIT` | `code_unit -> code_unit` | One unit extends/inherits another. |
| `IMPLEMENTS_CODE_UNIT` | `code_unit -> code_unit` | One unit implements an interface/trait/protocol. |
| `DECLARES_DEPENDENCY` | `code_package -> software_package` | Package metadata declares a dependency. |
| `IMPORTS_PACKAGE` | `code_file` or `code_unit -> software_package` | Source code actually imports/uses a package. |

`DECLARES_DEPENDENCY` and `IMPORTS_PACKAGE` are intentionally distinct.

Example:

```text
requirements.txt says boto3==1.40.0
=> code_package --DECLARES_DEPENDENCY--> software_package(pkg:pypi/boto3@1.40.0)

app.py says import boto3
=> code_file/code_unit --IMPORTS_PACKAGE--> software_package(pkg:pypi/boto3@1.40.0)
```

If an import can be observed but not resolved to an exact version:

```text
app.py says import boto3
=> code_file/code_unit --IMPORTS_PACKAGE--> software_package(pkg:pypi/boto3, version=null)
```

The declaration and observed usage may disagree. That disagreement is useful and
should remain visible.

## Trailmark Run Provenance

Do not model `code_graph` as a v0 node. Treat it as provenance for the analysis
run.

Eventually, when Trailmark runs as part of a collector-like action, stash the
Trailmark run metadata in batch metadata:

- Trailmark version
- parser/language selection
- source root/source reference
- counts of packages/files/units/edges
- warnings/errors
- extraction options

Do not mirror raw Trailmark fragments into each node's `configuration` in v0.
The transform from Trailmark-like output into TAP nodes is expected to be
straightforward. If raw output retention becomes important, store the whole
output as a run artifact/provenance object later rather than smearing fragments
across every node.

## SamSite Demo Path

The SamSite use case should be allowed to seed a small graph directly, without
committing to a full code-analysis runtime.

Desired visible path:

```text
aws_lambda
  --RUNS_CODE_PACKAGE--> code_package
  --PACKAGES_FILE--> code_file
  --DECLARES_CODE_UNIT--> code_unit
  --IMPORTS_PACKAGE--> software_package
```

The cross-plugin edge from `aws_lambda` to `code_package` may live in `aws_core`,
`code_core`, or a small integration spec later. Do not force this doc to settle
cross-plugin ownership before the plugin exists.

For the Sam demo, the important affordances are:

- show the Lambda has a package snapshot
- show the Python file metadata
- show the handler/function as a code unit
- show which libraries/packages are declared or imported
- avoid storing source text
- avoid running a generalized analysis engine in the critical path

## Future Work

### Trailmark Runner

Trailmark can likely run in-process for tiny, trusted demo inputs because it is
Python and exposes programmatic APIs. The durable architecture should still
leave room for a separate analysis runner container once TAP processes arbitrary
customer code.

Potential staged path:

1. Manual/demo GRIFT seed from inspected SamSite source.
2. Bounded in-process collector/action for trusted local/Lambda packages.
3. Separate `code-analysis-runner` container that receives a source bundle/ref,
   runs Trailmark, and returns Trailmark JSON or GRIFT.

### Source Storage And File References

`code_file` is metadata-only until TAP has a durable file/source reference
mechanism. When that mechanism exists, revisit whether source text, checksums,
renderable excerpts, or external source references belong on `code_file`.

Add `sha256` or a similar hash field later when file identity, source integrity,
and diff/history behavior need it.

### Tree-Sitter Extraction

Tree-sitter grammars ship a language-neutral tags query whose captures (function, method and type
definitions, and call references) line up with `code_unit` kinds and `CALLS_CODE_UNIT`. What the
captures give, what a syntax parser cannot resolve, measured volume and a comparison with string
matching are in `docs/misc/doc-code-core-tree-sitter.md`.

### Annotations And Third-Party Analysis Labels

Trailmark supports annotations as a way to attach analysis-produced labels or
notes to code units. `code_core` v0 deliberately does not model annotations
because SamSite only needs package/file/unit/dependency structure and entrypoint
metadata.

When TAP begins importing richer third-party code-analysis output, revisit
annotations as a first-class concept. At that point decide whether annotations
should be nodes, edge properties, or a more general TAP finding/evidence-style
mechanism.

### Vulnerability Management

`software_package` is designed with future vulnerability management in mind, but
v0 should not define vulnerability nodes or package-to-vulnerability edges.
Mention that future work explicitly in the eventual plugin spec and let the
first vulnerability use case drive the shape.

### Multi-Language Expansion

v0 is Python-first. Expand to a second language only when a real target creates
demand. Trailmark's model is broad enough to guide that expansion, but TAP should
avoid pretending language-neutral behavior is implemented before it has two
languages under test.
