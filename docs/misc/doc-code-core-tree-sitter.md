---
title: Tree-Sitter As A Source Of Code Structure
date: 2026-11-01
status: observation
audience:
  - developer
  - llm
spec: none
related_docs:
  - docs/misc/code-core-v0.md
  - specs/spec-aws-core-crosscheck.md (aws-core-tap)
---

# Tree-sitter As A Source Of Code Structure

A companion to `docs/misc/code-core-v0.md`, the design seed for the planned `code_core` plugin. That note
puts source-code structure in `code_core` and keeps `computing_core` for runtime and execution. This one
records what tree-sitter offers as an *extractor* for `code_core`'s catalog (`code_package`, `code_file`,
`code_unit`, `software_package`). Written 2026-11-01 from a spike done for the AWS coverage work; if a
`code_core` repository is created, move this note into it.

Each claim names its method: **read** (a file was opened), **ran** (code was executed and its output seen),
**inferred** (reasoned, not checked).

## The four captures

Tree-sitter grammars ship `queries/tags.scm`, a query file that tags the definitions and references a
code-navigation tool needs, using capture names that are the same across languages. **Read**: the Go
grammar's file, from the installed package (`tree-sitter-go` 0.25.0); and, from the listing of each
repository's `queries/` directory only, that Python, Rust, Java, TypeScript and JavaScript also ship a
`tags.scm` (their contents were not read).

| Capture | What it marks in Go | A `code_core` counterpart |
| --- | --- | --- |
| `@definition.function` | a `function_declaration`, name captured as `@name` | `code_unit` with `kind = function` |
| `@definition.method` | a `method_declaration`, name captured as `@name` | `code_unit` with `kind = method` |
| `@definition.type` | a `type_spec`, name captured as `@name` | `code_unit` with `kind = class` (or a struct or interface kind) |
| `@reference.call` | a `call_expression` whose callee is an identifier or the field of a selector, name captured as `@name` | a `CALLS_CODE_UNIT` edge, once the callee is resolved |

Around them, the same Go file also tags a `package_clause` name, each `import_spec`, each `var_spec`, struct
and interface type specs (without a `@definition` name) and every `type_identifier` as `@reference.type`.
Capture names beginning `definition.` and `reference.` are the convention; `@name` marks the identifier and
`@doc` a leading comment.

Two cautions. The file uses predicates `#strip!` and `#set-adjacent!`, which belong to the tags library and
not the core query engine, so a Python binding must ignore or implement them. And the queries were **read, not
run**: the measurements below walk syntax-node types directly (`function_declaration`, `method_declaration`,
`type_spec`, `import_spec`, `call_expression`), which are the nodes the captures sit on.

## What it cannot give (inferred)

Tree-sitter parses syntax. It does not resolve names. A call to `Set` is the name `Set`; which `Set` is not
known. Within one package, matching by name is often right; across packages, through interfaces, embedded
types, generics, build tags or generated code, it is not, and a graph of `CALLS` edges built from names alone
is an approximation. Exact resolution needs a semantic index (the kind produced by SCIP, LSIF, a language
server, Joern or CodeQL; **none read**). `code-core-v0.md` already allows for this: `IMPORTS_CODE_UNIT` is
"when resolvable".

## Measured on one codebase (ran, 2026-11-01)

The Terraform AWS provider at commit `6979502b5176`, `internal/service` and `names` only, parsed with
`tree-sitter` 0.26.0 and `tree-sitter-go` 0.25.0 on Python 3.14 (prebuilt wheels).

| Measure | Value |
| --- | --- |
| Non-test Go files parsed | 4,588 (4,532 in the first run; the later count includes every directory) |
| Files with a parse error | 1 |
| Lines | about 1.2 million |
| `function_declaration` / `method_declaration` / `type_spec` | 27,970 / 7,053 / 4,904 |
| `import_spec` / `call_expression` | 59,259 / 321,343 |
| Time to parse and walk the whole tree | about 4 seconds |

