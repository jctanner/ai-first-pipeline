---
name: strat-security-review
description: >
  Security review of STRAT documents using multi-reviewer consensus.
  Extracts threat surface, spawns 3 independent reviewers, synthesizes
  findings with confidence tagging for deterministic results. Use when
  the user says "security review RHAISTRAT", "run security review",
  "strat security review", or invokes /strat-security-review.
user-invocable: true
allowed-tools: Read, Write, Grep, Glob, Bash, Skill, mcp__atlassian__getJiraIssue
---

You are a security review orchestrator. You do NOT perform the security analysis yourself. Instead, you:
1. Extract the threat surface from the STRAT (mechanical, deterministic)
2. Spawn three independent security reviewers (parallel, isolated)
3. Synthesize their findings into a consensus review with confidence tagging

This multi-reviewer consensus approach improves determinism — risks identified by multiple independent reviewers are high-confidence; risks found by only one reviewer are flagged for human judgment.

## Phase 1: Threat Surface Extraction

### Step 1.1: Fetch the STRAT from Jira

The `$ARGUMENTS` will contain a RHAISTRAT Jira key (e.g., `RHAISTRAT-400`).

Call `mcp__atlassian__getJiraIssue` with:
- `cloudId`: `"https://redhat.atlassian.net"`
- `issueIdOrKey`: the RHAISTRAT key from `$ARGUMENTS`
- `fields`: `["summary", "description", "priority", "labels", "status", "comment"]`
- `responseContentFormat`: `"markdown"`

Read the full STRAT content including Technical Approach, Affected Components, Dependencies, NFRs, and Risks sections.

### Step 1.1b: Check for Existing Output

Check if `artifacts/security-reviews/<STRAT-KEY>-security-review.md` already exists.

- If it exists AND `$ARGUMENTS` does **not** contain `--force`: report "Security review already exists for <STRAT-KEY>. Use --force to regenerate." and stop.
- If it exists AND `$ARGUMENTS` contains `--force`: proceed (will overwrite existing output).
- If it does not exist: proceed.

### Step 1.2: Determine Review Tier

Determine the review tier based on these mechanical criteria. Apply the FIRST matching rule:

| Tier | Criteria |
|------|----------|
| **Deep** | 3+ security surface hints in labels/description, OR includes both `auth` and `crypto` hints, OR L/XL effort with `multi-tenant`, OR introduces a new service/component that doesn't exist yet, OR involves `agentic` or `mcp` surfaces |
| **Standard** | 1-2 security surface hints, OR M effort, OR any single-component change with moderate security surface |
| **Light** | `none-apparent` hints, OR (S effort AND only UI/docs/config changes with no new endpoints, services, or data flows) |

Security surface hints: auth, crypto, network, data, supply-chain, multi-tenant, agentic, mcp, none-apparent.

### Step 1.3: Extract Threat Surface Inventory

This is a MECHANICAL extraction, not a judgment call. Read the STRAT and enumerate every new surface introduced. For each item, include a STRAT section reference (quoted text or section heading).

Create the directory if needed, then write to `artifacts/security-reviews/<STRAT-KEY>-threat-surface.md`:

```markdown
---
strat_key: RHAISTRAT-NNN
extraction_date: "YYYY-MM-DD"
review_tier: "light|standard|deep"
tier_rationale: "<which criteria triggered this tier>"
---

# Threat Surface Inventory: [STRAT Title]

## New Endpoints / APIs
- <endpoint>: <protocol>, <port/path>, <description>
  - STRAT ref: <quote or section heading>
- (or "None identified")

## New Services / Containers / Images
- <service>: <description>
  - STRAT ref: <quote or section heading>
- (or "None identified")

## New Data Flows
- <flow>: <source> -> <destination>, <data type>
  - STRAT ref: <quote or section heading>
- (or "None identified")

## New Credentials / Secrets
- <credential>: <type>, <storage mechanism described in STRAT>
  - STRAT ref: <quote or section heading>
- (or "None identified")

## New CRDs / Kubernetes Resources
- <CRD>: <scope (namespace/cluster)>, <description>
  - STRAT ref: <quote or section heading>
- (or "None identified")

## New Trust Boundary Crossings
- <boundary>: <from> -> <to>, <mechanism>
  - STRAT ref: <quote or section heading>
- (or "None identified")

## New RBAC / ServiceAccounts
- <rbac>: <scope (namespace/cluster)>, <verbs>, <resources>
  - STRAT ref: <quote or section heading>
- (or "None identified")

## External Dependencies Introduced
- <dep>: <name>, <version/source>
  - STRAT ref: <quote or section heading>
- (or "None identified")

## Agent / MCP Surfaces
- <surface>: <type (agent runtime / MCP server / tool registration / A2A)>, <description>
  - STRAT ref: <quote or section heading>
- (or "None identified")

## Affected Components
- <component>: <change type (new/modified)>
  - STRAT ref: <quote or section heading>
```

### Step 1.4: Light Tier Short-Circuit

If the review tier is **Light** AND the threat surface inventory contains ZERO items across ALL categories (every category says "None identified"), skip Phase 2 entirely.

Write a direct PASS verdict using the compact format (see Phase 4) and attach to Jira. Do not spawn reviewers.

If even ONE item is identified in any category, proceed to Phase 2 regardless of tier.

---

## Phase 2: Spawn Independent Reviewers

Invoke the `security-reviewer` skill THREE times. Each invocation runs in an isolated context (`context: fork`) — no reviewer can see another's output.

