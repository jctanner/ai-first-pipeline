# Fullsend Development Stack on Breadboard

**Status:** M8 complete; all fidelity checkpoints are development-only and locally reproducible

## Goal

Use breadboard and its GitHub emulator to provide a repeatable development
stack for Fullsend. The first usable path should run one Fullsend agent role
through the emulator's Actions implementation, a Kubernetes runner, OpenShell,
and Vertex AI, then write a visible result back to the emulator.

```text
GitHub emulator
  -> Actions runner pod
  -> Fullsend runner image
  -> OpenShell sandbox
  -> Claude Code / Vertex AI
  -> emulator issue, comment, label, branch, or PR
```

The MVP is intentionally not a complete GitHub replacement. It should provide
the smallest compatible contract needed to run one real Fullsend workflow.

## Current findings

Confirmed from the local checkouts and manifests:

- The GitHub emulator supports PAT authentication, Git transport, substantial
  REST/GraphQL APIs, Actions records, runner registration, and a Python runner.
- The emulator has no GitHub App/installation-token implementation and no
  actual Actions OIDC token issuer. Its OAuth implementation is a simplified
  stub.
- The emulator's workflow graph currently models ordinary jobs and shell
  steps. The lightweight runner now supports the narrow local composite-action
  path required by Fullsend's mint action, but job-level reusable workflows and
  the broader `uses:` action ecosystem remain unsupported.
- The emulator has an experimental real `actions/runner` path, but its README
  still identifies protocol validation as incomplete.
- Breadboard has GitHub `.local` Ingress/TLS routes, an ingress proxy, and
  CoreDNS rewrites. Ordinary k3s pods resolve `github.local`; OpenShell
  sandbox egress to that local endpoint still needs a dedicated compatibility
  fix; M5 verified both the local API request and the real Vertex runtime.
- Breadboard deploys a GitLab Runner but does not yet have an equivalent
  GitHub Actions runner Deployment.
- Fullsend's workflows expect OIDC minting, reusable workflows, composite
  actions, `GITHUB_TOKEN`, OpenShell, and GCP/WIF setup.
- Fullsend's default configuration references pinned resources on public
  `raw.githubusercontent.com` URLs; emulator-local mirroring or vendoring is
  therefore required for an isolated stack.

## MVP architecture decisions

### Separate development mint

Add a breadboard-deployed `fullsend-mint-dev` service rather than putting
Fullsend-specific token-minting logic into the GitHub emulator initially.

The service exposes Fullsend's `/v1/token` contract and maps roles such as
`triage`, `coder`, and `review` to pre-created emulator PATs scoped to the
requested repositories. It is explicitly development-only. The bootstrap
script creates those PATs and stores the role map in a Kubernetes Secret.

The later fidelity milestone may add GitHub Apps, installations, JWT
authentication, OIDC/JWKS, and installation access tokens to the emulator so
Fullsend's standalone mint can run unmodified.

### One initial role

Start with one role and one target repository. Prefer a role whose post-script
result is easy to verify, such as triage producing an issue comment/label. Add
code/PR-producing roles only after the runner, token, sandbox, and API contracts
are stable.

### Vendored harnesses first

For the first smoke test, vendor the required Fullsend harnesses and skills or
use local paths. Later, mirror the Fullsend agent and QualityFlow repositories
into the emulator and validate pinned remote-resource resolution.

## Work packages

### A. Reproducible dependency and seed setup

- Make the Fullsend checkout a declared breadboard dependency under the normal
  `checkouts` layout; do not rely on an untracked temporary checkout.
- Add a repeatable demo/bootstrap directory, likely
  `var/demos/fullsend-dev-stack/`.
- Seed or import the minimum emulator repositories and target fixture.
- Install the Fullsend workflow scaffold and required `.fullsend` content.
- Record source revisions, image tags/digests, and any breadboard-specific
  patches in a change ledger.
- Keep remote agent sources vendored for the first path; add mirroring as a
  separate capability.

### B. GitHub emulator Actions contract

Implement and test the minimum API/runtime contract:

- `workflow_dispatch` REST dispatch.
- `workflow_call` reusable-workflow expansion, including inputs, secrets, and
  outputs.
- Local composite actions and the specific actions required by Fullsend,
  beginning with checkout and artifact handling.
- `GITHUB_TOKEN`, `GH_TOKEN`, repository/API/server/GraphQL URLs, workspace,
  event payload, run identifiers, and step outputs.
