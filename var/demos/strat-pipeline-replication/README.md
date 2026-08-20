# Strat-pipeline emulator fixture

This fixture bootstraps the private `strat-pipeline` checkout into the local
GitLab emulator. It deliberately does not contain a copy of the private source.
The tracked `strat-pipeline` symlink points to the separately restored checkout
under `deploy/repos.third-party/`.

## M0: source contract

From the repository root, run:

```bash
python3 var/demos/strat-pipeline-replication/scripts/preflight.py
```

The preflight verifies:

- the source symlink exists and resolves to a Git checkout;
- the checkout has the expected private `origin` and `main` branch;
- the current commit and dirty state are reported as JSON;
- local changes are rejected unless explicitly reviewed with
  `--allow-dirty`.

The recorded baseline is in `source-manifest.json`. A changed commit is a
warning because it may represent an intentional local change; it must be
recorded in the plan's change ledger before later bootstrap milestones.

## Source recovery boundary

The private checkout is an explicit prerequisite. A service-data wipe leaves it
in place, but a full workspace wipe requires restoring it separately. The
fixture does not contain or request credentials for the private GitLab origin.

The later bootstrap will clone/push from this local checkout into the GitLab
emulator without changing its private `origin`. It will then apply any tracked
environment-compatibility patches before the mirror is used by CI.

## M1: repository topology

After the emulators are running, set the GitHub emulator admin token and run:

```bash
export GITHUB_API_TOKEN=<set-me>
python3 var/demos/strat-pipeline-replication/scripts/bootstrap_topology.py
```

The bootstrap is idempotent. It creates the `opendatahub-io` GitHub mirrors,
the nested GitLab groups, and the three private GitLab projects; it then pushes
the local `main` branches for all four source checkouts to their matching
mirrors. The GitLab emulator's
local `admin:admin` credentials are used only for this topology step unless
overridden with `GITLAB_USER` and `GITLAB_ADMIN_PASSWORD`.

It writes the non-secret result to `topology-manifest.json`. Review that file
before proceeding to M2; this milestone does not create CI variables, Jira
users, or run a pipeline.

The GitLab Runner is a platform prerequisite. A fresh stack install creates it
through `deploy/scripts/15-deploy-gitlab-runner.sh`; `deploy/scripts/clean-all.sh`
also re-registers it after wiping emulator data. Before M4, verify that
`glemu-k8s-runner` is online and has the `aipcc-small-x86_64` tag.

## M2: credentials and access

With the M1 topology present, run:

```bash
python3 var/demos/strat-pipeline-replication/scripts/bootstrap_credentials.py
```

This creates or reuses the Jira bot and its PAT, creates or reuses the GitLab
results-push PAT, and stores them as masked project variables on
`strat-pipeline`. It also stores the same GitLab PAT as masked
`DATA_REPO_TOKEN` on `strat-dashboard`, installs the dashboard endpoint
variables, and copies available GCP inputs into pipeline CI variables when the
platform secrets are available. The report in `credentials-manifest.json`
contains metadata only; raw credentials are never printed or written to the
fixture.

## M3: pipeline wiring

Apply the tracked environment transformation and publish the adapted pipeline
mirror while retaining upstream-safe defaults:

```bash
python3 var/demos/strat-pipeline-replication/scripts/apply_m3_patch.py
python3 var/demos/strat-pipeline-replication/scripts/validate_m3.py
```

The publisher never edits the source checkouts. It clones them temporarily,
applies the tracked transformations under `patches/`, commits the adapted
files, and force-updates the matching emulator project's `main` branch. The
dashboard Pages job uses the local GitHub/GitLab endpoints and its masked data
token only when the emulator project variables are present; shell fallbacks
preserve public GitHub/GitLab behavior for ordinary upstream use.
`NO_SSL_VERIFY=1` is only a project-level emulator override. The pipeline
stages and four strategy job types are unchanged.
`pipeline-manifest.json` records the source and adapted commits, while
`m3-validation.json` records the non-secret CI-lint and project API checks.

The validation script does not run a strategy workload. It lints the manual
jobs, checks the scheduled `batch-jql` contract, verifies both public defaults
and emulator overrides, and creates then cancels a harmless direct acceptance
job.
