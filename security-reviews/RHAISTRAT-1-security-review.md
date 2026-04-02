---
strat_key: RHAISTRAT-1
review_date: "2026-04-02"
review_tier: "standard"
verdict: "CONCERNS"
risk_count:
  critical: 0
  high: 0
  medium: 1
  low: 0
architecture_context_consulted:
  - "PLATFORM.md"
  - "rhods-operator.md"
  - "kube-auth-proxy.md"
  - "notebooks.md"
  - "odh-model-controller.md"
---

# Security Review: RHOAI support for Ingress / Gateway API sharding

## Security Verdict: CONCERNS

**Summary:** The STRAT proposes splitting the single `data-science-gateway` into multiple Gateway resources aligned to IngressController shards, but does not address how the tightly-coupled authentication infrastructure (kube-auth-proxy, EnvoyFilter ext_authz, OAuth clients, NetworkPolicies) will be replicated and consistently enforced across each new Gateway instance. This creates a medium-severity risk that sharded Gateways could be deployed without authentication enforcement.

## Threat Surface Analysis

- **Attack surfaces introduced/expanded:** Each new Gateway per IngressController shard creates an additional external HTTPS ingress point (port 443) that must independently enforce authentication. The current single `data-science-gateway` in `openshift-ingress` is the sole external entry point; the proposal multiplies this.
- **Trust boundaries crossed:** The STRAT explicitly states shards map to "a specific network segment" or "a designated test/dev/production development stage." This means the proposal intentionally spans different network trust zones, where each zone's Gateway becomes the trust boundary enforcement point for all RHOAI services exposed on that shard.
- **Data flows created/modified:** HTTPRoute CRs from platform components (Dashboard, Notebooks, KServe InferenceServices, Model Registry, etc.) currently all reference the single `data-science-gateway` as their parent. Under this proposal, components would need to target the correct per-shard Gateway, modifying the parent Gateway reference in every HTTPRoute creation path across the platform.

## Existing Security Controls

The current RHOAI 3.x Gateway API architecture provides a centralized, well-integrated auth stack for the single `data-science-gateway`:

> - **Gateway:** Single `data-science-gateway` Gateway in `openshift-ingress` namespace using GatewayClass `data-science-gateway-class` (controller: `openshift.io/gateway-controller/v1`).
> - **Authentication:** EnvoyFilter `data-science-authn-filter` integrates kube-auth-proxy via ext_authz. A Lua filter strips OAuth cookies and sets Bearer authorization headers. All requests through the Gateway are authenticated via OAuth2/OIDC.
> - **Auth Proxy:** kube-auth-proxy Deployment (2 replicas, HPA 2-10) with service-CA TLS on port 8443, fronted by a ClusterIP Service. OAuth client credentials stored in `kube-auth-proxy-creds` Secret (client ID, client secret, cookie secret).
> - **Network Policy:** `kube-auth-proxy` NetworkPolicy in `openshift-ingress` restricts ingress to port 8443 from Gateway pods and port 9000 from monitoring namespaces.
> - **TLS:** Gateway listener uses TLS 1.2+ (SIMPLE termination). DestinationRule `data-science-tls-rule` configures TLS for upstream service communication. TLS certificates managed via `data-science-gatewayconfig-tls` and `data-science-gateway-service-tls` Secrets.
> - **OAuth Callback:** Dedicated HTTPRoute for `/oauth2/*` paths routes to kube-auth-proxy for OAuth callback handling.
> - **Dashboard Redirects:** nginx-based redirect Deployment + Routes for legacy URLs.
> - **Gateway Discovery:** odh-model-controller exposes `/api/v1/gateways` REST API on port 8443 with Bearer token auth, performing RBAC-based filtering of available Gateways per namespace.

All of these resources are created by the Gateway Controller in rhods-operator and are scoped to the single gateway instance. The controller code (`gateway_controller_actions.go`, `gateway_support.go`) manages the full lifecycle as a unit.

## Security Risks

### RISK-001: Authentication enforcement gap across sharded Gateways

- **Severity:** Medium
- **Category:** auth
- **STRAT Reference:** "For this specific customer scenario, one Gateway for each IngressController shard be the preferred approach, as opposed to using one single Gateway for the default IngressController" (Proposed Solution/Rationale)
- **Relevance:** The current authentication enforcement is architecturally coupled to the single `data-science-gateway` instance. The following resources are all singleton and gateway-specific:
  1. **EnvoyFilter** (`data-science-authn-filter`) — references the specific gateway's listener and routes ext_authz to a specific kube-auth-proxy Service. A second Gateway with a different IngressController would have its own Envoy instance that does NOT have this filter unless explicitly created.
  2. **kube-auth-proxy Deployment** — the single instance is deployed in `openshift-ingress` with a NetworkPolicy allowing ingress only from Gateway pods in that namespace. A shard using a different IngressController (potentially in a different namespace or with different pod selectors) would not match this NetworkPolicy.
  3. **OAuth client** (`kube-auth-proxy-creds`) — the OAuth callback URL is tied to the Gateway's FQDN (`rh-ai.{cluster-domain}`). Each sharded Gateway on a different IngressController will have a different FQDN, requiring a separate OAuth client registration with its own callback URL.
  4. **TLS certificates** — each Gateway listener needs its own TLS certificate matching its hostname. The current `data-science-gatewayconfig-tls` Secret is for the single gateway's hostname.

  Without explicitly specifying that each sharded Gateway must have its own complete auth stack (kube-auth-proxy instance, EnvoyFilter, OAuth client, NetworkPolicy, TLS certs), there is a risk that a new Gateway shard is stood up with routing but without authentication — allowing unauthenticated access to RHOAI services on that network segment.

  This risk is NOT mitigated by existing infrastructure because the existing controls are all scoped to the single gateway instance.

