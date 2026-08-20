# M3 pipeline adaptations

`0001-local-emulator-runtime-endpoints.py` contains the environment
adaptations applied to the private `strat-pipeline` source before it is pushed
to the GitLab emulator.

The changes are intentionally generic: the pipeline keeps public GitHub and
Jira defaults for ordinary upstream use, while CI/project variables can
override the GitHub, GitLab, and Jira endpoints for an emulator. Its Git helper
scripts construct authenticated URLs from `GITLAB_GIT_URL` instead of assuming
`gitlab.com`. The pipeline's job logic and four job types are unchanged. The
recipe fails if an expected upstream source line is absent or ambiguous.

Additional tracked adaptations:

- `0002-no-ssl-verify.py` adds opt-in TLS bypass support to clients; defaults
  remain certificate verification.
- `0003-dashboard-emulator-runtime.py` makes the dashboard Pages checkout use
  runtime emulator endpoints and its masked data-repository token.
- `0004-jira-attachment-runtime-url.py` rewrites loopback Jira attachment URLs
  for runner-pod reachability while leaving ordinary URLs unchanged.
- `0005-emulator-smoke-config.py` adds only the fixture mirror's controlled
  `config/emulator-smoke.yaml`; the private source checkout is not modified.
- `0006-no-work-pipeline-post.py` makes empty, already-processed batches exit
  successfully before report generation; normal artifact runs are unchanged.
- `0007-otel-api-bodies.py` makes Claude Messages API body capture opt-in and
  uploads the untruncated body files as restricted GitLab job artifacts; it
  does not print them or copy them into the results repository.
