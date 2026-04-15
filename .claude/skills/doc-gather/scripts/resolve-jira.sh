#!/usr/bin/env bash
# Resolve a Jira ticket via MCP Atlassian tools and emit structured JSON.
#
# This script is a reference wrapper that documents the MCP call pattern.
# In practice, skills invoke MCP tools directly. This script serves as
# documentation and as a fallback for non-MCP environments.
#
# Usage:
#   bash resolve-jira.sh RHOAIENG-55490
#
# Output (JSON to stdout):
# {
#   "key": "RHOAIENG-55490",
#   "summary": "...",
#   "description": "...",
#   "acceptance_criteria": "...",
#   "fix_versions": ["rhoai-2.18"],
#   "components": ["Dashboard", "Model Serving"],
#   "linked_tickets": ["RHOAIENG-12345"],
#   "epic_key": "RHOAIENG-55000",
#   "status": "In Progress",
#   "issue_type": "Story"
# }
#
# MCP tool used: mcp__mcp-atlassian__jira_get_issue
#
# When running inside Claude Code, the skill should call the MCP tool directly:
#   mcp__mcp-atlassian__jira_get_issue(issue_key="RHOAIENG-55490")
#
# The skill then extracts from the MCP response:
#   - summary (fields.summary)
#   - description (fields.description)
#   - acceptance criteria (fields.customfield_* or from description)
#   - fixVersions (fields.fixVersions[].name)
#   - components (fields.components[].name)
#   - issuelinks (fields.issuelinks[].outwardIssue.key / inwardIssue.key)
#   - epic link (fields.customfield_10014 or parent.key for next-gen projects)
#   - status (fields.status.name)
#   - issuetype (fields.issuetype.name)

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load .env if available (credentials, JIRA_URL, etc.)
source "${SCRIPTS_DIR}/load-env.sh"

TICKET_KEY="${1:?Usage: resolve-jira.sh <JIRA-KEY>}"

# When MCP is not available, attempt to use the Jira REST API directly.
# Requires JIRA_URL, JIRA_EMAIL, JIRA_TOKEN environment variables.
JIRA_URL="${JIRA_URL:-https://issues.redhat.com}"

if [[ -z "${JIRA_EMAIL:-}" ]] || [[ -z "${JIRA_TOKEN:-}" ]]; then
    echo "Error: JIRA_EMAIL and JIRA_TOKEN must be set for REST API access." >&2
    echo "When running inside Claude Code, use MCP tools instead." >&2
    exit 1
fi

# Fetch the issue
RESPONSE=$(curl -s -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
    -H "Content-Type: application/json" \
    "${JIRA_URL}/rest/api/2/issue/${TICKET_KEY}?fields=summary,description,fixVersions,components,issuelinks,status,issuetype,parent")

if echo "$RESPONSE" | jq -e '.errorMessages' >/dev/null 2>&1; then
    echo "Error fetching ticket ${TICKET_KEY}:" >&2
    echo "$RESPONSE" | jq -r '.errorMessages[]' >&2
    exit 1
fi

# Extract fields into structured JSON
echo "$RESPONSE" | jq '{
    key: .key,
    summary: .fields.summary,
    description: (.fields.description // ""),
    acceptance_criteria: "",
    fix_versions: [.fields.fixVersions[]?.name],
    components: [.fields.components[]?.name],
    linked_tickets: [.fields.issuelinks[]? | (.outwardIssue.key // .inwardIssue.key) | select(. != null)],
    epic_key: (.fields.parent.key // ""),
    status: .fields.status.name,
    issue_type: .fields.issuetype.name
}'
