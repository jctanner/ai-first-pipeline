"""Reference implementation of the stage-receipt reuse contract."""


def reusable(receipt: dict, expected: dict) -> tuple[bool, str]:
    checks = (
        (receipt.get("schema_version") == 2, "schema-changed"),
        (receipt.get("result") == "complete", "receipt-incomplete"),
        (receipt.get("stage") == expected["stage"], "stage-changed"),
        (receipt.get("scope") == expected["scope"], "scope-changed"),
        (receipt.get("implementation") == expected["implementation"], "implementation-changed"),
        (receipt.get("inputs", {}).get("digest") == expected["input_digest"], "inputs-changed"),
        (
            receipt.get("inputs", {}).get("evidence_context_digest")
            == expected.get("evidence_context_digest"),
            "evidence-context-changed",
        ),
        (expected.get("outputs_exist", False), "outputs-missing"),
    )
    failure = next((reason for passed, reason in checks if not passed), None)
    return failure is None, failure or "receipt-current"
