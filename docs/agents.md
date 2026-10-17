# Active agents and deterministic controls

The live workflow creates exactly three LLM agents in `app/agents/__init__.py`:

| Agent | Responsibility | Output |
| --- | --- | --- |
| `diagnosis_agent` | Identify the recurring business break and root-cause hypothesis | Hypothesis, confidence, measured evidence, alternatives |
| `analysis_agent` | Validate the diagnosis against the incident, policy, aggregate metrics, and verified memories | Evidence summary, supported processor, confidence, readiness |
| `evolution_agent` | Propose one bounded, evidence-supported policy change | Parent version, processor, exactly one parameter, rationale, risk |

The former memory-only LLM role is now part of Analysis. Verified memory retrieval
is a deterministic database operation. Unknown memory citations or unsupported
processor claims are rejected. Low-confidence diagnosis or analysis does not
advance to evolution.

Backtesting, scoring, safety guardrails, human approval, promotion, replay,
rollback, and verified-memory writing are controlled workflow operations, not
additional LLM agents. An agent cannot approve its own proposal or alter labels.

Four policy categories are executable: absolute amount tolerance (0–25 cents),
settlement window (0–5 days; business days in the current demo), fixed-fee adjustment (0–100 cents), and
percentage fee (0–300 basis points). Each is processor-scoped. A patch must specify
exactly one parameter and change its existing value. Fee forms are alternatives;
fixed and percentage fees do not stack. Customer, currency, merchant, processor,
reference matching, unique allocation, and promotion guardrails stay fixed.

Python snippet generation/execution, fuzzy reference matching, refund rules, and
group matching remain on hold or drafts. The live workflow never executes source
from the artifact registry.

## Named policy representation

The current runtime baseline is `app/evolution_patches/policies/policy.json`.
It uses `amount_matching`, `settlement`, `fees`, `refunds`, `group_matching`,
`reference_matching`, and `processor_overrides`, with global defaults inherited
by each processor. Old processor-map versions can be read for compatibility;
new versions serialize the named structure only.

The execution engine honors capped absolute/relative tolerances, business or
calendar days, conditional weekend grace, settlement timestamp timezones, fee
treatment, and half-up/half-even rounding. Weekend grace applies only if a
transaction's ledger or settlement date falls on a weekend. Date-only inputs
are already local dates; timestamp inputs are converted to the configured IANA
timezone. Global configuration is validated; current agent proposals remain
limited to one processor override for absolute tolerance, settlement window,
fixed fee, or percentage fee.

Refund/group sections are explicitly disabled and cannot be enabled through this
runtime schema. Reference strategy is exact, and a Python patch cannot be attached
while integration is on hold. These are visible planned configuration sections,
not functioning reconciliation capabilities.

## Policy Update Skill

`app/evolution_patches/policies/policy_skill/SKILL.md` defines the proposal procedure, with typed paths and
limits in `app/evolution_patches/policies/policy_skill/rules.json`. Evolution receives these instructions plus
the current policy, measured incident, complete diagnosis, validated analysis,
aggregate metrics and prior attempts. Analysis receives the read-only rules.
The loader refuses rule/schema drift. The run stores the exact skill snapshot;
policy versions store its ID, version, and SHA-256, and an audit event records when
it was supplied. Editing skill text cannot weaken the backend policy schema,
deterministic guardrails, or human approval requirement. This is a runtime agent
skill, not a Codex installation or a permission to execute arbitrary Python.
