# markov for_each silently truncates large lists

## Status: Open

## Symptom

The `seed-jira-components` workflow uses `for_each: rhai_components` to iterate over 96 RHAI component names and POST each to the Jira emulator. After the workflow completes successfully, only ~14 components exist in the emulator instead of 96.

## Reproduction

```yaml
# seed-jira-components.yaml
steps:
  - name: create_components
    for_each: rhai_components
    as: component_name
    type: jira_api
    params:
      path: /rest/api/2/component
      method: POST
      body:
        name: "{{ component_name }}"
        project: RHAI
      ignore_status: [400]
```

The `rhai_components` list in `vars.yaml` has 96 entries. The workflow reports `completed` status, but only the first ~14 items were actually processed.

## Evidence

```
$ markovd-cli runs create var-demos-end-to-end --workflow seed-jira-components --wait
run markov-run-3cd45c69 completed in 2.0s

# After run: only 14 components exist (should be 96)
$ kubectl exec jira-emulator -- curl -s http://localhost:8080/rest/api/2/project/RHAI/components | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"
14
```

Manually seeding all 96 via a Python script (direct `kubectl exec curl` for each) works perfectly — all 96 are created with no errors.

## Impact

High for the demo pipeline. The `rhai-components.txt` file on the shared PVC (used by epic-creator and codegen skills) ends up with a subset of components, causing skills to assign epics to only 9 component teams instead of 96.

## Workaround

Seed components outside of markov using a script that directly calls the Jira API for each component.

## Root cause (suspected)

The markov `for_each` implementation likely has a default iteration cap, or the Go template engine's list handling truncates the rendered list. The 2-second wall-clock completion time for 96 API calls also suggests most iterations were skipped, not failed.
