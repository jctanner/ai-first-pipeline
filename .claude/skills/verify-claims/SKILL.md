---
name: verify-claims
description: Verify extracted claims against source material and architecture context, submit verdicts to Observatory
allowed-tools: Read, Write, Glob, Grep, Bash
user-invocable: true
---

# Verify Claims

Verify previously extracted claims by evaluating them against source material and architecture documentation. Produces verdicts (supported/refuted/insufficient/inconclusive) with confidence scores, writes verification logs, and submits results to the Observatory.

## Inputs

This skill accepts inputs as positional arguments and/or kwargs in a `## Inputs` section appended to the prompt:

- **Issue key** (positional, e.g. `RHAISTRAT-1676`) — verify claims linked to this Jira key
- **claim_ids** (kwarg, e.g. `123,456,789`) — verify specific claim IDs
- **claim_types** (kwarg, e.g. `security,architectural`) — only verify claims of these types
- **`--force`** — re-verify claims that already have verdicts

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

Fetch pending claims for the issue:

```bash
curl -s "${observatory_url}/api/hallucinations/claims?jira_key=${ISSUE_KEY}&verdict=pending&limit=200"
```

This returns `{"claims": [...], "total": N}` where each claim has:
- `id` — claim ID (needed for submitting verdicts)
- `claim_text` — the claim to verify
- `claim_type` — factual/architectural/security/scope/attribution
- `sources` — list of `{pipeline_slug, source_file}` objects

If `claim_types` kwarg is provided, filter to only those types after fetching. If `--force`, fetch all claims (not just pending): omit the `verdict=pending` parameter.

### Disk fallback

If the Observatory is unreachable, read claims from `{artifacts_dir}/claims/**/*.claims.json` files matching the issue key. Note: disk-based claims don't have database IDs, so verdicts can only be written to log files, not submitted to the Observatory.

Report the number of claims found and their type distribution before proceeding.

## Step 2: Gather Evidence for Each Claim

For each claim, gather relevant source material based on the claim type and source file. Evidence comes from three categories:

### 2a. Source Documents

Find source/ground-truth files related to the claim's source artifact. Given the `source_file` field (e.g. `strat-pipeline/RHAISTRAT-1676.md`):

- Look for sibling files: `*-strat-text.md`, `*-threat-surface.md` in the same directory or parent
- Look for `strat-originals/` directory at the parent level — these are the original RFE texts
- Read these files as "Source" evidence (they describe what was PROPOSED, not current platform state)

### 2b. Architecture Context (for `architectural` and `security` claims)

Search the architecture-context checkout for relevant component documentation.

**Directory structure:**
```
{context_dir}/architecture-context/architecture/
├── rhoai-3.4/           # GA release docs
│   ├── component-name.md
│   └── PLATFORM.md
├── rhoai-3.5-ea.1/      # EA release docs
└── rhoai.next/           # Next release docs
```

**Component detection:** Extract component names from the claim text. Check these known aliases:
- ogx, ogx distribution, llama stack, llamastack → `llama-stack`
- ogx k8s operator, ogx operator → `llama-stack-k8s-operator`

**Version detection:** Look for RHOAI version patterns in the claim (e.g., "RHOAI 3.5", "rhoai-3.4"). Default to `rhoai-3.4` if no version detected.

**Steps:**
1. List available components: `ls {context_dir}/architecture-context/architecture/{version}/`
2. For each component mentioned in the claim, read the `.md` file
3. Use `grep -r` to search for technical terms from the claim (mTLS, FIPS, kube-rbac-proxy, NetworkPolicy, port numbers, etc.)
4. For platform-level claims (mentioning "ships", "container image", "component"), read `PLATFORM.md`

### 2c. NFR Checklist (for `security` claims)

If available, read the NFR checklist at:
```
{artifacts_dir}/../.claude/skills/strat-security-review/references/nfr-checklist.md
```
Or search for it:
```bash
find {base_dir} -path "*/strat-security-review/references/nfr-checklist.md" -type f 2>/dev/null | head -1
```

A security requirement that maps to a checklist item is valid (not hallucinated).

## Step 3: Evaluate Each Claim

For each claim, evaluate it against the gathered evidence. You ARE the verification judge.

### Verification Rules

**CRITICAL DISTINCTION:** Pay attention to the type of evidence:

1. **Source documents** (strat-text, strat-originals) describe what is being PROPOSED. They are NOT evidence of current platform state.
2. **Architecture context docs** represent what CURRENTLY EXISTS in the platform. These are authoritative for architectural claims.
3. **NFR checklist items** are ground truth for security requirements.

When a claim says something "does not exist" or "has no reference" in the platform, verify against architecture docs ONLY, not source documents.

When verifying architectural claims, connect related facts. For example, if a source says component X has a kube-rbac-proxy sidecar AND lists port 8443 as HTTPS, then "X uses kube-rbac-proxy on port 8443" is supported.

### Verdict Schema

For each claim, produce:

```json
{
  "claim_id": 123,
  "verdict": "supported|refuted|insufficient|inconclusive",
  "confidence": 85,
  "evidence_summary": "One sentence explaining the verdict",
  "evidence_source": "skill(verify-claims)",
  "evidence_detail": "Most relevant quote or reasoning"
}
```

**Verdict definitions:**
- `supported` — the evidence clearly supports this claim
- `refuted` — the evidence contradicts this claim
- `insufficient` — no relevant evidence found in available sources
- `inconclusive` — the evidence is ambiguous

**Confidence:** 0-100 integer reflecting how certain you are of the verdict.

## Step 4: Write Verification Logs

For each verified claim, write a markdown log to:
```
{artifacts_dir}/verification/{claim_id}.md
```

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

## Verdict

**{verdict}** (confidence: {confidence}%)

{evidence_summary}

### Evidence Quote

> {evidence_detail}
```

Create parent directories with `mkdir -p`.

## Step 5: Submit Verdicts to Observatory

POST all verdicts to the Observatory in a single batch:

```bash
curl -s -X POST "${observatory_url}/api/claims/verdicts" \
  -H "Content-Type: application/json" \
  -d '{"verdicts": [...]}' \
  --max-time 30
```

The endpoint returns `{"stored": N, "skipped": M}`.

If the Observatory is unreachable, log the error. The verification log files on disk are the primary output.

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