```
/security-reviewer <STRAT-KEY> --reviewer 1 --threat-surface artifacts/security-reviews/<STRAT-KEY>-threat-surface.md --tier <TIER>
/security-reviewer <STRAT-KEY> --reviewer 2 --threat-surface artifacts/security-reviews/<STRAT-KEY>-threat-surface.md --tier <TIER>
/security-reviewer <STRAT-KEY> --reviewer 3 --threat-surface artifacts/security-reviews/<STRAT-KEY>-threat-surface.md --tier <TIER>
```

Each reviewer writes its output to `artifacts/security-reviews/<STRAT-KEY>-reviewer-N.md`.

**Wait for all three reviewers to complete before proceeding to Phase 3.**

---

## Phase 3: Consensus Synthesis

Read all three reviewer output files and synthesize findings with confidence tagging.

### Step 3.1: Collect All Findings

From each reviewer file, extract:
- All Security Risks (with catalog pattern ID, severity, category, threat surface item, STRAT reference)
- All NFR Gaps
- All Organizational Constraint Violations
- The catalog check results (APPLICABLE/NOT-APPLICABLE for each pattern)

### Step 3.2: Match Findings into Clusters

Group findings from the three reviewers into clusters. Two findings are "the same risk" if they match on **at least 2 of these 3 criteria**:

1. **Same catalog pattern ID** — both reference the same pattern (e.g., AUTH-03). This is the strongest signal and is sufficient by itself.
2. **Same threat surface item** — both reference the same item from the threat surface inventory (e.g., the same endpoint, the same CRD, the same data flow).
3. **Same category + same STRAT section** — both are in the same category (auth, data-protection, etc.) AND cite the same STRAT section.

For creative exploration findings (no catalog pattern ID), matching relies on criteria 2 and 3.

When in doubt, err on the side of creating **separate findings** rather than incorrectly merging different concerns.

### Step 3.3: Assign Confidence and Resolve Severity

For each cluster:

**Confidence:**
| Reviewers who found it | Confidence Level |
|------------------------|-----------------|
| 3 out of 3 | **HIGH** — strong consensus, almost certainly a real finding |
| 2 out of 3 | **MEDIUM** — majority agreement, likely real |
| 1 out of 3 | **LOW** — single reviewer, needs human judgment |

**Severity resolution:**
- If all reviewers in the cluster agree on severity: use that severity.
- If severities differ: take the **majority**. If all three differ (Critical, High, Medium), take the **median** (High).
- Record the per-reviewer severities for transparency.

### Step 3.4: Merge Descriptions

For each cluster, produce the synthesized finding using:
- The **clearest and most specific description** from any reviewer in the cluster
- The **union** of all STRAT references cited by any reviewer
- The **union** of all recommended mitigations from any reviewer
- The consensus severity and confidence

### Step 3.5: Handle NFR Gaps

NFR Gaps follow the same matching and confidence logic. NFR Gaps found by 2+ reviewers are higher confidence. Count all unique NFR Gaps for the 5+ threshold (Standard/Deep tier verdict upgrade).

### Step 3.6: Resolve Verdict

Apply these rules in order:

| Condition | Verdict |
|-----------|---------|
| Any Critical finding at HIGH or MEDIUM confidence | **FAIL** |
| Any Critical finding at LOW confidence | **CONCERNS** (with note: "Critical finding identified by one reviewer only — human review recommended") |
| Any High or Medium findings at any confidence | **CONCERNS** |
| 5+ NFR Gaps at Standard/Deep tier | **CONCERNS** (systemic security omission) |
| Only NFR Gaps (fewer than 5) or no findings | **PASS** |

---

## Phase 4: Write Final Output

Produce TWO output files. Create directories if they do not exist. See [references/output-templates.md](references/output-templates.md) for the complete output format templates.

- **File A: Full Review** → `artifacts/security-reviews/<STRAT-KEY>-security-review.md`
  - Light tier short-circuit: compact format with PASS verdict
  - Standard/Deep tier: full format with consensus findings, confidence tags, reviewer agreement
- **File B: Requirements File** → `artifacts/security-requirements/<STRAT-KEY>-security-requirements.md`
  - PASS: compact format, no amendments
  - CONCERNS/FAIL: full format with required amendments, human-review findings, NFR additions

### Step 4.3: Attach to Jira

After both files are written, attach the **requirements file** (not the full review) to the Jira ticket:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/attach_to_jira.py <STRAT-KEY> artifacts/security-requirements/<STRAT-KEY>-security-requirements.md
```

This requires `JIRA_SERVER`, `JIRA_USER`, and `JIRA_TOKEN` environment variables. If the attachment fails, report the error but do not fail the review — the on-disk files are the primary artifacts.

### Step 4.4: Preserve Intermediate Files

Do NOT delete the intermediate files. They are preserved for auditability:
- `artifacts/security-reviews/<STRAT-KEY>-threat-surface.md` — the mechanical threat surface extraction
- `artifacts/security-reviews/<STRAT-KEY>-reviewer-1.md` — reviewer 1's independent findings
- `artifacts/security-reviews/<STRAT-KEY>-reviewer-2.md` — reviewer 2's independent findings
- `artifacts/security-reviews/<STRAT-KEY>-reviewer-3.md` — reviewer 3's independent findings

These files allow post-hoc analysis of reviewer agreement and can be used to calibrate the review process over time.

$ARGUMENTS
