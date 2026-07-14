---
name: extract-claims
description: Extract atomic, context-preserving factual claims from AI-generated pipeline artifacts, write durable claim files, and ingest them into Observatory. Use for issue-scoped or artifact-scoped claim analysis before verification.
allowed-tools: Read, Write, Glob, Grep, Bash
user-invocable: true
---

# Extract Claims

Extract verifiable factual claims from pipeline artifact files, write structured JSON, and ingest into the Observatory service.

This stage identifies what was asserted; it does not decide whether an assertion
is true. Preserve the source's modality and scope so verification receives the
claim the author actually made.

## Inputs

This skill accepts inputs as positional arguments and/or kwargs in a `## Inputs` section appended to the prompt:

- **Issue key** (positional, e.g. `RHAISTRAT-1676`) — find all artifacts referencing this issue
- **artifact_filter** (kwarg, e.g. `strat-pipeline/RHAISTRAT-1676.md`) — file path substring to match specific artifact files
- **extractor_revision**, **repository_revision**, **model**, **harness**, and
  **configuration_digest** — resolved execution provenance supplied by the
  workflow; preserve these exact values in staged output. The extractor
  revision identifies the stage-specific Git tree, while repository revision
  identifies the commit resolved from the configured execution ref.
- **segmentation_version**, **preceding_context_units**, and
  **following_context_units** — deterministic segmentation settings supplied
  by the workflow; do not silently substitute different values
- **decontextualization_mode** (`basic` or `full`) — `basic` records whether
  each accepted claim is self-contained or needs review; `full` requires the
  independent extracted-versus-maximally-contextualized retrieval comparison
  and its digests for every accepted claim
- **`--force`** or **force** (boolean kwarg) — re-extract even if a
  `.claims.json` file already exists for the artifact

Example prompt with kwargs:
```
/extract-claims --headless RHAISTRAT-1676

## Inputs
- artifact_filter: strat-pipeline/RHAISTRAT-1676.md
```

If both an issue key and artifact_filter are provided, use both to narrow the
search. Treat a workflow-supplied `artifact_filter` as an exact artifacts-root
relative path. It must select at most one eligible file; fail if it ambiguously
matches multiple files.

Require at least one of `issue key` or `artifact_filter`. If no eligible files
match, report a successful zero-file result rather than inventing work.

## Artifacts Directory

The artifacts directory is resolved in this order:
1. `/app/artifacts` — K8s job container mount (preferred)
2. `./artifacts` — local project directory (fallback)

Use Bash to check which exists: `test -d /app/artifacts && echo /app/artifacts || echo ./artifacts`

## Step 1: Find Artifact Files

Search the artifacts directory for `.md` files matching the input criteria.

**File filtering rules (must match `extract-claims.py` behavior):**
- Skip hidden files and anything under `.git/`
- Skip files with `-strat-text.md` in the name (these are source inputs, not agent outputs)
- Skip files under `rfe-originals/` and `strat-originals/` directories
  (human/source inputs rather than generated pipeline outputs)
- Skip files under `ci-jobs/` directories (duplicates of data-repo files)
- Skip files under `claims/`, `verification/`, and `explanations/` directories
  (derived outputs from this claim-analysis pipeline)
- Skip `README.md` and `strat-rubric.md`
- For `strat-pipeline/` paths, only process files with names starting with `RHAISTRAT-`

Use `find` via Bash to locate matching files, then apply the filtering rules.

If an issue key was provided, also filter to files whose path or name contains the issue key.

Report the list of matching files before proceeding.

## Step 2: Segment the Artifact

For each matching artifact file:

1. Read the file content
2. Skip if content is under 100 characters
3. Check if a `.claims.json` file already exists at `{artifacts_dir}/claims/{relative_path}.claims.json` — skip unless `--force` was given
4. Resolve this skill's directory, then run its segmenter to produce
   deterministic source units:

```bash
SKILL_FILE=$(find . /app/.claude/skills/extract-claims \
  -path "*/extract-claims/SKILL.md" -type f 2>/dev/null | head -1)
SKILL_DIR=$(dirname "${SKILL_FILE:-.claude/skills/extract-claims/SKILL.md}")
test -f "$SKILL_DIR/scripts/segment-artifact.py"
test -f "$SKILL_DIR/scripts/create-staged-scaffold.py"
test -f "$SKILL_DIR/scripts/validate-stages.py"
test -f "$SKILL_DIR/scripts/project-legacy-claims.py"
test -f "$SKILL_DIR/schemas/staged-extraction.schema.json"
python3 "$SKILL_DIR/scripts/segment-artifact.py" --help
```

Do not look for these files under the repository-level `scripts/` directory.
If any required skill resource is unavailable, fail the extraction instead of
substituting manual segmentation or validation.

