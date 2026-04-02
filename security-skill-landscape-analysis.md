# Security Skill Landscape Gap Analysis

Gap analysis between the RHOAI Security Landscape document (`tmp/RHOAI-SECURITY-LANDSCAPE.md`) and the current `strat-security-review` skill (`.claude/skills/strat-security-review/SKILL.md`).

## What the Skill Currently Covers

The skill assesses 11 dimensions and enforces 8 organizational requirements:

| Dimension | Coverage |
|-----------|----------|
| Authentication & Authorization | Approved auth patterns, RBAC, token handling, multi-tenancy |
| Data Protection | Sensitive data storage, encryption at rest, secrets, retention |
| Cryptographic Compliance | FIPS 140-3, PQC tension, certificate management |
| Network & API Security | New endpoints, rate limiting, Gateway API |
| Supply Chain & Dependencies | External deps, image provenance, build pipelines |
| Infrastructure & Deployment | Least privilege, pod security, network policies |
| Operational Security | Logging, monitoring, upgrade implications |
| Compliance & Regulatory | FedRAMP/FIPS, certification boundaries |
| ML/AI-Specific Threats | Data poisoning, prompt injection, model artifact access, model provenance |
| Multi-Tenant Isolation | Namespace boundaries, shared resources, resource quotas, side-channels |
| Organizational Requirements | FIPS, PQC, Gateway API, Service Mesh, image provenance, upstream-first, auth patterns, secrets |

## Identified Gaps

### Gap 1: Agentic AI Security

**Landscape reference:** Gap 1 (Agentic AI Security Has No Owner), Gap 6 (No Threat Model for RHOAI as AI Workload Platform)

The skill's ML/AI section covers model poisoning and prompt injection but does not assess agentic AI concerns:

- **Agent workload sandboxing** — Does the STRAT deploy agent workloads? What prevents a compromised agent from accessing cluster resources, other tenants' data, or escalating privileges? The landscape notes Kubernetes `agent-sandbox` (Kata Containers) exists but is not integrated into RHOAI.
- **Agent skill/tool permission scoping** — Does the STRAT give agents access to tools? Are tool permissions scoped per-agent or blanket? 36% of agent skills have at least one vulnerability per Snyk research.
- **Agent-to-agent (A2A) communication** — Does the STRAT enable agents to call other agents? What prevents a compromised agent from manipulating another agent's actions via its A2A interface?
- **Agent action audit trail** — Are agent tool calls, model invocations, and data access operations logged with sufficient detail for forensic analysis? 40% of deployed agents have zero safety monitoring per Gravitee 2026.
- **Agent goal hijacking / misalignment** — Does the STRAT address what happens when an agent's actions diverge from intended behavior? OpenAI documented their own coding agents encoding commands in base64 to bypass security controls.

**What to add to the skill:** An "Agentic AI Security" subsection under "What to Assess" covering sandboxing, tool permissions, A2A auth, audit trails, and misalignment detection.

### Gap 2: MCP Server/Tool Security

**Landscape reference:** Gap 2 (MCP Server/Tool Security Architecture Is Missing)

Completely absent from the skill. The landscape documents a specific attack pattern — the "lethal trifecta":

> An MCP server with access to (1) private data, (2) untrusted content, and (3) external communication capability = data exfiltration via prompt injection.

Specific checks the skill should perform when a STRAT involves MCP:

- **MCP server authentication** — Does the STRAT specify how MCP servers authenticate to the platform and to agents? 53% of MCP servers use insecure static credentials per Gravitee 2026.
- **MCP tool poisoning** — Can a malicious MCP server inject tool descriptions that cause agents to execute unintended actions? Are tool descriptions validated?
- **MCP credential management** — How are MCP server credentials stored, rotated, and scoped? Does the STRAT avoid hardcoded credentials?
- **MCP scope/permission controls** — Are MCP server capabilities restricted to what the agent actually needs? Is there a capability model or allowlist?
- **MCP sandboxing** — Are MCP servers isolated from each other and from the platform? Can a compromised MCP server access other MCP servers' data?
- **Lethal trifecta check** — Does the proposed MCP integration combine private data access + untrusted content processing + external communication? If so, flag as Critical.

**What to add to the skill:** An "MCP Security" subsection under "What to Assess."

### Gap 3: Agent Identity and Zero Trust

**Landscape reference:** Gap 4 (Agent Identity and Zero Trust Is Unsolved)

The skill covers human-user authentication but does not address agent identity:

