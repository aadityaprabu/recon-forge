"""Offline evidence-driven validation; does not create approvals or promote policies."""
import json

from app.config import ROOT
from app.demo.generator import Dataset
from app.schemas import Policy, EvolutionResult, apply_patch
from app.tools.analytics import detect_incidents
from app.tools.backtester import compare
from app.tools.guardrails import decide
from app.tools.matcher import match


def verify(dataset):
    def flatten(value, prefix=""):
        result = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(item, dict):
                result.update(flatten(item, path))
            else:
                result[path] = item
        return result
    historical = (*dataset.business("historical"), dataset.load("historical_ground_truth"))
    live = (*dataset.business("live"), dataset.load("live_ground_truth"))
    policy = dataset.baseline()
    steps = []
    for phase in range(10):
        position = (phase + 1) * 500
        incidents = detect_incidents(match(live[0][:position], live[1][:position], policy.matching)["cases"])
        assert len(incidents) == 1, f"Phase {phase + 1} must expose one actionable incident"
        incident = incidents[0]
        value = incident["suggested_value"]
        proposal = EvolutionResult(parent_version=policy.version,
            candidate_patch={"processor": incident["processor"], incident["patch_field"]: value},
            reason="Offline measured-incident validation", expected_effect="Resolve one cluster", risk="False matches",
            required_eval_slices=[])
        candidate = apply_patch(policy, proposal, f"scale-validation-v{phase + 1}")
        before = policy.matching.model_dump()
        after = candidate.matching.model_dump()
        old_leaves = flatten(policy.model_dump(exclude={"version", "parent"}))
        new_leaves = flatten(candidate.model_dump(exclude={"version", "parent"}))
        changed = [path for path in old_leaves.keys() | new_leaves.keys() if old_leaves.get(path) != new_leaves.get(path)]
        assert len(changed) == 1
        _, field, _ = proposal.candidate_patch.change()
        evaluation = compare(policy, candidate, *historical)
        gate = decide(evaluation)
        assert gate["passed"], f"Phase {phase + 1}: {gate['reasons']}"
        held_out = compare(policy, candidate, *live)
        assert decide(held_out, require_improvement=False)["passed"]
        steps.append({"phase": phase + 1, "stream_position": position,
                      "field": changed[0],
                      "before": before[field][incident["processor"]], "after": value,
                      "changed_fields": 1, "backtest_records": evaluation["candidate"]["sample_size"],
                      "auto_resolution_gain_pp": round(100 * (evaluation["candidate"]["auto_resolution_rate"] - evaluation["baseline"]["auto_resolution_rate"]), 3),
                      "accuracy_before": round(100 * evaluation["baseline"]["accuracy"], 3),
                      "accuracy_after": round(100 * evaluation["candidate"]["accuracy"], 3),
                      "accuracy_gain_pp": round(100 * (evaluation["candidate"]["accuracy"] - evaluation["baseline"]["accuracy"]), 3),
                      "held_out_accuracy_after": round(100 * held_out["candidate"]["accuracy"], 3),
                      "false_matches": evaluation["candidate"]["false_auto"],
                      "held_out_false_matches": held_out["candidate"]["false_auto"],
                      "guardrails_passed": gate["passed"]})
        policy = candidate
    assert [s["accuracy_after"] for s in steps] == list(range(25, 71, 5))
    assert [s["held_out_accuracy_after"] for s in steps] == list(range(25, 71, 5))
    remaining = detect_incidents(match(live[0], live[1], policy.matching)["cases"])
    assert not remaining, "All ten targeted clusters should be resolved"
    return {"mode": "OFFLINE_VALIDATION_NOT_PRODUCTION_PROMOTIONS", "live_records": len(live[0]),
            "historical_records": len(historical[0]), "validated_evolutions": len(steps), "steps": steps}


if __name__ == "__main__":
    result = verify(Dataset(ROOT / "ReconForge_Scale5000_Dataset"))
    path = ROOT / "docs" / "scale5000_validation.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Verified {result['validated_evolutions']} single-field evolutions across {result['live_records']} live records; report: {path}")
