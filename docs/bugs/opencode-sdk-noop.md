# OpenCode SDK mode silently drops prompts (no LLM call)

## Summary

`opencode serve` accepts prompts via the REST API, emits a `session.next.prompt.admitted` SSE event, and then does nothing. Zero tokens are consumed, no outbound TCP connection to Vertex AI is made, and the session hangs until the pod times out.

CLI mode (`opencode run`) works correctly with the same model, credentials, and environment.

## Reproduction

1. Submit a job from the dashboard with: Harness=opencode, Runner=SDK, any model, any skill
2. The job logs show "=== Agent Output ===" and then hang indefinitely
3. The session API shows `tokens: {input: 0, output: 0}` — the LLM was never called
4. The job eventually fails via K8s `activeDeadlineSeconds` timeout

Jobs tested:
- `cookiemonster-all-claude-haiku-4-5-0622-213703` (SDK, mlflow=true) — hung, failed
- `cookiemonster-all-claude-haiku-4-5-0622-214843` (SDK, mlflow=false) — hung, failed
- `cookiemonster-all-claude-haiku-4-5-0622-215432` (SDK, mlflow=false, strace on serve) — hung

CLI mode jobs with the same model work fine:
- `cookiemonster-all-claude-haiku-4-5-0622-185811` (CLI) — completed in 22s
- `cookiemonster-all-claude-haiku-4-5-0622-200731` (CLI) — completed in 24s

## What the driver does

`scripts/run_skill_opencode_sdk.sh` runs `opencode serve --port 4096` in the background, then uses an inline Python driver to:

1. `POST /api/session` — create a session with `providerID: "google-vertex-anthropic"`, `id: "claude-haiku-4-5@20251001"` (split from the `--model` flag)
2. `GET /api/event` — subscribe to SSE events (in a background thread)
3. `POST /api/session/{id}/prompt` — send the prompt text
4. Wait for a `session.status` event with `type: "idle"`

Step 1-3 all return HTTP 200. The SSE stream receives exactly two events, then blocks forever:
- `server.connected`
- `session.next.prompt.admitted`

No further events are emitted: no `message.part.updated`, no `session.error`, no `permission.asked`, no `session.status`.

## Strace evidence

Job `cookiemonster-all-claude-haiku-4-5-0622-215432` has strace on both the serve process and the Python driver.

Strace files:
```
/data/k3s/storage/pvc-9acffda0-4dda-4fa5-80a3-ced82db48109_ai-pipeline_pipeline-artifacts/strace/cookiemonster-all-claude-haiku-4-5-0622-215432/
  serve.*   — opencode serve process (37 = main PID, ~30 goroutine threads)
  driver.*  — Python SDK driver (54 = main PID, 58 = SSE listener thread)
```

Key findings from the serve process strace:

- **Zero `socket(AF_INET, ...)` calls** — the serve process never created an outbound TCP socket
- **Zero `connect()` calls** — no attempt to reach Vertex AI, npm, or any external host
- **All activity after startup is idle** — `epoll_pwait2`, `futex`, `clock_gettime`, `sched_yield`, and Go runtime `SIGPWR` preemption signals
- The HTTP listener accepted the driver's connections (health check, session create, prompt, SSE), but never initiated outbound work in response

By contrast, the CLI mode strace (`cookiemonster-all-claude-haiku-4-5-0622-185811`) shows immediate outbound `connect()` calls to Cloudflare IPs (npm/plugin registry) and the Vertex AI endpoint after the prompt is processed.

## Environment

Both CLI and SDK jobs run in the same container image (`pipeline-agent`) with identical env vars:
- `GOOGLE_CLOUD_PROJECT=itpc-gcp-ai-eng-claude`
- `GOOGLE_VERTEX_PROJECT=itpc-gcp-ai-eng-claude`
- `GOOGLE_VERTEX_LOCATION=us-east5`
- `GOOGLE_APPLICATION_CREDENTIALS=/home/pipelineagent/.config/gcloud/credentials.json`
- `CLAUDE_CODE_USE_VERTEX=1`

