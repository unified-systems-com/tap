# tap_web HTML Panel Specification

## Philosophy

A page sometimes wants rich text that no other panel sets well: a styled explanation, a callout, a small table, a figure with a caption. The Text panel shows plain text only (`req-web-panel-render-content.sec`: Django auto-escaping, so markup is never markup). Where the text the grid holds is structured text (an advisory, a collected description, a report body written by a person or a tool), the choice is between rendering it block by block, which needs a block vocabulary for every source, and **cleaning the markup it already is**. TAP cleans it.

The markup is untrusted wherever it came from. A node field a collector filled from a scanner, a Search row, and a config string that anyone with edit access to the panel can change are all attacker-influenced, and the panel treats all three the same: where the markup came from earns it no trust. The panel shows it with the look of the site and the guarantee that it cannot run script, load anything from elsewhere, send anything anywhere or change how the rest of the page looks.

The panel is **tap_web-owned** so any plugin can use it without shipping a sanitizer of its own. It was built first in `stackarmor-vdr-tap` (`req-stackarmor-vdr-panel-html`, requested by George 2026-10-27, "meant for the core" 2026-10-30) and moved here unchanged except for its slug, its stylesheet prefix and its class names.

### Cross-References

- [`tap_web/specs/spec-web-panel.md`](spec-web-panel.md) — Panel model and type-registration contract.
- [`tap_web/specs/spec-web-panel-security.md`](spec-web-panel-security.md) — the baseline contract this panel goes beyond: it is the one panel that renders markup, so it carries its own.
- [`tap_web/specs/spec-web-panels-chart.md`](spec-web-panels-chart.md) — sibling Search-fed panel; same data path (`tap_web.panels.search_rows`).

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Untrusted By Default | Markup from config, from a Search row or from anywhere else is cleaned the same way, on every render |
| 2. | Closed Vocabulary | What may pass is a fixed set of named features; a panel can only narrow it, never name a tag, attribute or scheme the vocabulary does not hold |
| 3. | Fails Closed | A fault, a missing library or an over-limit document shows a message and no content, never the raw markup |
| 4. | Two Independent Checks | A maintained sanitizer cleans; the standard library's parser reads the output and must find nothing outside the policy |
| 5. | Data, Not Code | A panel is a Panel node, a config and optionally a Search; no per-panel Python or JavaScript |
| 6. | Themed, Contained | Colours come from the theme's palette tokens, so light and dark are free; the content is contained to its box; no inline style or script is needed |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-panels-html-panel-type | [HTML Panel Type](#html-panel-type) | Implemented | `HtmlPanelType` registered under slug `html`; described config schema |
| req-web-panels-html-clean | [The Cleaner](#the-cleaner) | Implemented | Closed feature vocabulary, per-panel narrowing, nh3 plus a second independent check, limits |
| req-web-panels-html-render | [Rendering](#rendering) | Implemented | Cleaned every render, fails closed, one trusted step, the same from both sources |
| req-web-panels-html-style | [Styling](#styling) | Implemented | Palette tokens only (no colour literal, no dark block), scoped under the panel root, contained, print block |
| req-web-panels-html-dependency | [The Dependency](#the-dependency) | Implemented | `nh3` in `pyproject`; the sanitizer decision recorded |

---

### HTML Panel Type
----
RID: `req-web-panels-html-panel-type`

Status: `Implemented`

`HtmlPanelType` (slug `html`, view `tap_web/panels/html.html`, css `tap_web/css/panel-html.css`, no JavaScript) is registered in `tap_web/apps.py` `ready()`. The config names exactly one source:

- `html`: a string written in the panel's config.
- `field`: the row field of the Search the panel is bound to (the `USES_SEARCH` edge, `tap_web.panels.search_rows`) that holds the markup, with an optional `row` index, default 0. The Search runs once per render with the page's query parameters.

The other keys only narrow the cleaner (see The Cleaner): `features`, `classes`, `link_schemes`, `link_hosts`, `image_prefixes`, `max_bytes`; `hide_header` hides the header bar. A config that names two sources, none, an unknown key, or a value outside its vocabulary is invalid, and the panel says so instead of rendering.

Reading is the Search's. The panel adds no access of its own; what a viewer sees through it is what the bound Search returns to them.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-html-panel-type-1 | Registered With A Described Config | Implemented | The panel type is registered under `html`; its config schema describes every property, requires exactly one of `html` and `field`, refuses unknown keys, and bounds `html` to the size ceiling. | As `req-web-panels-chart-config`. |

### The Cleaner
----
RID: `req-web-panels-html-clean`

Status: `Implemented`

`tap_web/panels/html/sanitize.py` holds the cleaning. The file imports nothing from Django and nothing from any plugin. `clean(html, policy)` returns the cleaned markup, the number of start tags it removed and the element count and depth, or raises `HtmlRefused` (an over-limit document, or output that failed the second check) or `CleanerUnavailable` (the library cannot be imported).

#### Threat Model

| Threat | Example | Closed by |
| --- | --- | --- |
| Script execution | `<script>`, `onerror=`, `javascript:` URLs, `<svg onload>` | Tags and attributes outside an allowlist are dropped; only `http`, `https` and `mailto` URL schemes pass; no SVG or MathML. |
| Mutation XSS | Markup that is safe to the sanitizer and unsafe once the browser re-parses it | A maintained sanitizer built on a browser-grade HTML5 parser, no SVG, MathML or `template`, and the output checked by a second parser. |
| Loading from elsewhere | `<img src=https://x/pixel>`, CSS `url()`, `<link>`, `<iframe>` | No external resource: `img` may point only at this site; no `style`, `link`, `iframe`, `object`, `embed`, `audio` or `video`. |
| Sending data out | `<form action=https://x>`, `<meta http-equiv=refresh>`, `<a ping>` | No `form`, `input`, `button`, `meta` or `base`; no `ping`. |
| Restyling or covering the page | `style="position:fixed;inset:0"`, a fake sign-in box over the real page | No `style` attribute and no `<style>`; `class` limited to a fixed list the panel styles; the panel's own CSS contains the content to its box. |
| Name collisions | `<a id=config>`, `name=location` shadowing a script's globals | No `id`, `name` or `form` attribute passes. |
| Tab-napping | `target=_blank` without `rel` | No `target`; every link gets `rel="noopener noreferrer nofollow"`. |
| Resource exhaustion | A very large or deeply nested document | A size limit, an element limit and a depth limit, each refusing the whole document. |
| A bypass that comes back | A sanitizer fix that never reaches stored content | Cleaning is done on every render, never once on write, so a fixed sanitizer fixes what is already stored. |

#### Implementation

- **An allowlist, not a blocklist,** built from a closed vocabulary of named features (the table below). Everything not allowed is dropped; the content of `script`, `style`, `iframe`, `object`, `embed`, `noscript`, `template`, `svg`, `math`, `select`, `textarea`, `form` and similar tags is dropped with the tag. Comments, processing instructions and doctype are dropped. No tag has `id`, `name`, `form`, `style`, `target`, an event handler, `srcset` or `ping`. `lang` and `dir` are allowed on any allowed tag.
- **Per-panel features.** The config may carry `features` (default every feature but `images`; `text` is always on), `classes` (a subset of the ten, default all), `link_schemes` (a subset of `http`, `https`, `mailto`, default all), `link_hosts` (host names an `http` or `https` link may point at, default any), `image_prefixes` (path prefixes on this site an image may come from, default `/static/`) and `max_bytes` (at most 262144, default 65536). A value outside its vocabulary makes the config invalid. A page can therefore give a free-text panel only paragraphs and links, a report panel tables and headings, and a figure panel images from one folder, each by data.
- **The second check.** After the library cleans, the output is read again by the standard library's HTML parser and every tag, attribute and URL is checked against the same policy; anything outside it, a comment, or an unbalanced tree refuses the document. The element and depth limits (2000 and 20) are measured on this read. A bug in the library that let something through is stopped here.

#### Features

| `feature` | Tags | Attributes |
| --- | --- | --- |
| `text` | `p`, `br`, `strong`, `em`, `b`, `i`, `u`, `s`, `sub`, `sup`, `span`, `div` | |
| `headings` | `h2`, `h3`, `h4` | |
| `lists` | `ul`, `ol`, `li`, `dl`, `dt`, `dd` | |
| `tables` | `table`, `thead`, `tbody`, `tfoot`, `tr`, `th`, `td`, `caption` | `th`: `colspan`, `rowspan`, `scope`; `td`: `colspan`, `rowspan` |
| `code` | `code`, `pre`, `kbd` | |
| `quotes` | `blockquote`, `hr` | |
| `figures` | `figure`, `figcaption` | |
| `disclosure` | `details`, `summary` | |
| `links` | `a` | `a`: `href`, `title` |
| `images` | `img` | `img`: `src`, `alt`, `width`, `height`, `title` |

The ten classes are `tap-html-lead`, `tap-html-muted`, `tap-html-callout`, `tap-html-callout-note`, `tap-html-callout-warning`, `tap-html-columns`, `tap-html-badge`, `tap-html-figure`, `tap-html-table` and `tap-html-quote`. A link may point at a path on this site, a `#fragment`, or an `http`, `https` or `mailto` URL, with no whitespace, control character or backslash in it; an image may come only from a path on this site under an allowed prefix. Widths, heights and spans are digits only.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-html-clean-1 | Allowlist Only | Implemented | Every tag in the output is in the tag allowlist and every attribute is allowed on its tag; the test parses the output with a second, independent parser and walks every element. | A check that does not trust the cleaner it checks. |
| req-web-panels-html-clean-2 | Script Cannot Run | Implemented | The OWASP filter-evasion vectors, event-handler, `javascript:`, `data:` and `vbscript:` URL vectors, and SVG and MathML vectors leave no `script` element, no `on*` attribute and no URL with a scheme outside `http`, `https` and `mailto`. | The corpus is a test fixture with its source named in the test. |
| req-web-panels-html-clean-3 | Mutation Vectors | Implemented | Known mutation-XSS payloads (nested `noscript`, `style` and `select`, namespace confusion, `<math>` and `<svg>` breakouts) clean to the same output when the output is cleaned again. | Idempotence: `clean(clean(x)) == clean(x)`. |
| req-web-panels-html-clean-4 | Nothing Is Fetched | Implemented | No output element has a `src` or `href` that points off this site except an `a` `href` to `http`, `https` or `mailto`; there is no `style`, `link`, `iframe`, `object`, `embed`, `form`, `meta` or `base`, and no `ping`. | Beacons and exfiltration. |
| req-web-panels-html-clean-5 | Links Are Safe | Implemented | Every `a` in the output has `rel="noopener noreferrer nofollow"` and no `target`. | |
| req-web-panels-html-clean-6 | No Names | Implemented | No output element has `id`, `name` or `form`. | DOM clobbering. |
| req-web-panels-html-clean-7 | Classes Are The Panel's | Implemented | Only the ten listed classes survive, and a class outside them is removed without removing its element. | |
| req-web-panels-html-clean-8 | Limits Refuse | Implemented | A document over the byte, element or depth limit raises `HtmlRefused`. | A depth bomb must not reach the browser or exhaust the parser. |
| req-web-panels-html-clean-9 | The Second Check Stops The Library | Implemented | When the library's output contains anything outside the policy, the document is refused instead of shown. | A test replaces the library's result with markup that breaks the policy. |
| req-web-panels-html-clean-10 | The Allowlist Is The One In This Spec | Implemented | The configured vocabulary equals the Features table above, feature by feature, and every class named there exists, so a library default or a code edit cannot widen the allowlist without this spec changing with it. | The 2026 `ammonia` advisories are all in features this vocabulary does not hold. |
| req-web-panels-html-clean-11 | Features Narrow Per Panel | Implemented | A panel's `features`, `classes`, `link_schemes`, `link_hosts` and `image_prefixes` narrow what is allowed: a feature that is off has its tags stripped and its text kept, images are off unless asked for, and a name outside the vocabulary or a value past a ceiling makes the config invalid. | The vocabulary is the ceiling; no config can reach a forbidden tag. |

### Rendering
----
RID: `req-web-panels-html-render`

Status: `Implemented`

- **Cleaned every render.** The panel cleans the markup each time it renders and stores nothing cleaned.
- **The one trusted step.** The cleaned string is marked safe in exactly one place, `_safe` in `tap_web/panels/html/__init__.py`; the template prints that one variable and every other variable with Django's autoescaping.
- **Fails closed.** If cleaning raises, the library is missing or the document is over a limit, the panel shows a message saying so and no content; it never falls back to the raw markup or to the markup as text. A Search that fails, or a row or field that is missing or not text, shows a message and raises nothing; the error text is logged by class only and never shown.
- **Script and style.** The template holds no `script` element and no `style` attribute or element, and the stylesheet is the only style source, so the panel works under a Content Security Policy that forbids `unsafe-inline`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-html-render-1 | Cleaned Every Render | Implemented | The panel cleans the markup each time it renders and stores nothing cleaned; a fixture whose cleaner is changed between two renders shows the second cleaner's output. | The config schema has no field to hold a cleaned copy. |
| req-web-panels-html-render-2 | Fails Closed | Implemented | When the cleaner raises, the library cannot be imported or a document is over a limit, the panel renders a visible message and no content, and neither the raw markup nor an escaped copy of it appears. | |
| req-web-panels-html-render-3 | One Trusted Step | Implemented | The panel's package contains exactly one `mark_safe`, in its context builder, applied to the cleaner's output; the template uses no `safe` filter and no `autoescape off`. | A grep test. |
| req-web-panels-html-render-4 | The Same From Both Sources | Implemented | The same markup given as the `html` config string and as the `field` of a bound Search's row yields identical output. | The source earns no trust. |
| req-web-panels-html-render-5 | Failures Of The Search | Implemented | A Search that fails, or a row or field that is missing or not text, renders a visible message and raises nothing. | As `req-web-panels-chart-render`. |
| req-web-panels-html-render-6 | Needs No Script Or Inline Style | Implemented | The template holds no `script` element and no `style` attribute or element, and neither does the rendered output of the vectors. | |

### Styling
----
RID: `req-web-panels-html-style`

Status: `Implemented`

`panel-html.css` scopes every rule under `.tap-panel--html`, takes every colour from the palette tokens in `theme.css` (`rgb(var(--tap-slate-800))` and the like), which the theme redefines for dark, so it has no colour literal and no dark block of its own (`req-web-theme-surfaces-1`); it sets the typography for the allowed tags and the ten classes, contains its content (`overflow` clipped, `contain: content`), reflows its two-column class in a narrow panel, and has a print block.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-html-style-1 | Scoped, Themed, Printable | Implemented | Every selector in the stylesheet is under `.tap-panel--html`, it holds no hex or `rgb()` colour literal and draws its colours from the palette tokens, and it has a print block. | |

### The Dependency
----
RID: `req-web-panels-html-dependency`

Status: `Implemented`

The sanitizer is a library, not code written here: `nh3`, the Python bindings for Rust's `ammonia` (built on the `html5ever` HTML5 parser). It is a direct dependency of the root project, bounded `>=0.3.7,<0.4`: a sanitizer's behaviour is its security, so a new 0.x line arrives as its own deliberate Renovate PR. Approved by George, 2026-10-29 for the plugin and 2026-11-06 for the core ("nh3 is fine in core").

#### Sanitizer Decision

Compared 2026-10-29 from the package index, the projects' repositories and the OSV advisory database, not from memory, for the plugin this panel came from; `uv lock` on 2026-11-06 resolved `nh3` 0.3.7, still the newest release inside the bound. The comparison was not re-run in full.

| Axis | `nh3` 0.3.7 (chosen) | `bleach` 6.4.0 | `lxml-html-clean` 0.4.6 | `html-sanitizer` 2.7.0 |
| --- | --- | --- | --- | --- |
| Model and parser | Allowlist; Rust `ammonia` 4.1.4 on `html5ever`, a browser-grade HTML5 parser | Allowlist; pure Python on `html5lib` | Blocklist cleaner on `libxml2` (an HTML4 parser) | Allowlist on `lxml` and `lxml-html-clean` |
| Status | Released 2026-08-23; repository pushed 2026-10-27, 404 stars, 7 open issues, not archived | Package classifier `Development Status :: 7 - Inactive`; called deprecated by the `nh3` README | Active (2026-10-26) | Stable (2026-10-25) |
| Security fitness | The sanitizer the lxml cleaner's own README names as the alternative for security-sensitive use | Inactive | Its README: "not considered appropriate for security sensitive environments" | Inherits that cleaner |
| Advisories | None against `nh3`; 15 against `ammonia` since 2019, six in 2026 (SVG/MathML mutation XSS, `animate`/`set` tags, CSS `url()`), each fixed in a later `ammonia` release | 13 recorded | Not queried | 2 recorded |
| Dependencies | None | `webencodings` | `lxml` | `beautifulsoup4`, `lxml`, `lxml-html-clean` |
| Wheels for Python 3.14 | `cp38-abi3` wheels for Linux x86-64 and aarch64, glibc and musl, macOS, Windows; sdist 25 KB | Pure Python | Needs `lxml` build | Needs `lxml` build |
| Licence, cryptography | MIT; the package has no cryptography or network code (not independently audited here) | Apache-2.0 | BSD-3-Clause | BSD-3-Clause |
| Distribution identity | `nh3` on PyPI, author `messense`, source link `github.com/messense/nh3`, which is the repository checked | | | |

Two findings shape how it is used, not whether. First, the 2026 `ammonia` advisories are in SVG, MathML and CSS handling, the three things this panel never allows (no `svg`, `math`, `style` element or `style` attribute), so the allowlist avoids the code they fixed; this is a reason for the narrow allowlist, not a reason to trust the library. Second, `nh3` 0.3.7 bundles `ammonia` 4.1.4, and `ammonia` 4.1.8 and 4.2.4 (2026-10-17) fix RUSTSEC-2026-0373 (CSS `url()` matching), which needs a `style` attribute to be exploitable and so does not reach this panel. Not verified: whether the `nh3` release is built with an attested, trusted-publishing workflow.

#### FIPS

`nh3` is a compiled (Rust) wheel, so the question the project asks of every native dependency applies: does it bring its own cryptography? It does not read as doing so: it has no dependencies of its own, no TLS and no network code, and `html5ever` and `ammonia` parse text. That is a reading of the package metadata and the description of the project, not an audit of its source tree. The dependency is **not** built `--no-binary` like `cryptography` and `psycopg`, because there is nothing for it to link against the system OpenSSL for. If a later release adds a crypto or TLS crate, that is a change to this section and to `[tool.uv] no-binary-package`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panels-html-dependency-1 | The Dependency Is Recorded | Implemented | `nh3` is a direct dependency in `pyproject.toml` with a lower bound of 0.3.7 and an upper bound below the next 0.x line, `uv.lock` carries it, and this section is kept current. | |

### Non-Goals

A sandboxed `iframe` mode (the strongest isolation, but it cannot inherit the theme or link to the page's anchors); Markdown input; `style` through a vetted property list; and any write path (the panel has no editor; its config is edited as a Panel node). They are Backlog if wanted.
