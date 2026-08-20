# Plan: Replicate `strat-pipeline` in the Breadboard emulators

## Objective

Mirror `strat-creator` and `assess-strat` into the GitHub emulator, mirror
`strat-pipeline` into the GitLab emulator, and run the strategy pipeline against
the local GitHub, GitLab, and Jira emulators. Changes should be isolated,
documented, and generic enough to propose upstream where practical.

## Agreed target

- GitHub emulator repositories:
  - `opendatahub-io/strat-creator` (`main`)
  - `opendatahub-io/assess-strat` (`main`)
- GitLab emulator project:
  - `redhat/rhel-ai/agentic-ci/strat-pipeline`
- Additional GitLab emulator projects:
  - `redhat/rhel-ai/agentic-ci/strat-pipeline-data`
  - `redhat/rhel-ai/agentic-ci/strat-dashboard`
- Preserve all four pipeline job types and the schedule configuration. Use
  `single-rfe` as the first focused test path.
- Jira identity:
  - display name: `AIPCC Agentic Jira Bot`
  - email / `JIRA_USER`: `aipcc-agentic-jira-bot@redhat.com`
  - create a Jira emulator token and store it as a masked GitLab CI variable.

The data project is initialized empty for result commits. The dashboard is
restored from the local `deploy/repos.third-party/strat-dashboard` checkout and
its Pages job is adapted through the same reproducible publisher.

## Repeatable reset/recreate model

The setup must not depend on the current contents of emulator databases or on
manual UI configuration. Treat it as a demo fixture with two phases:

1. `clean-all.sh --yes` (or the equivalent service reset) wipes emulator and
   pipeline state and re-registers the CI runner.
2. The platform deployment/bootstrap recreates the in-cluster Kubernetes
   runner, then one idempotent `strat-pipeline` bootstrap recreates the
   forge/Jira/pipeline fixture.

### Platform CI-runner prerequisite

`glemu-k8s-runner` is part of the platform deployment, not a repository
fixture. Its reproducible definition is split between:

- `deploy/k8s/21-gitlab-runner.yaml` — namespace, service account, RBAC, and
  permissions for job pods;
- `deploy/scripts/15-deploy-gitlab-runner.sh` — runner registration,
  runtime-generated runner token, emulator URL, tags, Kubernetes executor
  configuration, CA mount, and runner Deployment;
- `deploy/scripts/deploy-all.sh` — invokes the runner deployment during a
  fresh stack install;
- `deploy/scripts/clean-all.sh` — removes the runner configuration while
  wiping data and invokes the same registration script afterward.

The expected runner identity is `glemu-k8s-runner`, with tags
`k8s-incluster,aipcc-small-x86_64`, using the Kubernetes executor in the
`gitlab-runner` namespace. The strat-pipeline bootstrap must verify that this
runner is registered, online, and advertises the required tag before M4; it
must not create a second runner registration.

Add a tracked fixture bundle under `var/demos/` containing:

- a source manifest with repository URLs, expected commits, target hosts,
  owners, project paths, and refs;
- bootstrap code that waits for emulator health, creates groups/projects/users,
  imports or pushes repositories, creates Jira projects/issues, creates the
  Jira PAT, and writes GitLab CI variables/schedules;
- small Jira seed fixtures for the focused `single-rfe` run;
- a patch/change ledger and, where needed, tracked patch files that can be
  applied to fresh source checkouts;
- a README with one reset/bootstrap command, required external credentials,
  generated-secret handling, and verification commands.

The private `strat-pipeline` source should be exposed to the fixture through a
tracked relative symlink, for example:

```text
var/demos/strat-pipeline-replication/strat-pipeline
  -> ../../../deploy/repos.third-party/strat-pipeline
```

Preflight must fail with an actionable message when the symlink is dangling or
the target is not a Git checkout. It should also print and record the source
remote, branch, commit, and dirty-state so local changes remain attributable.
This intentionally means a full workspace wipe requires the private checkout
to be restored separately; the fixture must not pretend it can reconstruct
private source without credentials or an external source artifact.

