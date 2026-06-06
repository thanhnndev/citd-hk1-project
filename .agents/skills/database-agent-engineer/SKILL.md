---
name: database-agent-engineer
description: Database engineering skill for agentic systems. Use for schema design, migrations, query correctness, performance, transactions, multi-tenant boundaries, privacy, backups/rollback, and safe DB operations.
argument-hint: "[database/task]"
allowed-tools: Read Write Edit Bash Grep Glob
---

Build database changes as **auditable, reversible, and verified** operations.

## Non-negotiable behavior
- Do not assume schema, indexes, or constraints. **Verify** by reading migrations/schema files or introspecting the DB when available.
- Do not guess query plans or performance. **Verify** with `EXPLAIN` / `EXPLAIN ANALYZE` when possible.
- Do not propose destructive operations without a rollback and explicit approval.
- Separate **facts** (schema, constraints, measured plans) from **hypotheses** (suspected bottlenecks).

## Use this skill when
- designing tables, relations, constraints, or indexes
- planning or reviewing migrations
- writing SQL queries or query builders
- debugging performance issues
- enforcing tenancy, privacy, and access boundaries in data models
- adding audit logs, soft deletes, retention, or compliance controls

## Database design priorities (agentic products)
Agentic products tend to need:
- **run and step logs** (replayable traces)
- **tool receipts** (what changed / where / why)
- **artifacts** (plans, outputs, generated files)
- **approvals** (requested/approved/denied with scope)
- **eval results** (golden/adversarial/regression history)

Your schema should support:
- correct querying at scale
- isolation across tenants/users
- cost-effective retention (hot vs cold storage)
- legal/compliance deletion and export paths

## Procedure: schema or migration work
### 1. Establish ground truth
Collect:
- existing schema (DDL or ORM models)
- current migrations
- data volume estimates (rows, growth)
- access patterns (reads/writes, most frequent queries)
- privacy requirements (PII fields, retention, redaction)
- tenancy model (single-tenant vs multi-tenant)

If you cannot access an actual DB, state the limitation and proceed with file-based verification only.

### 2. Define the data contract
For each entity/table:
- primary key strategy
- required fields and nullability
- uniqueness rules
- foreign keys and cascade strategy
- soft delete strategy (if any)
- timestamps and ordering fields
- audit fields (who/what/when)

### 3. Design for access patterns
For each top query:
- write the query shape
- decide required indexes
- choose covering vs selective indexes
- decide partitioning strategy if needed

### 4. Plan migrations safely
For each migration:
- classify: additive / backfill / constraint / destructive
- ensure idempotency where feasible
- ensure backward compatibility across deploys when needed
- add a rollback path (down migration or compensating migration)

#### Safe migration patterns
- Add new nullable column → backfill in batches → add constraint/default → flip reads/writes → remove old column later.
- Create index concurrently (where supported) to reduce lock impact.
- Introduce new table + dual write → migrate reads → remove old path.

### 5. Transactions and consistency
Be explicit about:
- transaction boundaries
- isolation needs
- idempotency keys for side effects
- uniqueness constraints that enforce invariants (not just app code)

### 6. Multi-tenant and privacy boundaries
If multi-tenant:
- include `tenant_id` on every tenant-scoped table
- enforce tenant scoping in queries (and ideally in DB constraints/policies when available)
- avoid cross-tenant joins unless explicitly required and audited

For privacy:
- separate PII fields when helpful
- minimize indexing on sensitive fields
- define retention and deletion behavior

### 7. Verification checklist (must do)
- Validate schema changes against the existing models/migrations.
- Validate queries against real or representative schema.
- For performance changes, provide `EXPLAIN` results or clearly state when unavailable.
- Ensure roll-forward and rollback procedures exist.
- Ensure invariants are enforced by constraints where appropriate.

## Query review checklist
- Correctness: joins, filters, null semantics
- Tenancy: `tenant_id` scoping present and indexed
- Safety: no SQL injection, parameters used
- Performance: index usage, avoid N+1 patterns
- Locking: avoid long transactions; beware `SELECT ... FOR UPDATE` blast radius
- Pagination: stable ordering; no offset pitfalls at scale (prefer keyset pagination)

## Recommended schemas for agentic systems (templates)
If relevant, propose tables like:
- `runs`: one row per user-visible run
- `run_steps`: one row per step with state transitions
- `tool_calls`: tool name, validated args summary, timings, errors
- `tool_receipts`: what changed/where/why/next + artifact pointers
- `approvals`: requested action, scope, decision, approver, expiry
- `artifacts`: blobs/paths, provenance, retention policy
- `eval_runs`: eval suite runs + metrics + thresholds

## Output contract
When asked for DB work, return:
1. **Verified facts** (schema, constraints, observed plans)
2. **Proposed change** (DDL/migration steps)
3. **Why** (access patterns + invariants)
4. **Risk analysis** (locks, backfill cost, downtime risk)
5. **Rollback plan**
6. **Verification plan** (queries, explain, tests)

## Stop conditions
Stop and require explicit approval before:
- dropping columns/tables or destructive backfills
- long-running migrations in production
- changing retention/deletion semantics
- exporting or touching sensitive data

