# Fullsend development stack

This demo defines the first breadboard-to-Fullsend compatibility scenario.
M0 records the scenario contract; M1 adds the k3s GitHub Actions runner and
in-cluster `.local` networking; M3 adds the development mint and Vertex
credential path; M4 executes the deterministic Fullsend role inside OpenShell;
M5 adds Claude/Vertex and M6 verifies the emulator-side result.

## M0 scenario

```text
GitHub workflow_dispatch
  -> fullsend triage role
  -> fullsend-dev/triage-target issue #1
  -> one emulator-visible issue comment containing the scenario marker
```

The first token path is deliberately development-only. The
`fullsend-mint-dev` service exchanges a local opaque OIDC request for an
emulator PAT scoped to the target repository. It is not a production GitHub
App or OIDC implementation.

Harnesses and skills are vendored/local for the first run. Mirroring the
Fullsend agent repositories into the emulator is deferred until the basic
workflow works.

## Run the M0 contract check

From the breadboard repository root:

```bash
python3 var/demos/fullsend-dev-stack/scripts/m0_contract.py
```

The check is deterministic and does not require a running cluster. It verifies
the scenario contract, required local Fullsend files, repository naming, and
that no credential value is embedded in the contract.

## Run the M1 seed and smoke path

The repeatable seed creates the development org, target repository, issue, and
push-triggered shell-only workflow:

```bash
python3 var/demos/fullsend-dev-stack/scripts/m1_seed.py
```

The deployment scripts build/import the local runner image, configure CoreDNS,
install the internal CA in the runner pod, and deploy the runner:

```bash
bash deploy/scripts/05g-build-github-actions-runner.sh
bash deploy/scripts/17-deploy-github-actions-runner.sh
```

M1 evidence from the live stack is recorded in the plan and change ledger.
The workflow is intentionally shell-only; Fullsend Actions compatibility,
token minting, Vertex, and OpenShell begin in M2–M4.

## Run the M2 reduced Fullsend-shaped workflow

This seeds the dispatch-only workflow, creates the `FULLSEND_M2_MARKER`
repository variable, dispatches the workflow, and prints its run ID:

```bash
python3 var/demos/fullsend-dev-stack/scripts/m2_seed.py
```

The live M2 check performs a real emulator checkout, renders dispatch inputs
and repository variables, reaches the reduced `fullsend run` step, and checks
`GITHUB_OUTPUT`/`GITHUB_ENV`. It does not invoke an LLM or OpenShell yet.

Reusable workflows and artifact transport remain compatibility work. M3 adds
the narrow local composite-action support needed by Fullsend's `mint-token`
action.

## Run the M3 mint and Vertex smoke path

Build/deploy the development mint and updated runner, then seed and dispatch
the workflow:

```bash
bash deploy/scripts/05h-build-fullsend-mint-dev.sh
bash deploy/scripts/18-deploy-fullsend-mint-dev.sh
bash deploy/scripts/05g-build-github-actions-runner.sh
bash deploy/scripts/17-deploy-github-actions-runner.sh
python3 var/demos/fullsend-dev-stack/scripts/m3_seed.py
```

The smoke invokes the vendored Fullsend `mint-token` action, verifies the
returned token against the emulator, and loads the existing
`gcp-credentials` file plus Vertex project/region settings. It does not make a
Vertex API call or run an LLM yet.

## Run the M4 OpenShell smoke path

Build the Fullsend launcher from the local checkout, build the pinned
OpenShell CLI, import both development images into k3s, and run the
deterministic dummy role:

```bash
bash deploy/scripts/05i-build-fullsend.sh
bash deploy/scripts/19-run-fullsend-m4-smoke.sh
```

The smoke uses `fullsend-dev/triage-target`, the pre-provisioned emulator role
token, and a local harness/policy ConfigMap. It verifies repository transfer,
`GH_TOKEN` delivery through Fullsend's sandbox `.env`, OpenShell sandbox
creation/cleanup, and the retained marker. Evidence is copied under
`var/demos/fullsend-dev-stack/artifacts/m4/`.

The build script archives the clean `HEAD` of `checkouts.tmp/fullsend` and
applies `patches/fullsend/0001-openshell-compatible-sandbox-and-dummy-env.patch`.
This keeps the setup reproducible and makes the local compatibility changes
easy to propose upstream. The M4 policy is present, but sandbox-side access to
github.local is verified by the M5 network probe.