- **Impact:** If a sharded Gateway is deployed without its corresponding EnvoyFilter and kube-auth-proxy, all HTTPRoutes attached to that Gateway would serve traffic without authentication. Given that shards are intended for different network zones (including production), this could expose notebooks, model endpoints, and the dashboard to unauthenticated access on specific network segments.

- **Recommended Mitigation:** The STRAT should specify that the Gateway Controller in rhods-operator must create a complete auth stack per Gateway instance, including:
  - Per-Gateway kube-auth-proxy Deployment, Service, and HPA
  - Per-Gateway EnvoyFilter for ext_authz integration
  - Per-Gateway OAuth client registration with shard-specific callback URL
  - Per-Gateway NetworkPolicy scoped to the shard's IngressController pods
  - Per-Gateway TLS certificate provisioning for the shard's hostname
  - A validation mechanism to prevent creating a Gateway without its auth infrastructure (e.g., a readiness gate or status condition)

## NFR Gaps

- **HTTPRoute targeting:** The STRAT does not specify how component controllers (Dashboard, Notebook Controller, odh-model-controller, KServe) will determine which Gateway their HTTPRoutes should reference. Currently all HTTPRoutes use a hardcoded parent ref to `data-science-gateway`. A selection mechanism is needed — this could be label-based, namespace-based, or configuration-driven via the DSCInitialization/GatewayConfig CRD. Without this, components will default to the original gateway, defeating the sharding purpose.
- **Gateway Discovery API impact:** The odh-model-controller's Gateway Discovery Server (`/api/v1/gateways`) already supports listing multiple Gateways with RBAC filtering. The STRAT should confirm that this API is the intended mechanism for Dashboard and user-facing components to discover available sharded Gateways.
- **Monitoring replication:** The current monitoring configuration (ServiceMonitor for kube-auth-proxy metrics on port 9000, NetworkPolicy allowing monitoring namespace access) is scoped to the single instance. Multiple kube-auth-proxy instances across shards would need corresponding monitoring configuration.

## Organizational Constraint Violations

No organizational constraint violations detected.

## STRAT Amendments Needed

**Security Risk Mitigations** (must be addressed before implementation):
- Add a "Security" or "Auth Architecture" section specifying that each sharded Gateway MUST have a complete, independently-functional auth stack (kube-auth-proxy, EnvoyFilter, OAuth client, NetworkPolicy, TLS certificates). Define whether the Gateway Controller will automatically create these resources for each Gateway or whether a separate mechanism is needed.
- Specify a validation/safety mechanism to prevent a Gateway from accepting traffic before its auth infrastructure is ready (e.g., a Gateway status condition that blocks HTTPRoute attachment until the EnvoyFilter and kube-auth-proxy are healthy).

**NFR Additions** (recommended for completeness):
- Define the HTTPRoute-to-Gateway selection mechanism: how do component controllers know which Gateway to target for a given workload or namespace?
- Confirm the GatewayConfig CRD will be extended to support multiple gateway definitions, or define a new CRD for per-shard gateway configuration.
- Specify monitoring requirements for multiple kube-auth-proxy instances.

## Missing Context

- **Missing STRAT detail:** The STRAT is a sparse RFE-level description with no Technical Approach, Affected Components, Dependencies, NFRs, or Risks sections. The Proposed Solution is a single sentence ("one Gateway for each IngressController shard") with no architectural detail. This severely limits the security review — most analysis is based on inference from the architecture context about what would be required, rather than what the STRAT specifically proposes.
- **Missing requirements:** No specification of how many shards are expected, whether shards can be in different namespaces, whether shard configuration is declarative (CRD-driven) or imperative, or what the lifecycle of a sharded Gateway looks like (create, update, delete).
- **Missing threat model inputs:** The STRAT mentions different network zones ("specific network segment" and "test/dev/production development stage") but does not define the trust model between zones. For example: should a user authenticated on one shard's Gateway be able to access services on another shard? Are there isolation requirements between zones beyond network segmentation?
- **Missing integration details:** No detail on how this interacts with the existing GatewayConfig CRD (`services.platform.opendatahub.io/v1alpha1`), the Dashboard redirect infrastructure, or KServe/LLMInferenceService Kuadrant AuthPolicy integration which targets the specific `data-science-gateway`.

## Recommendation

**CONCERNS** — The STRAT proposes a significant architectural change to the RHOAI ingress model (single gateway to multiple sharded gateways) without addressing how the authentication enforcement architecture will scale across shards. The current auth stack is tightly coupled to the single gateway instance, and the proposal creates a real risk of unauthenticated gateway shards if auth replication is not explicitly designed. The STRAT should be revised to include a security architecture section before implementation begins. The risk has a known mitigation pattern (replicate auth infrastructure per gateway) and does not require fundamental redesign.