- **Agent authentication** — How does an agent authenticate to tools, models, and other agents? Is there a workload identity mechanism (SPIFFE/SPIRE, OAuth2 token exchange)?
- **Agent credential lifecycle** — How are agent credentials issued, rotated, and revoked? Are they scoped per-session or persistent?
- **Per-request least privilege** — Can agent permissions be scoped per-request rather than per-deployment? Does the STRAT address dynamic permission adjustment?
- **Agent identity propagation** — When an agent calls a tool on behalf of a user, is the user's identity propagated for audit and authorization? Or does the agent use its own identity, breaking the audit chain?

**What to add to the skill:** Expand the "Authentication & Authorization" dimension to include agent identity concerns, or add a dedicated "Agent Identity" subsection.

### Gap 4: FIPS Language-Specific Depth

**Landscape reference:** Designed for FIPS (DfFIPS) Deep Dive

The skill's organizational requirements say "All crypto MUST use FIPS-validated modules on RHEL 9" but the landscape reveals language-specific constraints that affect whether a STRAT's implementation choices are FIPS-compatible:

| Language | Key Constraint | Skill Awareness |
|----------|---------------|-----------------|
| **Go** | Must use CGO_ENABLED=1, GOEXPERIMENT=strictfipsruntime, RHEL/UBI Go compiler | Not in skill |
| **Python** | Banned packages: pycrypto, pycryptodome, blake3, rsa. Binary wheels with Rust crypto extensions need recompilation from source. check-payload does NOT scan Python code. | Not in skill |
| **Java** | Automatic with RH JDK unless explicitly overridden | Not in skill |
| **Rust** | No formal FIPS guidance exists yet | Not in skill |

When a STRAT introduces a new component or dependency in a specific language, the reviewer should know whether FIPS compliance is straightforward (Java), well-defined but requires specific build flags (Go), partially covered with known gaps (Python), or undefined (Rust).

**What to add to the skill:** Add language-specific FIPS constraints to the organizational requirements table or as notes under Cryptographic Compliance.

### Gap 5: PQC/TLS Compliance Specifics

**Landscape reference:** Post-Quantum Cryptography (PQC) section

The skill says "Acknowledge tension with FIPS; do not mandate PQ-only" but misses actionable PQC requirements:

- **OCP 4.22 ML-KEM mandate** — All TLS servers must negotiate TLS 1.3 + ML-KEM if the client supports it. This is mandatory, not optional.
- **TLS profile obedience** — Components must honor cluster-wide TLS settings. No hardcoded TLS versions, cipher suites, or curve preferences. Violation is an OCP 5.0 release blocker.
- **Known blockers** — PostgreSQL < 18 only supports one TLS curve (cannot negotiate ML-KEM). If a STRAT depends on PostgreSQL, this is a known constraint.
- **Go TLS limitation** — Go does not allow configuring TLS 1.3 cipher suites (hardcoded). It does allow curve preferences (where PQC lives).
- **Exception process** — If a component cannot meet PQC requirements, it must file an OCPEXCEPT. The skill should flag this as an action item, not a blocker.

**What to add to the skill:** Update the organizational requirements table to include TLS profile compliance and ML-KEM as specific requirements with enforcement timelines.

### Gap 6: Upstream Component Risk Awareness

**Landscape reference:** Critical Security Findings, organizational gaps

The skill assesses each STRAT in isolation. The landscape documents systemic upstream risks that should inform review when a STRAT touches these components:

| Upstream Component | Known Systemic Risk |
|-------------------|-------------------|
| **Ray** | Architecturally "insecure by design" (CVE-2023-48022 / ShadowRay 2.0) — no authentication on Dashboard by default |
| **MLflow** | 6+ recurring path traversal CVEs across two years — systemic codebase pattern, not isolated bugs |
| **Kubeflow** | Profile Controller runs as cluster-admin — anti-pattern for least privilege |
| **HuggingFace transformers** | CVEs with no upstream fix path — Red Hat must find mitigations independently |
| **vLLM** | Model loading from untrusted sources — Pickle deserialization risks |

When a STRAT proposes using or extending one of these components, the reviewer should cross-reference these known risks and check whether the STRAT's design accounts for them.

**What to add to the skill:** A "Known Upstream Risks" reference section, or a calibration rule instructing the reviewer to consider known upstream security posture.

### Gap 7: AI Artifact Supply Chain

**Landscape reference:** Build Security (Konflux), Gap 6 (RHOAI-as-platform threat model)

