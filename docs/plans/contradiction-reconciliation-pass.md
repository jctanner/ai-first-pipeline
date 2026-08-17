# Proposal: Contradiction Reconciliation Pass for Strategy Refinement/Review

JIRA: [RHAIFIRST-372](https://redhat.atlassian.net/browse/RHAIFIRST-372)

## Problem

Refined strategies reach `strat-creator-human-sign-off` while containing internal contradictions that the refinement process had all the inputs to catch. The current review pipeline scores along four dimensions (feasibility, testability, scope, architecture) but none of them systematically check whether the document contradicts itself or its own source inputs. When contradictions survive to sign-off, downstream decomposition silently picks one interpretation and builds epics on it — no flag is raised, and the wrong interpretation becomes the plan of record.

## How Contradictions Enter the Document

Strategies are assembled from multiple input sources with different authorship and timing:

1. **Business Need (from RFE)** — verbatim, never modified by the pipeline
2. **Removed Implementation Context** — technical details stripped by rfe-creator, injected back as HOW input
3. **Staff Engineer / SME Input** — human corrections, highest priority
4. **Architecture Context Overlays** — cross-strategy corrections
5. **Architecture Context** — generated platform docs
6. **AI-generated Strategy section** — the pipeline's output

The `strategy-refine` skill resolves conflicts between these inputs using a priority chain (SME > overlays > removed context > arch context), but this resolution is local: it may fix the Technical Approach section while leaving a conflicting statement standing in the RFE-inherited user flows, the acceptance criteria, or the deliverables list. The Business Need section is verbatim and immutable — so if the RFE says "DataRegistry CR" and the refined strategy settles on "FeatureStore CR," both statements coexist in the final document.

On revision runs, the problem compounds: `strategy-refine` only rewrites subsections addressed by feedback, leaving untouched subsections byte-for-byte identical. A contradiction introduced in the first pass that wasn't flagged by review persists through all subsequent revisions.

## Verified Examples

### Example A — Self-contradiction within the document (RHAISTRAT-2281)

Three incompatible mechanisms for registry provisioning via GitOps:

- **User Flow 1** (RFE-inherited): "Registry creation is also possible via GitOps (DataRegistry CR manifest)"
- **Provisioning Model** (AI technical approach): "No new CRD is introduced"
- **Same section**: "GitOps provisioning works through the existing FeatureStore CR manifest ... with no new DataRegistry CR needed"

The technical approach resolved the RFE's ambiguity (settling on FeatureStore CR) but the original RFE user-flow line naming a DataRegistry CR was never removed. Detectable from the document alone.

### Example B — Claim contradicts architecture context (RHAISTRAT-2281)

- Strategy asserts: "No new operators, pods, or CRDs are introduced. The Feast server gains /v1/* endpoints" — a single server-side search endpoint.
- Strategy also requires cross-registry discovery and search across multiple tenants.
- Architecture context: FeatureStore CRD is Namespaced; operator deploys a feature server per FeatureStore CR (one deployment per registry/namespace).
- Therefore: multiple registries = multiple per-namespace feature-server deployments, so single server-side `/v1/search` cannot span them without fan-out or a new shared pod — contradicting "no new pods."

Detectable from document + architecture context, both of which the pipeline already reads.

### Example C — RFE scope exclusion contradicts Staff Engineer Input (RHAISTRAT-1741)

marius danciu [reported in Slack](https://redhat-internal.slack.com/archives/C0APA0E2J3Z/p1778659137693789) that the scorer rejected the strategy (3/8) due to a fundamental conflict:

- **RFE** explicitly states: "Not control-plane-level isolation (HCP) — a separate RFE covers control-plane-level tenant isolation for government/FSI customers requiring stronger separation than namespace-level. This RFE is namespace-level isolation only."
- **Staff Engineer Input**: "pivot to HCP/single-gateway model"
- **Refined strategy**: followed the Staff Engineer Input (as designed by the priority chain) and described an HCP-based approach

The scorer caught the contradiction on this particular run, but the strategy had already passed through earlier rounds of refinement and review without it being surfaced. The conflict between the RFE's explicit scope exclusion and the Staff Engineer's direction was never formally reconciled — marius asked: "In situations where there are different opinions, how are these captured in the refinement process?"

This example is especially important because the priority chain (SME > arch context > RFE removed context) is working as designed — but when SME input directly contradicts the RFE's scope, the conflict should be surfaced rather than silently resolved by priority.

### Example D — KFP SDK version contradictions (RHAISTRAT-1848)

The KALE integration strategy contained KFP SDK version contradictions that the feasibility reviewer flagged. The strategy referenced one KFP SDK version in one section while assuming a different version elsewhere, leading to a 1/2 feasibility score.

### Example E — RFE vs SME conflict caught by Claude's judgment, not by design (RHAISTRAT-1556)

Jason Greene [analyzed](https://redhat-internal.slack.com/archives/C0APA0E2J3Z/p1785443440424409) a case where:

- **RFE acceptance criterion**: data scientists "cannot receive deployment recommendations"
- **SME Input**: classifies `recommend_model` as a compute operation (needs only get/list), meaning data scientists CAN receive recommendations but can't act on them

Claude correctly refused to silently resolve the conflict and parked it in Open Questions for PM confirmation. This is an example where the system produced the right outcome — but only because of Claude's ad-hoc judgment, not because a systematic consistency check exists. A consistency reviewer would catch this class of conflict reliably instead of depending on the model noticing it.

## Why Current Reviewers Don't Catch This

The four existing reviewer skills each run in an isolated fork (`context: fork`) and assess along a single dimension:

| Reviewer | What it checks | Why it misses contradictions |
|----------|---------------|------------------------------|
| `strategy-feasibility-review` | Can we build this? Is the effort credible? | Evaluates the approach as stated, not whether it's internally consistent |
| `strategy-testability-review` | Are ACs testable? Edge cases covered? | Checks AC format and coverage, not whether ACs conflict with the technical approach |
| `strategy-scope-review` | Right-sized? Effort matches scope? | Measures size, not self-consistency |
| `strategy-architecture-review` | Dependencies correct? Integration patterns valid? | Closest to catching Example B, but its prompt doesn't instruct it to compare claims across sections or flag when one section's mechanism contradicts another's |

The architecture reviewer could theoretically catch Example B, but its prompt focuses on "are integration patterns correct" and "are dependencies identified" — not "does the document's claim about deployment topology contradict what the architecture context says about how this CRD is actually deployed." The distinction is subtle but real: it checks whether the approach is architecturally sound in isolation, not whether the document makes conflicting claims about the same mechanism.

None of the reviewers compare the Business Need section against the Strategy section. By design, the Business Need is read-only input — but that means contradictions between what the RFE promises and what the strategy proposes are never surfaced.

## Where a Fix Should Go

Two options, not mutually exclusive:

### Option 1: New reviewer skill (strategy-consistency-review)

Add a fifth reviewer alongside the existing four, invoked in Step 6 of `strategy-review`. It runs in its own fork with access to the strategy file and architecture context, and specifically checks:

1. **Cross-section consistency** — does any claim in the Technical Approach, Affected Components, or Acceptance Criteria contradict the Business Need section? (Example A pattern)
2. **Intra-section consistency** — does the document state two things about the same mechanism/topology/API that cannot both be true? (Also Example A)
3. **Context reconciliation** — does any deployment/topology/mechanism claim contradict what the architecture context says about the referenced component's actual scope? (Example B pattern)

This option is additive — no changes to existing skills. The consistency reviewer's output would be written to the review file alongside the other four, and its findings would inform the human sign-off decision.

Eder's comment on the ticket ("This will probably be a new reviewer type") suggests this is the intended direction.

### Option 2: Pre-sign-off reconciliation pass in strategy-refine

Add a final step to `strategy-refine` that, after generating/revising the Strategy section, performs a self-consistency scan and edits contradictions before the document leaves refinement. This catches problems earlier but makes the refine step longer and more expensive.

### Recommendation

Start with Option 1. A new reviewer is lower risk (purely additive, no changes to refine logic), aligns with Eder's comment, and surfaces contradictions at the right moment — before human sign-off, where a human can make the call on which interpretation is correct. Option 2 could be added later if the volume of contradictions makes it worthwhile to catch them earlier.

## Scoring Integration

The existing rubric scores four dimensions at 0/1/2 each, for a total of 8. Adding a fifth dimension would change the scoring math (total out of 10, new verdict thresholds). Two paths:

1. **Separate finding, no score change**: The consistency reviewer produces findings appended to the review file but doesn't affect the numeric score or verdict. Contradictions are surfaced for the human reviewer but don't gate the pipeline. Simpler to implement.
2. **New scored dimension**: Add a "Consistency" score to the rubric, adjust verdict thresholds. More impactful but requires changes to `assess-strat`, `parse_results.py`, `apply_scores.py`, and the Jira comment format.

Start with option 1 to validate the reviewer before integrating it into scoring.

## Open Questions

- Should the consistency reviewer also check for contradictions between the strategy and its linked RFE comments (removed implementation context)?
- How should contradictions involving the immutable Business Need section be reported? The pipeline can't edit it — the finding would need to either flag it for human resolution or note it as an accepted divergence.
- Should contradictions found during review trigger an automatic re-refine, or only surface as findings for human review?