Volume is the design constraint. One mature repository is hundreds of thousands of call nodes; a whole-program
graph would be the same kind of volume as the history and event records the AWS coverage work excludes with a
written reason. `code-core-v0.md` already keeps raw AST nodes, control flow and data flow out of scope, which is the right
line: use the syntax tree to *produce* `code_unit` rows, do not store it.

## How it maps to the code_core catalog (inferred)

Names below are those in `code-core-v0.md`.

| Layer | Contents | `code_core` types and edges |
| --- | --- | --- |
| L0 | package or repository snapshot, files, imports | `code_package`, `code_file`, `software_package`; `PACKAGES_FILE`, `IMPORTS_PACKAGE` |
| L1 | definitions, with an exported flag | `code_unit` (function, method, type); `DECLARES_CODE_UNIT` |
| L2 | calls, resolved within a package by name, for a named question only | `CALLS_CODE_UNIT` |
| L3 | calls resolved across packages | needs a semantic index |

Start at L0 and L1; add L2 for a specific question (which code calls a cryptographic API, which entry points
reach a vulnerable function). The extraction the grammar's own query gives is language-neutral at L1, so the
second language is a second grammar and a mapping table, not a second extractor.

## Use in the AWS collector cross-check (ran)

The AWS coverage work reads the Terraform provider's Go source as a reference for fields, read operations and
the API field behind each attribute (`d.Set("is_enabled", key.metadata.Enabled)`). To test whether the parser
was worth it, the same extraction was written twice over the same 1,233 SDK-style resources: with tree-sitter,
and with line-matching patterns of the kind a quick script would use.

| Extraction | Tree-sitter | String matching |
| --- | --- | --- |
| Schema attributes (top-level) | 11,457 found | 7,092 extra keys, in 575 of 1,233 resources; 57 missed in 52 |
| Resources whose attributes agree exactly | n/a | 620 of 1,233 (50%) |
| Keys set in the read path (`d.Set`) | 9,299 | 128 extra and 154 missed; 1,132 of 1,233 resources agree exactly (92%) |

The attribute gap is structural: nested block attributes look identical to top-level ones on a line, and
telling them apart means tracking brace depth, which is writing a parser. The `d.Set` gap is scope: tree-sitter
follows calls from the read function through helpers in other files, which a per-file pattern cannot. Where the
structure is flat (the generated registry, the `d.Set` keys) string matching is close; where nesting or scope
matters, it is not. Neither string matching nor tree-sitter is ground truth, so tree-sitter was checked against the provider's own
schema dump (**ran**: `terraform init` in an empty directory fetched the signed AWS provider v6.71.0, then
`terraform providers schema -json` wrote about 20 MB in 8 seconds; no credentials, nothing created). The dump
lists 1,746 resources, every attribute with type and Required, Optional, Computed, sensitive and deprecated
flags, nested blocks (6,311 attributes sit inside nested blocks), identity schemas for 562 resources, and
`tags_all` on 865. Ignoring `id`, `region` and `timeouts`, which the provider framework adds at runtime and
which are not in the Go source, the top-level attribute names agree exactly on 1,200 of 1,233 resources (97.3%).
The dump has 271 further names (mostly attributes injected by shared helper functions) and tree-sitter 58 the
dump lacks (not examined). The dump has no API response field for an attribute and no read operations, which
exist only in the code, so tree-sitter stays necessary for those two. Disagreements in the string-matching
comparison were sampled by name, not hand-checked.

## Open points

- Whether the Trailmark tool named in `code-core-v0.md` is itself built on tree-sitter: not checked.
- The licences of the tree-sitter packages and grammars: not checked.
- Reading HCL (Terraform configuration) with a tree-sitter grammar to put declared infrastructure on the grid
  beside the collected AWS: a candidate use, not tried.
- Which use case comes first (reachability, crypto inventory, declared infrastructure) decides the layer to build.
