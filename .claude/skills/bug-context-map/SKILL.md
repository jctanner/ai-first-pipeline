---
name: bug-context-map
description: Map bug to available architecture context
allowed-tools: Read, Write, Glob, Grep
---

# Bug Context Mapping

Map a Jira bug to available architecture documentation and source code, producing both a machine-readable JSON result and a human-readable markdown summary.

## Instructions

### JSON Schema

Your primary output is a JSON file conforming to this schema.

**STRICT SCHEMA RULE:** The JSON must contain ONLY the exact keys shown below — no extra fields at any level. Do NOT add `*_note`, `*_override_note`, `name` (on context_entries), or any other invented keys anywhere in the JSON. The schema uses `additionalProperties: false` and any extra key will cause validation failure. If you want to explain something, use the existing `justification`, `reason`, or `missing_context` fields.

Schema:

```json
{
  "issue_key": "RHOAIENG-XXXXX",
  "identified_components": [
    {
      "name": "kserve",
      "source": "Jira component field"
    }
  ],
  "context_entries": [
    {
      "component": "kserve",
      "architecture_doc": "architecture-context/architecture/rhoai-3.4-ea.2/kserve.md",
      "source_checkout": "architecture-context/checkouts/rhoai-3.4-ea.2/kserve",
      "rating": "full-context"
    }
  ],
  "overall_rating": "full-context",
  "relevant_files": [
    "architecture-context/architecture/rhoai-3.4-ea.2/kserve.md"
  ],
  "missing_context": [
    "No source checkout available for component X"
  ],
  "affected_versions": ["3.4"],
  "context_helpfulness": {
    "overall_score": 67,
    "coverage": {
      "score": 100,
      "justification": "Architecture doc covers the kserve serving pipeline in detail"
    },
    "depth": {
      "score": 50,
      "justification": "Doc describes high-level flow but lacks internal error-handling paths"
    },
    "freshness": {
      "score": 50,
      "justification": "Doc is for 3.4-ea.2 but bug may involve changes merged after that snapshot"
    }
  },
  "repos_and_files_used": [
    {
      "repository": "architecture-context/architecture/rhoai-3.4-ea.2",
      "files": ["kserve.md"]
    },
    {
      "repository": "architecture-context/checkouts/rhoai-3.4-ea.2/kserve",
      "files": ["pkg/controller/v1beta1/inferenceservice/controller.go"]
    }
  ],
  "repos_and_files_needed": [
    {
      "repository": "red-hat-data-services/some-unlisted-component",
      "files": ["controllers/reconciler.go"],
      "reason": "Component has no architecture doc or source checkout in architecture-context; needed to understand the reconciliation logic described in the bug"
    }
  ]
}
```

- `identified_components`: array of objects with `name` (string) and `source` (string describing how it was identified)
- `context_entries`: array of objects with:
  - `component`: component name
  - `architecture_doc`: path to doc or `"not found"`
  - `source_checkout`: path to checkout or `"not found"`
  - `rating`: one of `"full-context"`, `"partial-context"`, `"no-context"`, `"cross-component"`
- `overall_rating`: one of `"full-context"`, `"partial-context"`, `"no-context"`, `"cross-component"`
- `relevant_files`: array of paths to architecture docs relevant to this bug
- `missing_context`: array of strings describing context gaps
- `affected_versions`: array of version strings mentioned or inferred
- `context_helpfulness`: object scoring how helpful the available context is:
  - `overall_score`: number 0-100 (weighted average of dimension scores)
  - `coverage`: object `{ score, justification }` — does available context cover the area of the bug?
  - `depth`: object `{ score, justification }` — is the context detailed enough to understand the problem?
  - `freshness`: object `{ score, justification }` — is the context current for the affected version?
- `repos_and_files_used`: array of objects listing repos/doc sets and specific files that were consulted:
  - `repository`: string (repo name or architecture doc set path)
  - `files`: array of strings (specific file paths that were consulted and relevant)
- `repos_and_files_needed`: array of objects listing repos/files that are missing or would help:
  - `repository`: string (repo that would be needed)
  - `files`: array of strings (specific files that would help but don't exist or weren't found)
  - `reason`: string (why this is needed)

### Context Rating Definitions

| Rating | Meaning |
|--------|---------|
| `full-context` | Component doc exists, source checkout available, dependencies mapped |
| `partial-context` | Component doc exists but no source checkout, or source exists but component not clearly identified |
| `no-context` | Component not documented in architecture-context, or bug doesn't identify a component |
| `cross-component` | Bug spans multiple components; some have context, some don't |

### Context Helpfulness Scoring Rubric

Score each dimension as 0, 50, or 100:

