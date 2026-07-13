# ai-first-pipeline demo script

--------------------------------------------------------------------------

## introduction

<show slide 1: An "ai-first" pipeline>

This project explores what an "AI-first" engineering pipeline could look like when agents are treated as part of a complete system rather than as isolated prompts. The focus is not only running agents, but creating a safe environment where their workflows can be observed, evaluated, and improved.

<advance to slide 2: Intro>

The question behind the project is: how does a skill or pipeline developer learn, write, test, and iterate safely? The answer I have been exploring is a sandbox where agents can do realistic work without putting production systems or a developer's workstation at risk—and where the results of each experiment can inform the next one.

<advance to slide 3: Background>

The project began during AI Engineering Bug Bash week as a multi-agent loop for RHOAI engineering bugs. Instead of assigning one bug to one developer, I wanted to see what happened if agents attempted all of the bugs in parallel—and then understand which inputs, tools, and context actually improved the results. That experiment grew into the larger platform shown here.

<advance to slide 4: The local infrastructure solution>

The first implementation was a local Python script that used the Claude Agent SDK to run multiple bug-fix agents in parallel. That was enough to prove the basic idea, but as the experiment added credentials, repositories, shared artifacts, service emulators, and more concurrent jobs, managing everything directly on my workstation became the next problem.

K3s became the integration layer for the expanded experiment. It isolates the services and agent processes from the host, gives every execution a native Job abstraction and lifecycle, and provides a path toward running the same ideas on OpenShift.

We also built a small Go ingress proxy so the cluster services are reachable from the host through stable `*.local` names such as `dashboard.local`, `jira.local`, and `markov.local`. The proxy routes those hostnames into Traefik and works with the cluster's internal certificate authority, so the services feel like a coherent local environment rather than a collection of port forwards.

<advance to slide 5: Dashboard>

<show the pipeline dashboard home page>

The dashboard is the landing page for the environment, an artifact viewer, an administrative surface, and one way to launch agent jobs. The primary inputs are Jira tickets and fully qualified skill names. Skills are versioned in Git repositories, so a workflow can identify both the capability it needs and the exact revision it should run.

The dashboard also contains experimental evaluation stubs for the `agent-eval-harness` project. The Evals page can describe a versioned dataset by FQN, select a model and context revision, launch the harness as a Kubernetes Job, and retain the same logs and telemetry used by skill runs. This is early integration work, but it points toward evaluating skill and context changes from the same interface used to run them.

<optionally show the dashboard Evals page>

--------------------------------------------------------------------------

## jobs and execution

<advance to slide 6: Agent runner>

The dashboard evolved from a reporting UI into one of the platform's execution surfaces. This is where the conceptual agent runner from the slide becomes a real Kubernetes Job.

<show the dashboard Jobs page>

One problem I ran into early was ambiguity around skill names. I might have the original skill in its upstream repository, a fork with experimental changes, and another local revision under active development. Asking the runner to execute a skill by name did not say which copy I meant.

Fully qualified skill names became the answer. An FQN identifies the Git host, owner, repository, revision, and skill—for example, `github.local/opendatahub-io/rfe-creator@main:rfe.speedrun`. That makes the source of the skill explicit and lets me choose between the original version and an edited copy imported into the local forge. It also gives each run useful provenance: we know which skill was requested, where it came from, and which revision should be compared later.

The dashboard is one way to submit and inspect agent jobs. A job can choose its skill, model, harness, and runner, and then runs in Kubernetes with the appropriate credentials, storage, and context. The backend launches each job using a custom pipeline-agent image and selects a wrapper for the chosen harness and runner. That wrapper resolves and installs the skill from its FQN, constructs the skill inputs, and configures credentials and telemetry. Jobs can capture MLflow traces, OpenTelemetry events, API-body dumps, and strace output for the harness and its child processes. Harness, model, and runner are selectable; the exact telemetry available varies by execution path, with Claude API-body capture currently specific to the Claude Code CLI runner.

Generated artifacts, job logs, API-body dumps, and strace output are stored on the shared `/app/artifacts` volume, making them available to subsequent jobs; MLflow traces are stored separately by the MLflow service.

<open one completed job and show its logs>

Each execution captures enough information to understand not only whether the job succeeded, but what the agent actually did.

<advance to slide 7: MLflow>

<show the corresponding MLflow experiment and trace>

