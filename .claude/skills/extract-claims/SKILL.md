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
- **`--force`** — re-extract even if a `.claims.json` file already exists for the artifact

Example prompt with kwargs:
```
/extract-claims --headless RHAISTRAT-1676

## Inputs
- artifact_filter: strat-pipeline/RHAISTRAT-1676.md
```

If both an issue key and artifact_filter are provided, use both to narrow the search.

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
- Skip files under `strat-originals/` directories (source RFE texts)
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
test -f "$SKILL_DIR/scripts/validate-stages.py"
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

Process every source unit independently through these stages. Emit valid JSON
for each stage before continuing; do not silently repair malformed model output.
The combined artifact must conform to
`$SKILL_DIR/schemas/staged-extraction.schema.json` in addition to the
cross-stage invariants enforced by
`$SKILL_DIR/scripts/validate-stages.py`.

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

### Extraction Rubric

Extract only statements that can be independently verified as true or false. Apply these rules:

1. **Extract only verifiable statements** — claims that involve reasoning or architectural knowledge
2. **Skip purely subjective content** — opinions, bare recommendations, and
   scoring rationale. If a recommendation contains a factual premise, extract
   the premise without turning the recommendation itself into a fact.
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

### Per-Claim Output

For each extracted claim, produce an object:

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

Decontextualization evaluation may be sampled outside the regression corpus,
but each accepted claim must record whether it is self-contained or needs
review.

For regression and sampled production claims, perform the full comparison:

1. Generate a maximally contextualized comparison claim using only the heading,
   list preamble, and bounded source context.
2. Retrieve evidence independently for the extracted and comparison claims,
   recording identical retrieval limits and the query/evidence digests.
3. Judge whether omitted context changes the evidence set or its relationship
   to the claim.
4. Record `desirable` only when the shorter claim preserves meaning and
   evidence behavior; otherwise record `undesirable` with the omitted context.

Do not use stylistic preference or claim length as a proxy for this result.

For each processed artifact file, write the claims to:

```
{artifacts_dir}/claims/{pipeline_slug}/{original_filename}.claims.json
```

Where `{pipeline_slug}` is the first path component under the artifacts directory (e.g., `strat-pipeline`, `security-reviews`, `rfe-assessor`).

Use this JSON schema for the output file:

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
`$SKILL_DIR/scripts/validate-stages.py` against the staged artifact before
writing either file. If validation fails, preserve the invalid candidate separately for
diagnosis, report failure, and do not ingest or emit a completion receipt.

Create parent directories as needed with `mkdir -p`.

If the shared `claims/` directory is not writable, stop and report the
permission error. Never rename, replace, recursively delete, or move the shared
`claims/` directory or its `.receipts/` directory to work around permissions.

Write each JSON file atomically (temporary file followed by rename). Before
renaming, parse it again and verify that `claim_count == len(claims)`, every
claim has non-empty `claim`, `type`, and `original_text`, and `type` is one of
the five allowed values. A zero-claim file is a valid durable result.

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
rather than normalized legacy claim IDs.

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
