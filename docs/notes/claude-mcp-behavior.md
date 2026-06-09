# Claude CLI --print Mode MCP Connection Behavior

## Problem Summary

When using `claude --print` in non-interactive/batch mode, **MCP servers are configured correctly but tools are not available** to the agent during execution. This causes skills that depend on MCP tools (like Atlassian Jira integration) to fall back to manual workarounds even though the MCP server is accessible.

## Affected Skills

All skills using `runner: cli` with `mcp_servers` configured in `pipeline-skills.yaml`:

- ✅ **rfe-review** - Falls back to REST API (has `scripts/fetch_issue.py`)
- ✅ **rfe-split** - Falls back to REST API
- ✅ **rfe-speedrun** - Falls back to REST API
- ❌ **strat-create** - Falls back to manual guide (no REST API for clone operation)
- ❌ **strat-submit** - Falls back to manual operations
- ❌ **strat-security-review** - Degraded functionality

**NOT affected:**
- Local skills in `.claude/skills/` - use Python SDK runner which properly initializes MCP
- Skills without MCP dependencies

## Evidence

### 1. Configuration is Correct

MCP server is properly configured in `~/.claude/settings.json`:

```json
{
  "apiProvider": "vertex",
  "vertexProjectId": "itpc-gcp-ai-eng-claude",
  "vertexRegion": "us-east5",
  "mcpServers": {
    "atlassian": {
      "type": "sse",
      "url": "http://jira-emulator.ai-pipeline.svc.cluster.local:8081/sse"
    }
  }
}
```

Setup script confirms:
```
✓ Atlassian MCP server configured
✓ Vertex AI settings merged
```

### 2. MCP Endpoint is Accessible

Direct connectivity test from pod:
```bash
$ curl http://jira-emulator.ai-pipeline.svc.cluster.local:8081/sse
event: endpoint
data: /messages/?session_id=9322a0ab09d244619f3ebc1ff7669d38
```

### 3. Tools Are Not Available During Agent Execution

Test job output (2026-04-17):
```bash
$ claude --model haiku --print "List all tools that start with 'mcp__'"
NO

I don't see any tools that start with 'mcp__' in the available tools.

$ claude --model haiku --print "Use mcp__atlassian__getJiraIssue..."
MCP tool not found.
```

Agent's thinking log from strat-create job:
```
I don't have MCP tools available, but I do have the Jira credentials set up.
The skill instructions say if MCP isn't available, I should write a guide
instead of attempting manual API calls.
```

## Root Cause: Lazy MCP Connection in --print Mode

From `claude-code/src/cli/print.ts` source code:

```typescript
// Lazy lookup: MCP connects are per-server incremental in print mode, so
// the tool may not be in the appState yet at init time. Resolve on first call
// (first permission prompt), by which point connects have had time to finish.
```

**Timeline of events:**

1. `claude --print` starts
2. Agent begins execution immediately
3. MCP server connection starts in background (lazy/async)
4. Agent checks available tools during thinking phase
5. MCP tools not yet in tool list → agent says "not available"
6. Agent falls back to manual mode
7. MCP connection eventually completes (too late)

**The race condition:**

```
Agent thinking:     [============]
                    ↑
                    checks for mcp__ tools → NOT FOUND
MCP connection:              [=========ready]
                                      ↑
                                      tools available (too late)
```

The comment in Claude Code source indicates MCP tools become available "on first call (first permission prompt)" - but skills check for tool availability during their initial thinking phase, BEFORE any tool is actually invoked.

## Why strat.create Has No REST API Fallback

**Issue cloning is NOT available via Jira REST API.** The clone operation is a UI-only feature:

- ❌ Can't use POST `/rest/api/3/issue` - would lose original metadata
- ❌ Can't create "Cloners" link type properly via REST
- ❌ Manual recreation is error-prone and complex

The **Atlassian MCP server can clone** because it can drive the Jira UI programmatically. The skill's fallback to a manual guide is by design when MCP is unavailable.

## Comparison: CLI Runner vs SDK Runner

