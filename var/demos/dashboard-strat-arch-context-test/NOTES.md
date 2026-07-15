# Test Findings

## Run context

- Markov run: `markov-run-f2e1e5b9`
- The run executed on the environment reached through `markovd.local` (testbox), not the Vagrant cluster.
- Baseline input: `RHAIRFE-2259`
- Overlay input: `RHAIRFE-2260`
- Baseline strategy: `RHAISTRAT-1`
- Overlay strategy: `RHAISTRAT-2`
- Both strategies completed create, refine, and review.

## Findings

### A. Does the overlay strategy place the catalog admin UIs in model-registry?

Yes. `RHAISTRAT-2` places the work in the `model-registry` module. It proposes:

- MCP Catalog write APIs in the `model-catalog` service.
- MCP Catalog admin pages in the `model-registry` frontend module.
- Reuse of Model Catalog patterns for UI, RBAC, and BFF routing.
- An implementation described as contained within the `model-registry` module.

This matches the architectural direction supplied by overlay `0018-catalog-admin-uis-in-model-registry.md`.

### B. Does the baseline strategy say something different?

Yes. `RHAISTRAT-1` assigns the work primarily to:

- The dashboard's `gen-ai` BFF and frontend.
- `MCPServer` custom resources.
- The `mcp-lifecycle-operator`.

The baseline review specifically reports that the strategy misattributes MCP endpoints to the `gen-ai` BFF and identifies inconsistencies with the available architecture context. The baseline review score was 6/8.

The overlay therefore caused a material change in architectural ownership: from dashboard/gen-ai and MCP lifecycle components to the `model-registry` module.

### C. Is either refined and reviewed strategy defensive in tone?

For this test, "defensive" has a specific meaning derived from the original problem statement: after overlay 0018 establishes `model-registry` as the authoritative location, the strategy must not re-litigate `gen-ai-ui` as an alternative. In particular, it must not contain a "Why model-registry module, not gen-ai-ui?" justification or name `gen-ai-ui` in Out-of-Scope material.

`RHAISTRAT-2` passes that criterion:

- It contains no reference to `gen-ai-ui`.
- It contains no "Why model-registry" defense or equivalent comparison with the pre-overlay alternative.
- Its Out-of-Scope section does not name `gen-ai-ui`.
- It presents `model-registry` ownership directly as the implementation default.

This differs from the originally observed failure in `RHAISTRAT-1859`, where two refine passes with overlay 0018 active still produced both a defensive "Why model-registry module, not gen-ai-ui?" paragraph and an Out-of-Scope reference to `gen-ai-ui`.

More generally, neither strategy in this run argues with reviewers or makes excuses for its conclusions. Both use normal planning qualifications such as risks, mitigations, assumptions, open questions, and `needs validation` markers. Those qualifications are not the defensive behavior targeted by this test.

The overlay strategy's review score was 7/8. Its only deduction concerned testability: a subjective UXD criterion, absent non-functional thresholds, and missing edge-case criteria.

## Conclusion

The test supports the intended hypothesis: installing the architecture overlay before strategy generation changed the strategy's component ownership conclusion to `model-registry`, while the baseline reached a materially different conclusion. After refinement and review, the overlay strategy treated that ownership as settled and did not mention or argue against `gen-ai-ui`. This run therefore exhibits the expected behavior and does not reproduce the `RHAISTRAT-1859` failure.
