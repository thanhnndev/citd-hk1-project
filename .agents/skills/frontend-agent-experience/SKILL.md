---
name: frontend-agent-experience
description: Designs and implements frontend experiences for agentic applications. Use for chat and non-chat agent UX, streaming state machines, plan and receipt surfaces, approvals, provenance, failure recovery, and trustworthy interaction design.
argument-hint: "[screen/flow]"
allowed-tools: Read Write Edit Grep Glob
---

Build agentic UI as a **high-trust execution console**, not a generic text box.

The frontend must make the agent's work inspectable and controllable without overwhelming the user.

## Use this skill when
- designing or implementing an agentic app frontend
- building chat, timeline, approval, or provenance surfaces
- defining frontend state stores for streaming run events
- deciding how users inspect, edit, approve, retry, or cancel agent work

## Core UI principles
### 1. Separate conversation from execution
The transcript is not the system of record.
The system of record is the run timeline and state model.

### 2. Make progress semantic
Do not show only "thinking" or "loading".
Show whether the agent is:
- planning
- gathering information
- executing a tool
- waiting for input
- waiting for approval
- retrying
- completed
- failed

### 3. Receipts matter more than flourish
Users trust visible evidence:
- plan
- tool used
- what changed
- artifact generated
- whether approval was required

### 4. High-control beats hidden automation
Make it easy to:
- edit the plan
- pause or cancel
- inspect evidence
- retry safely
- continue from a checkpoint

## Required frontend model
Represent the run as a state machine with at least:
- `idle`
- `drafting`
- `planning`
- `executing`
- `waiting_for_user_input`
- `waiting_for_approval`
- `retrying`
- `completed`
- `failed-recoverable`
- `failed-terminal`

Maintain separate stores for:
- **user intent and transcript**
- **run state**
- **event timeline**
- **artifacts**
- **pending approvals**

## Required UI surfaces
### 1. Composer
Supports:
- goal entry
- attachment or artifact reference
- optional constraints
- run start and cancellation

### 2. Plan surface
Shows:
- interpreted goal
- assumptions if any
- plan steps
- editable plan before execution when appropriate

### 3. Timeline surface
A chronological event stream with:
- state transitions
- step starts and ends
- tool calls
- tool receipts
- errors
- approval events

### 4. Receipt surface
Every important step should show:
- tool name
- redacted key inputs
- summary of outputs
- what changed
- links to artifacts or diffs

### 5. Approval surface
Must show:
- action requested
- risk or scope
- why approval is needed
- what data or systems will be touched
- approve, deny, and edit options

### 6. Artifact surface
Shows generated files, diffs, previews, or external outputs.

## Streaming and concurrency rules
- Treat backend output as an event stream, not as append-only prose.
- Rendering must be idempotent under duplicated or delayed events.
- The UI must tolerate out-of-order delivery where the backend guarantees eventual consistency.
- Background jobs should continue updating the same run timeline.
- Long-running runs must survive page refresh or reconnect.

## Provenance rules
Clearly label:
- model-generated plan text
- tool-observed facts
- retrieved citations
- side effects actually applied

Never blur "the agent thinks" with "the system confirmed".

## Failure and retry rules
For each failure state, show:
- what failed
- whether changes were made
- whether retry is safe
- what alternatives the user has
- whether human intervention is recommended

## Accessibility rules
At minimum:
- keyboard navigation for all major controls
- clear focus management for approvals and errors
- screen-reader-friendly event summaries
- no critical information conveyed by color alone

## Output contract
When asked for frontend design or implementation guidance, return:
1. **User journey**
2. **UI state model**
3. **Component model**
4. **Event schema**
5. **Receipt and approval design**
6. **Failure and recovery UX**
7. **Accessibility checklist**

## Anti-patterns
Avoid:
- a single scrolling transcript as the only interface
- rendering raw tool logs with no interpretation
- approvals that interrupt without context
- progress indicators that say nothing about what is happening
- ephemeral state that is lost on refresh

## Done criteria
This skill is done only when:
- the UI is modeled as explicit state, not implicit chat
- users can inspect and control risky actions
- provenance and receipts are visible
- reconnect, retry, and failure behavior are designed