## Root cause

The bug is an Effect layer wiring issue in the OpenCode server's V2 API handler stack.

When `opencode serve` starts, the HTTP request handlers are assembled in `packages/server/src/handlers.ts`. This module provides two layers to its handler group:

```typescript
Layer.provide(SessionV2.defaultLayer),              // line 51
Layer.provide(SessionExecutionLocal.defaultLayer),  // line 52
```

The intent is for `SessionExecutionLocal.defaultLayer` to supply `SessionExecution.Service` — the layer that actually calls the LLM when a prompt is submitted. However, `SessionV2.defaultLayer` (defined in `packages/core/src/session.ts:438`) already bundles its own `SessionExecution` dependency internally:

```typescript
export const defaultLayer = layer.pipe(
  Layer.provide(SessionExecution.noopLayer),   // ← baked-in noop
  Layer.provide(SessionStore.defaultLayer),
  Layer.provide(SessionProjector.defaultLayer),
  Layer.provide(EventV2.defaultLayer),
  Layer.provide(Database.defaultLayer),
  Layer.provide(ProjectV2.defaultLayer),
  Layer.orDie,
)
```

Because `defaultLayer` already satisfies its own `SessionExecution.Service` requirement with `noopLayer`, the `SessionExecutionLocal.defaultLayer` on the next line is dead — it provides `SessionExecution.Service` but nothing in the layer tree consumes it. The result: every prompt goes through `SessionExecution.noop.wake`, which does nothing.

The debug log from a failing job confirms this:

```
[opencode-debug] SessionExecution.local.layer initialized
[opencode-debug] SessionV2.prompt.wake sessionID=ses_...
[opencode-debug] SessionExecution.noop.wake sessionID=ses_...
[opencode-debug] SessionV2.prompt.wake-returned sessionID=ses_...
```

Note that `SessionExecution.local.layer initialized` appears because the local layer IS constructed — it's just never used. The `noop.wake` line is the smoking gun.

CLI mode (`opencode run`) works because it uses a completely different code path that wires `SessionExecutionLocal` directly into the runner without going through `SessionV2.defaultLayer`.

## Fix attempts

### Attempt 1: Replace `SessionV2.defaultLayer` with `SessionV2.layer` in handlers.ts

In `packages/server/src/handlers.ts`, changed `SessionV2.defaultLayer` to `SessionV2.layer` so the bare `layer` export leaves `SessionExecution.Service` as an unsatisfied dependency, which `SessionExecutionLocal.layer` should fill. Also added `SessionStore.layer` since it was previously bundled inside `defaultLayer`:

```typescript
import { SessionStore } from "@opencode-ai/core/session/store"
// ...
Layer.provide(SessionV2.layer),                     // was: SessionV2.defaultLayer
Layer.provide(SessionExecutionLocal.layer),         // bare layer; share SessionStore below
Layer.provide(SessionStore.layer),                  // new: was bundled in defaultLayer
```

**Result**: Still `noop.wake`. Sequential `Layer.provide` calls in a pipe satisfy the upstream layer's dependencies, not each other's. `SessionExecutionLocal.layer` was being provided to the merged handlers group, not to `SessionV2.layer`.

### Attempt 2: Explicit composition with nested pipe

Explicitly composed `SessionV2.layer` with its dependencies in a single `Layer.provide`:

```typescript
Layer.provide(
  SessionV2.layer.pipe(
    Layer.provide(SessionExecutionLocal.layer),
    Layer.provide(SessionStore.layer),
  ),
),
```

**Result**: Still `noop.wake`. The noop execution fires despite local being correctly composed into the `SessionV2` layer. This means either:
1. Something else is providing `SessionV2.Service` (with noop baked in) at a higher priority, or
2. The `HttpApiBuilder` system resolves services from a different context than the `handlers` pipe chain.