Environment-specific adaptations should be applied from the tracked patch set
or generated configuration; they should not exist only as untracked edits in
`deploy/repos.third-party`.

Generated secrets are acceptable for the emulator, but they must be returned
only through a local operator output or a Kubernetes/GitLab secret path and
must never be written to the fixture manifest, logs, or committed files. A
second bootstrap against the same state must converge without creating
duplicate users, projects, repositories, tokens, schedules, or Jira issues.

## Source baselines

Record the source commit and local mirror commit before making changes:

| Component | Source | Initial checkout |
|---|---|---|
| `assess-strat` | `https://github.com/opendatahub-io/assess-strat` | `ae449845b2c8bde238ba7cd6ecd536b2c83f4a8b` |
| `strat-creator` | `https://github.com/opendatahub-io/strat-creator` | `2588e668f89c719946723430ec2dde8bc0047fd6` |
| `strat-pipeline` | `git@gitlab.com:redhat/rhel-ai/agentic-ci/strat-pipeline` | `14d81319af44973d592e4197b14b680684f35813` |
| `strat-dashboard` | `git@gitlab.com:redhat/rhel-ai/agentic-ci/strat-dashboard` | `0bb887f7766d10df26f25cae14c66422d6e546e4` |

For every local change, record the source file, reason, local commit, whether
it is a candidate for upstream, and the validation that supports it. Keep
environment-only changes separate from generic compatibility fixes.

## Work plan

### 1. Establish the emulator topology

- Add the fixture bundle and its source/patch manifest before making service
  changes, so every later compatibility change has a replayable entry point.
- Verify the deployed GitHub, GitLab, and Jira emulator URLs and the CA bundle
  available to GitLab Runner jobs.
- Verify `glemu-k8s-runner` is online with the `aipcc-small-x86_64` tag. If the
  platform was freshly reset, run the existing platform runner bootstrap
  before continuing; do not hand-create the runner in the GitLab UI.
- Create the nested GitLab groups and the three projects above.
- Import the two GitHub repositories with history, default branch, and tags as
  applicable; import `strat-pipeline` with history into the nested GitLab
  project.
- Bootstrap `strat-pipeline-data` with an empty logical layout and `main`; it
  must accept result commits from the pipeline.
- Mirror the restored `strat-dashboard` checkout and adapt its Pages job to
  clone the local creator and data repositories.
- Keep the mirrors reproducible through an idempotent setup script or workflow;
  do not rely on hand-created UI state.

### 2. Create credentials and access

- Create the Jira user with the agreed display name, email, and a stable
  emulator username.
- Create a Jira PAT/API token for that user through the emulator’s supported
  token API. Grant the read/write behavior required for RHAIRFE and RHAISTRAT
  issue discovery, locking labels, strategy creation, refinement, review, and
  unlock operations.
- Store the raw token only in the local secret-management path; add it to the
  pipeline project as masked `JIRA_API_TOKEN` and expose it to the job as
  `JIRA_TOKEN`. Set `JIRA_USER` to the bot email.
- Create a GitLab emulator credential with permission to clone the local
  GitHub mirrors, clone/push `strat-pipeline-data`, and trigger the dashboard
  project. Store it as a masked CI variable; do not put it in repository files.
- Provide the existing Vertex project/service-account values through CI
  variables required by `setup-claude-ci.sh`: `GCP_PROJECT_ID` and the
  base64-encoded `GCP_SERVICE_ACCOUNT_KEY`.

### M1 execution record

The repeatable topology bootstrap is implemented at
`var/demos/strat-pipeline-replication/scripts/bootstrap_topology.py`. It uses
the local Git checkouts as push sources, creates or reuses the forge objects,
and writes the non-secret `topology-manifest.json`. A second run converged
without creating duplicate objects.

Observed topology:

- GitHub mirrors are public and their `main` refs are
  `strat-creator@2588e668f89c719946723430ec2dde8bc0047fd6` and
  `assess-strat@ae449845b2c8bde238ba7cd6ecd536b2c83f4a8b`.
