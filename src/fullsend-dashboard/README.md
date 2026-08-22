# Fullsend operations dashboard

This is a read-only operational view for the local Fullsend development stack.
It polls `/api/state` every five seconds and combines:

- GitHub Actions workflow runs and jobs from the configured emulator API;
- Fullsend/OpenShell-related pods across the cluster;
- Fullsend Kubernetes Jobs; and
- recent GitHub Actions and Kubernetes events.

The service does not mutate GitHub, Kubernetes, OpenShell, or Fullsend state.
It is exposed as `https://fullsend.local` by the breadboard ingress proxy.

Configuration is supplied through environment variables:

- `GITHUB_API_URL` — GitHub-compatible API base URL;
- `GITHUB_UI_URL` — browser-facing GitHub emulator URL used to build `/ui/`
  run and job links;
- `GITHUB_REPOS` — comma-separated `owner/repo` values to inspect;
- `GITHUB_TOKEN` — optional read token; and
- `NO_SSL_VERIFY=1` — explicit development-only TLS verification opt-out.
