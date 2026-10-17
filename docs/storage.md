# Long-horizon storage

Active database: `reconforge_long_horizon`. Previous databases are preserved.

## Durable collections

| Collection | Purpose |
| --- | --- |
| control | Active policy, stream cursor, dataset fingerprint, engine lease/settings |
| harness_policies | Runtime policy versions, parent links, compact benchmarks and provenance |
| evolution_patch_versions | Immutable baseline/policy artifact contents and hashes; no inactive Python drafts |
| workflow_runs | Diagnosis, analysis, skill snapshot, proposed change and final outcome |
| human_approvals | Idempotent human approval/rejection decisions |
| policy_evaluations | Backtest and replay results used by promotion/rollback guards |
| incident_memories | Verified learning reused by future agents |
| reconciliation_cases | Latest reconciliation result per ingested transaction |
| case_events | Initial outcomes and actual status changes; no unchanged-policy churn |
| agent_action_logs | Workflow stage, promotion, rollback and learning audit |

## Temporary operational data

`metric_snapshots` and `evaluator_decisions` expire after seven days.
Consumed `doorbell_events` expire seven days after consumption; pending signals do not expire.
`adk_sessions` and `adk_events` expire seven days after a workflow reaches COMPLETED, REJECTED or ROLLED_BACK. Pending/error workflows retain their replay checkpoints. ADK scope state is stored only if the framework writes scoped state.

TTL indexes use BSON dates. MongoDB performs expiry asynchronously. Durable policy, approval, evaluation, memory and audit collections have no TTL.

## Local data

Historical/live ledger rows, settlements and ground-truth labels stay in the selected local dataset directory. MongoDB stores no `internal_ledger`, `processor_settlement`, `ground_truth` or `evaluation_corpora` copies. The saved dataset fingerprint prevents silently switching fixture contents in the same database. Preserve the local dataset for reproducible evaluation and restart. Agents receive business evidence, never the evaluator labels.

Ingestion advances an independently leased cursor over the immutable local fixture, regardless of human approval. New database setup is a fresh stream, not a migration of earlier workflows or memories.
