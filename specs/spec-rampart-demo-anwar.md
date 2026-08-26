# Rampart Anwar Demo Specification

## Philosophy

This specification defines the target shape for the first Rampart show-and-tell demo for Anwar Kibria of Ace of Cloud. It is a cross-cutting goal spec for a specific live demo outcome rather than a full product specification.

The purpose of this spec is to work backwards from the audience, the conversation, and the desired takeaways so that current implementation work can be judged against a concrete target. This helps keep the next stretch of development focused on building the smallest coherent demo that is technically credible, visually compelling, and useful as a springboard for deeper partnership discussions.

This demo is not intended to prove that Rampart is finished, fully automated, or already productized. It is intended to prove that the core model is real, that the platform can display and assess cloud infrastructure in a way that is differentiated from typical compliance tooling, and that the system can be shaped toward real field use.

## Goals

For this specification the goals are:

|   |   |  |
| :---: | --- | --- |
| 1. | Live Infrastructure View | The demo must open on a legible, visually compelling infrastructure projection of a realistic cloud environment. |
| 2. | Real Compliance Signal | The demo must show real compliance findings and not merely a static diagram. |
| 3. | Perspective Drilldown | The demo must move from a global account view into an instance-specific view that feels like a real working system. |
| 4. | Service Scoreboarding | The demo must show a service-level scorecard and compliance table tied to the projected system. |
| 5. | Demo-Speed Delivery | The required output may be assembled manually where needed so long as the live result is coherent and clickable. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-demo-anwar-env | [Demo Environment Exists](#demo-environment-exists) | In Development | A dedicated Rampart-friendly environment and dataset are available for the live demo. |
| req-demo-anwar-landing | [Landing Page High-Level Projection](#landing-page-high-level-projection) | Implemented | Full-page account projection for the Genericom AWS environment. |
| req-demo-anwar-alerts | [Alert Badges On High-Level Projection](#alert-badges-on-high-level-projection) | In Development | Clickable badges on the EC2 instance summarize unencrypted HTTP findings. |
| req-demo-anwar-drilldown | [Instance Perspective Navigation](#instance-perspective-navigation) | Proposed | Double-clicking the EC2 instance opens a service-specific perspective page. |
| req-demo-anwar-instance-view | [Instance Perspective Projection](#instance-perspective-projection) | In Development | Service page shows a local projection centered on the application instance and related components. |
| req-demo-anwar-scoreboard | [Service Compliance Table And Scorecard](#service-compliance-table-and-scorecard) | Proposed | Service page includes a live compliance table and summary score. |
| req-demo-anwar-global-ksi | [Global KSI Page](#global-ksi-page) | Implemented | A page exists listing KSIs and a live summary across relevant entities. |
| req-demo-anwar-manuality | [Manual Demo Assembly Allowed](#manual-demo-assembly-allowed) | Proposed | Layouts and some projections may be assembled by hand for this demo. |
| req-demo-anwar-nongoals | [Non-Goals And Deferrals](#non-goals-and-deferrals) | Proposed | Explicitly defines what is not required for the first demo. |

### Demo Environment Exists
----
RID: `req-demo-anwar-env`
Status: `In Development`

The demo must run in an environment that is stable, legible, and seeded with the Genericom dataset needed for the live walkthrough.

#### Status Details
This requirement exists so that the live walkthrough is not dependent on mixed development data, incomplete seed state, or ad hoc setup on the day of the demo.

#### Implementation
The environment may be a dedicated local or hosted TAP/Rampart instance configured specifically for the demo. It may share code with the main development environment, but the live demo should use a known-good dataset and page set.

#### Development
The preferred path is to keep demo-critical content isolated enough that the walkthrough is not disrupted by unrelated LOTR or experimental Rampart data.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-demo-anwar-env-1 | Genericom Dataset Available | Proposed | The demo environment includes the Genericom infrastructure data required for the landing page, instance page, and KSI page. | |
| req-demo-anwar-env-2 | Demo Pages Resolve Cleanly | Proposed | All demo pages load without setup steps during the live session. | |
| req-demo-anwar-env-3 | Demo Path Is Repeatable | Proposed | The intended demo flow can be run more than once without reseeding or hand-repair during the same session. | |

#### Future
Formalize a repeatable demo seed/import workflow once the initial live demo shape stabilizes.

### Landing Page High-Level Projection
----
RID: `req-demo-anwar-landing`
Status: `Implemented`

The landing page loads with a full-page diagram projection of the Genericom AWS account infrastructure. The first demo only requires a single high-level view and does not require advanced scrolling, dynamic nesting, or automatic layout generation.

#### Status Details
This is the opening visual moment of the demo and the main source of initial differentiation from traditional GRC tooling.

#### Implementation
The page may use a fixed layout with manual node placement if needed. The important behavior is that the page visibly presents a coherent cloud system projection and serves as the first navigable graph view in the demo.

#### Development
For this first demo, visual legibility and live rendering matter more than automation sophistication. Manual placement is acceptable if it yields a clean, understandable projection.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-demo-anwar-landing-1 | Landing Page Opens On Projection | Proposed | The demo landing page opens directly into a full-page infrastructure projection. | |
| req-demo-anwar-landing-2 | Genericom AWS Account Represented | Proposed | The projection includes the major Genericom account entities needed for the demo narrative. | |
| req-demo-anwar-landing-3 | Fixed Layout Permitted | Proposed | The high-level projection may use a fixed manually assembled layout rather than an automatic layout engine. | Manual assembly is allowed for the first demo. |

#### Future
Replace manual positioning with richer placement and nesting behavior after the first demo target is met.

### Alert Badges On High-Level Projection
----
RID: `req-demo-anwar-alerts`
Status: `In Development`

Alert badges are applied to the EC2 instance on the landing page because of unencrypted HTTP findings. The badges are real interactive elements, and clicking them opens an infowindow summarizing the alerts.

#### Status Details
This requirement establishes that the graph is not decorative alone and that compliance findings are attached directly to the rendered system.

#### Implementation
At least one EC2 instance on the landing projection carries visible alert state. Clicking the badge opens an infowindow, popover, or equivalent inline detail surface that summarizes the current alerts associated with that instance.

#### Development
The first implementation only needs to support the demo alert path centered on unencrypted HTTP. The alert payload may be narrow so long as it is real and derived from the demo dataset.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-demo-anwar-alerts-1 | EC2 Alert Badge Visible | Proposed | The target EC2 instance displays a visible alert badge on the landing projection. | |
| req-demo-anwar-alerts-2 | Badge Is Clickable | Proposed | Clicking the badge opens a visible detail surface. | |
| req-demo-anwar-alerts-3 | Alert Summary Explains Finding | Proposed | The detail surface summarizes the list of alerts and clearly indicates unencrypted HTTP as the issue. | |

#### Future
Support multiple alert categories, counts, severities, and richer evidence links.

### Instance Perspective Navigation
----
RID: `req-demo-anwar-drilldown`
Status: `Proposed`

The user can double-click the EC2 instance on the landing page to jump to the web application tier instance-perspective page.

#### Status Details
This requirement is the first explicit proof that the landing projection is part of a live navigable system rather than a static visualization.

#### Implementation
The landing page graph supports a double-click or equivalent direct navigation gesture on the target EC2 instance. The resulting page transition opens the instance-perspective view for the web application tier.

#### Development
The first demo does not require generalized deep linking or arbitrary node navigation patterns. It only requires the target drilldown used in the demo narrative.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-demo-anwar-drilldown-1 | Double-Click Navigation Exists | Proposed | Double-clicking the target EC2 instance triggers navigation to the instance page. | |
| req-demo-anwar-drilldown-2 | Correct Perspective Page Opens | Proposed | The resulting page is the intended web application tier instance-perspective page. | |

#### Future
Generalize navigation to support broader object and perspective routing across Rampart views.

### Instance Perspective Projection
----
RID: `req-demo-anwar-instance-view`
Status: `In Development`

The instance page shows a projection of the EC2 instance and related components, including the host, ALB, customer, the internal application running on the host, the crypto library, and the connection to the Postgres database.

#### Status Details
This is the main “working view” of the demo and should show that Rampart can pivot from account-level infrastructure into a more service-centered projection.

#### Implementation
The instance-perspective page renders a projection that includes the specific entities and relationships needed for the compliance story. The projection may be manually assembled or curated for the first demo.

#### Development
The important property is not completeness of all possible infrastructure edges, but clarity of the service path and the supporting components relevant to the crypto story.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-demo-anwar-instance-view-1 | Service Perspective Renders | Proposed | The instance-perspective page renders a projection centered on the target web application service. | |
| req-demo-anwar-instance-view-2 | Key Entities Included | Proposed | The projection includes the host, ALB, customer, internal application, crypto library, and Postgres database. | |
| req-demo-anwar-instance-view-3 | Relevant Connections Visible | Proposed | The projection shows the relevant connections between those entities for the crypto/compliance narrative. | |

#### Future
Expand to richer service perspectives, additional infrastructure types, and more automated projection generation.

### Service Compliance Table And Scorecard
----
RID: `req-demo-anwar-scoreboard`
Status: `Proposed`

The instance-perspective page includes a table showing the state of compliance checks and a real-time scorecard summarizing that service.

#### Status Details
This requirement turns the instance view from a system diagram into an assessment surface.

#### Implementation
The page includes at minimum:

- a score summary for the service
- a table of compliance checks or findings
- enough detail to understand current pass/fail state

The first demo only needs to support the checks needed for the live walkthrough.

#### Development
For demo purposes, “real-time” means live from the current demo dataset and page state. It does not require background streaming or production-grade update infrastructure.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-demo-anwar-scoreboard-1 | Service Score Visible | Proposed | The instance page displays a visible compliance score or summary indicator for the service. | |
| req-demo-anwar-scoreboard-2 | Compliance Table Visible | Proposed | The instance page displays a table of compliance checks or findings. | |
| req-demo-anwar-scoreboard-3 | Failures Are Understandable | Proposed | A viewer can identify which checks are failing and why from the table or adjacent scorecard detail. | |

#### Future
Support richer scoring models, trends, severity weighting, and broader KSI families.

### Global KSI Page
----
RID: `req-demo-anwar-global-ksi`
Status: `Implemented`

The demo includes a global KSI page listing KSIs for all entities in the graph and a live summary of the state of the represented instances.

#### Status Details
This requirement broadens the story from a single service page to a wider compliance surface and hints at fleet-level assessment.

#### Implementation
The global KSI page may be a table-first view. It should summarize KSI or check state across the relevant entities included in the demo dataset and be reachable from the instance perspective page.

#### Development
The page does not need to cover every future KSI concept. It only needs to demonstrate that a broader assessment layer exists across the graph and that the service view is not isolated.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-demo-anwar-global-ksi-1 | KSI Page Reachable | Proposed | The instance page includes a link to the global KSI page. | |
| req-demo-anwar-global-ksi-2 | KSI Listing Visible | Proposed | The KSI page displays a list of KSIs or equivalent checks across the demo graph. | |
| req-demo-anwar-global-ksi-3 | Live Summary Present | Proposed | The KSI page includes a current summary of compliance state across the represented instances. | |

#### Future
Extend into control families, ownership, trends, exceptions, and additional compliance domains.

### Manual Demo Assembly Allowed
----
RID: `req-demo-anwar-manuality`
Status: `Proposed`

The first demo may rely on manual assembly for certain features such as layout generation, projection shaping, and related presentation mechanics.

#### Status Details
This requirement exists to protect demo scope and preserve momentum. The first goal is a convincing live system, not full automation of every supporting workflow.

#### Implementation
Manual preparation is explicitly acceptable for:

- layout creation
- node placement
- projection shaping
- curation of the demo path

So long as the resulting live system behaves coherently during the walkthrough.

#### Development
This requirement should be used to avoid unnecessary detours into generic automation before the demo target is met.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-demo-anwar-manuality-1 | Manual Layouts Allowed | Proposed | A requirement is not blocked solely because its layout or projection is assembled by hand. | |
| req-demo-anwar-manuality-2 | Live Behavior Still Required | Proposed | Manual preparation does not exempt the demo from needing to be live, clickable, and coherent during presentation. | |

#### Future
Replace manual demo scaffolding with durable generation and editing capabilities where justified.

### Non-Goals And Deferrals
----
RID: `req-demo-anwar-nongoals`
Status: `Proposed`

The first demo intentionally excludes several classes of work that may be desirable later but are not required to achieve the current show-and-tell objective.

#### Status Details
This requirement exists to constrain scope and reduce the risk of derailment during the current demo sprint.

#### Implementation
The following are explicitly not required for the first demo:

- advanced scrolling behavior
- automatic layout generation
- dynamic nesting behavior
- fully generalized perspective routing
- fully automated projection generation
- complete productization of Rampart

#### Development
If a proposed task does not materially advance one of the demo requirements in this specification, it should be considered out of scope for the initial Anwar demo unless it is needed to unblock a demo-critical dependency.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-demo-anwar-nongoals-1 | Fancy Scrolling Deferred | Proposed | The first demo does not require advanced scrolling or viewport mechanics beyond what is needed for the fixed views. | |
| req-demo-anwar-nongoals-2 | Automation Depth Deferred | Proposed | The first demo does not require automatic layout or projection generation. | |
| req-demo-anwar-nongoals-3 | Productization Deferred | Proposed | The first demo does not require a fully productized or generalized Rampart release. | |

#### Future
Promote deferred items into dedicated product or platform specs once the demo target is complete.

## Status Vocabulary

Use these values consistently in the Requirements table and each requirement's `Status` line:

| Status States |  |
| --- | --- |
| Proposed | Hey everyone, here's an idea. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on, see the Development section for more details. |
| Implemented | Has been written, see the Implementation section for how. |
| Verified | Has met the acceptance criteria as defined in that section. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer live. |

## RID Format

The Requirement ID (RID) is a unique text field separated by `-` and used for reference to the requirements throughout the codebase and documents.

Format: `req-<application>-<specification>-<feature>-<sub-feature>`

Acceptance criteria IDs should use the requirement RID followed by `-<number>`.

## Requirements Format

A requirement explanation section is formatted with a title, followed by a horizontal break, followed by `RID: \`req-example-spec-id\`` followed by `Status: \`Status State\``.

After that the feature is described in as much detail as needed. Depending on the feature this is where specifics of how the feature is implemented, gotchas, and all associated information needed to understand the feature go. If it starts getting too big consider making it a sub-feature and further breaking it down into smaller pieces.

Requirements can reference other requirements, designs, and should align with goals.

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details | Explanation for the current status state. |
| Implementation | How the feature is implemented in code, database, and operationally. This should be sufficient to inform re-implementation in the future and be kept up to date as the implementation evolves. |
| Development | Notes, lessons learned, and useful context identified during the development of the feature. Helps inform why the implementation is the way it is. |
| Acceptance Criteria | Table containing a uniquely identified list of acceptance criteria based on the RID followed by a `-` and a number. Tests are linked to criteria using `@pytest.mark.spec("acid-id")`. Acceptance criteria status follows the same status model as the requirements section. |
| Future | Notes on future ideas, concepts, and things to consider when doing further work on this feature. |