Use the same segmentation version and context-window configuration for every
artifact in a run. Preserve the generated `unit_key`, locator, heading path,
list preamble, and context arrays in all later stage results.

## Step 3: Run the Extraction Stages

Create the canonical artifact scaffold from each segmenter result before making
any model judgment:

```bash
python3 "$SKILL_DIR/scripts/create-staged-scaffold.py" "$SEGMENTS_JSON" \
  --output "$STAGED_JSON" \
  --pipeline-slug "$PIPELINE_SLUG" \
  --artifact-type "$ARTIFACT_TYPE" \
  --extractor-revision "$EXTRACTOR_REVISION" \
  --repository-revision "$REPOSITORY_REVISION" \
  --model "$MODEL" --harness "$HARNESS" \
  --configuration-digest "$CONFIGURATION_DIGEST" \
  --decontextualization-mode "$DECONTEXTUALIZATION_MODE" \
  --segmentation-version "$SEGMENTATION_VERSION" \
  --preceding-context-units "$PRECEDING_CONTEXT_UNITS" \
  --following-context-units "$FOLLOWING_CONTEXT_UNITS"
```

Populate that scaffold in place. Process every source unit independently
through the stages below. The only accepted durable shape is one top-level
`units` array whose entries embed `source_unit`, `selection`, `ambiguity`, and
`claims`. Never replace it with top-level `source_units`, `stages`, `selection`,
`ambiguity`, or `decomposition` arrays.

Do not silently repair, normalize, merge, or transform malformed model output.
Never default or infer a missing classification, ambiguity decision,
entailment result, coverage result, evidence record, acceptance decision, or
decontextualization result. A missing judgment is a failed extraction, not a
reasonable default.

When `artifact_filter` is provided, do not delegate extraction to another
agent. The workflow already provides artifact-level parallelism, and this
agent must populate and validate the one selected scaffold itself. For a local
issue-scoped invocation without `artifact_filter`, any delegated worker must
receive exactly one scaffold path and must populate the canonical nested shape
and run `validate-stages.py` itself. Treat a worker result that does not pass
validation as failed. The parent must not translate a worker-specific format
into the canonical format or fill in judgments on a failed worker's behalf.

1. **Selection** — classify the unit as `verifiable`, `mixed`, or
   `unverifiable`. For a mixed unit, select its exact verifiable portions.
2. **Disambiguation** — classify ambiguity as `none`, `resolved`, or
   `unresolved`. Check referential, structural, temporal, component/version,
   and proposal-versus-current-state ambiguity. Resolve only from the supplied
   unit context. An unresolved unit produces no claims.
3. **Decomposition** — extract independently verifiable claims using the rubric
   below. Preserve the exact source excerpt and record contextual clarification
   separately; never present clarification as quoted source text.

Every unit must have durable selection output, including unverifiable units.
Every selected unit must have durable ambiguity output, including unresolved
units. This makes abstention and coverage measurable instead of disappearing
from the output.

### Canonical staged shape

Each populated unit must retain the scaffold's deterministic `source_unit` and
use this structure:

```json
{
  "source_unit": {"id": "...", "kind": "sentence", "text": "...", "source_locator": "..."},
  "selection": {"classification": "verifiable", "evaluator_revision": "..."},
  "ambiguity": {"status": "none", "evaluator_revision": "..."},
  "claims": [{
    "claim_text": "...",
    "claim_type": "architectural",
    "original_text": "exact bounded-source excerpt",
    "accepted": true,
    "evaluation": {
      "evaluator_revision": "...",
      "entailed": true,
      "coverage_result": "complete",
      "coverage_elements": [{"element_text": "...", "element_kind": "verifiable", "coverage": "explicit"}],
      "decontextualization_result": "self_contained",
      "evidence": [{"evidence_type": "source_unit", "source_locator": "...", "excerpt": "..."}]
    }
  }]
}
```

Use `ambiguity: null` only for an `unverifiable` selection. An unresolved
ambiguity has a durable ambiguity object and no claims. The schema and validator
are authoritative when this abbreviated example omits an optional field.

### Extraction Rubric

Extract only statements that can be independently verified as true or false. Apply these rules:

1. **Extract only verifiable statements** — claims that involve reasoning or architectural knowledge
2. **Skip purely subjective content** — opinions, bare recommendations, and
   scoring rationale. If a recommendation contains a factual premise, extract
   the premise without turning the recommendation itself into a fact. Treat
   competitive-positioning phrases such as “key differentiator,” “better,” or
   “leading” as unverifiable unless the source supplies a defined comparison.
   When such a phrase embeds a factual premise (for example, that named managed
   services automate a specific operation), extract the premise separately and
   omit only the evaluative positioning.