- GitLab projects are private, use `main`, and are nested under
  `redhat/rhel-ai/agentic-ci`. The pipeline `main` ref is
  `14d81319af44973d592e4197b14b680684f35813`; the dashboard source ref is
  `0bb887f7766d10df26f25cae14c66422d6e546e4`; data has an emulator-generated
  initial commit.
- No CI run, Jira account, token, or CI variable was created in M1.

The bootstrap initially exposed a source-selection bug: its push subprocess
was using Breadboard's working checkout instead of the selected source. The
script now passes each source through `git -C` and verifies the advertised
remote ref before writing success metadata. This is recorded as a fixture
bootstrap fix, not a source-repository change.

### M2 execution record

M2 is implemented by
`var/demos/strat-pipeline-replication/scripts/bootstrap_credentials.py`. It
converges the Jira bot/PAT and GitLab results-push PAT through the existing
emulator APIs, stores them as masked `JIRA_API_TOKEN` and
`RESULTS_PUSH_TOKEN` project variables, and verifies the bot's `myself` and
JQL paths. It also verifies the platform CA objects used by runner jobs and
copies available GCP inputs into `GCP_PROJECT_ID` and
`GCP_SERVICE_ACCOUNT_KEY` variables. It stores the same GitLab PAT as masked
`DATA_REPO_TOKEN` on the dashboard project and installs its endpoint overrides.
`credentials-manifest.json` is metadata only; raw credentials are never
written to the fixture.

The M2 rerun after the M1 reset converged successfully. Its visible endpoint
variables are emulator overrides, not new upstream requirements; the pipeline
defaults remain in the adapted CI configuration for ordinary public use.

### M0/M1 review after upstream-compatibility correction

M0 was revalidated against the unchanged private source checkout and still
reports the expected remote, `main` branch, baseline commit, and clean state.
M1 was rerun idempotently: both GitHub mirrors retained their source commits,
the nested GitLab groups/projects remained correct, and the pipeline mirror was
reset to the source baseline before M3 reapplied its transformation. Neither
milestone needs a patch for the upstream-default requirement.

### M3 execution record

M3 is implemented by the tracked transformations under
`var/demos/strat-pipeline-replication/patches/` and publisher
`scripts/apply_m3_patch.py`. The source checkouts remain clean; the latest
source/adapted pairs are:

- `strat-creator`: `5761024` -> `1b7532f`
- `strat-pipeline`: `14d81319af44973d592e4197b14b680684f35813` -> `975ccf3`
- `strat-dashboard`: `0bb887f7766d10df26f25cae14c66422d6e546e4` -> `f1ace7a`

The strategy pipeline retains public-safe shell fallbacks while accepting
emulator project variables for GitHub, GitLab, Jira, Vertex, and TLS. The
dashboard Pages job similarly derives the creator and data-repository URLs at
runtime and uses masked `DATA_REPO_TOKEN` only for the emulator checkout.
`NO_SSL_VERIFY=1` remains opt-in and project-scoped.

M3 validation passed with CI lint for all four strategy jobs and the dashboard
`pages` job, the scheduled `batch-jql` contract, upstream defaults, emulator
overrides, and the dashboard bridge prerequisites. Bridge-only pipeline `1865`
completed successfully; downstream dashboard pipeline `1866` and Pages job
`3714` also completed successfully. The earlier `.gitlab-ci.yml not found`
failure was caused by the placeholder dashboard project and is resolved.

### M4 focused execution record

The seeded Jira fixture is `RHAIRFE-1`, labeled with the targeting and quality
labels used by the demo workflows. Initial focused attempts exposed nested
GitHub URL expansion, the public Jira URL masking the emulator URL, and
`NO_SSL_VERIFY=1` being masked by its YAML default; these are recorded in the
change ledger. After the runtime fixes, job `3699` cloned both local GitHub
repositories and the local results project, locked `RHAIRFE-1`, and created
`RHAISTRAT-1`. That fixture was not suitable for a clean rerun because its
existing strategy had the `strat-creator-rubric-pass` gate label.

