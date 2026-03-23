---
name: bug-test-plan
description: Generate a comprehensive test plan for a bug
allowed-tools: Read, Write, Glob, Grep
---

# Bug Test Plan Generation

Generate a comprehensive, ecosystem-aware test plan for a Jira bug in the RHOAI/ODH ecosystem. The test plan must specify the correct test layer, target repository, framework, and patterns for each component involved.

## Instructions

### Decision Tree: What Test Do I Write?

Walk through this decision tree for each aspect of the bug fix:

```
1. Is the fix pure business logic with no Kubernetes/cluster dependency?
   -> Write a UNIT TEST in the same package as the code changed.

2. Does the fix involve webhook validation, CEL rules, CRD conversion,
   or controller reconciliation logic that can be verified against a
   simulated API server?
   -> Write an INTEGRATION TEST using envtest, in the same repo.

3. Does the fix involve behavior that can only be verified against a
   real running cluster (operator deployment lifecycle, cross-component
   interactions, real network behavior)?
   -> Write an E2E TEST in the same repo's tests/e2e/ directory.

4. Does the fix involve UI behavior visible in the RHOAI dashboard?
   -> Write a CYPRESS TEST in the odh-dashboard repo.

5. Does the fix involve product-level behavior that should be validated
   at the QE layer (model serving, model registry, workbenches,
   explainability, cluster health)?
   -> Write a PYTEST TEST in the opendatahub-tests repo.
   This is the PRIMARY cross-repo test repository. ods-ci (Robot
   Framework) is deprecated — all new QE tests go in opendatahub-tests.
```

**Bias toward unit and integration tests.** They run in seconds, have zero infrastructure flake, and are the most valuable per line of code. Only propose an e2e test if the behavior genuinely cannot be verified at a lower level.

### Per-Repository Test Guide

#### opendatahub-operator / rhods-operator (Go)

Test coverage follows a layered priority:

```
Level 1: Unit tests        — ALWAYS required. Every fix gets a unit test.
Level 2: E2E tests         — WHEN the fix affects cluster-level behavior.
Level 3: opendatahub-tests — WHEN the fix affects product-level QE validation.
```

**Unit tests** (always required):
- Location: Same package as the code, `*_test.go` file
- Framework: Go standard testing + Gomega assertions
- Pattern: table-driven tests with `NewWithT(t)`
- Run: `make unit-test`

```go
func TestMyFix(t *testing.T) {
    g := NewWithT(t)
    result := functionUnderTest(input)
    g.Expect(result).Should(Equal(expected))
}
```

Integration tests using envtest (webhook, CEL, controller reconciliation) also run as part of `make unit-test`:
- Location: `internal/controller/components/*/`, `internal/webhook/*/`
- Framework: Ginkgo v2 + Gomega + envtest
- Uses existing `suite_test.go` — DO NOT create a new suite

**E2E tests** (when fix affects cluster behavior):
- Location: `tests/e2e/`
- Framework: Ginkgo v2 + Gomega against a real OpenShift cluster
- Run: `make e2e-test`
- DO NOT add e2e tests for logic that can be tested with envtest

#### odh-dashboard (TypeScript/React)

**Unit tests**:
- Location: Co-located with components, `__tests__/` directories
- Framework: Jest + React Testing Library
- Run: Check `package.json` scripts

**Cypress e2e tests** (UI behavior):
- Location: In the odh-dashboard repo, under the cypress test directory
- Framework: Cypress
- Files: `*.cy.ts`
- Pattern: page object model with custom commands

#### kubeflow / notebook controllers (Go)

- Unit tests: standard Go tests, same package
- Integration tests: GitHub Actions workflows
- Follow the same Ginkgo/Gomega patterns as the operator

#### kserve (Go)

- Unit tests: standard Go tests in each package
- E2E tests: in the repo's test directory
- Framework: Ginkgo/Gomega

#### data-science-pipelines (Go/Python)

- Has GitHub Actions workflows for CI
- Some components use pytest
- Check `Makefile` and `.github/workflows/` for test targets

#### model-registry (Go/Python)

- Unit tests in each package
- Shift-left tests exist in opendatahub-tests
- Check existing test patterns in the repo