## Run the M5 Claude/Vertex smoke path

After the M4 images are built/imported and the gcp-credentials secret exists:

bash deploy/scripts/20-run-fullsend-m5-vertex.sh

The script derives a temporary M5 manifest from the proven M4 Job shape. It
switches the runtime to Claude, transfers the existing GCP credential file
into the OpenShell sandbox as a host file, injects the Vertex environment, and
uses explicit policies for the emulator, Google OAuth, and regional Vertex
endpoints. It retains the Claude transcript, output stream, telemetry,
metrics, and OpenShell logs under
var/demos/fullsend-dev-stack/artifacts/m5/.

## Run the M6 emulator-result path

Run the real Claude/OpenShell role with the host-side Fullsend post-script:

```bash
bash deploy/scripts/21-run-fullsend-m6-result.sh
```

The generated post-script posts a marked comment to issue `#1` in
`fullsend-dev/triage-target` through the emulator API. The script verifies the
marker after the Job completes and retains sanitized comment metadata together
with the Claude transcript, trace, metrics, and OpenShell logs under
`var/demos/fullsend-dev-stack/artifacts/m6/`. The sandbox remains read-only to
the GitHub API; the result mutation happens in the host-side post-script.

## Run the M7 Actions-to-emulator path

Build/import the Fullsend runner image, deploy the runner, and dispatch the
workflow-backed scenario:

```bash
bash deploy/scripts/05i-build-fullsend.sh
bash deploy/scripts/17-deploy-github-actions-runner.sh
python3 var/demos/fullsend-dev-stack/scripts/m7_seed.py
```

The seed pushes the workflow and local `.fullsend` harness into the emulator,
dispatches it, waits for the Actions run and job, and verifies a new marked
comment on issue `#1`. The successful validation was workflow run `62`, job
`106`, on `fullsend-dev-runner`.

## Check the M8 runner protocol

Run the emulator-side Actions runner contract tests:

```bash
bash var/demos/fullsend-dev-stack/scripts/m8_protocol_check.sh
```

This validates registration, job polling, log upload, completion, and the
compatibility broker for the emulator-side contract. The upstream binary is
covered by the following M8 smoke.

## Run the M8 upstream runner smoke

Build the upstream runner image from the emulator checkout, then run the
isolated real-runner workflow:

```bash
docker build -t ghemu-actions-real-runner-test:latest checkouts/github-emulator/runner-real
bash var/demos/fullsend-dev-stack/scripts/m8_real_runner_smoke.sh
```

The smoke uses the separate `fullsend-real` label and leaves the M7 lightweight
runner deployment untouched. Its log is retained at
`var/demos/fullsend-dev-stack/m8-real-runner.log`.

The validated reference run was workflow run `74`, job `118`, on
`fullsend-real-runner`; the emulator job log contained
`m8-upstream-runner-ok`.

## Run the complete M8 fidelity checks

After the emulator and runner deployments are ready, the bootstrap script
creates the resettable App/installation fixture and mirrors the selected local
Fullsend actions:

```bash
bash deploy/scripts/22-seed-fullsend-m8.sh
```

The App and OIDC behavior is development-only. The emulator exposes an
ephemeral RS256 issuer at `https://github.local`, and the App private key is
kept only in the emulator's local database. The real standalone Fullsend mint
can be exercised without a production credential:

```bash
bash var/demos/fullsend-dev-stack/scripts/m8_standalone_mint_smoke.sh
PYTHONPATH=var/demos/fullsend-dev-stack/scripts \
  python3 var/demos/fullsend-dev-stack/scripts/m8_events_smoke.py
```

The first command builds Fullsend's `cmd/mint`, validates the emulator JWKS,
calls the emulator App installation API, and checks for a selected-repository
`ghs_` token. The second dispatches triage, review, and coder matrix jobs.
Artifact, permissions, concurrency, cancellation, and App/OIDC regression
coverage is in the GitHub emulator tests.

## M0 boundary

M0 does not create `fullsend-dev/triage-target`, mint tokens, deploy a GitHub
Actions runner, configure cluster DNS, or run Claude. M1 creates the target
fixture and runner; M2 adds the reduced, shell-only Fullsend-shaped workflow;
M3 adds mint authentication and Vertex credential initialization; M4 launches
OpenShell with the deterministic dummy runtime. M4 still does not call Vertex
or run an LLM.