- `$GITHUB_ENV`, `$GITHUB_OUTPUT`, and step-summary behavior.
- Repository variables and secrets in the workflow expression context.
- Issue, comment, label, pull-request, review, branch, and push behavior used
  by the selected Fullsend role.
- Event-to-workflow triggering for the initial event, with issue/comment/PR
  events added as required by later roles.

Do not claim broad Actions compatibility until each supported feature has an
emulator test and at least one Fullsend integration test.

### C. Kubernetes GitHub Actions runner

- Add a GitHub Actions runner Deployment and service configuration under
  `deploy/k8s/`.
- Add build/deploy/verify scripts under `deploy/scripts/`.
- Support registration-token bootstrap, repository selection, labels,
  re-registration after restart, workspace cleanup, and local image loading.
- Decide whether the MVP uses an enhanced emulator Python runner or completes
  the real `actions/runner` protocol. The enhanced runner is the shorter path;
  the real runner remains the fidelity target.
- Make runner-facing attempts and stale/requeue behavior observable in the
  emulator UI and logs.

### D. Development token and credential path

- Deploy `fullsend-mint-dev` with role-to-emulator-token configuration stored
  as a Kubernetes Secret.
- Add the Actions OIDC request environment contract, even if the first dev
  mint validates a deliberately non-production token format.
- Configure `FULLSEND_MINT_URL` and required role/repository variables.
- For Vertex, add a development path that reuses breadboard's existing
  credential mechanism instead of requiring Google WIF immediately.
- Keep the production Fullsend `setup-gcp`/WIF path as a later compatibility
  target.

### E. Cluster DNS and TLS

- Add cluster-wide CoreDNS rewrites for the supported `.local` names to the
  ingress-proxy service, preserving the original Host/SNI values.
- Ensure GitHub Actions runner pods and OpenShell sandboxes can resolve and
  reach `github.local`, plus Jira/GitLab/Observatory names when a role needs
  them.
- Propagate breadboard's internal CA to the runner and sandbox images.
- Verify `git`, `curl`, Go, Python, Node, and Claude clients trust the CA.
- Keep any `NO_SSL_VERIFY` behavior explicitly development-only.

### F. Fullsend runner, sandbox, and OpenShell integration

- Build/import a Fullsend runner image containing the Fullsend CLI, OpenShell
  CLI, Git, `gh`, `curl`, `jq`, and the required workflow tooling.
- Build/import the required Fullsend sandbox image or adapt the existing
  breadboard sandbox image.
- Configure the OpenShell gateway endpoint, supervisor image, providers, and
  network policies for the emulator, mint, Vertex, and package registries.
- Ensure Fullsend's host-side pre/post scripts can push branches and create
  comments/PRs while sandbox credentials remain appropriately restricted.
- Use local image references and `imagePullPolicy: Never` or an equivalent
  deterministic development policy.

### G. Bootstrap, smoke test, and evidence

The demo bootstrap must:

1. Verify all required checkouts.
2. Build/import images.
3. Deploy the emulator, mint, runner, DNS, and OpenShell prerequisites.
4. Seed repositories, variables, secrets, and the selected agent config.
5. Dispatch one Fullsend workflow.
6. Verify the Actions run, runner job, OpenShell sandbox, agent output, and
   emulator-side result.
7. Preserve logs, run metadata, source revisions, and failure evidence.

The smoke test should be runnable after a clean system reset without manual
credential or UI steps beyond supplying the existing Vertex credential input.

## Milestones

### M0 — Compatibility contracts and seed design

- Select the first role, event, target repository, and expected emulator-side
  result.
- Write the emulator-to-Fullsend contract tests.
- Decide whether the initial workflow uses vendored or mirrored harnesses.
- Define the dev mint token format and credential boundary.

**Exit:** the required API, workflow, token, DNS, and artifact contracts are
explicit and testable. Evidence: `var/demos/fullsend-dev-stack/m0-contract.json`,
`var/demos/fullsend-dev-stack/scripts/m0_contract.py`, and
`var/demos/fullsend-dev-stack/change-ledger.md`.

### M1 — Runner and in-cluster networking

- Deploy the GitHub Actions runner.
- Add `.local` DNS rewrites and internal CA trust.
- Verify runner registration, push-triggered workflow discovery, job polling,
  and job completion. Repository checkout and `uses:` action handling are
  deferred to M2.

**Exit:** a trivial emulator Actions workflow runs successfully inside k3s.

