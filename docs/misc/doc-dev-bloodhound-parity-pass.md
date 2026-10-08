---
title: BloodHound GitHub parity pass — 27 of 87 today, the three collector slices to 59
date: 2026-09-11
status: active
audience:
  - developer
  - llm
spec: tap_grid/specs/spec-grid-traversal-language.md
related_docs:
  - docs/misc/doc-dev-gryphon-query-audit.md
  - docs/misc/doc-gryphon-feature-demand.md
---

> **Re-run of the 2026-08-27 audit** (`doc-dev-gryphon-query-audit.md`) against the CURRENT corpus and the
> CURRENT grid, 2026-09-11. Corpus: `SpecterOps/openhound-github` @ `056c0f8` (2026-09-10) + `SpecterOps/GitHound`
> @ `bcd3da1` — 41 node kinds, 159 edge kinds, **87 unique saved queries** (55 + 62 saved-query files, 5
> documentation-only enterprise queries, 11 + 12 privilege-zone rules; 58 shared verbatim). Grid: github_core
> 0.8.0 on the demo instance — 26 node types, 48 edge types, all collector-written.
>
> Human-readable briefing: the "Twenty-Seven of Eighty-Seven" artifact. Work: `tap-plugin-github-core#109` (epic),
> `#110` (slice A, built), `#111` (slice B), `#112` (slice C, an L); `git-serious-fixtures#2`; `git-serious-tap#80`.
> The raw query files of the August audit were lost with their scratchpad; this time the verdict table is IN the doc.

# The numbers

