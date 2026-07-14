---
name: verify-claims
description: Verify extracted claims against version-appropriate source material and architecture context, record evidence-backed verdicts, and submit them to Observatory. Use only after claim extraction; do not infer forensic root cause in this stage.
allowed-tools: Read, Write, Glob, Grep, Bash
user-invocable: true
---

# Verify Claims

Verify previously extracted claims by evaluating them against source material
and architecture documentation. Produces canonical v2 verdicts (`supported`,
`contradicted`, `insufficient_evidence`, or `not_applicable`) with confidence
triage ranks, writes verification logs, and submits results to Observatory.

This stage decides what the available evidence supports. It does not explain
why the generating agent made the claim; `explain-claims` owns forensic root
cause attribution after verdicts exist.

## Inputs

This skill accepts inputs as positional arguments and/or kwargs in a `## Inputs` section appended to the prompt:

- **Issue key** (positional, e.g. `RHAISTRAT-1676`) — verify claims linked to this Jira key
- **claim_ids** (kwarg, e.g. `123,456,789`) — verify specific claim IDs
- **claim_types** (kwarg, e.g. `security,architectural`) — only verify claims of these types
- **implementation_revision**, **repository_revision**, **model**, **harness**,
  and **configuration_digest** — resolved verifier tree identity and resolved
  repository commit to persist
- **evidence_revision** and **evidence_context_digest** — immutable evidence
  dependency identity; the recorded digest must match the workflow input
- **`--force`** or **force** (boolean kwarg) — re-verify claims that already
  have verdicts

Example prompt with kwargs:
```
/verify-claims --headless RHAISTRAT-1676

## Inputs
- claim_types: security,architectural
```

## Directory Layout

Resolve directories in this order:

| Path | K8s | Local fallback |
|------|-----|----------------|
| Artifacts | `/app/artifacts` | `./artifacts` |
| Architecture context | `/app/.context/architecture-context` | `.context/architecture-context` |

Use Bash to detect: `test -d /app/artifacts && echo /app || echo .`

## Step 1: Fetch Claims to Verify

Fetch claims from the Observatory API, falling back to disk if unreachable.

**Observatory URL** (resolved in order):
1. `$OBSERVATORY_URL` environment variable
2. `http://observatory.ai-pipeline.svc.cluster.local:8000`

### API approach (preferred)

Fetch pending, extraction-entailed occurrences for the issue using the API's
maximum page size:

```bash
curl -s "$observatory_url/api/v2/claims/occurrences?jira_key=$ISSUE_KEY&pending_only=true&limit=1000"
```

Count the returned occurrences before filtering or delegating work. If the API
returns exactly 1000 occurrences, stop with an explicit overflow error; the
endpoint may have truncated the candidate set, and a partial “successful”
verification would violate the workflow gate. Never replace this query with a
smaller fixed limit. If `claim_ids` was supplied, confirm that every requested
ID is present after applying the extraction-entailment and source-file rules;
report any missing IDs rather than silently completing a subset.

This returns `{"occurrences": [...]}` where each occurrence has:
- `id` — claim occurrence ID (needed for the immutable verification run)
- `claim_text` — the claim to verify
- `claim_type` — factual/architectural/security/scope/attribution
- source file, stable locator, source-unit text, and context window
- modality, product version, and temporal scope
- extraction entailment, coverage, and decontextualization outcomes

Never verify an occurrence unless `extraction_entailed` is true. Route failed or
missing extraction assurance to review instead. If `claim_types` is provided,
filter after fetching. If `--force`, use `pending_only=false`; this creates a
new verification run and preserves earlier runs.

Exclude occurrences whose `source_file` is under `rfe-originals/`,
`strat-originals/`, or `ci-jobs/`. Those are human/source inputs or duplicate
transport artifacts, not generated outputs owned by claim assurance.

If the v2 endpoint returns `404` during migration, use the legacy claims API
and explicitly mark the result as legacy/unassured. Do not use legacy fallback
for other non-2xx responses.