**Evidence:** the `fullsend-dev/triage-target` seed workflow completed as
emulator run `44`, job `88`, with conclusion `success` on runner
`fullsend-dev-runner`; the runner resolved `github.local` to the ingress proxy
from inside k3s and reached the HTTPS API with the breadboard CA installed.
The emulator Actions idle poll was also fixed and verified to return `204`
when no job is queued. The shell-only smoke deliberately does not exercise
repository checkout; the current lightweight runner executes `run:` steps and
M2 will add the checkout/action contract required by Fullsend.

### M2 — Minimum Actions compatibility

- Add workflow dispatch and reusable workflow support.
- Add the required environment, expressions, outputs, secrets, variables, and
  local action behavior.
- Run a reduced Fullsend-shaped workflow without an LLM.

**Exit:** the Fullsend workflow reaches its `fullsend run` step.

**Evidence:** the repeatable M2 seed dispatched workflow `21` as run `47`;
job `91` completed successfully on `fullsend-dev-runner`. The job performed a
real emulator Git checkout, rendered dispatch inputs and repository variables,
reached the reduced `fullsend run` step, and verified `GITHUB_OUTPUT` and
`GITHUB_ENV` propagation.

This is the minimum M2 slice, not broad Actions compatibility. Job-level
reusable-workflow expansion, local composite-action execution beyond checkout,
and artifact upload/download remain explicit follow-up work before a real
Fullsend workflow can run unchanged.

### M3 — Development mint and Vertex path

- Deploy and test `fullsend-mint-dev`.
- Inject role-scoped emulator credentials.
- Add the development Vertex credential path.

**Exit:** a job can authenticate to the emulator through the Fullsend action
and can initialize the configured model backend.

**Evidence:** `fullsend-mint-dev` deployed successfully with role-specific
emulator PATs and a development-only opaque OIDC contract. Live run `56`, job
`100`, completed successfully: it checked out the target repository, invoked
Fullsend's vendored local `mint-token` composite action, authenticated to the
emulator with the returned token, and loaded the existing breadboard Vertex
credential file. The runner now supplies the local OIDC request endpoint,
executes composite shell steps with Bash, masks action secrets in logs, and
preserves runtime `steps.*.outputs.*` expressions. This validates credential
initialization only; it does not call Vertex or run an agent. The emulator's
PAT implementation does not enforce repository-specific scopes, so the
role/repository restriction is currently a validated mint response contract,
not a production-grade authorization boundary.

### M4 — OpenShell Fullsend execution

- Build/import Fullsend runner and sandbox images.
- Configure gateway connectivity and policies.
- Execute the selected role in an ephemeral sandbox.

**Exit:** the deterministic Fullsend dummy role creates and cleans up an
OpenShell sandbox, receives the emulator token, executes the target checkout,
and leaves retained output and OpenShell logs. The M4 smoke deliberately does
not call Vertex or an LLM; local sandbox egress is carried into M5.

**Evidence:** the clean-archive build path applied the checked-in Fullsend
compatibility patch and rebuilt `fullsend-runner-dev:k3s`. The final smoke
created sandbox `agent-triage-3b8d6`, completed with agent exit code `0`, wrote
`m4-smoke.txt`, retained `behaviour-results.json` and OpenShell logs, and
deleted the sandbox and Job.

### M5 — Local egress and real runtime

- Make OpenShell sandboxes reach the emulator through the supported
  `github.local` route under an explicit network policy.
- Verify the policy path with a sandbox-side API request and internal CA
  handling.
- Replace the dummy runtime with a focused Vertex/Claude role and verify the
  emulator-side result.

**Exit:** the agent completes and produces a retained trace/output artifact.

**Evidence:** The M5 script rebuilt the patched Fullsend image, copied the
existing GCP credential file into the sandbox, and completed sandbox
agent-claude-6d8ed with Fullsend status 0. Claude used Vertex model
claude-opus-4-6 and retained metrics, transcript/output JSONL, telemetry, and
OpenShell logs under var/demos/fullsend-dev-stack/artifacts/m5/. OAuth and
regional Vertex requests were allowed; metadata-server requests were denied
by the fail-closed policy.

### M6 — End-to-end emulator result

- Verify the role's post-script behavior: comment, label, branch, or PR.
- Verify Actions UI state, logs, runner state, and OpenShell artifacts.
- Make the bootstrap and smoke test repeatable from a clean deployment.

**Exit:** one documented Fullsend scenario passes from event to emulator-side
result.

