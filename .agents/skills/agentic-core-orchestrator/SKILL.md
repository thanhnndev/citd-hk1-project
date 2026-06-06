---
name: agentic-core-orchestrator
description: Orchestrates production-grade LLM-driven agent systems in 2026. Use for agent architecture, control loops, topology choice, tool contracts, memory, approvals, safety boundaries, evals, and observability.
argument-hint: "[optional: short goal]"
allowed-tools: Read Write Edit Bash Grep Glob
---

This skill is the default operating system for production-grade **LLM-driven agentic systems**.

Use it to turn vague requests like "build an agent" into a concrete system with:
- a topology
- an execution loop
- explicit state
- typed tool contracts
- memory policy
- approval boundaries
- eval and observability gates

## Working philosophy
Treat the model as a probabilistic planner and reasoner embedded in a deterministic runtime.

The runtime, not the model alone, must guarantee:
- bounded execution
- policy compliance
- reproducibility and replay
- safe side effects
- measurable quality

## Use this skill when
- the user asks to build, redesign, or harden an AI agent
- the task requires choosing between single-agent, planner-worker, or multi-agent topologies
- the work includes tools, memory, approvals, RAG, evals, orchestration, or release readiness
- multiple specialist skills need to be coordinated into one coherent plan

## Do not use this skill as an excuse to over-engineer
Before selecting a sophisticated topology, prove that a simpler one will not work.

Default order of preference:
1. single agent + tools
2. planner + worker
3. supervisor + specialists
4. workflow graph / event-driven orchestration
5. parallel multi-agent

## Primary outputs
Unless the request is clearly narrower, produce these artifacts:
1. mission brief
2. topology decision
3. run-state schema
4. tool contract catalog
5. memory and retrieval policy
6. approval and safety boundary map
7. eval and observability plan
8. phased implementation plan

## Operating procedure
### 1. Frame the mission
Write a mission brief with:
- **primary user**
- **job to be done**
- **goal**
- **non-goals**
- **constraints**: latency, cost, privacy, data residency, compliance, UX expectations
- **risk tier**: low / medium / high / critical
- **failure impact**
- **acceptable degradation mode**

If the user request is underspecified, explicitly list assumptions. If an assumption materially changes the architecture, ask instead of guessing.

### 2. Choose the topology
Select the smallest topology that satisfies the mission:

**Single agent + tools**
- Use when work is mostly linear, latency-sensitive, and does not need specialized authorities.
- This is the default.

**Planner + worker**
- Use when decomposition improves correctness or reduces context confusion.
- Planner writes or updates the plan; worker executes bounded steps.

**Supervisor + specialists**
- Use when subproblems require different domains, tools, or permission scopes.
- The supervisor owns merge logic and final accountability.

**Workflow graph / resumable orchestration**
- Use when jobs are long-running, asynchronous, human-gated, or externally evented.

**Parallel multi-agent**
- Use only for independent subproblems with explicit merge criteria.
- Never use parallelism as a substitute for clarity.

For every topology choice, state:
- why it is necessary
- what the cheaper alternative was
- what failure mode the chosen topology avoids

### 3. Define explicit state
Define the state machine and its update rules.

Minimum state fields:
- `goal`
- `constraints`
- `plan`
- `next_action`
- `observations`
- `tool_history`
- `artifacts`
- `approval_status`
- `budget`
- `risk_flags`
- `final_answer`

For each field, specify:
- owner
- how it is updated
- whether it is persisted
- whether it can influence side effects

### 4. Define the control loop
Use a loop like:
1. plan
2. act
3. observe
4. evaluate
5. continue, escalate, or stop

For each stage, define:
- allowed inputs
- outputs
- failure handling
- max retries
- budget accounting

### 5. Define tool contracts
Every tool must have a strict contract:
- **name**
- **purpose**
- **input schema**
- **output schema**
- **side-effect classification**: read-only / reversible / irreversible / externalized
- **timeout**
- **retry policy**
- **idempotency requirement**
- **approval requirement**
- **audit fields**

Rules:
- reject unknown fields
- sanitize untrusted content before reinserting it into planner context
- return structured outputs, not narrative prose
- include receipts such as `what_changed`, `where`, `why`, and `next`

### 6. Define memory and retrieval
Split memory into layers:
- **working memory**: current task context
- **run summary**: condensed trace for long runs
- **artifact memory**: plans, outputs, receipts, files
- **long-term memory**: user or environment preferences if explicitly allowed

For each layer, define:
- write conditions
- retention
- retrieval policy
- redaction rules
- trust level

Do not treat vector retrieval as a substitute for state design.

### 7. Define safety and approvals
Assume the following are default threats:
- prompt injection from web pages, files, or tool results
- tool misuse through ambiguous instructions
- data exfiltration
- silent budget creep
- incorrect autonomy escalation

Specify:
- which actions require approval
- who can approve
- approval scope and expiry
- what must be shown before approval
- what happens on denial or timeout

Default approval triggers:
- deletes
- production deploys
- paid external API actions
- message sending
- data export
- privilege changes

### 8. Define observability
Minimum telemetry:
- run id
- state transitions
- tool calls with validated args
- tool results with structured outputs
- retry counts
- latency and cost estimates
- approval requests and outcomes
- final result classification

The trace must allow replay of any important run end-to-end.

### 9. Define eval gates
Every architecture proposal should include:
- **golden-path evals**
- **adversarial evals**
- **regression evals**
- **cost and latency thresholds**
- **release gating policy**

At minimum, test:
- task completion on representative tasks
- tool selection correctness
- argument correctness
- policy adherence
- graceful failure
- budget adherence

## Output contract
When producing an architecture, return sections in this order:
1. **System overview**
2. **Topology decision**
3. **Run-state schema**
4. **Control loop**
5. **Tool contract catalog**
6. **Memory policy**
7. **Approval boundaries**
8. **Threat model**
9. **Eval plan**
10. **Implementation phases**

## Anti-patterns
Avoid these failure modes:
- "multi-agent" with no merge or accountability model
- memory described only as "use a vector DB"
- tool definitions without schema, retry, or approval behavior
- policies buried in prose instead of attached to execution boundaries
- "we will monitor" without traces, metrics, or thresholds
- open-ended autonomy with no stop conditions

## Done criteria
This skill has done its job only when:
- the architecture can be implemented without major ambiguity
- the topology choice is justified against simpler alternatives
- side-effect boundaries are explicit
- tool and state contracts are concrete
- evals can block unsafe or regressive releases


