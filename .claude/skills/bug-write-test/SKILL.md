---
name: bug-write-test
description: Write QE tests for opendatahub-tests based on a fix attempt and test plan
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Bug Write-Test: QE Test Code Generation

Write actual pytest test code for the `opendatahub-tests` repository based on a fix attempt and test plan, or explicitly decline with justification.

## Instructions

### Decision Logic: Write vs Skip

Before writing any test code, evaluate these criteria:

1. **Does the fix change user-facing behavior?** (API responses, UI behavior, status conditions, CLI output, CRD fields visible to users)
2. **Does it cross component boundaries?** (e.g., operator change affects model serving, dashboard change affects notebook controller)
3. **Is the scenario already covered by existing opendatahub-tests cases?** Search the cloned repo for related tests before writing new ones.
4. **Does the test-plan specifically recommend QE-level coverage?** Check the `qe_coverage_note` field.
5. **Can the behavior be asserted without a live cluster?** If so, it belongs as a unit test in the component repo, not here.

**Decision outcomes:**

- `"write-test"` -- the fix warrants a QE-level test in opendatahub-tests. You MUST produce working pytest code and a patch.
- `"skip"` -- no QE test is warranted. You MUST provide a clear justification explaining why (e.g., "pure internal refactor with no user-visible behavior change", "already covered by existing test_model_registry_rbac.py").

### opendatahub-tests Repository Conventions

- **Repo:** `opendatahub-io/opendatahub-tests`
- **Framework:** PyTest 9.0+ with extensive fixture hierarchy
- **Python:** 3.14, managed with `uv`
- **Run:** `uv run pytest -m <marker> tests/`

#### Test Organization

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

#### Available Markers

`smoke`, `sanity`, `tier1`, `tier2`, `tier3`, `model_serving`, `model_registry`, `llama_stack`, `model_explainability`, `gpu`, `multinode`, `pre_upgrade`, `post_upgrade`, `parallel`, `cluster_health`, `operator_health`

#### Mandatory Coding Standards

- **Type annotations mandatory** -- mypy strict mode is enforced on the entire repo. Every function signature, variable annotation, and return type must be explicit.
- **Google-format docstrings mandatory** -- use the Given-When-Then pattern:
  ```python
  def test_example(self) -> None:
      """Test that X behaves correctly when Y.

      Given: A running inference service with model Z.
      When: A prediction request is sent with invalid input.
      Then: The service returns a 400 error with a descriptive message.
      """
  ```
- **One aspect per test** -- each test function tests exactly one behavior.
- **`openshift-python-wrapper` for K8s interactions** -- never use raw subprocess calls to `oc` or `kubectl`. Use the wrapper's resource classes (`Pod`, `Namespace`, `InferenceService`, etc.).
- **Fixtures must be nouns, not verbs** -- `model_namespace` not `create_namespace`, `serving_runtime` not `deploy_runtime`.
- **Use `indirect=True` for parametrized fixtures:**
  ```python
  @pytest.mark.parametrize(
      "model_namespace, serving_runtime, inference_service",
      [
          pytest.param(
              {"name": "test-ns"},
              {"deployment_type": KServeDeploymentType.RAW_DEPLOYMENT},
              {"gpu_count": 1, "name": "test-model"},
              id="test-model-raw-single-gpu",
          ),
      ],
      indirect=True,
  )
  ```
- **Snapshot testing with syrupy** -- use for inference response validation.
- **Never duplicate utility code** -- check `utilities/` directory before writing new helpers. Reuse existing validation functions, API clients, and assertion helpers.
- **Never create new `conftest.py`** if one already exists in the target directory. Add fixtures to the existing one.
- **Import style** -- use absolute imports from the repo root.

#### Test Pattern Example