### Attempt 3: Patch all three noop providers

Replaced `SessionV2.defaultLayer` with `SessionV2.layer` + `SessionExecutionLocal` at all three non-test sites:
- `packages/server/src/handlers.ts`
- `packages/opencode/src/session/session.ts:970-971`
- `packages/core/src/control-plane/move-session.ts:128-129`

**Result**: Server crash at startup — `Service not found: @opencode/example/LocationServiceMap`. `SessionExecutionLocal.layer` depends on `LocationServiceMap`, `SessionRunCoordinator`, and `SessionRunner`, which aren't available in the `defaultLayer` contexts of `session.ts` and `move-session.ts`. Those two sites legitimately use noop — they only need to record sessions, not execute them. Reverted both; kept the `handlers.ts` fix only.

### Diagnostic build: tagged noop + unminified binary

Added two diagnostic layers:
- `packages/core/src/session.ts` — replaced `noopLayer` in `defaultLayer` with `_noopWithLog` that logs `noop-from-defaultLayer.wake` with construction and call stack traces
- `packages/core/src/session/execution.ts` — the standalone `noopLayer` logs `noop.wake` (original message)
- Built with `--no-minify` flag for readable stack traces

### Diagnostic results (job cookiemonster-all-claude-haiku-4-5-0623-121558)

The noop that fires is **`noop-from-defaultLayer.wake`** — confirming it is `SessionV2.defaultLayer` (with baked-in noop) that provides the `SessionV2.Service` used by the prompt handler, NOT the standalone `noopLayer`.

`SessionV2.defaultLayer` is constructed **twice** at startup. Both construction stacks originate from `../core/src/session.ts:441`. The local execution layer IS initialized (`SessionExecution.local.layer initialized` appears), but the `SessionV2.Service` that the prompt handler resolves uses the noop-backed instance from `defaultLayer`.

The wake call stack shows the noop is invoked from the prompt path:
```
[opencode-debug] SessionExecution.noop-from-defaultLayer.wake sessionID=ses_...
    at ../core/src/session.ts:447:25       ← _noopWithLog.wake
    at ~effect/Effect/evaluate
    ...
    at NodeStream.js:142:7                 ← HTTP request handling
```

This means the `handlers.ts` fix (Attempt 2) correctly composes `SessionV2.layer` with `SessionExecutionLocal.layer`, but the resulting `SessionV2.Service` is **not the one the prompt handler uses**. Something else in the layer tree — most likely `MoveSession.defaultLayer` provided at `createRoutes()` line 279 — builds `SessionV2.defaultLayer` first, and Effect's memoization causes subsequent resolutions of `SessionV2.Service` (including in the prompt handler) to reuse that noop-backed instance.

### Remaining suspects

Two non-test sites still provide `SessionV2.defaultLayer` (which bundles `noopLayer` internally) and cannot simply be switched to use `SessionExecutionLocal` (missing `LocationServiceMap` dependency):

1. **`packages/opencode/src/session/session.ts:971`** — the opencode `Session.defaultLayer` provides `SessionV2.defaultLayer`. While `Session.node` uses `layer` (not `defaultLayer`), the `defaultLayer` export could be pulled in elsewhere.

2. **`packages/core/src/control-plane/move-session.ts:129`** — `MoveSession.defaultLayer` provides `SessionV2.defaultLayer`. This layer is explicitly included in `createRoutes()` at line 279 of `packages/opencode/src/server/routes/instance/httpapi/server.ts`. This is the strongest suspect because it's directly in the serve layer tree and would be built before the `handlers` layer.

### Attempt 4: `MoveSession.layer` in createRoutes (deadlock)

Changed `MoveSession.defaultLayer` to `MoveSession.layer` at `createRoutes()` line 279. The idea: `MoveSession.layer` takes `SessionV2.Service` as a dependency (via `yield* SessionV2.Service`) instead of bundling its own noop-backed copy. The `handlers` layer provides `SessionV2.Service` with local execution, and `MoveSession.layer` should use that.