The skill covers container image provenance and dependency pinning, but the landscape identifies a gap: Konflux secures the code supply chain but does NOT cover:

- **ML model artifact provenance** — Who built/signed the model? What's its training lineage? Can a user upload a malicious model (Pickle deserialization, backdoored weights)?
- **Training data supply chain** — Where did training data come from? Is it validated against poisoning?
- **Agent skill/tool supply chain** — Are agent skills and tool definitions sourced from trusted origins? Are they integrity-checked?
- **MCP tool description integrity** — Can MCP tool descriptions be tampered with between registration and invocation?

**What to add to the skill:** Expand "Supply Chain & Dependencies" to include AI-specific artifacts (models, training data, agent skills, MCP tools), not just code dependencies and container images.

### Gap 8: ServiceAccount/RBAC Anti-Pattern Awareness

**Landscape reference:** Critical Security Findings (Systemic RBAC Vulnerability)

The skill checks "Are new Kubernetes resources properly scoped (least privilege)?" but doesn't reference the known RHOAI-specific anti-pattern:

- 9 out of 10 RHOAI components have excessive ServiceAccount permissions (cluster-wide secrets access, pods/exec, RBAC manipulation)
- Only `notebook-controller-service-account` follows correct least-privilege
- 548+ secrets accessible via ServiceAccount token extraction

When a STRAT creates new ServiceAccounts, requests new RBAC permissions, or deploys new controllers, the reviewer should explicitly check against this known anti-pattern and flag any repetition of it.

**What to add to the skill:** Add to organizational requirements or calibration rules: "New ServiceAccounts and RBAC must be namespace-scoped. Cluster-wide permissions are a known systemic vulnerability in RHOAI (9/10 components affected). Flag any new cluster-wide RBAC as High severity."

### Gap 9: Cross-Component Attack Chain Analysis

**Landscape reference:** Role Boundaries (what security engineers uniquely do)

The skill reviews each STRAT in isolation. The landscape identifies cross-component attack chain analysis as something only the security engineers do — and it's missing from the skill:

- How does a vulnerability in the STRAT's component chain into exploits in adjacent components?
- Does a prompt injection in model serving chain through a pipeline into a Ray cluster?
- Does a RBAC escalation in one namespace affect the security posture of another?

This is inherently difficult for a per-STRAT reviewer to catch, but the skill could at least prompt the reviewer to consider adjacent-component implications for Deep-tier reviews.

**What to add to the skill:** A calibration rule for Deep-tier reviews: "Consider how the proposed change interacts with adjacent components. Can a vulnerability in this STRAT's scope chain into exploits in other RHOAI layers?"

### Gap 10: TLS Profile Compliance as Organizational Requirement

**Landscape reference:** PQC section, Runtime Security

The organizational requirements table does not include TLS profile compliance, which is an OCP 5.0 release blocker:

- Components must honor cluster-wide TLS settings (no hardcoded TLS versions, cipher suites, or curve preferences)
- Both kube-auth-proxy and kube-rbac-proxy have known bugs: they set CipherSuites unconditionally for TLS 1.3 where Go ignores them
- Any new component or TLS endpoint must support configurable TLS profiles

**What to add to the skill:** Add "TLS Profile Compliance" to the organizational requirements table.

## Summary

| # | Gap | Severity | Effort to Fix |
|---|-----|----------|---------------|
| 1 | Agentic AI security (sandboxing, tool permissions, A2A, audit) | High | New assessment dimension |
| 2 | MCP server/tool security (auth, poisoning, credentials, sandboxing, lethal trifecta) | Critical | New assessment dimension |
| 3 | Agent identity and zero trust (workload identity, credential lifecycle, per-request authz) | High | Expand existing dimension |
| 4 | FIPS language-specific constraints (Go, Python, Java, Rust) | Medium | Notes under existing dimension |
| 5 | PQC/TLS compliance specifics (ML-KEM mandate, TLS profile obedience, known blockers) | Medium | Expand organizational requirements |
| 6 | Upstream component risk awareness (Ray, MLflow, Kubeflow, HuggingFace, vLLM) | Medium | New reference section |
| 7 | AI artifact supply chain (model provenance, training data, agent skills, MCP tools) | High | Expand existing dimension |
| 8 | ServiceAccount/RBAC anti-pattern awareness | Medium | Add to organizational requirements |
| 9 | Cross-component attack chain analysis | Low | Add calibration rule |
| 10 | TLS profile compliance as organizational requirement | Medium | Add to organizational requirements |