### Disk fallback

If the Observatory is unreachable, prefer staged
`{artifacts_dir}/claims/**/*.extraction.json` files and select only claims with
`evaluation.entailed == true`. Legacy `.claims.json` files lack occurrence IDs
and assurance, so they can only produce explicitly legacy log files and must
not satisfy the workflow assurance gate.

Report the number of claims found and their type distribution before proceeding.
If no matching pending claims exist, report a successful no-op and stop.

## Step 2: Gather Evidence for Each Claim

For each claim, gather relevant source material based on the claim type and source file. Evidence comes from three categories:

### 2a. Source Documents

Find source/ground-truth files related to the claim's source artifact. Given the `source_file` field (e.g. `strat-pipeline/RHAISTRAT-1676.md`):

- Look for sibling files: `*-strat-text.md`, `*-threat-surface.md` in the same directory or parent
- Look for `strat-originals/` directory at the parent level — these are the original RFE texts
- Read these files as "Source" evidence (they describe what was PROPOSED, not current platform state)

### 2b. Architecture Context (for `architectural` and `security` claims)

Use **both** `arch-query` (structured queries) and **raw file reads** (full narrative) to gather evidence. They complement each other — arch-query gives fast structured lookups (ports, webhooks, CRDs, deps), while raw files contain data flows, proxy chains, deployment topology, and architectural narratives that the structured output omits.

#### arch-query CLI

The `arch-query` binary is installed at `/usr/local/bin/arch-query`. It queries structured RHOAI architecture documentation with embedded data.

**Version handling:** Do NOT specify `--version` unless the claim references a specific RHOAI release (e.g., "RHOAI 3.4"). The default is `rhoai.next` which has the most complete component coverage. Only add `--version rhoai-3.4` when verifying claims specifically about the 3.4 GA release. List available versions with `arch-query versions`.

| Subcommand | When to use | Example |
|------------|-------------|---------|
| `component {name}` | Claim mentions a specific component | `arch-query component training-operator` |
| `search {term}` | Don't know the exact component name | `arch-query search "model serving"` |
| `grep {term}` | Search for a term across ALL components | `arch-query grep "mTLS"` |
| `list --names-only` | Need to see all available component names | `arch-query list --names-only` |
| `ports` or `ports {component}` | Claims about ports, protocols, TLS | `arch-query ports kserve` |
| `webhooks` or `webhooks {component}` | Claims about webhook counts or types | `arch-query webhooks training-operator` |
| `deps {component}` | Claims about dependencies | `arch-query deps odh-dashboard` |
| `crds` or `crds {component}` | Claims about CRDs | `arch-query crds kserve` |
| `images` or `images {filter}` | Claims about container images | `arch-query images mlflow` |
| `watches` or `watches {component}` | Claims about controller watches | `arch-query watches rhods-operator` |
| `platform` | Platform-level summary (component counts, image counts) | `arch-query platform` |
| `overlays` | Recent architecture changes, renames, policies | `arch-query overlays` |
| `diff {component} --from {v1} --to {v2}` | Compare versions | `arch-query diff kserve --from rhoai-3.3 --to rhoai-3.4` |

Add `-o raw` to any subcommand to get the full unstructured markdown instead of the structured summary.

**Component name tips:**
- Component names are lowercase with hyphens: `training-operator`, `odh-dashboard`, `kserve`
- If unsure of the exact name, use `search` first, then `component` with the result
- Common aliases: OGX = llama-stack, OGX Operator = llama-stack-k8s-operator
- Use `list --names-only` to see all component names

#### Raw Architecture Docs

Read the full component markdown files directly for data flows, integration points, and architectural narrative:

```
{context_dir}/architecture-context/architecture/{version}/{component}.md
```