3. **Decompose compound claims** — one fact per claim (atomic statements)
4. **Preserve context** — each claim must be understandable standalone
   - retain the subject, component, version, environment, and time scope
   - retain negation and qualifiers such as `may`, `must`, `currently`, and `proposed`
   - never rewrite a proposal or requirement as a statement about current reality
   - resolve pronouns only when the referenced subject is unambiguous
5. **Skip boilerplate metadata** — do NOT extract any of these:
   - Document status (e.g., "The strategy status is Refined")
   - Priority values (e.g., "The priority is Major/Critical/Normal")
   - Rubric scores and totals (e.g., "received a score of X out of Y")
   - Reviewer verdicts and bare recommendations (e.g., "the reviewer recommends
     approve"); still extract independently verifiable premises used to justify them
   - Effort estimates (e.g., "estimated at 3-5 sprints")
   - Generator attribution (e.g., "generated by an Agentic SDLC Pipeline")
   - Acceptance criteria counts or format descriptions
   - `needs_attention` flags or similar boolean fields
6. **Classify each claim** by type:
   - `factual` — concrete facts about things, people, products, dates
   - `architectural` — claims about software architecture, dependencies, APIs
   - `security` — claims about vulnerabilities, risks, security properties
   - `scope` — claims about project scope, size, complexity
   - `attribution` — claims about who did what, ownership, responsibility

### Legacy per-claim projection

Do not ask model workers to produce this shape. After the canonical staged
artifact passes validation, the deterministic projection script produces each
legacy claim object:

```json
{
  "claim": "the atomic verifiable statement",
  "type": "factual|architectural|security|scope|attribution",
  "original_text": "the exact source sentence(s) from the document"
}
```

`original_text` must be an exact excerpt from the source, not a paraphrase.
Do not emit duplicate normalized claim text within one source file.

## Step 4: Evaluate and Write Claims JSON

Before accepting a claim, judge whether the source unit plus its supplied
context entails it. Retain a non-entailed candidate with `accepted: false` as
a visible extraction error, but never send it to factual verification; factual
truth cannot compensate for a source-attribution error. Record element-level
coverage as `explicit`, `implicit`, or `omitted` for each verifiable source
element. Record each unverifiable source element as `omitted` when correctly
excluded or `included` when it leaked into a claim, so precision and explicit
unverifiable-inclusion rate can be measured.

Coverage is audited across the complete decomposition of a source unit. Assign
each verifiable source element to the atomic claim that expresses it; do not
mark that element `omitted` on sibling claims that intentionally express other
elements from the same unit. After drafting all sibling claims, audit their
combined coverage. Every verifiable source element must be `explicit` or
`implicit` on at least one accepted claim. If no accepted claim covers an
element, record it once as `omitted` on the closest candidate and mark that
candidate `partial` or `failed`. Likewise, record an unverifiable element as
`included` only on the claim into which it actually leaked.

Set `coverage_result` from those elements, not from whether the source unit was
classified `mixed`. Use `complete` only when every verifiable element is
`explicit` or `implicit` and every unverifiable element is `omitted`. Use
`partial` or `failed` when at least one verifiable element is `omitted` or one
unverifiable element is `included`. The validator rejects inconsistent labels.

In `basic` mode, each accepted claim must record `self_contained`,
`needs_review`, or `not_sampled`. Use `desirable` or `undesirable` only after
performing the full comparison below.

In `full` mode (required for regression and sampled production claims), perform
the full comparison for every accepted claim:

1. Generate a maximally contextualized comparison claim using only the heading,
   list preamble, and bounded source context.
2. Retrieve evidence independently for the extracted and comparison claims,
   using identical retrieval limits. Record deterministic digests of each
   retrieval query/result set and the common evidence context.
3. Judge whether omitted context changes the evidence set or its relationship
   to the claim.
4. Record `desirable` only when the shorter claim preserves meaning and
   evidence behavior; otherwise record `undesirable` with the omitted context.

Do not use stylistic preference or claim length as a proxy for this result.
The validator rejects `self_contained`, `needs_review`, and `not_sampled` for
accepted claims in `full` mode, and rejects `desirable` or `undesirable` unless
all four comparison fields are non-empty.

For each processed artifact file, project and write the legacy claims to:

```
{artifacts_dir}/claims/{pipeline_slug}/{original_filename}.claims.json
```

Where `{pipeline_slug}` is the first path component under the artifacts directory (e.g., `strat-pipeline`, `security-reviews`, `rfe-assessor`).

Use this compatibility format for the output file:

```json
{
  "source_file": "strat-pipeline/RHAISTRAT-1676.md",
  "pipeline_slug": "strat-pipeline",
  "claim_count": 42,
  "claims": [
    {
      "claim": "RHOAI 3.5 requires mTLS between all control-plane components",
      "type": "security",
      "original_text": "The strategy mandates mutual TLS for all control-plane service-to-service communication in RHOAI 3.5"
    }
  ]
}
```

Also write the complete staged run to the same relative path with suffix
`.extraction.json`. This is the authoritative v2 artifact sent to Observatory
and must contain:

- run identity, source digest, extractor/model/harness/configuration revisions;
- the artifact class (`artifact_type`) separately from its storage-oriented
  `pipeline_slug`, so metrics can be compared across RFE, strategy,
  security-review, Epic, investigation, and code-generation outputs;
- every deterministic `source_unit`;
- one `selection` result for every unit;
- `ambiguity` for each selected unit;
- zero or more decomposed claims per unit;
- extraction `evaluation` for each accepted claim, including entailment,
  coverage, and decontextualization status.

In the staged artifact use canonical v2 names `claim_text` and `claim_type`;
retain `claim` and `type` only in the flattened legacy projection. The
segmenter's `id`/`kind`/`text` source-unit fields are accepted directly by the
v2 API as aliases for `unit_key`/`unit_kind`/`original_text`.

The legacy `.claims.json` is a flattened compatibility projection only. Run
the validator and projector exactly as follows:

```bash
python3 "$SKILL_DIR/scripts/validate-stages.py" "$STAGED_JSON"
python3 "$SKILL_DIR/scripts/project-legacy-claims.py" "$STAGED_JSON" \
  --output "$CLAIMS_JSON"
```

The validator performs full JSON Schema validation and cross-stage invariant
checks. If validation fails, preserve the invalid candidate separately for
diagnosis, report failure, and do not write the authoritative staged artifact,
project legacy claims, ingest, or emit a completion receipt. Do not write a
script during the run to convert an invalid candidate into a passing artifact.

Create parent directories as needed with `mkdir -p`.

If the shared `claims/` directory is not writable, stop and report the
permission error. Never rename, replace, recursively delete, or move the shared
`claims/` directory or its `.receipts/` directory to work around permissions.

The projector writes legacy JSON atomically and verifies the canonical input
again. Write the staged JSON atomically after it passes validation. A
zero-claim file is a valid durable result.

## Step 5: Ingest into Observatory

After writing claims JSON files, POST each file's claims to the Observatory service for database ingestion.

**Observatory URL** (resolved in order):
1. `$OBSERVATORY_URL` environment variable (if set)
2. `http://observatory.ai-pipeline.svc.cluster.local:8000` (K8s in-cluster default)

Prefer the versioned extraction-run endpoint with `.extraction.json` so source occurrences and stage
results remain immutable:

`POST {observatory_url}/api/v2/claims/extraction-runs`

On success, atomically add the returned run ID as `observatory_run_id` to the
staged artifact before the workflow writes its receipt. Preserve the response's
occurrence IDs as `observatory_occurrence_ids`; later stages must use those IDs
rather than normalized legacy claim IDs. Parse and preserve the exact IDs from
the response. Never infer, renumber, or synthesize them as a sequential range.
Run `validate-stages.py` again after adding both fields; the validator requires
exactly one returned occurrence ID per staged claim.

During migration, if that endpoint returns `404`, fall back to the legacy
endpoint for the flattened claims only and report that stage provenance was not
ingested. For each legacy claims file written in Step 4, POST to
`{observatory_url}/api/claims/ingest`:

```bash
curl -s -X POST "{observatory_url}/api/claims/ingest" \
  -H "Content-Type: application/json" \
  -d @"{claims_json_file}" \
  --max-time 30
```

The endpoint accepts the exact JSON format written in Step 3. It returns:

```json
{
  "ingested": 42,
  "new": 15,
  "duplicate": 27,
  "jira_links": 8,
  "sources_added": 1
}
```

If the Observatory is unreachable (connection refused, timeout), log the error and continue. The claims JSON files on disk are the primary output; ingestion can be retried later.

Treat non-2xx responses and malformed response JSON as ingestion failures too.
Do not report a file as ingested unless the endpoint confirms it. Preserve the
disk output and distinguish `written`, `ingested`, and `ingestion_failed` in the
summary.

## Step 6: Report Results

After processing all files, output a summary:

```
## Claim Extraction Summary

- **Files processed:** 3
- **Files skipped (already extracted):** 1
- **Total claims extracted:** 87
- **Claims by type:** factual: 32, architectural: 28, security: 15, scope: 8, attribution: 4

### Observatory Ingestion
- **New claims ingested:** 52
- **Duplicate claims:** 35
- **Jira links created:** 23

### Files
| Source File | Claims | Status |
|---|---|---|
| strat-pipeline/RHAISTRAT-1676.md | 42 | ingested |
| security-reviews/RHAISTRAT-1676-security-review.md | 31 | ingested |
| strat-pipeline/RHAISTRAT-1677.md | 14 | ingested |
```

$ARGUMENTS