| Dimension | 0 (None) | 50 (Partial) | 100 (Sufficient) |
|-----------|----------|--------------|-------------------|
| **Coverage** | No architecture docs or source code cover the area of the bug | Some docs/source exist but don't cover the specific subsystem or code path | Docs and/or source fully cover the affected component and code path |
| **Depth** | Available context is too high-level or generic to understand the problem | Context describes the component but lacks internal details (error handling, edge cases, config) | Context includes implementation details, data flow, and error handling relevant to the bug |
| **Freshness** | Context is for a different major version or is significantly outdated | Context is for a nearby version but may miss recent changes relevant to the bug | Context matches the affected version or is confirmed current |

Compute `overall_score` as the weighted average: `(coverage.score * 0.4) + (depth.score * 0.35) + (freshness.score * 0.25)`, rounded to the nearest integer.

**IMPORTANT:** The `context_helpfulness` object must contain ONLY the four keys shown above: `overall_score`, `coverage`, `depth`, and `freshness`. Do NOT add any extra keys such as `depth_note`, `depth_override_note`, or similar. Put all explanatory text inside the `justification` field of each dimension.

### Understanding the architecture-context directory structure

The architecture-context directory is organized by RHOAI release version:

- **Architecture docs:** `architecture-context/architecture/rhoai-{VERSION}/{component}.md`
- **Source checkouts:** `architecture-context/checkouts/red-hat-data-services.rhoai-{VERSION}/{component}/`

The `{VERSION}` corresponds to an RHOAI release branch (e.g. `2.25`, `3.0`, `3.4-ea.2`). The `{component}` folders under each version are downstream repo names — these may differ from upstream or midstream repo names referenced in bugs (e.g. `opendatahub-io/opendatahub-operator` is checked out as `rhods-operator`).

**Before assessing what's missing, always enumerate what's available:**

1. List `architecture-context/architecture/` to see which versions have docs
2. List `architecture-context/checkouts/` to see which versions have source
3. List the component folders under the version closest to the bug's affected version
4. Match the bug's referenced repos/components against those folder names — strip the org prefix and look for the component name in the listing

### Repos and Files Tracking

When producing the context map:

1. **`repos_and_files_used`**: List every repository (or architecture doc set) and the specific files within it that you actually read and found relevant. Use the paths as they appear in the architecture-context directory (e.g. `architecture-context/checkouts/red-hat-data-services.rhoai-3.4-ea.2/odh-dashboard`).

2. **`repos_and_files_needed`**: List only repos whose component does NOT appear in any `architecture-context/architecture/rhoai-*/` doc or `architecture-context/checkouts/red-hat-data-services.rhoai-*/` folder. If you found and used a component's checkout or doc, it is available — do not list it here. If you wish a specific file existed within an available checkout, note that in `missing_context` instead. Include a `reason` for each truly missing repo.

### Steps

1. **Extract component identifiers** from the bug:
   - Jira `components` field
   - Keywords in summary/description (e.g., "kserve", "dashboard", "notebook-controller", "model-registry", "trustyai", "kueue", "vllm", "codeflare")
   - Repo references in comments or description (GitHub/GitLab URLs)
   - Map any upstream repo names to their downstream equivalents (see table above)

2. **Search architecture context:**
   - Look in `architecture-context/architecture/` for component docs matching the identified components
   - Check `architecture-context/checkouts/` for source code availability
   - Search for the component name in architecture doc filenames and content
   - Try alternate names (upstream/downstream equivalents) if the first search finds nothing

3. **Assess context sufficiency** for each component using the ratings above.

4. **Determine the overall rating** based on all components found.

### Output Format

Write **two files**:

1. **`issues/{KEY}.context-map.json`** — the JSON object described above
2. **`issues/{KEY}.context-map.md`** — a human-readable rendering:

```markdown
# Context Map: {KEY}

## Identified Components

- [Component name] — [how it was identified: Jira component, keyword, URL, etc.]

## Architecture Context Found

| Component | Architecture Doc | Source Checkout | Rating |
|-----------|-----------------|-----------------|--------|
| [name] | [path or "not found"] | [path or "not found"] | [rating] |

## Overall Context Rating: [full-context / partial-context / no-context / cross-component]

## Context Helpfulness: [overall_score] / 100

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Coverage  | [0/50/100] | [justification] |
| Depth     | [0/50/100] | [justification] |
| Freshness | [0/50/100] | [justification] |

## Repos & Files Used

- **[repository]**: [file1], [file2], ...

## Repos & Files Needed (Gaps)

- **[repository]**: [file1], [file2], ... — [reason]

## Relevant Architecture Files

- [List of specific architecture doc paths that are relevant to this bug]

## What's Missing

- [List of context gaps that would need to be filled for a fix attempt]

## Affected RHOAI Versions

- [Versions mentioned in the bug or inferred from components]
```

Search thoroughly through the architecture-context directory. Use Glob and Grep to find matching files. Verify that files you reference actually exist.
