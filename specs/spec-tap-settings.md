# TAP Settings Specification

## Philosophy

TAP is designed to be deployed as the foundation for multiple branded products. Rampart is a FedRAMP/compliance-focused implementation; future products will address other verticals. The platform needs a clean mechanism to express per-deployment identity — product name, and eventually other brand attributes — without forking templates, duplicating code, or introducing plugin-level brand registration complexity.

Django's `settings.py` is the natural home for deployment-level configuration. A product name is a property of the deployment, not of the data or the runtime — it belongs alongside `DEBUG`, `ALLOWED_HOSTS`, and `TIME_ZONE`. A context processor makes the value available to every template without manual wiring.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Single Source | One setting controls the product name across all UI surfaces. |
| 2. | Zero Code Forks | Rebranding requires only a settings change, not template or code modifications. |
| 3. | Template Availability | The product name is available in every template context without explicit view-level passing. |
| 4. | Safe Default | Out-of-the-box TAP installations display "TAP" with no additional configuration required. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-settings-product-name | [Product Name](#product-name) | Approved for Development | Deployment-level product name setting with context processor delivery |

## Requirements

### Product Name
----
RID: `req-tap-settings-product-name`

Status: `Approved for Development`

Each TAP deployment has a product name that appears in all user-facing UI surfaces where the platform identifies itself.

#### Implementation

- `TAP_PRODUCT_NAME` is a string setting in `settings.py`, defaulting to `"TAP"`.
- A context processor `tap_web.context_processors.branding` injects `product_name` into every template context.
- The context processor is registered in `settings.TEMPLATES[0]["OPTIONS"]["context_processors"]`.
- Templates reference `{{ product_name }}` wherever the product name appears:
  - Navigation bar logo text
  - `<title>` tag (e.g. `{{ page.name }} — {{ product_name }}`)
- Internal code references (`tap_*` prefixes, CSS class names, URL paths, API namespaces) are **not** rebranded. The setting controls user-facing display only.

#### Development

`product_name` was chosen over `brand_name` to keep the vocabulary concrete — it's the name of the product, not an abstract branding concept. The setting name `TAP_PRODUCT_NAME` follows the `TAP_` prefix convention for TAP-specific settings (consistent with `TAP_GRID_ID`).

A context processor is the standard Django mechanism for values that every template needs. The alternative — passing the value manually from every view — is fragile and violates the "zero code forks" goal.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-settings-product-name-1 | Default Value | Approved for Development | `TAP_PRODUCT_NAME` defaults to `"TAP"` when not explicitly set. | |
| req-tap-settings-product-name-2 | Context Processor | Approved for Development | `product_name` is available in all template contexts via the branding context processor. | |
| req-tap-settings-product-name-3 | Nav Bar | Approved for Development | The navigation bar displays `{{ product_name }}` instead of a hardcoded string. | |
| req-tap-settings-product-name-4 | Page Title | Approved for Development | The `<title>` tag uses `{{ product_name }}` instead of a hardcoded string. | |
| req-tap-settings-product-name-5 | No Internal Rebranding | Approved for Development | Code-level identifiers (`tap_*` module names, CSS classes, URL paths, API prefixes) remain unchanged regardless of the product name setting. | |

#### Future

- Additional brand attributes (logo image, accent color, tagline) can follow the same pattern — add settings, expose via the same context processor.
- Consider whether plugins should be able to read `TAP_PRODUCT_NAME` for use in generated content (e.g. email templates, PDF reports).
- Environment variable override (`TAP_PRODUCT_NAME = os.environ.get("TAP_PRODUCT_NAME", "TAP")`) for container deployments where settings.py is baked into the image.