| Aspect | CLI Runner (`--print`) | SDK Runner (Python) |
|--------|------------------------|---------------------|
| MCP initialization | Lazy/async in background | Synchronous before agent starts |
| Tool availability | Not guaranteed at agent start | Guaranteed when agent starts |
| Used by | K8s jobs (`run_skill.sh`) | Local skills (`.claude/skills/`) |
| Configuration | `~/.claude/settings.json` | Passed via SDK parameters |
| Affected skills | rfe-*, strat-* from marketplace | Local bug/doc skills |

## Solutions

### Option 1: MCP Warmup (Quick Fix)

Add warmup step to `scripts/run_skill.sh` before skill invocation:

```bash
# Warm up MCP connection before running skill
echo "Warming up MCP connection..."
claude --model haiku --print "test connection" >/dev/null 2>&1 || true
sleep 2
```

**Pros:** Simple, minimal code change  
**Cons:** Hacky, adds latency, not guaranteed to work

### Option 2: Switch to SDK Runner (Proper Fix)

Change `pipeline-skills.yaml` to use SDK runner for MCP-dependent skills:

```yaml
strat-create:
  skill: strat.create
  source: rfe-creator
  invoke: native
  runner: sdk  # Changed from 'cli'
  allowed_tools: [Read, Write, Edit, Glob, Grep, Bash]
  mcp_servers: [atlassian]
```

**Pros:** Proper MCP initialization, proven to work  
**Cons:** Requires updating agent_runner.py to support SDK runner with marketplace skills

### Option 3: Retry Logic in Skills (Defensive)

Modify skills to retry MCP tool discovery:

```python
# In skill prompt
attempts = 0
while attempts < 3:
    if mcp tools available:
        use them
        break
    sleep(1)
    attempts += 1
else:
    fall back to manual
```

**Pros:** Self-healing, no infrastructure changes  
**Cons:** Adds complexity to skill logic, increases execution time

### Option 4: File Upstream Bug

Report to Anthropic that `claude --print` should wait for configured MCP servers before starting agent execution.

**Pros:** Proper fix in Claude Code itself  
**Cons:** Unknown timeline, may not align with `--print` design goals

## Current Status (2026-04-17)

- **Diagnosis:** Complete - root cause identified and confirmed
- **Workaround:** Using manual guides when MCP operations needed
- **Fix:** Pending - need to choose option 1, 2, or 3
- **Impact:** strat-create cannot auto-clone to RHAISTRAT project

## Related Files

- `scripts/run_skill.sh` - Job execution wrapper using `--print` mode
- `lib/agent_runner.py` - Python SDK runner (works correctly with MCP)
- `pipeline-skills.yaml` - Skill configuration including MCP server mappings
- `deploy/repos/claude-code/src/cli/print.ts` - Claude Code source showing lazy MCP connection
- `deploy/repos/rfe-creator/.claude/skills/strat.create/SKILL.md` - Explicitly documents MCP fallback behavior

## Test Case

To reproduce:

```bash
# In K8s pod with pipeline-agent:latest image
python3 -c "
import json
import os
os.makedirs(os.path.expanduser('~/.claude'), exist_ok=True)
with open(os.path.expanduser('~/.claude/settings.json'), 'w') as f:
    json.dump({
        'apiProvider': 'vertex',
        'mcpServers': {
            'atlassian': {
                'type': 'sse',
                'url': 'http://jira-emulator.ai-pipeline.svc.cluster.local:8081/sse'
            }
        }
    }, f)
"

# Test MCP tool availability
claude --model haiku --print "List all tools starting with mcp__"
# Expected: "NO" or empty list
# Actual behavior: MCP tools not visible

# Verify settings
cat ~/.claude/settings.json
# Expected: mcpServers configured correctly
```

## Recommendations

1. **Short term:** Add MCP warmup to run_skill.sh (Option 1)
2. **Medium term:** Switch strat-* skills to SDK runner (Option 2)
3. **Long term:** File upstream bug with Anthropic (Option 4)