**Directory structure:**
```
{context_dir}/architecture-context/
├── architecture/
│   ├── rhoai-3.4/           # GA release docs
│   │   ├── component-name.md
│   │   └── PLATFORM.md
│   ├── rhoai-3.5-ea.1/      # EA release docs
│   └── rhoai.next/           # Next release docs (most complete)
└── overlays/                # Human-authored corrections & policies
    ├── 0001-*.md
    ├── 0008-no-external-operator-auto-install-policy.md
    └── ...
```

Use `grep -r` to search for technical terms from the claim (mTLS, FIPS, kube-rbac-proxy, NetworkPolicy, port numbers, etc.) across the raw docs. For platform-level claims, read `PLATFORM.md`.

#### Overlays

**Check overlays** for recent architecture changes, renames, version bumps, and platform policies. Read any overlay referenced by number in the claim, or grep overlays for claim keywords. Overlays are authoritative first-class architecture context — treat them the same as component docs.

Access via either:
- `arch-query overlays` (structured summary)
- `ls {context_dir}/architecture-context/overlays/` + read individual files (full content)

#### Evidence Gathering Steps

1. Run `arch-query component {name}` for each component mentioned in the claim
2. Read the raw `.md` file for the same component(s) — especially for claims about data flows, proxy chains, or deployment topology
3. Use `arch-query grep {term}` or `grep -r` on raw docs for technical terms in the claim
4. For platform-level claims, run `arch-query platform` and read `PLATFORM.md`
5. Check overlays via `arch-query overlays` and read any overlay referenced in the claim
6. For version-specific claims, use `arch-query diff` to compare versions

Query only components and terms mentioned in the claim — don't fetch everything.

Record the exact version, command/query, file path, and relevant section for
every source actually used. Evidence must be reproducible; a bare component
name or uncited model recollection is not evidence.

### 2c. NFR Checklist (for `security` claims)

If available, read the NFR checklist at:
```
{artifacts_dir}/../.claude/skills/strat-security-review/references/nfr-checklist.md
```
Or search for it:
```bash
find {base_dir} -path "*/strat-security-review/references/nfr-checklist.md" -type f 2>/dev/null | head -1
```

The checklist defines platform-wide security requirements. Three cases:
1. A claim that **applies** a checklist requirement to a specific component (e.g., "Kagenti must be built with CGO_ENABLED=1 for FIPS") → **supported** if the checklist defines that requirement for the component's language/type
2. A claim that **restates** a checklist item as a review requirement → **supported**
3. A claim that asserts a component **already implements** something (e.g., "component X has FIPS mode enabled") → requires verification against architecture docs. The checklist defines requirements, not current implementation state.

## Step 3: Evaluate Each Claim

For each claim, evaluate it against the gathered evidence. You ARE the verification judge.

### Verification Rules

**CRITICAL DISTINCTION:** Pay attention to the type of evidence:

1. **Source documents** (strat-text, strat-originals) describe what is being PROPOSED. They are NOT evidence of current platform state.
2. **Architecture context docs** represent what CURRENTLY EXISTS in the platform. These are authoritative for architectural claims.
3. **Overlay files** are human-authored corrections and platform policies. They are authoritative first-class architecture context — treat them the same as architecture docs.
4. **NFR checklist items** are ground truth for security requirements.

**For architectural and security claims: ALWAYS query architecture docs before rendering a verdict**, even if source documents seem sufficient. Source documents describe proposals — you must cross-reference against actual architecture docs to determine whether something exists in the platform or is merely proposed.

When a claim says something "does not exist" or "has no reference" in the platform, verify against architecture docs ONLY, not source documents.

Absence claims require a documented search across the appropriate version and
reasonable aliases. Failure to find a reference after a narrow lookup is
`insufficient`, not automatically `supported`.

When verifying architectural claims, connect related facts. For example, if a source says component X has a kube-rbac-proxy sidecar AND lists port 8443 as HTTPS, then "X uses kube-rbac-proxy on port 8443" is supported.

### Proposal-Derived Claims (CRITICAL)

