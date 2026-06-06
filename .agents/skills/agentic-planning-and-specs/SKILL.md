---
name: agentic-planning-and-specs
description: Plans and specifies production-grade agent systems. Use when scoping work, writing implementation plans, defining state and tool contracts, sequencing milestones, and producing clear done criteria for LLM-driven systems.
argument-hint: "[task]"
allowed-tools: Read Write Edit Grep Glob
---

Produce plans that are concrete enough to implement and specific enough to verify.

The purpose of this skill is to remove ambiguity before expensive coding begins.

## Use this skill when
- the task is large, cross-cutting, or architecture-sensitive
- the request includes "plan", "spec", "design", "roadmap", or "break this down"
- the work touches multiple subsystems across frontend, backend, and agent runtime
- success depends on clearly defined contracts or evaluation gates

## Planning rules
### 1. Start with uncertainty, not confidence
List:
- assumptions
- unknowns
- decisions already made
- decisions still open

If an unknown can invalidate the plan, convert it into a discovery or spike task.

### 2. Define interfaces before implementation
Prefer:
- state schema
- event schema
- tool contracts
- API contracts
- acceptance criteria

before discussing classes, frameworks, or low-level code.

### 3. Keep decomposition shallow and testable
Use 5 to 12 steps if possible.
Each step should have:
- a clear outcome
- a verification method
- dependencies

### 4. Every plan needs gates
Include:
- functional gates
- safety gates
- UX gates
- cost and latency gates

## Standard spec pack
When asked to produce a plan or design for an agentic feature, return:
1. **Scope**
2. **Assumptions and unknowns**
3. **Topology decision**
4. **State schema**
5. **Tool contracts**
6. **Memory and retrieval policy**
7. **Threat model**
8. **Eval plan**
9. **Implementation phases**
10. **Done criteria**

## Section guidance
### Scope
Include:
- goal
- non-goals
- primary user
- constraints
- risk tier

### Assumptions and unknowns
Separate:
- safe assumptions you can proceed with
- blocking unknowns that need user confirmation or discovery work

### Topology decision
State:
- recommended architecture
- two alternatives considered
- why they were rejected

### State schema
Define major fields, ownership, and update triggers.

### Tool contracts
For each tool:
- purpose
- schema
- read/write scope
- retry policy
- approval requirement
- receipt format

### Threat model
At minimum cover:
- prompt injection
- tool misuse
- data leakage
- stale retrieval
- runaway cost or loops

### Eval plan
Include:
- representative tasks
- adversarial tasks
- regression checks
- metrics and thresholds

### Implementation phases
Order work so risk is retired early:
1. design and contracts
2. skeleton runtime
3. tool integration
4. UX and approvals
5. evals and observability
6. hardening and rollout

## Output template
Use this shape:
- **Summary**
- **Scope**
- **Assumptions**
- **Unknowns**
- **Architecture**
- **Contracts**
- **Risks**
- **Phases**
- **Verification**

## Anti-patterns
Avoid:
- implementation plans with no acceptance criteria
- plans that start with framework choices instead of product constraints
- task breakdowns that hide risky unknowns inside later phases
- "we will add tests later"

## Done criteria checklist
- [ ] Scope and non-goals are explicit
- [ ] Topology choice is justified
- [ ] Tool and state contracts are concrete
- [ ] Golden and adversarial evals are defined
- [ ] Each implementation phase has a verification method
- [ ] Cost and latency expectations are stated