A fresh validation issue `RHAIRFE-2` was created and processed by pipeline
`1858`, job `3704`. The job completed successfully through create, refine,
review, unlock, and result publication. It created `RHAISTRAT-2`, received a
7/8 `APPROVE` automated score, and pushed result commits `7858149` and
`077d019` to `strat-pipeline-data`. A command-specific trace scan found no
`pytest`, `uv run pytest`, or `make test` invocation. M4 focused execution is
therefore complete. The dashboard bridge was subsequently verified separately
by pipeline `1865`, with downstream Pages pipeline `1866` and job `3714`
completing successfully.

### M5 broader validation record

`reprocess-strat` was run against `RHAISTRAT-2` in pipeline `1873`, job `3723`.
It successfully pulled the four Jira-backed artifacts, including attachments,
ran refine and review, unlocked `RHAIRFE-2`, and completed publication. The
runner displayed a stale-threshold warning during the long Claude review, but
the runner pod remained active and the job ultimately succeeded; no requeue was
performed.

`batch-config` was exercised with the adapted mirror's fixture-only
`config/emulator-smoke.yaml`. Its first run (`3727`) correctly skipped the
already-processed `RHAIRFE-2` but exposed that `pipeline-post.sh` failed when no
strategy artifacts existed. Tracked patch `0006-no-work-pipeline-post.py` makes
that valid no-work case successful. The rerun in pipeline `1881`, job `3734`,
completed successfully.

The existing GitLab test schedule was given `BATCH_SIZE=0` and manually played.
Pipeline `1878`, job `3730`, materialized `batch-jql` with
`CI_PIPELINE_SOURCE=schedule` and completed successfully without selecting an
RFE. This validates the scheduled rule and runner path without processing
unintended production issue keys. The dashboard trigger jobs also completed as
part of these pipelines.

### 3. Make the pipeline environment-configurable

Adapt `.gitlab-ci.yml` and helper scripts so the same pipeline can target the
public services or the emulators through variables:

- Replace the public `CLAUDE_REPO` and `CLAUDE_PLUGINS` URLs with local GitHub
  emulator URLs for `strat-creator` and `assess-strat`.
- Replace `JIRA_SERVER=https://redhat.atlassian.net` with the Jira emulator
  endpoint reachable from runner pods.
- Set `JIRA_USER` explicitly; the current CI file sets `JIRA_TOKEN` but the
  runner preflight also requires `JIRA_USER`.
- Replace the hard-coded public `RESULTS_REPO` with the local nested GitLab
  project URL/path.
- Update `clone-data-repo.sh` and `push-results.py`, which currently construct
  `https://bot:<token>@gitlab.com/...` for path-style repositories. They must
  accept an emulator base URL or a complete authenticated URL without
  embedding `gitlab.com`.
- Update the `build-dashboard` trigger to the local dashboard project and
  verify that the GitLab emulator supports the required downstream trigger
  behavior. Keep it non-blocking only if the placeholder dashboard cannot
  provide a valid target pipeline.
- Preserve the four job rules, `resource_group`, schedule variables, and
  manual variables. Adapt only values that describe the environment.
- Verify the `aipcc-small-x86_64` runner tag matches the deployed runner. Keep
  image/package installation changes separate from URL and credential changes.
- Verify `setup-claude-ci.sh` works in the selected job image: it installs git,
  Python, Claude Code, and the GCP key at runtime. Ensure local TLS trust and
  outbound Vertex access are available to that job.

### 4. Validate the GitHub skill consumption path

- From a real GitLab Runner job, clone local `strat-creator` and load the local
  `assess-strat` plugin over the emulator hostname.
- Confirm the cloned commits are the expected mirror commits, not public
  GitHub fallbacks.
- Confirm the skill workspace can fetch architecture context as configured by
  `strat-creator`; if that remains an external dependency, record it explicitly
  and decide whether it also needs a local mirror.