Determine the claim's modality from its text and exact `original_text` before
choosing evidence. A source path is a clue, not proof that every assertion in
that file is about a proposal. Review artifacts often mix proposed behavior,
current-platform assertions, requirements, and reviewer analysis.

The following source patterns commonly contain discussion of proposals:
- `*-security-review.md` or `*-reviewer-*.md` (security review artifacts)
- `strat-security-reviews/` (security review pipeline directory)
- `strat-pipeline/` (strategy review pipeline directory)
- `*-review.md` in a `strat-reviews/` directory

For an assertion explicitly describing proposed or required behavior, the
verification question is: **"Does the source strategy text actually propose or
require what this claim says?"** — NOT "Does this exist in the current platform?"

- Look at the source documents for the original STRAT text
- If the STRAT text describes the feature/behavior the claim mentions → **supported**
- If the STRAT text does NOT describe it (the reviewer invented it) → **refuted**
- If architecture docs show the feature doesn't exist yet, that is EXPECTED and NOT grounds for refutation — the whole point of a strategy is to propose new things

Only use architecture docs to refute proposal-derived claims when the claim makes a specific assertion about the EXISTING platform that you can check (e.g., "this conflicts with the existing X" or "the platform currently has Y").

If a review artifact asserts current behavior, versions, dependencies, ports,
or security properties, verify that assertion against version-appropriate
architecture evidence even though it appeared in a proposal review.

### Verdict Schema

For each claim, produce:

```json
{
  "claim_occurrence_id": 123,
  "verifier_revision": "resolved commit or immutable implementation ID",
  "repository_revision": "resolved repository commit",
  "model": "resolved model identity",
  "harness": "dashboard-jobs-api",
  "configuration_digest": "sha256:...",
  "evidence_context_digest": "sha256:...",
  "verdict": "supported|contradicted|insufficient_evidence|not_applicable",
  "severity": "info|low|medium|high|critical",
  "confidence": 85,
  "evidence_summary": "One sentence explaining the verdict",
  "evidence": [{
    "evidence_type": "repository_file",
    "uri": "repo://architecture/component.md",
    "repository_revision": "abc123",
    "source_locator": "component.md:Architecture",
    "relationship": "supports|contradicts",
    "authority": "architecture-context",
    "product_version": "rhoai-3.4"
  }]
}
```

**Verdict definitions:**
- `supported` — the evidence clearly supports this claim. For proposal-derived claims: the source strategy text describes what the claim says.
- `contradicted` — the evidence contradicts this claim. For proposal-derived claims: the source strategy text does NOT describe what the claim says.
- `insufficient_evidence` — evidence is missing, ambiguous, or cannot distinguish support from contradiction
- `not_applicable` — the occurrence is not a factual-verification target after modality-aware review

Apply verdicts to the whole atomic claim, not only its easiest clause. Every
material, independently checkable element must have authoritative support for a
`supported` verdict. If any material element lacks evidence, use
`insufficient_evidence`; if authoritative evidence contradicts a material
element, use `contradicted`. Split a genuinely non-atomic occurrence upstream
rather than averaging evidence across its clauses.

Never promote plausibility to support. Phrases such as "plausible",
"reasonable", "well-known", "close to", "could not be independently
verified", or "the source document states it" identify an evidence gap when
the claim asserts current state, external product behavior, user behavior, or
a numeric fact. A generated artifact proves what it proposed or reported; it
does not prove that its current-state premise is true.

Legacy reports may render `contradicted` as `refuted` and split
`insufficient_evidence` into `insufficient`/`inconclusive`, but v2 JSON always
uses the canonical values above.

**Confidence:** use this as a ranking signal, not a probability:
- `90-100` — direct, authoritative evidence explicitly confirms or contradicts the claim
- `70-89` — multiple consistent evidence points require limited interpretation
- `40-69` — partial, indirect, or version-ambiguous evidence
- `0-39` — little usable evidence; normally pair with `insufficient` or `inconclusive`