**Result**: Server deadlock. The serve process bound to port 4096 but never responded to the health check — hung forever. Only one noop construction message appeared (down from two), confirming the `MoveSession` noop was eliminated. But `MoveSession.layer` needs `SessionV2.Service` from the context, and `SessionV2.Service` is only provided inside `serverRoutes` via the `handlers` layer — it's not available at the `createRoutes` level where `MoveSession.layer` sits. Effect hung waiting for a service that would never be provided.

Job: `cookiemonster-all-claude-haiku-4-5-0623-131630` — server accepted health check HTTP request but never sent a response.

### Attempt 5: `MoveSession.defaultLayer.pipe(Layer.fresh)`

Instead of removing `MoveSession.defaultLayer` (which causes deadlock) or keeping it as-is (which leaks noop via memoization), wrap it with `Layer.fresh`. This tells Effect to create a fresh, isolated instance of the layer — its internal noop-backed `SessionV2.Service` will not be memoized and shared with the rest of the layer tree.

`MoveSession` only uses `SessionV2` for reading session data (get, list), not for executing prompts, so its internal noop `SessionExecution` is correct behavior. The problem was never that `MoveSession` used noop — it was that Effect's memoization caused `MoveSession.defaultLayer`'s noop-backed `SessionV2.Service` to be reused by the prompt handler.

```typescript
// In createRoutes(), line 279:
MoveSession.defaultLayer.pipe(Layer.fresh),  // was: MoveSession.defaultLayer
```

**Result**: **Fixed.** Job `cookiemonster-all-claude-haiku-4-5-0623-153621` completed successfully — the LLM was called, tokens consumed (3 input, 376 output), and Cookie Monster responded. Only one noop construction message appeared in strace (from `MoveSession.defaultLayer`'s isolated scope), and the prompt handler used the local-execution-backed `SessionV2.Service` from `handlers.ts`.

### Summary of the memoization problem

Effect memoizes service instances by tag. When `MoveSession.defaultLayer` is provided in the `createRoutes()` pipe, it builds its internal `SessionV2.defaultLayer` (which bundles `SessionExecution.noopLayer`). This creates and memoizes a `SessionV2.Service` instance. Later, when the `handlers` layer tries to provide its own `SessionV2.Service` (composed with `SessionExecutionLocal.layer`), the memoized noop-backed instance wins.

`Layer.fresh` prevents this by giving `MoveSession.defaultLayer` its own isolated scope — its services are never shared with the outer layer tree.

## Impact

This blocks the MLflow tracing fix. The `@mlflow/opencode` plugin only works reliably in SDK mode (due to the CLI `process.exit()` race), but SDK mode itself doesn't work with Vertex AI. Until this is resolved, OpenCode jobs cannot produce MLflow traces.

## Files involved

- `deploy/repos/opencode/packages/server/src/handlers.ts` — Attempt 2 fix (layer wiring)
- `deploy/repos/opencode/packages/core/src/session.ts` — `SessionV2.defaultLayer` with baked-in noop; diagnostic `_noopWithLog`
- `deploy/repos/opencode/packages/core/src/session/execution.ts` — noop layer definition
- `deploy/repos/opencode/packages/core/src/session/execution/local.ts` — local (real) execution layer
- `deploy/repos/opencode/packages/core/src/control-plane/move-session.ts` — `MoveSession.defaultLayer` provides `SessionV2.defaultLayer`; primary suspect
- `deploy/repos/opencode/packages/opencode/src/server/routes/instance/httpapi/server.ts` — `createRoutes()` includes `MoveSession.defaultLayer` at line 279
- `deploy/repos/opencode/packages/opencode/script/build.ts` — `--no-minify` flag for debug builds
- `scripts/run_skill_opencode_sdk.sh` — SDK entrypoint and Python driver
- `deploy/pipeline-agent/Dockerfile` — container image (builds OpenCode from local source with `--no-minify`)