- Add a provenance check to the setup/test workflow so future mirror changes
  identify the exact skill and plugin commits used by a run.

### 5. Focused execution and broader pipeline checks

Run checks in this order:

1. Verify Jira bot authentication with `myself`, JQL search, label update, and
   issue update against the emulator.
2. Run `single-rfe` against a seeded RHAIRFE issue and verify the complete
   create → refine → review → unlock path.
3. Verify generated artifacts, labels, and Jira links.
4. Verify a result commit reaches `strat-pipeline-data` and that the summary
   regeneration path works.
5. Exercise `reprocess-strat` with a known strategy.
6. Exercise `batch-config` with a small fixture.
7. Exercise `batch-jql` manually, then validate the scheduled source and
   `resource_group` behavior.
8. Exercise the dashboard trigger and record whether the placeholder project
   is sufficient.

Capture runner logs, pipeline/job IDs, source commit IDs, Jira issue keys,
result-repository commit IDs, and any emulator gaps in the change ledger.

## Reviewable milestones

Each milestone is an intentional pause point. The next milestone should not
run automatically until the outputs below have been reviewed.

| Milestone | Delivered outcome | Review point |
|---|---|---|
| M0 — Source contract | Relative source symlink, source manifest, baseline/dirty-state preflight, and fixture README | Confirm the private checkout boundary and provenance policy |
| M1 — Repository topology | Platform runner is registered and online; GitHub mirrors plus nested GitLab pipeline/data/dashboard projects exist and are reachable; no CI pipeline run yet | Review runner identity/tags, paths, default branches, source commits, and project visibility |
| M2 — Credentials | Jira bot/PAT, GitLab push/trigger credential, CI variables, and CA/trust configuration are installed and verified | Review secret names/scopes and ensure no raw secret entered Git or logs |
| M3 — Pipeline wiring | Localized `.gitlab-ci.yml` and helper scripts are pushed; all four jobs and the scheduled job contract are accepted by the emulator | Review every environment-specific diff and upstream-candidate classification |
| M4 — Focused execution | One seeded `single-rfe` run completes through create, refine, review, unlock, and artifact/result publication | Review Jira labels, generated artifacts, result commit, and runner logs |
| M5 — Broader validation | `reprocess-strat`, `batch-config`, `batch-jql`, and dashboard-trigger behavior are individually exercised | Review remaining emulator gaps and decide whether to upstream generic fixes |

The bootstrap workflow should support stopping after M0, M1, M2, or M3 through
an explicit variable or separate workflow entrypoint. M4 and M5 are execution
validation and should remain separate from the setup-only bootstrap path.

## Expected compatibility changes to track

| Area | Expected change | Upstream candidate |
|---|---|---|
| Service URLs | Remove hard-coded public GitHub/GitLab/Jira endpoints | Yes: generic configuration |
| Results repo auth | Accept configurable GitLab host and full repository URL | Yes |
| CI variables | Add explicit `JIRA_USER`; map emulator secrets to existing names | Mostly environment-specific |
| Dashboard trigger | Configurable downstream project and optional placeholder behavior | Generic if implemented cleanly |
| TLS | Trust the emulator CA inside CI jobs | Environment-specific unless generalized |
| Credentials | Jira bot and GitLab push/trigger secrets | Environment-specific |
| Setup | Idempotent mirror/project/credential bootstrap | Breadboard-specific orchestration |

## Completion criteria

- All three local GitLab projects and both local GitHub mirrors are reachable
  from the in-cluster runner.
- `glemu-k8s-runner` can accept a tagged job in the `gitlab-runner` namespace
  after a clean platform reset.
- The Jira bot authenticates and performs the pipeline’s required operations.
- `single-rfe` completes successfully against emulator data.
- All four pipeline job definitions are present and manually/scheduled
  invocable, with focused tests recorded for each.
- Results can be committed to the local data project.
- Every local source change has a provenance entry and an upstream-candidate
  disposition.
