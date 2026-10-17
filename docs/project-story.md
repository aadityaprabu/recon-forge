# ReconForge: Project Story

## Inspiration

Every payment exists twice: once in a company's **internal ledger** and once in the **processor's settlement report**. Reconciliation means proving that those two records describe the same transaction. In practice it's a long, quiet grind. Processors take fees, round in their own way, settle a day or two late, and rewrite references along the way (`PAY-150000` arrives as `pay150000` or `P/150000-SETTLED`). Nothing gives you a shared ID to join on.

Finance teams handle this with rules that someone wrote once and almost never revisits. When a processor starts taking a 3¢ fee, the rules don't adapt. The breaks pile up and people clear them by hand, one case at a time.

LLMs looked like the obvious fix, but I didn't want an AI quietly matching money. What I wanted was a system that **learns from its own breaks, proposes better rules, and still can't promote a change unless a human signs off**. That idea became ReconForge: a reconciliation harness that improves itself inside a fixed safety envelope.

## What it does

ReconForge streams ledger and settlement records into a deterministic matcher, watches for recurring breaks, and runs a bounded agent loop to fix them:

1. **Deterministic matching.** Seven constant business checks (customer, currency, merchant, processor, reference, settlement date, final safety decision) plus **one evolvable policy** decide MATCH or BREAK.
2. **Diagnosis → Analysis → Evolution.** Three LLM agents find the recurring break, validate it against metrics and verified memories, and propose **exactly one** processor-scoped parameter change.
3. **Backtest + guardrails.** The candidate policy is replayed against a protected historical benchmark and must clear fixed vetoes.
4. **Human approval.** A person approves or rejects it. The workflow pauses, saves a checkpoint to MongoDB, and resumes when the decision arrives.
5. **Promotion and replay.** The approved policy is hot-swapped in, open cases are replayed, and the loop keeps running.

On the hard 5,000-record scenario, ten sequential single-field evolutions raise benchmark accuracy from **20% to 70%** in steps of exactly +5 percentage points, with **zero false matches and zero regressions** at every stage.

## How I built it

**Stack:** Python 3.11, FastAPI, Google ADK for the agent workflow, LiteLLM (Gemini or Nicrron), Pydantic v2 for the policy schema, MongoDB for persistence and checkpoints, and a React + Vite dashboard.

### 1. A policy the agents can edit, and code they can't

The main design decision was **7 constant functions + 1 evolvable patch**. Agents can only change a typed, processor-scoped policy with four executable knobs:

| Parameter | Range |
|---|---|
| Absolute amount tolerance | $0$ to $25$ cents |
| Settlement window | $0$ to $5$ business days |
| Fixed fee | $0$ to $100$ cents |
| Percentage fee | $0$ to $300$ bps |

For a ledger amount $g$ (gross, in cents), the engine accepts a settlement amount $s$ if it falls close to one of the allowed forms:

$$
s \in \{\, g,\;\; g - f,\;\; g - \operatorname{round}\!\left(\tfrac{g \cdot b}{10^4}\right) \,\}
$$

where $f$ is the fixed fee and $b$ the fee in basis points. Fees are alternatives and never stack. Rounding is integer-exact, using half-up or half-even, so money never touches floating point.

A **Policy Update Skill** (`SKILL.md` + `rules.json`) tells the Evolution agent how to propose a change. Each policy version records the skill's SHA-256, so every promotion can be traced to the exact instructions the agent received.

### 2. Guardrails no model can touch

Promotion goes through fixed vetoes in `guardrails.py`. A candidate is eligible only if:

$$
\begin{aligned}
n &\ge 1000 \\
\text{FMR}_{\text{cand}} &\le 0.5\% \\
\text{FMR}_{\text{cand}} - \text{FMR}_{\text{base}} &\le 0.1\ \text{pp} \\
\text{high-value false matches} &= 0 \\
\text{regressions} &= 0 \\
\text{AR}_{\text{cand}} - \text{AR}_{\text{base}} &\ge 3\ \text{pp}
\end{aligned}
$$

where FMR is the false-match rate and AR is the correct auto-resolution rate. Even when every check passes, the result is `requires_human: true`. An agent can't approve its own proposal, and it can't see the ground-truth labels.

### 3. The match cascade

Matching runs as a five-step priority cascade, and each settlement can be claimed only once:

```text
① match_by_id → ② match_by_rule → ③ match_by_fuzzy_score → ④ match_by_llm → ⑤ match_by_human
```

