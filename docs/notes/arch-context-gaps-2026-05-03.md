# Architecture-Context: Complete Problem Analysis from Slack

**Date:** 2026-05-03
**Source:** Comprehensive Slack search across all channels for mentions of `architecture-context`, `arch-context`, `arch context`, and `opendatahub-io/architecture-context`.
**Repo:** https://github.com/opendatahub-io/architecture-context

---

## 1. Missing Components — Products/Tools Not Recognized

### Docling + Kagenti not recognized

**Channel:** `#wg-redhat-ai-rfe-review` (12-message thread starting 2026-04-14)

@Ann Marie reported RHAIRFE-1521 falsely flagged Docling and Kagenti as not existing in the product. She asked "How do the bots know what's available in the product and what isn't?" and answered her own question: "Is it because it's relying on something in the architecture repo?"

She noted the rule of thumb is to update arch context between dev preview and tech preview, which is why Kagenti isn't listed. Docling isn't listed "because it's not a component per se; it's more like a set of libraries."

She went ahead and approved the RFE anyway, and recommended expanding context to include (1) Dev-Preview projects like Kagenti and (2) loosely integrated projects like Docling.

@abiazett later replied she had the same problem with **codeflare-sdk** — opened [issue #1](https://github.com/opendatahub-io/architecture-context/issues/1), which led to the overlays concept and [PR #5](https://github.com/opendatahub-io/architecture-context/pull/5).

### vllm variants for RHAI missing

**Channel:** `#wg-rhai-rfe-builder` (44-message thread starting 2026-04-24)

@Tom Gundersen raised that arch-context only covers RHOAI, not all of RHAI. "It has vllm-cpu/vllm-gaudi, but seems to be missing all the variants maintained by @Taneem @Tyler Michael Smith... also not sure if this is the right place to cover base images, python indexes..."

@astefanu confirmed it's RHOAI-only and noted "the agent scripts/skills may be quite different for RHAI and components of different types like images and python packages."

### odh-gitops not a source

**Channel:** `#team-ai-core-platform-forge`

@lburgazzoli wants odh-gitops included as a source for architecture-context.

### MaaS context missing new CRD

**Channel:** `#wg-openshift-ai-architecture-diagrams` (v2.0 thread, 22 messages)

@Lindani LD Phiri noted the MaaS context for 3.4 is missing a new CRD and an additional dependency repo. jtanner confirmed 3.4 hasn't been regenerated since early in the lifecycle and that rhoai.next has the correct data. This raised the question: **how do we update versioned releases?**

### Still-open gaps from v2.0 gap analysis

From jtanner's own gap analysis posted in `#wg-openshift-ai-architecture-diagrams`:

- AutoRAG/AutoML backends — still investigating
- Docling, MCP Gateway, ITS/its-hub, CLEAR, LLM Compressor — need to determine which repos these live in and whether they're shipped
- Cross-product scope (RHELAI, RHAIIS) — architecture-context still covers RHOAI only
- GPU/accelerator details — hardware-specific details (multi-GPU topology, RDMA, FIPS cipher suites per accelerator) depend on what the agent finds in the source code

### LlamaStack (LLS) not mentioned

**Channel:** `#team-dashboard-crimson`

@Nick Gagan noted there's no mention of LLS in architectural context and that it "probably needs to be updated."

### llamastack->ogx rename needed

**Channel:** `#wg-rhai-first-combined-tiger`

jtanner flagged: "I'm guessing we're going to need an architecture-context overlay very soon for the llamastack->ogx rename."

---

## 2. Stale Data / Update Cadence

### EvalHub code far ahead of arch-context

**Channel:** `#wg-rhai-strat-refine-review`

@mmortari: "The EvalHub code is already far ahead in terms of status, and seemed like the suggested Strat based on Arch context that lagged somehow." They worked around it by "pointing the strat pipeline in the 'input' to specific tags."

Asked: "how often is the Arch Context updated?" — no clear answer was given.

### KFP SDK version out of date

**Channel:** `#wg-rhai-strat-refine-review` (31-message thread)

@Eder Ignatowicz shared a concrete example: the pipeline referenced KFP SDK 2.15 throughout strategies, but it had already been bumped to 2.16 in a merged PR. "The architecture docs hadn't been regenerated yet, so the pipeline didn't know." Fixed via an overlay.

### 3.4 not regenerated

**Channel:** `#wg-openshift-ai-architecture-diagrams` (v2.0 thread)

jtanner said: "3.4 hasn't been regenerated since early in the lifecycle" and "we need to collectively figure out how to update them and on what cadence." Currently no automated refresh jobs exist. @Jessica suggested "once a week we would want to refresh the current pre-release — the state of main basically."

### Repos point at red-hat-data-services, not opendatahub-io

**Channel:** `#wg-openshift-ai-architecture-diagrams`

@Dana Gutride: "I've noticed the repos point at red-hat-data-services repositories and not opendatahub-io in many cases — is there an updated version that has midstream/upstream context that I can use?"

### Data that doesn't appear in arch-context

**Channel:** `#wg-rhai-ai-first-steering-committee` (75-message thread)

@Eder Ignatowicz: "Jessica, this is an example of data that for some reason don't appear on architectural context." The specifics weren't elaborated, but it triggered the overlay system discussion.

---

## 3. Hallucination / Accuracy

### Hallucination with markdown-based context

**Channel:** `#wg-rhai-ai-first-steering-committee` (weekly report thread)

jtanner noted: "After Luca reported hallucination issues with markdown-based architecture context, Jessica proposed using YAML for deterministic data (API lists, version tables). Jason Greene suggested helper scripts generating markdown deterministically from YAML/CSV inputs."

### LLM-inferred team mappings

**Channel:** `#wg-rhai-strat-refine-review`

@Eder Ignatowicz acknowledged team mappings in strategies are "LLM-inferred (most likely based on PLATFORM.md)." He noted: "If things went terribly wrong, we can always do a file like TEAMs.md or an overlay."

### Strategy violated established principles

**Channel:** `#wg-rhai-strat-refine-review`

@mmortari: The strategy "decided it was a good idea for a proxy sidecar to do additional business logic" — violating their principle of least astonishment. "Some of those principles could be detailed in the Architecture Context, but what about principles that we know Architects or other Stakeholders have 'pinned' in the project?"

### Factual errors not caught by validation

From jtanner's gap analysis:

- Eval-hub port conflict
- Dashboard RBAC staleness
- Missing vllm-cpu endpoints

"The validation scripts catch structural issues but not factual ones."

### Docs in repos might mislead agents

**Channel:** `#wg-openshift-ai-architecture-diagrams` (v2.0 thread)

@Lindani LD Phiri: "There is definitely relevant info in the docs, because there are references to infra level things that may not be directly in the codebase, but are good architecture context. However there are also non-production setup instructions that could muddy up the waters."

jtanner replied: "I'm leery of human written docs given they're usually ill-maintained and out of date."

---

## 4. Clone Performance

### Agent gives up cloning

**Channel:** `#wg-rhai-rfe-builder` and `#wg-rhai-ai-first-steering-committee`

@Jessica: "It took too long to clone otherwise and the agent was like oh well taking too long i will just move on without it." She implemented sparse checkout of just the latest release folder.

@Jessica: "Claude got feisty and didn't want to wait on the clone of the full repo."

This is why she doesn't pull AGENT_USAGE.md: "I'm doing that sparse checkout of just one arch folder."

### 10/20 agents failed to use arch-context

**Channel:** mpdm channel (astefanu/jgreene/jforrest/jtanner)

@astefanu found that when the Bash tool was denied non-deterministically for a subagent, it fell back to Glob, which couldn't find files in the sparse-checkout. "10 out of 20 feasibility agents failed to use architecture context despite it being correctly fetched." Fixed by writing a `LATEST_VERSION` file for Read-based discovery.

---

## 5. Contributor Access / Process

### Permission denied

**Channel:** DM with @abiazett

"I am getting this error: Permission to opendatahub-io/architecture-context.git denied to abiazett... I don't have access to push it directly." Had to create PR #5 via fork.

### No clear update process existed

**Channel:** `#wg-rhai-ai-first-steering-committee` (75-message thread starting 2026-04-18)

@Eder Ignatowicz opened with: "do we have a readme/link on how to update the architectural/design context?"

@andy asked: "if there is a particular 'integration pattern' we know we want for Workbenches moving forward... can we 'hint' at that info such that your skills/scraping could honor that?"

This led to the overlay system being designed in real-time, with @Eder creating PR #2 during the conversation. The urgency was palpable: "sorry to being pushy — I need to handover this to architects."

Key exchange:
- jtanner: "we need to have something that would end up in the rfe skill's .context folder after that script runs"
- @Jessica: "Fwiw we can change how rfe-creator vendors if we need to"
- @Eder: "I've added the superseded_by, that when it's not null, my skills just ignore it (when we convert it for the real thing)"

---

## 6. Architecture / Design Concerns

### Overlays are a "hack"

**Channel:** `#wg-rhai-strat-refine-review` + `#wg-rhai-ai-first-steering-committee`

@mmortari: "I understand that is an 'hack' — what is the expected way to update the Arch Context eventually?"

@Eder Ignatowicz: "It's a bandaid for now for the architect/staff be able to quickly update arch. context." And later: "Later the group will figure out how to do it better."

### 1-day POC now foundational

**Channel:** `#wg-rhai-ai-first-steering-committee` (75-message thread)

jtanner: "just keep in mind arch-context in its current form was a 1 day POC."

@Eder Ignatowicz immediately after: "Well, it's the brain that strat and rfe uses to generate content."

@Jessica weighed in: "Fwiw Eder's requirements would take priority over stuff to generalize for the other orgs, just if you have to prioritize."

### Skills and context mixed in same repo

**Channel:** `#wg-rhai-rfe-builder` (44-message thread)

@astefanu: "architecture-context is both skills and context ATM." Proposed skills should live in ai-helpers.

@Jessica: "Keep it separate from the skills" and "I like that the arch context is in its own repo — especially with how its size will grow over time."

jtanner clarified: "the skills there are largely to generate the outputs." @Jessica agreed: "I meant don't mix it with the skills consuming it."

### Release mechanism unclear

**Channel:** `#wg-rhai-ai-first-steering-committee` (75-message thread)

@andy: "not clear how this `release` is meant to work... particularly as its a list item" (referring to PR #2).

@Eder Ignatowicz worried about "losing overlays when we create 3.5."

jtanner suggested symlinks as a possible approach.

### Need to reconcile with wiki/knowledge management

**Channels:** DM with @khowell + `#wg-rhai-ai-first-code-autofix`

@khowell: "We'll have to reconcile architecture-context and the wiki thing at some point."

@khowell wrote a proposal around "evolving the patterns we started in architecture-context into a broader knowledge management and context synthesis strategy" (linked a Google Doc).

In the autofix thread: khowell is creating a separate repo for organizational context (component mapping etc.), with plans to substantially restructure.

### No automated refresh jobs

**Channel:** `#wg-rhai-rfe-builder` (44-message thread)

@Jessica: "Do you have automated jobs set up for that to refresh it?"

jtanner: "not yet... we didn't really have a project scope beyond the initial 'let's make some diagrams'."

@Jessica suggested: "Wondering if once a week we would want to refresh the current pre-release."

---

## 7. Scope / Boundary Issues

### Architecture context vs organizational context

**Channel:** `#wg-rhai-strat-refine-review` (26-message thread)

jtanner: "there's architecture context and there's organizational context" — questioning whether Jira component mappings belong in arch-context or "an organizational knowledgebase / ambient-GPS type thing."

### Org charts in public repos

**Channel:** `#wg-rhai-strat-refine-review`

jtanner raised: "org charts may not be something we want in public repos."

@Eder Ignatowicz: "We can always make arch. context private."

### RHOAI only — what about RHELAI, RHAIIS?

From jtanner's gap analysis: cross-product scope still open. Only RHOAI documented. "At minimum I should document the product boundary and cross-product integration points."

### Upstream Kubernetes operators/CRDs missing

**Channel:** `#wg-openshift-ai-architecture-diagrams` (12-message thread)

jtanner: "The biggest accuracy problems were driven by gaps in upstream architecture data. Specifically, the tool had no visibility into upstream Kubernetes operators and CRDs that RHOAI depends on, which led it to make incorrect assumptions about dependencies and implementation approaches."

@Lindani LD Phiri suggested: "Would a vector database/RAG with architecture documentation help here?"

jtanner: "there's a ton of options. @khowell has brought up a few. I think it's a matter of testing and evaluating some solutions to see what's more helpful than telling our agents 'go look at this checkout of files'."

Also missing: istio and kuadrant context.

---

## 8. Jira / Component Mapping Gap

### PLATFORM.md doesn't map to Jira components

**Channel:** `#wg-rhai-strat-refine-review` (26-message thread starting 2026-05-01)

@andrewballantyne: "The table of components don't map to Jira components in the RHAISTRAT project — I'm thinking of adding a column next to the name."

jtanner: "there's nothing in the codebases that indicates opendatahub-operator/rhods-operator is referred to as the 'platform'... so when architecture is generated, it simply can't make a map of repos to jira components unless something scrapes jira and maps historical references."

@andy: "it also would be great to map JIRA component labels to code repos" and noted "ENG, STRAT, RFE annoyingly and unnecessarily slightly misaligned."

@Dana Gutride added the dependency dimension: "in addition to just mapping components to repos — we also need a way to identify dependencies between them... Components also might cover multiple codebases so steering and dependency graphs are crucial." She provided concrete data showing a single Jira component ("AI Hub") maps to 15 different repos.

### AutoFix needs repo-to-component mapping

**Channel:** `#wg-rhai-ai-first-code-autofix` (25-message thread)

@Steven Huels: "there are a large number that just need to know the Repo for the component in the issue. Does your Architecture Context agent provide the repo's for the components? It seems like this could be a quick value add with large impact on AutoFix."

Multiple parallel efforts emerged:
- jtanner created a gist with component mapping data
- @khowell started a separate component mapping repo (announced in `#forum-rhai-ai-first`)
- @stobin / @Emilien Macchi working on a separate layer in the autofix pipeline

@Emilien Macchi: "the problem we try to solve too is that not all components have a mapping with one repo, some have multiple repos, like in AIPCC but many other teams I'm sure."

Current plan per jtanner: @khowell to extract rhoai.yaml component mapping into a new org-context repo, iterate with knowledge management proposals.

---

## 9. Integration Requests

### Doc pipeline needs arch-context as grounding

**Channel:** `#wg-rhai-document-builder`

@mmortari: "something like architecture-context will likely need be part of the 'grounding' even if not expressively called out in any of the jira."

@Matthew Stratton's doc-agent pipeline implementation plan references architecture-context as a key input for product context gathering.

### Include as spoke in team_home

**Channel:** `#wg-ray-ai-experiment-team-home`

@lfitzger: "Have we thought about including architecture-context as a spoke into team_home?"

### Connect to autofix pipeline

**Channel:** `#wg-rhai-ai-first-code-autofix` (SDLC working group summary, 24 messages)

Listed as a key action item: "Connect architecture-context to autofix pipeline for better agent outcomes."

Also: "Architecture context: James generated architecture context for AIPC repos via Doug Helman, but status is unclear."

Primary finding from the SDLC working group: "Context improves fixability: Many 'not AI-fixable' bugs from bug bash could become fixable with small amounts of human-provided context."

### CVE/security review needs product context

**Channel:** `#wg-rhai-prodsec-security-collab`

@russellb: "Given the architectural context of our product (Red Hat AI), how does this CVE affect us / our customers? Is the code reachable in how we use it? Is there anything about how we use it that might make it even worse than reported?"

### Bug triage prompts reference arch-context

**Channels:** `#team-ai-core-platform-heimdall`, `#team-ai-core-platform-crucible`

Multiple teams are using arch-context in their bug triage prompts:
- @Ugo Giordano and @sfroberg both include "Consult https://github.com/opendatahub-io/architecture-context" in their triage prompts
- @stobin's recommended triage prompt includes "Consult architecture-context" as a final step

---

## 10. Previously Fixed in v2.0

These issues were identified and resolved in the v2.0 overhaul (34 commits):

- **vllm variants not documented** (P0, 143 combined references) — rhoai.next now has docs for vllm (CUDA), vllm-rocm, vllm-spyre, vllm-gaudi, and vllm-cpu
- **Missing RBAC, TLS, credentials, NetworkPolicy sections** — 93% of security reviews previously flagged "Missing Context" for these sections. Now structured tables in every component doc
- **No free-form architectural analysis** — Added Architectural Analysis section for injection surfaces, multi-tenancy model, supply chain observations, FIPS compliance
- **Sub-component visibility** — BFF sidecars, build variants, multi-binary repos now get explicit Sub-Component Details sections
- **Deployment manifest architecture** — Added Deployment Manifests section documenting kustomize structure, parameterization, ODH/RHOAI distribution variants
- **Component discovery** — Built discover-components phase finding 60+ components automatically via DSC specs, container images, go.mod dependencies. Old approach only found components in get_all_manifests.sh
- **Rich markup parser crash** — Fixed crash on agent output containing /path patterns
- **Agent concurrency safety** — Added safety-net exception handling; sub-agents write findings to temp files

---

## Summary of Open Action Items Identified in Threads

| # | Action Item | Status | Owner |
|---|-------------|--------|-------|
| 1 | **Update cadence** — No automated refresh; no agreed schedule. Jessica suggested weekly for pre-release. | Open | jtanner |
| 2 | **Component-to-Jira mapping** — khowell creating separate org-context repo; andy has cross-project alignment doc; stobin building autofix layer. | In progress | khowell, andy, stobin |
| 3 | **Overlay system permanence** — Currently a "bandaid"; no plan for the "real thing." | Open | Unassigned |
| 4 | **Deterministic data formats** — YAML/CSV for structured data proposed but not implemented. | Open | Unassigned |
| 5 | **Dev-Preview/loosely-integrated components** — Docling, Kagenti, etc. still not systematically covered. | Open | Unassigned |
| 6 | **Upstream dependency coverage** — Kubernetes operators, CRDs, istio, kuadrant gaps remain. | Open | jtanner |
| 7 | **Skills vs. context separation** — Consensus to keep skills separate from context; not yet executed. | Open | jtanner, astefanu |
| 8 | **Contributor access** — At least one contributor (abiazett) had to fork due to 403; process documentation needed. | Open | jtanner |
| 9 | **Cross-product scope** — RHELAI, RHAIIS, OpenShift not covered. | Open | jtanner |
| 10 | **Factual validation** — No mechanism to catch factual errors (only structural validation exists). | Open | Unassigned |

---

## Key Channels with Most Discussion

- `#wg-rhai-ai-first-steering-committee` — governance, overlays, lifecycle, priorities
- `#wg-openshift-ai-architecture-diagrams` — v2.0 announcement, gaps analysis, upstream gaps, diagrams
- `#wg-rhai-strat-refine-review` — Jira mapping, stale data, hallucination, overlay workflow
- `#wg-rhai-rfe-builder` — clone performance, skills vs context, RHAI scope, refresh cadence
- `#wg-rhai-ai-first-code-autofix` — repo-to-component mapping, SDLC integration, autofix connection
- `#wg-redhat-ai-rfe-review` — missing components (Docling, Kagenti, codeflare-sdk)
- `#wg-rhai-document-builder` — grounding needs, doc pipeline integration
- `#rhai-staff-engineering` — initial announcement, feedback solicitation
- `#forum-rhai-ai-first` — RHAIFIRST Jira components, cross-channel announcements
