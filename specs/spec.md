# Spec Spec

## Philosophy 
This file defines the specification format that will be used for features developed.  This sits below the level of design files - which focus on the whole of the app / large sets of related features - and provides a human and AI-readable persistent repository of intention and state that moves us beyond vibe coding and into more thoughtful, consistent, and repeatable architecture.

Each spec will have a philosophy section which describes the "why" of this feature and it's alignment with the overall goals of the project.

## Goals

The goals are a set of 3-5 things that this feature "must do" in order to be functional. They are specified as a named entity followed by a short description.

For this specification the goals are:

|   |   |  |
| :---: | --- | --- |
| 1. | Recreate | The spec and design files should be sufficient to re-create the entire application from whole cloth. |
| 2. | Pivot Point | This is the pivot point for creation of new features, documentation of how they should work, and their implementation and testing status |
| 3. | Reference Everywhere | Specs contain reference IDs that are referenced throughout the code, tests, specs, and docs |

If there are more than 5 goals for a given feature, then you're probably dealing with multiple features.
It should be possible to identify which of the goals are advanced by each feature.  If a feature doesn't advance a goal think hard about why that is.


## Requirements

| RID | Name | Status | Notes |
| --- | -----| :------: | ----- |
| req-spec-table | [Requirements Table](#requirements-table) | In Development | Hooray, self-referential features |
| req-spec-rid | [Requirement ID](#requirement-id) | In Development | |
| req-spec-stat | [Requirement Status](#requirement-status) | In Development | |
| req-spec-fmt | [Requirements Format](#requirements-format) | In Development | |
| req-spec-test | [Test Linkage](#test-linkage) | In Development | Convention for associating tests with acceptance criteria |
| req-spec-loc | [Spec File Location](#spec-file-location) | In Development | Convention for where spec files live |



### Requirements Table
----
RID: `req-spec-table`  
Status: `In Development`

The Requirements section contains a table displaying the high-level set of requirements and their status. This is the quick-glance view and is used for navigation in the page.

| Req Table Columns |  |
| --- | --- |
| RID | The requirements ID for the requirement |
| Name | Human-readable name |
| Status | Implementation status |
| Notes | Any high level info people should know |

The Requirements Table comes before each of the requirements are listed below and is updated as needed.


### Requirement ID
----
RID: `req-spec-rid`  
Status: `In Development`

The Requirement ID (RID) is a unique text field separated by `-` and used for reference to the requirements throughout the codebase and documents.

Format:  req-\<application\>-\<specification\>-\<feature\>-\<sub-feature\>

Sub-features follow the same specification structure with nested RIDs.


### Requirement Status
----
RID: `req-spec-stat`  
Status: `In Development`

The requirement status is an indicator of the state of the requirement in the feature lifecycle.

| Status States |  |
| --- | --- |
| Proposed | hey everyone, here's an idea |
| Approved for Development | requirement is accepted and ready to be implemented |
| In Development | actively being worked on, see the Development section for more details |
| Implemented | has been written, see implementation section for how |
| Verified | has met the acceptance criteria as defined in that section |
| Refactoring | in the process of being re-worked |
| Deprecating | in the process of being deprecated, watch out! |
| Deprecated | no longer live |

Each of the status sections will be reflected in the requirement as the feature enters each of the phases.

### Requirements Format
----
RID: `req-spec-fmt`  
Status: `In Development`

A requirement explanation section is formatted with a title, followed by a horizontal break, followed by RID: \`req-example-spec-id\` followed by Status: \`Status State\`

Followed by Status in the form Status: \<Current Status State\> and a section describing why and what's going on.  This should match the requirements table.

After that the feature is described in as much detail as needed.  Depending on the feature this is where specifics of how the feature is implemented, gotchas, and all associated information needed to understand the feature go.  If it starts getting too big consider making it a sub-feature and further breaking it down into smaller pieces.

Requirements can reference other requirements, designs, and should align with goals.

|  Sub-Sections | (as needed) |
| --- | --- |
| Status Details | Explanation for the current status state. |
| Implementation | how the feature is implemented in code, database, and operationally. This should be sufficient to inform re-implementation in the future and be kept up to date as the implementation evolves. |
| Development | Notes, lessons learned, and useful context identified during the development of the feature. Helps inform why the implementation is why it is. |
| Acceptance Criteria | Table containing uniquely identified list of acceptance criteria based on the RID followed by a `-` and a number. Will be used for associating with test cases. Acceptance criteria status follows the same status as the requirements section. |
| Future | Notes on future ideas, concepts, and things to consider when doing further work on this feature. |

### Test Linkage
----
RID: `req-spec-test`
Status: `In Development`

Tests are linked to acceptance criteria using the `@pytest.mark.spec` marker with the ACID as the argument.

```python
@pytest.mark.spec("req-example-dimension-core-1")
def test_dimensions_json_shape():
    ...
```

A single test may reference multiple ACIDs if it validates more than one criterion. A requirement moves to `Verified` status when all of its acceptance criteria have passing, linked tests.

### Spec File Location
----
RID: `req-spec-loc`
Status: `In Development`

Spec files are organized by scope:

| Location | Contents |
| --- | --- |
| `specs/` (repo root) | The meta-spec (`spec.md`), the annotated template (`spec-req-template.md`), and the blank starter template (`spec-req-template-empty.md`) |
| `<app>/specs/` | Feature specs that belong to that Django application |

Each Django application that has specified features should have a `specs/` subdirectory. Cross-cutting specs that span multiple applications live at the repo root `specs/` level.
