# Evolution patches

```text
evolution_patches/
  manifest.json
  policies/
    policy.json                  # Latest runtime baseline
    policy_skill/
      SKILL.md                   # Policy update procedure
      rules.json                 # Allowed parameters and limits
      __init__.py                # Rule/schema validation and skill fingerprint
  python_code/
    reference_similarity_v1.py    # Draft; integration on hold
```

Only the latest baseline is kept locally as `policies/policy.json`; older local
policy JSON files have been removed. MongoDB version history is retained.

The policy names four synthetic processors: Stripe, Adyen, PayPal, and Square.
Stable internal IDs are PROC_A through PROC_D. These labels do not imply live
provider integrations. Policies use named amount, settlement and fee rules with
inherited defaults and individual processor overrides. Refund/group matching are
disabled; references are exact and Python/fuzzy evolution is on hold.

The Evolution agent reads `policy_skill/SKILL.md`, `rules.json`, the current policy,
the Diagnosis report, and the Analysis report to propose a new version. It changes
one supported parameter at a time. Skill/schema drift, bundled edits, stale parent
versions, and no-ops are rejected. The run records the exact skill snapshot and
hash; the policy version records that skill's identity. The agent cannot edit its
own skill, weaken guardrails, or activate a candidate without human approval.

`reconforge_policy_skill_demo.evolution_patch_versions` archives local artifacts
with content, SHA-256, version, parent, status and original source path. Moving an
unchanged file does not create a different content version. Historical source
paths may refer to files that no longer exist locally; their source content remains
in MongoDB. Run `python -m scripts.seed_patches` to seed the current local artifacts.

`harness_policies` stores runtime versions and their promotion status. The `control`
active-policy pointer is authoritative for live execution. Approvals, evaluations,
and rollback records are retained in their existing collections. Local `policy.json`
is the baseline; approved runtime changes are new MongoDB versions rather than
silent edits to that file. See the repository's `docs/agents.md` and `docs/scale5000.md`.
