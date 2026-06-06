---
name: backend-agent-engineer
description: Engineers backend systems for LLM-driven agents. Use when designing APIs, orchestrators, tool runtimes, persistence, jobs, auth, retrieval and memory services, approvals, budgets, and reliability controls.
argument-hint: "[service/feature]"
allowed-tools: Read Write Edit Bash Grep Glob
---

Build the backend as the **safety, execution, and observability layer** around model reasoning.

This skill should produce designs that are:
- deterministic where possible
- strongly typed at the edges
- resumable and replayable
- safe under retries and partial failure
- legible to the frontend and operators

## Use this skill when
- the task involves APIs, services, queues, jobs, or orchestrators for an agent
- tool calling, memory, approvals, auth, or background execution is involved
- the user asks how to structure the backend of an AI agent system
- the system must be hardened for production reliability

## Backend architecture defaults
Unless there is a strong reason otherwise, partition the backend into:
- **Run API**: create, inspect, approve, cancel, and resume runs
- **Orchestrator**: owns state transitions and control loop
- **Tool router**: validates inputs, enforces policy, dispatches tools
- **Job runner**: executes long-running or asynchronous tasks
- **Memory service**: working context, summaries, and artifacts
- **Trace store**: state transitions, tool receipts, audit events

## Design procedure
### 1. Define the run lifecycle
At minimum support:
- create run
- start planning
- begin execution
- pause for approval
- resume after approval
- retry a failed step
- cancel run
- complete or fail terminally

For each lifecycle stage, specify:
- entry event
- persisted state
- user-visible event
- retry or recovery behavior

### 2. Define the API surface
Prefer resource-oriented endpoints such as:
- `POST /runs`
- `GET /runs/:id`
- `POST /runs/:id/approve`
- `POST /runs/:id/cancel`
- `POST /runs/:id/retry`

If streaming is used, define event types such as:
- `run.created`
- `plan.updated`
- `step.started`
- `tool.called`
- `tool.completed`
- `approval.requested`
- `run.completed`
- `run.failed`

### 3. Define the orchestrator
The orchestrator should:
- own state transitions
- account for budgets
- decide whether to continue, escalate, retry, or stop
- persist every state transition
- never perform side effects without going through the tool router

### 4. Define tool execution
Every tool needs:
- strict input schema
- strict output schema
- authorization scope
- timeout
- retry classification
- idempotency policy
- approval policy
- structured receipt

Never let the model call arbitrary code or arbitrary shell without policy mediation.

### 5. Define job execution
For long tasks:
- move execution to background jobs
- persist checkpointed progress
- expose progress handles for the UI
- support resume and recovery after worker failure

### 6. Define memory
Separate:
- short-lived working context
- run summaries
- artifact store
- optional long-term preference memory

Retrieval rules must define:
- source eligibility
- freshness expectations
- ranking strategy
- citation or provenance requirements
- redaction policy

### 7. Define auth and policy
At minimum specify:
- caller identity
- tenant or workspace scope
- tool permission scope
- approval authority
- audit identity for every action

### 8. Define reliability controls
Always include:
- timeouts
- bounded retries
- exponential backoff
- circuit breakers or backpressure if appropriate
- dead-letter handling for repeated failures
- idempotency keys for side effects

### 9. Define receipts and auditability
Every executed step should produce:
- `step_id`
- `tool_name`
- validated inputs summary
- outcome status
- what changed
- where it changed
- failure classification if applicable
- next suggested action

## Threats to address
At minimum discuss:
- prompt injection via retrieved content or tool output
- unauthorized tool access
- exfiltration of secrets or tenant data
- duplicate side effects from retries
- stale or conflicting memory
- hidden cost growth

## Output contract
When asked for backend design, return:
1. **Component architecture**
2. **Run lifecycle**
3. **API surface**
4. **Event model**
5. **Tool contract table**
6. **Persistence model**
7. **Memory and retrieval policy**
8. **Auth and approval model**
9. **Reliability controls**
10. **Threats and mitigations**
11. **Test and eval plan**

## Anti-patterns
Avoid:
- a single god-service with planning, execution, memory, and auth mixed together
- tools that return free-form strings as their contract
- retries without idempotency
- streaming without persisted event state
- background jobs with no resume semantics
- audit logs that cannot explain user-visible changes

## Done criteria
This skill is done only when:
- the run lifecycle is explicit
- tool and event contracts are concrete
- retries and idempotency are specified
- approvals and auth scopes are defined
- the design can support replay, debugging, and UI receipts

