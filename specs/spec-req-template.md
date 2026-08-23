# Feature Specification Template

## Philosophy
Describe why this feature exists, what problem it solves, and how it supports the broader goals of the project.

## Goals

The goals are a set of 3-5 things that this feature "must do" in order to be functional. They are specified as a named entity followed by a short description.

For this specification the goals are:

|   |   |  |
| :---: | --- | --- |
| 1. | Goal Name | Short description of the first required outcome. |
| 2. | Goal Name | Short description of the second required outcome. |
| 3. | Goal Name | Short description of the third required outcome. |

If there are more than 5 goals for a given feature, then you're probably dealing with multiple features.
It should be possible to identify which of the goals are advanced by each feature. If a feature doesn't advance a goal think hard about why that is.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-app-spec-feature | [Primary Requirement](#primary-requirement) | Proposed | Replace with summary note |
| req-app-spec-feature-sub | [Supporting Requirement](#supporting-requirement) | Proposed | Replace with summary note |

### Primary Requirement
----
RID: `req-app-spec-feature`  
Status: `Proposed`

Describe the requirement in as much detail as needed. Depending on the feature this is where specifics of how the feature is implemented, gotchas, and all associated information needed to understand the feature go. If it starts getting too big consider making it a sub-feature and further breaking it down into smaller pieces.

Requirements can reference other requirements, designs, and should align with goals.

#### Status Details
Explain the current lifecycle state of this requirement and any relevant context.

#### Implementation
Document how the feature is implemented in code, database, and operationally. This should be sufficient to inform re-implementation in the future and be kept up to date as the implementation evolves.

#### Development
Capture notes, lessons learned, and useful context identified during development. This helps explain why the implementation is the way it is.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-app-spec-feature-1 | Criterion Name | Proposed | Replace with a concrete, testable condition | Optional note |
| req-app-spec-feature-2 | Criterion Name | Proposed | Replace with a second concrete, testable condition | Optional note |

#### Future
Document future ideas, concepts, and things to consider when doing further work on this feature.

### Supporting Requirement
----
RID: `req-app-spec-feature-sub`  
Status: `Proposed`

Describe the supporting or nested requirement here.

Requirements can reference other requirements, designs, and should align with goals.

#### Status Details
Explain the current lifecycle state of this requirement and any relevant context.

#### Implementation
Document how the feature is implemented in code, database, and operationally.

#### Development
Capture notes, lessons learned, and useful context identified during development.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-app-spec-feature-sub-1 | Criterion Name | Proposed | Replace with a concrete, testable condition | Optional note |

#### Future
Document future ideas, concepts, and things to consider when doing further work on this feature.

## Status Vocabulary

Use these values consistently in the Requirements table and each requirement's `Status` line:

| Status States |  |
| --- | --- |
| Proposed | Hey everyone, here's an idea. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on, see the Development section for more details. |
| Implemented | Has been written, see the Implementation section for how. |
| Verified | Has met the acceptance criteria as defined in that section. |
| In Force | Standing doctrine: in effect now, and never "completed". Expects conformance from other work rather than an implementation of its own. |
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