#### Other component repos

1. Check the `Makefile` for test targets (`make test`, `make unit-test`, etc.)
2. Look at `.github/workflows/` for CI test definitions
3. Find existing `*_test.go` or `test_*.py` files and match their patterns
4. Check for a `CONTRIBUTING.md` or `CLAUDE.md` that describes test expectations

### opendatahub-tests (PyTest) — The QE Test Repository

This is the **primary cross-repo test repository** for RHOAI/ODH. If the bug fix involves product-level behavior that should be validated against a real cluster, propose a test here.

- Repo: `opendatahub-io/opendatahub-tests`
- Framework: PyTest 9.0+ with extensive fixture hierarchy
- Python: 3.14, managed with `uv`
- Run: `uv run pytest -m <marker> tests/`

**Test organization:**
```
tests/
├── conftest.py              # component-shared fixtures
├── cluster_health/          # node health, operator status
├── model_serving/           # largest suite (vLLM, Triton, MLServer, OpenVINO)
├── model_registry/          # REST API, catalog, RBAC
├── model_explainability/    # TrustyAI, guardrails, LM Eval
├── llama_stack/             # inference, vector IO, safety
├── workbenches/             # notebook controller
└── fixtures/                # reusable pytest plugin fixtures
```

**Available markers:** `smoke`, `sanity`, `tier1`, `tier2`, `tier3`, `model_serving`, `model_registry`, `llama_stack`, `model_explainability`, `gpu`, `multinode`, `pre_upgrade`, `post_upgrade`, `parallel`, `cluster_health`, `operator_health`

**Key rules for opendatahub-tests:**
- Type annotations mandatory (mypy strict)
- Google-format docstrings mandatory (Given-When-Then pattern)
- One aspect per test
- Use `openshift-python-wrapper` for K8s interactions — never raw subprocess calls
- Fixtures must be nouns, not verbs
- Use `indirect=True` for parametrized fixtures
- Use snapshot testing with syrupy for inference response validation
- Never duplicate utility code — check `utilities/` first
- Never create new `conftest.py` if one exists in the directory

**Test pattern example (parametrized model deployment):**
```python
@pytest.mark.parametrize(
    "model_namespace, serving_runtime, vllm_inference_service",
    [
        pytest.param(
            {"name": "granite-starter-raw"},
            {"deployment_type": KServeDeploymentType.RAW_DEPLOYMENT},
            {"gpu_count": 1, "name": "granite-starter-raw"},
            id="granite-starter-raw-single-gpu",
        ),
    ],
    indirect=True,
)
class TestGraniteStarterModel:
    @pytest.mark.smoke
    def test_granite_starter_inference(
        self,
        vllm_inference_service: Generator[InferenceService, Any, Any],
        vllm_pod_resource: Pod,
        response_snapshot: Any,
    ) -> None:
        """Test inference with OpenAI protocol.

        Given: A running vLLM inference service with Granite model.
        When: A chat completion request is sent via OpenAI protocol.
        Then: The response matches the expected snapshot.
        """
        validate_raw_openai_inference_request(
            pod_name=vllm_pod_resource.name,
            isvc=vllm_inference_service,
            response_snapshot=response_snapshot,
            chat_query=CHAT_QUERY,
        )
```

### Quick Reference: Test Commands by Repo

| Repo | Unit Tests | Integration Tests | E2E/QE Tests | Lint |
|------|-----------|------------------|--------------|------|
| opendatahub-operator | `make unit-test` | `make unit-test` | `make e2e-test` | `make lint` |
| opendatahub-tests | N/A | N/A | `uv run pytest -m smoke` | `ruff check`, `mypy` |
| odh-dashboard | Check `package.json` | N/A | Cypress | Check `package.json` |
| kubeflow | `make test` | GitHub Actions | `./run-e2e-test.sh` | Check Makefile |
| Other Go repos | `make test` or `go test ./...` | Check Makefile | Check Makefile | `make lint` |
| Other Python repos | `pytest` or `tox -e test` | Check tox.ini | N/A | `ruff check` |

### JSON Schema

Your primary output is a JSON file conforming to this schema:

```json
{
  "issue_key": "RHOAIENG-XXXXX",
  "decision_rationale": "The fix is a nil-guard in the reconciler (pure Go logic), so a unit test is the primary layer. An integration test with envtest is also warranted since it involves controller reconciliation. No e2e test needed — envtest can simulate the API server behavior.",
  "target_test_repos": [
    {
      "repo": "opendatahub-io/opendatahub-operator",
      "test_directory": "internal/controller/components/kserve/",
      "framework": "go-test-gomega",
      "run_command": "make unit-test"
    }
  ],
  "unit_tests": [
    {
      "description": "Test nil ConfigMap data handling",
      "file": "pkg/controller/reconciler_test.go",
      "setup": "Create mock client returning ConfigMap with nil Data",
      "input": "ConfigMap{Data: nil}",
      "expected": "Reconciler returns without error, no nil pointer panic",
      "edge_cases": ["Empty Data map vs nil Data", "Missing ConfigMap entirely"]
    }
  ],
  "integration_tests": [
    {
      "description": "Verify controller handles missing ConfigMap gracefully",
      "components": ["odh-model-controller", "kserve"],
      "setup": "Deploy controller without creating the expected ConfigMap",
      "steps": ["Deploy InferenceService", "Check controller logs", "Verify no crash loop"],
      "expected": "Controller logs warning but continues reconciliation",
      "api_verification": "GET /apis/serving.kserve.io/v1beta1/inferenceservices returns 200"
    }
  ],
  "regression_tests": [
    {
      "description": "Reproduce original nil pointer crash",
      "steps": ["Deploy RHOAI 3.4 with default config", "Delete the kserve-config ConfigMap", "Trigger reconciliation"],
      "before_fix": "Controller crashes with nil pointer dereference",
      "after_fix": "Controller logs warning and creates default ConfigMap"
    }
  ],
  "manual_verification_steps": [
    "Deploy RHOAI on OCP 4.16",
    "Check pod status: oc get pods -n redhat-ods-applications",
    "Verify no CrashLoopBackOff in controller pods"
  ],
  "environment_requirements": {
    "ocp_version": "4.16+",
    "rhoai_version": "3.4",
    "platform": "any",
    "special_config": "none"
  },
  "effort_estimate": "moderate",
  "qe_coverage_note": "This fix should be covered by a test in opendatahub-tests. Suggested: verify that InferenceService reconciliation succeeds when kserve-config ConfigMap is absent. Component: model_serving. Marker: tier1."
}
```

Field descriptions:

- `decision_rationale`: string explaining why these test layers were chosen, walking through the decision tree
- `target_test_repos`: array of objects specifying where tests should be added:
  - `repo`: midstream `org/repo` (e.g., `"opendatahub-io/opendatahub-operator"`)
  - `test_directory`: directory within the repo for the tests
  - `framework`: test framework (e.g., `"go-test-gomega"`, `"ginkgo-envtest"`, `"pytest"`, `"jest"`, `"cypress"`)
  - `run_command`: command to run the tests
- `unit_tests`: array of test case objects with `description`, `file`, `setup`, `input`, `expected`, `edge_cases` (string array)
- `integration_tests`: array of test case objects with `description`, `components` (string array), `setup`, `steps` (string array), `expected`, `api_verification` (optional string)
- `regression_tests`: array of test case objects with `description`, `steps` (string array), `before_fix`, `after_fix`
- `manual_verification_steps`: array of strings with step-by-step instructions
- `environment_requirements`: object with `ocp_version`, `rhoai_version`, `platform`, `special_config`
- `effort_estimate`: one of `"lightweight"`, `"moderate"`, `"heavy"`
- `qe_coverage_note`: string or null — if the fix warrants product-level QE coverage in opendatahub-tests, describe what test to write, which component directory, and which marker. Set to `null` if not applicable.

### Steps

1. **Analyze the bug and fix:**
   - Review the bug report, context map, and any available fix attempt
   - Identify which components and repos are affected
   - Walk through the decision tree to determine the correct test layer(s)
   - Document your reasoning in `decision_rationale`

2. **Identify target test repos:**
   - For each component, determine the midstream repo where tests should live
   - Identify the test directory, framework, and run command
   - If product-level QE coverage is warranted, include `opendatahub-io/opendatahub-tests`

