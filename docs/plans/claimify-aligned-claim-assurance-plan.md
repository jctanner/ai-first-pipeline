# Plan: Claimify-Aligned Claim Assurance and Improvement Loop

## Goal

Evolve Observatory's claim pipeline from a single-pass
"extract, then fact-check" workflow into a measurable claim-assurance system
inspired by *Towards Effective Extraction and Evaluation of Factual Claims*.

The system must answer four separate questions:

1. **Extraction entailment:** Does the source artifact support the extracted
   claim?
2. **Coverage:** Did extraction retain the source's verifiable information and
   exclude unverifiable material?
3. **Decontextualization:** Does the claim contain enough context to retrieve
   and interpret evidence without changing its meaning?
4. **Factual verification:** What does version-appropriate authoritative
   evidence say about the claim?

For problematic claims, the final stage attributes the most likely failure to
the skill, context, retrieval, workflow, tooling, model, policy, or human-owned
source and creates a replayable regression case.

## Current State

The current pipeline has three agent skills:

```text
extract-claims -> verify-claims -> explain-claims
```

Recent improvements establish useful boundaries:

- extraction preserves modality, negation, version, and exact source text;
- verification no longer assigns forensic root cause;
- explanation routes findings to an improvement target;
- per-issue receipts can skip unchanged extraction work;
- the end-to-end workflow covers the RFE and recursively discovered children.

At the time this plan was written, the architectural gaps were:

- extraction performs selection, disambiguation, decomposition, and output in
  one model pass;
- no deterministic source-unit segmentation or context-window contract exists;
- extraction entailment and element-level coverage are not evaluated;
- ambiguity cannot be represented as a first-class abstention;
- normalized claim text, source occurrence, and mutable verdict are conflated;
- one global verdict cannot represent different versions or evidence contexts;
- receipts do not yet include resolved skill/model/configuration revisions.

## Implementation Status

As of 2026-07-14, phases 0 through 8 are implemented, committed, and deployed.
The implementation includes the annotated regression corpus,
deterministic segmentation, staged extraction schemas and validation,
extraction-quality scoring, additive Observatory persistence and v2 APIs,
immutable verification and explanation histories, stage-aware receipts,
Markov gates and audited overrides, and the Observatory claim-assurance UI.

Acceptance evidence currently includes:

- 55 passing segmentation, stage-contract, scoring, and workflow-receipt tests;
- 14 passing focused Observatory claim-assurance and admin API tests;
- clean backend lint, valid Markov workflow definitions, and a successful
  Observatory production frontend build;
- deployed no-op receipt hits that skipped extraction, verification, and
  explanation agent jobs;
- skill-revision and context-revision invalidation that reran only the affected
  stages and their descendants;
- a completed context-change run with a provenance-bound, audited human
  override and dependent explanation replay; and
- a completed 54-unit regression job whose deterministic checks reported 100%
  decontextualization-contract compliance and 47 of 54 expected staged outputs.

Final acceptance remains open for two concrete reasons. The regression job
exceeded Markov's three-hour wait deadline, so the workflow was marked failed
before the Kubernetes job completed successfully. Its two model judges also
received neither the generated artifacts nor annotations and therefore emitted
the same non-evidentiary score for every case. Seven cases did not produce the
expected `.extraction.json` output and require investigation. In addition, the
source-artifact invalidation test and final import/sync of the latest
`ai-first-pipeline@main` revision remain outstanding.

## Active Ledger Items

- [Repair claim-assurance regression evaluation](../tasks/pending/repair-claim-assurance-regression-evaluation.md)
- [Complete claim-assurance deployment acceptance](../tasks/pending/complete-claim-assurance-deployment-acceptance.md)

## Design Principles

### Preserve stage boundaries

```text
document segmentation
    -> verifiable-content selection
    -> ambiguity detection/resolution
    -> claim decomposition
    -> extraction-quality evaluation
    -> external factual verification
    -> forensic explanation
    -> improvement + regression replay
```

