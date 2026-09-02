# Panel Security Specification

## Philosophy

Panels accept, render, and sometimes edit user-provided data. TAP Web needs one place to define the baseline security contract for panel rendering and panel edit behavior so built-in and future custom panels do not each reinvent form security and sanitization rules.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Consistent | One baseline security contract applies to all panel edit forms |
| 2. | Safe | Panel edit submissions use standard Django security protections |
| 3. | Reusable | Built-in and future custom panels can reference the same security requirements |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-panel-edit-form.sec | [Panel Edit Form Security](#panel-edit-form-security) | Implemented | Platform-level: CSRF middleware + Django Form validation + auto-escaping |
| req-web-panel-render-content.sec | [Panel Content Rendering Security](#panel-content-rendering-security) | Implemented | Platform-level: Django template auto-escaping applies to all panel templates |
| req-web-panel-json-embed.sec | [Script-Context JSON Embedding Security](#script-context-json-embedding-security) | Implemented | Django's json_script filter for all JSON-in-script-block embedding |

### Panel Edit Form Security
----
RID: `req-web-panel-edit-form.sec`

Status: `Implemented`

Panel edit mode accepts user input and must use standard Django form security protections. This requirement standardizes the baseline security behavior for panel edit submissions. These are **platform-level** guarantees: they are satisfied once by the framework and apply to all panel editors automatically. The more general editor-wide contract is being moved to `spec-web-editor.md` under `req-web-editor-form.sec`; this section remains the panel-specific compatibility reference.

#### Status Details
Implemented by the Text Panel editor (first concrete panel type). The security mechanisms are platform-level and apply to all present and future panel editors that follow the standard panel edit flow.

#### Implementation

**CSRF protection** is provided by Django's `CsrfViewMiddleware` in `MIDDLEWARE`. All panel edit form templates must include `{% csrf_token %}`. No per-panel CSRF configuration is required.

**Server-side input sanitization** is implemented via Django Form validation (`form.is_valid()`). Panel edit forms use `forms.CharField(strip=True)` (the Django default) to strip leading/trailing whitespace, enforce `max_length`, and validate field types on the server. Browser-side validation is treated as a UX aid only — forms are always validated server-side before persistence regardless of browser state.

**Untrusted input handling** means submitted values are passed through Django Form `.cleaned_data` before being written to the database. Raw `request.POST` values are not persisted directly.

**Render sanitization** is delegated to `req-web-panel-render-content.sec`. Persisted values flow through Django's template auto-escaping when rendered.

Panel editors should use Django Form classes as the standard server-side validation path. The generic panel edit fallback (raw JSON config editing) is reserved for panels without a registered PanelType and applies the same principle — config is parsed and validated before persistence.

#### Development
This requirement is intentionally generic so built-in and future plugin panels share one baseline security contract. More specialized panel config schema validation can layer on later.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-edit-form.sec-1 | CSRF Protection Required | Implemented | Panel edit forms use Django CSRF protection via `CsrfViewMiddleware` in `MIDDLEWARE`. All edit templates include `{% csrf_token %}`. | Platform-level; applies to all panel edit forms. |
| req-web-panel-edit-form.sec-2 | Server-side Input Sanitization Required | Implemented | Panel edit submissions are sanitized server-side via Django Form validation before persistence: whitespace stripped, max_length enforced, types validated. | Implemented in `TextPanelEditForm`; required contract for all panel edit forms. |
| req-web-panel-edit-form.sec-3 | Untrusted Input Handling | Implemented | Panel edit submissions are treated as untrusted input. Values are written to the database only from `form.cleaned_data`, never raw from `request.POST`. | |
| req-web-panel-edit-form.sec-4 | Existing Render Sanitization Applies | Implemented | Values saved through panel edit mode are rendered later using Django's template auto-escaping (`req-web-panel-render-content.sec`). | |

#### Future
Consider adding panel-config-schema validation so editors can validate `config` with more structure than generic form handling alone.

### Panel Content Rendering Security
----
RID: `req-web-panel-render-content.sec`

Status: `Implemented`

Panels render content that may originate from panel configuration, user edits, or searched data. Panel content rendering must default to standard Django escaping and must not treat edited panel content as trusted HTML unless a future requirement explicitly permits it.

#### Status Details
This is a **platform-level** guarantee provided by Django's template engine. Auto-escaping is enabled by default in all Django HTML templates. Panel templates must not use `|safe` or `mark_safe()` on user-provided or panel-config-sourced content.

#### Implementation
- Django template auto-escaping is enabled by default for all `.html` templates.
- Panel content values (`panel.title`, `panel.config.*`, etc.) rendered in templates are automatically HTML-escaped.
- Panel templates must not apply `|safe` or `mark_safe()` to user-sourced content.
- Any future panel type that wants trusted HTML or rich text must define a separate hardened requirement explicitly permitting it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-render-content.sec-1 | Escaping By Default | Implemented | Panel content rendering uses Django template auto-escaping by default. Panel templates must not mark user-sourced values as safe. | Platform-level; verified by Text Panel XSS tests. |
| req-web-panel-render-content.sec-2 | Edited Text Not Trusted HTML | Implemented | Text entered through standard panel editors is not treated as trusted HTML. `config.text` and `name` render as escaped plain text. | Verified in `test_text_panel.py` (`test_html_in_text_is_escaped`). |

#### Future
Define any future rich-text or trusted-HTML panel capability as a separate hardened feature rather than widening the default rendering rule.

### Script-Context JSON Embedding Security
----
RID: `req-web-panel-json-embed.sec`

Status: `Implemented`

Panels and views that embed serialized data inside `<script>` blocks operate in a different security context than standard template variable interpolation. Django's template auto-escaping (`req-web-panel-render-content.sec`) protects HTML context, but it does not protect script context: a serialized payload containing `</script>`, `<!--`, or `&` lets an attacker terminate the element and inject arbitrary HTML or JavaScript. The three-character set `<`, `>`, `&` covers script-block breakout, HTML comment injection, and entity-based bypasses.

Node names, edge types and search results are ingested from external systems, so this data **is** attacker-influenced. Escaping it is not defence in depth; it is the control.

This requirement mandates that every JSON payload destined for a `<script>` block is emitted by Django's built-in `json_script` template filter, which serializes with `DjangoJSONEncoder` and escapes those three characters to `\u003C`, `\u003E`, `\u0026`. `|safe` must not appear on a JSON payload in any TAP template.

#### Why json_script Rather Than a TAP Helper

TAP previously carried `tap_web.utils.safe_json()` — `json.dumps()` followed by a three-character replace — and templates emitted `{{ value|safe }}` inside a hand-written `<script type="application/json">` element. That helper's own docstring recorded that it "mirrors the escaping performed by Django's `json_script`", which is the definition of deriving one fact twice, in a security control, where the copy can drift from the original without anything failing.

This spec previously rejected `json_script` on the grounds that "TAP panels need the raw escaped JSON string to pass as a template variable within existing script blocks". That reasoning was retired on 2026-08-31 after checking it against the code: **all sixteen embed sites were standalone `<script type="application/json">` elements containing nothing but the payload** — byte-for-byte what `json_script` emits. No site embedded JSON inside a larger script block. The stated constraint did not exist.

`json_script` is also strictly more capable: `DjangoJSONEncoder` serializes `UUID`, `datetime` and `Decimal`, which plain `json.dumps` raises on.

#### safe_json Survives As Plugin-Facing API

`tap_web.utils.safe_json()` is **not** deleted. It is imported by three released plugins in their own repositories (`administrivia`, `fedramp_20x_ksi`, `samsite`), which are versioned independently and installed from git tags at boot — so removing it broke `django.setup()` on the cold-boot gate while core's own suite was entirely green, because nothing in THIS repository imported it any more. `tap_web/utils.py` is plugin-facing API: deprecate, do not delete. It now serializes with `DjangoJSONEncoder` and a test asserts its output is byte-for-byte identical to `json_script`'s payload — the original merely claimed that parity in its docstring, which is how a copied security control drifts. Removal is tracked in unified-systems-com/tap#255, after the plugins migrate and re-release.

#### Implementation

Context builders hand the template **plain Python objects**, not pre-serialized strings, plus a `*_script_id` key naming the element id:

```
{{ table_nodes|json_script:table_data_script_id }}
```

Element ids are built in Python (`tap_web.utils.graph_script_ids`, each panel's `_script_ids`) rather than concatenated in the template. This is not a style preference: `json_script` takes the id as a filter argument, which cannot be an expression, and the obvious workaround `{{ "tap-graph-nodes-"|add:panel.entity_id }}` **silently renders the empty string**, because Django's `add` falls back to `value + arg` and `str + UUID` raises. A silently-empty id produces a payload the panel JS can never find, with no error anywhere. The concatenation belongs where a type error is loud.

The id grammar (`tap-table-data-<panel id>`, `tap-graph-<kind>-<context id>`) is the contract with `panel-table.js` and `panel-graph.js`, which rebuild the same ids by concatenation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-json-embed.sec-1 | Escaping Is Django's | Implemented | Django's `json_script` filter is the single path for JSON-in-script-block embedding in TAP's own templates. | `tap_web.utils.safe_json()` is retained as plugin-facing API (see above) and test-asserted byte-identical to `json_script`; removal tracked in #255. |
| req-web-panel-json-embed.sec-2 | Unicode Escape Applied | Implemented | Rendered payloads escape `<`, `>`, `&` to `\u003C`, `\u003E`, `\u0026`. Asserted on rendered output, not on a helper. | |
| req-web-panel-json-embed.sec-3 | No `\|safe` On A Payload | Implemented | No TAP template applies `\|safe` to a JSON payload. Enforced externally by SonarCloud `Web:S5247`. | |
| req-web-panel-json-embed.sec-4 | XSS Round-Trip Test | Implemented | A payload containing `</script><script>alert(1)` is verified to round-trip through the RENDERED element with no unescaped `<` or `>` — asserted on template output, so a regression to `\|safe` fails the test. | |

#### Future
Nothing outstanding. The previous entry here proposed a custom `|safe_json` filter to make the intent self-documenting; adopting `json_script` reached that end without TAP owning any escaping code.


## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed |  |
| Implemented | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`

## Requirements Format

`RID: `...``
`Status: `...``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