**Evidence:** `deploy/scripts/21-run-fullsend-m6-result.sh` generated the M6
Job from the proven M4 manifest, carried forward the M5 Vertex credential and
OpenShell policy setup, and ran Claude in sandbox `agent-claude-8a772` with
trace `a6f3146f-db26-4f0c-a780-fbaf01e70a37`. The agent completed with exit
code `0`; the host-side POSIX `post_script` then created the marked comment on
`fullsend-dev/triage-target#1`. The script queried the emulator API, verified
the `<!-- fullsend-dev-stack:triage -->` marker, retained sanitized comment
metadata and the run/OpenShell artifacts under
`var/demos/fullsend-dev-stack/artifacts/m6/`, and deleted the Job. The
sandbox's read-only GitHub policy correctly blocked agent-side writes; the
post-script is the intended host-side result path.

This M6 evidence uses the direct breadboard Job launcher. The emulator Actions
surface and runner were validated separately in M1–M3; this run does not yet
claim one combined `workflow_dispatch -> Fullsend Job -> emulator comment`
chain.

### M7 — Combined Actions dispatch

- Connect the validated emulator `workflow_dispatch` path to the Fullsend
  OpenShell Job so one run covers Actions event, runner state, agent execution,
  and the emulator comment.

**Exit:** one workflow-dispatch run completes through the emulator runner,
Fullsend, OpenShell, and a verified emulator-side result.

**Evidence:** `var/demos/fullsend-dev-stack/scripts/m7_seed.py` pushed the
workflow and local `.fullsend` harness into `fullsend-dev/triage-target`, then
dispatched workflow `23`. Run `62` completed successfully with job `106` on
runner `fullsend-dev-runner`; the job checked out the repository, ran the
Fullsend Claude role through OpenShell, and verified the emulator comment.
The seed observed the issue comment count increase from `1` to `2` and found
two marked comments.

### M8 — Fidelity and breadth

M8 is executed in bounded checkpoints. The App/OIDC implementation below is a
resettable emulator feature, not a production GitHub identity claim.

- M8-001: Add a repeatable check for the emulator's runner registration,
  polling, log-upload, completion, and compatibility-broker paths.
- M8-002: Run a shell-only workflow on the upstream `actions/runner` binary
  with a separate `fullsend-real` label and verify its emulator job logs.

- M8-003: Add resettable GitHub App/installation/access-token APIs and an
  ephemeral Actions OIDC issuer/JWKS endpoint.
- M8-004: Build the real standalone Fullsend mint, point it at the emulator's
  OIDC/JWKS and App APIs, and verify a selected-repository `ghs_` token.
- M8-005: Mirror the selected local Fullsend actions and a role/event matrix;
  dispatch triage, review, and coder jobs through the lightweight runner.
- M8-006: Cover matrix expressions, permissions metadata, artifacts,
  concurrency cancellation, and explicit run cancellation.

M8-002 evidence: the isolated real-runner smoke built runner `2.317.0`, used
the `fullsend-real` label, and completed workflow run `74` / job `118` on
`fullsend-real-runner`. The job log contained the expected protocol marker.
The run required public-base URL handling, internal-CA trust in the runner,
label-subset matching, and removal of the artificial queued-job window.

M8-003 evidence: `tests/test_apps_oidc.py` passed the App JWT,
installation, selected-repository token, issuer, and JWKS checks. The live
seed is `scripts/m8_seed.py`; the emulator is configured with
`https://github.local` as its public OIDC issuer.

M8-004 evidence: `scripts/m8_standalone_mint_smoke.sh` built the real
`checkouts.tmp/fullsend/cmd/mint` binary and successfully exchanged a locally
issued OIDC JWT for a selected-repository installation token. The smoke uses
`NO_SSL_VERIFY=1` only for the internal breadboard CA; normal verification is
unchanged by default.

M8-005 evidence: `scripts/m8_mirror.py` mirrored three local Fullsend actions
and the role/event fixture workflow. `scripts/m8_events_smoke.py` dispatched
run `77`, which completed triage, review, and coder matrix jobs `121`–`123`.

M8-006 evidence: `tests/test_actions_fidelity.py` and the Actions regression
tests passed. The emulator now preserves job permissions, stores/retrieves
JSON-backed artifacts, cancels prior runs in the same concurrency group, and
exposes explicit cancellation results.

