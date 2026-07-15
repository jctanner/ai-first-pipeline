# Dashboard Strategy Architecture-Context Test

This directory-based Markov workflow first clears the shared pipeline volumes
and resets Jira. It then clones architecture context directly from its upstream
GitHub repository into the shared context PVC. Strategy skills are also loaded
directly from their upstream GitHub repository. The workflow imports the
captured Jira issue twice, as `RHAIRFE-2259` and `RHAIRFE-2260`.
Both imports add the `strat-creator-3.6` pipeline-targeting label required by
the strategy skill selector.

The baseline ticket runs `strategy-create`, `strategy-refine`, and
`strategy-review` against the unmodified architecture context. The workflow
then writes the overlay extracted from `files/42.diff` into the shared
architecture-context checkout and runs the same three phases for the second
ticket. The workflow produces the paired Jira and job artifacts but does not
judge their content or tone.

The strategy bootstrap script resolves architecture context as
`.context/architecture-context`. FQN jobs symlink the skill checkout's
`.context` directory to the shared `/app/.context` PVC mount, making the
effective agent path `/app/.context/architecture-context`. The context setup
job mounts that same PVC at `/context`, so its
`/context/architecture-context` checkout and overlay writes are visible at the
path consumed by the strategy skills.

## Prerequisites

- Jira emulator and pipeline dashboard are running.
- `gcp-credentials` exists in the `ai-pipeline` namespace.
- `pipeline-agent:latest` is loaded into the cluster image store.

## Run

```bash
markov validate var/demos/dashboard-strat-arch-context-test/
markov run var/demos/dashboard-strat-arch-context-test/
```

Override the model or skill source when needed:

```bash
markov run var/demos/dashboard-strat-arch-context-test/ \
  --var skill_model=claude-sonnet-4-6
```

The original Jira export remains in `files/RHAIRFE-2259.json`. The extracted
overlay is `files/0018-catalog-admin-uis-in-model-registry.md`, with
`files/42.diff` retained as its provenance.
