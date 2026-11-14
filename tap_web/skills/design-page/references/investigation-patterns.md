# Investigation patterns → TAP panel config

Reference for [`design-page`](../SKILL.md) Step 5. The patterns are drawn from **public** descriptions of how a
cloud-security graph product (Wiz) organizes investigation; no product code, styles or assets are reproduced,
and nothing here came from a customer tenant. Status per pattern: *documented* (vendor blog), *reported*
(third-party walkthrough or designer portfolio). Sources are listed at the foot.

Every mapping below uses standard panels and GRIFT only, and every Gryphon form was run against a live grid
before it was written down (2026-11).

## The chain

| Level | Job | TAP shape |
| --- | --- | --- |
| Overview | Where should I look? Aggregates and top-N. | `stat_card_panel` over `COUNT` searches + a room directory table |
| Board | What do I act on? A filtered, grouped list. | `table_panel` in projection mode with `group_by`, `quick_filter`, `row_url_template` |
| Profile | One object and everything touching it. | A `discoverable: false` page; every search declares `entity_id` in `input_schema` |
| Raw | Says who? The card, its edges and history. | The object viewer `/object/<type>/<slug>--<uuid>/`; never rebuilt |

Each level carries enough to decide whether to go one deeper (*reported*: progressive disclosure in five levels,
dashboard → list → detail → resource → raw).

## Patterns

### 1. Action and exploration are separate primitives (reported)

Findings are the unit of action; the graph is the unit of exploration. Entry points are per domain, the
investigation crosses domains. **In TAP:** a board is per domain (findings, hosts), and the profile is where
domains meet (a host's findings, subnet, VPC, account on one page).

### 2. The finding header quartet (reported)

A finding reader needs **status, severity, the rule that matched, and the resource**. **In TAP:** those are the
first four columns of a findings board; the resource column is a `link` to the resource profile, not text.
Drop severity when the collection has one value (check with `RETURN f.data.severity AS s, COUNT(f) AS n`).

### 3. Any resource is explorable from any entry point (reported)

**In TAP:** every row that names a typed object links to it: to the profile when one exists, otherwise to the
object viewer. The pivot is an edge in the query, not an id pasted into a URL by hand:

```text
MATCH (f:<finding_type>)-[:CONCERNS_RESOURCE__<plugin>]->(i:<resource_type>)
RETURN f.entity_id AS id, f.name AS name, i.entity_id AS resource_id, i.name AS resource
```

and the column `{"field": "resource", "formatter": "link", "formatter_params": {"href_template":
"/<profile-slug>?entity_id={resource_id}", "external": false}}`.

### 4. Inventory with issue counts, zeros kept (reported)

A resource list shows how many findings each resource carries, and the clean ones stay in the list (a zero is
an observed fact). **In TAP:** `OPTIONAL MATCH` anchored on the resource variable (the optional node needs its
own name; the form below is the accepted one):

```text
MATCH (i:<resource_type>)
OPTIONAL MATCH (i)<-[:CONCERNS_RESOURCE__<plugin>]-(f:<finding_type>)
RETURN i.entity_id AS id, i.name AS name, COUNT(f) AS findings
ORDER BY findings DESC
```

### 5. Group by what you fix once (documented)

Vulnerabilities grouped by component or base image so one fix closes many rows; issues by control, resource or
account. **In TAP:** `group_by` in the table panel (prefix rules, client-side over the loaded rows, so set
`page_size` to cover the group). One grouping per list; offer the other as a sort.

### 6. Profile pages per object type (documented)

Identity and datastore profiles, with sections for related things and a question scoped to the object.
**In TAP:** a profile page whose every panel binds a search with
`"input_schema": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]}`
and `WHERE i.entity_id = $entity_id`; the panels read `?entity_id=` from the page URL
(`tap_grid.search.inputs_from_query`). Identity first (a `chrome: minimal` table: one row of facts), then the
findings, then the neighbours, then the raw-card link.

### 7. Prove existence before reading absence (reported)

The resource drawer leads with name, type, account and region; a missing object means stop, not "no issues".
An empty result after coverage is proven is an honest answer. **In TAP:** the identity table on a profile has
`empty_text` that says the id did not resolve; the findings table's `empty_text` says *no findings recorded
for this host in the collection*, which is a different sentence.

### 8. Ownership slice (documented)

Projects and services gather resources and their issues so an owner sees their own pile. **In TAP:** a board
per account or per VPC, or a `group_by` on the owner field when the plugin records one.

### 9. Prioritize to a short default (documented)

From tens of thousands of findings to the handful that combine into real exposure. **In TAP:** the overview's
tiles count the actionable classes (malicious packages, exposed hosts), not the total; the total is a line
under them.

### 10. Navigation grouped by job (reported)

A vertical nav replaced a crowded horizontal one. **In TAP:** there is no side nav by design; the job grouping
is a landing directory (a table over `MATCH (p:page)` with `slug` as a `link`), `NESTS_UNDER` parents, and
`nav_weight` order in the Cmd-K palette.

## Gryphon forms verified for these rooms

| Need | Form | Note |
| --- | --- | --- |
| Count per value | `RETURN f.data.x AS x, COUNT(f) AS n` | Grouping is implicit |
| Sort a projection | `ORDER BY <alias>` | Not `ORDER BY f.data.x` |
| Sort a traversal | panel `initial_sort` | `ORDER BY` is rejected on single-hop traversals |
| List membership | `f.data.list CONTAINS "x"` | No `[0]` index access |
| Prefix | `STARTS_WITH "x"` | |
| Edge type | `e.data.edge_type` | Not a spine field |
| Page directory | `MATCH (p:page) WHERE p.data.discoverable = true RETURN p.name AS name, p.data.slug AS slug, p.data.description AS about` | |
| Zero-keeping count | `OPTIONAL MATCH (i)<-[...]-(f:...)` | Anchor on the existing variable |

## Not available without chrome changes

A side drawer over a list, multi-select filter chips, saved views, server-side grouping over all rows, and a
rendered attack path (needs path queries). Note them in the room's spec as gaps, do not imitate them with
text.

## Sources

- Wiz blog: <https://www.wiz.io/blog/the-anatomy-of-a-toxic-combination-of-risk>,
  <https://www.wiz.io/blog/wiz-sensitive-data-security>, <https://www.wiz.io/blog/introducing-wiz-service-catalog>,
  <https://www.wiz.io/blog/operationalize-vulnerability-remediation>
- Walkthroughs: <https://ai.techclick.in/blog/wiz_evidence_desk>, <https://ai.techclick.in/blog/wiz_session_factory>
- UX research: <https://www.aledlie.com/reports/wiz-io-security-explainability-ux/>
- Designer portfolio: <https://www.yaronazulay.com/wiz-portal>
- Interaction rules: Vercel web interface guidelines (public).