Each stage writes structured output and may abstain. A later stage must not hide
or silently repair an earlier-stage failure.

### Treat atomicity as an operational constraint

Claims should be independently verifiable, but decomposition should stop when
further splitting no longer improves verification. The primary extraction
quality measures are entailment, coverage, and decontextualization—not maximum
syntactic atomicity.

### Separate normalized claims from occurrences

Identical claim text may appear in different products, versions, artifacts, or
times. Deduplication may create a reusable normalized identity, but every source
occurrence and every verification run remains distinct and immutable.

### Prefer deterministic mechanics

Use code for segmentation, hashing, schema validation, persistence, pagination,
and receipt handling. Use model judgment for selection, ambiguity,
decomposition, entailment, and evidence interpretation.

## Target Data Model

The exact names may change during Observatory implementation, but the model must
represent these concepts:

```text
extraction_run
  id, artifact_digest, extractor_revision, model, configuration_digest,
  started_at, completed_at, status

source_unit
  id, extraction_run_id, source_file, source_locator, original_text,
  heading_path, preceding_context, following_context

selection_result
  source_unit_id, classification, selected_text, rationale
  classification = verifiable | mixed | unverifiable

ambiguity_result
  source_unit_id, status, ambiguity_types, clarified_text, resolution_context
  status = none | resolved | unresolved

normalized_claim
  id, normalized_text, content_hash

claim_occurrence
  id, normalized_claim_id, source_unit_id, claim_text, original_text,
  claim_type, modality, product_version, temporal_scope

extraction_evaluation
  claim_occurrence_id, entailed, coverage_result,
  decontextualization_result, evaluator_revision, evidence

verification_run
  id, claim_occurrence_id, evidence_context_digest, verifier_revision,
  verdict, confidence, evidence_records, created_at

explanation_run
  id, verification_run_id, category, improvement_target,
  explanation, contributing_factors, regression_test, evidence_records
```

Existing `claims`, `claim_sources`, `claim_verdicts`, and
`claim_explanations` APIs remain readable during migration.

## Implementation Phases

### Phase 0: Establish a regression corpus

Before changing extraction behavior:

1. Select representative RFE, strategy, security-review, Epic, investigation,
   and code-generation artifacts.
2. Include mixed factual/subjective sentences, bullet lists, pronouns,
   cross-version assertions, proposals, requirements, negation, and intentionally
   ambiguous passages.
3. Annotate source units with:
   - verifiable and unverifiable elements;
   - expected ambiguity status;
   - acceptable claim formulations;
   - required contextual qualifiers.
4. Preserve known extraction and verification failures as regression cases.
5. Version the corpus and annotation rubric in the local `eval-datasets`
   repository.

**Exit criteria:** at least 50 source units across every artifact class, with a
reviewed annotation rubric and deterministic dataset FQN.

### Phase 1: Add deterministic document segmentation

Create a reusable script under `extract-claims/scripts/` that:

- parses Markdown headings, paragraphs, sentences, and list items;
- preserves heading hierarchy and stable source locators;
- supplies configurable preceding and following context;
- keeps list preambles with list items;
- emits stable JSON source-unit records;
- produces identical identifiers for identical artifact content and config.

Configuration includes segmentation version, preceding/following window sizes,
and artifact-type overrides.

**Exit criteria:** fixture tests cover headings, nested lists, tables, code
blocks, abbreviations, and deterministic reruns.

### Phase 2: Split extraction into three model stages

Refactor `extract-claims` to process source units through explicit schemas.

#### Selection

Classify each unit as `verifiable`, `mixed`, or `unverifiable`. For `mixed`,
retain only the verifiable elements without inventing information.

#### Disambiguation

Detect at least:

- referential ambiguity;
- structural ambiguity;
- temporal ambiguity;
- component/version ambiguity;
- proposal-versus-current-state ambiguity.

