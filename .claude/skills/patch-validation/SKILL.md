---
name: patch-validation
description: Validate a patch using odh-tests-context recipes
allowed-tools: Read, Write, Glob, Grep, Bash
---

# Patch Validation

Validate a code patch by running lint and test commands inside a podman container, using the odh-tests-context documentation to understand what tools are available and how to run them.

## Instructions

You are a validation agent with Bash access. Your job is to:

1. Read the test context documentation to understand the project's test infrastructure
2. Run setup, lint, and test commands via `podman exec` against a running container
3. Write a structured result JSON file

### Step 1: Read the Test Context

Your prompt will include the path to a test context `.md` file. Read it carefully to understand:

- What base image is being used
- What setup commands are needed (dependency installation, build steps)
- What lint commands are available and how to run them
- What test commands are available (unit tests, integration tests)
- What tools are available (ginkgo, pytest, go test, make targets, etc.)
- Which commands are marked as `validated: true` (known working) vs `validated: false` (broken on base repo)

**Important:** The test context was written to be read by an AI agent. Use it as a guide, not a rigid script. If a command references a tool that isn't on `$PATH` (e.g., `ginkgo`), look for a Makefile target that installs it (e.g., `make ginkgo`) and run that first.

### Step 2: Run Setup

Use `podman exec {container_name} sh -c "..."` to run commands inside the container.

- Run any setup commands described in the test context (e.g., `go mod download`, `pip install -r requirements.txt`)
- If the test context mentions Makefile targets for tool installation, run them (e.g., `make ginkgo`, `make lint-setup`)
- Record whether setup succeeded

### Step 3: Run Selective Tests

Run tests scoped to the changed files/directories first for faster feedback:

- **Lint commands:** Run lint commands from the test context. Only run commands marked as `validated: true`.
- **Selective tests:** Run tests scoped to the changed directories. For Go repos, use `go test ./path/...` for each directory containing changed files. For Python repos, use `pytest path/` for each changed directory. Use the `test_single_file` template from the test context if available.

### Step 4: Run Full Test Suite (if selective passes)

If all selective tests pass, run the full test suite:

- Run the full `test_commands` from the test context
- Use a longer timeout for full suite runs (up to 20 minutes)
- Only run commands marked as `validated: true`

### Step 5: Rate the Test Context

Evaluate how helpful the odh-tests-context file was:

- `"high"` -- accurate, complete, commands worked as described
- `"medium"` -- mostly helpful but required adaptation (missing tools, wrong paths, etc.)
- `"low"` -- significant gaps, had to figure most things out from the repo itself
- `"none"` -- no useful information, or no test context file exists

Include a brief explanation of what worked and what didn't.

### Step 6: Write Result JSON

Write the result JSON to the path specified in your prompt. The schema is:

```json
{
  "overall_passed": true,
  "lint_passed": true,
  "selective_tests_passed": true,
  "full_tests_passed": true,
  "setup_success": true,
  "test_context_helpfulness": {
    "rating": "high",
    "explanation": "All commands worked as described, ginkgo was installed via make target as documented"
  },
  "commands_run": [
    {
      "command": "podman exec container-name sh -c 'go mod download'",
      "category": "setup",
      "exit_code": 0,
      "passed": true,
      "output_summary": "Downloaded 47 modules"
    },
    {
      "command": "podman exec container-name sh -c 'make lint'",
      "category": "lint",
      "exit_code": 0,
      "passed": true,
      "output_summary": "No lint errors found"
    }
  ],
  "summary": "All lint and test commands passed. Setup required running 'make ginkgo' first."
}
```

Field definitions:

- `overall_passed`: boolean -- true if all stages passed (setup + lint + selective tests + full tests if run)
- `lint_passed`: boolean -- true if all lint commands passed
- `selective_tests_passed`: boolean -- true if selective/scoped tests passed
- `full_tests_passed`: boolean or null -- true if full suite passed, null if not run
- `setup_success`: boolean -- true if container setup completed successfully
- `test_context_helpfulness`: object with `rating` (high/medium/low/none) and `explanation` string
- `commands_run`: array of command result objects:
  - `command`: the full command string that was executed
  - `category`: one of `"setup"`, `"lint"`, `"selective-test"`, `"full-test"`
  - `exit_code`: integer exit code
  - `passed`: boolean
  - `output_summary`: brief summary of the output (not the full output -- keep it concise)
  - `failure_type` (optional, for failed commands only): classify the failure as one of `"lint-violation"`, `"compilation-error"`, `"test-assertion-failure"`, `"test-runtime-error"`, `"timeout"`, `"setup-failure"`, `"unknown"`
- `summary`: human-readable summary of the overall validation result

### Important Rules

- Always use `podman exec {container_name} sh -c "..."` to run commands inside the container
- The container has the workspace mounted at `/app`
- Do not modify source files -- you are only validating, not fixing
- If a command times out or hangs, kill it and record it as failed
- If setup fails, skip lint and tests but still write the result JSON
- Keep `output_summary` concise (a few lines max) -- summarize rather than dumping full output
- If no test context file exists, rate helpfulness as `"none"` and attempt to discover test commands from the repo itself (look for Makefile, go.mod, pytest.ini, etc.)