Do not assign a root cause here. A contradiction establishes a verdict, not
whether the generator suffered a context gap, retrieval failure, reasoning
error, or another failure. Leave that attribution to `explain-claims`.

## Step 4: Write Verification Logs

For each verified claim, write a markdown log to:
```
{artifacts_dir}/verification/{claim_id}.md
```

Also write
`{artifacts_dir}/verification/{claim_occurrence_id}/{run_key}.verification.json`
as the authoritative machine-readable run, where `run_key` incorporates the
verifier revision and evidence-context digest. Include the claim occurrence ID, verifier
revision, evidence-context digest, verdict, severity, confidence triage rank,
and complete structured evidence records. Each execution creates a new run;
never replace a prior run merely because the normalized claim text matches.
The single `{claim_id}.md` report is a legacy projection and may show only the
effective run; it is not the history of record.
After successful v2 ingestion, atomically record the returned ID as
`observatory_run_id`; explanation must bind to this exact verification run.

Before ingestion, validate every machine-readable file created by this
execution (and only those files):

```bash
python3 "$SKILL_DIR/scripts/validate-verification.py" \
  "${current_verification_files[@]}"
```

Do not POST any run if validation fails. Repository and architecture evidence
must include the resolved evidence repository commit in
`repository_revision`, plus a stable source locator or exact query. Generated
artifact evidence must include its SHA-256 `artifact_digest` and stable source
locator. A URI or human-readable authority label is not immutable provenance by
itself.

Use `contradicted` for the v2 verdict corresponding to the legacy `refuted`
label. Severity describes the impact of a contradicted claim (`info`, `low`,
`medium`, `high`, or `critical`), not the evaluator's confidence.

Log format:
```markdown
# Claim {claim_id}

**Verdict:** {verdict}
**Confidence:** {confidence}%
**Type:** {claim_type}
**Source file:** `{source_file}`

## Claim

> {claim_text}

## Evidence Sources

### Files
- `{file_path}`

### Architecture Docs
- `{component}.md ({version})`

### Overlays
- `{overlay_file}` (if checked)

### Queries
- `{exact command or search}`

## Verdict

**{verdict}** (confidence: {confidence}%)

{evidence_summary}

### Evidence Quote

> {evidence_detail}
```

Create parent directories with `mkdir -p`.

## Step 5: Submit Verdicts to Observatory

POST each machine-readable run to the immutable v2 endpoint:

```bash
curl -s -X POST "${observatory_url}/api/v2/claims/verification-runs" \
  -H "Content-Type: application/json" \
  -d @"${verification_json_file}" \
  --max-time 30
```

The payload uses `claim_occurrence_id`, `verifier_revision`, resolved model,
harness and configuration identity, `evidence_context_digest`, v2 verdict,
severity, confidence, summary, and structured evidence. The endpoint returns
the immutable run ID. Only if the v2
endpoint returns `404` may a legacy/unassured run fall back to
`POST /api/claims/verdicts`; record that fallback in its disk artifact and do
not let it satisfy the structured-verification gate.

If the Observatory is unreachable or returns another error, log the error and
preserve the disk output for retry.

## Step 6: Report Results

After processing all claims, output a summary:

```
## Verification Summary

- **Claims verified:** 42
- **Supported:** 28 (67%)
- **Refuted:** 5 (12%)
- **Insufficient:** 6 (14%)
- **Inconclusive:** 3 (7%)
- **Average confidence:** 78%

### Observatory Submission
- **Verdicts stored:** 42
- **Skipped:** 0

### Refuted Claims (requires attention)
| ID | Claim | Confidence | Evidence |
|---|---|---|---|
| 456 | "Component X uses mTLS on port 8443" | 92% | Architecture doc shows port 8080, not 8443 |
```

Always highlight refuted claims in the summary — these represent potential hallucinations in the pipeline output.

$ARGUMENTS