Resolve ambiguity only from the supplied source context. Emit `unresolved` and
no claims when reasonable readers could not agree on an interpretation.

#### Decomposition

Produce independently verifiable declarative claims. Preserve qualifiers and
mark any clarification added from context separately from exact source text.

Use structured JSON schemas and validate every stage before continuing.

**Exit criteria:** every source unit has a durable stage result, including
unverifiable and unresolved units; no free-form output is silently accepted.

### Phase 3: Evaluate extraction quality

Add an evaluation pass before factual verification.

#### Entailment

Determine whether the source unit plus its supplied context entails each claim.
A true claim that is not supported by its source is still an extraction error.

#### Element-level coverage

Extract verifiable and unverifiable elements from each source unit and classify
each as explicitly covered, implicitly covered, or omitted. Calculate precision,
recall, and macro F1 for verifiable versus unverifiable elements.

#### Decontextualization

Generate a maximally contextualized comparison claim and test whether adding
the omitted context changes retrieved evidence or the evidence-to-claim
relationship. Initially run this on the regression corpus and sampled
production claims because it requires multiple retrieval and judge calls.

**Exit criteria:** every accepted claim passes source entailment; coverage is
reported per artifact and extraction run; unresolved ambiguity and omitted
verifiable elements remain visible in Observatory.

### Phase 4: Migrate Observatory persistence and APIs

Implement additive database migrations in the Observatory repository:

1. Add extraction runs, source units, occurrences, stage results, evaluation
   results, versioned verification runs, and explanation runs.
2. Backfill each legacy claim/source pair as a claim occurrence.
3. Preserve legacy endpoints while adding `/api/v2/claims/...` endpoints.
4. Store structured evidence records with immutable paths, repository commits,
   artifact digests, source locators, queries, excerpts, authority, and version.
5. Never overwrite historical verification or explanation runs.
6. Define an explicit policy for selecting the current/effective verdict.

**Exit criteria:** legacy Observatory pages remain functional, new runs retain
full occurrence and provenance data, and migrations are reversible from backup.

### Phase 5: Separate extraction assurance from factual verification

Update `verify-claims` so it accepts only occurrences that passed extraction
entailment. Verification selects evidence based on claim modality:

- proposals and requirements: verify faithful representation of the source;
- current-state architectural claims: verify versioned architecture evidence;
- historical or temporal claims: require time-appropriate evidence;
- absence claims: require documented searches across aliases and versions.

Store each verification as a new run bound to an evidence-context digest and
verifier revision. Treat confidence as a triage ranking, not a calibrated
probability.

**Exit criteria:** changing evidence, architecture version, or verifier revision
creates a new verification run rather than replacing history.

### Phase 6: Make explanation the improvement router

Update `explain-claims` and Observatory to emit:

- primary cause category;
- improvement target;
- contributing factors;
- evidence for and against the attribution;
- material alternative explanations;
- concrete remediation;
- regression test definition.

Initial categories:

```text
skill_instruction_gap
context_gap
retrieval_failure
source_misinterpretation
workflow_gap
tool_or_harness_gap
model_reasoning_error
human_source_quality
compound_error
unknown
```

Do not infer causal mechanisms from token counts or span counts alone.

**Exit criteria:** each non-supported claim either has an evidence-backed
improvement route or is explicitly `unknown`/human-review-required.

### Phase 7: Expand receipts into stage-aware provenance

Extend extraction receipts to include:

- resolved skill commit rather than only the configured FQN;
- model and harness identity;
- segmentation and context-window configuration digest;
- input artifact and source-unit digests;
- selection, ambiguity, and claim counts;
- extraction-evaluator revision;
- output and Observatory run identifiers.

Add equivalent receipts for verification and explanation. A receipt is reusable
only when stage, scope, resolved implementation, inputs, evidence context, and
configuration match.

**Exit criteria:** unchanged workflow reruns launch no unnecessary agent jobs;
changing any dependency invalidates only the affected stage and descendants.

