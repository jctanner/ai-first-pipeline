# Claim Assurance Evaluation Dataset

`claim-assurance-v1.json` is the seed corpus for the demo's local-only
`opendatahub-io/eval-datasets` repository. It contains 54 annotated source
units covering RFE, strategy, security-review, Epic, investigation, and
code-generation artifacts.

The annotations distinguish selection, ambiguity, acceptable atomic claims,
required qualifiers, and verifiable versus unverifiable elements. The stable
dataset FQN is:

```text
github.local/opendatahub-io/eval-datasets@main:claim-assurance
```

Review annotation changes independently from extractor changes. Increment the
dataset version when changing expected semantics; do not silently rewrite v1.
For reproducible non-demo runs, replace `main` with the resolved dataset commit.
The reviewed annotation rules are in
`claim-assurance/annotation-rubric.md`.