```python
import pytest
from typing import Any, Generator

from ocp_resources.inference_service import InferenceService
from ocp_resources.pod import Pod


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

### Steps

1. **Review inputs:**
   - Read the fix-attempt JSON/patch to understand what changed
   - Read the test-plan JSON to understand the recommended test strategy
   - Pay special attention to the `qe_coverage_note` field in the test plan

2. **Evaluate the decision criteria** listed above. If ANY of these are true, choose `"write-test"`:
   - The fix changes user-facing API behavior
   - The fix crosses component boundaries
   - The test-plan `qe_coverage_note` is non-null and recommends opendatahub-tests coverage
   - The fix affects product-level behavior (model serving, model registry, workbenches, etc.)

3. **If decision is `"write-test"`:**
   a. Explore the cloned opendatahub-tests repo to understand existing patterns
   b. Identify the correct subdirectory under `tests/` for the component
   c. Check existing `conftest.py` for available fixtures
   d. Check `utilities/` for reusable helpers
   e. Write the test file(s) directly into the cloned repo
   f. Follow ALL coding standards listed above (type annotations, docstrings, markers, etc.)
   g. Choose appropriate markers (`smoke`, `tier1`, `tier2`, etc.)

4. **If decision is `"skip"`:**
   - Provide a clear justification
   - Do NOT write any test code

### Output Format

Write **two files** in the output directory specified in the prompt header:

1. **`write-test.json`** -- structured output conforming to the schema:

```json
{
  "issue_key": "RHOAIENG-XXXXX",
  "decision": "write-test",
  "justification": "The fix changes the model serving inference endpoint response format, which is user-facing API behavior that should be validated at the QE level.",
  "test_file": "tests/model_serving/test_rhoaieng_xxxxx_inference_format.py",
  "test_markers": ["tier1", "model_serving"],
  "test_description": "Verify that the inference endpoint returns the corrected response format after the fix.",
  "patch": null,
  "confidence": "high",
  "risks": ["Test requires GPU node for model deployment"],
  "cluster_requirements": "OCP 4.16+ with GPU node, RHOAI 3.4+"
}
```

For skip decisions:

```json
{
  "issue_key": "RHOAIENG-XXXXX",
  "decision": "skip",
  "justification": "The fix is a pure internal refactor of the operator's reconciliation loop with no change to user-visible behavior. The test-plan confirms unit tests in the operator repo are sufficient.",
  "test_file": null,
  "test_markers": [],
  "test_description": null,
  "patch": null,
  "confidence": "high",
  "risks": [],
  "cluster_requirements": null
}
```

Field descriptions:
- `issue_key`: the Jira issue key
- `decision`: `"write-test"` or `"skip"`
- `justification`: explanation of why the decision was made
- `test_file`: path to the test file within opendatahub-tests (null if skip)
- `test_markers`: pytest markers applied to the test (empty array if skip)
- `test_description`: brief description of what the test verifies (null if skip)
- `patch`: will be populated by post-processing with the git diff (always write null)
- `confidence`: `"low"`, `"medium"`, or `"high"` -- how confident you are in the decision and test quality
- `risks`: array of strings describing risks or caveats
- `cluster_requirements`: cluster/environment requirements for running the test (null if skip)

2. **`write-test.md`** -- human-readable summary:

```markdown
# Write-Test: {KEY}

## Decision: {write-test | skip}

**Justification:** {explanation}

## Test Details

- **File:** {path in opendatahub-tests}
- **Markers:** {comma-separated markers}
- **Description:** {what the test verifies}

## Test Code

```python
{the actual test code written, if decision is write-test}
```

## Confidence: {low | medium | high}

## Risks

- {risk 1}
- {risk 2}

## Cluster Requirements

{requirements or "N/A"}
```

### Important Notes

- The `patch` field in the JSON output should always be set to `null` -- the orchestrator will capture the git diff from the cloned repo and inject it automatically.
- Write test files directly into the cloned opendatahub-tests repo at the workspace path provided.
- If you write test code, make sure it is syntactically valid Python that would pass `ruff check` and `mypy --strict`.
- Do NOT run tests -- there is no cluster available. Just write the code.
- When in doubt about whether to write a test, lean toward `"skip"` with a clear justification. Not every bug fix needs a QE-level test.