The skill, model, harness, and runner become part of the experiment identity. That lets us compare equivalent executions instead of treating all agent traces as one undifferentiated stream.

--------------------------------------------------------------------------

## service simulation

<advance to slide 8: Jira emulator>

<show the seeded RFE in the Jira emulator>

Jira is the planning system of record for the demo. The emulator gives agents a realistic API and data model while still allowing the entire environment to be reset to a known state.

<advance to slide 9: GitHub emulator>

<show an imported skill or source repository in the GitHub emulator>

The same principle applies to source control. Skills and their dependencies can be imported, modified, and exercised against realistic Git operations without touching their production repositories.

<advance to slide 10: GitLab emulator>

<show a GitLab pipeline and its runner job>

The GitLab emulator adds a reproducible CI surface. We can copy production-shaped pipelines into the sandbox, run their jobs inside the same K3s environment, and change the surrounding infrastructure without waiting for or disrupting scheduled production pipelines.

--------------------------------------------------------------------------

## workflow orchestration

<advance to slide 11: markov[d]>

<show the markovd Runs page>

Markov chains individual skills and service operations into workflows. I describe it as a state machine because a workflow can recursively invoke itself—looping indefinitely, or until the rule engine evaluates the current facts and decides that a condition has been met. Those rules determine whether the workflow continues, skips a path, pauses, or exits. markovd provides the control plane: it launches runs, receives callbacks, persists state, and makes the workflow visible.

That looping behavior matters to the larger idea of an AI factory. The factory should not be a one-way assembly line that ends when an agent produces an artifact. It should evaluate the result, use that feedback to improve the skill, context, workflow, model, or policy, and run the scenario again until the quality rules say it is ready—or until the system pauses for human judgment.

<open the end-to-end run in markovd>

This run resets the demo services, imports repositories, seeds an RFE, and then moves through RFE review, strategy creation, epic decomposition, investigation, and code generation.

<show the end-to-end React Flow graph in markovd>

The graph makes the orchestration concrete. We can see sequential phases, quality gates, nested workflows, and fan-out where multiple epics or investigations run independently.

<switch to the Gantt view or step table>

The same run can be inspected as a timeline or table, which makes concurrency, duration, failures, and individual step logs easier to understand.

<briefly return to the dashboard Jobs page and find one of the jobs from the Markov workflow>

These are the same agent jobs we looked at earlier, now launched as steps in the larger workflow. Markov could create the Kubernetes Jobs directly, but in this workflow we deliberately have it submit them through the dashboard's Jobs API. That gives us one consolidated agent-job abstraction for interactive launches and orchestrated workflows alike. Skill resolution, model and runner selection, credentials, storage, telemetry configuration, job metadata, status, and logs all follow the same path instead of being reimplemented inside Markov.

--------------------------------------------------------------------------

## feedback and improvement

<advance to slide 12: Observatory>

MLflow and the other tracing sources show how agents behaved, what tools they used, and what the run cost. Observatory asks the next question: was the resulting engineering output actually supported by evidence? Human observation is one feedback path, but it does not scale by itself.

<show Observatory claims or hallucinations page>

Observatory extracts claims from generated artifacts, verifies them against available evidence, and explains supported, refuted, insufficient, or inconclusive results. The important outcome is determining what needs improvement: the skill, the context, retrieval, workflow gates, model, harness, tools, policy, or even the human-authored source material.

<open one claim and show its evidence and verification explanation>

The long-term goal is to turn findings like this into regression cases. We should be able to change a skill or context source, replay the same seeded workflow, and measure whether quality improved without introducing regressions elsewhere.

--------------------------------------------------------------------------

## putting it together

<advance to slide 13: DEMO — End-to-end skill chaining with Markov>

At this point, we have already been walking through the end-to-end demo. We started with a Jira request, saw the agent-job abstraction in the dashboard, followed those jobs through a Markov workflow, inspected their traces in MLflow, and looked at how Observatory evaluates the resulting claims.

This slide is the zoomed-out view. These are not separate demos or unrelated services; together, they form one replayable RFE-to-code scenario. We can trace the original business request through planning, investigation, implementation, execution telemetry, and evidence-backed quality findings.

<optionally return to the end-to-end graph in markovd for questions>

--------------------------------------------------------------------------

## close

The grand vision is a continuous loop: execute realistic engineering work, observe it, verify the output, attribute failures, improve the responsible layer, and replay the scenario. That feedback loop is what turns a collection of agents into an engineering platform.
