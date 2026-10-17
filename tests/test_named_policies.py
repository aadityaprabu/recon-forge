import unittest

from app.schemas import Policy, EvolutionResult, apply_patch
from app.tools.business import make_match_decision


class NamedPolicyTests(unittest.TestCase):
    def test_four_named_processors_and_square_patch(self):
        policy = Policy(version="p1")
        self.assertEqual(policy.processor_names, {"PROC_A": "Stripe", "PROC_B": "Adyen", "PROC_C": "PayPal", "PROC_D": "Square"})
        proposal = EvolutionResult(parent_version="p1", candidate_patch={"processor": "PROC_D", "fixed_fee_cents": 43},
                                   reason="Square fee", expected_effect="recover net settlements", risk="false matches")
        candidate = apply_patch(policy, proposal, "p2")
        self.assertEqual(candidate.matching.processor_fixed_fee_cents["PROC_D"], 43)
        self.assertTrue(all(candidate.matching.processor_fixed_fee_cents[p] == 0 for p in ("PROC_A", "PROC_B", "PROC_C")))

    def setUp(self):
        self.row = {"customer_id": "C1", "merchant_id": "M1", "processor": "PROC_A",
                    "currency": "USD", "reference": "PAY-123", "amount_cents": 10000,
                    "settlement_date": "2026-10-02"}

    def test_named_defaults_and_sparse_processor_override(self):
        policy = Policy(version="p1", amount_matching={"absolute_tolerance_cents": 2},
                        processor_overrides={"PROC_B": {"amount_matching": {"absolute_tolerance_cents": 3}}})
        self.assertEqual(policy.matching.processor_amount_tolerance_cents, {"PROC_A": 2, "PROC_B": 3, "PROC_C": 2, "PROC_D": 2})
        proposal = EvolutionResult(parent_version="p1", candidate_patch={"processor": "PROC_A", "fixed_fee_cents": 31},
                                   reason="observed fee", expected_effect="recover net settlements", risk="false matches")
        candidate = apply_patch(policy, proposal, "p2")
        saved = candidate.model_dump()
        self.assertNotIn("matching", saved)
        self.assertEqual(saved["processor_overrides"]["PROC_A"]["fees"]["fixed_fee_cents"], 31)
        self.assertEqual(candidate.amount_matching, policy.amount_matching)
        self.assertEqual(Policy.model_validate(saved), candidate)

    def test_relative_tolerance_respects_fixed_maximum(self):
        policy = Policy(version="p1", amount_matching={"relative_tolerance_bps": 25, "maximum_tolerance_cents": 25})
        for delta, decision in ((25, "MATCH"), (26, "BREAK")):
            other = {**self.row, "amount_cents": 10000 - delta}
            self.assertEqual(make_match_decision(self.row, other, policy.matching)["decision"], decision)

    def test_business_day_window_and_weekend_grace(self):
        policy = Policy(version="p1", settlement={"day_basis": "business", "window_business_days": 1})
        monday = {**self.row, "settlement_date": "2026-10-05"}
        self.assertEqual(make_match_decision(self.row, monday, policy.matching)["decision"], "MATCH")
        tuesday = {**self.row, "settlement_date": "2026-10-06"}
        self.assertEqual(make_match_decision(self.row, tuesday, policy.matching)["decision"], "BREAK")
        sunday = {**self.row, "settlement_date": "2026-10-04"}
        calendar = Policy(version="p2", settlement={"day_basis": "calendar", "window_business_days": 1,
                                                     "weekend_grace_days": 1})
        self.assertEqual(make_match_decision(self.row, sunday, calendar.matching)["decision"], "MATCH")

    def test_rounding_and_fee_treatment_are_executed(self):
        row = {**self.row, "amount_cents": 100}
        other = {**row, "amount_cents": 99}
        even = Policy(version="p1", fees={"percentage_bps": 50, "rounding": "half_even"})
        up = Policy(version="p2", fees={"percentage_bps": 50, "rounding": "half_up"})
        gross = Policy(version="p3", fees={"percentage_bps": 50, "rounding": "half_up", "treatment": "gross_only"})
        self.assertEqual(make_match_decision(row, other, even.matching)["decision"], "BREAK")
        self.assertEqual(make_match_decision(row, other, up.matching)["decision"], "MATCH")
        self.assertEqual(make_match_decision(row, other, gross.matching)["decision"], "BREAK")

    def test_timezone_and_disabled_capabilities(self):
        policy = Policy(version="p1", settlement={"window_business_days": 0, "timezone": "America/New_York"})
        a = {**self.row, "settlement_date": "2026-10-03T00:30:00+00:00"}
        b = {**self.row, "settlement_date": "2026-10-02"}
        self.assertEqual(make_match_decision(a, b, policy.matching)["decision"], "MATCH")
        for data in ({"refunds": {"enabled": True}}, {"group_matching": {"enabled": True}},
                     {"reference_matching": {"strategy": "exact_then_fuzzy"}},
                     {"settlement": {"timezone": "invalid-zone"}}):
            with self.assertRaises(ValueError):
                Policy(version="bad", **data)

    def test_legacy_versions_load_without_duplicated_serialized_maps(self):
        legacy = Policy(version="old", matching={"processor_amount_tolerance_cents": {"PROC_A": 1, "PROC_B": 0, "PROC_C": 0}})
        self.assertEqual(legacy.matching.processor_amount_tolerance_cents['PROC_A'], 1)
        self.assertEqual(legacy.settlement.day_basis, "calendar")
        self.assertNotIn("matching", legacy.model_dump())