**M8 exit:** the emulator contract, upstream runner protocol, App/OIDC mint
path, local action mirror, role/event breadth, and fidelity regression checks
all have repeatable scripts or tests. A clean bootstrap runs
`deploy/scripts/22-seed-fullsend-m8.sh` after the deployment stack is ready.

### M9 — Real Fullsend triage agent

Replace the M7 synthetic triage harness with the actual Fullsend triage path.
The target is the pinned `fullsend-ai/agents` `triage.yaml` harness and
Fullsend's upstream `reusable-triage.yml`, executed against the local
`fullsend-dev/triage-target` fixture.

- Mirror or vendor the pinned agent harness and any required remote resources
  into the emulator/local fixture; do not depend on public raw-content URLs at
  runtime.
- Seed the actual triage caller/reusable workflow and the required local
  `.fullsend` configuration, variables, secrets, event payload, and runner
  inputs.
- Implement or verify the remaining emulator behavior required by the real
  workflow: reusable workflow calls, root/local actions, setup-agent-env,
  setup-gcp development credentials, mint-token outputs, permissions, and the
  issue event context.
- Keep the real agent's emulator writes as the result path. Remove the M7
  host-side fixed comment from this scenario; retain it only as a compatibility
  fixture if still useful for lower-level tests.
- Preserve the OpenShell policy boundary and ensure the agent can read the
  target issue/repository while its allowed write operations match the
  development triage contract.
- Capture the agent transcript, API/OTLP evidence, Actions logs, emulator
  comments/labels, source revisions, and all emulator-specific patches.

**Exit:** a clean, repeatable workflow dispatch runs the pinned Fullsend triage
agent—not a generated prompt-only substitute—through the local Actions runner
and OpenShell, and the agent itself produces a verifiable emulator-side triage
result on `fullsend-dev/triage-target`.

**Implementation note:** the pinned `fullsend-ai/agents` checkout does not
contain a `reusable-triage.yml` workflow. M9 therefore uses a repository-local
caller that invokes the pinned `fullsend run triage` harness directly; reusable
workflow integration remains a separate follow-up if the upstream workflow is
added or supplied.

### M10 — Real Fullsend review agent

Exercise the pinned upstream `review.yaml` harness against a local pull request
and verify that the agent's own approval reaches the GitHub emulator.

- Seed the review harness, skills, sub-agents, schemas, policies, profiles,
  local mint action, and a dispatchable repository-local workflow.
- Reuse the role-scoped mint path and local Vertex/OpenShell setup from M9,
  including the explicit `GH_ENTERPRISE_TOKEN` required by `gh` for
  `github.local`.
- Keep first-review inputs explicitly defaulted so the fixture works without
  extra environment variables or secrets.
- Apply the local compatibility patch that changes Fullsend's GitHub
  protected-path file lookup from `gh pr view --json files` (GraphQL) to the
  standard REST pull-files endpoint. The emulator exposes the REST contract;
  this is also valid for GitHub.com and GitHub Enterprise and is suitable for
  an upstream Fullsend patch.
- Require the workflow to observe a review or issue comment after the run.

**Exit:** a clean, repeatable dispatch runs the real Fullsend review agent
through the Actions runner and OpenShell, validates its structured result, and
leaves an emulator-side approval/comment for the local PR.

**Evidence:** `scripts/m10_seed.py` seeded PR #4 and dispatched workflow 27.
Run 122/job 170 completed successfully; the agent ran through OpenShell,
passed schema validation, and posted an `APPROVE` review plus the marked
Fullsend comment. The REST compatibility patch was required because the
emulator's GraphQL `PullRequest.files` field is currently a stub.

## Acceptance criteria

The MVP is complete when a clean bootstrap can:

- deploy the required breadboard and Fullsend components;
- resolve emulator `.local` names from runner and sandbox environments;
- run one Fullsend workflow through the emulator Actions API;
- execute `fullsend run` inside OpenShell;
- authenticate to Vertex through the documented development credential path;
- authenticate back to the emulator with a role-scoped dev token; and
- leave a verifiable issue/PR/comment/label result plus logs and trace artifacts.

No GitHub App or production OIDC claim should be made until M6 is complete.

## Open decisions

- Which Fullsend role is the first target: triage or a minimal code agent?
- Should the MVP enhance the Python runner or prioritize real-runner protocol
  compatibility?
- Which Fullsend repositories and actions will be vendored versus mirrored?
- What existing breadboard Vertex credential should the development workflow
  consume?
- Which `.local` names must be reachable from the first sandbox?
