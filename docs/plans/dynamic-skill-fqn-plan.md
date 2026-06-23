# Dynamic Skill Resolution via URI-Style FQNs

## Context

Skills are currently defined in `var/pipeline-skills.yaml` and must be pre-registered before they can be run from the Jobs UI. The FQN format (`owner/repo@ref:skill`) has no hostname component, implicitly assuming github.com. We need to support running skills from both github.com and github.local (anonymous read) without pre-registration in the YAML.

**Goal**: Allow the Jobs UI to accept an arbitrary URI-style FQN like `github.local/org/repo@branch:skill-name`, have the K8s orchestrator pass it through to the agent container, and have the entrypoint script clone the repo and run the skill -- all without touching `pipeline-skills.yaml`.

## FQN Format

New canonical format: `host/owner/repo@ref:skill-name`

Examples:
- `github.com/jwforres/rfe-creator@main:rfe.create` (explicit github.com)
- `github.local/myorg/my-skills@develop:my-skill` (internal forge)
- `local:bug-completeness` (unchanged for local skills)

Pre-registered skills in `pipeline-skills.yaml` continue to work by their phase key (e.g. `rfe-create`). The FQN is the new **alternative** path for ad-hoc/unregistered skills.

## Changes

### 1. FQN Parser (`src/cli/skill_config.py`)

Add a `parse_fqn(fqn: str) -> dict` function:

```python
def parse_fqn(fqn: str) -> dict | None:
    """Parse a URI-style FQN into components.
    
    Format: host/owner/repo@ref:skill-name
    Returns: {host, owner, repo, ref, skill} or None if not a valid FQN.
    """
```

Returns `None` for plain phase keys (e.g. `rfe-create`) so callers can distinguish registered skills from ad-hoc FQNs.

Update `get_skill_fqn()` to include the host. Add a `host` field to `skill_repos` entries in the YAML (defaulting to `github.com` when omitted) so existing registered skills also get proper multi-forge FQNs. Update `list_skills()` display format to include host.

### 2. K8s Orchestrator (`src/dashboard/k8s_orchestrator.py`)

In `submit_phase_job` and `_create_job_manifest`:
- Accept an optional `fqn` parameter alongside `phase`
- If `fqn` is provided, pass it to the container via a new `--fqn` arg (instead of `--skill`)
- Store the FQN in a K8s label/annotation for display in the jobs table
- Use the FQN as `MLFLOW_EXPERIMENT_NAME` when present

### 3. Flask API (`src/dashboard/webapp.py`)

In `api_submit_job`:
- Accept either `command` (existing phase key) or `fqn` (new URI-style FQN) in the POST body
- If `fqn` is provided, validate it parses correctly via `parse_fqn()`, then pass it to the orchestrator
- If `command` is a valid FQN (contains `/` and `:`), treat it as an FQN rather than a phase key

### 4. Jobs UI (`templates/jobs.html` + `static/js/jobs.js`)

- Add a text input field for free-text FQN entry alongside the existing dropdown
- Toggle: when the user types in the FQN field, disable the dropdown (and vice versa)
- The FQN input should have placeholder text like `github.local/org/repo@branch:skill-name`
- On submit, send `fqn` if the text field is populated, otherwise send `command` from dropdown
- Display the FQN in the jobs table skill column (already handled by `SKILL_MAP` fallback to `job.phase`)

### 5. Entrypoint Scripts (`scripts/run_skill.sh` + `scripts/run_skill_sdk.sh`)

Add a new `--fqn` argument. When present, the script:

1. Parses the FQN to extract `host`, `owner`, `repo`, `ref`, `skill_name`
2. Clones the repo via `git clone --depth 1 -b $ref https://$host/$owner/$repo.git` into a temp directory (e.g. `/tmp/skills/$owner-$repo`)
3. Sets up artifact symlinks (same pattern as existing plugin setup)
4. Sets the working directory to the cloned repo
5. Invokes the skill as `/$skill_name --headless ...`

When `--fqn` is NOT present, the existing `--skill` flow is unchanged.

Key detail: the clone uses HTTPS with no auth, which works for github.local anonymous read. For github.com public repos it also works. The existing `git config --global url."https://github.com/".insteadOf` line should be scoped or extended to also cover github.local.

Shared logic between the two scripts (FQN parsing, clone, symlink setup) should be extracted into a helper script like `scripts/resolve_fqn.sh` that both entrypoints source.

### 6. pipeline-skills.yaml Schema Update

Add optional `host` field to `skill_repos` entries:

```yaml
skill_repos:
  rfe-creator:
    host: github.com          # new, defaults to github.com if omitted
    github: jwforres/rfe-creator
    ref: main
    path: remote_skills/rfe-creator
    registry: rfe-creator@opendatahub-skills
```

This is backward-compatible -- existing entries without `host` default to `github.com`.

## File Summary

| File | Change |
|------|--------|
| `src/cli/skill_config.py` | Add `parse_fqn()`, add `host` support to FQN construction, update `list_skills()` display |
| `src/dashboard/k8s_orchestrator.py` | Accept `fqn` param, pass `--fqn` arg to container, store in labels |
| `src/dashboard/webapp.py` | Accept `fqn` in POST body, validate, route to orchestrator |
| `src/dashboard/templates/jobs.html` | Add FQN text input with toggle behavior |
| `src/dashboard/static/js/jobs.js` | Send `fqn` or `command`, toggle logic |
| `scripts/resolve_fqn.sh` | New helper: parse FQN, clone repo, set up symlinks |
| `scripts/run_skill.sh` | Add `--fqn` arg, source `resolve_fqn.sh` for clone path |
| `scripts/run_skill_sdk.sh` | Add `--fqn` arg, source `resolve_fqn.sh` for clone path |
| `var/pipeline-skills.yaml` | Add `host` field to existing `skill_repos` entries |

## Verification

1. **Unit**: Parse various FQN formats in `parse_fqn()` -- valid multi-forge, local, edge cases (missing ref, missing skill)
2. **UI**: Load jobs page, verify dropdown still works, type a FQN in the text field and confirm the dropdown disables
3. **Integration** (requires K8s cluster): Submit a job with a github.local FQN, verify the pod clones the repo and runs the skill
4. **Backward compat**: Submit a job via the dropdown (registered skill), verify the existing flow is untouched
