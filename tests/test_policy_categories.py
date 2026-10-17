import unittest
from copy import deepcopy

from app.schemas import MatchingPolicy, PolicyPatch
from app.tools.business import make_match_decision


class PolicyCategoryTests(unittest.TestCase):
    def setUp(self):
        self.ledger = {"customer_id": "C1", "merchant_id": "M1", "processor": "PROC_A",
                       "currency": "USD", "reference": "PAY-123", "amount_cents": 10000,
                       "settlement_date": "2026-10-01"}

    def test_fixed_and_percentage_fees_are_alternatives_never_stacked(self):
        policy = MatchingPolicy()
        policy.processor_fixed_fee_cents['PROC_A'] = 31
        policy.processor_fee_bps['PROC_A'] = 125
        other = deepcopy(self.ledger)
        for net in (10000, 9969, 9875):
            other['amount_cents'] = net
            self.assertEqual(make_match_decision(self.ledger, other, policy)['decision'], 'MATCH')
        other['amount_cents'] = 9844
        self.assertEqual(make_match_decision(self.ledger, other, policy)['decision'], 'BREAK')

    def test_settlement_window_is_scoped_and_does_not_override_identity(self):
        policy = MatchingPolicy()
        policy.processor_settlement_window_days['PROC_A'] = 4
        other = {**self.ledger, 'settlement_date': '2026-10-05'}
        self.assertEqual(make_match_decision(self.ledger, other, policy)['decision'], 'MATCH')
        other['customer_id'] = 'WRONG'
        self.assertEqual(make_match_decision(self.ledger, other, policy)['decision'], 'BREAK')
        other = {**self.ledger, 'processor': 'PROC_B', 'settlement_date': '2026-10-05'}
        ledger = {**self.ledger, 'processor': 'PROC_B'}
        self.assertEqual(make_match_decision(ledger, other, policy)['decision'], 'BREAK')

    def test_caps_and_bundle_prevention(self):
        for kwargs in ({'fixed_fee_cents': 101}, {'fee_bps': 301}, {'settlement_window_days': 6},
                       {'fixed_fee_cents': 31, 'fee_bps': 125}):
            with self.assertRaises(ValueError):
                PolicyPatch(processor='PROC_A', **kwargs)
