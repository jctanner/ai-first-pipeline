# Claude CLI Migration

**Date:** 2026-04-16  
**Status:** ✅ Complete

## Summary

Migrated from Python-based harness (`main.py`) to direct Claude CLI execution for running skills in Kubernetes Jobs. This eliminates complexity around volume mounting, permissions, and skill distribution.

## Old Approach (Python Harness)

```python
# Job command
python -u main.py rfe-review --issue RHAIRFE-953 --model opus

# Required infrastructure:
- Init container to clone rfe-creator repo
- EmptyDir volume for remote_skills
- PVC for rfe-creator/artifacts
- Symlink artifacts → /rfe-artifacts
- chown -R 1000:1000 for permissions
- Read-write mount for .mcp.json creation
```

**Problems:**
- ❌ Complex init container setup
- ❌ Permission issues (root clone vs pipelineagent user)
- ❌ Read-only vs read-write mount confusion
- ❌ Python buffering hid all output
- ❌ Symlink complexity for artifacts
- ❌ Tight coupling to repo structure

## New Approach (Claude CLI)

```bash
# Job command
/bin/bash /app/scripts/run_skill.sh --skill rfe.review --issue RHAIRFE-953 --model opus

# Script does:
1. claude plugin marketplace add opendatahub-io/skills-registry
2. claude plugin install rfe-creator@opendatahub-skills
3. export CLAUDE_ENABLE_MLFLOW_TRACING=1
4. claude -p "/rfe.review --issue RHAIRFE-953 --model opus"
```

**Benefits:**
- ✅ No init containers needed
- ✅ No volume mounts for skills
- ✅ Skills installed via registry (canonical source)
- ✅ Direct output (no Python buffering)
- ✅ MLflow tracing enabled by default
- ✅ Simpler job manifests
- ✅ Claude CLI handles MCP server setup

## Files Changed

### New Files
- `scripts/run_skill.sh` - Wrapper script for Claude CLI execution

### Modified Files
- `lib/k8s_orchestrator.py`:
  - Changed command from `python main.py` → `/bin/bash /app/scripts/run_skill.sh`
  - Removed `--component`, `--triage`, `--recommendation`, `--validation-retries`, `--skip-validation` args (not needed for skills)
  - Removed init container for cloning rfe-creator
  - Removed `remote-skills` emptyDir volume
  - Removed `rfe-artifacts` PVC volume
  - Removed volume mounts for both

- `deploy/k8s/20-pipeline-dashboard.yaml`:
  - Removed clone-skills init container
  - Removed remote-skills and rfe-artifacts volume mounts
  - Removed remote-skills and rfe-artifacts volume definitions

### Removed Infrastructure
- Init container: `clone-skills`
- Volume: `remote-skills` (emptyDir)
- Volume: `rfe-artifacts` (PVC reference)
- PVC: `pipeline-remote-skills` (can be deleted)

## Environment Variables

Jobs still receive:
- `MLFLOW_TRACKING_URI=http://mlflow.ai-pipeline.svc.cluster.local:5000`
- `CLAUDE_CODE_USE_VERTEX=1`
- `CLOUD_ML_REGION=us-east5`
- `ANTHROPIC_VERTEX_PROJECT_ID=<project>`
- `JIRA_SERVER`, `JIRA_USER`, `JIRA_TOKEN`
- `GOOGLE_APPLICATION_CREDENTIALS=/app/.gcloud/credentials.json`

Plus new:
- `CLAUDE_ENABLE_MLFLOW_TRACING=1` (set in run_skill.sh)

## Skills Registry Integration

Skills are now installed from the opendatahub-io/skills-registry marketplace:

```bash
claude plugin marketplace add opendatahub-io/skills-registry
claude plugin install rfe-creator@opendatahub-skills
```

This provides:
- Versioned skill distribution
- Canonical skill source
- Automatic dependency management
- Cleaner separation of concerns

## Testing

To test a job:

```bash
# Via Jobs UI
http://dashboard.local/jobs
# Select phase: rfe-review
# Enter issue: RHAIRFE-953  
# Select model: opus
# Submit

# Watch logs
kubectl logs -f -n ai-pipeline <job-pod-name>
```

Expected output:
```
============================================================
Running skill: rfe.review
Issue: RHAIRFE-953
Model: opus
============================================================

Installing skills from opendatahub-io/skills-registry...
✓ MLflow server is accessible

Running skill...

[Claude CLI output with skill execution]

============================================================
Skill execution complete
============================================================
```

## Migration Notes

The Python harness (`main.py`, `lib/phases.py`) is still used for:
- Local development: `python main.py bug-completeness --issue RHOAIENG-123`
- Dashboard server: `python main.py dashboard`
- Batch operations: `python main.py bug-all`

K8s Jobs now bypass the Python harness entirely and invoke skills directly via Claude CLI.

## Cleanup

After verifying jobs work correctly, can delete:
```bash
kubectl delete pvc -n ai-pipeline pipeline-remote-skills
```

This PVC was used for rfe-creator artifacts but is no longer needed with the new approach.