The fuzzy step only considers pairs whose hard fields (customer, currency, merchant, processor) are equal. It scores the soft fields:

$$
S = 0.5\,R + 0.3\,A + 0.2\,D
$$

$$
R = \text{SequenceMatcher}(\text{ref}_\ell, \text{ref}_s),\quad
A = \max\!\left(0,\ 1 - \frac{|\Delta_{\text{fee-adj}}|}{25}\right),\quad
D = \max\!\left(0,\ 1 - \frac{|\Delta_{\text{days}}|}{5}\right)
$$

A pair is accepted only when $S \ge 0.95$ **and** it leads the runner-up by at least $0.10$. Records of \$10,000 or more are never fuzzy-paired, and every threshold comes from the active, human-approved policy instead of being hard-coded.

### 4. Durable, resumable workflows

Human approval can take minutes or days, so the workflow had to survive restarts. I wrote a MongoDB-backed ADK session service, a heartbeat-renewed **engine lease** so only one worker drives the loop at a time, and persisted approval signals that resume a paused run from its last checkpoint.

### 5. Datasets designed to be hard

I generated a 5,000-record live stream and an 8,000-record historical benchmark with a seeded generator. Each 500-record phase introduces a new drift (250 drift cases, 50 ordinary matches, 150 hard reference typos that no policy can fix, and 50 negative controls such as currency mismatches, wrong customers, real amount differences, and ambiguous duplicates). The labels live in a protected ground-truth file that the matcher and agents never read.

## Challenges I ran into

**Fuzzy matching almost broke the learning loop.** My first fuzzy matcher auto-resolved pairs, and it quietly matched **1,068 fee cases**. That looked like a win until I noticed what it did to the loop:

```text
fuzzy silently matches every 3¢ fee case
  → no AMOUNT_MISMATCH breaks remain
  → no incident is detected
  → agents never run
  → no rule is ever proposed or approved
```

It had also accepted gaps of up to 25¢ that no human had approved. The fix was to treat fuzzy output as **evidence, not a decision**. A fuzzy pair keeps the case open, attaches the likely partner and measured deltas, and lets the AI explain the pattern ("312 PROC_C pairs are 3¢ short and 1 day late"), which then goes through backtest and approval.

**A relative tolerance that wasn't safe.** The first fuzzy version scored amount closeness relative to 1% of the payment, so on a \$260 payment a 50¢ gap looked "close." That produced **20 wrong pairs**, and every one was a real mismatch. Capping the gap at the policy's 25¢ ceiling brought wrong pairs down to **zero** (862/862 correct on historical data, 320/320 on live data). The 25¢ cap was chosen after seeing this dataset, so I treat that result as optimistic. It does have an independent justification, though: 25¢ is the existing policy ceiling.

**Stopping the LLM from being clever.** Early proposals bundled several edits, invented processors, cited memories that didn't exist, or proposed no-op versions. I added layered rejection: a typed schema, exactly one changed leaf, range limits, maximum jump sizes, verified-memory citations, and a confidence floor before evolution can run. In the end it was the deterministic code that made the agents trustworthy.

**Fair evaluation over time.** The live accuracy number moves around as new phases arrive, so I added a separate chart that scores every approved version against the same fixed 8,000-record benchmark. That way improvements are measured, not just felt.

**Honest numbers.** It was tempting to make the curve look good. I chose to report unresolved hard reference cases as unresolved, label pending results as pending, and list the caveats right next to the wins.

## What I learned

- **Where to put the LLM matters more than which LLM.** The agents are good at explaining patterns and proposing a hypothesis. Matching, scoring, and safety work best as deterministic code.
- **Self-improving systems need a reason to keep improving.** If you auto-fix the symptoms, the system loses the signal it learns from. Leaving cases open as evidence keeps the loop alive.
- **Bounded evolution scales.** Changing one parameter at a time, with backtesting and a person approving each step, makes every gain auditable, and each one can be rolled back.
- **Financial correctness is all about the details:** integer cents, explicit rounding modes, timezone-aware settlement dates, business-day windows, and one-to-one allocation.
- **Durable agent workflows are a systems problem.** Leases, checkpoints, and idempotent seeding mattered as much as the prompts did.

## What's next

- Promote fuzzy reference recovery from draft to a policy-controlled capability, so the hard reference-typo cases can be resolved.
- Refund and group (one-to-many) matching, which already exist in the schema but are disabled.
- Hand drift detection off to the agents automatically when a new processor behavior appears, with rollback triggered by post-promotion monitoring.