> **Correction, same evening (git-serious-tap PR# 81, the query pack).** Authoring the 79 translations one by one
> moved eight rows: the `branch-protection-*` queries were counted runnable because `github_ruleset` exists, but
> its `rules` is a JSON LIST and Gryphon has no array-membership predicate — they run after
> `tap-plugin-github-core#114` flattens it to `configuration.rule_types` ("slice A2"). Per unique query id (79,
> not 87 rows): **15 today · 35 after A · 43 after A2 · 46 after B · 55 after C**; 10 blocked on Gryphon, 14 not
> observable, 5 awaiting a type. The authoritative per-query record is now the pack itself
> (`git_serious/tap_plugin/git_serious/data/bloodhound_queries.json`, rendered at `/git-serious/queries`); the
> table below is the first pass and is kept as the record of it.

Counting unit: a query that runs **end to end** — Gryphon can express it AND the types/fields it filters on are
on the grid. Verdicts are rule-derived from the Cypher text by a classifier (regexes for the language features,
a kind→TAP mapping table for the data), then spot-checked by executing three probes on the demo grid.

| Stage | Runnable end to end (of 87) | What lands |
| --- | --: | --- |
| today | 27 | — |
| + slice A | 47 | org / repository / environment SETTINGS copied verbatim into `configuration` (github-core#110, built 2026-09-11) |
| + slice B | 51 | the people graph: members, `github_team`, nesting, membership, repository grants (github-core#111) |
| + slice C | 59 | custom org roles, fine-grained PAT grants (github-core#112) |
| ceiling | 73 | the other 14 need Enterprise, SAML/SCIM or an Azure/Okta graph — not observable for a Team-plan org |

Language: **3 verbatim, 69 after mechanical rewrites, 15 hit a gap.** The August audit's headline
defect — node inline property maps parsed and dropped — was fixed 2026-08-31 (tap#196, still open as an issue),
so `(o:GH_Organization {two_factor_requirement_enabled: false})` now filters. Rewrites: drop `RETURN p` (the
default envelope is the path set), `n.x` → `n.data.x` / `n.data.configuration.x`, `<>` → `!=`, `WHERE n:Label` →
`n.entity_type IN [...]`.

## Where the language still blocks — and the escape hatch for each

| Gap | Queries | Gryphon work | Closes it today (break-glass — `req-grid-search-canonical-read`) |
| --- | --: | --- | --- |
| variable-length `*1..` + alternation `A\|B\|C` | 7 | tap#259 | a `module` Search: `WITH RECURSIVE` over the edge table on the read-only alias, `edge_type IN (…)`, depth cap, cycle guard, canonical envelope out |
| correlated multi-`MATCH` (join, not union) | 3 | tap#433 (decision) | module: each clause through `execute_gryphon_raw`, intersect on the shared variable's entity ids; or `orm` `entity_id__in=Subquery(…)` |
| `OPTIONAL MATCH` beyond v0 | 2 | two medium widenings | module: mandatory + optional envelopes merged in Python |
| `'x' IN n.array_field` | 5 | small grammar addition, not yet filed | `orm` Search with the JSONField `__contains` lookup |

The machinery exists and is unused: `register_search_runner` (`tap_grid/registry.py:130`), dispatch
(`tap_grid/search.py:265`); a runner receives `(search, validated_inputs, db_alias=, layer=)` and returns the same
envelope a Gryphon search does, so every panel consumes it unchanged. No plugin has registered one.

**One verdict reversed by a probe.** "Repositories whose default branch is unprotected" was blocked in August on
property-to-property comparison. `git_ref.is_default` is a field now, and a three-hop chain through the neutral
`git_core__git_repository` expresses it with no join:

```
MATCH (g:github_core__github_repository)-[:HOSTS_REPOSITORY__github_core]->(r:git_core__git_repository)
      -[:DECLARES_REF__git_core]->(b:git_core__git_ref)
WHERE b.data.is_default = true
NOT EXISTS { MATCH (rs:github_core__github_ruleset)-[:PROTECTS_REF__github_core]->(b) }
RETURN g.data.full_name AS repo, b.data.name AS branch
```

Answer on the demo grid: **0 rows** — the organization rulesets cover every default branch. Note `DECLARES_REF`
hangs off the neutral git repository, not `github_repository`; a chain that changes direction mid-pattern is
accepted (117 rows on the workflow↔repository↔git-repository probe).

# Kind → type mapping used by the classifier

| BloodHound kind | TAP | Stage |
| --- | --- | --- |
| `GH_Organization` | `github_core__github_account` (account_type=Organization) + `configuration.*` | A |
| `GH_User` | `github_core__github_account` (User), enumerated via `MEMBER_OF_ORG` | B |
| `GH_Team` | `github_core__github_team` (new) | B |
| `GH_TeamRole` / `GH_RepoRole` | `MEMBER_OF_TEAM.role` / `HAS_REPO_PERMISSION.permission` — roles are edge properties, not nodes | B |
| `GH_OrgRole` | owners: `MEMBER_OF_ORG.role = admin` (B); custom roles: `github_org_role` (C, to rule) | B / C |
| `GH_Repository`, `GH_Workflow`, `GH_WorkflowJob`, `GH_App`, `GH_AppInstallation`, `GH_*Secret`, `GH_Runner`/`GH_RepoRunner` | existing github_core types | now |
| `GH_Branch` | `git_core__git_ref` | now |
| `GH_BranchProtectionRule` | `github_core__github_ruleset` + `PROTECTS_REF` (rulesets, not classic BPR — rule-by-rule translation) | now |
| `GH_Environment`, `GH_EnvironmentBranchPolicy` | `github_core__github_environment` + REST detail (slice A) | A |
| `GH_PersonalAccessToken(Request)` | `credential_grant` (identity_core) or `github_pat_grant` — to rule | C |
| `GH_*Variable`, `GH_OrgRunner(Group)`, `GH_DeployKey`, `GH_SecretScanningAlert` | proposed / unscheduled types | later |
| `GH_Enterprise*`, `GH_SamlIdentityProvider`, `GH_ExternalIdentity`, `SCIM_*`, `AZUser`, `Okta_User`, `AZFederatedIdentityCredential` | not observable on a Team plan / other plugin | n/a |

Rulings carried (vocabulary corpus, Part E): one account type; roles as edge properties; **evidence edges only** —
BloodHound's 382 computed `GH_CanWriteBranch` edges in its sample are derived as queries, never collected.

# Their samples

`GitHound/samples/githound_O_kgDOCoV2OQ.json` — 338 nodes / 2,763 edges, OpenGraph generic-ingest envelope
(`{"graph": {"nodes": [{"id","kinds","properties"}], "edges": [{"kind","start","end","properties"}]}}`): 13 users, 8 teams,
12 repos, 60 branches, 19 protection rules, 6 PATs, 5 installations, 1 secret-scanning alert, 382 computed
reachability edges. Home: a **seeded test oracle** in github_core (collector skill Step 9.5) — map `GH_*` onto our
types inside the test transaction, assert our queries against their computed edges. Never a GRIFT bundle or boot
record. Found in their repos: both READMEs list 7 query files that do not exist; `GH_CanAssumeIdentity` and
`GH_SyncedTo` are schema-declared traversable but emitted by no code in openhound-github; `GH_ValidToken` is
produced by authenticating to GitHub WITH the leaked secret (`githound.ps1:8426`) — we will not.

# All 87, one row each

| # | Query | Language | Data stage | Needs | Escape hatch today |
|--:|---|---|---|---|---|
| 1 | Actions SHA Pinning Not Required `actions-sha-pinning-not-required` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 2 | Active Leaked Secrets `active-leaked-secrets` | REWRITE | unscheduled type | drop the path variable: the default graph envelope carries nodes+edges | — |
| 3 | Advanced Security Disabled for New Repositories `advanced-security-disabled-new-repos` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 4 | All GitHub Actions Allowed `all-actions-allowed` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 5 | App Installations with Access to All Repositories `app-installations-all-repos` | REWRITE | today | inline property map (works since 08-31) | — |
| 6 | Branch Protection Rules - Admins Not Enforced `branch-protection-admins-not-enforced` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 7 | Branch Protection Rules - Deletions Allowed `branch-protection-deletions-allowed` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 8 | Branch Protection Rules - Force Pushes Allowed `branch-protection-force-pushes` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 9 | Branch Protection Rules - No Code Owner Reviews `branch-protection-no-code-owner-reviews` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 10 | Branch Protection Rules - No Pull Request Reviews Required `branch-protection-no-pr-reviews` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 11 | Branch Protection Rules - No Status Checks Required `branch-protection-no-status-checks` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 12 | Branch Protection Rules - Self-Approval Allowed `branch-protection-self-approval` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 13 | Branch Protection Rules - Stale Reviews Not Dismissed `branch-protection-stale-reviews` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 14 | Users Who Can Bypass Pull Request Requirements `bypass-pr-requirements` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 15 | Dangerous Branch Permissions `dangerous-branch-perms` | GAP | slice B (people) | variable-length path (tap#259); edge-type alternation (tap#259) | module runner: WITH RECURSIVE over tap_grid_edge on the read-only alias, depth cap + cycle guard |
| 16 | Organizations with default repository permission `default-repository-permissions` | REWRITE | slice A (settings) | <> → !=; bare props → n.data.<field> / n.data.configuration.<key> | — |
| 17 | [Demo] SSO Round-Trip: Azure/Okta → GitHub → Cloud Identity `demo-sso-to-cloud-round-trip` | GAP | not observable | variable-length path (tap#259); edge-type alternation (tap#259); correlated multi-MATCH on ghUser (tap#433) | module runner: WITH RECURSIVE over tap_grid_edge on the read-only alias, depth cap + cycle guard; module runner: run each clause through execute_gryphon_raw, intersect on the shared entity ids; or orm Subquery(entity_id__in=…) |
| 18 | Dependabot Alerts Disabled for New Repositories `dependabot-alerts-disabled-new-repos` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 19 | Dependabot Security Updates Disabled for New Repositories `dependabot-updates-disabled-new-repos` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 20 | Dependency Graph Disabled for New Repositories `dependency-graph-disabled-new-repos` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 21 | Environments Where Admins Can Bypass Protections `environments-admin-bypass` | REWRITE | slice A (settings) | drop the path variable: the default graph envelope carries nodes+edges | — |
| 22 | Expired Personal Access Tokens `expired-pats` | REWRITE | slice C (roles, PATs) | drop the path variable: the default graph envelope carries nodes+edges | — |
| 23 | External Identities Without SCIM Provisioning `external-identities-without-scim` | REWRITE | not observable | bare props → n.data.<field> / n.data.configuration.<key> | — |
| 24 | GitHub-to-Azure Identity Assumptions `github-to-azure-identity` | REWRITE | not observable | drop the path variable: the default graph envelope carries nodes+edges | — |
| 25 | Global Repo Permissions `global-repo-perms` | GAP | slice C (roles, PATs) | variable-length path (tap#259); edge-type alternation (tap#259) | module runner: WITH RECURSIVE over tap_grid_edge on the read-only alias, depth cap + cycle guard |
| 26 | External Identities `hybrid-identities` | REWRITE | not observable | drop the path variable: the default graph envelope carries nodes+edges; label predicate → entity_type IN [...] | — |
| 27 | Members Can Change Repository Visibility `members-can-change-repo-visibility` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 28 | Members Can Create GitHub Pages `members-can-create-pages` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 29 | Members Can Create Public Repositories `members-can-create-public-repos` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 30 | Members Can Delete Repositories `members-can-delete-repos` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 31 | Members Can Fork Private Repositories `members-can-fork-private-repos` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 32 | Members Can Invite Outside Collaborators `members-can-invite-outside-collaborators` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 33 | Organization Owners `org-owners` | REWRITE | slice B (people) | drop the path variable: the default graph envelope carries nodes+edges | — |
| 34 | Organizations without 2FA `orgs-without-2fa` | REWRITE | slice A (settings) | bare props → n.data.<field> / n.data.configuration.<key> | — |
| 35 | PATs with Access to All Repositories `pats-all-repo-access` | REWRITE | slice C (roles, PATs) | drop the path variable: the default graph envelope carries nodes+edges | — |
| 36 | Pending PAT Requests `pending-pat-requests` | REWRITE | slice C (roles, PATs) | drop the path variable: the default graph envelope carries nodes+edges | — |
| 37 | Private Repositories with Forking Allowed `private-repos-forking-allowed` | REWRITE | today | inline property map (works since 08-31) | — |
| 38 | Privileged Custom Org Roles `privileged-custom-org-roles` | REWRITE | slice C (roles, PATs) | drop the path variable: the default graph envelope carries nodes+edges; label predicate → entity_type IN [...] | — |
| 39 | Privileged Hybrid Identities `privileged-hybrid-identities` | REWRITE | slice B (people) | drop the path variable: the default graph envelope carries nodes+edges | — |
| 40 | Public Repositories `public-repos` | REWRITE | today | inline property map (works since 08-31) | — |
| 41 | Secret Scanning Push Protection Disabled for New Repositories `push-protection-disabled-new-repos` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 42 | Users Who Can Push to Protected Branches `push-to-protected-branches` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 43 | Repositories with Secret Scanning Disabled `repos-secret-scanning-disabled` | REWRITE | today | inline property map (works since 08-31) | — |
| 44 | Repos Vulnerable to Workflow Secret Exfiltration `repos-vulnerable-to-workflow-secret-exfil` | GAP | slice B (people) | variable-length path (tap#259); edge-type alternation (tap#259); OPTIONAL MATCH beyond the v0 shape | module runner: WITH RECURSIVE over tap_grid_edge on the read-only alias, depth cap + cycle guard; module runner: mandatory envelope + optional envelope merged in Python |
| 45 | Repository Workflows `repository-workflows` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 46 | SAML Configuration Mapping `saml-configuration` | GAP | not observable | correlated multi-MATCH on EI,OIP (tap#433) | module runner: run each clause through execute_gryphon_raw, intersect on the shared entity ids; or orm Subquery(entity_id__in=…) |
| 47 | Secret Scanning Alerts `secret-scanning-alerts` | REWRITE | unscheduled type | drop the path variable: the default graph envelope carries nodes+edges | — |
| 48 | Secret Scanning Disabled for New Repositories `secret-scanning-disabled-new-repos` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 49 | Secrets Reachable by User `secrets-reachable-by-user` | GAP | slice B (people) | variable-length path (tap#259); edge-type alternation (tap#259) | module runner: WITH RECURSIVE over tap_grid_edge on the read-only alias, depth cap + cycle guard |
| 50 | Team Membership Admins `team-membership-admin` | GAP | slice B (people) | correlated multi-MATCH on team (tap#433) | module runner: run each clause through execute_gryphon_raw, intersect on the shared entity ids; or orm Subquery(entity_id__in=…) |
| 51 | Team Structure `team-structure` | GAP | slice B (people) | variable-length path (tap#259) | module runner: WITH RECURSIVE over tap_grid_edge on the read-only alias, depth cap + cycle guard |
| 52 | Unprotected Branches `unprotected-branches` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 53 | Repositories with Workflows and Unprotected Default Branch `unprotected-default-branch-with-workflow` | REWRITE | today | fold both clauses into one chain: (w)<-[:DEFINES_WORKFLOW]-(g)-[:HOSTS_REPOSITORY]->(r)-[:DECLARES_REF]->(b) (verified 09-11); prop=prop avoided: git_ref.is_default = true replaces repo.default_branch = branch.short_name; drop the path variable: the default graph envelope carries nodes+edges; bare props → n.data.<field> / n.data.configuration.<key> | — |
| 54 | Unprotected Default Branches `unprotected-default-branches` | REWRITE | today | prop=prop avoided: git_ref.is_default = true replaces repo.default_branch = branch.short_name; drop the path variable: the default graph envelope carries nodes+edges; bare props → n.data.<field> / n.data.configuration.<key> | — |
| 55 | Web Commit Signoff Not Required `web-commit-signoff-not-required` | REWRITE | slice A (settings) | inline property map (works since 08-31) | — |
| 56 | Environments Where Admins Can Bypass Protections `environments-admin-bypass` | REWRITE | slice A (settings) | drop the path variable: the default graph envelope carries nodes+edges | — |
| 57 | Repository Workflows `repository-workflows` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 58 | Self-Hosted Runners Can Intercept Broad-Token Jobs `self-hosted-runners-can-intercept-broad-token-jobs` | GAP | today | array-membership predicate <literal> IN n.field (grammar gap; small) | orm search: JSONField `configuration__<key>__contains` filter; or Gryphon on a per-key projection once the collector stores permissions as a map |
| 59 | Shared Self-Hosted Runners Can Intercept Secret-Bearing Jobs `shared-self-hosted-runners-can-intercept-secret-bearing-jobs` | REWRITE | not observable | drop the path variable: the default graph envelope carries nodes+edges; label predicate → entity_type IN [...] | — |
| 60 | Unprotected Branches `unprotected-branches` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 61 | Repositories with Workflows and Unprotected Default Branch `unprotected-default-branch-with-workflow` | REWRITE | today | fold both clauses into one chain: (w)<-[:DEFINES_WORKFLOW]-(g)-[:HOSTS_REPOSITORY]->(r)-[:DECLARES_REF]->(b) (verified 09-11); prop=prop avoided: git_ref.is_default = true replaces repo.default_branch = branch.short_name; drop the path variable: the default graph envelope carries nodes+edges; bare props → n.data.<field> / n.data.configuration.<key> | — |
| 62 | Unprotected Default Branches `unprotected-default-branches` | REWRITE | today | prop=prop avoided: git_ref.is_default = true replaces repo.default_branch = branch.short_name; drop the path variable: the default graph envelope carries nodes+edges; bare props → n.data.<field> / n.data.configuration.<key> | — |
| 63 | Workflow Jobs Interceptable by Self-Hosted Runners `workflow-jobs-interceptable-by-self-hosted-runners` | REWRITE | today | drop the path variable: the default graph envelope carries nodes+edges | — |
| 64 | Workflow Jobs with Broad GITHUB_TOKEN Write Permissions `workflow-jobs-with-broad-token-write-permissions` | GAP | today | array-membership predicate <literal> IN n.field (grammar gap; small) | orm search: JSONField `configuration__<key>__contains` filter; or Gryphon on a per-key projection once the collector stores permissions as a map |
| 65 | OIDC-Capable Workflow Jobs Interceptable by Self-Hosted Runners `workflow-jobs-with-id-token-write-on-self-hosted-runners` | GAP | today | array-membership predicate <literal> IN n.field (grammar gap; small) | orm search: JSONField `configuration__<key>__contains` filter; or Gryphon on a per-key projection once the collector stores permissions as a map |
| 66 | Workflow Jobs with OIDC Token Permission `workflow-jobs-with-id-token-write` | GAP | today | array-membership predicate <literal> IN n.field (grammar gap; small) | orm search: JSONField `configuration__<key>__contains` filter; or Gryphon on a per-key projection once the collector stores permissions as a map |
| 67 | Workflow Jobs with Observed OIDC Authentication Steps `workflow-jobs-with-observed-oidc-auth-steps` | GAP | today | array-membership predicate <literal> IN n.field (grammar gap; small) | orm search: JSONField `configuration__<key>__contains` filter; or Gryphon on a per-key projection once the collector stores permissions as a map |
| 68 | Enterprise to Organization Hierarchy `enterprise-to-organization-hierarchy` | REWRITE | not observable | drop the path variable: the default graph envelope carries nodes+edges | — |
| 69 | Enterprise Members `enterprise-members` | REWRITE | not observable | drop the path variable: the default graph envelope carries nodes+edges | — |
| 70 | Enterprise Admins `enterprise-admins` | REWRITE | not observable | drop the path variable: the default graph envelope carries nodes+edges | — |
| 71 | Enterprise Role Assignments `enterprise-role-assignments` | REWRITE | not observable | drop the path variable: the default graph envelope carries nodes+edges | — |
| 72 | Enterprise Team Assignments and Projections `enterprise-team-assignments-and-projections` | GAP | not observable | OPTIONAL MATCH beyond the v0 shape | module runner: mandatory envelope + optional envelope merged in Python |
| 73 | Tier Zero All-Repo Admin Role `t0-all-repo-admin-role` | REWRITE | slice C (roles, PATs) | bare props → n.data.<field> / n.data.configuration.<key> | — |
| 74 | Tier Zero App Installations (All Repositories) `t0-app-installations-all-repos` | REWRITE | today | bare props → n.data.<field> / n.data.configuration.<key> | — |
| 75 | Tier Zero Apps (All-Repository Installations) `t0-apps-all-repos` | REWRITE | today | bare props → n.data.<field> / n.data.configuration.<key> | — |
| 76 | Tier Zero External Identities (Owner-Mapped) `t0-external-identities-owners` | REWRITE | not observable | inline property map (works since 08-31) | — |
| 77 | Tier Zero Organizations `t0-organizations` | VERBATIM | slice A (settings) | verbatim | — |
| 78 | Tier Zero Owner Users `t0-owner-users` | REWRITE | slice B (people) | inline property map (works since 08-31) | — |
| 79 | Tier Zero Owners Role `t0-owners-role` | REWRITE | slice B (people) | inline property map (works since 08-31) | — |
| 80 | Tier Zero PATs (All Repositories) `t0-pats-all-repos` | REWRITE | slice C (roles, PATs) | bare props → n.data.<field> / n.data.configuration.<key> | — |
| 81 | Tier Zero Privilege Escalation Roles `t0-privilege-escalation-roles` | VERBATIM | slice C (roles, PATs) | verbatim | — |
| 82 | Tier Zero Privilege Escalation Users `t0-privilege-escalation-users` | GAP | slice C (roles, PATs) | variable-length path (tap#259); edge-type alternation (tap#259) | module runner: WITH RECURSIVE over tap_grid_edge on the read-only alias, depth cap + cycle guard |
| 83 | Tier Zero SAML Identity Providers `t0-saml-identity-providers` | VERBATIM | not observable | verbatim | — |
| 84 | Tier Zero App Installations (All Repositories) `t0-app-installations-all-repos` | REWRITE | today | inline property map (works since 08-31) | — |
| 85 | Tier Zero Apps (All-Repository Installations) `t0-apps-all-repos` | REWRITE | today | inline property map (works since 08-31) | — |
| 86 | Tier Zero Enterprise Owners Role `t0-enterprise-owners-role` | REWRITE | not observable | inline property map (works since 08-31) | — |
| 87 | Tier Zero PATs (All Repositories) `t0-pats-all-repos` | REWRITE | slice C (roles, PATs) | inline property map (works since 08-31) | — |

---

# Update, 2026-10-08 — where the corpus lives now, and a measurement from the pack itself

The correction above says the authoritative per-query record moved into the pack. It did, and the
pack has since become the thing everything else is generated from — which is worth recording here
because the file's name invites exactly the wrong guess.

## It is not a GRIFT pack. It is the source a GRIFT pack is generated from.

Three layers, and only the middle one is GRIFT:

| layer | file (in `git-serious-tap`) | what it is |
| --- | --- | --- |
| source | `tap_plugin/git_serious/data/bloodhound_queries.json` | the content pack, hand-maintained: one record per query id, attribution, upstream pins, the translation, `status`/`stage`, caveats. **No nodes, no edges, no batch envelope** — not GRIFT |
| generated | `tap_plugin/git_serious/grift/queries.grift.json` | **this** is the GRIFT batch (`metadata` / `_reserved` / `batches`), seeding 35 `search`, 35 `object`, 2 `page`, 2 `panel`, 37 `edge`, 1 `batch` |
| generator | `scripts/build_query_pack_grift.py` | compiles source → GRIFT |

The generated file says so on every node it writes — *"GENERATED from data/bloodhound_queries.json —
do not hand-edit"* and *"edit the pack, not this node."* The edit surface is the source file; the
GRIFT batch is build output that happens to be committed.

**Two consumers, not one.** `tap_plugin/git_serious/panels/query_pack.py` reads the **source**
directly at runtime, so the page renders the whole corpus including queries that do not yet run;
the generated batch seeds only the runnable ones into the grid.

**That asymmetry is a cross-check worth keeping.** The GRIFT batch seeds exactly **35** `search`
nodes, and tallying `status == "runs"` in the source independently gives **35**. The generator's
contract is "seed what runs", so the two agreeing is evidence that both the tally and the generator
are right — and if they ever diverge, one of them is stale.

Declared in **git-serious-tap's** canon, not tap's: the query-pack requirement in
`specs/spec-git-serious-query-pack.md` in that repository, at status Implemented. Its id is
deliberately not reproduced here as a bare token — tap's `rids` guard resolves every `req-…` token
in this tree against tap's own requirement set, and a plugin repository's id cannot resolve.

## The ladder, re-measured from the pack

Derived 2026-10-08 by reading the source file and tallying, not recalled:

```
git -C <git-serious-tap> show origin/main:tap_plugin/git_serious/data/bloodhound_queries.json > /tmp/bhq.json
python3 -c "
import json, collections
q = json.load(open('/tmp/bhq.json'))['queries']
print(collections.Counter(x['status'] for x in q))
print(collections.Counter((x['status'], x['stage']) for x in q))
"
```

| status | count | meaning |
| --- | ---: | --- |
| `runs` | **35** | translates and runs on a grid `github_core` has collected |
| `expressible` | 20 | the translation exists; the data does not yet |
| `blocked` | 10 | a grammar gap or an unbuilt type, not a data gap |
| `not_observable` | 14 | Team-plan ceiling |
| | **79** | |

Cross-tabulated against `stage`, which shows *why* 35:

| status \ stage | today | A | A2 | B | C | later | na |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `runs` | 15 | 20 | · | · | · | · | · |
| `expressible` | · | · | 8 | 5 | 7 | · | · |
| `blocked` | · | · | · | 3 | 2 | 5 | · |
| `not_observable` | · | · | · | · | · | · | 14 |

So **slice A has landed** — that is what moved its 20 into `runs`, matching the `15 → 35` step of the
corrected ladder above. A2/B/C would add 20 more by translation alone.

**The 79-vs-87 question, settled mechanically:** summing `len(sources)` across the 79 records gives
exactly **87**. One record per query id, every upstream variant kept verbatim. Anyone comparing a
figure here against an older one should establish which of the two it counted before concluding
something regressed.

## Two gaps still have no issue behind them

Tallying `blocked_on` across the pack: `tap#259` owns variable-length path and alternation (6),
`github-core#112` owns custom org roles (2), and a collector build owns the unbuilt types (2). The
remaining two are tracked nowhere — **`OPTIONAL MATCH` beyond v0**, and the **derived eligibility and
branch-creation edges**. The gap table above already recorded `'x' IN n.array_field` as "not yet
filed" in September; it is still not filed. A gap counted in a stage table and owned by no issue is a
gap nobody is working.

## What did not survive

The pass's working inventories — `bloodhound-inventory.json/.md`, `github-core-inventory.json/.md`,
`query-verdicts.json`, and the `classify_queries.py` / `build_report.py` scripts behind the briefing
— lived in a session scratchpad under `/private/tmp` and are gone. **The numbers survived only
because this document put the verdict table inline**, which is exactly the lesson the header records
after the August files were lost the same way. The pack now carries the per-id record, so a third
loss would cost the derivation, not the data.
