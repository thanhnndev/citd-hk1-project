---
name: agentic-product-designer-2026
description: Designs production-grade AI agent experiences. Use for PRDs, user journeys, interaction models, trust and approval UX, failure handling, provenance, and measurable acceptance criteria for agentic products.
argument-hint: "[feature or workflow]"
allowed-tools: Read Write Edit Grep Glob
---

Design agentic user experiences as **state machines with trust**, not as chat transcripts with decoration.

The user must always be able to answer:
- what the agent believes the goal is
- what it is doing now
- what evidence it is using
- what it plans to do next
- what actions need approval
- how to stop, edit, or recover

## Use this skill when
- the user asks for a PRD or UX design for an AI agent
- a workflow needs planning, execution, approvals, and result review
- trust, provenance, or failure handling is central to product quality
- the product currently feels like a chatbot rather than a dependable operator

## First principles
### 1. Legibility beats magic
Invisible autonomy creates fear and error. Show plan, progress, and receipts.

### 2. Control is a feature
Users must be able to:
- edit the plan
- approve or deny risky actions
- pause or cancel execution
- retry safely
- inspect what changed

### 3. Provenance is mandatory
Separate:
- model inference
- retrieved knowledge
- tool-observed facts
- actual side effects

### 4. Failure is a designed state
Do not only design the happy path. Failure, ambiguity, and handoff need explicit UX.

### 5. Agent UX is a product system
The UX includes:
- onboarding
- plan authoring
- execution timeline
- approvals
- receipts and diffs
- recovery and handoff

## Design procedure
### 1. Define the operating model
State:
- what the user asks for
- what the agent can infer
- what the agent must confirm
- what the system will do automatically
- what requires explicit approval

### 2. Define core user journeys
At minimum produce:
- one **happy path**
- one **ambiguity path** where the agent needs clarification
- one **failure path** where a tool or policy blocks progress
- one **approval path** for side effects

For each journey, specify:
- trigger
- user-visible states
- system actions
- user decisions
- completion criteria

### 3. Define the state model
Minimum UI states:
- `idle`
- `drafting`
- `planning`
- `waiting_for_user_input`
- `executing`
- `waiting_for_approval`
- `retrying`
- `completed`
- `failed-recoverable`
- `failed-terminal`

For each state, specify:
- entry condition
- visible UI
- available actions
- exit transitions

### 4. Define trust surfaces
Every agentic UI should expose:
- **plan view**
- **timeline of steps**
- **tool receipts**
- **approval UI**
- **artifact/output panel**
- **error and retry controls**

### 5. Define approval UX
Approval requests must include:
- what action will happen
- why it is needed
- what inputs will be used
- what may change
- scope and expiry of approval
- deny and edit alternatives

Never present an approval CTA without consequences and scope.

### 6. Define provenance UX
For every important answer or action, make clear:
- which parts are from tool output
- which parts are model synthesis
- whether the information is current or cached
- where the user can inspect supporting evidence

### 7. Define recovery UX
For failures, specify:
- user-friendly error text
- what was attempted
- whether side effects occurred
- safe retry path
- escalation path

### 8. Define telemetry
Track:
- plan accepted or edited
- approval shown / approved / denied
- tool step success or failure
- retry count
- final task success
- user intervention rate

## PRD template
Return a PRD with:
1. **Problem**
2. **Primary user**
3. **Goals**
4. **Non-goals**
5. **Operating model**
6. **User journeys**
7. **State model**
8. **Trust and approval model**
9. **Provenance model**
10. **Failure and recovery**
11. **Telemetry**
12. **Acceptance criteria**

## Preferred patterns
- plan-first before execution
- editable plan before risky work
- step receipts instead of hidden work
- previews or dry-runs before production changes
- explicit handoff when confidence collapses

## Anti-patterns
Avoid:
- single chat stream hiding planning and execution state
- approval dialogs that do not explain consequences
- answers that mix tool facts with unstated model guesses
- "spinner UX" with no progress semantics
- error states with only "try again"

## Output contract
Return:
1. **PRD**
2. **Journey map**
3. **ASCII state diagram**
4. **Trust surfaces**
5. **Acceptance checklist**

## Done criteria
This skill is done only when:
- the UI can be implemented as a state machine
- trust, provenance, and approvals are explicit
- at least one failure path is designed as thoroughly as the happy path
- the acceptance criteria are testable