### Phase 8: Integrate workflows, gates, and UI

Update the end-to-end Markov workflows to expose stage results and apply gates:

- block factual verification when extraction entailment fails;
- route unresolved ambiguity and low coverage to review;
- prevent progression on high-severity refuted claims;
- pause on cross-verifier disagreement;
- allow explicit human override with an audit record;
- launch targeted regression evaluations after skill/context changes.

Update Observatory UI to show:

- source text and context window;
- selection and ambiguity outcomes;
- extracted occurrence versus normalized claim;
- extraction entailment and coverage;
- versioned verification history and evidence;
- explanation, improvement target, and regression status.

**Exit criteria:** an operator can trace a finding from generated artifact to
source unit, extraction decision, evidence, verdict, root-cause hypothesis,
improvement, and replay result.

## Evaluation Metrics

Track metrics by artifact type, skill revision, model, and extraction config:

- source-entailment rate;
- verifiable-element precision, recall, and macro F1;
- explicit unverifiable-element inclusion rate;
- unresolved ambiguity rate;
- desirable decontextualization outcome rate;
- factual-verification verdict distribution;
- cross-verifier agreement;
- human-review and override rate;
- recurrence rate by root-cause category;
- regression pass rate after remediation;
- tokens, cost, duration, and agent jobs avoided by receipts.

Do not optimize supported-claim rate alone; a system can inflate it by omitting
difficult claims.

## Rollout and Compatibility

1. Introduce the new schema and APIs additively.
2. Run legacy and staged extraction side-by-side on the regression corpus.
3. Shadow the staged pipeline on selected demo runs without gating progression.
4. Compare entailment, coverage, decontextualization, cost, and latency.
5. Enable extraction-entailment gating first.
6. Add coverage and ambiguity review gates after thresholds are calibrated.
7. Retire legacy mutable verdict writes only after UI and workflow consumers
   use versioned verification runs.

## Files and Repositories in Scope

### ai-first-pipeline

- `.claude/skills/extract-claims/`
- `.claude/skills/verify-claims/`
- `.claude/skills/explain-claims/`
- `var/demos/end-to-end/workflows/run-claims.yaml`
- `var/demos/end-to-end/workflows/run-claim-extraction.yaml`
- `var/demos/end-to-end/` receipt and evaluation helpers
- claim-oriented agent-eval-harness datasets

### Observatory component repository

- database migrations and claim CRUD
- claim ingestion, verdict, and explanation APIs
- extraction/evaluation workers or scripts
- claim assurance and provenance UI
- migration and API compatibility tests

### Markov / markovd, if required

- quality-gate inputs and human-review pauses
- stage receipt visibility
- workflow graph summaries for assurance outcomes

## Verification Strategy

1. Unit-test segmentation, stable locators, hashing, validation, and receipt
   invalidation.
2. Contract-test every structured model stage with valid, invalid, empty, and
   abstained outputs.
3. Run the annotated regression corpus through each extractor revision.
4. Test proposal/current-state and cross-version claim pairs explicitly.
5. Test occurrence separation for identical text in different source contexts.
6. Test versioned verification without overwriting history.
7. Run the complete RFE-to-code-to-claims demo twice and confirm the second run
   is a receipt hit.
8. Change one source artifact, one context revision, and one skill revision; in
   each case verify that only the dependent stages rerun.
9. Exercise human-review and override paths with complete audit provenance.

## Completion Criteria

The plan is complete when:

- extraction quality is measured separately from factual correctness;
- every claim is traceable to a stable source occurrence and context window;
- ambiguity can produce a durable abstention;
- coverage omissions are measurable;
- verification and explanation history is immutable and versioned;
- findings route to explicit improvement targets and regression cases;
- Markov can gate or loop based on assurance results;
- identical unchanged runs are idempotent through stage-aware receipts;
- the end-to-end demo shows a complete improvement-and-replay cycle.