3. **Design unit tests:**
   - Cover the specific code changes or affected code paths
   - Use the correct framework for the repo (Go tests for Go, Jest for TS, pytest for Python)
   - Include edge cases
   - Reference actual file paths from the component repo

4. **Design integration tests:**
   - Verify component interactions that cannot be caught by unit tests
   - For Go operators, prefer envtest-based integration tests over e2e tests
   - Specify the components involved and setup steps

5. **Design regression tests:**
   - Reproduce the original bug scenario
   - Document the before-fix and after-fix expected behavior
   - These should fail without the fix and pass with it

6. **Specify manual verification:**
   - List step-by-step instructions for human testers on a live cluster
   - Include specific `oc` commands, URLs, or UI steps to check

7. **Write QE coverage note (if applicable):**
   - If the fix affects user-visible product behavior, suggest an opendatahub-tests test
   - Specify component directory, marker, and test description
   - Follow opendatahub-tests conventions (Given-When-Then docstrings, type annotations, etc.)

### Common Mistakes to Avoid

1. **Don't put tests in the wrong repo.** Unit and integration tests go in the component repo. Product-level QE tests go in opendatahub-tests.
2. **Don't write Robot Framework tests.** ods-ci is deprecated. All new QE tests go in opendatahub-tests using PyTest.
3. **Don't write an e2e test when a unit test will do.** Most bug fixes only need unit tests.
4. **Don't create a new test suite file if one exists.** In Go repos, add to existing `suite_test.go`. In opendatahub-tests, add to existing `conftest.py`.
5. **Don't skip cleanup.** In Go e2e tests, use `t.Cleanup()` or `DeferCleanup()`. In opendatahub-tests, use context manager fixtures.
6. **Don't hardcode cluster-specific values.** Use environment variables or test configuration.
7. **Don't skip type annotations in opendatahub-tests tests.** mypy strict mode is enforced.

### How to Verify Tests Catch the Bug

The test plan should be designed so that:
1. Reverting the fix (keeping the tests) causes the tests to FAIL
2. Applying the fix causes the tests to PASS

If a test would pass both with and without the fix, it's not testing the right thing.

### Output Format

Write **two files**:

1. **`issues/{KEY}.test-plan.json`** — the JSON object described above
2. **`issues/{KEY}.test-plan.md`** — a human-readable rendering:

```markdown
# Test Plan: {KEY}

## Decision Rationale

[Why these test layers were chosen — walk through the decision tree]

## Target Test Repositories

| Repo | Test Directory | Framework | Run Command |
|------|---------------|-----------|-------------|
| [repo] | [directory] | [framework] | [command] |

## Unit Tests

- **Test case:** [description]
  - **File:** [test file path]
  - **Setup:** [prerequisites/mocks]
  - **Input:** [test input]
  - **Expected:** [expected behavior]
  - **Edge cases:** [variations to cover]

## Integration Tests

- **Test case:** [description]
  - **Components involved:** [list]
  - **Setup:** [cluster state, mock services]
  - **Steps:** [numbered steps]
  - **Expected:** [expected outcome]
  - **API verification:** [if applicable]

## Regression Tests

- **Test case:** Reproduce original bug
  - **Steps:** [steps that trigger the original failure]
  - **Before fix:** [expected failure behavior]
  - **After fix:** [expected success behavior]

## Manual Verification Steps

1. [Step-by-step instructions]
2. [What to check in logs, pod status, UI, etc.]

## Environment Requirements

- **OCP version:** [required version(s)]
- **RHOAI version:** [required version(s)]
- **Platform:** [AWS/GCP/bare metal/any]
- **Special config:** [disconnected, multi-tenant, GPU nodes, etc.]

## Effort Estimate: [lightweight / moderate / heavy]

[Brief justification for the effort level]

## QE Coverage Note

[If applicable: suggested opendatahub-tests test with component, marker, and description. Otherwise: "N/A"]
```

Be specific and practical. Reference actual file paths, function names, and test frameworks used by the component. Read the architecture context and fix attempt to tailor your test plan to the specific codebase.
