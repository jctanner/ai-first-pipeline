# Claim-assurance v1 annotation rubric

Review each source unit independently. `selection` is `verifiable` when every
material element can be checked, `mixed` when factual and subjective or
speculative elements coexist, and `unverifiable` when no independently
checkable assertion remains.

Use `ambiguity_status: unresolved` when the bounded source context cannot
support one interpretation that reasonable readers would share. Do not repair
such a unit with outside knowledge. Otherwise use `none` or `resolved`, and
record the resolving context in the staged result.

`acceptable_claims` contains semantically acceptable atomic formulations; it
is not permission to change modality, negation, version, temporal scope, or
proposal/current-state status. `required_qualifiers` lists language whose loss
changes the assertion. `verifiable_elements` enumerates information extraction
must cover. `unverifiable_elements` identifies material that must not leak into
claims.

The v1 review checks are:

- all six artifact classes are represented by nine cases each;
- proposals, requirements, negation, cross-version assertions, mixed content,
  list preambles, referential ambiguity, and unverifiable prediction appear in
  every class;
- unresolved cases have no acceptable claims;
- mixed and unverifiable cases identify the excluded material;
- every expected claim retains its required qualifier;
- case directories and the aggregate manifest contain identical stable IDs.

Changes to these semantics require a new dataset version. Typographical fixes
that do not alter expected meaning still require review in their own commit.
